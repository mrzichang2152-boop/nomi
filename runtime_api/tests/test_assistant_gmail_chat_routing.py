import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_parse_real_android_nomi_gmail_request():
    from app.assistant_identity.chat_routing import parse_nomi_gmail_command

    command = parse_nomi_gmail_command(
        "用你的gmail邮箱给 Mrzichang@icloud.com这个邮箱发个邮件 提醒他别迟到"
    )

    assert command is not None
    assert command.recipient == "Mrzichang@icloud.com"
    assert command.subject == "提醒"
    assert command.body_text == "提醒您别迟到。"


def test_user_owned_gmail_request_does_not_route_to_nomi_identity():
    from app.assistant_identity.chat_routing import parse_nomi_gmail_command

    assert (
        parse_nomi_gmail_command(
            "用我的 Gmail 给 alice@example.com 发邮件，说我晚点到"
        )
        is None
    )


def test_prepare_action_asks_for_missing_recipient_without_creating_draft():
    from app.assistant_identity.chat_routing import prepare_nomi_gmail_chat_action

    class Registry:
        def get(self, identity_id):
            raise AssertionError("identity must not be read before required slots are complete")

    class Outbound:
        def prepare_draft(self, **kwargs):
            raise AssertionError("draft must not be created without a recipient")

    action = prepare_nomi_gmail_chat_action(
        "用你的邮箱发一封邮件，提醒对方别迟到",
        event_id="event-missing-recipient",
        client_request_id="request-missing-recipient",
        identity_registry=Registry(),
        outbound_pipeline=Outbound(),
    )

    assert action is not None
    assert action["status"] == "needs_user_input"
    assert "收件人邮箱地址" in action["answer"]
    assert "draft" not in action


def test_prepare_action_asks_for_missing_body_without_creating_draft():
    from app.assistant_identity.chat_routing import prepare_nomi_gmail_chat_action

    class Registry:
        def get(self, identity_id):
            raise AssertionError("identity must not be read before required slots are complete")

    class Outbound:
        def prepare_draft(self, **kwargs):
            raise AssertionError("draft must not be created without a body")

    action = prepare_nomi_gmail_chat_action(
        "用你的 Gmail 给 alice@example.com 发一封邮件",
        event_id="event-missing-body",
        client_request_id="request-missing-body",
        identity_registry=Registry(),
        outbound_pipeline=Outbound(),
    )

    assert action is not None
    assert action["status"] == "needs_user_input"
    assert "邮件正文" in action["answer"]
    assert "draft" not in action


def test_prepare_action_creates_confirmation_required_nomi_draft_once():
    from app.assistant_identity.chat_routing import prepare_nomi_gmail_chat_action
    from app.assistant_identity.models import AssistantIdentity

    calls = []

    class Registry:
        def get(self, identity_id):
            assert identity_id == "nomi_gmail_primary"
            return AssistantIdentity(
                identity_id=identity_id,
                kind="assistant_gmail",
                display_name="Nomi",
                address="nomi@example.com",
                provider="composio",
                capabilities=["draft", "send", "receive"],
                status="connected",
            )

    class Outbound:
        def prepare_draft(self, **kwargs):
            calls.append(kwargs)
            return {
                "draft_id": "draft-real-request",
                "identity_id": kwargs["identity_id"],
                "channel": kwargs["channel"],
                "recipient": kwargs["recipient"],
                "subject": kwargs["subject"],
                "body_text": kwargs["body_text"],
                "status": "draft",
                "confirmation_required": True,
                "send_called": False,
                "confirmation_card": {"actions": ["send", "edit", "cancel"]},
            }

    action = prepare_nomi_gmail_chat_action(
        "用你的gmail邮箱给 Mrzichang@icloud.com这个邮箱发个邮件 提醒他别迟到",
        event_id="event-real-request",
        client_request_id="request-real-request",
        identity_registry=Registry(),
        outbound_pipeline=Outbound(),
    )

    assert action is not None
    assert action["status"] == "draft_ready"
    assert action["draft"]["confirmation_required"] is True
    assert action["draft"]["send_called"] is False
    assert "尚未发送" in action["answer"]
    assert "确认" in action["answer"]
    assert calls == [
        {
            "identity_id": "nomi_gmail_primary",
            "channel": "gmail",
            "recipient": "Mrzichang@icloud.com",
            "subject": "提醒",
            "body_text": "提醒您别迟到。",
            "source_evidence_ids": ["event-real-request"],
            "risk_notes": ["third_party_send_requires_confirmation"],
            "idempotency_key": "chat:request-real-request:nomi-gmail",
            "task_id": "chat:event-real-request",
        }
    ]


