import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")

from app.worker_concurrency import DedupeLockRegistry, process_entries_with_locks


def test_same_dedupe_key_reuses_same_lock():
    registry = DedupeLockRegistry()

    first = registry.lock_for("agenda:a")
    second = registry.lock_for("agenda:a")
    third = registry.lock_for("agenda:b")

    assert first is second
    assert first is not third


def test_same_dedupe_key_is_processed_serially_even_with_workers():
    registry = DedupeLockRegistry()
    active = {"count": 0, "max": 0}
    guard = threading.Lock()

    def process(entry):
        with guard:
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
        time.sleep(0.01)
        with guard:
            active["count"] -= 1
        return entry["id"]

    results = process_entries_with_locks(
        [{"id": "1", "key": "same"}, {"id": "2", "key": "same"}, {"id": "3", "key": "same"}],
        process_fn=process,
        key_fn=lambda entry: entry["key"],
        lock_registry=registry,
        max_workers=3,
    )

    assert results == ["1", "2", "3"]
    assert active["max"] == 1


def test_worker_stream_lock_key_uses_private_conversation_scope():
    from app.worker import stream_entry_lock_key

    first = (
        "1-0",
        {
            "source": "whatsapp",
            "event_id": "event-a",
            "raw_data": '{"chat_id":"chat-123","message":"明天见"}',
        },
    )
    second = (
        "2-0",
        {
            "source": "whatsapp",
            "event_id": "event-b",
            "raw_data": '{"chat_id":"chat-123","message":"改到后天"}',
        },
    )
    third = (
        "3-0",
        {
            "source": "gmail",
            "event_id": "event-c",
            "raw_data": '{"thread_id":"thread-9","subject":"Interview"}',
        },
    )

    assert stream_entry_lock_key(first) == stream_entry_lock_key(second)
    assert stream_entry_lock_key(first).startswith("whatsapp:chat_id:chat-123")
    assert stream_entry_lock_key(third) == "gmail:thread_id:thread-9"


def test_worker_batch_records_only_final_checkpoint(monkeypatch):
    from app import worker

    calls = []

    class RedisClient:
        def set(self, key, value):
            calls.append(("set", key, value))

    class Batcher:
        pass

    def fake_process(redis_client, message_id, fields, memory_batcher=None, record_checkpoint=True):
        calls.append(("process", message_id, record_checkpoint))
        assert record_checkpoint is False
        return worker.StreamProcessResult(success=True, checkpoint=True)

    monkeypatch.setattr(worker, "process_stream_entry_result", fake_process)

    results = worker.process_stream_entries_batch(
        RedisClient(),
        [
            ("1-0", {"source": "focus", "event_id": "a", "raw_data": "{}"}),
            ("2-0", {"source": "whatsapp", "event_id": "b", "event_type": "whatsapp_message", "raw_data": "{}"}),
            ("3-0", {"source": "gmail", "event_id": "c", "event_type": "gmail_message", "raw_data": "{}"}),
        ],
        memory_batcher=Batcher(),
        lock_registry=worker.DedupeLockRegistry(),
        max_workers=1,
    )

    assert results == [True, True, True]
    assert ("set", worker.WORKER_CHECKPOINT_KEY, "3-0") in calls
    assert [call for call in calls if call[0] == "set"] == [("set", worker.WORKER_CHECKPOINT_KEY, "3-0")]


def test_worker_batch_does_not_checkpoint_past_retryable_failure(monkeypatch):
    from app import worker

    calls = []

    class RedisClient:
        def set(self, key, value):
            calls.append(("set", key, value))

    class Batcher:
        pass

    def fake_process(redis_client, message_id, fields, memory_batcher=None, record_checkpoint=True):
        calls.append(("process", message_id))
        if message_id == "2-0":
            return worker.StreamProcessResult(success=False, checkpoint=False)
        return worker.StreamProcessResult(success=True, checkpoint=True)

    monkeypatch.setattr(worker, "process_stream_entry_result", fake_process)

    results = worker.process_stream_entries_batch(
        RedisClient(),
        [
            ("1-0", {"source": "gmail", "event_id": "a", "event_type": "gmail_message", "raw_data": "{}"}),
            ("2-0", {"source": "gmail", "event_id": "b", "event_type": "gmail_message", "raw_data": "{}"}),
            ("3-0", {"source": "gmail", "event_id": "c", "event_type": "gmail_message", "raw_data": "{}"}),
        ],
        memory_batcher=Batcher(),
        lock_registry=worker.DedupeLockRegistry(),
        max_workers=1,
    )

    assert results == [True, False, True]
    assert [call for call in calls if call[0] == "set"] == [("set", worker.WORKER_CHECKPOINT_KEY, "1-0")]


def test_worker_selects_high_priority_entries_from_large_read_window():
    from app import worker

    low_value_entries = [
        (
            f"{index}-0",
            {
                "source": "focus",
                "event_type": "browser_focus_event",
                "event_id": f"low-{index}",
                "raw_data": "{}",
            },
        )
        for index in range(20)
    ]
    high_value = (
        "21-0",
        {
            "source": "whatsapp",
            "event_type": "whatsapp_message",
            "event_id": "high-1",
            "raw_data": '{"message":"明天上午10点见"}',
        },
    )

    selected = worker.select_stream_entries_for_processing(low_value_entries + [high_value], max_items=10)

    assert high_value in selected
    assert selected[0] == high_value
    assert len(selected) == 10


def test_agenda_schema_ddl_runs_once_with_concurrent_workers(monkeypatch):
    from app import worker

    monkeypatch.setattr(worker, "_AGENDA_SCHEMA_READY", False, raising=False)
    calls = []
    guard = threading.Lock()

    class Conn:
        def execute(self, sql, params=()):
            with guard:
                calls.append(sql)

    def ensure_once():
        worker.ensure_agenda_schema(Conn())

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: ensure_once(), range(8)))

    assert len(calls) == 7
    assert sum("CREATE TABLE IF NOT EXISTS agenda_items" in sql for sql in calls) == 1
    assert sum("CREATE TABLE IF NOT EXISTS agenda_reminders" in sql for sql in calls) == 1
    assert sum("CREATE INDEX IF NOT EXISTS agenda_items_status_idx" in sql for sql in calls) == 1
    assert sum("CREATE UNIQUE INDEX IF NOT EXISTS agenda_reminders_dedupe_key_idx" in sql for sql in calls) == 1
    assert sum("CREATE INDEX IF NOT EXISTS agenda_reminders_due_idx" in sql for sql in calls) == 1
