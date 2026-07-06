import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")
os.environ["APP_PASSWORD"] = "test-password"


def test_assistant_identities_endpoint_lists_defaults():
    from fastapi.testclient import TestClient
    from app.main import app

    response = TestClient(app).get(
        "/api/assistant-identities",
        headers={"x-par-password": "test-password"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 3
    assert {item["identity_id"] for item in payload["identities"]} == {
        "nomi_gmail_primary",
        "nomi_whatsapp_primary",
        "nomi_phone_primary",
    }


def test_assistant_identity_connect_patch_and_health_endpoints():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    headers = {"x-par-password": "test-password"}

    connect = client.post("/api/assistant-identities/assistant_gmail/connect", headers=headers)
    assert connect.status_code == 200
    assert connect.json()["identity"]["kind"] == "assistant_gmail"
    assert connect.json()["identity"]["status"] == "connected"

    patch = client.patch(
        "/api/assistant-identities/nomi_gmail_primary",
        headers=headers,
        json={"display_name": "Nomi", "status": "healthy"},
    )
    assert patch.status_code == 200
    assert patch.json()["identity"]["status"] == "healthy"

    health = client.get("/api/assistant-identities/nomi_gmail_primary/health", headers=headers)
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"

    phone_connect = client.post("/api/assistant-identities/assistant_phone/connect", headers=headers)
    assert phone_connect.status_code == 200
    assert phone_connect.json()["identity"]["identity_id"] == "nomi_phone_primary"
    assert phone_connect.json()["identity"]["status"] == "connected"


def test_assistant_whatsapp_webhook_verification_endpoint():
    from fastapi.testclient import TestClient
    from app.main import app

    os.environ["ASSISTANT_WHATSAPP_VERIFY_TOKEN"] = "local-token"
    response = TestClient(app).get(
        "/api/assistant-inbox/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "local-token",
            "hub.challenge": "challenge-1",
        },
    )

    assert response.status_code == 200
    assert response.text == "challenge-1"


def test_assistant_outbound_draft_send_and_cancel_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    for name in [
        "ASSISTANT_GMAIL_ADDRESS",
        "ASSISTANT_GMAIL_ACCESS_TOKEN",
    ]:
        monkeypatch.delenv(name, raising=False)

    client = TestClient(app)
    headers = {"x-par-password": "test-password"}
    draft_response = client.post(
        "/api/assistant-outbound/drafts",
        headers=headers,
        json={
            "identity_id": "nomi_gmail_primary",
            "channel": "gmail",
            "recipient": "alice@example.com",
            "subject": "报价",
            "body_text": "我是 Nomi，张子长的个人助理。报价单今晚发。",
            "source_evidence_ids": ["evt_1"],
        },
    )

    assert draft_response.status_code == 200
    draft = draft_response.json()
    assert draft["status"] == "draft"
    assert draft["send_called"] is False
    assert draft["confirmation_card"]["actions"] == ["send", "edit", "cancel"]

    blocked_send = client.post(
        f"/api/assistant-outbound/drafts/{draft['draft_id']}/send",
        headers=headers,
        json={"confirmation_token": ""},
    )

    assert blocked_send.status_code == 403

    sent = client.post(
        f"/api/assistant-outbound/drafts/{draft['draft_id']}/send",
        headers=headers,
        json={"confirmation_token": "confirm-user-click"},
    )

    assert sent.status_code == 200
    sent_payload = sent.json()
    assert sent_payload["status"] == "blocked"
    assert sent_payload["reason"] == "misconfigured"
    assert sent_payload["send_called"] is True
    assert sent_payload["provider"] == "gmail"

    outbound = client.get("/api/assistant-outbound", headers=headers)
    assert outbound.status_code == 200
    outbound_payload = outbound.json()
    assert outbound_payload["count"] >= 1
    assert outbound_payload["items"][0]["draft_id"] == draft["draft_id"]
    assert outbound_payload["items"][0]["status"] == "blocked"

    second_draft = client.post(
        "/api/assistant-outbound/drafts",
        headers=headers,
        json={
            "identity_id": "nomi_whatsapp_primary",
            "channel": "whatsapp",
            "recipient": "+15551234567",
            "body_text": "我是 Nomi，收到。",
            "source_evidence_ids": ["evt_2"],
        },
    ).json()
    cancelled = client.post(
        f"/api/assistant-outbound/drafts/{second_draft['draft_id']}/cancel",
        headers=headers,
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["send_called"] is False


def test_assistant_inbox_gmail_sync_endpoint_normalizes_message():
    from fastapi.testclient import TestClient
    from app.main import app

    response = TestClient(app).post(
        "/api/assistant-inbox/gmail/sync",
        headers={"x-par-password": "test-password"},
        json={
            "identity_id": "nomi_gmail_primary",
            "message": {
                "id": "gmail-api-1",
                "thread_id": "thread-api",
                "from": "owner@example.com",
                "to": ["nomi@example.com"],
                "subject": "命令",
                "body": "帮我回复 Alice。",
            },
            "user_keys": ["owner@example.com"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["event"]["classification"] == "user_direct_command"
    assert payload["event"]["source_type"] == "assistant_gmail"
    assert payload["status"] == "accepted"

    detail = TestClient(app).get(
        f"/api/assistant-inbox/{payload['event']['event_id']}",
        headers={"x-par-password": "test-password"},
    )

    assert detail.status_code == 200
    assert detail.json()["event"]["event_id"] == payload["event"]["event_id"]


def test_assistant_whatsapp_post_webhook_normalizes_inbound_message():
    from fastapi.testclient import TestClient
    from app.main import app

    os.environ["ASSISTANT_WHATSAPP_VERIFY_TOKEN"] = "local-token"
    response = TestClient(app).post(
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
                                        "id": "wamid.api.1",
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
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["events"][0]["classification"] == "external_contact_message"
    assert payload["events"][0]["suggestion_channel"] == "assistant_channel_external_contact"


def test_assistant_phone_sms_webhook_normalizes_inbound_message():
    from fastapi.testclient import TestClient
    from app.main import app

    os.environ["ASSISTANT_PHONE_WEBHOOK_TOKEN"] = "phone-token"
    response = TestClient(app).post(
        "/api/assistant-inbox/phone/sms/webhook",
        headers={"x-assistant-webhook-token": "phone-token"},
        json={
            "provider_message_id": "sms-api-1",
            "from_number": "+15551234567",
            "to_number": "+15557654321",
            "body": "请让张子长今天回我电话。",
            "timestamp": "2026-06-05T09:00:00Z",
            "known_contacts": {"+15551234567": "contact_maya"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["event"]["source_type"] == "assistant_phone"
    assert payload["event"]["event_type"] == "assistant_sms_received"
    assert payload["event"]["classification"] == "external_contact_message"
    assert payload["event"]["suggestion_channel"] == "assistant_channel_external_contact"


def test_assistant_phone_call_webhook_records_inbound_call_status():
    from fastapi.testclient import TestClient
    from app.main import app

    os.environ["ASSISTANT_PHONE_WEBHOOK_TOKEN"] = "phone-token"
    response = TestClient(app).post(
        "/api/assistant-inbox/phone/calls/inbound",
        headers={"x-assistant-webhook-token": "phone-token"},
        json={
            "provider_call_id": "call-api-1",
            "from_number": "+15551234567",
            "to_number": "+15557654321",
            "direction": "inbound",
            "status": "answered_with_greeting",
            "timestamp": "2026-06-05T09:05:00Z",
            "known_contacts": {"+15551234567": "contact_maya"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["event"]["source_type"] == "assistant_phone"
    assert payload["event"]["event_type"] == "assistant_inbound_call_received"
    assert payload["event"]["normalized_payload"]["call_direction"] == "inbound"
    assert payload["event"]["normalized_payload"]["status"] == "answered_with_greeting"
    assert "Nomi" in payload["greeting"]["script_text"]


def test_assistant_phone_call_instruction_endpoint_is_one_way_playback():
    from fastapi.testclient import TestClient
    from app.main import app

    response = TestClient(app).get(
        "/api/assistant-inbox/phone/calls/local-greeting/instruction",
        headers={"x-par-password": "test-password"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "tts_playback"
    assert payload["v1_one_way_playback"] is True
    assert "Nomi" in payload["script_text"]


def test_assistant_outbound_phone_call_endpoint_requires_confirmation(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    for name in [
        "ASSISTANT_PHONE_PROVIDER_BASE_URL",
        "ASSISTANT_PHONE_PROVIDER_API_KEY",
        "ASSISTANT_PHONE_NUMBER",
    ]:
        monkeypatch.delenv(name, raising=False)

    client = TestClient(app)
    headers = {"x-par-password": "test-password"}
    draft = client.post(
        "/api/assistant-outbound/drafts",
        headers=headers,
        json={
            "identity_id": "nomi_phone_primary",
            "channel": "phone_call",
            "recipient": "+15551234567",
            "body_text": "我是 Nomi，张子长的个人助理。他十分钟后到。",
            "source_evidence_ids": ["evt_call_api"],
        },
    ).json()

    blocked = client.post(
        f"/api/assistant-outbound/drafts/{draft['draft_id']}/call",
        headers=headers,
        json={"confirmation_token": ""},
    )
    assert blocked.status_code == 403

    queued = client.post(
        f"/api/assistant-outbound/drafts/{draft['draft_id']}/call",
        headers=headers,
        json={"confirmation_token": "confirm-call"},
    )
    assert queued.status_code == 200
    queued_payload = queued.json()
    assert queued_payload["status"] == "blocked"
    assert queued_payload["reason"] == "misconfigured"
    assert queued_payload["call_called"] is True
    assert queued_payload["provider"] == "http_phone"


def test_assistant_outbound_duplex_phone_call_endpoint_requires_confirmation(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    for name in [
        "ASSISTANT_PHONE_PROVIDER_BASE_URL",
        "ASSISTANT_PHONE_PROVIDER_API_KEY",
        "ASSISTANT_PHONE_NUMBER",
        "ASSISTANT_PHONE_DUPLEX_WEBHOOK_URL",
    ]:
        monkeypatch.delenv(name, raising=False)

    client = TestClient(app)
    headers = {"x-par-password": "test-password"}
    draft_response = client.post(
        "/api/assistant-outbound/drafts",
        headers=headers,
        json={
            "identity_id": "nomi_phone_primary",
            "channel": "phone_duplex_call",
            "recipient": "+15551234567",
            "body_text": "我是 Nomi，张子长的个人助理。我可以先帮你记录并转达。",
            "source_evidence_ids": ["evt_duplex_call_api"],
        },
    )
    assert draft_response.status_code == 200
    draft = draft_response.json()
    assert draft["confirmation_card"]["type"] == "assistant_call_duplex_confirmation"
    assert draft["confirmation_card"]["actions"] == ["call", "edit", "cancel"]

    blocked = client.post(
        f"/api/assistant-outbound/drafts/{draft['draft_id']}/call",
        headers=headers,
        json={"confirmation_token": ""},
    )
    assert blocked.status_code == 403

    queued = client.post(
        f"/api/assistant-outbound/drafts/{draft['draft_id']}/call",
        headers=headers,
        json={"confirmation_token": "confirm-duplex-call"},
    )
    assert queued.status_code == 200
    queued_payload = queued.json()
    assert queued_payload["status"] == "blocked"
    assert queued_payload["reason"] == "misconfigured"
    assert queued_payload["call_called"] is True
    assert queued_payload["provider"] == "http_phone"
    assert "ASSISTANT_PHONE_DUPLEX_WEBHOOK_URL" in queued_payload["missing_env"]


def test_assistant_phone_duplex_turn_webhook_records_transcript_and_returns_reply_instruction():
    from fastapi.testclient import TestClient
    from app.main import app

    os.environ["ASSISTANT_PHONE_WEBHOOK_TOKEN"] = "phone-token"
    response = TestClient(app).post(
        "/api/assistant-inbox/phone/calls/duplex/turn",
        headers={"x-assistant-webhook-token": "phone-token"},
        json={
            "provider_call_id": "duplex-call-api-1",
            "from_number": "+15551234567",
            "to_number": "+15557654321",
            "transcript": "请告诉张子长我明天下午三点到。",
            "turn_index": 2,
            "timestamp": "2026-06-05T09:10:00Z",
            "known_contacts": {"+15551234567": "contact_maya"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["event"]["event_type"] == "assistant_duplex_call_turn"
    assert payload["event"]["conversation_id"] == "phone-call:duplex-call-api-1"
    assert payload["event"]["normalized_text"] == "请告诉张子长我明天下午三点到。"
    assert payload["reply_instruction"]["mode"] == "tts_reply"
    assert payload["reply_instruction"]["v2_duplex_turn"] is True
    assert "Nomi" in payload["reply_instruction"]["script_text"]


def test_assistant_gmail_pubsub_endpoint_accepts_push_payload():
    from fastapi.testclient import TestClient
    from app.main import app

    response = TestClient(app).post(
        "/api/assistant-inbox/gmail/pubsub",
        headers={"x-par-password": "test-password"},
        json={"message": {"messageId": "pubsub-1", "data": "eyJlbWFpbEFkZHJlc3MiOiAibm9taUBleGFtcGxlLmNvbSJ9"}},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["provider"] == "gmail_pubsub"
