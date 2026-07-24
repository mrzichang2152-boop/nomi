import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")
os.environ["APP_PASSWORD"] = "test-password"


def _fresh_identity_client(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    from app.assistant_identity.registry import AssistantIdentityRegistry
    from app.assistant_identity.health import AssistantIdentityHealthService
    from app.assistant_identity.repository import (
        InMemoryAssistantCredentialRepository,
        InMemoryAssistantIdentityHealthRepository,
    )

    main._ASSISTANT_IDENTITY_REGISTRY = AssistantIdentityRegistry()
    main._ASSISTANT_CREDENTIAL_REPOSITORY = InMemoryAssistantCredentialRepository()
    main._ASSISTANT_IDENTITY_HEALTH_REPOSITORY = InMemoryAssistantIdentityHealthRepository()
    main._ASSISTANT_IDENTITY_HEALTH_SERVICE = AssistantIdentityHealthService(
        main._ASSISTANT_IDENTITY_HEALTH_REPOSITORY
    )
    return TestClient(main.app)


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


def test_assistant_identity_connect_cannot_fake_status_or_health(monkeypatch):
    client = _fresh_identity_client(monkeypatch)
    headers = {"x-par-password": "test-password"}

    connect = client.post("/api/assistant-identities/assistant_gmail/connect", headers=headers)
    assert connect.status_code == 410
    assert connect.json()["detail"] == "use_assistant_gmail_connect_link"

    patch = client.patch(
        "/api/assistant-identities/nomi_gmail_primary",
        headers=headers,
        json={"display_name": "Nomi", "status": "healthy"},
    )
    assert patch.status_code == 400
    assert patch.json()["detail"] == "status_is_provider_managed"

    health = client.get("/api/assistant-identities/nomi_gmail_primary/health", headers=headers)
    assert health.status_code == 200
    assert health.json()["status"] == "unconfigured"
    assert health.json()["healthy"] is False


def test_identity_read_model_and_explicit_lifecycle_actions_are_truthful(monkeypatch):
    client = _fresh_identity_client(monkeypatch)
    headers = {"x-par-password": "test-password"}

    listed = client.get("/api/assistant-identities", headers=headers)
    gmail = next(
        item
        for item in listed.json()["identities"]
        if item["identity_id"] == "nomi_gmail_primary"
    )
    assert gmail["status"] == "unconfigured"
    assert gmail["provider"] == ""
    assert gmail["address"] == ""
    assert gmail["capabilities"] == []
    assert gmail["secret_presence"] == {"stored": False}
    assert gmail["version"] == 1

    detail = client.get(
        "/api/assistant-identities/nomi_gmail_primary",
        headers=headers,
    )
    assert detail.status_code == 200
    assert detail.json()["identity"] == gmail

    profile = client.patch(
        "/api/assistant-identities/nomi_gmail_primary/profile",
        headers=headers,
        json={"display_name": "Nomi Assistant", "style": {"tone": "concise"}},
    )
    assert profile.status_code == 200
    profile_payload = profile.json()
    assert profile_payload["identity"]["display_name"] == "Nomi Assistant"
    assert profile_payload["identity"]["metadata"]["profile_style"] == {"tone": "concise"}
    assert profile_payload["identity"]["version"] == 2
    assert profile_payload["trace_id"]

    forbidden_profile_field = client.patch(
        "/api/assistant-identities/nomi_gmail_primary/profile",
        headers=headers,
        json={"address": "forged@example.com"},
    )
    assert forbidden_profile_field.status_code == 422

    disabled = client.post(
        "/api/assistant-identities/nomi_gmail_primary/disable",
        headers=headers,
    )
    assert disabled.status_code == 200
    assert disabled.json()["identity"]["status"] == "disabled"
    assert disabled.json()["trace_id"]

    enabled = client.post(
        "/api/assistant-identities/nomi_gmail_primary/enable",
        headers=headers,
    )
    assert enabled.status_code == 200
    assert enabled.json()["identity"]["status"] == "verifying"

    disconnected = client.post(
        "/api/assistant-identities/nomi_gmail_primary/disconnect",
        headers=headers,
    )
    assert disconnected.status_code == 200
    assert disconnected.json()["identity"]["status"] == "unconfigured"
    assert disconnected.json()["identity"]["provider"] == ""
    assert disconnected.json()["identity"]["address"] == ""
    assert disconnected.json()["identity"]["capabilities"] == []


def test_disconnect_removes_local_provider_reference_after_identity_is_cleared(monkeypatch):
    client = _fresh_identity_client(monkeypatch)
    headers = {"x-par-password": "test-password"}

    from app import main
    from app.assistant_identity.models import AssistantCredentialRef

    registry = main._ASSISTANT_IDENTITY_REGISTRY
    registry.bootstrap_defaults()
    registry.lifecycle.request_authorization("nomi_gmail_primary")
    registry.lifecycle.begin_verification("nomi_gmail_primary")
    registry.lifecycle.provider_verified(
        "nomi_gmail_primary",
        provider="gmail_api",
        address="nomi.real@example.com",
        capabilities=["send"],
    )
    main._ASSISTANT_CREDENTIAL_REPOSITORY.put(
        AssistantCredentialRef(
            identity_id="nomi_gmail_primary",
            provider="gmail_api",
            encrypted_ref="encrypted-envelope",
        )
    )

    response = client.post(
        "/api/assistant-identities/nomi_gmail_primary/disconnect",
        headers=headers,
    )

    assert response.status_code == 200
    assert main._ASSISTANT_CREDENTIAL_REPOSITORY.get(
        "nomi_gmail_primary", "gmail_api"
    ) is None


def test_health_api_is_derived_from_append_only_check_history(monkeypatch):
    client = _fresh_identity_client(monkeypatch)
    headers = {"x-par-password": "test-password"}

    from app import main

    registry = main._ASSISTANT_IDENTITY_REGISTRY
    registry.bootstrap_defaults()
    registry.lifecycle.request_authorization("nomi_gmail_primary")
    registry.lifecycle.begin_verification("nomi_gmail_primary")
    registry.lifecycle.provider_verified(
        "nomi_gmail_primary",
        provider="composio_gmail",
        address="nomi.real@example.com",
        capabilities=["receive", "send"],
    )
    health = main._ASSISTANT_IDENTITY_HEALTH_SERVICE
    health.record("nomi_gmail_primary", "credentials", "passed")
    health.record("nomi_gmail_primary", "profile", "passed")
    health.record("nomi_gmail_primary", "inbound", "passed")
    health.record("nomi_gmail_primary", "outbound", "passed")

    connected = client.get(
        "/api/assistant-identities/nomi_gmail_primary/health",
        headers=headers,
    )
    assert connected.status_code == 200
    assert connected.json()["status"] == "connected"
    assert connected.json()["healthy"] is True

    health.record(
        "nomi_gmail_primary",
        "inbound",
        "degraded",
        error_code="gmail_inbound_stale",
    )
    degraded = client.get(
        "/api/assistant-identities/nomi_gmail_primary/health",
        headers=headers,
    )
    assert degraded.json()["status"] == "degraded"
    assert degraded.json()["healthy"] is False
    assert degraded.json()["checks"]["outbound"] == "passed"

    history = client.get(
        "/api/assistant-identities/nomi_gmail_primary/health-history",
        headers=headers,
    )
    assert history.status_code == 200
    assert history.json()["count"] == 5
    assert history.json()["checks"][0]["error_code"] == "gmail_inbound_stale"


def test_assistant_gmail_connect_link_uses_dedicated_service(monkeypatch):
    client = _fresh_identity_client(monkeypatch)
    headers = {"x-par-password": "test-password"}
    from app import main

    class Service:
        def create_connect_link(self):
            return {
                "status": "authorization_pending",
                "identity_id": "nomi_gmail_primary",
                "user_id": "nomi-owned::nomi_gmail_primary",
                "alias": "nomi-gmail-primary",
                "redirect_url": "https://connect.composio.dev/link/ln_assistant",
                "connection_request_id": "ln_assistant",
                "version": 3,
            }

    monkeypatch.setattr(main, "_ASSISTANT_GMAIL_CONNECTION_SERVICE", Service())

    response = client.post(
        "/api/assistant-identities/nomi_gmail_primary/connect-link",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == "nomi-owned::nomi_gmail_primary"
    assert response.json()["alias"] == "nomi-gmail-primary"
    assert response.json()["redirect_url"].endswith("ln_assistant")


def test_assistant_gmail_oauth_callback_finishes_bound_connection_and_returns_to_identity_page(monkeypatch):
    client = _fresh_identity_client(monkeypatch)
    from app import main

    calls = []

    class Service:
        def finish_connect(self, **values):
            calls.append(values)
            return {
                "status": "connected",
                "identity_id": "nomi_gmail_primary",
                "address": "nomi.real@example.com",
                "provider": "composio_gmail",
                "capabilities": ["draft", "send", "thread_reply"],
                "connected_account_id": "ca_nomi_gmail",
                "version": 4,
            }

    class InboundService:
        def configure_inbound(self):
            calls.append({"configure_inbound": True})
            return {
                "status": "configured",
                "mode": "trigger",
                "trigger_id": "trigger_nomi_gmail",
                "identity_id": "nomi_gmail_primary",
            }

    monkeypatch.setattr(main, "_ASSISTANT_GMAIL_CONNECTION_SERVICE", Service())
    monkeypatch.setattr(main, "_ASSISTANT_GMAIL_INBOUND_SYNC_SERVICE", InboundService())

    response = client.get(
        "/api/assistant-identities/oauth/callback",
        params={
            "identity_id": "nomi_gmail_primary",
            "state": "state-1",
            "status": "success",
            "connected_account_id": "ca_nomi_gmail",
        },
    )

    assert response.status_code == 200
    assert calls == [
        {
            "identity_id": "nomi_gmail_primary",
            "state": "state-1",
            "callback_status": "success",
            "connected_account_id": "ca_nomi_gmail",
        },
        {"configure_inbound": True},
    ]
    assert "nomi.real@example.com" in response.text
    assert "收件监听：trigger" in response.text
    assert "返回助理身份" in response.text
    assert 'href="/#assistant-identities"' in response.text
    assert 'href="nomi://composio/connected?toolkit=gmail&amp;status=success&amp;assistant_identity=nomi_gmail_primary"' in response.text


def test_assistant_gmail_oauth_callback_accepts_composio_camel_case_account_id(monkeypatch):
    client = _fresh_identity_client(monkeypatch)
    from app import main

    calls = []

    class Service:
        def finish_connect(self, **values):
            calls.append(values)
            return {
                "status": "connected",
                "identity_id": "nomi_gmail_primary",
                "address": "nomi.real@example.com",
            }

    class InboundService:
        def configure_inbound(self):
            return {
                "status": "configured",
                "mode": "polling",
                "identity_id": "nomi_gmail_primary",
            }

    monkeypatch.setattr(main, "_ASSISTANT_GMAIL_CONNECTION_SERVICE", Service())
    monkeypatch.setattr(main, "_ASSISTANT_GMAIL_INBOUND_SYNC_SERVICE", InboundService())

    response = client.get(
        "/api/assistant-identities/oauth/callback",
        params={
            "identity_id": "nomi_gmail_primary",
            "state": "state-1",
            "status": "success",
            "connectedAccountId": "ca_from_composio",
            "appName": "gmail",
        },
    )

    assert response.status_code == 200
    assert calls == [
        {
            "identity_id": "nomi_gmail_primary",
            "state": "state-1",
            "callback_status": "success",
            "connected_account_id": "ca_from_composio",
        }
    ]


def test_assistant_gmail_oauth_callback_rejects_invalid_state_without_success_page(monkeypatch):
    client = _fresh_identity_client(monkeypatch)
    from app import main
    from app.assistant_identity.composio_gmail import AssistantGmailConnectionError

    class Service:
        def finish_connect(self, **values):
            raise AssistantGmailConnectionError("oauth_state_mismatch")

    monkeypatch.setattr(main, "_ASSISTANT_GMAIL_CONNECTION_SERVICE", Service())

    response = client.get(
        "/api/assistant-identities/oauth/callback",
        params={
            "identity_id": "nomi_gmail_primary",
            "state": "forged",
            "status": "success",
            "connected_account_id": "ca_nomi_gmail",
        },
    )

    assert response.status_code == 400
    assert "oauth_state_mismatch" in response.text
    assert "授权成功" not in response.text
    assert 'href="/#assistant-identities"' in response.text
    assert 'href="nomi://composio/connected?toolkit=gmail&amp;status=error&amp;assistant_identity=nomi_gmail_primary"' in response.text


def test_assistant_gmail_verify_endpoint_uses_pinned_provider_account(monkeypatch):
    client = _fresh_identity_client(monkeypatch)
    headers = {"x-par-password": "test-password"}
    from app import main

    class Service:
        def verify_existing_connection(self, identity_id):
            assert identity_id == "nomi_gmail_primary"
            return {
                "status": "connected",
                "identity_id": identity_id,
                "address": "nomi.real@example.com",
                "connected_account_id": "ca_nomi_gmail",
                "version": 5,
            }

    class InboundService:
        def configure_inbound(self):
            return {
                "status": "configured",
                "mode": "bounded_incremental_sync",
                "identity_id": "nomi_gmail_primary",
                "created_count": 2,
                "duplicate_count": 1,
                "fetched_count": 3,
            }

    monkeypatch.setattr(main, "_ASSISTANT_GMAIL_CONNECTION_SERVICE", Service())
    monkeypatch.setattr(main, "_ASSISTANT_GMAIL_INBOUND_SYNC_SERVICE", InboundService())

    response = client.post(
        "/api/assistant-identities/nomi_gmail_primary/verify",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["address"] == "nomi.real@example.com"
    assert response.json()["connected_account_id"] == "ca_nomi_gmail"
    assert response.json()["inbound"]["mode"] == "bounded_incremental_sync"
    assert response.json()["inbound"]["created_count"] == 2


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

    confirmation = client.post(
        f"/api/assistant-outbound/drafts/{draft['draft_id']}/confirm",
        headers=headers,
    )
    assert confirmation.status_code == 200
    confirmation_payload = confirmation.json()
    assert confirmation_payload["draft_id"] == draft["draft_id"]
    assert confirmation_payload["actor"] == "local_owner"

    sent = client.post(
        f"/api/assistant-outbound/drafts/{draft['draft_id']}/send",
        headers=headers,
        json={"confirmation_token": confirmation_payload["confirmation_token"]},
    )

    assert sent.status_code == 200
    sent_payload = sent.json()
    assert sent_payload["status"] == "blocked"
    assert sent_payload["reason"] == "assistant_gmail_identity_not_verified"
    assert sent_payload["provider"] == "composio_gmail"
    assert sent_payload["send_called"] is True

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


def test_assistant_inbox_reads_persisted_gmail_events_and_deduplicates_sync(monkeypatch):
    from app import main
    from app.assistant_identity.gmail_sync import InMemoryAssistantInboxEventRepository

    main._ASSISTANT_INBOX_EVENT_REPOSITORY = InMemoryAssistantInboxEventRepository()
    main._ASSISTANT_INBOX_EVENTS.clear()
    client = _fresh_identity_client(monkeypatch)
    headers = {"x-par-password": "test-password"}
    request = {
        "identity_id": "nomi_gmail_primary",
        "message": {
            "id": "gmail-api-persisted-1",
            "thread_id": "thread-persisted",
            "from": "owner@example.com",
            "to": ["nomi@example.com"],
            "subject": "持久化收件箱",
            "body": "这封邮件重启后仍应可见。",
            "date": "2026-07-21T10:00:00Z",
        },
        "user_keys": ["owner@example.com"],
    }

    first = client.post("/api/assistant-inbox/gmail/sync", headers=headers, json=request)
    second = client.post("/api/assistant-inbox/gmail/sync", headers=headers, json=request)

    assert first.status_code == 200
    assert first.json()["status"] == "accepted"
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    main._ASSISTANT_INBOX_EVENTS.clear()

    listed = client.get("/api/assistant-inbox", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    assert listed.json()["items"][0]["external_message_id"] == "gmail-api-persisted-1"

    event_id = first.json()["event"]["event_id"]
    detail = client.get(f"/api/assistant-inbox/{event_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["event"]["normalized_text"] == "这封邮件重启后仍应可见。"


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

    confirmation = client.post(
        f"/api/assistant-outbound/drafts/{draft['draft_id']}/confirm",
        headers=headers,
    ).json()
    queued = client.post(
        f"/api/assistant-outbound/drafts/{draft['draft_id']}/call",
        headers=headers,
        json={"confirmation_token": confirmation["confirmation_token"]},
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

    confirmation = client.post(
        f"/api/assistant-outbound/drafts/{draft['draft_id']}/confirm",
        headers=headers,
    ).json()
    queued = client.post(
        f"/api/assistant-outbound/drafts/{draft['draft_id']}/call",
        headers=headers,
        json={"confirmation_token": confirmation["confirmation_token"]},
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


def test_assistant_tool_endpoint_uses_server_executor_and_rejects_client_scope(monkeypatch):
    client = _fresh_identity_client(monkeypatch)
    headers = {"x-par-password": "test-password"}
    from app import main

    calls = []

    class Executor:
        def execute(self, **values):
            calls.append(values)
            return {
                "status": "confirmation_required",
                "draft_id": "draft-safe-1",
            }

    monkeypatch.setattr(main, "_ASSISTANT_SCOPED_TOOL_EXECUTOR", Executor())
    response = client.post(
        "/api/assistant-tools/execute",
        headers=headers,
        json={
            "task_id": "lta_789",
            "tool_name": "assistant.email.create_draft",
            "arguments": {"task_id": "lta_789"},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "confirmation_required",
        "draft_id": "draft-safe-1",
    }
    assert calls == [
        {
            "task_id": "lta_789",
            "tool_name": "assistant.email.create_draft",
            "arguments": {"task_id": "lta_789"},
        }
    ]

    forged = client.post(
        "/api/assistant-tools/execute",
        headers=headers,
        json={
            "task_id": "lta_789",
            "tool_name": "assistant.email.create_draft",
            "arguments": {"task_id": "lta_789"},
            "task_scope": {
                "permitted_tool_names": ["assistant.email.create_draft"],
            },
        },
    )
    assert forged.status_code == 422


def test_assistant_delivery_receipt_updates_same_draft_and_exposes_redacted_audit(monkeypatch):
    client = _fresh_identity_client(monkeypatch)
    headers = {"x-par-password": "test-password"}
    from app import main
    from app.assistant_identity.audit import AssistantIdentityAuditor, InMemoryAssistantAuditRepository
    from app.assistant_identity.outbound import OutboundMessagePipeline

    class Adapter:
        def send_message(self, **values):
            return {
                "status": "sent",
                "provider": "test_gmail",
                "provider_message_id": "provider-receipt-1",
                "provider_result": {"accepted": True},
            }

    audit_repository = InMemoryAssistantAuditRepository()
    main._ASSISTANT_AUDIT_REPOSITORY = audit_repository
    main._ASSISTANT_OUTBOUND_PIPELINE = OutboundMessagePipeline(
        gmail_adapter=Adapter(),
        auditor=AssistantIdentityAuditor(audit_repository),
    )
    draft = client.post(
        "/api/assistant-outbound/drafts",
        headers=headers,
        json={
            "identity_id": "nomi_gmail_primary",
            "channel": "gmail",
            "recipient": "alice.private@example.com",
            "subject": "回执",
            "body_text": "私密正文",
            "source_evidence_ids": ["evt_receipt"],
        },
    ).json()
    confirmation = client.post(
        f"/api/assistant-outbound/drafts/{draft['draft_id']}/confirm",
        headers=headers,
    ).json()
    sent = client.post(
        f"/api/assistant-outbound/drafts/{draft['draft_id']}/send",
        headers=headers,
        json={"confirmation_token": confirmation["confirmation_token"]},
    )
    assert sent.status_code == 200

    receipt = client.post(
        "/api/assistant-outbound/receipts",
        headers=headers,
        json={
            "identity_id": "nomi_gmail_primary",
            "provider_message_id": "provider-receipt-1",
            "status": "delivered",
            "receipt_payload": {"body": "private provider receipt"},
        },
    )
    assert receipt.status_code == 200
    assert receipt.json()["draft_id"] == draft["draft_id"]
    assert receipt.json()["status"] == "delivered"
    assert main._ASSISTANT_OUTBOUND_PIPELINE.get_draft(draft["draft_id"])["status"] == "delivered"

    audit = client.get(
        "/api/assistant-audit",
        headers=headers,
        params={"identity_id": "nomi_gmail_primary", "draft_id": draft["draft_id"]},
    )
    assert audit.status_code == 200
    assert audit.json()["items"][-1]["action"] == "outbound.delivery_receipt"
    serialized = str(audit.json())
    assert "private provider receipt" not in serialized
    assert "alice.private@example.com" not in serialized


def test_assistant_outbound_draft_list_is_persistent_filterable_and_token_free(monkeypatch):
    client = _fresh_identity_client(monkeypatch)
    headers = {"x-par-password": "test-password"}
    from app import main
    from app.assistant_identity.outbound import OutboundMessagePipeline
    from app.assistant_identity.outbound_repository import InMemoryAssistantOutboundRepository

    main._ASSISTANT_OUTBOUND_PIPELINE = OutboundMessagePipeline(
        repository=InMemoryAssistantOutboundRepository()
    )
    created = client.post(
        "/api/assistant-outbound/drafts",
        headers=headers,
        json={
            "identity_id": "nomi_gmail_primary",
            "channel": "gmail",
            "recipient": "pending@example.com",
            "subject": "待确认",
            "body_text": "请核对后发送。",
            "source_evidence_ids": ["evt_pending"],
        },
    ).json()
    confirmation = client.post(
        f"/api/assistant-outbound/drafts/{created['draft_id']}/confirm",
        headers=headers,
    )
    assert confirmation.status_code == 200

    response = client.get(
        "/api/assistant-outbound/drafts?status=draft&limit=20",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["draft_id"] == created["draft_id"]
    assert "confirmation_token" not in str(payload).lower()


def test_assistant_outbound_message_history_survives_pipeline_restart(monkeypatch):
    client = _fresh_identity_client(monkeypatch)
    headers = {"x-par-password": "test-password"}
    from app import main
    from app.assistant_identity.outbound import OutboundMessagePipeline
    from app.assistant_identity.outbound_repository import InMemoryAssistantOutboundRepository

    class Adapter:
        def send_message(self, **values):
            return {
                "status": "sent",
                "provider": "test_gmail",
                "provider_message_id": "provider-restart-1",
                "provider_result": {"accepted": True},
            }

    repository = InMemoryAssistantOutboundRepository()
    main._ASSISTANT_OUTBOUND_PIPELINE = OutboundMessagePipeline(
        repository=repository,
        gmail_adapter=Adapter(),
    )
    created = client.post(
        "/api/assistant-outbound/drafts",
        headers=headers,
        json={
            "identity_id": "nomi_gmail_primary",
            "channel": "gmail",
            "recipient": "history@example.com",
            "subject": "重启历史",
            "body_text": "这条消息必须在重启后保留。",
            "source_evidence_ids": ["evt_restart"],
        },
    ).json()
    confirmation = client.post(
        f"/api/assistant-outbound/drafts/{created['draft_id']}/confirm",
        headers=headers,
    ).json()
    sent = client.post(
        f"/api/assistant-outbound/drafts/{created['draft_id']}/send",
        headers=headers,
        json={"confirmation_token": confirmation["confirmation_token"]},
    )
    assert sent.status_code == 200

    main._ASSISTANT_OUTBOUND_MESSAGES.clear()
    main._ASSISTANT_OUTBOUND_PIPELINE = OutboundMessagePipeline(repository=repository)
    response = client.get("/api/assistant-outbound/messages", headers=headers)

    assert response.status_code == 200
    assert response.json()["count"] == 1
    item = response.json()["items"][0]
    assert item["draft_id"] == created["draft_id"]
    assert item["status"] == "sent"
    assert item["provider_message_id"] == "provider-restart-1"
    assert "confirmation_token" not in str(response.json()).lower()
