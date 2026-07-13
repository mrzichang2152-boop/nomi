from __future__ import annotations

import threading
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")

from app.attachments.models import AttachmentLimits, DEFAULT_ATTACHMENT_ONLY_INSTRUCTION
from app.attachments.service import AttachmentSubmissionError, AttachmentSubmissionService


NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


@dataclass
class Draft:
    attachment_id: UUID
    status: str = "ready"
    lifecycle: str = "draft"
    byte_size: int = 100
    expires_at: Optional[datetime] = NOW + timedelta(hours=1)
    attached_at: Optional[datetime] = None


class Cursor:
    def __init__(self, rows: Optional[list[tuple[Any, ...]]] = None, rowcount: int = 0):
        self.rows = rows or []
        self.rowcount = rowcount

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class SharedStore:
    def __init__(self):
        self.attachments: dict[UUID, Draft] = {}
        self.turns: dict[str, dict[str, Any]] = {}
        self.turns_by_tool_call: dict[str, str] = {}
        self.bindings: dict[str, list[UUID]] = {}
        self.lock = threading.RLock()

    def seed(
        self,
        *,
        status: str = "ready",
        lifecycle: str = "draft",
        byte_size: int = 100,
        expires_at: Optional[datetime] = NOW + timedelta(hours=1),
    ) -> Draft:
        draft = Draft(
            attachment_id=uuid4(),
            status=status,
            lifecycle=lifecycle,
            byte_size=byte_size,
            expires_at=expires_at,
        )
        self.attachments[draft.attachment_id] = draft
        return draft


class FakeConnection:
    def __init__(self, store: SharedStore):
        self.store = store

    def __enter__(self):
        self.store.lock.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.store.lock.release()
        return False

    def execute(self, sql: str, params=()):
        normalized = " ".join(sql.split()).lower()
        if "from assistant_turns" in normalized and "tool_call_id" in normalized:
            tool_call_id = str(params[0])
            turn_id = self.store.turns_by_tool_call.get(tool_call_id)
            if not turn_id:
                return Cursor()
            turn = self.store.turns[turn_id]
            return Cursor(
                [
                    (
                        turn_id,
                        turn["conversation_id"],
                        turn["event_id"],
                        "user",
                        turn["content"],
                    )
                ]
            )
        if "from assistant_turn_attachments" in normalized and "order by ordinal" in normalized:
            turn_id = str(params[0])
            return Cursor([(attachment_id,) for attachment_id in self.store.bindings.get(turn_id, [])])
        if "from chat_attachments" in normalized and "for update" in normalized:
            requested = [UUID(str(value)) for value in params[0]]
            rows = []
            for attachment_id in requested:
                draft = self.store.attachments.get(attachment_id)
                if draft is not None:
                    rows.append(
                        (
                            draft.attachment_id,
                            draft.status,
                            draft.lifecycle,
                            draft.byte_size,
                            draft.expires_at,
                        )
                    )
            return Cursor(rows)
        if normalized.startswith("insert into assistant_turn_attachments"):
            turn_id, attachment_id, ordinal = params[:3]
            ordered = self.store.bindings.setdefault(str(turn_id), [])
            assert int(ordinal) == len(ordered)
            ordered.append(UUID(str(attachment_id)))
            return Cursor(rowcount=1)
        if normalized.startswith("update chat_attachments"):
            attached_at, attachment_id = params
            draft = self.store.attachments[UUID(str(attachment_id))]
            if draft.lifecycle != "draft":
                return Cursor(rowcount=0)
            draft.lifecycle = "attached"
            draft.attached_at = attached_at
            draft.expires_at = None
            return Cursor(rowcount=1)
        raise AssertionError(f"unexpected SQL: {normalized}")


def persist_turn(store: SharedStore):
    def persist(
        conn,
        redis_obj,
        *,
        role,
        content,
        conversation_id,
        client_type,
        tool_call_id,
        **kwargs,
    ):
        assert role == "user"
        turn_id = str(uuid4())
        event_id = str(uuid4())
        resolved_conversation_id = conversation_id or str(uuid4())
        store.turns[turn_id] = {
            "turn_id": turn_id,
            "event_id": event_id,
            "conversation_id": resolved_conversation_id,
            "content": content,
            "client_type": client_type,
        }
        if tool_call_id:
            store.turns_by_tool_call[tool_call_id] = turn_id
        return {
            "turn_id": turn_id,
            "event_id": event_id,
            "conversation_id": resolved_conversation_id,
            "role": role,
        }

    return persist


@pytest.fixture
def store():
    return SharedStore()


@pytest.fixture
def submission():
    return AttachmentSubmissionService(now=lambda: NOW)


def submit(
    submission: AttachmentSubmissionService,
    store: SharedStore,
    *,
    message: str = "分析这些文件",
    attachments: Optional[list[UUID]] = None,
    request_id: Optional[str] = "request-1",
):
    with FakeConnection(store) as conn:
        return submission.submit_user_turn(
            conn=conn,
            redis_obj=None,
            message=message,
            attachment_ids=attachments or [],
            conversation_id="conversation-1",
            client_type="android",
            client_request_id=request_id,
            user_tool_call_id=f"chat:user:{request_id}" if request_id else None,
            persist_turn=persist_turn(store),
        )


def test_attachment_only_uses_default_instruction_and_binds_once(store, submission):
    draft = store.seed()

    result = submit(submission, store, message="", attachments=[draft.attachment_id])

    assert result["content"] == DEFAULT_ATTACHMENT_ONLY_INSTRUCTION
    assert result["attachment_ids"] == [str(draft.attachment_id)]
    assert store.turns[result["turn_id"]]["content"] == DEFAULT_ATTACHMENT_ONLY_INSTRUCTION
    assert store.bindings[result["turn_id"]] == [draft.attachment_id]
    assert draft.lifecycle == "attached"
    assert draft.expires_at is None


