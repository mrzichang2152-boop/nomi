from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.assistant_identity.contact_resolver import ContactResolver
from app.assistant_identity.inbox_gateway import AssistantInboxGateway
from app.assistant_identity.whatsapp_adapter import WhatsAppWebhookVerifier


router = APIRouter()


def build_default_assistant_inbox_gateway() -> AssistantInboxGateway:
    return AssistantInboxGateway(ContactResolver(user_keys=set(), known_contacts={}))


def normalized_assistant_event_to_private_payload(event: dict[str, Any]) -> dict[str, Any]:
    memory_scope = event.get("memory_scope") if isinstance(event.get("memory_scope"), dict) else {}
    normalized_payload = event.get("normalized_payload")
    raw_data = dict(normalized_payload) if isinstance(normalized_payload, dict) else {}
    raw_data.update(
        {
            "assistant_identity_id": event.get("identity_id") or event.get("source_account_id") or "",
            "classification": event.get("classification") or "",
            "visibility_scope": memory_scope.get("visibility_scope") or "",
            "conversation_id": event.get("conversation_id") or "",
            "external_message_id": event.get("external_message_id") or "",
            "counterparty_scope": memory_scope.get("counterparty_scope") or "",
            "normalized_text": event.get("normalized_text") or "",
        }
    )
    return {
        "source": event["source_type"],
        "event_type": event["event_type"],
        "raw_data": raw_data,
    }


@router.get("/api/assistant-inbox/whatsapp/webhook", response_class=PlainTextResponse)
def verify_whatsapp_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> PlainTextResponse:
    verifier = WhatsAppWebhookVerifier(os.getenv("ASSISTANT_WHATSAPP_VERIFY_TOKEN", ""))
    try:
        return PlainTextResponse(
            verifier.verify(mode=hub_mode, token=hub_verify_token, challenge=hub_challenge)
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
