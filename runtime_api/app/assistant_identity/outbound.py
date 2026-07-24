from __future__ import annotations

import hashlib
import os
import secrets
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Callable

from app.assistant_identity.adapters import (
    AssistantGmailAdapter,
    AssistantDuplexPhoneCallAdapter,
    AssistantPhoneCallAdapter,
    AssistantSmsAdapter,
    AssistantWhatsAppAdapter,
)
from app.assistant_identity.gmail_adapter import GmailHttpAdapter
from app.assistant_identity.audit import AssistantIdentityAuditor
from app.assistant_identity.outbound_repository import (
    AssistantOutboundRepository,
    InMemoryAssistantOutboundRepository,
)
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
        repository: AssistantOutboundRepository | None = None,
        clock: Callable[[], datetime] | None = None,
        per_contact_daily_limit: int = 5,
        per_channel_daily_limit: int = 50,
        daily_limit: int = 100,
        near_duplicate_window_seconds: int = 86400,
        near_duplicate_similarity: float = 0.92,
        auditor: AssistantIdentityAuditor | None = None,
    ) -> None:
        self._repository = repository or InMemoryAssistantOutboundRepository()
        self._gmail_adapter = gmail_adapter
        self._whatsapp_adapter = whatsapp_adapter
        self._sms_adapter = sms_adapter
        self._phone_call_adapter = phone_call_adapter
        self._duplex_phone_call_adapter = duplex_phone_call_adapter
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._per_contact_daily_limit = max(1, int(per_contact_daily_limit))
        self._per_channel_daily_limit = max(1, int(per_channel_daily_limit))
        self._daily_limit = max(1, int(daily_limit))
        self._near_duplicate_window_seconds = max(1, int(near_duplicate_window_seconds))
        self._near_duplicate_similarity = min(1.0, max(0.0, float(near_duplicate_similarity)))
        self._auditor = auditor or AssistantIdentityAuditor()

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
        idempotency_key: str = "",
        task_id: str = "",
    ) -> dict:
        normalized_idempotency_key = str(idempotency_key or "").strip()
        if normalized_idempotency_key:
            existing = self._repository.get_draft_by_idempotency_key(
                normalized_idempotency_key
            )
            if existing is not None:
                return existing
        draft_id = str(uuid.uuid4())
        now = self._clock()
        now_iso = now.isoformat()
        draft = {
            "draft_id": draft_id,
            "identity_id": identity_id,
            "channel": channel,
            "recipient": recipient,
            "subject": subject,
            "body_text": body_text,
            "body_hash": hashlib.sha256(body_text.encode("utf-8")).hexdigest(),
            "normalized_body_hash": hashlib.sha256(
                self._normalize_body(body_text).encode("utf-8")
            ).hexdigest(),
            "status": "draft",
            "revision": 1,
            "confirmation_required": True,
            "send_called": False,
            "call_called": False,
            "source_evidence_ids": list(source_evidence_ids),
            "risk_notes": list(risk_notes or []),
            "idempotency_key": normalized_idempotency_key,
            "task_id": str(task_id or "").strip(),
            "created_at": now_iso,
            "updated_at": now_iso,
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
        violation = self._policy_violation(draft, now=now)
        if violation is not None:
            draft["status"] = "blocked"
            draft["confirmation_required"] = False
            draft["reason"] = violation["reason"]
            draft["policy_result"] = violation
            draft["confirmation_card"] = {
                **draft["confirmation_card"],
                "type": "assistant_outbound_blocked",
                "actions": ["edit", "cancel"],
                "policy_result": violation,
            }
        stored = self._repository.save_draft(draft)
        action = "outbound.draft_blocked" if stored["status"] == "blocked" else "outbound.draft_created"
        audit = self._audit(
            action,
            stored,
            actor="system",
            policy_result=str(stored.get("reason") or "passed"),
            payload={
                "task_id": stored.get("task_id", ""),
                "idempotency_key": stored.get("idempotency_key", ""),
                "policy_result": stored.get("policy_result") or {"status": "passed"},
            },
        )
        stored["audit_trace_id"] = audit["trace_id"]
        return stored

    def cancel_draft(self, draft_id: str) -> dict:
        draft = self.get_draft(draft_id)
        current_status = str(draft.get("status") or "")
        if current_status == "cancelled":
            draft["send_called"] = False
            draft["confirmation_required"] = False
            return draft
        if current_status not in {"draft", "blocked"}:
            raise PermissionError(
                f"Draft status '{current_status}' cannot transition to cancelled."
            )
        expected_revision = int(draft.get("revision") or 1)
        draft["status"] = "cancelled"
        draft["send_called"] = False
        draft["confirmation_required"] = False
        draft["updated_at"] = self._clock().isoformat()
        stored = self._repository.transition_draft(
            draft,
            expected_statuses={current_status},
            expected_revision=expected_revision,
        )
        if stored is None:
            raise PermissionError("Draft state changed before cancellation.")
        self._invalidate_confirmations(draft_id)
        audit = self._audit("outbound.draft_cancelled", stored, actor="local_owner")
        stored["audit_trace_id"] = audit["trace_id"]
        return stored

    def get_draft(self, draft_id: str) -> dict:
        draft = self._repository.get_draft(draft_id)
        if draft is None:
            raise KeyError(draft_id)
        return draft

    def list_drafts(self, *, status: str = "", limit: int = 50) -> list[dict]:
        drafts = self._repository.list_drafts_since(datetime(1970, 1, 1, tzinfo=timezone.utc))
        normalized_status = str(status or "").strip().lower()
        if normalized_status:
            drafts = [
                draft
                for draft in drafts
                if str(draft.get("status") or "").strip().lower() == normalized_status
            ]
        drafts.sort(
            key=lambda draft: str(draft.get("updated_at") or draft.get("created_at") or ""),
            reverse=True,
        )
        safe_items = []
        for draft in drafts[: max(1, min(200, int(limit)))]:
            safe_items.append(
                {
                    key: value
                    for key, value in draft.items()
                    if "confirmation_token" not in str(key).lower()
                }
            )
        return safe_items

    def list_messages(self, *, limit: int = 50) -> list[dict]:
        history_statuses = {
            "sent",
            "delivered",
            "read",
            "failed",
            "rejected",
            "delivery_unknown",
            "call_queued",
            "queued",
            "blocked",
        }
        drafts = self.list_drafts(limit=200)
        return [
            draft
            for draft in drafts
            if str(draft.get("status") or "").strip().lower() in history_statuses
        ][: max(1, min(200, int(limit)))]

    def reconcile_stale_attempts(self) -> list[str]:
        """Move expired in-flight attempts to a reviewable terminal state.

        A process crash can happen after the provider accepted a request but before
        Nomi persisted the response. Retrying that request would risk a duplicate
        side effect, so recovery deliberately requires provider-side verification.
        """
        now = self._clock()
        recovered: list[str] = []
        drafts = self._repository.list_drafts_since(
            datetime(1970, 1, 1, tzinfo=timezone.utc)
        )
        for draft in drafts:
            if str(draft.get("status") or "").strip().lower() != "sending":
                continue
            lease_expires_at = self._parse_timestamp(draft.get("send_lease_expires_at"))
            if lease_expires_at is None:
                updated_at = self._parse_timestamp(
                    draft.get("updated_at") or draft.get("created_at")
                )
                lease_expires_at = (
                    updated_at + timedelta(minutes=5) if updated_at is not None else now
                )
            if lease_expires_at > now:
                continue

            expected_revision = int(draft.get("revision") or 1)
            draft["status"] = "delivery_unknown"
            draft["confirmation_required"] = False
            draft["reason"] = "stale_sending_requires_provider_verification"
            draft["recovery_guidance"] = (
                "Verify the provider delivery history before creating a new draft; "
                "this attempt will not be retried automatically."
            )
            draft["updated_at"] = now.isoformat()
            stored = self._repository.transition_draft(
                draft,
                expected_statuses={"sending"},
                expected_revision=expected_revision,
            )
            if stored is None:
                continue
            recovered.append(str(stored.get("draft_id") or ""))
            self._audit(
                "outbound.send_recovery_required",
                stored,
                actor="system",
                policy_result=str(stored["reason"]),
                payload={
                    "send_attempt_id": stored.get("send_attempt_id", ""),
                    "recovery_guidance": stored["recovery_guidance"],
                },
            )
        return recovered

    def edit_draft(
        self,
        draft_id: str,
        *,
        recipient: str | None = None,
        subject: str | None = None,
        body_text: str | None = None,
        risk_notes: list[str] | None = None,
    ) -> dict:
        draft = self.get_draft(draft_id)
        current_status = str(draft.get("status") or "")
        if current_status not in {"draft", "blocked"}:
            raise PermissionError(
                f"Draft status '{current_status}' cannot transition to an editable draft."
            )
        expected_revision = int(draft.get("revision") or 1)
        if recipient is not None:
            draft["recipient"] = str(recipient)
        if subject is not None:
            draft["subject"] = str(subject)
        if body_text is not None:
            draft["body_text"] = str(body_text)
            draft["body_hash"] = hashlib.sha256(str(body_text).encode("utf-8")).hexdigest()
            draft["normalized_body_hash"] = hashlib.sha256(
                self._normalize_body(str(body_text)).encode("utf-8")
            ).hexdigest()
        if risk_notes is not None:
            draft["risk_notes"] = list(risk_notes)
        for stale_key in (
            "reason",
            "policy_result",
            "provider_result",
            "provider_message_id",
            "provider_call_id",
            "sent_at",
            "called_at",
            "confirmation_actor",
            "send_attempt_id",
            "send_lease_expires_at",
        ):
            draft.pop(stale_key, None)
        draft["status"] = "draft"
        draft["confirmation_required"] = True
        draft["send_called"] = False
        draft["call_called"] = False
        draft["updated_at"] = self._clock().isoformat()
        draft["confirmation_card"] = self._confirmation_card(
            draft_id=draft_id,
            identity_id=draft["identity_id"],
            channel=draft["channel"],
            recipient=draft["recipient"],
            subject=draft["subject"],
            body_text=draft["body_text"],
            source_evidence_ids=list(draft["source_evidence_ids"]),
            risk_notes=list(draft["risk_notes"]),
        )
        violation = self._policy_violation(draft, now=self._clock())
        if violation is not None:
            draft["status"] = "blocked"
            draft["confirmation_required"] = False
            draft["reason"] = violation["reason"]
            draft["policy_result"] = violation
            draft["confirmation_card"] = {
                **draft["confirmation_card"],
                "type": "assistant_outbound_blocked",
                "actions": ["edit", "cancel"],
                "policy_result": violation,
            }
        stored = self._repository.transition_draft(
            draft,
            expected_statuses={current_status},
            expected_revision=expected_revision,
        )
        if stored is None:
            raise PermissionError("Draft state changed before the edit was saved.")
        self._invalidate_confirmations(draft_id)
        audit = self._audit("outbound.draft_edited", stored, actor="local_owner")
        stored["audit_trace_id"] = audit["trace_id"]
        return stored

    def issue_confirmation(
        self,
        draft_id: str,
        *,
        actor: str,
        ttl_seconds: int = 300,
    ) -> dict:
        draft = self.get_draft(draft_id)
        confirmation_actor = str(actor or "").strip()
        if not confirmation_actor:
            raise PermissionError("Confirmation actor is required.")
        if draft.get("status") != "draft":
            raise PermissionError("Only an active draft can be confirmed.")
        now = self._clock()
        token = secrets.token_urlsafe(32)
        record = {
            "confirmation_token": token,
            "draft_id": draft_id,
            "actor": confirmation_actor,
            "protected_hash": self._protected_hash(draft),
            "issued_at": now,
            "expires_at": now + timedelta(seconds=max(1, int(ttl_seconds))),
            "consumed_at": None,
            "invalidated_at": None,
        }
        self._repository.save_confirmation(record)
        audit = self._audit(
            "outbound.confirmation_issued",
            draft,
            actor=confirmation_actor,
            policy_result="confirmation_bound",
            payload={"expires_at": record["expires_at"].isoformat()},
        )
        return {
            "confirmation_token": token,
            "draft_id": draft_id,
            "actor": confirmation_actor,
            "expires_at": record["expires_at"].isoformat(),
            "audit_trace_id": audit["trace_id"],
        }

    def confirm_and_send(
        self,
        draft_id: str,
        confirmation_token: str,
        *,
        actor: str = "",
    ) -> dict:
        current = self.get_draft(draft_id)
        if str(current.get("status") or "") != "draft":
            return current
        try:
            record = self._validate_confirmation(draft_id, confirmation_token, actor=actor)
        except PermissionError:
            current = self.get_draft(draft_id)
            if str(current.get("status") or "") != "draft":
                return current
            raise
        draft = self.get_draft(draft_id)
        claimed_at = self._clock()
        expected_revision = int(draft.get("revision") or 1)
        draft.pop("confirmation_token", None)
        draft["confirmation_actor"] = str(actor)
        draft["send_called"] = True
        draft["sent_at"] = claimed_at.isoformat()
        draft["status"] = "sending"
        draft["confirmation_required"] = False
        draft["send_attempt_id"] = str(uuid.uuid4())
        draft["provider_idempotency_key"] = f"assistant-draft:{draft_id}"
        draft["send_lease_expires_at"] = (claimed_at + timedelta(minutes=5)).isoformat()
        draft["updated_at"] = claimed_at.isoformat()
        claimed = self._repository.claim_confirmation_and_transition_draft(
            confirmation_token,
            draft_id=draft_id,
            protected_hash=str(record.get("protected_hash") or ""),
            actor=str(actor or "").strip(),
            expected_revision=expected_revision,
            claimed_draft=draft,
            claimed_at=claimed_at,
        )
        if claimed is None:
            return self.get_draft(draft_id)
        draft = claimed
        sending_revision = int(draft.get("revision") or expected_revision + 1)
        try:
            provider_result = self._send_confirmed_draft(draft)
        except TimeoutError as exc:
            draft["status"] = "delivery_unknown"
            draft["reason"] = "provider_timeout_requires_verification"
            draft["provider_result"] = {
                "error_type": type(exc).__name__,
                "message": "Provider response timed out; delivery must be verified before retrying.",
            }
            draft["updated_at"] = self._clock().isoformat()
            audit = self._audit(
                "outbound.send_timeout",
                draft,
                actor=actor,
                policy_result=draft["reason"],
                payload={"status": draft["status"], "error_type": type(exc).__name__},
            )
            draft["audit_trace_id"] = audit["trace_id"]
            stored = self._repository.transition_draft(
                draft,
                expected_statuses={"sending"},
                expected_revision=sending_revision,
            )
            return stored or self.get_draft(draft_id)
        self._apply_message_provider_result(draft, provider_result)
        draft["updated_at"] = self._clock().isoformat()
        audit = self._audit(
            "outbound.send_completed",
            draft,
            actor=actor,
            policy_result="provider_result_recorded",
            payload={
                "status": draft.get("status", ""),
                "provider": draft.get("provider", ""),
                "provider_message_id": draft.get("provider_message_id", ""),
                "provider_result": draft.get("provider_result") or {},
            },
        )
        draft["audit_trace_id"] = audit["trace_id"]
        stored = self._repository.transition_draft(
            draft,
            expected_statuses={"sending"},
            expected_revision=sending_revision,
        )
        return stored or self.get_draft(draft_id)

    def confirm_and_call(
        self,
        draft_id: str,
        confirmation_token: str,
        *,
        actor: str = "",
    ) -> dict:
        current = self.get_draft(draft_id)
        if str(current.get("status") or "") != "draft":
            return current
        try:
            record = self._validate_confirmation(draft_id, confirmation_token, actor=actor)
        except PermissionError:
            current = self.get_draft(draft_id)
            if str(current.get("status") or "") != "draft":
                return current
            raise
        draft = self.get_draft(draft_id)
        claimed_at = self._clock()
        if draft["channel"] not in {"phone_call", "phone_duplex_call"}:
            raise ValueError("Draft channel is not phone_call.")
        expected_revision = int(draft.get("revision") or 1)
        draft.pop("confirmation_token", None)
        draft["confirmation_actor"] = str(actor)
        draft["call_called"] = True
        draft["called_at"] = claimed_at.isoformat()
        draft["status"] = "sending"
        draft["confirmation_required"] = False
        draft["send_attempt_id"] = str(uuid.uuid4())
        draft["provider_idempotency_key"] = f"assistant-draft:{draft_id}"
        draft["send_lease_expires_at"] = (claimed_at + timedelta(minutes=5)).isoformat()
        draft["updated_at"] = claimed_at.isoformat()
        claimed = self._repository.claim_confirmation_and_transition_draft(
            confirmation_token,
            draft_id=draft_id,
            protected_hash=str(record.get("protected_hash") or ""),
            actor=str(actor or "").strip(),
            expected_revision=expected_revision,
            claimed_draft=draft,
            claimed_at=claimed_at,
        )
        if claimed is None:
            return self.get_draft(draft_id)
        draft = claimed
        sending_revision = int(draft.get("revision") or expected_revision + 1)
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
        draft["updated_at"] = self._clock().isoformat()
        audit = self._audit(
            "outbound.call_completed",
            draft,
            actor=actor,
            policy_result="provider_result_recorded",
            payload={
                "status": draft.get("status", ""),
                "provider": draft.get("provider", ""),
                "provider_call_id": draft.get("provider_call_id", ""),
                "provider_result": draft.get("provider_result") or {},
            },
        )
        draft["audit_trace_id"] = audit["trace_id"]
        stored = self._repository.transition_draft(
            draft,
            expected_statuses={"sending"},
            expected_revision=sending_revision,
        )
        return stored or self.get_draft(draft_id)

    def _protected_hash(self, draft: dict) -> str:
        protected = "\x1f".join(
            str(draft.get(key) or "")
            for key in (
                "draft_id",
                "revision",
                "identity_id",
                "channel",
                "recipient",
                "subject",
                "body_hash",
            )
        )
        return hashlib.sha256(protected.encode("utf-8")).hexdigest()

    def record_delivery_receipt(
        self,
        *,
        identity_id: str,
        provider_message_id: str,
        status: str,
        receipt_payload: dict | None = None,
        occurred_at: datetime | None = None,
    ) -> dict:
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in {"delivered", "read", "failed", "rejected"}:
            raise ValueError("unsupported_delivery_receipt_status")
        receipt = self._repository.record_delivery_receipt(
            identity_id=str(identity_id),
            provider_message_id=str(provider_message_id),
            status=normalized_status,
            receipt_payload=dict(receipt_payload or {}),
            occurred_at=occurred_at or self._clock(),
        )
        audit = self._auditor.record(
            "outbound.delivery_receipt",
            actor="provider",
            identity_id=str(identity_id),
            draft_id=str(receipt.get("draft_id") or ""),
            status=normalized_status,
            policy_result="provider_receipt_recorded",
            payload={
                "provider_message_id": provider_message_id,
                "status": normalized_status,
                "receipt_payload": dict(receipt_payload or {}),
            },
        )
        receipt["audit_trace_id"] = audit["trace_id"]
        return receipt

    def _audit(
        self,
        action: str,
        draft: dict,
        *,
        actor: str,
        policy_result: str = "",
        payload: dict | None = None,
    ) -> dict:
        return self._auditor.record(
            action,
            actor=actor,
            identity_id=str(draft.get("identity_id") or ""),
            draft_id=str(draft.get("draft_id") or ""),
            status=str(draft.get("status") or ""),
            policy_result=policy_result,
            payload=payload,
        )

    def _invalidate_confirmations(self, draft_id: str) -> None:
        self._repository.invalidate_confirmations(
            draft_id,
            invalidated_at=self._clock(),
        )

    def _validate_confirmation(
        self,
        draft_id: str,
        confirmation_token: str,
        *,
        actor: str,
    ) -> dict:
        token = str(confirmation_token or "").strip()
        if not token:
            raise PermissionError("Explicit confirmation is required before sending.")
        record = self._repository.get_confirmation(token)
        if record is None or record.get("draft_id") != draft_id:
            raise PermissionError("Confirmation is invalid.")
        if str(record.get("actor") or "") != str(actor or "").strip():
            raise PermissionError("Confirmation actor does not match.")
        if record.get("invalidated_at") is not None:
            raise PermissionError("Confirmation is invalid because the draft changed.")
        if self._clock() > record["expires_at"]:
            raise PermissionError("Confirmation has expired.")
        draft = self.get_draft(draft_id)
        if record.get("protected_hash") != self._protected_hash(draft):
            raise PermissionError("Confirmation is invalid because the draft changed.")
        return record

    @staticmethod
    def _normalize_body(body_text: str) -> str:
        normalized = unicodedata.normalize("NFKC", str(body_text or "")).casefold()
        return "".join(character for character in normalized if character.isalnum())

    @staticmethod
    def _parse_timestamp(value: object) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _policy_violation(self, draft: dict, *, now: datetime) -> dict | None:
        duplicate_since = now - timedelta(seconds=self._near_duplicate_window_seconds)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        recent = self._repository.list_drafts_since(min(duplicate_since, start_of_day))
        normalized_body = self._normalize_body(draft["body_text"])
        active_statuses = {"draft", "sending", "sent", "call_queued", "delivery_unknown"}
        for existing in recent:
            if str(existing.get("draft_id") or "") == str(draft.get("draft_id") or ""):
                continue
            if existing.get("status") not in active_statuses:
                continue
            if str(existing.get("channel") or "") != str(draft["channel"]):
                continue
            if str(existing.get("recipient") or "").casefold() != str(draft["recipient"]).casefold():
                continue
            timestamp = datetime.fromisoformat(
                str(existing.get("updated_at") or existing.get("created_at")).replace("Z", "+00:00")
            )
            if timestamp < duplicate_since:
                continue
            existing_body = self._normalize_body(str(existing.get("body_text") or ""))
            similarity = SequenceMatcher(None, existing_body, normalized_body).ratio()
            if similarity >= self._near_duplicate_similarity:
                return {
                    "status": "blocked",
                    "reason": "near_duplicate_outbound",
                    "matched_draft_id": existing.get("draft_id"),
                    "similarity": round(similarity, 4),
                    "window_seconds": self._near_duplicate_window_seconds,
                    "guidance": "Edit the recipient or message content before requesting confirmation.",
                }

        sent_today = [
            item
            for item in recent
            if item.get("status") in {"sent", "call_queued"}
            and datetime.fromisoformat(
                str(item.get("updated_at") or item.get("created_at")).replace("Z", "+00:00")
            )
            >= start_of_day
        ]
        contact_count = sum(
            1
            for item in sent_today
            if str(item.get("channel") or "") == str(draft["channel"])
            and str(item.get("recipient") or "").casefold() == str(draft["recipient"]).casefold()
        )
        if contact_count >= self._per_contact_daily_limit:
            return self._quota_violation(
                "per_contact_daily_quota_exceeded",
                contact_count,
                self._per_contact_daily_limit,
            )
        channel_count = sum(
            1 for item in sent_today if str(item.get("channel") or "") == str(draft["channel"])
        )
        if channel_count >= self._per_channel_daily_limit:
            return self._quota_violation(
                "per_channel_daily_quota_exceeded",
                channel_count,
                self._per_channel_daily_limit,
            )
        if len(sent_today) >= self._daily_limit:
            return self._quota_violation(
                "assistant_daily_quota_exceeded",
                len(sent_today),
                self._daily_limit,
            )
        return None

    @staticmethod
    def _quota_violation(reason: str, current: int, limit: int) -> dict:
        return {
            "status": "blocked",
            "reason": reason,
            "current": current,
            "limit": limit,
            "guidance": "Wait for the next quota window or explicitly raise the local policy limit.",
        }

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
