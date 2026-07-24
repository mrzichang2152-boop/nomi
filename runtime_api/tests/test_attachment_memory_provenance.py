from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


TURN_ID = uuid.UUID("00000000-0000-0000-0000-000000000101")
ATTACHMENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000201")


class Cursor:
    def __init__(self, rows=None):
        self.rows = rows or []

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, pending_rows, provenance_rows):
        self.pending_rows = pending_rows
        self.provenance_rows = provenance_rows
        self.executed = []

    def execute(self, sql, params=()):
        normalized = " ".join(str(sql).split())
        self.executed.append((normalized, params))
        if "FROM assistant_turns" in normalized and "memory_pending = TRUE" in normalized:
            return Cursor(self.pending_rows)
        if "FROM assistant_turn_attachments" in normalized:
            return Cursor(self.provenance_rows)
        return Cursor()


class FakeRedis:
    def __init__(self):
        self.events = []

    def xadd(self, stream, payload):
        self.events.append((stream, payload))


def fixed_insert_private_event(conn, source, event_type, raw_data, ts=None):
    return (
        uuid.UUID("11111111-1111-1111-1111-111111111111"),
        ts or datetime(2026, 7, 13, 8, 0, tzinfo=timezone.utc),
        dict(raw_data),
    )


def pending_dialogue_rows():
    rows = []
    for index in range(15):
        user_id = TURN_ID if index == 0 else uuid.UUID(int=index + 1)
        rows.append(
            (
                user_id,
                "user",
                "请根据附件回答" if index == 0 else f"user {index}",
                uuid.UUID(int=100 + index),
                datetime(2026, 7, 13, 8, index, tzinfo=timezone.utc),
            )
        )
        rows.append(
            (
                uuid.UUID(int=1000 + index),
                "assistant",
                "附件第 2 页说明项目在九月交付" if index == 0 else f"assistant {index}",
                uuid.UUID(int=200 + index),
                datetime(2026, 7, 13, 8, index, 30, tzinfo=timezone.utc),
            )
        )
    return rows


def test_attachment_upload_or_parse_does_not_bypass_dialogue_memory_batch():
    from app.attachments.trace import attachment_memory_policy

    assert attachment_memory_policy("upload") == "none"
    assert attachment_memory_policy("parse") == "none"
    assert attachment_memory_policy("dialogue_batch") == "eligible"


def test_fifteen_round_batch_carries_safe_attachment_provenance(monkeypatch):
    from app import main

    provenance_rows = [
        (
            TURN_ID,
            ATTACHMENT_ID,
            "application/pdf",
            "ready",
            "attachment-v1",
            {"page": 2},
            "chunk-hash-2",
            1,
        )
    ]
    conn = FakeConn(pending_dialogue_rows(), provenance_rows)
    redis = FakeRedis()
    monkeypatch.setattr(main, "insert_private_event", fixed_insert_private_event)

    result = main.maybe_enqueue_dialogue_memory_batch(
        conn,
        redis,
        uuid.UUID("22222222-2222-2222-2222-222222222222"),
    )

    assert result["batch_created"] is True
    raw_data = json.loads(redis.events[0][1]["raw_data"])
    assert raw_data["attachment_provenance"] == [
        {
            "attachment_id": str(ATTACHMENT_ID),
            "turn_id": str(TURN_ID),
            "mime_type": "application/pdf",
            "status": "ready",
            "processing_version": "attachment-v1",
            "locator": {"page": 2},
            "content_hash": "chunk-hash-2",
            "chunk_ordinal": 1,
        }
    ]
    serialized = json.dumps(raw_data, ensure_ascii=False)
    assert "附件第 2 页说明" in serialized
    assert "storage_relative_path" not in serialized
    assert "/private/" not in serialized
    assert "base64" not in serialized.lower()


def test_reprocessing_adds_versioned_provenance_without_rewriting_prior_evidence():
    from app.attachments.trace import merge_attachment_provenance

    v1 = {
        "attachment_id": str(ATTACHMENT_ID),
        "turn_id": str(TURN_ID),
        "locator": {"page": 2},
        "content_hash": "hash-v1",
        "processing_version": "attachment-v1",
    }
    v2 = {**v1, "content_hash": "hash-v2", "processing_version": "attachment-v2"}

    merged = merge_attachment_provenance([v1], [v2])

    assert merged == [v1, v2]
    assert merge_attachment_provenance(merged, [v2]) == merged


def test_visual_attachment_without_text_chunk_uses_whole_file_provenance():
    from app.attachments.trace import load_attachment_provenance_for_turns

    conn = FakeConn(
        [],
        [
            (
                TURN_ID,
                ATTACHMENT_ID,
                "image/png",
                "ready",
                "attachment-v1",
                None,
                "whole-file-sha256",
                None,
            )
        ],
    )

    provenance = load_attachment_provenance_for_turns(conn, [TURN_ID])

    assert provenance == [
        {
            "attachment_id": str(ATTACHMENT_ID),
            "turn_id": str(TURN_ID),
            "mime_type": "image/png",
            "status": "ready",
            "processing_version": "attachment-v1",
            "locator": {"ordinal": 0},
            "content_hash": "whole-file-sha256",
            "chunk_ordinal": 0,
        }
    ]
