import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_websocket_streams_chat_delta_and_done(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.model_gateway import ModelStreamChunk

    monkeypatch.setattr(main, "retrieve_context", lambda message, limit, request_scope=None: [{"layer": "semantic_memory", "summary": "用户最近收到订单邮件"}])

    class FakeGateway:
        async def stream_chat(self, messages, temperature=0.4):
            yield ModelStreamChunk(delta="需要", provider_id="test-provider")
            yield ModelStreamChunk(delta="处理", provider_id="test-provider")

    monkeypatch.setattr(main, "model_gateway", lambda: FakeGateway())

    async def no_realtime_listener(websocket):
        await main.asyncio.Event().wait()

    monkeypatch.setattr(main, "redis_realtime_listener", no_realtime_listener)

    client = TestClient(main.app)
    with client.websocket_connect("/ws?password=secret") as websocket:
        websocket.send_json({"type": "chat_message", "message": "我有什么要处理？"})
        first = websocket.receive_json()
        second = websocket.receive_json()
        done = websocket.receive_json()

    assert first == {"type": "chat_delta", "delta": "需要"}
    assert second == {"type": "chat_delta", "delta": "处理"}
    assert done["type"] == "chat_done"
    assert done["answer"] == "需要处理"
    assert done["sources"][0]["layer"] == "semantic_memory"


def test_websocket_reports_chat_stream_failure(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.model_gateway import ModelGatewayError

    monkeypatch.setattr(main, "redis_client", lambda: None)
    monkeypatch.setattr(
        main,
        "persist_assistant_turn",
        lambda *args, **kwargs: {
            "conversation_id": "11111111-1111-1111-1111-111111111111",
            "event_id": "event-1",
            "turn_id": "turn-1",
        },
    )
    monkeypatch.setattr(main, "retrieve_context", lambda message, limit, request_scope=None: [])
    monkeypatch.setattr(main, "retrieve_current_source_context", lambda message, request_scope, limit=6: [])
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda message, conversation_id=None, limit=64: [])
    monkeypatch.setattr(main, "retrieve_active_agenda_context", lambda message, conversation_id=None, limit=6: [])
    monkeypatch.setattr(main, "retrieve_active_task_context", lambda message, conversation_id=None, limit=8: [])
    monkeypatch.setattr(
        main,
        "build_context_pack",
        lambda *args, **kwargs: {
            "included_event_ids": [],
            "assistant_dialogue": [],
            "agenda_context": [],
            "memory_context": [],
            "source_context": [],
            "task_context": [],
            "reason": "test context",
        },
    )
    monkeypatch.setattr(main, "build_chat_messages", lambda message, context_pack: [{"role": "user", "content": message}])

    class FailingGateway:
        async def stream_chat(self, messages, temperature=0.4):
            raise ModelGatewayError(
                "primary unreachable",
                [{"provider_id": "primary", "error_type": "unreachable", "error": "connection refused"}],
            )
            yield None

    monkeypatch.setattr(main, "model_gateway", lambda: FailingGateway())

    class FakeWebSocket:
        def __init__(self):
            self.events = []

        async def send_json(self, event):
            self.events.append(event)

    websocket = FakeWebSocket()
    main.asyncio.run(main.stream_chat_to_websocket(websocket, "测试失败提示", 12))

    assert websocket.events[-1]["type"] == "error"
    assert "模型" in websocket.events[-1]["message"]


def test_stream_chat_to_websocket_uses_model_gateway(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.model_gateway import ModelStreamChunk

    monkeypatch.setattr(main, "redis_client", lambda: None)
    monkeypatch.setattr(
        main,
        "persist_assistant_turn",
        lambda *args, **kwargs: {
            "conversation_id": "11111111-1111-1111-1111-111111111111",
            "event_id": "event-1",
            "turn_id": "turn-1",
        },
    )
    monkeypatch.setattr(main, "retrieve_context", lambda message, limit, request_scope=None: [])
    monkeypatch.setattr(main, "retrieve_current_source_context", lambda message, request_scope, limit=6: [])
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda message, conversation_id=None, limit=64: [])
    monkeypatch.setattr(main, "retrieve_active_agenda_context", lambda message, conversation_id=None, limit=6: [])
    monkeypatch.setattr(main, "retrieve_active_task_context", lambda message, conversation_id=None, limit=8: [])
    monkeypatch.setattr(
        main,
        "build_context_pack",
        lambda *args, **kwargs: {
            "included_event_ids": [],
            "assistant_dialogue": [],
            "agenda_context": [],
            "memory_context": [],
            "source_context": [],
            "task_context": [],
            "reason": "test context",
        },
    )
    monkeypatch.setattr(main, "build_chat_messages", lambda message, context_pack: [{"role": "user", "content": message}])

    class FakeGateway:
        async def stream_chat(self, messages, temperature=0.4):
            yield ModelStreamChunk(delta="网关", provider_id="gateway-provider")
            yield ModelStreamChunk(delta="回复", provider_id="gateway-provider")

    monkeypatch.setattr(main, "model_gateway", lambda: FakeGateway())

    class FakeWebSocket:
        def __init__(self):
            self.events = []

        async def send_json(self, event):
            self.events.append(event)

    websocket = FakeWebSocket()
    main.asyncio.run(main.stream_chat_to_websocket(websocket, "测试网关", 12))

    assert websocket.events[0] == {"type": "chat_delta", "delta": "网关"}
    assert websocket.events[1] == {"type": "chat_delta", "delta": "回复"}
    assert websocket.events[-1]["type"] == "chat_done"
    assert websocket.events[-1]["answer"] == "网关回复"


def test_websocket_rejects_wrong_password(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    client = TestClient(main.app)
    try:
        with client.websocket_connect("/ws?password=wrong"):
            raise AssertionError("wrong password websocket should not connect")
    except Exception as exc:
        assert "1008" in str(exc) or "WebSocketDisconnect" in exc.__class__.__name__
