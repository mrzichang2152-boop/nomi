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


def test_http_chat_routes_explicit_nomi_gmail_request_without_calling_model(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    persisted = []

    class Submission:
        def submit_user_turn(self, **kwargs):
            return {
                "conversation_id": "conversation-nomi-gmail-http",
                "turn_id": "turn-user",
                "event_id": "event-user",
                "content": kwargs["message"],
                "attachment_ids": [],
                "duplicate": False,
            }

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def persist_turn(*args, **kwargs):
        persisted.append(kwargs)
        return {
            "conversation_id": kwargs["conversation_id"],
            "turn_id": "turn-assistant",
            "event_id": "event-assistant",
        }

    monkeypatch.setattr(main, "attachment_submission_service", lambda: Submission())
    monkeypatch.setattr(main, "redis_client", lambda: None)
    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "find_cached_assistant_response", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "load_completed_artifact_delivery_for_followup", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "find_pending_open_task_for_conversation", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "persist_assistant_turn", persist_turn)
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "safe_persist_context_route_trace", lambda *args, **kwargs: "route-nomi-gmail")
    monkeypatch.setattr(
        main,
        "prepare_nomi_gmail_chat_action",
        lambda *args, **kwargs: {
            "status": "draft_ready",
            "answer": "我已用 Nomi 自己的 Gmail 准备好草稿，尚未发送，请确认。",
            "draft": {
                "draft_id": "draft-http",
                "confirmation_required": True,
                "send_called": False,
            },
            "route_decision": {"pipeline_id": "reply_pipeline", "tool_name": "assistant.email.send"},
        },
        raising=False,
    )

    class ForbiddenGateway:
        async def chat(self, *args, **kwargs):
            raise AssertionError("deterministic Nomi Gmail route must not call the model")

    monkeypatch.setattr(main, "model_gateway", lambda: ForbiddenGateway())

    response = TestClient(main.app).post(
        "/api/chat",
        headers={"x-par-password": "secret"},
        json={
            "message": "用你的gmail邮箱给 Mrzichang@icloud.com这个邮箱发个邮件 提醒他别迟到",
            "conversation_id": "conversation-nomi-gmail-http",
            "client_type": "android",
            "client_request_id": "request-nomi-gmail-http",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assistant_draft"]["draft_id"] == "draft-http"
    assert payload["context_pack"]["retrieval_modes"]["task_route"] == "assistant_owned_gmail"
    assert payload["context_pack"]["latency_trace"]["model_ms"] == 0
    assert persisted[-1]["content"] == payload["answer"]


def test_websocket_routes_explicit_nomi_gmail_request_without_calling_model(monkeypatch):
    from app import main

    class Submission:
        def submit_user_turn(self, **kwargs):
            return {
                "conversation_id": "conversation-nomi-gmail-ws",
                "turn_id": "turn-user",
                "event_id": "event-user",
                "content": kwargs["message"],
                "attachment_ids": [],
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
    monkeypatch.setattr(main, "load_completed_artifact_delivery_for_followup", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "find_pending_open_task_for_conversation", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        main,
        "persist_assistant_turn",
        lambda *args, **kwargs: {
            "conversation_id": kwargs["conversation_id"],
            "turn_id": "turn-assistant",
            "event_id": "event-assistant",
        },
    )
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "safe_persist_context_route_trace", lambda *args, **kwargs: "route-nomi-gmail")
    monkeypatch.setattr(
        main,
        "prepare_nomi_gmail_chat_action",
        lambda *args, **kwargs: {
            "status": "draft_ready",
            "answer": "我已用 Nomi 自己的 Gmail 准备好草稿，尚未发送，请确认。",
            "draft": {
                "draft_id": "draft-ws",
                "confirmation_required": True,
                "send_called": False,
            },
            "route_decision": {"pipeline_id": "reply_pipeline", "tool_name": "assistant.email.send"},
        },
        raising=False,
    )

    class ForbiddenGateway:
        async def stream_chat(self, *args, **kwargs):
            raise AssertionError("deterministic Nomi Gmail route must not call the model")
            yield None

    monkeypatch.setattr(main, "model_gateway", lambda: ForbiddenGateway())

    class WebSocket:
        def __init__(self):
            self.events = []

        async def send_json(self, event):
            self.events.append(event)

    websocket = WebSocket()
    main.asyncio.run(
        main.stream_chat_to_websocket(
            websocket,
            "用你的gmail邮箱给 Mrzichang@icloud.com这个邮箱发个邮件 提醒他别迟到",
            12,
            conversation_id="conversation-nomi-gmail-ws",
            client_type="android",
            client_request_id="request-nomi-gmail-ws",
        )
    )

    assert [item["type"] for item in websocket.events] == ["chat_delta", "chat_done"]
    assert websocket.events[-1]["assistant_draft"]["draft_id"] == "draft-ws"
    assert websocket.events[-1]["context_pack"]["latency_trace"]["model_ms"] == 0


def test_http_and_websocket_forward_same_ordered_attachments(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    first = uuid4()
    second = uuid4()
    conversation_id = uuid4()
    user_turn_id = uuid4()
    user_event_id = uuid4()
    captured = []
    retrieved = []
    packed_attachment_context = []

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
                "conversation_id": kwargs["conversation_id"] or str(conversation_id),
                "turn_id": str(user_turn_id),
                "event_id": str(user_event_id),
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
            "conversation_id": str(conversation_id),
        },
    )

    response = TestClient(main.app).post(
        "/api/chat",
        headers={"x-par-password": "secret"},
        json={
            "message": "比较附件",
            "attachment_ids": [str(second), str(first)],
            "conversation_id": str(conversation_id),
            "client_type": "android",
            "client_request_id": "parity-1",
        },
    )
    assert response.status_code == 200

    monkeypatch.setattr(
        main,
        "persist_assistant_turn",
        lambda *args, **kwargs: {
            "conversation_id": kwargs.get("conversation_id") or str(conversation_id),
            "turn_id": "assistant-turn",
            "event_id": "assistant-event",
        },
    )
    monkeypatch.setattr(main, "retrieve_context", lambda message, limit, request_scope=None: [])
    monkeypatch.setattr(main, "retrieve_current_source_context", lambda message, request_scope, limit=6: [])
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda message, conversation_id=None, limit=64: [])
    monkeypatch.setattr(main, "retrieve_active_agenda_context", lambda message, conversation_id=None, limit=6: [])
    monkeypatch.setattr(main, "retrieve_active_task_context", lambda message, conversation_id=None, limit=8: [])

    def fake_retrieve_attachment_context(message, **kwargs):
        retrieved.append({"message": message, **kwargs})
        return [
            {
                "layer": "attachment_evidence",
                "source": "attachment",
                "source_id": "attachment-evidence-1",
                "attachment_id": str(second),
                "filename": "brief.txt",
                "content": "Project codename MossQuartz.",
            }
        ]

    def fake_build_context_pack(*args, **kwargs):
        packed_attachment_context.extend(kwargs.get("attachment_context") or [])
        return {
            "included_event_ids": [],
            "included_memory_ids": [],
            "included_agenda_ids": [],
            "included_web_source_ids": [],
            "assistant_dialogue": [],
            "agenda_context": [],
            "memory_context": [],
            "source_context": [],
            "web_context": [],
            "attachment_context": list(kwargs.get("attachment_context") or []),
            "task_context": [],
            "sections": [],
            "excluded": [],
            "warnings": [],
            "reason": "attachment parity",
        }

    monkeypatch.setattr(main, "retrieve_attachment_context_for_chat", fake_retrieve_attachment_context)
    monkeypatch.setattr(
        main,
        "build_context_pack",
        fake_build_context_pack,
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
            conversation_id=str(conversation_id),
            client_type="android",
            client_request_id="parity-1",
            attachment_ids=[second, first],
        )
    )

    assert captured == [
        {
            "message": "比较附件",
            "attachment_ids": [second, first],
            "conversation_id": str(conversation_id),
            "client_type": "android",
            "client_request_id": "parity-1",
        },
        {
            "message": "比较附件",
            "attachment_ids": [second, first],
            "conversation_id": str(conversation_id),
            "client_type": "android",
            "client_request_id": "parity-1",
        },
    ]
    assert len(retrieved) == 1
    assert retrieved[0]["message"] == "比较附件"
    assert retrieved[0]["current_attachment_ids"] == [second, first]
    assert retrieved[0]["conversation_id"] == conversation_id
    assert retrieved[0]["current_turn_id"] == user_turn_id
    assert retrieved[0]["route_requires_file_evidence"] is True
    assert packed_attachment_context[0]["content"] == "Project codename MossQuartz."
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


