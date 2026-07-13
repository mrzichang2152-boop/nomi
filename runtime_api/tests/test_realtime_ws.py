import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_chat_input_allows_attachment_only_payload():
    from app import main

    attachment_id = uuid4()
    body = main.ChatIn(message="", attachment_ids=[attachment_id])

    assert body.message == ""
    assert body.attachment_ids == [attachment_id]


def test_http_and_websocket_forward_same_ordered_attachments(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    first = uuid4()
    second = uuid4()
    captured = []

    class Submission:
        def submit_user_turn(self, **kwargs):
            captured.append(
                {
                    "message": kwargs["message"],
                    "attachment_ids": list(kwargs["attachment_ids"]),
                    "conversation_id": kwargs["conversation_id"],
                    "client_type": kwargs["client_type"],
                    "client_request_id": kwargs["client_request_id"],
                }
            )
            return {
                "conversation_id": kwargs["conversation_id"] or "conversation-parity",
                "turn_id": f"turn-{len(captured)}",
                "event_id": f"event-{len(captured)}",
                "content": kwargs["message"],
                "attachment_ids": [str(value) for value in kwargs["attachment_ids"]],
                "duplicate": False,
            }

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(main, "attachment_submission_service", lambda: Submission())
    monkeypatch.setattr(main, "redis_client", lambda: None)
    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(
        main,
        "find_cached_assistant_response",
        lambda conn, request_id: {
            "answer": "cached",
            "conversation_id": "conversation-parity",
        },
    )

    response = TestClient(main.app).post(
        "/api/chat",
        headers={"x-par-password": "secret"},
        json={
            "message": "比较附件",
            "attachment_ids": [str(second), str(first)],
            "conversation_id": "conversation-parity",
            "client_type": "android",
            "client_request_id": "parity-1",
        },
    )
    assert response.status_code == 200

    monkeypatch.setattr(
        main,
        "persist_assistant_turn",
        lambda *args, **kwargs: {
            "conversation_id": kwargs.get("conversation_id") or "conversation-parity",
            "turn_id": "assistant-turn",
            "event_id": "assistant-event",
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
            "reason": "attachment parity",
        },
    )
    monkeypatch.setattr(main, "build_chat_messages", lambda message, context_pack: [{"role": "user", "content": message}])
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "safe_persist_context_route_trace", lambda *args, **kwargs: None, raising=False)

    class Gateway:
        async def stream_chat(self, messages, temperature=0.4):
            from app.model_gateway import ModelStreamChunk

            yield ModelStreamChunk(delta="完成", provider_id="test-provider")

    monkeypatch.setattr(main, "model_gateway", lambda: Gateway())

    class WebSocket:
        def __init__(self):
            self.events = []

        async def send_json(self, event):
            self.events.append(event)

    websocket = WebSocket()
    main.asyncio.run(
        main.stream_chat_to_websocket(
            websocket,
            "比较附件",
            12,
            conversation_id="conversation-parity",
            client_type="android",
            client_request_id="parity-1",
            attachment_ids=[second, first],
        )
    )

    assert captured == [
        {
            "message": "比较附件",
            "attachment_ids": [second, first],
            "conversation_id": "conversation-parity",
            "client_type": "android",
            "client_request_id": "parity-1",
        },
        {
            "message": "比较附件",
            "attachment_ids": [second, first],
            "conversation_id": "conversation-parity",
            "client_type": "android",
            "client_request_id": "parity-1",
        },
    ]
    assert websocket.events[-1]["type"] == "chat_done"


def test_http_and_websocket_return_same_attachment_error_code(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.attachments.service import AttachmentSubmissionError

    attachment_id = uuid4()

    class Submission:
        def submit_user_turn(self, **kwargs):
            raise AttachmentSubmissionError(
                "attachment_not_ready",
                "文件仍在处理中，请稍后重试。",
                http_status=409,
            )

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(main, "attachment_submission_service", lambda: Submission())
    monkeypatch.setattr(main, "redis_client", lambda: None)
    monkeypatch.setattr(main, "db", lambda: Conn())

    response = TestClient(main.app).post(
        "/api/chat",
        headers={"x-par-password": "secret"},
        json={"message": "分析", "attachment_ids": [str(attachment_id)]},
    )

    class WebSocket:
        def __init__(self):
            self.events = []

        async def send_json(self, event):
            self.events.append(event)

    websocket = WebSocket()
    main.asyncio.run(
        main.stream_chat_to_websocket(
            websocket,
            "分析",
            12,
            attachment_ids=[attachment_id],
        )
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "attachment_not_ready"
    assert websocket.events == [
        {
            "type": "error",
            "code": "attachment_not_ready",
            "message": "文件仍在处理中，请稍后重试。",
        }
    ]


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

    assert first["type"] == "chat_delta"
    assert first["delta"] == "需要"
    assert first["is_first_delta"] is True
    assert isinstance(first["elapsed_ms"], int)
    assert isinstance(first["stream_first_token_ms"], int)
    assert isinstance(first["model_first_token_ms"], int)
    assert second["type"] == "chat_delta"
    assert second["delta"] == "处理"
    assert second.get("is_first_delta") is not True
    assert isinstance(second["elapsed_ms"], int)
    assert done["type"] == "chat_done"
    assert done["answer"] == "需要处理"
    assert done["sources"][0]["layer"] == "semantic_memory"
    assert isinstance(done["context_pack"]["latency_trace"]["stream_first_token_ms"], int)
    assert isinstance(done["context_pack"]["latency_trace"]["model_ms"], int)


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

    assert websocket.events[0]["type"] == "chat_delta"
    assert websocket.events[0]["delta"] == "网关"
    assert websocket.events[0]["is_first_delta"] is True
    assert websocket.events[0]["stream_first_token_ms"] >= 0
    assert websocket.events[0]["model_first_token_ms"] >= 0
    assert websocket.events[1]["type"] == "chat_delta"
    assert websocket.events[1]["delta"] == "回复"
    assert websocket.events[1].get("is_first_delta") is not True
    assert websocket.events[-1]["type"] == "chat_done"
    assert websocket.events[-1]["answer"] == "网关回复"
    latency_trace = websocket.events[-1]["context_pack"]["latency_trace"]
    assert latency_trace["stream_first_token_ms"] >= 0
    assert latency_trace["model_first_token_ms"] >= 0
    assert latency_trace["model_ms"] >= latency_trace["model_first_token_ms"]
    assert latency_trace["total_ms"] >= latency_trace["stream_first_token_ms"]


def test_websocket_rejects_wrong_password(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    client = TestClient(main.app)
    try:
        with client.websocket_connect("/ws?password=wrong"):
            raise AssertionError("wrong password websocket should not connect")
    except Exception as exc:
        assert "1008" in str(exc) or "WebSocketDisconnect" in exc.__class__.__name__
