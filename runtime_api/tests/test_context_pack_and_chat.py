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


def test_build_context_pack_uses_token_budget_not_fixed_turn_count():
    from app.main import build_context_pack

    assistant_context = [
        {
            "layer": "assistant_dialogue",
            "event_id": f"turn-{index}",
            "conversation_id": "conv-budget",
            "role": "assistant" if index % 2 else "user",
            "content": f"PHONE_1 报价上下文第 {index} 条，包含成本、利润率和客户反馈。",
        }
        for index in range(12)
    ]

    pack = build_context_pack(
        "继续核对 PHONE_1 的成本与利润率",
        base_context=[],
        assistant_context=assistant_context,
        conversation_id="conv-budget",
        context_budget={"input_target": 12000, "hard_input_ceiling": 16000},
    )

    dialogue_ids = [item["event_id"] for item in pack["assistant_dialogue"]]
    assert dialogue_ids == [f"turn-{index}" for index in range(12)]
    assert pack["token_budget"]["model_window"] == 256000
    assert pack["token_budget"]["input_used"] > 0
    assert pack["sections"][0]["name"] == "same_conversation"
    assert pack["sections"][0]["tokens_used"] > 0


def test_build_context_pack_filters_cross_contact_context_before_ranking():
    from app.main import build_context_pack

    pack = build_context_pack(
        "帮我回复 Alice",
        base_context=[
            {
                "layer": "semantic_memory",
                "event_id": "alice-event",
                "content": "Alice 说这周五可以确认报价。",
                "counterparty_ids": ["alice"],
                "visibility_scope": "contact_scoped",
                "sensitivity_level": "medium",
            },
            {
                "layer": "semantic_memory",
                "event_id": "bob-private",
                "content": "Bob 私下抱怨 Alice 不靠谱。",
                "counterparty_ids": ["bob"],
                "visibility_scope": "contact_scoped",
                "sensitivity_level": "high",
            },
        ],
        assistant_context=[],
        conversation_id="conv-alice",
        request_scope={"counterparty_ids": ["alice"], "primary_scope": "contact_scoped"},
    )

    memory_text = json_text(pack["memory_context"])
    assert "Alice 说这周五可以确认报价" in memory_text
    assert "Bob 私下抱怨" not in memory_text
    assert pack["excluded"][0]["source_id"] == "bob-private"
    assert "Different contact scope" in pack["excluded"][0]["reason"]


def test_build_context_pack_truncates_oversized_items_with_source_trace():
    from app.main import build_context_pack

    long_content = "这是一封很长的邮件。" * 400
    pack = build_context_pack(
        "总结这封邮件",
        base_context=[
            {
                "layer": "vector_recall",
                "event_id": "long-email-1",
                "content": long_content,
                "source_event_ids": ["long-email-source"],
            }
        ],
        assistant_context=[],
        context_budget={
            "input_target": 900,
            "hard_input_ceiling": 1200,
            "single_item_token_limit": 80,
        },
    )

    packed_item = pack["memory_context"][0]
    assert packed_item["event_id"] == "long-email-1"
    assert packed_item["truncated"] is True
    assert len(packed_item["content"]) < len(long_content)
    assert pack["warnings"][0]["source_id"] == "long-email-1"
    assert pack["warnings"][0]["type"] == "truncated"


def test_normalize_client_delta_dedupes_current_message_and_keeps_prior_question():
    from app.main import normalize_client_dialogue_context

    normalized = normalize_client_dialogue_context(
        [
            {"role": "assistant", "content": "需要我帮你核对成本与利润率数据吗？"},
            {"role": "user", "content": "需要"},
        ],
        "conv-1",
        current_message="需要",
        token_budget=1000,
    )

    assert [item["role"] for item in normalized] == ["assistant"]
    assert normalized[0]["content"] == "需要我帮你核对成本与利润率数据吗？"


def json_text(value):
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


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
        assistant_text = "\n".join(item.get("content", "") for item in assistant_context or [])
        assert [item.get("role") for item in assistant_context or []] == ["assistant"]
        assert "核对成本与利润率" in assistant_text
        assert assistant_text.count("需要") == 1
        return {
            "query": message,
            "memory_context": base_context,
            "assistant_dialogue": [{"layer": "assistant_dialogue", "content": assistant_text}],
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
            assert "核对成本与利润率" in messages[1]["content"]
            return "好的，我会继续按“核对成本与利润率”这个方向处理。"

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
        json={
            "message": "需要",
            "limit": 8,
            "conversation_id": "conv-1",
            "client_context_delta": [
                {"role": "assistant", "content": "需要我帮你核对成本与利润率数据吗？"},
                {"role": "user", "content": "需要"},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "conv-1"
    assert body["answer"] == "好的，我会继续按“核对成本与利润率”这个方向处理。"
    assert body["context_pack"]["included_event_ids"] == ["event-user"]
    assert [item["role"] for item in persisted_turns] == ["user", "assistant"]
    assert persisted_turns[0]["content"] == "需要"
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