def test_websocket_asks_clarification_before_opencode_for_vague_ppt(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    requested_inputs = []
    created_tasks = []

    monkeypatch.setattr(main, "redis_client", lambda: None)
    monkeypatch.setattr(
        main,
        "persist_assistant_turn",
        lambda *args, **kwargs: {
            "conversation_id": kwargs.get("conversation_id") or "conv-ws-open-clarify",
            "event_id": f"event-{kwargs.get('role', 'turn')}",
            "turn_id": f"turn-{kwargs.get('role', 'turn')}",
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
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "safe_persist_context_route_trace", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(
        main,
        "create_opencode_artifact_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("OpenCode must not start before clarification")),
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "run_opencode_artifact_worker_once",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("worker must not run before clarification")),
        raising=False,
    )

    class FakeLongTailRunner:
        def __init__(self):
            self.state = {}

        def create_task(self, *, original_goal, route_decision, plan):
            created_tasks.append({"original_goal": original_goal, "route_decision": route_decision, "plan": plan})
            self.state = {
                "task_id": "lta_ws_open_clarify",
                "status": "created",
                "current_node": "select_step",
                "route_decision": route_decision,
                "original_goal": original_goal,
                "plan_version": 1,
                "completed_steps": [],
            }
            return dict(self.state)

        def request_human_input(self, task_id, *, step_id=None, input_type="clarification", question="", options=None):
            requested_inputs.append(
                {
                    "task_id": task_id,
                    "step_id": step_id,
                    "input_type": input_type,
                    "question": question,
                    "options": options or [],
                }
            )
            self.state["status"] = "waiting_user"
            self.state["current_node"] = "waiting_for_human_input"
            self.state["pending_human_input"] = requested_inputs[-1]
            return {"event_type": "human_input.requested", **requested_inputs[-1]}

        def get_task_state(self, task_id):
            return dict(self.state)

    fake_runner = FakeLongTailRunner()
    monkeypatch.setattr(main, "long_tail_runner", lambda: fake_runner, raising=False)

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "db", lambda: Conn())

    class FakeWebSocket:
        def __init__(self):
            self.events = []

        async def send_json(self, event):
            self.events.append(event)

    websocket = FakeWebSocket()
    main.asyncio.run(
        main.stream_chat_to_websocket(
            websocket,
            "帮我做一个 AI 生成视频原理的 PPT 可以用来讲解",
            12,
            conversation_id="conv-ws-open-clarify",
            public_base_url="http://testserver",
        )
    )

    assert websocket.events[0]["type"] == "chat_delta"
    assert "先确认" in websocket.events[0]["delta"]
    assert "普通人" in websocket.events[0]["delta"]
    assert websocket.events[-1]["type"] == "chat_done"
    assert websocket.events[-1]["task"]["task_id"] == "lta_ws_open_clarify"
    assert websocket.events[-1]["task"]["status"] == "waiting_user"
    assert websocket.events[-1]["task"]["current_node"] == "waiting_for_human_input"
    assert websocket.events[-1]["task"]["clarification"]["missing_fields"] == ["audience", "depth"]
    assert requested_inputs[0]["input_type"] == "open_task_clarification"
    assert created_tasks[0]["route_decision"]["clarification_gate"]["status"] == "needs_clarification"


def test_websocket_resumes_pending_open_task_after_user_clarifies(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner

    runner = LongTailGraphRunner(event_store=LongTailEventStore())
    monkeypatch.setattr(main, "_LONG_TAIL_RUNNER", runner, raising=False)
    monkeypatch.setattr(main, "redis_client", lambda: None)
    monkeypatch.setattr(
        main,
        "persist_assistant_turn",
        lambda *args, **kwargs: {
            "conversation_id": kwargs.get("conversation_id") or "conv-ws-open-resume",
            "event_id": f"event-{kwargs.get('role', 'turn')}",
            "turn_id": f"turn-{kwargs.get('role', 'turn')}",
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
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "safe_persist_context_route_trace", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "ENABLE_OPENCODE_ARTIFACT_INLINE_RUN", False, raising=False)

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "db", lambda: Conn())

    class GatewayShouldNotRun:
        async def stream_chat(self, *args, **kwargs):
            raise AssertionError("clarification follow-up must resume task, not call chat model")
            yield None

    monkeypatch.setattr(main, "model_gateway", lambda: GatewayShouldNotRun())

    class FakeWebSocket:
        def __init__(self):
            self.events = []

        async def send_json(self, event):
            self.events.append(event)

    first_socket = FakeWebSocket()
    main.asyncio.run(
        main.stream_chat_to_websocket(
            first_socket,
            "帮我做一个 AI 生成视频原理的 PPT 可以用来讲解",
            12,
            conversation_id="conv-ws-open-resume",
            public_base_url="http://testserver",
        )
    )
    pending_task_id = first_socket.events[-1]["task"]["task_id"]

    second_socket = FakeWebSocket()
    main.asyncio.run(
        main.stream_chat_to_websocket(
            second_socket,
            "普通人，10页，偏科普，可以多用类比",
            12,
            conversation_id="conv-ws-open-resume",
            public_base_url="http://testserver",
        )
    )

    assert second_socket.events[0]["type"] == "chat_delta"
    assert "开始生成" in second_socket.events[0]["delta"]
    assert second_socket.events[-1]["type"] == "chat_done"
    assert second_socket.events[-1]["task"]["task_id"] == pending_task_id
    assert second_socket.events[-1]["task"]["status"] == "running"
    assert second_socket.events[-1]["task"]["current_node"] == "select_step"
    assert second_socket.events[-1]["task"]["requirements_contract"]["audience"] == "普通人"
    assert second_socket.events[-1]["task"]["requirements_contract"]["page_count"] == 10


def test_websocket_resumes_android_english_ppt_clarification_without_repeating_question(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner

    runner = LongTailGraphRunner(event_store=LongTailEventStore())
    monkeypatch.setattr(main, "_LONG_TAIL_RUNNER", runner, raising=False)
    monkeypatch.setattr(main, "redis_client", lambda: None)
    monkeypatch.setattr(
        main,
        "persist_assistant_turn",
        lambda *args, **kwargs: {
            "conversation_id": kwargs.get("conversation_id") or "conv-ws-android-ppt-resume",
            "event_id": f"event-{kwargs.get('role', 'turn')}",
            "turn_id": f"turn-{kwargs.get('role', 'turn')}",
        },
    )
    monkeypatch.setattr(main, "retrieve_context", lambda message, limit, request_scope=None: [])
    monkeypatch.setattr(main, "retrieve_current_source_context", lambda message, request_scope, limit=6: [])
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda message, conversation_id=None, limit=64: [])
    monkeypatch.setattr(main, "retrieve_active_agenda_context", lambda message, conversation_id=None, limit=6: [])
    monkeypatch.setattr(main, "retrieve_active_task_context", lambda message, conversation_id=None, limit=8: [])
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "safe_persist_context_route_trace", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "ENABLE_OPENCODE_ARTIFACT_INLINE_RUN", False, raising=False)

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "db", lambda: Conn())

    class GatewayShouldNotRun:
        async def stream_chat(self, *args, **kwargs):
            raise AssertionError("clarification follow-up must resume task, not call chat model")
            yield None

    monkeypatch.setattr(main, "model_gateway", lambda: GatewayShouldNotRun())

    class FakeWebSocket:
        def __init__(self):
            self.events = []

        async def send_json(self, event):
            self.events.append(event)

    first_socket = FakeWebSocket()
    main.asyncio.run(
        main.stream_chat_to_websocket(
            first_socket,
            (
                "Create a 2-slide PPTX titled Android verification. "
                "Slide 1: title. Slide 2: latency 2 seconds and status available. "
                "Do not invent data."
            ),
            12,
            conversation_id="conv-ws-android-ppt-resume",
            public_base_url="http://testserver",
        )
    )
    pending_task_id = first_socket.events[-1]["task"]["task_id"]
    assert first_socket.events[-1]["task"]["status"] == "waiting_user"

    second_socket = FakeWebSocket()
    main.asyncio.run(
        main.stream_chat_to_websocket(
            second_socket,
            (
                "Audience is managers. Purpose is a 2-minute system verification. "
                "Exactly 2 slides. Proceed now."
            ),
            12,
            conversation_id="conv-ws-android-ppt-resume",
            public_base_url="http://testserver",
        )
    )

    first_delta = second_socket.events[0]["delta"]
    task = second_socket.events[-1]["task"]
    assert "开始生成" in first_delta
    assert "先确认" not in first_delta
    assert task["task_id"] == pending_task_id
    assert task["status"] == "running"
    assert task["current_node"] == "select_step"
    assert task["requirements_contract"]["audience"] == "管理层"
    assert task["requirements_contract"]["purpose"] == "2-minute system verification"
    assert task["requirements_contract"]["page_count"] == 2


