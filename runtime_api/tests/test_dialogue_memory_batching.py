import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


class Cursor:
    def __init__(self, rows=None, row=None, rowcount=1):
        self.rows = rows or []
        self.row = row
        self.rowcount = rowcount

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


class FakeConn:
    def __init__(self, pending_rows=None):
        self.pending_rows = pending_rows or []
        self.executed = []

    def execute(self, sql, params=()):
        normalized = " ".join(str(sql).split())
        self.executed.append((normalized, params))
        if "FROM assistant_turns" in normalized and "memory_pending = TRUE" in normalized:
            return Cursor(rows=self.pending_rows)
        return Cursor()


class FakeRedis:
    def __init__(self):
        self.events = []

    def xadd(self, stream, payload):
        self.events.append((stream, payload))


def fixed_insert_private_event(conn, source, event_type, raw_data, ts=None):
    return (
        uuid.UUID("11111111-1111-1111-1111-111111111111"),
        ts or datetime(2026, 6, 16, 8, 0, tzinfo=timezone.utc),
        dict(raw_data),
    )


def test_dialogue_memory_policy_defers_ordinary_dialogue():
    from app import main

    decision = main.dialogue_memory_policy_for_turn("user", "你好，今天聊点轻松的", explicit_policy="auto")

    assert decision["policy"] == "defer"
    assert decision["reason"] == "ordinary_dialogue"


def test_dialogue_memory_policy_immediately_enqueues_strong_signal():
    from app import main

    decision = main.dialogue_memory_policy_for_turn("user", "请记住我更喜欢上午面试", explicit_policy="auto")

    assert decision["policy"] == "immediate"
    assert decision["reason"] == "explicit_memory"


def test_persist_assistant_turn_defers_ordinary_dialogue_without_redis_enqueue(monkeypatch):
    from app import main

    conn = FakeConn()
    redis = FakeRedis()
    monkeypatch.setattr(main, "insert_private_event", fixed_insert_private_event)

    result = main.persist_assistant_turn(
        conn,
        redis,
        role="user",
        content="你好，普通聊天",
        conversation_id="22222222-2222-2222-2222-222222222222",
        client_type="android",
    )

    assert redis.events == []
    assert result["dialogue_memory_enqueue"]["policy"] == "defer"
    assert result["dialogue_memory_enqueue"]["batch_created"] is False
    combined_sql = "\n".join(sql for sql, _ in conn.executed)
    assert "memory_pending" in combined_sql


def test_persist_assistant_turn_immediately_enqueues_explicit_memory(monkeypatch):
    from app import main

    conn = FakeConn()
    redis = FakeRedis()
    monkeypatch.setattr(main, "insert_private_event", fixed_insert_private_event)

    result = main.persist_assistant_turn(
        conn,
        redis,
        role="user",
        content="记住我每周三上午要看求职进展",
        conversation_id="22222222-2222-2222-2222-222222222222",
        client_type="android",
    )

    assert len(redis.events) == 1
    assert redis.events[0][1]["event_type"] == "user_message"
    assert result["dialogue_memory_enqueue"]["policy"] == "immediate"
    assert result["dialogue_memory_enqueue"]["reason"] == "explicit_memory"


def test_dialogue_batch_slice_waits_for_15_complete_rounds():
    from app import main

    fourteen_rounds = []
    for index in range(14):
        fourteen_rounds.append({"turn_id": f"u-{index}", "role": "user", "content": f"u {index}"})
        fourteen_rounds.append({"turn_id": f"a-{index}", "role": "assistant", "content": f"a {index}"})

    selected, round_count = main.dialogue_batch_turn_slice(fourteen_rounds, threshold_rounds=15)

    assert selected == []
    assert round_count == 14


def test_dialogue_batch_slice_selects_first_15_complete_rounds():
    from app import main

    turns = []
    for index in range(16):
        turns.append({"turn_id": f"u-{index}", "role": "user", "content": f"user {index}"})
        turns.append({"turn_id": f"a-{index}", "role": "assistant", "content": f"assistant {index}"})

    selected, round_count = main.dialogue_batch_turn_slice(turns, threshold_rounds=15)

    assert round_count == 15
    assert len(selected) == 30
    assert selected[0]["turn_id"] == "u-0"
    assert selected[-1]["turn_id"] == "a-14"


def test_maybe_enqueue_dialogue_memory_batch_creates_one_batch_for_15_rounds(monkeypatch):
    from app import main

    conversation_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    pending_rows = []
    for index in range(15):
        pending_rows.append(
            (
                uuid.UUID(int=index + 1),
                "user",
                f"user {index}",
                uuid.UUID(int=100 + index),
                datetime(2026, 6, 16, 8, index, tzinfo=timezone.utc),
            )
        )
        pending_rows.append(
            (
                uuid.UUID(int=1000 + index),
                "assistant",
                f"assistant {index}",
                uuid.UUID(int=200 + index),
                datetime(2026, 6, 16, 8, index, 30, tzinfo=timezone.utc),
            )
        )
    conn = FakeConn(pending_rows=pending_rows)
    redis = FakeRedis()
    monkeypatch.setattr(main, "insert_private_event", fixed_insert_private_event)

    result = main.maybe_enqueue_dialogue_memory_batch(conn, redis, conversation_id)

    assert result["policy"] == "batch_created"
    assert result["pending_round_count"] == 15
    assert result["batch_created"] is True
    assert len(redis.events) == 1
    assert redis.events[0][1]["event_type"] == "dialogue_batch"
    combined_sql = "\n".join(sql for sql, _ in conn.executed)
    assert "INSERT INTO conversation_memory_batches" in combined_sql
    assert "UPDATE assistant_turns" in combined_sql
