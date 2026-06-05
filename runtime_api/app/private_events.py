from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


SUPPORTED_SOURCES = {
    "gmail",
    "whatsapp",
    "telegram",
    "browser",
    "composio",
    "nomi_chat",
    "assistant_gmail",
    "assistant_whatsapp",
    "assistant_phone",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_hash(parts: list[Any]) -> str:
    normalized = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, default=str).strip()


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    return [str(item).strip() for item in value if str(item).strip()]


def source_specific_fields(source_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if source_type == "gmail":
        return {
            "source_event_id": payload.get("message_id") or payload.get("id"),
            "conversation_id": payload.get("thread_id") or payload.get("conversation_id"),
            "sender_id": payload.get("from") or payload.get("sender"),
            "recipient_ids": normalize_list(payload.get("to") or payload.get("recipients")),
            "text": coerce_text(payload.get("text") or payload.get("body") or payload.get("snippet")),
        }
    if source_type == "assistant_gmail":
        return {
            "source_event_id": payload.get("message_id") or payload.get("id") or payload.get("external_message_id"),
            "conversation_id": payload.get("thread_id") or payload.get("conversation_id"),
            "sender_id": payload.get("from") or payload.get("sender"),
            "recipient_ids": normalize_list(payload.get("to") or payload.get("recipients")),
            "text": coerce_text(
                payload.get("text") or payload.get("body") or payload.get("body_text") or payload.get("snippet")
            ),
        }
    if source_type == "assistant_whatsapp":
        return {
            "source_event_id": payload.get("wamid") or payload.get("message_id") or payload.get("id") or payload.get("external_message_id"),
            "conversation_id": payload.get("chat_id") or payload.get("conversation_id") or payload.get("from"),
            "sender_id": payload.get("sender") or payload.get("from"),
            "recipient_ids": normalize_list(payload.get("recipients") or payload.get("to") or payload.get("recipient_identity_id")),
            "text": coerce_text(payload.get("text") or payload.get("message") or payload.get("body_text")),
        }
    if source_type == "assistant_phone":
        return {
            "source_event_id": payload.get("provider_message_id")
            or payload.get("provider_call_id")
            or payload.get("message_id")
            or payload.get("call_id")
            or payload.get("id")
            or payload.get("external_message_id"),
            "conversation_id": payload.get("conversation_id") or payload.get("from") or payload.get("caller"),
            "sender_id": payload.get("sender") or payload.get("from") or payload.get("caller"),
            "recipient_ids": normalize_list(payload.get("recipients") or payload.get("to") or payload.get("recipient_identity_id")),
            "text": coerce_text(payload.get("text") or payload.get("message") or payload.get("body_text") or payload.get("status")),
        }
    if source_type in {"whatsapp", "telegram"}:
        return {
            "source_event_id": payload.get("message_id") or payload.get("id"),
            "conversation_id": payload.get("chat_id") or payload.get("conversation_id"),
            "sender_id": payload.get("sender") or payload.get("from"),
            "recipient_ids": normalize_list(payload.get("recipients") or payload.get("to")),
            "text": coerce_text(payload.get("text") or payload.get("message")),
        }
    if source_type == "browser":
        return {
            "source_event_id": payload.get("page_session_id") or payload.get("id") or payload.get("url"),
            "conversation_id": payload.get("page_session_id") or payload.get("url"),
            "sender_id": payload.get("actor") or "browser",
            "recipient_ids": [],
            "text": coerce_text(payload.get("visible_text") or payload.get("selected_text") or payload.get("title")),
        }
    if source_type == "nomi_chat":
        return {
            "source_event_id": payload.get("turn_id") or payload.get("id"),
            "conversation_id": payload.get("conversation_id"),
            "sender_id": payload.get("role") or "user",
            "recipient_ids": ["nomi"] if payload.get("role") == "user" else ["user"],
            "text": coerce_text(payload.get("content") or payload.get("text")),
        }
    return {
        "source_event_id": payload.get("id") or payload.get("event_id"),
        "conversation_id": payload.get("conversation_id") or payload.get("thread_id"),
        "sender_id": payload.get("sender") or payload.get("actor"),
        "recipient_ids": normalize_list(payload.get("recipient_ids") or payload.get("to")),
        "text": coerce_text(payload.get("text") or payload.get("content") or payload),
    }


def normalize_private_event(
    source_type: str,
    payload: dict[str, Any],
    *,
    source_account_id: str = "local_account",
    observed_at: str | None = None,
) -> dict[str, Any]:
    normalized_source = str(source_type or "").strip().lower()
    if normalized_source not in SUPPORTED_SOURCES:
        raise ValueError(f"unsupported private event source: {source_type}")
    raw = payload or {}
    fields = source_specific_fields(normalized_source, raw)
    occurred_at = coerce_text(raw.get("occurred_at") or raw.get("timestamp") or raw.get("date")) or (observed_at or utc_now_iso())
    observed = observed_at or utc_now_iso()
    source_event_id = coerce_text(fields.get("source_event_id")) or stable_hash([normalized_source, fields.get("conversation_id"), fields.get("text")])[:24]
    conversation_id = coerce_text(fields.get("conversation_id")) or f"{normalized_source}:unknown"
    sender_id = coerce_text(fields.get("sender_id")) or "unknown"
    text = coerce_text(fields.get("text"))
    dedupe = stable_hash([normalized_source, source_account_id, source_event_id, conversation_id, sender_id, text])
    event_id = f"evt_{dedupe[:32]}"
    return {
        "event_id": event_id,
        "source_type": normalized_source,
        "source_account_id": source_account_id,
        "source_event_id": source_event_id,
        "conversation_id": conversation_id,
        "sender_id": sender_id,
        "recipient_ids": normalize_list(fields.get("recipient_ids")),
        "occurred_at": occurred_at,
        "observed_at": observed,
        "text": text,
        "attachments": raw.get("attachments") or [],
        "raw_payload_ref": raw.get("raw_payload_ref") or f"local:{event_id}",
        "visibility_scope": raw.get("visibility_scope")
        or (
            "assistant_identity_thread"
            if normalized_source in {"assistant_gmail", "assistant_whatsapp", "assistant_phone"}
            else ("thread_scoped" if conversation_id else "global_user")
        ),
        "sensitivity_level": raw.get("sensitivity_level") or "medium",
        "dedupe_hash": dedupe,
        "raw": raw,
    }


class PrivateEventDedupeIndex:
    def __init__(self) -> None:
        self._accepted: dict[str, str] = {}

    def accept(self, event: dict[str, Any]) -> bool:
        dedupe_hash = str(event.get("dedupe_hash") or "")
        if not dedupe_hash:
            raise ValueError("event missing dedupe_hash")
        if dedupe_hash in self._accepted:
            return False
        self._accepted[dedupe_hash] = str(event.get("event_id") or "")
        return True

    def duplicate_of(self, event: dict[str, Any]) -> str | None:
        return self._accepted.get(str(event.get("dedupe_hash") or ""))


def private_event_gateway_schema_sql() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS source_events (
          event_id TEXT PRIMARY KEY,
          source_type TEXT NOT NULL DEFAULT '',
          source_account_id TEXT NOT NULL DEFAULT '',
          source_event_id TEXT NOT NULL DEFAULT '',
          conversation_id TEXT NOT NULL DEFAULT '',
          sender_id TEXT NOT NULL DEFAULT '',
          recipient_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          occurred_at TIMESTAMPTZ,
          observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          text TEXT NOT NULL DEFAULT '',
          attachments JSONB NOT NULL DEFAULT '[]'::jsonb,
          raw_payload_ref TEXT NOT NULL DEFAULT '',
          visibility_scope TEXT NOT NULL DEFAULT '',
          sensitivity_level TEXT NOT NULL DEFAULT '',
          dedupe_hash TEXT NOT NULL DEFAULT '',
          payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS source_cursors (
          source_type TEXT NOT NULL,
          source_account_id TEXT NOT NULL DEFAULT '',
          cursor_value TEXT NOT NULL DEFAULT '',
          last_observed_at TIMESTAMPTZ,
          status TEXT NOT NULL DEFAULT 'active',
          payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (source_type, source_account_id)
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS source_events_dedupe_idx
        ON source_events(dedupe_hash)
        """,
        """
        CREATE INDEX IF NOT EXISTS source_events_conversation_idx
        ON source_events(source_type, conversation_id, occurred_at DESC)
        """,
    ]