def test_websocket_routes_ppt_artifact_request_to_done_without_model(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    monkeypatch.setattr(main, "redis_client", lambda: None)
    monkeypatch.setattr(
        main,
        "persist_assistant_turn",
        lambda *args, **kwargs: {
            "conversation_id": "11111111-1111-1111-1111-111111111111",
            "event_id": f"event-{kwargs.get('role', 'turn')}",
            "turn_id": f"turn-{kwargs.get('role', 'turn')}",
        },
    )
    monkeypatch.setattr(
        main,
        "retrieve_context",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("self-contained websocket artifact request must not retrieve long-term memory")
        ),
    )
    monkeypatch.setattr(
        main,
        "retrieve_current_source_context",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("self-contained websocket artifact request must not retrieve private sources")
        ),
    )
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "safe_persist_context_route_trace", lambda *args, **kwargs: None, raising=False)

    monkeypatch.setattr(
        main,
        "persist_artifact_task_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("artifact requests must not use the legacy ppt pipeline")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "maybe_generate_pptx_artifact_for_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("artifact requests must not directly generate a pptx")
        ),
        raising=False,
    )

    class FakeLongTailRunner:
        def __init__(self):
            self.state = {}

        def create_task(self, *, original_goal, route_decision, plan):
            assert route_decision["route_type"] == "long_tail_agent"
            assert route_decision["executor_adapter"] == "opencode"
            assert plan["steps"][1]["step_id"] == "opencode_execute_artifact"
            self.state = {
                "task_id": "lta_ppt_1",
                "status": "running",
                "current_node": "select_step",
                "route_decision": route_decision,
                "original_goal": original_goal,
                "plan_version": 1,
                "completed_steps": [],
            }
            return dict(self.state)

        def run_next(self, task_id):
            self.state["current_node"] = "awaiting_executor"
            return {
                "task_id": task_id,
                "step_id": "gather_artifact_context",
                "step_objective": "收集生成产物所需的私有上下文和证据。",
                "allowed_actions": ["nomi.context.read_scoped"],
                "forbidden_actions": ["browser.submit", "message.send", "payment.transfer"],
                "expected_outputs": ["scoped_context_pack"],
                "verification_criteria": ["上下文必须可追溯到真实来源。"],
            }

        def get_task_state(self, task_id):
            return dict(self.state)

    fake_runner = FakeLongTailRunner()
    monkeypatch.setattr(main, "long_tail_runner", lambda: fake_runner, raising=False)

    class GatewayShouldNotRun:
        async def stream_chat(self, *args, **kwargs):
            raise AssertionError("artifact requests must not call model streaming")
            yield None

    monkeypatch.setattr(main, "model_gateway", lambda: GatewayShouldNotRun())

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "db", lambda: Conn())

    class FakeWebSocket:
        def __init__(self):
            self.events = []

        async def send_json(self, event):
            self.events.append(event)

    websocket = FakeWebSocket()
    main.asyncio.run(
        main.stream_chat_to_websocket(
            websocket,
            "那你帮我做一个ppt 让普通人可以理解llm的工作原理",
            12,
            public_base_url="http://testserver",
        )
    )

    assert websocket.events[0]["type"] == "chat_delta"
    assert "OpenCode" in websocket.events[0]["delta"]
    assert "已生成 PPT 文件" not in websocket.events[0]["delta"]
    assert "/api/artifacts/" not in websocket.events[0]["delta"]
    assert websocket.events[-1]["type"] == "chat_done"
    assert websocket.events[-1]["task"]["task_run_id"] == "lta_ppt_1"
    assert websocket.events[-1]["task"]["route_type"] == "long_tail_agent"
    assert websocket.events[-1]["task"]["executor_adapter"] == "opencode"
    assert websocket.events[-1]["task"]["current_node"] == "awaiting_executor"
    assert websocket.events[-1]["task"]["requirements_contract"]["audience"] == "普通人"
    assert websocket.events[-1]["task"]["requirements_contract"]["page_count"] == 10
    assert websocket.events[-1]["task"]["requirements_contract"]["depth"] == "科普"
    assert websocket.events[-1]["task"]["artifacts"] == []
    assert websocket.events[-1]["task"]["step_packet"]["step_id"] == "gather_artifact_context"
    assert websocket.events[-1]["context_pack"]["artifact_count"] == 0


