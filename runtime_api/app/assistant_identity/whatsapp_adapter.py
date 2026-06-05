from __future__ import annotations

import uuid


class WhatsAppWebhookVerifier:
    def __init__(self, verify_token: str) -> None:
        self.verify_token = str(verify_token or "")

    def verify(self, *, mode: str, token: str, challenge: str) -> str:
        if mode != "subscribe":
            raise PermissionError("WhatsApp webhook mode mismatch.")
        if token != self.verify_token:
            raise PermissionError("WhatsApp webhook verify token mismatch.")
        return challenge


class FakeAssistantWhatsAppAdapter:
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []

    def send_text(self, *, phone_number_id: str, to: str, body_text: str) -> dict:
        payload = {"phone_number_id": phone_number_id, "to": to, "body_text": body_text}
        self.sent_messages.append(payload)
        return {
            "status": "sent",
            "provider": "fake_whatsapp",
            "provider_message_id": "fake-whatsapp-" + str(uuid.uuid4()),
            "payload": payload,
        }
