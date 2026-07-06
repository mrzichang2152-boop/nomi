from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

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


class PhoneDuplexTurnHandler:
    def build_opening_instruction(self, *, opening_script: str, voice: str = "default") -> dict[str, object]:
        text = str(opening_script or "").strip()
        if not text:
            raise ValueError("双工电话开场白不能为空。")
        if "Nomi" not in text and "诺米" not in text:
            raise ValueError("双工电话开场白必须明确说明这是 Nomi 助理。")
        return {
            "mode": "tts_duplex_opening",
            "voice": voice or "default",
            "script_text": text,
            "v2_duplex_turn": True,
        }

    def build_reply_instruction(self, *, transcript: str, voice: str = "default") -> dict[str, object]:
        text = str(transcript or "").strip()
        if not text:
            script = "我是 Nomi，我没有听清楚。可以再说一遍吗？"
        elif any(marker in text for marker in ("再见", "没有了", "不用了", "拜拜")):
            script = "好的，我会把这次通话内容转达给张子长。再见。"
        elif any(marker in text for marker in ("告诉", "转达", "留言", "请让", "帮我")):
            script = "好的，我是 Nomi。我已经记录下来，会转达给张子长。还有其他要补充的吗？"
        else:
            brief = text[:60]
            script = f"我是 Nomi，我已记录：{brief}。我会转达给张子长，也可以继续补充。"
        return {
            "mode": "tts_reply",
            "voice": voice or "default",
            "script_text": script,
            "v2_duplex_turn": True,
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


@dataclass
class FakeAssistantDuplexPhoneCallAdapter:
    calls: list[dict[str, object]] = field(default_factory=list)

    def create_duplex_call(
        self,
        *,
        from_number: str,
        to_number: str,
        opening_script: str,
        media_stream_url: Optional[str] = None,
        voice: str = "default",
    ) -> dict[str, object]:
        opening_instruction = PhoneDuplexTurnHandler().build_opening_instruction(
            opening_script=opening_script,
            voice=voice,
        )
        result = {
            "status": "queued",
            "provider": "fake-phone",
            "provider_call_id": "fake-duplex-call-" + str(uuid4()),
            "from_number": from_number,
            "to_number": to_number,
            "duplex_mode": "turn_based_voice",
            "media_stream_url": media_stream_url or "",
            "opening_instruction": opening_instruction,
        }
        self.calls.append(result)
        return result


@dataclass
class HttpAssistantPhoneProvider:
    base_url: str
    api_key: str
    from_number: str
    provider_name: str = "http_phone"
    sms_path: str = "/sms"
    call_path: str = "/calls/playback"
    duplex_call_path: str = "/calls/duplex"
    duplex_webhook_url: str = ""
    http_client: ProviderHttpClient = field(default_factory=HttpxProviderHttpClient)
    missing_env: list[str] = field(default_factory=list)
    timeout: float = 10.0

    @classmethod
    def from_env(cls, *, http_client: ProviderHttpClient | None = None) -> "HttpAssistantPhoneProvider":
        base_url = os.getenv("ASSISTANT_PHONE_PROVIDER_BASE_URL", "").strip()
        api_key = os.getenv("ASSISTANT_PHONE_PROVIDER_API_KEY", "").strip()
        from_number = os.getenv("ASSISTANT_PHONE_NUMBER", "").strip()
        missing_env: list[str] = []
        if not from_number:
            missing_env.append("ASSISTANT_PHONE_NUMBER")
        if not api_key:
            missing_env.append("ASSISTANT_PHONE_PROVIDER_API_KEY")
        if not base_url:
            missing_env.append("ASSISTANT_PHONE_PROVIDER_BASE_URL")
        return cls(
            base_url=base_url,
            api_key=api_key,
            from_number=from_number,
            provider_name=os.getenv("ASSISTANT_PHONE_PROVIDER_NAME", "http_phone").strip() or "http_phone",
            sms_path=os.getenv("ASSISTANT_PHONE_SMS_PATH", "/sms").strip() or "/sms",
            call_path=os.getenv("ASSISTANT_PHONE_CALL_PATH", "/calls/playback").strip() or "/calls/playback",
            duplex_call_path=os.getenv("ASSISTANT_PHONE_DUPLEX_CALL_PATH", "/calls/duplex").strip() or "/calls/duplex",
            duplex_webhook_url=os.getenv("ASSISTANT_PHONE_DUPLEX_WEBHOOK_URL", "").strip(),
            http_client=http_client or HttpxProviderHttpClient(),
            missing_env=missing_env,
        )

    @property
    def provider(self) -> str:
        return self.provider_name

    def send_sms(self, *, from_number: str, to_number: str, body_text: str) -> dict[str, object]:
        if self.missing_env:
            return blocked_misconfigured_result(provider=self.provider, missing_env=self.missing_env)

        sender = str(from_number or "").strip() or self.from_number
        payload = {
            "from": sender,
            "to": to_number,
            "body": body_text,
        }
        url = join_url(self.base_url, self.sms_path)
        try:
            response = self.http_client.post(
                url,
                headers=bearer_json_headers(self.api_key),
                json=payload,
                timeout=self.timeout,
            )
        except Exception as exc:
            return provider_http_error_result(provider=self.provider, exc=exc)

        provider_result = provider_response_result(response)
        status = "sent" if http_success(provider_result["status_code"]) else "failed"
        return {
            "status": status,
            "provider": self.provider,
            "provider_message_id": first_body_value(provider_result["body"], ["message_id", "id", "sid"]),
            "provider_result": provider_result,
            "request": {
                "method": "POST",
                "url": url,
                "json": payload,
            },
        }

    def create_playback_call(
        self,
        *,
        from_number: str,
        to_number: str,
        script_text: str,
        audio_url: Optional[str] = None,
        voice: str = "default",
    ) -> dict[str, object]:
        if self.missing_env:
            return blocked_misconfigured_result(provider=self.provider, missing_env=self.missing_env)

        instruction = PhoneCallInstructionBuilder().build_tts_instruction(
            script_text=script_text,
            voice=voice,
        )
        sender = str(from_number or "").strip() or self.from_number
        payload = {
            "from": sender,
            "to": to_number,
            "script_text": script_text,
            "audio_url": audio_url or "",
            "voice": voice or "default",
            "instruction": instruction,
        }
        url = join_url(self.base_url, self.call_path)
        try:
            response = self.http_client.post(
                url,
                headers=bearer_json_headers(self.api_key),
                json=payload,
                timeout=self.timeout,
            )
        except Exception as exc:
            return provider_http_error_result(provider=self.provider, exc=exc)

        provider_result = provider_response_result(response)
        status = "queued" if http_success(provider_result["status_code"]) else "failed"
        return {
            "status": status,
            "provider": self.provider,
            "provider_call_id": first_body_value(provider_result["body"], ["call_id", "id", "sid"]),
            "playback_mode": "tts",
            "instruction": instruction,
            "provider_result": provider_result,
            "request": {
                "method": "POST",
                "url": url,
                "json": payload,
            },
        }

    def create_duplex_call(
        self,
        *,
        from_number: str,
        to_number: str,
        opening_script: str,
        media_stream_url: Optional[str] = None,
        voice: str = "default",
    ) -> dict[str, object]:
        missing_env = list(self.missing_env)
        callback_url = str(media_stream_url or self.duplex_webhook_url or "").strip()
        if not callback_url:
            missing_env.append("ASSISTANT_PHONE_DUPLEX_WEBHOOK_URL")
        if missing_env:
            return blocked_misconfigured_result(provider=self.provider, missing_env=missing_env)

        opening_instruction = PhoneDuplexTurnHandler().build_opening_instruction(
            opening_script=opening_script,
            voice=voice,
        )
        sender = str(from_number or "").strip() or self.from_number
        payload = {
            "from": sender,
            "to": to_number,
            "opening_script": opening_script,
            "voice": voice or "default",
            "duplex_mode": "turn_based_voice",
            "duplex_webhook_url": callback_url,
            "opening_instruction": opening_instruction,
        }
        url = join_url(self.base_url, self.duplex_call_path)
        try:
            response = self.http_client.post(
                url,
                headers=bearer_json_headers(self.api_key),
                json=payload,
                timeout=self.timeout,
            )
        except Exception as exc:
            return provider_http_error_result(provider=self.provider, exc=exc)

        provider_result = provider_response_result(response)
        status = "queued" if http_success(provider_result["status_code"]) else "failed"
        return {
            "status": status,
            "provider": self.provider,
            "provider_call_id": first_body_value(provider_result["body"], ["call_id", "id", "sid"]),
            "duplex_mode": "turn_based_voice",
            "opening_instruction": opening_instruction,
            "provider_result": provider_result,
            "request": {
                "method": "POST",
                "url": url,
                "json": payload,
            },
        }


class PhoneWebhookVerifier:
    def __init__(self, verify_token: str) -> None:
        self.verify_token = str(verify_token or "")

    def verify(self, token: str) -> None:
        if self.verify_token and token != self.verify_token:
            raise PermissionError("Assistant phone webhook token mismatch.")
