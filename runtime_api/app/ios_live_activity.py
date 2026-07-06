from __future__ import annotations

import json
import uuid
from typing import Any


IOS_LIVE_ACTIVITY_DEFAULT_SETTINGS: dict[str, Any] = {
    "live_activity_enabled": True,
    "notification_fallback_enabled": True,
    "deep_links_enabled": True,
    "token_level_chat_streaming_enabled": False,
    "token_level_chat_delivery": "local_when_foreground",
    "sensitive_apns_payload_enabled": False,
    "include_private_message_body": False,
    "include_contact_names": False,
    "include_raw_private_context": False,
    "max_sensitive_payload_chars": 2400,
}

TOKEN_DELIVERY_MODES = {
    "local_when_foreground",
    "apns_best_effort",
    "local_and_apns_best_effort",
}


def normalize_ios_live_activity_settings(value: dict[str, Any] | None) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    settings = dict(IOS_LIVE_ACTIVITY_DEFAULT_SETTINGS)
    for key in settings:
        if key in raw:
            settings[key] = raw[key]
    if settings["token_level_chat_delivery"] not in TOKEN_DELIVERY_MODES:
        settings["token_level_chat_delivery"] = "local_when_foreground"
    settings["max_sensitive_payload_chars"] = max(
        0,
        min(3400, int(settings.get("max_sensitive_payload_chars") or 0)),
    )
    for key in [
        "live_activity_enabled",
        "notification_fallback_enabled",
        "deep_links_enabled",
        "token_level_chat_streaming_enabled",
        "sensitive_apns_payload_enabled",
        "include_private_message_body",
        "include_contact_names",
        "include_raw_private_context",
    ]:
        settings[key] = bool(settings.get(key))
    return settings


