import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_third_party_email_request_creates_draft_not_send():
    from app.assistant_identity.outbound import OutboundMessagePipeline

    draft = OutboundMessagePipeline().prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="会议资料",
        body_text="我是 Nomi，张子长的个人助理。明天会议资料已整理。",
        source_evidence_ids=["evt_1"],
    )

    assert draft["status"] == "draft"
    assert draft["confirmation_required"] is True
    assert draft["send_called"] is False
    assert draft["confirmation_card"]["identity_id"] == "nomi_gmail_primary"
    assert draft["confirmation_card"]["actions"] == ["send", "edit", "cancel"]


def test_cancelled_draft_never_calls_provider():
    from app.assistant_identity.outbound import OutboundMessagePipeline

    pipeline = OutboundMessagePipeline()
    draft = pipeline.prepare_draft(
        identity_id="nomi_whatsapp_primary",
        channel="whatsapp",
        recipient="+15551234567",
        subject="",
        body_text="我是 Nomi，张子长的个人助理。收到你的消息。",
        source_evidence_ids=["evt_2"],
    )

    cancelled = pipeline.cancel_draft(draft["draft_id"])

    assert cancelled["status"] == "cancelled"
    assert cancelled["send_called"] is False


def test_send_requires_explicit_confirmation_token():
    from app.assistant_identity.outbound import OutboundMessagePipeline

    pipeline = OutboundMessagePipeline()
    draft = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="Hi",
        body_text="我是 Nomi。",
        source_evidence_ids=["evt_3"],
    )

    try:
        pipeline.confirm_and_send(draft["draft_id"], confirmation_token="")
    except PermissionError as exc:
        assert "confirmation" in str(exc).lower()
    else:
        raise AssertionError("send succeeded without confirmation")


def test_sms_draft_uses_sms_confirmation_card():
    from app.assistant_identity.outbound import OutboundMessagePipeline

    draft = OutboundMessagePipeline().prepare_draft(
        identity_id="nomi_phone_primary",
        channel="sms",
        recipient="+15551234567",
        subject="",
        body_text="我是 Nomi，张子长的个人助理。他十分钟后到。",
        source_evidence_ids=["evt_sms_1"],
    )

    assert draft["confirmation_card"]["type"] == "assistant_sms_confirmation"
    assert draft["confirmation_card"]["actions"] == ["send", "edit", "cancel"]
    assert draft["send_called"] is False


def test_phone_call_draft_uses_call_confirmation_card():
    from app.assistant_identity.outbound import OutboundMessagePipeline

    draft = OutboundMessagePipeline().prepare_draft(
        identity_id="nomi_phone_primary",
        channel="phone_call",
        recipient="+15551234567",
        subject="",
        body_text="我是 Nomi，张子长的个人助理。他十分钟后到。",
        source_evidence_ids=["evt_call_1"],
    )

    card = draft["confirmation_card"]
    assert card["type"] == "assistant_call_playback_confirmation"
    assert card["actions"] == ["call", "edit", "cancel"]
    assert card["estimated_duration_seconds"] >= 3
    assert "不会实时对话" in card["v1_limitation"]


def test_call_requires_explicit_confirmation_token():
    from app.assistant_identity.outbound import OutboundMessagePipeline

    pipeline = OutboundMessagePipeline()
    draft = pipeline.prepare_draft(
        identity_id="nomi_phone_primary",
        channel="phone_call",
        recipient="+15551234567",
        subject="",
        body_text="我是 Nomi，张子长的个人助理。他十分钟后到。",
        source_evidence_ids=["evt_call_2"],
    )

    try:
        pipeline.confirm_and_call(draft["draft_id"], confirmation_token="")
    except PermissionError as exc:
        assert "confirmation" in str(exc).lower()
    else:
        raise AssertionError("call succeeded without confirmation")

    called = pipeline.confirm_and_call(draft["draft_id"], confirmation_token="confirm-call")
    assert called["status"] == "call_queued"
    assert called["call_called"] is True
    assert called["provider_call_id"].startswith("local-call-")


def test_communication_pipeline_returns_agent_policy_for_long_tail_request():
    from app.pipelines.communication import route_assistant_owned_communication

    result = route_assistant_owned_communication(
        "帮我分析客户历史邮件，找出回复策略，然后让 Nomi 发邮件",
        trigger_source="user_direct_command",
        channel_hint="gmail",
        recipient_hint="client_42",
        source_evidence_ids=["memory_fact_1"],
    )

    assert result["status"] == "agent_required"
    assert result["agent_policy"]["allowed_tools"] == ["assistant.outbound.create_draft"]
    assert "gmail.messages.send" in result["agent_policy"]["forbidden_provider_tools"]
    assert result["agent_policy"]["must_return_to_pipeline"] == "outbound_message_pipeline"


def test_communication_pipeline_returns_draft_route_for_explicit_send_request():
    from app.pipelines.communication import route_assistant_owned_communication

    result = route_assistant_owned_communication(
        "用 Nomi 邮箱给 Alice 发一封邮件",
        trigger_source="user_explicit_send_request",
        channel_hint="gmail",
        recipient_hint="Alice",
        source_evidence_ids=["private_event_7"],
    )

    assert result["status"] == "draft_route_ready"
    assert result["external_effect"] == "assistant_outbound_draft"
    assert result["route_decision"]["capability_id"] == "assistant.email.send"
    assert result["confirmation_required"] is True
