from __future__ import annotations

import json
import os


os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def provenance(version: str, content_hash: str) -> dict:
    return {
        "attachment_id": "00000000-0000-0000-0000-000000000201",
        "turn_id": "00000000-0000-0000-0000-000000000101",
        "mime_type": "application/pdf",
        "status": "ready",
        "processing_version": version,
        "locator": {"page": 2},
        "content_hash": content_hash,
        "chunk_ordinal": 1,
    }


def test_dialogue_batch_fact_keeps_safe_attachment_provenance():
    from app.worker import extract_semantics, fact_from_semantic

    raw_data = {
        "conversation_id": "conversation-1",
        "round_count": 15,
        "turns": [
            {"role": "user", "content": "请总结附件", "turn_id": "turn-1"},
            {"role": "assistant", "content": "九月交付", "turn_id": "turn-2"},
        ],
        "attachment_provenance": [
            provenance("attachment-v1", "hash-v1"),
            {
                **provenance("attachment-v1", "hash-v1"),
                "content": "private extracted text",
                "storage_relative_path": "private/report.pdf",
                "api_key": "sk-secret",
            },
        ],
    }

    semantic = extract_semantics("nomi_chat", "dialogue_batch", raw_data)
    fact = fact_from_semantic("11111111-1111-1111-1111-111111111111", semantic)

    assert fact["metadata"]["attachment_provenance"] == [provenance("attachment-v1", "hash-v1")]
    serialized = json.dumps(fact["metadata"], ensure_ascii=False).lower()
    assert "private extracted text" not in serialized
    assert "storage_relative_path" not in serialized
    assert "private/report.pdf" not in serialized
    assert "sk-secret" not in serialized


def test_fact_upsert_sql_appends_distinct_attachment_versions():
    from app.worker import persist_fact_graph_and_state

    class Cursor:
        def fetchone(self):
            return ("fact-id",)

    class Conn:
        def __init__(self):
            self.executed = []

        def execute(self, sql, params=()):
            normalized = " ".join(str(sql).split())
            self.executed.append((normalized, params))
            return Cursor()

    conn = Conn()
    semantic = {
        "intent": "dialogue_batch_summary",
        "importance": 0.62,
        "summary": "九月交付",
        "entities": {"source": "nomi_chat", "event_type": "dialogue_batch"},
        "raw_data": {
            "attachment_provenance": [provenance("attachment-v2", "hash-v2")],
        },
    }

    persist_fact_graph_and_state(conn, "11111111-1111-1111-1111-111111111111", "2026-07-13T08:00:00+00:00", semantic)

    fact_insert = next(sql for sql, _ in conn.executed if "INSERT INTO facts" in sql)
    assert "facts.metadata->'attachment_provenance'" in fact_insert
    assert "EXCLUDED.metadata->'attachment_provenance'" in fact_insert
    assert "SELECT DISTINCT" in fact_insert
    assert "metadata = EXCLUDED.metadata" not in fact_insert
