import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_schema_bootstrap_creates_assistant_context_tables(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed = []

    class Cursor:
        pass

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            executed.append(" ".join(sql.split()))
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())

    main.ensure_assistant_context_schema()

    combined = "\n".join(executed)
    assert "CREATE TABLE IF NOT EXISTS assistant_conversations" in combined
    assert "CREATE TABLE IF NOT EXISTS assistant_turns" in combined
    assert "CREATE TABLE IF NOT EXISTS context_snapshots" in combined
    assert "assistant_turns_conversation_idx" in combined
    assert "context_snapshots_event_idx" in combined


def test_build_context_pack_includes_relevant_dialogue_and_excludes_unrelated():
    from app.main import build_context_pack

    pack = build_context_pack(
        "那就周日吧",
        base_context=[
            {
                "layer": "entity_graph",
                "subject": "alex",
                "predicate": "identity",
                "object": "健身房 Alex",
                "confidence": 0.82,
                "source_event_ids": ["fact-1"],
            }
        ],
        assistant_context=[
            {
                "layer": "assistant_dialogue",
                "event_id": "turn-1",
                "conversation_id": "conv-active",
                "role": "user",
                "content": "帮我盯一下周末和 Alex 见面的事",
            },
            {
                "layer": "assistant_dialogue",
                "event_id": "turn-2",
                "conversation_id": "conv-active",
                "role": "user",
                "content": "不是公司 Alex，是健身房 Alex",
            },
            {
                "layer": "assistant_dialogue",
                "event_id": "turn-3",
                "conversation_id": "conv-other",
                "role": "user",
                "content": "猫粮优惠券下次再说",
            },
        ],
        conversation_id="conv-active",
    )

    dialogue_text = "\n".join(item["content"] for item in pack["assistant_dialogue"])
    assert "周末和 Alex 见面" in dialogue_text
    assert "健身房 Alex" in dialogue_text
    assert "猫粮优惠券" not in dialogue_text
    assert pack["included_event_ids"] == ["turn-1", "turn-2", "fact-1"]
    assert "bounded" in pack["reason"]


def test_persist_assistant_turn_creates_private_event_turn_and_queue(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed = []
    queued = []

    class Cursor:
        rowcount = 1

        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchone(self):
            return self.rows[0] if self.rows else None

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            return Cursor()

    class Redis:
        def xadd(self, stream, fields):
            queued.append((stream, fields))

    result = main.persist_assistant_turn(
        Conn(),
        Redis(),
        role="user",
        content="帮我盯一下周末和 Alex 见面的事",
        conversation_id=None,
        client_type="android",
    )

    combined_sql = "\n".join(sql for sql, _ in executed)
    assert "INSERT INTO assistant_conversations" in combined_sql
    assert "INSERT INTO events" in combined_sql
    assert "INSERT INTO assistant_turns" in combined_sql
    assert result["conversation_id"]
    assert result["event_id"]
    assert queued[0][0] == "events:raw"
    queued_payload = queued[0][1]
    assert queued_payload["source"] == "nomi_chat"
    assert queued_payload["event_type"] == "user_message"
    assert "周末和 Alex" in queued_payload["raw_data"]


def test_chat_endpoint_persists_turns_uses_context_pack_and_returns_trace(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    persisted_turns = []
    snapshots = []

    def fake_persist_turn(conn, redis_client, role, content, conversation_id=None, client_type="web", **kwargs):
        persisted_turns.append({"role": role, "content": content, "conversation_id": conversation_id})
        return {
            "conversation_id": conversation_id or "conv-1",
            "turn_id": f"turn-{role}",
            "event_id": f"event-{role}",
        }

    def fake_context_pack(message, base_context, assistant_context=None, conversation_id=None, **kwargs):
        return {
            "query": message,
            "memory_context": base_context,
            "assistant_dialogue": [{"layer": "assistant_dialogue", "content": "用户之前说要盯周末见面"}],
            "included_event_ids": ["event-user"],
            "reason": "bounded context pack: active conversation and scoped memory",
        }

    def fake_snapshot(conn, event_id, context_type, context_pack):
        snapshots.append((event_id, context_type, context_pack["included_event_ids"]))

    class FakeQwen:
        def __init__(self, *args, **kwargs):
            pass

        async def chat(self, messages):
            assert "bounded context pack" in messages[1]["content"]
            assert "用户之前说要盯周末见面" in messages[1]["content"]
            return "我会继续帮你盯这个周末安排。"

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class Redis:
        pass

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: Redis())
    monkeypatch.setattr(main, "retrieve_context", lambda message, limit: [{"layer": "entity_graph", "subject": "alex"}])
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "persist_assistant_turn", fake_persist_turn, raising=False)
    monkeypatch.setattr(main, "build_context_pack", fake_context_pack, raising=False)
    monkeypatch.setattr(main, "persist_context_snapshot", fake_snapshot, raising=False)
    monkeypatch.setattr(main, "QwenClient", FakeQwen)

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        headers={"x-par-password": "secret"},
        json={"message": "那就周日吧", "limit": 8, "conversation_id": "conv-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "conv-1"
    assert body["answer"] == "我会继续帮你盯这个周末安排。"
    assert body["context_pack"]["included_event_ids"] == ["event-user"]
    assert [item["role"] for item in persisted_turns] == ["user", "assistant"]
    assert persisted_turns[0]["content"] == "那就周日吧"
    assert snapshots == [("event-user", "chat_response", ["event-user"])]


def test_chat_messages_alias_uses_same_chat_pipeline(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    def fake_persist_turn(conn, redis_client, role, content, conversation_id=None, client_type="web", **kwargs):
        return {
            "conversation_id": conversation_id or "conv-alias",
            "turn_id": f"turn-{role}",
            "event_id": f"event-{role}",
        }

    def fake_context_pack(message, base_context, assistant_context=None, conversation_id=None, **kwargs):
        return {
            "query": message,
            "memory_context": base_context,
            "assistant_dialogue": [],
            "agenda_context": [],
            "included_event_ids": ["event-user"],
            "included_agenda_ids": [],
            "reason": "bounded context pack: alias route",
        }

    class FakeQwen:
        def __init__(self, *args, **kwargs):
            pass

        async def chat(self, messages):
            assert "alias route" in messages[1]["content"]
            return "别名路由也走同一个对话管线。"

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: object())
    monkeypatch.setattr(main, "retrieve_context", lambda message, limit: [])
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_agenda_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "persist_assistant_turn", fake_persist_turn, raising=False)
    monkeypatch.setattr(main, "build_context_pack", fake_context_pack, raising=False)
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "QwenClient", FakeQwen)

    response = TestClient(main.app).post(
        "/api/chat/messages",
        headers={"x-par-password": "secret"},
        json={"message": "走兼容消息接口", "conversation_id": "conv-alias"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "conv-alias"
    assert body["answer"] == "别名路由也走同一个对话管线。"
    assert body["context_pack"]["included_event_ids"] == ["event-user"]
