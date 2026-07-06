import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")

from app.event_batcher import MemoryBatcher


def test_batcher_flushes_by_size():
    flushed = []
    batcher = MemoryBatcher(
        max_items=3,
        max_age_seconds=60,
        flush_fn=lambda items: flushed.append(list(items)),
    )

    assert batcher.add({"id": "1"}) == []
    assert batcher.add({"id": "2"}) == []
    batches = batcher.add({"id": "3"})

    assert len(batches) == 1
    assert [item["id"] for item in batches[0]] == ["1", "2", "3"]
    assert [item["id"] for item in flushed[0]] == ["1", "2", "3"]
    assert batcher.flush_due() == []


def test_batcher_flushes_by_age():
    now = {"value": 1000.0}
    flushed = []
    batcher = MemoryBatcher(
        max_items=10,
        max_age_seconds=5,
        flush_fn=lambda items: flushed.append(list(items)),
        now=lambda: now["value"],
    )

    assert batcher.add({"id": "1"}) == []
    now["value"] = 1004.0
    assert batcher.flush_due() == []
    now["value"] = 1006.0
    batches = batcher.flush_due()

    assert len(batches) == 1
    assert batches[0][0]["id"] == "1"
    assert flushed[0][0]["id"] == "1"
    assert batcher.flush_due() == []


def test_persist_semantics_queues_memory_enrichment_without_blocking_online_outputs():
    from app import worker

    executed = []

    class Cursor:
        rowcount = 1

        def __init__(self, row=None):
            self.row = row

        def fetchone(self):
            return self.row

    class Conn:
        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            executed.append(normalized)
            if normalized.startswith("SELECT source, event_type FROM events"):
                return Cursor(("whatsapp", "whatsapp_message"))
            return Cursor()

    queued_batches = []
    batcher = MemoryBatcher(
        max_items=20,
        max_age_seconds=30,
        flush_fn=lambda items: queued_batches.append(list(items)),
    )
    semantic = {
        "intent": "generic_event",
        "entities": {"source": "whatsapp", "event_type": "whatsapp_message", "labels": []},
        "importance": 0.2,
        "summary": "普通消息。",
        "model_version": "test",
        "raw_data": {"text": "普通消息。"},
    }

    worker.persist_semantics(
        Conn(),
        "11111111-1111-1111-1111-111111111111",
        "2026-06-12T10:00:00+08:00",
        semantic,
        memory_batcher=batcher,
    )

    combined_sql = "\n".join(executed)
    assert "INSERT INTO semantic_events" in combined_sql
    assert "INSERT INTO facts" not in combined_sql
    assert "INSERT INTO memory_vectors" not in combined_sql
    assert len(batcher.items) == 1
    queued = batcher.items[0]
    assert queued["event_id"] == "11111111-1111-1111-1111-111111111111"
    assert queued["source"] == "whatsapp"
    assert queued["event_type"] == "whatsapp_message"
    assert queued["semantic"]["summary"] == "普通消息。"
    assert queued_batches == []


def test_batcher_is_thread_safe_for_concurrent_adds():
    flushed = []
    batcher = MemoryBatcher(
        max_items=10,
        max_age_seconds=60,
        flush_fn=lambda items: flushed.append(list(items)),
    )

    threads = [
        threading.Thread(target=lambda item_id=index: batcher.add({"id": str(item_id)}))
        for index in range(10)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(flushed) == 1
    assert sorted(item["id"] for item in flushed[0]) == [str(index) for index in range(10)]
    assert batcher.items == []
