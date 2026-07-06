from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field

from app.assistant_identity.adapters import (
    HttpxProviderHttpClient,
    ProviderHttpClient,
    bearer_json_headers,
    blocked_misconfigured_result,
    http_success,
    join_url,
    provider_http_error_result,
    provider_response_result,
)


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


@dataclass
class WhatsAppCloudHttpAdapter:
    access_token: str
    phone_number_id: str
    api_base_url: str = "https://graph.facebook.com/v20.0"
    http_client: ProviderHttpClient = field(default_factory=HttpxProviderHttpClient)
    missing_env: list[str] = field(default_factory=list)
    timeout: float = 10.0

    provider = "whatsapp_cloud_api"

    @classmethod
    def from_env(cls, *, http_client: ProviderHttpClient | None = None) -> "WhatsAppCloudHttpAdapter":
        access_token = os.getenv("ASSISTANT_WHATSAPP_ACCESS_TOKEN", "").strip()
        phone_number_id = os.getenv("ASSISTANT_WHATSAPP_PHONE_NUMBER_ID", "").strip()
        missing_env: list[str] = []
        if not access_token:
            missing_env.append("ASSISTANT_WHATSAPP_ACCESS_TOKEN")
        if not phone_number_id:
            missing_env.append("ASSISTANT_WHATSAPP_PHONE_NUMBER_ID")
        return cls(
            access_token=access_token,
            phone_number_id=phone_number_id,
            api_base_url=os.getenv("ASSISTANT_WHATSAPP_API_BASE_URL", "https://graph.facebook.com/v20.0").strip(),
            http_client=http_client or HttpxProviderHttpClient(),
            missing_env=missing_env,
        )

    def send_text(self, *, phone_number_id: str, to: str, body_text: str) -> dict[str, object]:
        if self.missing_env:
            return blocked_misconfigured_result(provider=self.provider, missing_env=self.missing_env)

        provider_phone_number_id = str(phone_number_id or "").strip() or self.phone_number_id
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body_text},
        }
        url = join_url(self.api_base_url, f"{provider_phone_number_id}/messages")
        try:
            response = self.http_client.post(
                url,
                headers=bearer_json_headers(self.access_token),
                json=payload,
                timeout=self.timeout,
            )
        except Exception as exc:
            return provider_http_error_result(provider=self.provider, exc=exc)

        provider_result = provider_response_result(response)
        body = provider_result["body"]
        provider_message_id = ""
        if isinstance(body, dict):
            messages = body.get("messages")
            if isinstance(messages, list) and messages and isinstance(messages[0], dict):
                provider_message_id = str(messages[0].get("id") or "")
            provider_message_id = provider_message_id or str(body.get("id") or body.get("message_id") or "")
        status = "sent" if http_success(provider_result["status_code"]) else "failed"
        return {
            "status": status,
            "provider": self.provider,
            "provider_message_id": provider_message_id,
            "provider_result": provider_result,
            "request": {
                "method": "POST",
                "url": url,
                "json": payload,
            },
        }
