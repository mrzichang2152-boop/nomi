import json
import os
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_ios_settings_defaults_are_conservative():
    from app.ios_live_activity import normalize_ios_live_activity_settings

    settings = normalize_ios_live_activity_settings({})

    assert settings["live_activity_enabled"] is True
    assert settings["notification_fallback_enabled"] is True
    assert settings["deep_links_enabled"] is True
    assert settings["token_level_chat_streaming_enabled"] is False
    assert settings["token_level_chat_delivery"] == "local_when_foreground"
    assert settings["sensitive_apns_payload_enabled"] is False
    assert settings["include_private_message_body"] is False
    assert settings["include_contact_names"] is False
    assert settings["include_raw_private_context"] is False
    assert settings["max_sensitive_payload_chars"] == 2400


def test_ios_settings_accept_explicit_sensitive_and_token_modes():
    from app.ios_live_activity import normalize_ios_live_activity_settings

    settings = normalize_ios_live_activity_settings(
        {
            "token_level_chat_streaming_enabled": True,
            "token_level_chat_delivery": "local_and_apns_best_effort",
            "sensitive_apns_payload_enabled": True,
            "include_private_message_body": True,
            "include_contact_names": True,
            "include_raw_private_context": True,
            "max_sensitive_payload_chars": 3200,
        }
    )

    assert settings["token_level_chat_streaming_enabled"] is True
    assert settings["token_level_chat_delivery"] == "local_and_apns_best_effort"
    assert settings["sensitive_apns_payload_enabled"] is True
    assert settings["include_private_message_body"] is True
    assert settings["include_contact_names"] is True
    assert settings["include_raw_private_context"] is True
    assert settings["max_sensitive_payload_chars"] == 3200


def test_ios_settings_reject_unknown_token_delivery_mode():
    from app.ios_live_activity import normalize_ios_live_activity_settings

    settings = normalize_ios_live_activity_settings({"token_level_chat_delivery": "websocket_forever"})

    assert settings["token_level_chat_delivery"] == "local_when_foreground"


def test_ios_live_activity_schema_contains_required_tables():
    from app.ios_live_activity import ios_live_activity_schema_sql

    sql = "\n".join(ios_live_activity_schema_sql())

    assert "CREATE TABLE IF NOT EXISTS ios_devices" in sql
    assert "CREATE TABLE IF NOT EXISTS ios_live_activities" in sql
    assert "CREATE TABLE IF NOT EXISTS ios_live_activity_events" in sql
    assert "ios_live_activities_device_status_idx" in sql


def test_register_ios_device_persists_normalized_settings(monkeypatch):
    from app import main

    calls = []

    class Cursor:
        rowcount = 1

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=None):
            calls.append((sql, params))
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "require_password", lambda password: None)

    result = main.register_ios_device(
        main.IOSDeviceRegisterIn(
            device_id="ios-device-1",
            display_name="Will's iPhone",
            apns_environment="sandbox",
            settings={"sensitive_apns_payload_enabled": True},
        ),
        x_par_password="secret",
    )

    assert result["device_id"] == "ios-device-1"
    assert result["settings"]["sensitive_apns_payload_enabled"] is True
    assert "INSERT INTO ios_devices" in calls[0][0]
    stored_settings = json.loads(calls[0][1][6])
    assert stored_settings["token_level_chat_delivery"] == "local_when_foreground"


