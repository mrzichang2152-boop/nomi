from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


from app.attachments.repository import (
    AttachmentCleanupOutboxRecord,
    delete_conversation_with_attachment_cleanup,
    load_public_attachments_for_turns,
    load_retryable_user_turn,
)
from app.attachments.schema import attachment_schema_sql
from app.attachments.worker import AttachmentOutboxCleaner


NOW = datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc)
CONVERSATION_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_CONVERSATION_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
USER_TURN_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
ASSISTANT_TURN_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
FIRST_ATTACHMENT_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
SECOND_ATTACHMENT_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")


class Cursor:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None, rowcount: int = 0):
        self.rows = rows or []
        self.rowcount = rowcount

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


def public_attachment_rows(turn_id: uuid.UUID = USER_TURN_ID) -> list[tuple[Any, ...]]:
    return [
        (
            turn_id,
            0,
            FIRST_ATTACHMENT_ID,
            "架构图.png",
            "image/png",
            None,
            431551,
            "ready",
            "attached",
            "image",
        ),
        (
            turn_id,
            1,
            SECOND_ATTACHMENT_ID,
            "需求说明.pdf",
            "application/pdf",
            None,
            912000,
            "ready",
            "attached",
            "pdf",
        ),
    ]


def test_history_metadata_is_batch_loaded_in_user_order_without_private_fields():
    calls: list[tuple[str, tuple[Any, ...]]] = []

    class Conn:
        def execute(self, sql: str, params=()):
            calls.append((" ".join(sql.split()).lower(), tuple(params)))
            return Cursor(public_attachment_rows())

    result = load_public_attachments_for_turns(Conn(), [USER_TURN_ID, ASSISTANT_TURN_ID])

    assert len(calls) == 1
    assert "= any(%s)" in calls[0][0]
    assert list(result) == [str(USER_TURN_ID)]
    assert [item["attachment_id"] for item in result[str(USER_TURN_ID)]] == [
        str(FIRST_ATTACHMENT_ID),
        str(SECOND_ATTACHMENT_ID),
    ]
    assert result[str(USER_TURN_ID)][0] == {
        "attachment_id": str(FIRST_ATTACHMENT_ID),
        "ordinal": 0,
        "filename": "架构图.png",
        "mime_type": "image/png",
        "byte_size": 431551,
        "status": "ready",
        "kind": "image",
        "preview_url": f"/api/chat/attachments/{FIRST_ATTACHMENT_ID}/preview",
        "content_url": f"/api/chat/attachments/{FIRST_ATTACHMENT_ID}/content",
    }
    assert "storage_relative_path" not in repr(result)
    assert "sha256" not in repr(result)


def test_empty_history_does_not_issue_attachment_query():
    class Conn:
        def execute(self, sql: str, params=()):
            raise AssertionError("empty turn collection must not query attachments")

    assert load_public_attachments_for_turns(Conn(), []) == {}