def test_websocket_can_inline_run_opencode_artifact_worker_and_stream_download_link(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    monkeypatch.setattr(main, "ENABLE_OPENCODE_ARTIFACT_INLINE_RUN", True, raising=False)
    monkeypatch.setattr(main, "redis_client", lambda: None)
    monkeypatch.setattr(
        main,
        "persist_assistant_turn",
        lambda *args, **kwargs: {
            "conversation_id": "11111111-1111-1111-1111-111111111111",
            "event_id": f"event-{kwargs.get('role', 'turn')}",
            "turn_id": f"turn-{kwargs.get('role', 'turn')}",
        },
    )
    monkeypatch.setattr(main, "retrieve_context", lambda message, limit, request_scope=None: [])
    monkeypatch.setattr(main, "retrieve_current_source_context", lambda message, request_scope, limit=6: [])
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "safe_persist_context_route_trace", lambda *args, **kwargs: None, raising=False)

    class FakeLongTailRunner:
        def __init__(self):
            self.state = {}

        def create_task(self, *, original_goal, route_decision, plan):
            self.state = {
                "task_id": "lta_ppt_inline_ws",
                "status": "running",
                "current_node": "select_step",
                "route_decision": route_decision,
                "original_goal": original_goal,
                "plan_version": 1,
                "completed_steps": [],
            }
            return dict(self.state)

        def run_next(self, task_id):
            self.state["current_node"] = "awaiting_executor"
            return {
                "task_id": task_id,
                "step_id": "gather_artifact_context",
                "step_objective": "收集生成产物所需的私有上下文和证据。",
                "allowed_actions": ["nomi.context.read_scoped"],
                "forbidden_actions": ["browser.submit", "message.send", "payment.transfer"],
                "expected_outputs": ["scoped_context_pack"],
                "verification_criteria": ["上下文必须可追溯到真实来源。"],
            }

        def get_task_state(self, task_id):
            return dict(self.state)

    monkeypatch.setattr(main, "long_tail_runner", lambda: FakeLongTailRunner(), raising=False)

    worker_calls = []

    def fake_run_worker(task_id):
        worker_calls.append(task_id)
        return {
            "status": "completed",
            "artifact": {
                "artifact_id": "artifact_ws_ppt",
                "task_run_id": task_id,
                "artifact_type": "pptx",
                "filename": "LLM工作原理.pptx",
                "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "storage_path": "/tmp/LLM工作原理.pptx",
                "slide_count": 6,
                "verification_status": "verified",
            },
        }

    monkeypatch.setattr(main, "run_opencode_artifact_worker_once", fake_run_worker, raising=False)

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "db", lambda: Conn())

    class FakeWebSocket:
        def __init__(self):
            self.events = []

        async def send_json(self, event):
            self.events.append(event)

    websocket = FakeWebSocket()
    main.asyncio.run(
        main.stream_chat_to_websocket(
            websocket,
            "那你帮我做一个ppt 让普通人可以理解llm的工作原理",
            12,
            public_base_url="http://testserver",
        )
    )

    assert worker_calls == ["lta_ppt_inline_ws"]
    assert websocket.events[0]["type"] == "chat_delta"
    assert any(event.get("type") == "chat_delta" and "已生成 PPT 文件" in event.get("delta", "") for event in websocket.events)
    assert websocket.events[-1]["type"] == "chat_done"
    assert websocket.events[-1]["task"]["status"] == "completed"
    assert websocket.events[-1]["task"]["artifacts"][0]["download_url"] == "http://testserver/api/artifacts/artifact_ws_ppt/download"
    assert "已生成 PPT 文件" in websocket.events[-1]["answer"]
    assert "LLM工作原理.pptx" in websocket.events[-1]["answer"]
    assert websocket.events[-1]["context_pack"]["artifact_count"] == 1