def test_register_ios_live_activity_requires_existing_device(monkeypatch):
    from app import main

    class Cursor:
        def fetchone(self):
            return None

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=None):
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "require_password", lambda password: None)

    with pytest.raises(main.HTTPException) as exc:
        main.register_ios_live_activity(
            main.IOSLiveActivityRegisterIn(
                device_id="missing-device",
                activity_id="activity-1",
                update_token="update-token",
            ),
            x_par_password="secret",
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "ios device not found"


def test_safe_payload_excludes_private_message_body():
    from app.ios_live_activity import build_live_activity_content_state

    event = {
        "type": "proactive_message",
        "suggestion_id": "s1",
        "title": "客户问报价",
        "body": "Alice: 报价今天还能确认吗？",
        "source": "whatsapp",
    }
    settings = {
        "sensitive_apns_payload_enabled": False,
        "deep_links_enabled": True,
    }

    state = build_live_activity_content_state(event, settings, private_context={"contact": "Alice"})

    assert state["payloadMode"] == "safe"
    assert state["title"] == "Nomi has a new suggestion"
    assert state["body"] == "Open Nomi to review it."
    assert "privateContext" not in state
    assert state["deepLink"] == "nomi://suggestion?id=s1"


def test_sensitive_payload_includes_user_enabled_private_context():
    from app.ios_live_activity import build_live_activity_content_state

    event = {
        "type": "proactive_message",
        "suggestion_id": "s1",
        "title": "客户问报价",
        "body": "Alice: 报价今天还能确认吗？",
        "source": "whatsapp",
    }
    settings = {
        "sensitive_apns_payload_enabled": True,
        "include_private_message_body": True,
        "include_contact_names": True,
        "include_raw_private_context": True,
        "max_sensitive_payload_chars": 2400,
        "deep_links_enabled": True,
    }

    state = build_live_activity_content_state(
        event,
        settings,
        private_context={"contact": "Alice", "channel": "whatsapp", "rawSnippet": "Alice: 报价今天还能确认吗？"},
    )

    assert state["payloadMode"] == "sensitive"
    assert state["title"] == "客户问报价"
    assert state["body"] == "Alice: 报价今天还能确认吗？"
    assert state["privateContext"]["contact"] == "Alice"
    assert state["privateContext"]["rawSnippet"] == "Alice: 报价今天还能确认吗？"


def test_chat_delta_payload_includes_partial_answer_only_in_sensitive_mode():
    from app.ios_live_activity import build_live_activity_content_state

    safe_state = build_live_activity_content_state(
        {
            "type": "chat_delta",
            "conversation_id": "c1",
            "partial_answer": "可以，我先帮你核对",
            "token_sequence": 7,
        },
        {
            "token_level_chat_streaming_enabled": True,
            "sensitive_apns_payload_enabled": False,
            "deep_links_enabled": True,
        },
    )
    sensitive_state = build_live_activity_content_state(
        {
            "type": "chat_delta",
            "conversation_id": "c1",
            "partial_answer": "可以，我先帮你核对",
            "token_sequence": 7,
        },
        {
            "token_level_chat_streaming_enabled": True,
            "sensitive_apns_payload_enabled": True,
            "deep_links_enabled": True,
        },
    )

    assert safe_state["phase"] == "chat_streaming"
    assert safe_state["partialAnswer"] == ""
    assert safe_state["payloadMode"] == "safe"
    assert safe_state["deepLink"] == "nomi://chat?conversation_id=c1"
    assert sensitive_state["partialAnswer"] == "可以，我先帮你核对"
    assert sensitive_state["payloadMode"] == "sensitive"
    assert sensitive_state["tokenSequence"] == 7


def test_deep_links_disabled_omits_live_activity_url():
    from app.ios_live_activity import build_live_activity_content_state, deep_link_for_event

    settings = {"deep_links_enabled": False}
    event = {"type": "proactive_message", "suggestion_id": "s1"}

    assert deep_link_for_event(event, settings) == ""
    assert build_live_activity_content_state(event, settings)["deepLink"] == ""


def test_payload_truncates_large_sensitive_content():
    from app.ios_live_activity import build_live_activity_content_state

    long_text = "敏感内容" * 500
    state = build_live_activity_content_state(
        {
            "type": "proactive_message",
            "suggestion_id": "s1",
            "title": "长消息",
            "body": long_text,
            "source": "gmail",
        },
        {
            "sensitive_apns_payload_enabled": True,
            "include_private_message_body": True,
            "include_raw_private_context": True,
            "max_sensitive_payload_chars": 400,
        },
        private_context={"rawSnippet": long_text},
    )

    assert state["truncated"] is True
    assert len(state["body"]) <= 240
    assert len(state["privateContext"]["rawSnippet"]) <= 360


def test_apns_live_activity_payload_wraps_content_state():
    from app.ios_apns import build_live_activity_apns_payload

    payload = build_live_activity_apns_payload(
        {"phase": "idle", "title": "Nomi", "body": "Ready", "deepLink": "nomi://chat"},
        event="update",
        stale_after_seconds=600,
    )

    assert payload["aps"]["event"] == "update"
    assert payload["aps"]["content-state"]["title"] == "Nomi"
    assert "timestamp" in payload["aps"]
    assert payload["aps"]["stale-date"] >= payload["aps"]["timestamp"] + 600


def test_standard_apns_alert_payload_uses_safe_defaults_and_deep_link():
    from app.ios_apns import build_alert_apns_payload

    payload = build_alert_apns_payload(
        title="Nomi has a new suggestion",
        body="Open Nomi to review it.",
        deep_link="nomi://suggestion?id=s1",
    )

    assert payload["aps"]["alert"]["title"] == "Nomi has a new suggestion"
    assert payload["aps"]["alert"]["body"] == "Open Nomi to review it."
    assert payload["deep_link"] == "nomi://suggestion?id=s1"


def test_apns_config_uses_live_activity_topic_and_environment():
    from app.ios_apns import APNsConfig

    sandbox = APNsConfig(
        team_id="TEAM",
        key_id="KEY",
        bundle_id="com.example.nomi",
        private_key_p8="key",
        environment="sandbox",
    )
    production = APNsConfig(
        team_id="TEAM",
        key_id="KEY",
        bundle_id="com.example.nomi",
        private_key_p8="key",
        environment="production",
    )

    assert sandbox.base_url == "https://api.sandbox.push.apple.com"
    assert production.base_url == "https://api.push.apple.com"
    assert sandbox.alert_topic == "com.example.nomi"
    assert sandbox.live_activity_topic == "com.example.nomi.push-type.liveactivity"


@pytest.mark.asyncio
async def test_apns_client_reports_misconfigured_without_network_call():
    from app.ios_apns import APNsConfig, APNsLiveActivityClient

    client = APNsLiveActivityClient(
        APNsConfig(
            team_id="",
            key_id="",
            bundle_id="com.example.nomi",
            private_key_p8="",
            environment="sandbox",
        )
    )

    result = await client.send_update("token", {"phase": "idle"})

    assert result["status"] == "misconfigured"
    assert result["status_code"] == 0


def test_active_ios_live_activities_normalizes_device_settings():
    from app.ios_live_activity import active_ios_live_activities

    class Cursor:
        def fetchall(self):
            return [
                (
                    "activity-1",
                    "device-1",
                    "update-token",
                    {"sensitive_apns_payload_enabled": True, "token_level_chat_delivery": "invalid"},
                )
            ]

    class Conn:
        def execute(self, sql, params=None):
            return Cursor()

    activities = active_ios_live_activities(Conn())

    assert activities == [
        {
            "activity_id": "activity-1",
            "device_id": "device-1",
            "update_token": "update-token",
            "apns_device_token": "",
            "settings": {
                "live_activity_enabled": True,
                "notification_fallback_enabled": True,
                "deep_links_enabled": True,
                "token_level_chat_streaming_enabled": False,
                "token_level_chat_delivery": "local_when_foreground",
                "sensitive_apns_payload_enabled": True,
                "include_private_message_body": False,
                "include_contact_names": False,
                "include_raw_private_context": False,
                "max_sensitive_payload_chars": 2400,
            },
        }
    ]


def test_record_ios_live_activity_delivery_writes_audit_row():
    from app.ios_live_activity import record_ios_live_activity_delivery

    calls = []

    class Conn:
        def execute(self, sql, params=None):
            calls.append((sql, params))

    record_ios_live_activity_delivery(
        Conn(),
        activity_id="activity-1",
        device_id="device-1",
        event_type="proactive_message",
        source_id="suggestion-1",
        payload_mode="sensitive",
        delivery_status="sent",
        payload={"aps": {"event": "update"}},
        error="",
    )

    assert "INSERT INTO ios_live_activity_events" in calls[0][0]
    assert calls[0][1][1] == "activity-1"
    assert calls[0][1][2] == "device-1"
    assert calls[0][1][5] == "sensitive"
    assert json.loads(calls[0][1][7]) == {"aps": {"event": "update"}}


@pytest.mark.asyncio
async def test_push_realtime_event_to_ios_live_activities_delivers_and_audits(monkeypatch):
    from app import main

    calls = []

    class SelectCursor:
        def fetchall(self):
            return [
                (
                    "activity-1",
                    "device-1",
                    "update-token",
                    {
                        "live_activity_enabled": True,
                        "sensitive_apns_payload_enabled": True,
                        "include_private_message_body": True,
                    },
                )
            ]

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=None):
            calls.append((sql, params))
            if "SELECT a.activity_id" in sql:
                return SelectCursor()
            return None

    class FakeAPNs:
        def __init__(self):
            self.sent = []

        async def send_update(self, update_token, content_state):
            self.sent.append((update_token, content_state))
            return {"status": "sent", "payload": {"aps": {"content-state": content_state}}}

    fake_apns = FakeAPNs()
    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "fetch_ios_private_context_for_event", lambda conn, event, settings: {})

    await main.push_realtime_event_to_ios_live_activities(
        {
            "type": "proactive_message",
            "suggestion_id": "s1",
            "title": "客户问报价",
            "body": "Alice: 报价今天还能确认吗？",
            "source": "whatsapp",
        },
        fake_apns,
    )

    assert fake_apns.sent[0][0] == "update-token"
    assert fake_apns.sent[0][1]["payloadMode"] == "sensitive"
    assert fake_apns.sent[0][1]["title"] == "客户问报价"
    assert any("INSERT INTO ios_live_activity_events" in sql for sql, _params in calls)