def test_history_endpoint_keeps_stable_ids_and_only_decorates_bound_user_turn(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed: list[str] = []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql: str, params=()):
            normalized = " ".join(sql.split()).lower()
            executed.append(normalized)
            if "from assistant_turns" in normalized and "recent_turns" in normalized:
                return Cursor(
                    [
                        (
                            USER_TURN_ID,
                            CONVERSATION_ID,
                            "user",
                            "请比较附件",
                            uuid.uuid4(),
                            None,
                            None,
                            NOW,
                            None,
                        ),
                        (
                            ASSISTANT_TURN_ID,
                            CONVERSATION_ID,
                            "assistant",
                            "模型暂时不可用，请重试。",
                            uuid.uuid4(),
                            None,
                            None,
                            NOW,
                            NOW,
                        ),
                    ]
                )
            if "from assistant_turn_attachments" in normalized:
                return Cursor(public_attachment_rows())
            raise AssertionError(f"unexpected SQL: {normalized}")

    monkeypatch.setattr(main, "db", lambda: Conn())
    client = TestClient(main.app)
    first = client.get(
        f"/api/chat/history?conversation_id={CONVERSATION_ID}",
        headers={"x-par-password": "secret"},
    )
    second = client.get(
        f"/api/chat/history?conversation_id={CONVERSATION_ID}",
        headers={"x-par-password": "secret"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert [item["id"] for item in first.json()["messages"]] == [
        str(USER_TURN_ID),
        str(ASSISTANT_TURN_ID),
    ]
    assert [item["id"] for item in second.json()["messages"]] == [
        str(USER_TURN_ID),
        str(ASSISTANT_TURN_ID),
    ]
    assert [item["attachment_id"] for item in first.json()["messages"][0]["attachments"]] == [
        str(FIRST_ATTACHMENT_ID),
        str(SECOND_ATTACHMENT_ID),
    ]
    assert "attachments" not in first.json()["messages"][1]
    assert sum("from assistant_turn_attachments" in sql for sql in executed) == 2


def test_retry_target_uses_original_user_turn_and_bound_attachment_order():
    executed: list[str] = []

    class Conn:
        def execute(self, sql: str, params=()):
            normalized = " ".join(sql.split()).lower()
            executed.append(normalized)
            if "from assistant_turns" in normalized:
                return Cursor(
                    [
                        (
                            USER_TURN_ID,
                            CONVERSATION_ID,
                            "user",
                            "请比较附件",
                            uuid.uuid4(),
                            NOW,
                        )
                    ]
                )
            if "from assistant_turn_attachments" in normalized:
                return Cursor(public_attachment_rows())
            raise AssertionError(f"unexpected SQL: {normalized}")

    target = load_retryable_user_turn(Conn(), USER_TURN_ID)

    assert target is not None
    assert target.user_turn_id == USER_TURN_ID
    assert target.conversation_id == CONVERSATION_ID
    assert target.content == "请比较附件"
    assert [item["attachment_id"] for item in target.attachments] == [
        str(FIRST_ATTACHMENT_ID),
        str(SECOND_ATTACHMENT_ID),
    ]
    assert any("role = 'user'" in sql and "for update" in sql for sql in executed)


def test_retry_endpoint_model_failure_preserves_user_turn_then_success_adds_only_assistant(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    persisted: list[dict[str, Any]] = []
    model_should_fail = {"value": True}

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql: str, params=()):
            normalized = " ".join(sql.split()).lower()
            if "from assistant_turns" in normalized and "role = 'user'" in normalized:
                return Cursor(
                    [(USER_TURN_ID, CONVERSATION_ID, "user", "请比较附件", uuid.uuid4(), NOW)]
                )
            if "from assistant_turn_attachments" in normalized:
                return Cursor(public_attachment_rows())
            if "from assistant_turns" in normalized and "tool_call_id" in normalized:
                matching = [item for item in persisted if item.get("tool_call_id") == params[0]]
                if not matching:
                    return Cursor()
                item = matching[0]
                return Cursor(
                    [
                        (
                            item["turn_id"],
                            CONVERSATION_ID,
                            item["event_id"],
                            item["content"],
                        )
                    ]
                )
            raise AssertionError(f"unexpected SQL: {normalized}")

    class Gateway:
        async def chat(self, messages):
            if model_should_fail["value"]:
                raise main.ModelGatewayError("no_provider_available", [])
            return type(
                "Result",
                (),
                {"text": "附件结论", "provider_id": "qwen", "trace": {"mode": "non_thinking"}},
            )()

    def persist(conn, redis_obj, *, role, content, conversation_id, client_type, tool_call_id, **kwargs):
        assert role == "assistant"
        item = {
            "turn_id": str(uuid.uuid4()),
            "event_id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "conversation_id": conversation_id,
            "tool_call_id": tool_call_id,
        }
        persisted.append(item)
        return item

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "model_gateway", lambda: Gateway())
    monkeypatch.setattr(main, "persist_assistant_turn", persist)
    monkeypatch.setattr(main, "redis_client", lambda: object())
    client = TestClient(main.app, raise_server_exceptions=False)

    failed = client.post(
        f"/api/chat/turns/{USER_TURN_ID}/retry",
        json={"client_type": "android"},
        headers={"x-par-password": "secret"},
    )
    assert failed.status_code == 503
    assert persisted == []

    model_should_fail["value"] = False
    succeeded = client.post(
        f"/api/chat/turns/{USER_TURN_ID}/retry",
        json={"client_type": "android"},
        headers={"x-par-password": "secret"},
    )
    repeated = client.post(
        f"/api/chat/turns/{USER_TURN_ID}/retry",
        json={"client_type": "android"},
        headers={"x-par-password": "secret"},
    )

    assert succeeded.status_code == 200
    assert repeated.status_code == 200
    assert succeeded.json()["conversation_id"] == str(CONVERSATION_ID)
    assert succeeded.json()["user_turn_id"] == str(USER_TURN_ID)
    assert succeeded.json()["attachment_ids"] == [
        str(FIRST_ATTACHMENT_ID),
        str(SECOND_ATTACHMENT_ID),
    ]
    assert repeated.json()["assistant_turn_id"] == succeeded.json()["assistant_turn_id"]
    assert len(persisted) == 1
    assert persisted[0]["role"] == "assistant"


def test_conversation_deletion_enqueues_relative_paths_before_cascading_rows():
    operations: list[tuple[str, tuple[Any, ...]]] = []

    class Conn:
        def execute(self, sql: str, params=()):
            normalized = " ".join(sql.split()).lower()
            params = tuple(params)
            operations.append((normalized, params))
            if normalized.startswith("select c.id"):
                return Cursor([(CONVERSATION_ID,)])
            if normalized.startswith("select attachment.id"):
                return Cursor([(FIRST_ATTACHMENT_ID,), (SECOND_ATTACHMENT_ID,)])
            if "from assistant_turn_attachments" in normalized and "storage_relative_path" in normalized:
                return Cursor(
                    [
                        (FIRST_ATTACHMENT_ID, "originals/55/source.png"),
                        (FIRST_ATTACHMENT_ID, "derivatives/55/preview.png"),
                        (SECOND_ATTACHMENT_ID, "originals/66/source.pdf"),
                    ]
                )
            if normalized.startswith("insert into attachment_cleanup_outbox"):
                return Cursor(rowcount=1)
            if normalized.startswith("delete from chat_attachments"):
                return Cursor(rowcount=2)
            if normalized.startswith("delete from assistant_conversations"):
                assert params == (CONVERSATION_ID,)
                return Cursor([(CONVERSATION_ID,)], rowcount=1)
            raise AssertionError(f"unexpected SQL: {normalized}")

    result = delete_conversation_with_attachment_cleanup(Conn(), CONVERSATION_ID)

    assert result.deleted is True
    assert result.deleted_attachment_count == 2
    assert result.cleanup_path_count == 3
    insert_positions = [
        index for index, (sql, _) in enumerate(operations) if sql.startswith("insert into attachment_cleanup_outbox")
    ]
    attachment_delete_position = next(
        index for index, (sql, _) in enumerate(operations) if sql.startswith("delete from chat_attachments")
    )
    conversation_delete_position = next(
        index for index, (sql, _) in enumerate(operations) if sql.startswith("delete from assistant_conversations")
    )
    assert insert_positions and max(insert_positions) < attachment_delete_position < conversation_delete_position
    outbox_paths = [
        params[2]
        for sql, params in operations
        if sql.startswith("insert into attachment_cleanup_outbox")
    ]
    assert outbox_paths == [
        "originals/55/source.png",
        "derivatives/55/preview.png",
        "originals/66/source.pdf",
    ]
    assert all(not path.startswith("/") and ".." not in Path(path).parts for path in outbox_paths)
    assert all(str(OTHER_CONVERSATION_ID) not in repr(params) for _, params in operations)


def test_conversation_deletion_cascades_bound_attachment_even_without_physical_path():
    deleted_ids: list[uuid.UUID] = []

    class Conn:
        def execute(self, sql: str, params=()):
            normalized = " ".join(sql.split()).lower()
            if normalized.startswith("select c.id"):
                return Cursor([(CONVERSATION_ID,)])
            if normalized.startswith("select attachment.id"):
                return Cursor([(FIRST_ATTACHMENT_ID,)])
            if "from assistant_turn_attachments" in normalized and "storage_relative_path" in normalized:
                return Cursor([])
            if normalized.startswith("delete from chat_attachments"):
                deleted_ids.extend(uuid.UUID(str(item)) for item in params[0])
                return Cursor(rowcount=1)
            if normalized.startswith("delete from assistant_conversations"):
                return Cursor([(CONVERSATION_ID,)], rowcount=1)
            raise AssertionError(f"unexpected SQL: {normalized}")

    result = delete_conversation_with_attachment_cleanup(Conn(), CONVERSATION_ID)

    assert result.deleted_attachment_count == 1
    assert result.cleanup_path_count == 0
    assert deleted_ids == [FIRST_ATTACHMENT_ID]


def test_cleanup_outbox_is_present_in_fresh_and_runtime_schema():
    runtime_sql = "\n".join(attachment_schema_sql()).lower()
    fresh_sql = (Path(__file__).resolve().parents[2] / "db" / "init.sql").read_text().lower()

    for sql in (runtime_sql, fresh_sql):
        assert "create table if not exists attachment_cleanup_outbox" in sql
        assert "storage_relative_path text not null" in sql
        assert "unique (attachment_id, storage_relative_path)" in sql


def test_outbox_cleaner_deletes_private_file_then_marks_item_completed(tmp_path):
    relative_path = "originals/55/source.png"
    private_file = tmp_path / relative_path
    private_file.parent.mkdir(parents=True)
    private_file.write_bytes(b"private")
    item = AttachmentCleanupOutboxRecord(
        outbox_id=uuid.uuid4(),
        attachment_id=FIRST_ATTACHMENT_ID,
        storage_relative_path=relative_path,
        attempt_count=1,
    )

    class Repository:
        def __init__(self):
            self.completed: list[uuid.UUID] = []
            self.retried: list[tuple[uuid.UUID, str]] = []
            self.claimed = False

        def claim_cleanup_outbox(self, *, now, lease_seconds):
            if self.claimed:
                return None
            self.claimed = True
            return item

        def complete_cleanup_outbox(self, outbox_id, *, completed_at):
            self.completed.append(outbox_id)

        def retry_cleanup_outbox(self, outbox_id, *, available_at, error_code):
            self.retried.append((outbox_id, error_code))

    repository = Repository()
    cleaner = AttachmentOutboxCleaner(repository=repository, storage_root=tmp_path)

    result = cleaner.run_next(now=NOW)

    assert result == "completed"
    assert not private_file.exists()
    assert repository.completed == [item.outbox_id]
    assert repository.retried == []


def test_outbox_cleaner_requeues_failed_deletion_without_losing_path(tmp_path):
    relative_path = "originals/55/not-a-file"
    blocked_path = tmp_path / relative_path
    blocked_path.mkdir(parents=True)
    item = AttachmentCleanupOutboxRecord(
        outbox_id=uuid.uuid4(),
        attachment_id=FIRST_ATTACHMENT_ID,
        storage_relative_path=relative_path,
        attempt_count=2,
    )

    class Repository:
        def __init__(self):
            self.retry: tuple[uuid.UUID, datetime, str] | None = None

        def claim_cleanup_outbox(self, *, now, lease_seconds):
            return item

        def complete_cleanup_outbox(self, outbox_id, *, completed_at):
            raise AssertionError("failed deletion must not complete")

        def retry_cleanup_outbox(self, outbox_id, *, available_at, error_code):
            self.retry = (outbox_id, available_at, error_code)

    repository = Repository()
    cleaner = AttachmentOutboxCleaner(repository=repository, storage_root=tmp_path)

    result = cleaner.run_next(now=NOW)

    assert result == "retry_scheduled"
    assert blocked_path.exists()
    assert repository.retry is not None
    assert repository.retry[0] == item.outbox_id
    assert repository.retry[1] > NOW
    assert repository.retry[2] == "physical_delete_failed"