def ios_live_activity_schema_sql() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS ios_devices (
          id UUID PRIMARY KEY,
          device_id TEXT NOT NULL UNIQUE,
          display_name TEXT NOT NULL DEFAULT '',
          apns_environment TEXT NOT NULL DEFAULT 'sandbox',
          apns_device_token TEXT NOT NULL DEFAULT '',
          live_activity_push_to_start_token TEXT NOT NULL DEFAULT '',
          settings JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ios_live_activities (
          id UUID PRIMARY KEY,
          device_id TEXT NOT NULL REFERENCES ios_devices(device_id) ON DELETE CASCADE,
          activity_id TEXT NOT NULL UNIQUE,
          activity_kind TEXT NOT NULL DEFAULT 'nomi_status',
          update_token TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          last_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          ended_at TIMESTAMPTZ
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ios_live_activity_events (
          id UUID PRIMARY KEY,
          activity_id TEXT NOT NULL,
          device_id TEXT NOT NULL,
          event_type TEXT NOT NULL,
          source_id TEXT NOT NULL DEFAULT '',
          payload_mode TEXT NOT NULL DEFAULT 'safe',
          delivery_status TEXT NOT NULL DEFAULT 'pending',
          payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          error TEXT NOT NULL DEFAULT '',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS ios_live_activities_device_status_idx
        ON ios_live_activities(device_id, status, updated_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS ios_live_activity_events_activity_idx
        ON ios_live_activity_events(activity_id, created_at DESC)
        """,
    ]


def deep_link_for_event(event: dict[str, Any], settings: dict[str, Any]) -> str:
    if not settings.get("deep_links_enabled", True):
        return ""
    event_type = str(event.get("type") or "")
    if event_type == "proactive_message":
        suggestion_id = str(event.get("suggestion_id") or event.get("id") or "")
        return f"nomi://suggestion?id={suggestion_id}" if suggestion_id else "nomi://chat"
    if event_type in {"agent_task_delivery", "agent_task_fallback"}:
        task_id = str(event.get("task_id") or "")
        return f"nomi://task?id={task_id}" if task_id else "nomi://chat"
    if event_type in {"chat_delta", "chat_done", "chat_streaming"}:
        conversation_id = str(event.get("conversation_id") or "")
        return f"nomi://chat?conversation_id={conversation_id}" if conversation_id else "nomi://chat"
    return "nomi://chat"


def build_live_activity_content_state(
    event: dict[str, Any],
    settings: dict[str, Any] | None,
    private_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = normalize_ios_live_activity_settings(settings)
    event_type = str(event.get("type") or "")
    source = str(event.get("source") or "unknown")
    sensitive = bool(normalized.get("sensitive_apns_payload_enabled"))
    private_context = private_context if isinstance(private_context, dict) else {}

    if event_type == "proactive_message":
        suggestion_id = str(event.get("suggestion_id") or event.get("id") or "")
        state = {
            "phase": "suggestion",
            "title": "Nomi has a new suggestion",
            "body": "Open Nomi to review it.",
            "source": source,
            "suggestionId": suggestion_id,
            "taskId": "",
            "conversationId": "",
            "unreadCount": int(event.get("unread_count") or 1),
            "partialAnswer": "",
            "tokenSequence": 0,
            "payloadMode": "safe",
            "deepLink": deep_link_for_event(event, normalized),
            "truncated": False,
        }
        if sensitive:
            state["payloadMode"] = "sensitive"
            if normalized.get("include_private_message_body"):
                state["title"] = str(event.get("title") or state["title"])
                state["body"] = str(event.get("body") or state["body"])
            if normalized.get("include_contact_names") or normalized.get("include_raw_private_context"):
                private_payload: dict[str, Any] = {}
                if normalized.get("include_contact_names") and private_context.get("contact"):
                    private_payload["contact"] = str(private_context["contact"])
                if private_context.get("channel"):
                    private_payload["channel"] = str(private_context["channel"])
                if normalized.get("include_raw_private_context") and private_context.get("rawSnippet"):
                    private_payload["rawSnippet"] = str(private_context["rawSnippet"])
                if private_payload:
                    state["privateContext"] = private_payload
        return trim_state_for_budget(state, normalized)

    if event_type in {"agent_task_delivery", "agent_task_fallback"}:
        task_id = str(event.get("task_id") or "")
        delivery = event.get("delivery") if isinstance(event.get("delivery"), dict) else {}
        fallback = event.get("fallback_decision") if isinstance(event.get("fallback_decision"), dict) else {}
        message = str(delivery.get("message") or fallback.get("message") or "Open Nomi to review the task.")
        return trim_state_for_budget(
            {
                "phase": "task_needs_attention" if event_type == "agent_task_fallback" else "task_done",
                "title": "Nomi task update",
                "body": message if sensitive else "Open Nomi to review the task.",
                "source": "long_tail_agent",
                "suggestionId": "",
                "taskId": task_id,
                "conversationId": "",
                "unreadCount": 0,
                "partialAnswer": "",
                "tokenSequence": 0,
                "payloadMode": "sensitive" if sensitive else "safe",
                "deepLink": deep_link_for_event(event, normalized),
                "truncated": False,
            },
            normalized,
        )

    if event_type == "chat_delta":
        partial_answer = str(event.get("partial_answer") or event.get("delta") or "")
        return trim_state_for_budget(
            {
                "phase": "chat_streaming",
                "title": "Nomi is replying",
                "body": "正在生成回复",
                "source": "chat",
                "suggestionId": "",
                "taskId": "",
                "conversationId": str(event.get("conversation_id") or ""),
                "unreadCount": 0,
                "partialAnswer": partial_answer if sensitive else "",
                "tokenSequence": int(event.get("token_sequence") or 0),
                "payloadMode": "sensitive" if sensitive else "safe",
                "deepLink": deep_link_for_event(event, normalized),
                "truncated": False,
            },
            normalized,
        )

    return {
        "phase": "idle",
        "title": "Nomi",
        "body": "Ready",
        "source": "system",
        "suggestionId": "",
        "taskId": "",
        "conversationId": "",
        "unreadCount": 0,
        "partialAnswer": "",
        "tokenSequence": 0,
        "payloadMode": "safe",
        "deepLink": "nomi://chat",
        "truncated": False,
    }


def trim_state_for_budget(state: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    limit = int(settings.get("max_sensitive_payload_chars") or 2400)
    encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= min(3600, limit + 900):
        return state
    trimmed = dict(state)
    trimmed["truncated"] = True
    for key in ["partialAnswer", "body"]:
        value = str(trimmed.get(key) or "")
        if len(value) > 240:
            trimmed[key] = value[-240:]
    private_context = trimmed.get("privateContext")
    if isinstance(private_context, dict):
        raw = str(private_context.get("rawSnippet") or "")
        if len(raw) > 360:
            private_context["rawSnippet"] = raw[-360:]
    return trimmed


def active_ios_live_activities(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT a.activity_id, a.device_id, a.update_token, d.settings, d.apns_device_token
        FROM ios_live_activities a
        JOIN ios_devices d ON d.device_id = a.device_id
        WHERE a.status = 'active'
        ORDER BY a.updated_at DESC
        """
    ).fetchall()
    return [
        {
            "activity_id": row[0],
            "device_id": row[1],
            "update_token": row[2],
            "settings": normalize_ios_live_activity_settings(row[3] or {}),
            "apns_device_token": row[4] if len(row) > 4 else "",
        }
        for row in rows
    ]


def record_ios_live_activity_delivery(
    conn: Any,
    activity_id: str,
    device_id: str,
    event_type: str,
    source_id: str,
    payload_mode: str,
    delivery_status: str,
    payload: dict[str, Any],
    error: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO ios_live_activity_events
          (id, activity_id, device_id, event_type, source_id, payload_mode, delivery_status, payload, error)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            uuid.uuid4(),
            activity_id,
            device_id,
            event_type,
            source_id,
            payload_mode,
            delivery_status,
            json.dumps(payload, ensure_ascii=False),
            error,
        ),
    )
