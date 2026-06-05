from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4


class PhonePlaybackScriptValidator:
    DUPLEX_HINTS = (
        "回答我",
        "跟我说",
        "问一下",
        "聊一下",
        "实时",
        "对话",
        "conversation",
        "answer me",
    )

    def validate(self, script_text: str) -> dict[str, object]:
        text = str(script_text or "").strip()
        if not text:
            return {"allowed": False, "reason": "电话播放内容不能为空。"}
        if any(hint in text for hint in self.DUPLEX_HINTS):
            return {"allowed": False, "reason": "V1 电话只支持单向播放，不能要求对方实时回答。"}
        if "Nomi" not in text and "诺米" not in text:
            return {"allowed": False, "reason": "电话播放内容必须明确说明这是 Nomi 助理。"}
        return {"allowed": True, "reason": "one_way_playback_allowed"}


class PhoneCallInstructionBuilder:
    def estimate_duration_seconds(self, script_text: str) -> int:
        text = str(script_text or "")
        # Conservative Mandarin playback estimate: roughly 4 chars/sec.
        return max(3, int(len(text) / 4) + 1)

    def build_tts_instruction(self, *, script_text: str, voice: str = "default") -> dict[str, object]:
        validation = PhonePlaybackScriptValidator().validate(script_text)
        if not validation["allowed"]:
            raise ValueError(str(validation["reason"]))
        return {
            "mode": "tts_playback",
            "voice": voice or "default",
            "script_text": script_text,
            "estimated_duration_seconds": self.estimate_duration_seconds(script_text),
            "v1_one_way_playback": True,
        }


@dataclass
class FakeAssistantSmsAdapter:
    sent_messages: list[dict[str, object]] = field(default_factory=list)

    def send_sms(self, *, from_number: str, to_number: str, body_text: str) -> dict[str, object]:
        result = {
            "status": "sent",
            "provider": "fake-phone",
            "provider_message_id": "fake-sms-" + str(uuid4()),
            "from_number": from_number,
            "to_number": to_number,
            "body_text": body_text,
        }
        self.sent_messages.append(result)
        return result


@dataclass
class FakeAssistantPhoneCallAdapter:
    calls: list[dict[str, object]] = field(default_factory=list)

    def create_playback_call(
        self,
        *,
        from_number: str,
        to_number: str,
        script_text: str,
        audio_url: Optional[str] = None,
        voice: str = "default",
    ) -> dict[str, object]:
        instruction = PhoneCallInstructionBuilder().build_tts_instruction(
            script_text=script_text,
            voice=voice,
        )
        result = {
            "status": "queued",
            "provider": "fake-phone",
            "provider_call_id": "fake-call-" + str(uuid4()),
            "from_number": from_number,
            "to_number": to_number,
            "script_text": script_text,
            "audio_url": audio_url or "",
            "playback_mode": "tts",
            "instruction": instruction,
        }
        self.calls.append(result)
        return result


class PhoneWebhookVerifier:
    def __init__(self, verify_token: str) -> None:
        self.verify_token = str(verify_token or "")

    def verify(self, token: str) -> None:
        if self.verify_token and token != self.verify_token:
            raise PermissionError("Assistant phone webhook token mismatch.")
