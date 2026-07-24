import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class RecordingGmailAdapter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_message(
        self,
        *,
        sender: str,
        recipient: str,
        subject: str,
        body_text: str,
        thread_id: Optional[str] = None,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "sender": sender,
                "recipient": recipient,
                "subject": subject,
                "body_text": body_text,
                "thread_id": thread_id or "",
            }
        )
        return {
            "status": "sent",
            "provider": "recording_gmail",
            "provider_message_id": "gmail-provider-1",
            "provider_result": {"status_code": 200, "body": {"id": "gmail-provider-1"}},
        }


class RecordingPhoneCallAdapter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create_playback_call(
        self,
        *,
        from_number: str,
        to_number: str,
        script_text: str,
        audio_url: Optional[str] = None,
        voice: str = "default",
    ) -> dict[str, object]:
        self.calls.append(
            {
                "from_number": from_number,
                "to_number": to_number,
                "script_text": script_text,
                "audio_url": audio_url or "",
                "voice": voice,
            }
        )
        return {
            "status": "queued",
            "provider": "recording_phone",
            "provider_call_id": "call-provider-1",
            "provider_result": {"status_code": 201, "body": {"call_id": "call-provider-1"}},
        }


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


def test_cancelling_an_already_cancelled_draft_is_idempotent():
    from app.assistant_identity.outbound import OutboundMessagePipeline

    pipeline = OutboundMessagePipeline()
    draft = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="qa-recipient@example.invalid",
        subject="提醒",
        body_text="提醒您别迟到。",
        source_evidence_ids=["evt_cancel_retry"],
    )

    first = pipeline.cancel_draft(draft["draft_id"])
    second = pipeline.cancel_draft(draft["draft_id"])

    assert first["status"] == "cancelled"
    assert second["status"] == "cancelled"
    assert second["revision"] == first["revision"]
    assert second["send_called"] is False
    assert second["confirmation_required"] is False


def test_send_requires_explicit_confirmation_token():
    from app.assistant_identity.outbound import OutboundMessagePipeline

    adapter = RecordingGmailAdapter()
    pipeline = OutboundMessagePipeline(gmail_adapter=adapter)
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

    assert adapter.calls == []


def test_confirmed_gmail_send_calls_adapter_and_records_provider_result(monkeypatch):
    from app.assistant_identity.outbound import OutboundMessagePipeline

    monkeypatch.setenv("ASSISTANT_GMAIL_ADDRESS", "nomi@example.com")
    adapter = RecordingGmailAdapter()
    pipeline = OutboundMessagePipeline(gmail_adapter=adapter)

    draft = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="Hi",
        body_text="我是 Nomi。",
        source_evidence_ids=["evt_3b"],
    )

    confirmation = pipeline.issue_confirmation(draft["draft_id"], actor="local_owner")
    result = pipeline.confirm_and_send(
        draft["draft_id"],
        confirmation_token=confirmation["confirmation_token"],
        actor="local_owner",
    )

    assert result["status"] == "sent"
    assert result["send_called"] is True
    assert result["provider"] == "recording_gmail"
    assert result["provider_message_id"] == "gmail-provider-1"
    assert result["provider_result"]["status_code"] == 200
    assert adapter.calls == [
        {
            "sender": "nomi@example.com",
            "recipient": "alice@example.com",
            "subject": "Hi",
            "body_text": "我是 Nomi。",
            "thread_id": "",
        }
    ]