def test_prepare_action_reports_nomi_identity_unavailable_instead_of_user_gmail_refusal():
    from app.assistant_identity.chat_routing import prepare_nomi_gmail_chat_action
    from app.assistant_identity.models import AssistantIdentity

    class Registry:
        def get(self, identity_id):
            return AssistantIdentity(
                identity_id=identity_id,
                kind="assistant_gmail",
                display_name="Nomi",
                address="",
                capabilities=[],
                status="unconfigured",
            )

    action = prepare_nomi_gmail_chat_action(
        "用你的邮箱给 alice@example.com 发邮件，正文是测试",
        event_id="event-unavailable",
        client_request_id="request-unavailable",
        identity_registry=Registry(),
        outbound_pipeline=object(),
    )

    assert action is not None
    assert action["status"] == "identity_unavailable"
    assert "Nomi 自己的 Gmail" in action["answer"]
    assert "您的 Gmail" not in action["answer"]


def test_same_chat_request_reuses_same_draft_and_never_sends():
    from app.assistant_identity.chat_routing import prepare_nomi_gmail_chat_action
    from app.assistant_identity.models import AssistantIdentity
    from app.assistant_identity.outbound import OutboundMessagePipeline

    class Registry:
        def get(self, identity_id):
            return AssistantIdentity(
                identity_id=identity_id,
                kind="assistant_gmail",
                display_name="Nomi",
                address="nomi@example.com",
                provider="composio",
                capabilities=["draft", "send"],
                status="connected",
            )

    outbound = OutboundMessagePipeline()
    arguments = {
        "text": "用你的邮箱给 alice@example.com 发邮件，正文是只创建一次草稿",
        "event_id": "event-idempotent",
        "client_request_id": "request-idempotent",
        "identity_registry": Registry(),
        "outbound_pipeline": outbound,
    }

    first = prepare_nomi_gmail_chat_action(**arguments)
    second = prepare_nomi_gmail_chat_action(**arguments)

    assert first is not None and second is not None
    assert first["draft"]["draft_id"] == second["draft"]["draft_id"]
    assert first["draft"]["send_called"] is False
    assert len(outbound.list_drafts()) == 1


def test_http_chat_real_parser_and_outbound_pipeline_create_correct_safe_draft(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.assistant_identity.models import AssistantIdentity
    from app.assistant_identity.outbound import OutboundMessagePipeline

    class Registry:
        def get(self, identity_id):
            return AssistantIdentity(
                identity_id=identity_id,
                kind="assistant_gmail",
                display_name="Nomi",
                address="nomi@example.com",
                provider="composio",
                capabilities=["receive", "draft", "send", "thread_reply"],
                status="connected",
            )

    class Submission:
        def submit_user_turn(self, **kwargs):
            return {
                "conversation_id": "conversation-real-nomi-gmail",
                "turn_id": "turn-user",
                "event_id": "event-user-real-nomi-gmail",
                "content": kwargs["message"],
                "attachment_ids": [],
                "duplicate": False,
            }

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    outbound = OutboundMessagePipeline()
    monkeypatch.setattr(main, "_ASSISTANT_IDENTITY_REGISTRY", Registry())
    monkeypatch.setattr(main, "_ASSISTANT_OUTBOUND_PIPELINE", outbound)
    monkeypatch.setattr(main, "attachment_submission_service", lambda: Submission())
    monkeypatch.setattr(main, "redis_client", lambda: None)
    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "find_cached_assistant_response", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "load_completed_artifact_delivery_for_followup", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "find_pending_open_task_for_conversation", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        main,
        "persist_assistant_turn",
        lambda *args, **kwargs: {
            "conversation_id": kwargs["conversation_id"],
            "turn_id": "turn-assistant",
            "event_id": "event-assistant-real-nomi-gmail",
        },
    )
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "safe_persist_context_route_trace", lambda *args, **kwargs: "route-real-nomi-gmail")

    class ForbiddenGateway:
        async def chat(self, *args, **kwargs):
            raise AssertionError("Nomi Gmail draft route must not invoke the chat model")

    monkeypatch.setattr(main, "model_gateway", lambda: ForbiddenGateway())

    response = TestClient(main.app).post(
        "/api/chat",
        headers={"x-par-password": "secret"},
        json={
            "message": "用你的gmail邮箱给 Mrzichang@icloud.com这个邮箱发个邮件 提醒他别迟到",
            "conversation_id": "conversation-real-nomi-gmail",
            "client_type": "android",
            "client_request_id": "request-real-nomi-gmail",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    draft = payload["assistant_draft"]
    assert draft["identity_id"] == "nomi_gmail_primary"
    assert draft["recipient"] == "Mrzichang@icloud.com"
    assert draft["subject"] == "提醒"
    assert draft["body_text"] == "提醒您别迟到。"
    assert draft["status"] == "draft"
    assert draft["confirmation_required"] is True
    assert draft["send_called"] is False
    assert payload["context_pack"]["task_route"]["pipeline_id"] == "reply_pipeline"
    assert payload["context_pack"]["task_route"]["capability_id"] == "assistant.email.send"