def test_mixed_message_preserves_text_and_attachment_order(store, submission):
    first = store.seed()
    second = store.seed()

    result = submit(
        submission,
        store,
        message="比较两份材料",
        attachments=[second.attachment_id, first.attachment_id],
    )

    assert result["content"] == "比较两份材料"
    assert result["attachment_ids"] == [str(second.attachment_id), str(first.attachment_id)]
    assert store.bindings[result["turn_id"]] == [second.attachment_id, first.attachment_id]


@pytest.mark.parametrize(
    ("message", "attachments", "expected_code"),
    [
        ("", [], "message_or_attachment_required"),
        ("分析", [UUID(int=1), UUID(int=1)], "duplicate_attachment_id"),
        ("分析", [UUID(int=value) for value in range(1, 10)], "too_many_attachments"),
    ],
)
def test_rejects_invalid_message_level_input_without_turn(
    store, submission, message, attachments, expected_code
):
    with pytest.raises(AttachmentSubmissionError) as error:
        submit(submission, store, message=message, attachments=attachments)

    assert error.value.code == expected_code
    assert store.turns == {}
    assert store.bindings == {}


def test_rejects_aggregate_limit_before_persisting_turn(store):
    submission = AttachmentSubmissionService(
        limits=AttachmentLimits(max_message_attachment_bytes=150),
        now=lambda: NOW,
    )
    first = store.seed(byte_size=100)
    second = store.seed(byte_size=60)

    with pytest.raises(AttachmentSubmissionError) as error:
        submit(submission, store, attachments=[first.attachment_id, second.attachment_id])

    assert error.value.code == "attachments_too_large"
    assert error.value.http_status == 413
    assert store.turns == {}


def test_rejects_malformed_attachment_id_with_stable_error(store, submission):
    with pytest.raises(AttachmentSubmissionError) as error:
        submit(submission, store, attachments=["not-a-uuid"])  # type: ignore[list-item]

    assert error.value.code == "invalid_attachment_id"
    assert error.value.http_status == 422
    assert store.turns == {}


@pytest.mark.parametrize(
    ("seed_kwargs", "expected_code", "expected_status"),
    [
        ({"status": "processing"}, "attachment_not_ready", 409),
        ({"status": "failed"}, "attachment_not_ready", 409),
        ({"lifecycle": "deleted"}, "attachment_not_found", 404),
        ({"lifecycle": "attached"}, "attachment_already_attached", 409),
        ({"expires_at": NOW - timedelta(seconds=1)}, "attachment_expired", 410),
    ],
)
def test_rejects_unusable_attachment_without_turn(
    store, submission, seed_kwargs, expected_code, expected_status
):
    draft = store.seed(**seed_kwargs)

    with pytest.raises(AttachmentSubmissionError) as error:
        submit(submission, store, attachments=[draft.attachment_id])

    assert error.value.code == expected_code
    assert error.value.http_status == expected_status
    assert store.turns == {}
    assert store.bindings == {}


def test_one_invalid_attachment_prevents_all_turn_and_binding_writes(store, submission):
    ready = store.seed()
    failed = store.seed(status="failed")

    with pytest.raises(AttachmentSubmissionError) as error:
        submit(submission, store, attachments=[ready.attachment_id, failed.attachment_id])

    assert error.value.code == "attachment_not_ready"
    assert store.turns == {}
    assert store.bindings == {}
    assert ready.lifecycle == "draft"


def test_missing_attachment_is_reported_before_turn_creation(store, submission):
    missing = uuid4()

    with pytest.raises(AttachmentSubmissionError) as error:
        submit(submission, store, attachments=[missing])

    assert error.value.code == "attachment_not_found"
    assert store.turns == {}


def test_repeated_client_request_id_returns_same_turn_and_bindings(store, submission):
    draft = store.seed()

    first = submit(submission, store, attachments=[draft.attachment_id], request_id="stable-1")
    second = submit(submission, store, attachments=[draft.attachment_id], request_id="stable-1")

    assert second["turn_id"] == first["turn_id"]
    assert second["duplicate"] is True
    assert len(store.turns) == 1
    assert store.bindings[first["turn_id"]] == [draft.attachment_id]


def test_reused_client_request_id_with_different_attachments_is_conflict(store, submission):
    first_draft = store.seed()
    second_draft = store.seed()
    submit(submission, store, attachments=[first_draft.attachment_id], request_id="stable-2")

    with pytest.raises(AttachmentSubmissionError) as error:
        submit(submission, store, attachments=[second_draft.attachment_id], request_id="stable-2")

    assert error.value.code == "client_request_id_conflict"
    assert second_draft.lifecycle == "draft"
    assert len(store.turns) == 1


def test_concurrent_submission_of_same_draft_allows_exactly_one_turn(store, submission):
    draft = store.seed()
    barrier = threading.Barrier(2)
    results: list[dict[str, Any]] = []
    errors: list[str] = []

    def worker(request_id: str):
        barrier.wait()
        try:
            results.append(
                submit(submission, store, attachments=[draft.attachment_id], request_id=request_id)
            )
        except AttachmentSubmissionError as exc:
            errors.append(exc.code)

    threads = [
        threading.Thread(target=worker, args=("parallel-1",)),
        threading.Thread(target=worker, args=("parallel-2",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert len(results) == 1
    assert errors == ["attachment_already_attached"]
    assert len(store.turns) == 1
    assert draft.lifecycle == "attached"
