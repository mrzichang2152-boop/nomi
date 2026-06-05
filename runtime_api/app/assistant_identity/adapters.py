from __future__ import annotations

from typing import Optional, Protocol


class AssistantGmailAdapter(Protocol):
    def send_message(
        self,
        *,
        sender: str,
        recipient: str,
        subject: str,
        body_text: str,
        thread_id: Optional[str] = None,
    ) -> dict[str, object]:
        """Send a confirmed Nomi-owned Gmail message through a provider adapter."""


class AssistantWhatsAppAdapter(Protocol):
    def send_text(
        self,
        *,
        phone_number_id: str,
        to: str,
        body_text: str,
    ) -> dict[str, object]:
        """Send a confirmed Nomi-owned WhatsApp text through a provider adapter."""


class AssistantSmsAdapter(Protocol):
    def send_sms(
        self,
        *,
        from_number: str,
        to_number: str,
        body_text: str,
    ) -> dict[str, object]:
        """Send a confirmed Nomi-owned SMS through a provider adapter."""


class AssistantPhoneCallAdapter(Protocol):
    def create_playback_call(
        self,
        *,
        from_number: str,
        to_number: str,
        script_text: str,
        audio_url: Optional[str] = None,
        voice: str = "default",
    ) -> dict[str, object]:
        """Place a confirmed one-way playback call through a provider adapter."""
