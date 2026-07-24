from __future__ import annotations

import base64
import hashlib
import os
import uuid
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any, Callable, Optional

from app.assistant_identity.composio_gmail import (
    ASSISTANT_GMAIL_COMPOSIO_USER_ID,
    ASSISTANT_GMAIL_PROVIDER,
    assistant_gmail_toolkit_version,
)

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


def _composio_result_dict(value: object) -> dict[str, Any]:
    if hasattr(value, "model_dump") and callable(value.model_dump):
        value = value.model_dump()
    elif hasattr(value, "dict") and callable(value.dict):
        value = value.dict()
    return value if isinstance(value, dict) else {}


@dataclass
class ComposioAssistantGmailAdapter:
    sdk: object
    connected_account_id: str
    address: str

    provider = ASSISTANT_GMAIL_PROVIDER

    def send_message(
        self,
        *,
        sender: str,
        recipient: str,
        subject: str,
        body_text: str,
        thread_id: Optional[str] = None,
    ) -> dict[str, object]:
        expected_sender = self.address.strip().lower()
        requested_sender = str(sender or "").strip().lower() or expected_sender
        if not expected_sender or requested_sender != expected_sender:
            return {
                "status": "blocked",
                "reason": "assistant_gmail_sender_mismatch",
                "provider": self.provider,
                "provider_result": {"successful": False},
            }
        if not self.connected_account_id.strip():
            return {
                "status": "blocked",
                "reason": "assistant_gmail_connected_account_missing",
                "provider": self.provider,
                "provider_result": {"successful": False},
            }

        normalized_thread_id = str(thread_id or "").strip()
        if normalized_thread_id:
            tool_slug = "GMAIL_REPLY_TO_THREAD"
            arguments = {
                "recipient_email": recipient,
                "message_body": body_text,
                "thread_id": normalized_thread_id,
            }
        else:
            tool_slug = "GMAIL_SEND_EMAIL"
            arguments = {
                "recipient_email": recipient,
                "subject": subject,
                "body": body_text,
            }
        try:
            raw_result = self.sdk.tools.execute(
                tool_slug,
                user_id=ASSISTANT_GMAIL_COMPOSIO_USER_ID,
                connected_account_id=self.connected_account_id,
                version=assistant_gmail_toolkit_version(),
                arguments=arguments,
            )
        except Exception as exc:
            return {
                "status": "delivery_unknown",
                "reason": "composio_gmail_delivery_requires_verification",
                "provider": self.provider,
                "provider_result": {
                    "successful": None,
                    "error_type": exc.__class__.__name__,
                },
            }
        result = _composio_result_dict(raw_result)
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        successful = bool(result.get("successful"))
        return {
            "status": "sent" if successful else "failed",
            "provider": self.provider,
            "provider_message_id": str(
                data.get("id") or data.get("message_id") or ""
            ),
            "provider_thread_id": str(
                data.get("threadId") or data.get("thread_id") or normalized_thread_id
            ),
            "provider_result": {"successful": successful},
            "request": {
                "tool_slug": tool_slug,
                "connected_account_id": self.connected_account_id,
                "recipient": recipient,
                "subject_present": bool(subject),
                "body_sha256": hashlib.sha256(body_text.encode("utf-8")).hexdigest(),
            },
        }


@dataclass
class RegistryBackedComposioAssistantGmailAdapter:
    registry: object
    sdk_factory: Callable[[], object]

    provider = ASSISTANT_GMAIL_PROVIDER

    def send_message(
        self,
        *,
        sender: str,
        recipient: str,
        subject: str,
        body_text: str,
        thread_id: Optional[str] = None,
    ) -> dict[str, object]:
        identity = self.registry.get("nomi_gmail_primary")
        if (
            identity is None
            or getattr(identity, "kind", "") != "assistant_gmail"
            or getattr(identity, "status", "") not in {"connected", "degraded"}
            or "send" not in list(getattr(identity, "capabilities", []) or [])
            or not str(getattr(identity, "address", "") or "").strip()
        ):
            return {
                "status": "blocked",
                "reason": "assistant_gmail_identity_not_verified",
                "provider": self.provider,
                "provider_result": {"successful": False},
            }
        metadata = dict(getattr(identity, "metadata", {}) or {})
        connection = dict(metadata.get("provider_connection") or {})
        connected_account_id = str(
            connection.get("connected_account_id") or ""
        ).strip()
        if (
            not connected_account_id
            or str(connection.get("composio_user_id") or "")
            != ASSISTANT_GMAIL_COMPOSIO_USER_ID
        ):
            return {
                "status": "blocked",
                "reason": "assistant_gmail_connected_account_missing",
                "provider": self.provider,
                "provider_result": {"successful": False},
            }
        try:
            sdk = self.sdk_factory()
        except Exception as exc:
            return {
                "status": "failed",
                "reason": "composio_gmail_sdk_unavailable",
                "provider": self.provider,
                "provider_result": {
                    "successful": False,
                    "error_type": exc.__class__.__name__,
                },
            }
        return ComposioAssistantGmailAdapter(
            sdk=sdk,
            connected_account_id=connected_account_id,
            address=str(identity.address),
        ).send_message(
            sender=sender,
            recipient=recipient,
            subject=subject,
            body_text=body_text,
            thread_id=thread_id,
        )


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