@pytest.mark.asyncio
async def test_push_realtime_event_falls_back_to_standard_notification_when_live_activity_fails(monkeypatch):
    from app import main

    calls = []

    class SelectCursor:
        def fetchall(self):
            return [
                (
                    "activity-1",
                    "device-1",
                    "update-token",
                    {
                        "live_activity_enabled": True,
                        "notification_fallback_enabled": True,
                        "sensitive_apns_payload_enabled": False,
                    },
                    "device-apns-token",
                )
            ]

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=None):
            calls.append((sql, params))
            if "SELECT a.activity_id" in sql:
                return SelectCursor()
            return None

    class FakeAPNs:
        def __init__(self):
            self.alerts = []

        async def send_update(self, update_token, content_state):
            return {"status": "failed", "error": "BadDeviceToken", "payload": {"aps": {"content-state": content_state}}}

        async def send_alert(self, device_token, title, body, deep_link):
            self.alerts.append((device_token, title, body, deep_link))
            return {"status": "sent", "payload": {"aps": {"alert": {"title": title, "body": body}}}}

    fake_apns = FakeAPNs()
    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "fetch_ios_private_context_for_event", lambda conn, event, settings: {})

    await main.push_realtime_event_to_ios_live_activities(
        {
            "type": "proactive_message",
            "suggestion_id": "s1",
            "title": "客户问报价",
            "body": "Alice: 报价今天还能确认吗？",
            "source": "whatsapp",
        },
        fake_apns,
    )

    assert fake_apns.alerts == [
        (
            "device-apns-token",
            "Nomi has a new suggestion",
            "Open Nomi to review it.",
            "nomi://suggestion?id=s1",
        )
    ]
    assert any(params and params[6] == "notification_fallback_sent" for _sql, params in calls)


