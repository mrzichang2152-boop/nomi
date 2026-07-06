import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_chat_response_contains_latency_trace(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.model_gateway import ModelAnswer

    def fake_persist_turn(conn, redis_client, role, content, conversation_id=None, client_type="web", **kwargs):
        return {
            "conversation_id": conversation_id or "latency-test",
            "turn_id": f"turn-{role}",
            "event_id": f"event-{role}",
            "dialogue_memory_enqueue": {
                "policy": "defer" if role == "user" else "threshold_not_reached",
                "reason": "ordinary_dialogue",
                "pending_turn_count": 2,
                "pending_round_count": 1,
                "batch_created": False,
                "batch_id": None,
                "batch_event_id": None,
            },
        }

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeGateway:
        async def chat(self, messages, temperature=0.4):
            return ModelAnswer(text="ok", provider_id="fake", trace={"fallback_from": []})

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: object())
    monkeypatch.setattr(main, "persist_assistant_turn", fake_persist_turn, raising=False)
    monkeypatch.setattr(main, "find_cached_assistant_response", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "retrieve_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_current_source_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "normalize_client_dialogue_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_agenda_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_task_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "safe_persist_model_request_trace", lambda *args, **kwargs: None, raising=False)
    route_trace_calls = []

    def fake_persist_route_trace(conn, **kwargs):
        route_trace_calls.append(kwargs)
        return "route-trace-1"

    monkeypatch.setattr(main, "safe_persist_context_route_trace", fake_persist_route_trace, raising=False)
    monkeypatch.setattr(main, "model_gateway", lambda: FakeGateway())

    response = TestClient(main.app).post(
        "/api/chat",
        json={"message": "ping", "conversation_id": "latency-test"},
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    trace = body["context_pack"]["latency_trace"]
    chat_route = body["context_pack"]["chat_route"]
    assert trace["total_ms"] >= 0
    assert trace["context_retrieval_ms"] >= 0
    assert trace["model_ms"] >= 0
    assert trace["persist_ms"] >= 0
    assert chat_route["intent"] == "simple_chat"
    assert chat_route["decision"]["intent"] == "simple_chat"
    assert chat_route["fetch_limits"]["input_target_tokens"] == 16000
    assert chat_route["fetch_limits"]["dialogue"] == 30
    assert body["context_pack"]["dialogue_memory_enqueue"]["pending_round_count"] == 1
    assert body["context_pack"]["context_route_trace_id"] == "route-trace-1"
    assert route_trace_calls
    assert route_trace_calls[0]["route_decision"]["intent"] == "simple_chat"
    assert "dialogue_ms" in route_trace_calls[0]["fetch_latency"]


def test_chat_response_uses_explicit_memory_layer_fetchers(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.model_gateway import ModelAnswer

    def fake_persist_turn(conn, redis_client, role, content, conversation_id=None, client_type="web", **kwargs):
        return {
            "conversation_id": conversation_id or "memory-layer-test",
            "turn_id": f"turn-{role}",
            "event_id": f"event-{role}",
            "dialogue_memory_enqueue": {},
        }

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeGateway:
        async def chat(self, messages, temperature=0.4):
            return ModelAnswer(text="PHONE_1 报价截止信息已根据可用上下文核对。", provider_id="fake", trace={})

    calls = []

    def fake_layer_context(query, limit, layer, request_scope=None):
        calls.append((layer, limit))
        return [
            {
                "source_id": f"{layer}:1",
                "layer": {
                    "kv": "working_memory",
                    "graph": "entity_graph",
                    "rag": "vector_recall",
                    "timeline": "timeline",
                }[layer],
                "content": f"{layer} evidence for PHONE_1",
            }
        ]

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: object())
    monkeypatch.setattr(main, "persist_assistant_turn", fake_persist_turn, raising=False)
    monkeypatch.setattr(main, "find_cached_assistant_response", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "retrieve_context", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("combined memory fetcher should not run")), raising=False)
    monkeypatch.setattr(main, "retrieve_memory_layer_context", fake_layer_context, raising=False)
    monkeypatch.setattr(main, "retrieve_current_source_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "normalize_client_dialogue_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_agenda_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_task_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "safe_persist_model_request_trace", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "safe_persist_context_route_trace", lambda *args, **kwargs: "route-trace-memory", raising=False)
    monkeypatch.setattr(main, "model_gateway", lambda: FakeGateway())

    response = TestClient(main.app).post(
        "/api/chat",
        json={"message": "Alice 之前说报价什么时候截止？", "conversation_id": "memory-layer-test"},
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert {layer for layer, _limit in calls} == {"kv", "graph", "rag", "timeline"}
    assert body["context_pack"]["chat_route"]["decision"]["needs"]["memory_graph"] is True
    assert body["context_pack"]["retrieval_modes"]["kv_profile"] == 1
    assert body["context_pack"]["retrieval_modes"]["knowledge_graph_context"] == 1
    assert body["context_pack"]["retrieval_modes"]["rag_event_memory"] == 2