def test_websocket_returns_completed_opencode_artifact_when_user_asks_status(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    persisted_turns = []

    def fake_persist_turn(conn, redis_client, role, content, conversation_id=None, client_type="web", **kwargs):
        persisted_turns.append({"role": role, "content": content, "conversation_id": conversation_id})
        return {
            "conversation_id": conversation_id or "conv-ws-artifact-status",
            "event_id": f"event-{role}-{len(persisted_turns)}",
            "turn_id": f"turn-{role}-{len(persisted_turns)}",
        }

    completed_artifact = {
        "task": {
            "task_run_id": "lta_ws_done_ppt",
            "task_id": "lta_ws_done_ppt",
            "task_type": "artifact_creation",
            "artifact_type": "pptx",
            "pipeline_id": "open_task_opencode_artifact_pipeline",
            "route_type": "long_tail_agent",
            "executor_adapter": "opencode",
            "status": "completed",
            "current_node": "delivered",
            "current_step_id": "verify_artifact_delivery",
            "title": "生成 PPT",
            "source_event_ids": [],
            "requirements_contract": {"page_count": 6, "audience": "普通人"},
        },
        "payload": {"route": {"artifact_type": "pptx"}},
        "artifacts": [
            {
                "artifact_id": "artifact_ws_done_ppt",
                "task_run_id": "lta_ws_done_ppt",
                "artifact_type": "pptx",
                "filename": "AI_video_generation_for_presentation_ws.pptx",
                "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "download_url": "http://testserver/api/artifacts/artifact_ws_done_ppt/download",
                "verification_status": "verified",
            }
        ],
    }

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: None)
    monkeypatch.setattr(main, "persist_assistant_turn", fake_persist_turn)
    monkeypatch.setattr(main, "find_pending_open_task_for_conversation", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(
        main,
        "find_latest_completed_artifact_delivery_for_conversation",
        lambda conn, conversation_id, public_base_url="": completed_artifact
        if conversation_id == "conv-ws-artifact-status"
        else None,
        raising=False,
    )

    class GatewayShouldNotRun:
        async def stream_chat(self, *args, **kwargs):
            raise AssertionError("artifact status follow-up must not call streaming model")
            yield None

    monkeypatch.setattr(main, "model_gateway", lambda: GatewayShouldNotRun())

    class FakeWebSocket:
        def __init__(self):
            self.events = []

        async def send_json(self, event):
            self.events.append(event)

    websocket = FakeWebSocket()
    main.asyncio.run(
        main.stream_chat_to_websocket(
            websocket,
            "还没做好吗",
            12,
            conversation_id="conv-ws-artifact-status",
            public_base_url="http://testserver",
        )
    )

    assert websocket.events[0]["type"] == "chat_delta"
    assert "已生成 PPT 文件" in websocket.events[0]["delta"]
    assert websocket.events[-1]["type"] == "chat_done"
    assert websocket.events[-1]["task"]["task_run_id"] == "lta_ws_done_ppt"
    assert websocket.events[-1]["task"]["artifacts"][0]["artifact_id"] == "artifact_ws_done_ppt"
    assert websocket.events[-1]["artifacts"][0]["download_url"] == "http://testserver/api/artifacts/artifact_ws_done_ppt/download"
    assert websocket.events[-1]["context_pack"]["retrieval_modes"]["task_route"] == "completed_artifact_delivery"
    assert persisted_turns[-1]["role"] == "assistant"


def test_websocket_rejects_wrong_password(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    client = TestClient(main.app)
    try:
        with client.websocket_connect("/ws?password=wrong"):
            raise AssertionError("wrong password websocket should not connect")
    except Exception as exc:
        assert "1008" in str(exc) or "WebSocketDisconnect" in exc.__class__.__name__