@pytest.mark.asyncio
async def test_maybe_push_ios_chat_delta_sends_when_apns_token_streaming_enabled(monkeypatch):
    from app import main

    calls = []

    class SelectCursor:
        def fetchone(self):
            return (
                "activity-1",
                "device-1",
                "update-token",
                {
                    "live_activity_enabled": True,
                    "token_level_chat_streaming_enabled": True,
                    "token_level_chat_delivery": "apns_best_effort",
                    "sensitive_apns_payload_enabled": True,
                },
            )

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=None):
            calls.append((sql, params))
            if "SELECT a.activity_id" in sql:
                return SelectCursor()
            return None

    class FakeAPNs:
        def __init__(self):
            self.sent = []

        async def send_update(self, update_token, content_state):
            self.sent.append((update_token, content_state))
            return {"status": "sent", "payload": {"aps": {"content-state": content_state}}}

    fake_apns = FakeAPNs()
    monkeypatch.setattr(main, "db", lambda: Conn())

    await main.maybe_push_ios_chat_delta(
        "activity-1",
        "conversation-1",
        "可以，我先帮你核对",
        3,
        apns=fake_apns,
    )

    assert fake_apns.sent == [
        (
            "update-token",
            {
                "phase": "chat_streaming",
                "title": "Nomi is replying",
                "body": "正在生成回复",
                "source": "chat",
                "suggestionId": "",
                "taskId": "",
                "conversationId": "conversation-1",
                "unreadCount": 0,
                "partialAnswer": "可以，我先帮你核对",
                "tokenSequence": 3,
                "payloadMode": "sensitive",
                "deepLink": "nomi://chat?conversation_id=conversation-1",
                "truncated": False,
            },
        )
    ]
    assert any("INSERT INTO ios_live_activity_events" in sql for sql, _params in calls)


@pytest.mark.asyncio
async def test_maybe_push_ios_chat_delta_skips_when_apns_token_streaming_disabled(monkeypatch):
    from app import main

    class SelectCursor:
        def fetchone(self):
            return (
                "activity-1",
                "device-1",
                "update-token",
                {
                    "live_activity_enabled": True,
                    "token_level_chat_streaming_enabled": False,
                    "token_level_chat_delivery": "apns_best_effort",
                    "sensitive_apns_payload_enabled": True,
                },
            )

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=None):
            if "SELECT a.activity_id" in sql:
                return SelectCursor()
            return None

    class FakeAPNs:
        def __init__(self):
            self.sent = []

        async def send_update(self, update_token, content_state):
            self.sent.append((update_token, content_state))
            return {"status": "sent"}

    fake_apns = FakeAPNs()
    monkeypatch.setattr(main, "db", lambda: Conn())

    await main.maybe_push_ios_chat_delta(
        "activity-1",
        "conversation-1",
        "敏感回复",
        1,
        apns=fake_apns,
    )

    assert fake_apns.sent == []
