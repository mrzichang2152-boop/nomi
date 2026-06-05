from __future__ import annotations

import base64
import uuid
from email.message import EmailMessage


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
