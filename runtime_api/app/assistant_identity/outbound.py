from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone

from app.assistant_identity.adapters import (
    AssistantGmailAdapter,
    AssistantDuplexPhoneCallAdapter,
    AssistantPhoneCallAdapter,
    AssistantSmsAdapter,
    AssistantWhatsAppAdapter,
)
from app.assistant_identity.gmail_adapter import GmailHttpAdapter
from app.assistant_identity.phone_adapter import PhoneCallInstructionBuilder
from app.assistant_identity.phone_adapter import HttpAssistantPhoneProvider
from app.assistant_identity.whatsapp_adapter import WhatsAppCloudHttpAdapter


class OutboundMessagePipeline:
    def __init__(
        self,
        *,
        gmail_adapter: AssistantGmailAdapter | None = None,
        whatsapp_adapter: AssistantWhatsAppAdapter | None = None,
        sms_adapter: AssistantSmsAdapter | None = None,
        phone_call_adapter: AssistantPhoneCallAdapter | None = None,
        duplex_phone_call_adapter: AssistantDuplexPhoneCallAdapter | None = None,
    ) -> None:
        self._drafts: dict[str, dict] = {}
        self._gmail_adapter = gmail_adapter
        self._whatsapp_adapter = whatsapp_adapter
        self._sms_adapter = sms_adapter
        self._phone_call_adapter = phone_call_adapter
        self._duplex_phone_call_adapter = duplex_phone_call_adapter

    def _confirmation_card(
        self,
        *,
        draft_id: str,
        identity_id: str,
        channel: str,
        recipient: str,
        subject: str,
        body_text: str,
        source_evidence_ids: list[str],
        risk_notes: list[str],
    ) -> dict:
        base = {
            "draft_id": draft_id,
            "identity_id": identity_id,
            "channel": channel,
            "recipient": recipient,
            "subject": subject,
            "body_preview": body_text,
            "source_evidence_ids": list(source_evidence_ids),
            "risk_notes": list(risk_notes),
        }
        if channel == "sms":
            return {
                **base,
                "type": "assistant_sms_confirmation",
                "actions": ["send", "edit", "cancel"],
            }
        if channel == "phone_call":
            return {
                **base,
                "type": "assistant_call_playback_confirmation",
                "script_preview": body_text,
                "estimated_duration_seconds": PhoneCallInstructionBuilder().estimate_duration_seconds(body_text),
                "v1_limitation": "电话只会播放这段语音，不会实时对话。",
                "actions": ["call", "edit", "cancel"],
            }
        if channel == "phone_duplex_call":
            return {
                **base,
                "type": "assistant_call_duplex_confirmation",
                "opening_script_preview": body_text,
                "duplex_mode": "turn_based_voice",
                "actions": ["call", "edit", "cancel"],
            }
        return {
            **base,
            "type": "assistant_message_confirmation",
            "actions": ["send", "edit", "cancel"],
        }

    def prepare_draft(
        self,
        *,
        identity_id: str,
        channel: str,
        recipient: str,
        subject: str,
        body_text: str,
        source_evidence_ids: list[str],
        risk_notes: list[str] | None = None,
    ) -> dict:
        draft_id = str(uuid.uuid4())
        draft = {
            "draft_id": draft_id,
            "identity_id": identity_id,
            "channel": channel,
            "recipient": recipient,
            "subject": subject,
            "body_text": body_text,
            "body_hash": hashlib.sha256(body_text.encode("utf-8")).hexdigest(),
            "status": "draft",
            "confirmation_required": True,
            "send_called": False,
            "call_called": False,
            "source_evidence_ids": list(source_evidence_ids),
            "risk_notes": list(risk_notes or []),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "confirmation_card": self._confirmation_card(
                draft_id=draft_id,
                identity_id=identity_id,
                channel=channel,
                recipient=recipient,
                subject=subject,
                body_text=body_text,
                source_evidence_ids=source_evidence_ids,
                risk_notes=list(risk_notes or []),
            ),
        }
        self._drafts[draft_id] = draft
        return draft

    def cancel_draft(self, draft_id: str) -> dict:
        draft = self._drafts[draft_id]
        draft["status"] = "cancelled"
        draft["send_called"] = False
        return draft

    def get_draft(self, draft_id: str) -> dict:
        return self._drafts[draft_id]

    def confirm_and_send(self, draft_id: str, confirmation_token: str) -> dict:
        if not str(confirmation_token or "").strip():
            raise PermissionError("Explicit confirmation is required before sending.")
        draft = self._drafts[draft_id]
        draft["confirmation_token"] = str(confirmation_token)
        draft["send_called"] = True
        draft["sent_at"] = datetime.now(timezone.utc).isoformat()
        provider_result = self._send_confirmed_draft(draft)
        self._apply_message_provider_result(draft, provider_result)
        return draft

    def confirm_and_call(self, draft_id: str, confirmation_token: str) -> dict:
        if not str(confirmation_token or "").strip():
            raise PermissionError("Explicit confirmation is required before calling.")
        draft = self._drafts[draft_id]
        if draft["channel"] not in {"phone_call", "phone_duplex_call"}:
            raise ValueError("Draft channel is not phone_call.")
        draft["confirmation_token"] = str(confirmation_token)
        draft["call_called"] = True
        draft["called_at"] = datetime.now(timezone.utc).isoformat()
        if draft["channel"] == "phone_duplex_call":
            provider_result = self._duplex_phone_call().create_duplex_call(
                from_number=os.getenv("ASSISTANT_PHONE_NUMBER", ""),
                to_number=draft["recipient"],
                opening_script=draft["body_text"],
            )
        else:
            provider_result = self._phone_call().create_playback_call(
                from_number=os.getenv("ASSISTANT_PHONE_NUMBER", ""),
                to_number=draft["recipient"],
                script_text=draft["body_text"],
            )
        self._apply_call_provider_result(draft, provider_result)
        return draft

    def _gmail(self) -> AssistantGmailAdapter:
        return self._gmail_adapter or GmailHttpAdapter.from_env()

    def _whatsapp(self) -> AssistantWhatsAppAdapter:
        return self._whatsapp_adapter or WhatsAppCloudHttpAdapter.from_env()

    def _sms(self) -> AssistantSmsAdapter:
        return self._sms_adapter or HttpAssistantPhoneProvider.from_env()

    def _phone_call(self) -> AssistantPhoneCallAdapter:
        return self._phone_call_adapter or HttpAssistantPhoneProvider.from_env()

    def _duplex_phone_call(self) -> AssistantDuplexPhoneCallAdapter:
        return self._duplex_phone_call_adapter or HttpAssistantPhoneProvider.from_env()

    def _send_confirmed_draft(self, draft: dict) -> dict[str, object]:
        channel = str(draft.get("channel") or "").strip().lower()
        if channel == "gmail":
            return self._gmail().send_message(
                sender=os.getenv("ASSISTANT_GMAIL_ADDRESS", ""),
                recipient=draft["recipient"],
                subject=draft.get("subject", ""),
                body_text=draft["body_text"],
                thread_id=draft.get("thread_id", ""),
            )
        if channel == "whatsapp":
            return self._whatsapp().send_text(
                phone_number_id=os.getenv("ASSISTANT_WHATSAPP_PHONE_NUMBER_ID", ""),
                to=draft["recipient"],
                body_text=draft["body_text"],
            )
        if channel == "sms":
            return self._sms().send_sms(
                from_number=os.getenv("ASSISTANT_PHONE_NUMBER", ""),
                to_number=draft["recipient"],
                body_text=draft["body_text"],
            )
        return {
            "status": "blocked",
            "reason": "unsupported_channel",
            "provider": "assistant_outbound",
            "provider_result": {
                "status": "unsupported_channel",
                "channel": channel,
            },
        }

    def _apply_message_provider_result(self, draft: dict, result: dict[str, object]) -> None:
        status = str(result.get("status") or "")
        draft["status"] = status or "failed"
        self._copy_provider_result(draft, result)

    def _apply_call_provider_result(self, draft: dict, result: dict[str, object]) -> None:
        status = str(result.get("status") or "")
        if status == "queued":
            draft["status"] = "call_queued"
        else:
            draft["status"] = status or "failed"
        self._copy_provider_result(draft, result)

    def _copy_provider_result(self, draft: dict, result: dict[str, object]) -> None:
        for key in [
            "provider",
            "provider_message_id",
            "provider_call_id",
            "provider_result",
            "request",
            "reason",
            "misconfigured",
            "missing_env",
            "playback_mode",
            "duplex_mode",
            "instruction",
            "opening_instruction",
        ]:
            if key in result:
                draft[key] = result[key]
