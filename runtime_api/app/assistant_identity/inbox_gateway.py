from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.assistant_identity.contact_resolver import ContactResolver


class AssistantInboxGateway:
    def __init__(self, resolver: ContactResolver | None = None) -> None:
        self.resolver = resolver or ContactResolver()

    def normalize_gmail(self, *, identity_id: str, message: dict[str, Any]) -> dict[str, Any]:
        sender = str(message.get("from") or "")
        resolved = self.resolver.classify_sender(sender)
        classification = self._message_classification(str(resolved["sender_class"]))
        text = str(message.get("body") or message.get("text") or message.get("snippet") or "")
        event = {
            "event_id": "assistant-inbox-" + str(uuid4()),
            "source_type": "assistant_gmail",
            "source_account_id": identity_id,
            "event_type": "assistant_email_received",
            "identity_id": identity_id,
            "conversation_id": str(message.get("thread_id") or message.get("conversation_id") or ""),
            "external_message_id": str(message.get("id") or message.get("message_id") or ""),
            "sender_key": resolved["sender_key"],
            "sender": {
                "email": sender,
                "contact_id": resolved.get("contact_id") or "",
                "sender_class": resolved["sender_class"],
            },
            "recipients": message.get("to") or [],
            "subject": str(message.get("subject") or ""),
            "normalized_text": text,
            "normalized_payload": {
                "subject": str(message.get("subject") or ""),
                "from": sender,
                "to": message.get("to") or [],
                "body_text": text,
            },
            "classification": classification,
            "suggestion_channel": self._suggestion_channel(classification),
            "memory_scope": self._memory_scope(identity_id, resolved, classification),
            "occurred_at": str(message.get("date") or message.get("occurred_at") or self._now()),
        }
        return event

    def normalize_whatsapp(self, *, identity_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        sender = str(payload.get("from") or payload.get("sender") or "")
        resolved = self.resolver.classify_sender(sender)
        classification = self._message_classification(str(resolved["sender_class"]))
        text = str(payload.get("text") or payload.get("body") or payload.get("message") or "")
        event = {
            "event_id": "assistant-inbox-" + str(uuid4()),
            "source_type": "assistant_whatsapp",
            "source_account_id": identity_id,
            "event_type": "assistant_whatsapp_message_received",
            "identity_id": identity_id,
            "conversation_id": "whatsapp:" + str(resolved["sender_key"]),
            "external_message_id": str(payload.get("wamid") or payload.get("id") or payload.get("message_id") or ""),
            "sender_key": resolved["sender_key"],
            "sender": {
                "phone_hash": resolved["sender_key"],
                "contact_id": resolved.get("contact_id") or "",
                "sender_class": resolved["sender_class"],
            },
            "recipient_identity_id": identity_id,
            "normalized_text": text,
            "normalized_payload": {
                "from": sender,
                "body_text": text,
                "raw_type": str(payload.get("type") or "text"),
            },
            "classification": classification,
            "suggestion_channel": self._suggestion_channel(classification),
            "memory_scope": self._memory_scope(identity_id, resolved, classification),
            "occurred_at": str(payload.get("timestamp") or payload.get("occurred_at") or self._now()),
        }
        return event

    def normalize_sms(self, *, identity_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        sender = str(payload.get("from") or payload.get("sender") or "")
        resolved = self.resolver.classify_sender(sender)
        classification = self._message_classification(str(resolved["sender_class"]))
        text = str(payload.get("body") or payload.get("text") or payload.get("message") or "")
        event = {
            "event_id": "assistant-inbox-" + str(uuid4()),
            "source_type": "assistant_phone",
            "source_account_id": identity_id,
            "event_type": "assistant_sms_received",
            "identity_id": identity_id,
            "conversation_id": "sms:" + str(resolved["sender_key"]),
            "external_message_id": str(payload.get("provider_message_id") or payload.get("message_id") or payload.get("id") or ""),
            "sender_key": resolved["sender_key"],
            "sender": {
                "phone_hash": resolved["sender_key"],
                "contact_id": resolved.get("contact_id") or "",
                "sender_class": resolved["sender_class"],
            },
            "recipient_identity_id": identity_id,
            "normalized_text": text,
            "normalized_payload": {
                "from": sender,
                "to": str(payload.get("to") or payload.get("recipient") or ""),
                "body_text": text,
                "raw_type": "sms",
            },
            "classification": classification,
            "suggestion_channel": self._suggestion_channel(classification),
            "memory_scope": self._memory_scope(identity_id, resolved, classification),
            "occurred_at": str(payload.get("timestamp") or payload.get("occurred_at") or self._now()),
        }
        return event

    def normalize_phone_call(self, *, identity_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        sender = str(payload.get("from") or payload.get("caller") or "")
        resolved = self.resolver.classify_sender(sender)
        direction = str(payload.get("direction") or "inbound")
        status = str(payload.get("status") or "received")
        event_type = "assistant_inbound_call_received" if direction == "inbound" else "assistant_call_status"
        event = {
            "event_id": "assistant-inbox-" + str(uuid4()),
            "source_type": "assistant_phone",
            "source_account_id": identity_id,
            "event_type": event_type,
            "identity_id": identity_id,
            "conversation_id": "phone:" + str(resolved["sender_key"]),
            "external_message_id": str(payload.get("provider_call_id") or payload.get("call_id") or payload.get("id") or ""),
            "sender_key": resolved["sender_key"],
            "sender": {
                "phone_hash": resolved["sender_key"],
                "contact_id": resolved.get("contact_id") or "",
                "sender_class": resolved["sender_class"],
            },
            "recipient_identity_id": identity_id,
            "normalized_text": "",
            "normalized_payload": {
                "from": sender,
                "to": str(payload.get("to") or payload.get("recipient") or ""),
                "call_direction": direction,
                "status": status,
                "raw_type": "phone_call",
            },
            "classification": "provider_status",
            "suggestion_channel": "assistant_channel_provider_status",
            "memory_scope": self._memory_scope(identity_id, resolved, "provider_status"),
            "occurred_at": str(payload.get("timestamp") or payload.get("occurred_at") or self._now()),
        }
        return event

    def normalize_phone_duplex_turn(self, *, identity_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        sender = str(payload.get("from") or payload.get("caller") or "")
        resolved = self.resolver.classify_sender(sender)
        transcript = str(payload.get("transcript") or payload.get("text") or "").strip()
        provider_call_id = str(payload.get("provider_call_id") or payload.get("call_id") or payload.get("id") or "")
        conversation_id = "phone-call:" + provider_call_id if provider_call_id else "phone:" + str(resolved["sender_key"])
        classification = self._message_classification(str(resolved["sender_class"]))
        event = {
            "event_id": "assistant-inbox-" + str(uuid4()),
            "source_type": "assistant_phone",
            "source_account_id": identity_id,
            "event_type": "assistant_duplex_call_turn",
            "identity_id": identity_id,
            "conversation_id": conversation_id,
            "external_message_id": provider_call_id,
            "sender_key": resolved["sender_key"],
            "sender": {
                "phone_hash": resolved["sender_key"],
                "contact_id": resolved.get("contact_id") or "",
                "sender_class": resolved["sender_class"],
            },
            "recipient_identity_id": identity_id,
            "normalized_text": transcript,
            "normalized_payload": {
                "from": sender,
                "to": str(payload.get("to") or payload.get("recipient") or ""),
                "provider_call_id": provider_call_id,
                "turn_index": payload.get("turn_index"),
                "body_text": transcript,
                "raw_type": "phone_duplex_turn",
            },
            "classification": classification,
            "suggestion_channel": self._suggestion_channel(classification),
            "memory_scope": self._memory_scope(identity_id, resolved, classification),
            "occurred_at": str(payload.get("timestamp") or payload.get("occurred_at") or self._now()),
        }
        return event

    def _message_classification(self, sender_class: str) -> str:
        if sender_class == "user":
            return "user_direct_command"
        if sender_class == "known_contact":
            return "external_contact_message"
        return "unknown_sender"

    def _suggestion_channel(self, classification: str) -> str:
        if classification == "external_contact_message":
            return "assistant_channel_external_contact"
        if classification == "user_direct_command":
            return "assistant_channel_user_command"
        return "assistant_channel_unknown_sender"

    def _memory_scope(self, identity_id: str, resolved: dict[str, Any], classification: str) -> dict[str, Any]:
        visibility_scope = "low_trust_assistant_inbox" if classification == "unknown_sender" else "assistant_identity_thread"
        return {
            "assistant_identity_id": identity_id,
            "visibility_scope": visibility_scope,
            "counterparty_scope": resolved.get("contact_id") or str(resolved.get("sender_key") or ""),
            "scope_policy": "contact_scoped" if classification == "external_contact_message" else "thread_scoped",
        }

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
