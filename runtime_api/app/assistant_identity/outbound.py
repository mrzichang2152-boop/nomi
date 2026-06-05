from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from app.assistant_identity.phone_adapter import PhoneCallInstructionBuilder


class OutboundMessagePipeline:
    def __init__(self) -> None:
        self._drafts: dict[str, dict] = {}

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
        draft["status"] = "sent"
        draft["confirmation_token"] = str(confirmation_token)
        draft["send_called"] = True
        draft["sent_at"] = datetime.now(timezone.utc).isoformat()
        return draft

    def confirm_and_call(self, draft_id: str, confirmation_token: str) -> dict:
        if not str(confirmation_token or "").strip():
            raise PermissionError("Explicit confirmation is required before calling.")
        draft = self._drafts[draft_id]
        if draft["channel"] != "phone_call":
            raise ValueError("Draft channel is not phone_call.")
        draft["status"] = "call_queued"
        draft["confirmation_token"] = str(confirmation_token)
        draft["call_called"] = True
        draft["provider_call_id"] = "local-call-" + str(uuid.uuid4())
        draft["called_at"] = datetime.now(timezone.utc).isoformat()
        return draft
