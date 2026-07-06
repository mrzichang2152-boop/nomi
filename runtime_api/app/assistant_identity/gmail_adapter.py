from __future__ import annotations

import base64
import os
import uuid
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Optional

from app.assistant_identity.adapters import (
    HttpxProviderHttpClient,
    ProviderHttpClient,
    bearer_json_headers,
    blocked_misconfigured_result,
    first_body_value,
    http_success,
    join_url,
    provider_http_error_result,
    provider_response_result,
)


class GmailMimeBuilder:
    def build_raw_message(self, *, sender: str, recipient: str, subject: str, body_text: str) -> str:
        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body_text)
        return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


class FakeAssistantGmailAdapter:
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []

    def send_message(
        self,
        *,
        sender: str,
        recipient: str,
        subject: str,
        body_text: str,
        thread_id: str = "",
    ) -> dict:
        payload = {
            "sender": sender,
            "recipient": recipient,
            "subject": subject,
            "body_text": body_text,
            "thread_id": thread_id,
        }
        self.sent_messages.append(payload)
        return {
            "status": "sent",
            "provider": "fake_gmail",
            "provider_message_id": "fake-gmail-" + str(uuid.uuid4()),
            "payload": payload,
        }


@dataclass
class GmailHttpAdapter:
    address: str
    access_token: str
    api_base_url: str = "https://gmail.googleapis.com/gmail/v1"
    http_client: ProviderHttpClient = field(default_factory=HttpxProviderHttpClient)
    missing_env: list[str] = field(default_factory=list)
    timeout: float = 10.0

    provider = "gmail"

    @classmethod
    def from_env(cls, *, http_client: ProviderHttpClient | None = None) -> "GmailHttpAdapter":
        address = os.getenv("ASSISTANT_GMAIL_ADDRESS", "").strip()
        access_token = os.getenv("ASSISTANT_GMAIL_ACCESS_TOKEN", "").strip()
        missing_env: list[str] = []
        if not access_token:
            missing_env.append("ASSISTANT_GMAIL_ACCESS_TOKEN")
        if not address:
            missing_env.append("ASSISTANT_GMAIL_ADDRESS")
        return cls(
            address=address,
            access_token=access_token,
            api_base_url=os.getenv("ASSISTANT_GMAIL_API_BASE_URL", "https://gmail.googleapis.com/gmail/v1").strip(),
            http_client=http_client or HttpxProviderHttpClient(),
            missing_env=missing_env,
        )

    def send_message(
        self,
        *,
        sender: str,
        recipient: str,
        subject: str,
        body_text: str,
        thread_id: Optional[str] = None,
    ) -> dict[str, object]:
        if self.missing_env:
            return blocked_misconfigured_result(provider=self.provider, missing_env=self.missing_env)

        sender_address = str(sender or "").strip() or self.address
        payload: dict[str, object] = {
            "raw": GmailMimeBuilder().build_raw_message(
                sender=sender_address,
                recipient=recipient,
                subject=subject,
                body_text=body_text,
            )
        }
        if thread_id:
            payload["threadId"] = str(thread_id)

        url = join_url(self.api_base_url, f"users/{sender_address}/messages/send")
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
        provider_message_id = first_body_value(body, ["id", "message_id"])
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
