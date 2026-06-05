#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime_api"))

os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")
os.environ.setdefault("APP_PASSWORD", "test-password")
os.environ["ASSISTANT_WHATSAPP_VERIFY_TOKEN"] = "local-token"
os.environ["ASSISTANT_PHONE_WEBHOOK_TOKEN"] = "phone-token"

from fastapi.testclient import TestClient  # noqa: E402

from app.assistant_identity.api import normalized_assistant_event_to_private_payload  # noqa: E402
from app.assistant_identity.contact_resolver import ContactResolver  # noqa: E402
from app.assistant_identity.inbox_gateway import AssistantInboxGateway  # noqa: E402
from app.assistant_identity.routing import AssistantCommunicationTriggerRouter  # noqa: E402
from app.main import app  # noqa: E402


HEADERS = {"x-par-password": "test-password"}


def record(case: str, ok: bool, expected: str, observed: Any) -> dict[str, Any]:
    return {
        "case": case,
        "passed": bool(ok),
        "expected": expected,
        "observed": observed,
    }


def main() -> int:
    client = TestClient(app)
    results: list[dict[str, Any]] = []

    identities = client.get("/api/assistant-identities", headers=HEADERS).json()
    identity_ids = {item["identity_id"] for item in identities["identities"]}
    results.append(
        record(
            "AI-ID-001",
            identity_ids == {"nomi_gmail_primary", "nomi_whatsapp_primary", "nomi_phone_primary"},
            "Default Nomi Gmail, WhatsApp, and phone identities are all present.",
            identities,
        )
    )

    gmail_event = client.post(
        "/api/assistant-inbox/gmail/sync",
        headers=HEADERS,
        json={
            "identity_id": "nomi_gmail_primary",
            "message": {
                "id": "reg-gmail-1",
                "thread_id": "reg-thread-1",
                "from": "owner@example.com",
                "to": ["nomi@example.com"],
                "subject": "Nomi",
                "body": "帮我回复 Alice。",
            },
            "user_keys": ["owner@example.com"],
        },
    ).json()["event"]
    results.append(
        record(
            "AI-GM-001",
            gmail_event["classification"] == "user_direct_command"
            and gmail_event["source_type"] == "assistant_gmail"
            and gmail_event["memory_scope"]["visibility_scope"] == "assistant_identity_thread",
            "User email to Nomi becomes a scoped user_direct_command assistant Gmail event.",
            gmail_event,
        )
    )

    wa_user_event = AssistantInboxGateway(
        ContactResolver(user_keys={"+15550000000"}, known_contacts={})
    ).normalize_whatsapp(
        identity_id="nomi_whatsapp_primary",
        payload={"wamid": "reg-wa-user-1", "from": "+15550000000", "text": "Nomi，帮我查报价"},
    )
    results.append(
        record(
            "AI-WA-001",
            wa_user_event["classification"] == "user_direct_command"
            and wa_user_event["source_type"] == "assistant_whatsapp",
            "User WhatsApp message to Nomi becomes user_direct_command.",
            wa_user_event,
        )
    )

    before_outbound = client.get("/api/assistant-outbound/messages", headers=HEADERS).json()["count"]
    wa_external = client.post(
        "/api/assistant-inbox/whatsapp/webhook",
        headers={"x-assistant-webhook-token": "local-token"},
        json={
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": "reg-wa-ext-1",
                                        "from": "+15551234567",
                                        "text": {"body": "请让张子长今天回我电话。"},
                                        "timestamp": "2026-06-04T12:00:00Z",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ],
            "known_contacts": {"+15551234567": "contact_maya"},
        },
    ).json()["events"][0]
    after_outbound = client.get("/api/assistant-outbound/messages", headers=HEADERS).json()["count"]
    results.append(
        record(
            "AI-EXT-001",
            wa_external["classification"] == "external_contact_message"
            and wa_external["suggestion_channel"] == "assistant_channel_external_contact"
            and before_outbound == after_outbound,
            "External WhatsApp contact is stored/surfaced and does not auto-send a reply.",
            {"event": wa_external, "outbound_count_before": before_outbound, "outbound_count_after": after_outbound},
        )
    )

    before_phone_outbound = client.get("/api/assistant-outbound/messages", headers=HEADERS).json()["count"]
    sms_external = client.post(
        "/api/assistant-inbox/phone/sms/webhook",
        headers={"x-assistant-webhook-token": "phone-token"},
        json={
            "provider_message_id": "reg-sms-ext-1",
            "from_number": "+15551234567",
            "to_number": "+15557654321",
            "body": "请让张子长今天回我电话。",
            "timestamp": "2026-06-05T09:00:00Z",
            "known_contacts": {"+15551234567": "contact_maya"},
        },
    ).json()["event"]
    after_phone_outbound = client.get("/api/assistant-outbound/messages", headers=HEADERS).json()["count"]
    results.append(
        record(
            "AI-SMS-001",
            sms_external["classification"] == "external_contact_message"
            and sms_external["source_type"] == "assistant_phone"
            and sms_external["suggestion_channel"] == "assistant_channel_external_contact"
            and before_phone_outbound == after_phone_outbound,
            "External SMS to Nomi phone is scoped and surfaced; it does not auto-send a reply.",
            {
                "event": sms_external,
                "outbound_count_before": before_phone_outbound,
                "outbound_count_after": after_phone_outbound,
            },
        )
    )

    call_external = client.post(
        "/api/assistant-inbox/phone/calls/inbound",
        headers={"x-assistant-webhook-token": "phone-token"},
        json={
            "provider_call_id": "reg-call-in-1",
            "from_number": "+15551234567",
            "to_number": "+15557654321",
            "direction": "inbound",
            "status": "answered_with_greeting",
            "timestamp": "2026-06-05T09:05:00Z",
            "known_contacts": {"+15551234567": "contact_maya"},
        },
    ).json()
    results.append(
        record(
            "AI-CALL-IN-001",
            call_external["event"]["source_type"] == "assistant_phone"
            and call_external["event"]["event_type"] == "assistant_inbound_call_received"
            and call_external["event"]["normalized_payload"]["status"] == "answered_with_greeting"
            and call_external["greeting"]["v1_one_way_playback"] is True,
            "Inbound calls to Nomi phone produce an auditable status event and one-way greeting instruction.",
            call_external,
        )
    )

    draft = client.post(
        "/api/assistant-outbound/drafts",
        headers=HEADERS,
        json={
            "identity_id": "nomi_gmail_primary",
            "channel": "gmail",
            "recipient": "alice@example.com",
            "subject": "报价",
            "body_text": "我是 Nomi，张子长的个人助理。报价单今晚发。",
            "source_evidence_ids": [gmail_event["event_id"]],
        },
    ).json()
    blocked_send = client.post(
        f"/api/assistant-outbound/drafts/{draft['draft_id']}/send",
        headers=HEADERS,
        json={"confirmation_token": ""},
    )
    sent = client.post(
        f"/api/assistant-outbound/drafts/{draft['draft_id']}/send",
        headers=HEADERS,
        json={"confirmation_token": "confirm-user-click"},
    ).json()
    results.append(
        record(
            "AI-DRAFT-001",
            draft["status"] == "draft"
            and draft["send_called"] is False
            and draft["confirmation_card"]["actions"] == ["send", "edit", "cancel"]
            and blocked_send.status_code == 403
            and sent["status"] == "sent"
            and sent["send_called"] is True,
            "Third-party outbound starts as a confirmation draft; empty confirmation is blocked; explicit confirmation sends.",
            {"draft": draft, "blocked_status": blocked_send.status_code, "sent": sent},
        )
    )

    call_draft = client.post(
        "/api/assistant-outbound/drafts",
        headers=HEADERS,
        json={
            "identity_id": "nomi_phone_primary",
            "channel": "phone_call",
            "recipient": "+15551234567",
            "subject": "",
            "body_text": "我是 Nomi，张子长的个人助理。他十分钟后到。",
            "source_evidence_ids": [sms_external["event_id"]],
        },
    ).json()
    blocked_call = client.post(
        f"/api/assistant-outbound/drafts/{call_draft['draft_id']}/call",
        headers=HEADERS,
        json={"confirmation_token": ""},
    )
    queued_call = client.post(
        f"/api/assistant-outbound/drafts/{call_draft['draft_id']}/call",
        headers=HEADERS,
        json={"confirmation_token": "confirm-call-click"},
    ).json()
    results.append(
        record(
            "AI-CALL-DRAFT-001",
            call_draft["status"] == "draft"
            and call_draft["call_called"] is False
            and call_draft["confirmation_card"]["type"] == "assistant_call_playback_confirmation"
            and "不会实时对话" in call_draft["confirmation_card"]["v1_limitation"]
            and blocked_call.status_code == 403
            and queued_call["status"] == "call_queued"
            and queued_call["call_called"] is True,
            "Outbound phone call starts as one-way playback confirmation draft; empty confirmation is blocked; explicit confirmation queues the call.",
            {"draft": call_draft, "blocked_status": blocked_call.status_code, "queued": queued_call},
        )
    )

    private_payload = normalized_assistant_event_to_private_payload(wa_external)
    results.append(
        record(
            "AI-SCOPE-001",
            private_payload["source"] == "assistant_whatsapp"
            and private_payload["raw_data"]["assistant_identity_id"] == "nomi_whatsapp_primary"
            and private_payload["raw_data"]["classification"] == "external_contact_message",
            "Assistant-owned events preserve assistant identity and classification before private-event storage.",
            private_payload,
        )
    )

    phone_private_payload = normalized_assistant_event_to_private_payload(sms_external)
    results.append(
        record(
            "AI-SCOPE-PHONE-001",
            phone_private_payload["source"] == "assistant_phone"
            and phone_private_payload["raw_data"]["assistant_identity_id"] == "nomi_phone_primary"
            and phone_private_payload["raw_data"]["classification"] == "external_contact_message",
            "Nomi phone events preserve assistant phone identity and counterparty scope before private-event storage.",
            phone_private_payload,
        )
    )

    router = AssistantCommunicationTriggerRouter()
    explicit_route = router.route(
        {
            "trigger_source": "user_explicit_send_request",
            "text": "让 Nomi 用 WhatsApp 告诉 Maya 我晚点到",
            "channel_hint": "whatsapp",
            "recipient_hint": "Maya",
            "source_evidence_ids": [wa_external["event_id"]],
        }
    )
    long_tail_route = router.route(
        {
            "trigger_source": "user_direct_command",
            "text": "帮我分析这个客户之前的邮件、找出最合适的回复策略，然后让 Nomi 写一封邮件",
            "channel_hint": "gmail",
            "recipient_hint": "client_42",
            "source_evidence_ids": [gmail_event["event_id"]],
        }
    )
    sms_route = router.route(
        {
            "trigger_source": "user_explicit_send_request",
            "text": "让 Nomi 用自己的手机号给 Maya 发短信说我晚点到",
            "channel_hint": "sms",
            "recipient_hint": "Maya",
            "source_evidence_ids": [sms_external["event_id"]],
        }
    )
    call_route = router.route(
        {
            "trigger_source": "user_explicit_send_request",
            "text": "让 Nomi 用自己的手机号给 Maya 打电话播放我晚点到",
            "channel_hint": "phone_call",
            "recipient_hint": "Maya",
            "source_evidence_ids": [sms_external["event_id"]],
        }
    )
    results.append(
        record(
            "AI-ROUTE-001",
            explicit_route["route_type"] == "core_pipeline"
            and explicit_route["capability_id"] == "assistant.whatsapp.send"
            and explicit_route["confirmation_required"] is True
            and explicit_route["agent_allowed"] is False,
            "Known Nomi WhatsApp send request uses deterministic pipeline with confirmation.",
            explicit_route,
        )
    )
    results.append(
        record(
            "AI-ROUTE-002",
            long_tail_route["route_type"] == "agent"
            and long_tail_route["agent_allowed_tools"] == ["assistant.outbound.create_draft"]
            and "gmail.messages.send" in long_tail_route["forbidden_provider_tools"]
            and "sms.messages.send" in long_tail_route["forbidden_provider_tools"]
            and "phone.calls.create" in long_tail_route["forbidden_provider_tools"],
            "Long-tail route can plan, but only create an outbound draft and cannot call provider send/call tools.",
            long_tail_route,
        )
    )
    results.append(
        record(
            "AI-ROUTE-PHONE-001",
            sms_route["route_type"] == "core_pipeline"
            and sms_route["capability_id"] == "assistant.sms.send"
            and call_route["route_type"] == "core_pipeline"
            and call_route["capability_id"] == "assistant.phone.call_playback"
            and sms_route["confirmation_required"] is True
            and call_route["confirmation_required"] is True,
            "Known Nomi phone SMS and one-way call requests use deterministic confirmation pipelines.",
            {"sms_route": sms_route, "call_route": call_route},
        )
    )

    payload = {"results": results, "passed": sum(1 for item in results if item["passed"]), "total": len(results)}
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["passed"] == payload["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