def test_default_gmail_send_returns_misconfigured_after_confirmation(monkeypatch):
    from app.assistant_identity.outbound import OutboundMessagePipeline

    for name in [
        "ASSISTANT_GMAIL_ADDRESS",
        "ASSISTANT_GMAIL_ACCESS_TOKEN",
    ]:
        monkeypatch.delenv(name, raising=False)

    pipeline = OutboundMessagePipeline()
    draft = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="Hi",
        body_text="我是 Nomi。",
        source_evidence_ids=["evt_3c"],
    )

    confirmation = pipeline.issue_confirmation(draft["draft_id"], actor="local_owner")
    result = pipeline.confirm_and_send(
        draft["draft_id"],
        confirmation_token=confirmation["confirmation_token"],
        actor="local_owner",
    )

    assert result["status"] == "blocked"
    assert result["send_called"] is True
    assert result["provider"] == "gmail"
    assert result["reason"] == "misconfigured"
    assert result["provider_result"]["status"] == "misconfigured"


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

    adapter = RecordingPhoneCallAdapter()
    pipeline = OutboundMessagePipeline(phone_call_adapter=adapter)
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

    assert adapter.calls == []

    confirmation = pipeline.issue_confirmation(draft["draft_id"], actor="local_owner")
    called = pipeline.confirm_and_call(
        draft["draft_id"],
        confirmation_token=confirmation["confirmation_token"],
        actor="local_owner",
    )
    assert called["status"] == "call_queued"
    assert called["call_called"] is True
    assert called["provider_call_id"] == "call-provider-1"
    assert called["provider_result"]["status_code"] == 201
    assert adapter.calls[0]["to_number"] == "+15551234567"


def test_confirmation_binds_actor_and_immutable_draft_content():
    from app.assistant_identity.outbound import OutboundMessagePipeline

    adapter = RecordingGmailAdapter()
    pipeline = OutboundMessagePipeline(gmail_adapter=adapter)
    draft = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="报价",
        body_text="初版正文",
        source_evidence_ids=["evt_confirm_1"],
    )
    confirmation = pipeline.issue_confirmation(draft["draft_id"], actor="local_owner")

    try:
        pipeline.confirm_and_send(
            draft["draft_id"],
            confirmation_token=confirmation["confirmation_token"],
            actor="other_actor",
        )
    except PermissionError as exc:
        assert "actor" in str(exc).lower()
    else:
        raise AssertionError("confirmation was accepted for a different actor")

    pipeline.edit_draft(draft["draft_id"], body_text="修改后的正文")
    try:
        pipeline.confirm_and_send(
            draft["draft_id"],
            confirmation_token=confirmation["confirmation_token"],
            actor="local_owner",
        )
    except PermissionError as exc:
        assert "changed" in str(exc).lower() or "invalid" in str(exc).lower()
    else:
        raise AssertionError("confirmation survived a protected draft edit")

    assert adapter.calls == []


def test_confirmation_expires_and_duplicate_confirm_tap_sends_only_once(monkeypatch):
    from app.assistant_identity.outbound import OutboundMessagePipeline

    monkeypatch.setenv("ASSISTANT_GMAIL_ADDRESS", "nomi@example.com")
    now = datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc)
    adapter = RecordingGmailAdapter()
    pipeline = OutboundMessagePipeline(gmail_adapter=adapter, clock=lambda: now)
    expired_draft = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="expired@example.com",
        subject="过期测试",
        body_text="不会发送",
        source_evidence_ids=["evt_expired"],
    )
    expired = pipeline.issue_confirmation(
        expired_draft["draft_id"],
        actor="local_owner",
        ttl_seconds=60,
    )
    now = now + timedelta(seconds=61)
    try:
        pipeline.confirm_and_send(
            expired_draft["draft_id"],
            confirmation_token=expired["confirmation_token"],
            actor="local_owner",
        )
    except PermissionError as exc:
        assert "expired" in str(exc).lower()
    else:
        raise AssertionError("expired confirmation was accepted")

    active_draft = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="只发一次",
        body_text="重复点击也只能发一次",
        source_evidence_ids=["evt_once"],
    )
    active = pipeline.issue_confirmation(active_draft["draft_id"], actor="local_owner")
    first = pipeline.confirm_and_send(
        active_draft["draft_id"],
        confirmation_token=active["confirmation_token"],
        actor="local_owner",
    )
    second = pipeline.confirm_and_send(
        active_draft["draft_id"],
        confirmation_token=active["confirmation_token"],
        actor="local_owner",
    )

    assert first == second
    assert first["status"] == "sent"
    assert len(adapter.calls) == 1


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
    assert result["agent_policy"]["allowed_tools"] == ["assistant.email.create_draft"]
    assert "assistant.outbound.create_draft" not in str(result["agent_policy"])
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
