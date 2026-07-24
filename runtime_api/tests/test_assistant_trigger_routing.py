import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_explicit_nomi_gmail_send_routes_to_core_pipeline_not_agent():
    from app.assistant_identity.routing import AssistantCommunicationTriggerRouter

    decision = AssistantCommunicationTriggerRouter().route(
        {
            "trigger_source": "user_explicit_send_request",
            "text": "用 Nomi 自己的邮箱给 Alice 发邮件，说我下午到",
            "channel_hint": "gmail",
            "recipient_hint": "Alice",
            "source_evidence_ids": ["private_event_1"],
        }
    )

    assert decision["route_type"] == "core_pipeline"
    assert decision["pipeline_id"] == "reply_pipeline"
    assert decision["capability_id"] == "assistant.email.send"
    assert decision["confirmation_required"] is True
    assert decision["agent_allowed"] is False
    assert "draft" in decision["allowed_effects"]
    assert "send_without_confirmation" in decision["forbidden_effects"]


def test_explicit_nomi_sms_send_routes_to_sms_pipeline_not_agent():
    from app.assistant_identity.routing import AssistantCommunicationTriggerRouter

    decision = AssistantCommunicationTriggerRouter().route(
        {
            "trigger_source": "user_explicit_send_request",
            "text": "用 Nomi 的手机号给 Alice 发短信，说我十分钟后到",
            "channel_hint": "sms",
            "recipient_hint": "+15551234567",
            "source_evidence_ids": ["private_event_sms_1"],
        }
    )

    assert decision["route_type"] == "core_pipeline"
    assert decision["pipeline_id"] == "reply_pipeline"
    assert decision["capability_id"] == "assistant.sms.send"
    assert decision["confirmation_required"] is True
    assert decision["agent_allowed"] is False
    assert "send_without_confirmation" in decision["forbidden_effects"]


def test_explicit_nomi_phone_call_routes_to_one_way_playback_pipeline():
    from app.assistant_identity.routing import AssistantCommunicationTriggerRouter

    decision = AssistantCommunicationTriggerRouter().route(
        {
            "trigger_source": "user_explicit_send_request",
            "text": "用 Nomi 的手机号给 Maya 打电话，播放我会晚到五分钟",
            "channel_hint": "phone_call",
            "recipient_hint": "+15557654321",
            "source_evidence_ids": ["private_event_call_1"],
        }
    )

    assert decision["route_type"] == "core_pipeline"
    assert decision["pipeline_id"] == "reply_pipeline"
    assert decision["capability_id"] == "assistant.phone.call_playback"
    assert decision["confirmation_required"] is True
    assert decision["agent_allowed"] is False
    assert "send_without_confirmation" in decision["forbidden_effects"]


def test_external_contact_message_does_not_auto_reply():
    from app.assistant_identity.routing import AssistantCommunicationTriggerRouter

    decision = AssistantCommunicationTriggerRouter().route(
        {
            "trigger_source": "external_contact_message",
            "text": "你让张子长尽快给我回电话",
            "sender_class": "known_contact",
            "source_evidence_ids": ["assistant_inbox_event_2"],
        }
    )

    assert decision["route_type"] == "none"
    assert decision["pipeline_id"] == "proactive_suggestion_pipeline"
    assert decision["capability_id"] == "assistant.inbox.read"
    assert decision["confirmation_required"] is False
    assert decision["allowed_effects"] == ["store", "summarize", "notify_user_if_relevant"]
    assert "auto_reply" in decision["forbidden_effects"]


def test_long_tail_goal_routes_to_agent_but_only_allows_draft_tool():
    from app.assistant_identity.routing import AssistantCommunicationTriggerRouter

    decision = AssistantCommunicationTriggerRouter().route(
        {
            "trigger_source": "user_direct_command",
            "text": "帮我分析这个客户之前的邮件、找出最合适的回复策略，然后让 Nomi 写一封邮件",
            "channel_hint": "gmail",
            "recipient_hint": "client_42",
            "source_evidence_ids": ["private_event_3", "memory_fact_9"],
        }
    )

    assert decision["route_type"] == "agent"
    assert decision["agent_allowed"] is True
    assert decision["agent_allowed_tools"] == ["assistant.email.create_draft"]
    assert "assistant.outbound.create_draft" not in str(decision)
    assert decision["confirmation_required"] is True
    assert "gmail.messages.send" in decision["forbidden_provider_tools"]
    assert "whatsapp.messages.send" in decision["forbidden_provider_tools"]
    assert "sms.messages.send" in decision["forbidden_provider_tools"]
    assert "phone.calls.create" in decision["forbidden_provider_tools"]
    assert "deterministic pipeline was insufficient" in decision["reason"]


def test_agent_outbound_intent_returns_to_deterministic_draft_pipeline():
    from app.assistant_identity.routing import AssistantCommunicationTriggerRouter

    decision = AssistantCommunicationTriggerRouter().route(
        {
            "trigger_source": "agent_outbound_request",
            "text": "assistant_outbound_intent: email Alice with final summary",
            "channel_hint": "gmail",
            "recipient_hint": "Alice",
            "source_evidence_ids": ["agent_checkpoint_4"],
        }
    )

    assert decision["route_type"] == "core_pipeline"
    assert decision["pipeline_id"] == "outbound_message_pipeline"
    assert decision["capability_id"] == "assistant.email.create_draft"
    assert decision["agent_allowed"] is False
    assert decision["confirmation_required"] is True
