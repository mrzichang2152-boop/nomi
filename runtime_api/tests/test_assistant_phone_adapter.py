import sys
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_fake_sms_adapter_records_confirmed_send():
    from app.assistant_identity.phone_adapter import FakeAssistantSmsAdapter

    adapter = FakeAssistantSmsAdapter()
    result = adapter.send_sms(
        from_number="+15550000000",
        to_number="+15551234567",
        body_text="我是 Nomi，张子长的个人助理。他十分钟后到。",
    )

    assert result["status"] == "sent"
    assert result["provider_message_id"].startswith("fake-sms-")
    assert adapter.sent_messages[0]["to_number"] == "+15551234567"


def test_call_script_validator_rejects_duplex_request_shape():
    from app.assistant_identity.phone_adapter import PhonePlaybackScriptValidator

    result = PhonePlaybackScriptValidator().validate("我是 Nomi，请你听到后回答我现在是否方便。")

    assert result["allowed"] is False
    assert "单向播放" in result["reason"]


def test_call_instruction_builder_outputs_one_way_playback_payload():
    from app.assistant_identity.phone_adapter import PhoneCallInstructionBuilder

    payload = PhoneCallInstructionBuilder().build_tts_instruction(
        script_text="我是 Nomi，张子长的个人助理。他十分钟后到。",
        voice="default",
    )

    assert payload["mode"] == "tts_playback"
    assert payload["script_text"].startswith("我是 Nomi")
    assert payload["estimated_duration_seconds"] >= 3


def test_fake_call_adapter_records_playback_call():
    from app.assistant_identity.phone_adapter import FakeAssistantPhoneCallAdapter

    adapter = FakeAssistantPhoneCallAdapter()
    result = adapter.create_playback_call(
        from_number="+15550000000",
        to_number="+15551234567",
        script_text="我是 Nomi，张子长的个人助理。他十分钟后到。",
    )

    assert result["status"] == "queued"
    assert result["provider_call_id"].startswith("fake-call-")
    assert result["playback_mode"] == "tts"
    assert adapter.calls[0]["to_number"] == "+15551234567"


def test_phone_http_provider_blocks_sms_when_env_config_is_missing(monkeypatch):
    from app.assistant_identity.phone_adapter import HttpAssistantPhoneProvider

    for name in [
        "ASSISTANT_PHONE_PROVIDER_BASE_URL",
        "ASSISTANT_PHONE_PROVIDER_API_KEY",
        "ASSISTANT_PHONE_NUMBER",
    ]:
        monkeypatch.delenv(name, raising=False)

    adapter = HttpAssistantPhoneProvider.from_env(http_client=None)

    result = adapter.send_sms(
        from_number="",
        to_number="+15551234567",
        body_text="我是 Nomi。",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "misconfigured"
    assert result["provider"] == "http_phone"
    assert result["missing_env"] == [
        "ASSISTANT_PHONE_NUMBER",
        "ASSISTANT_PHONE_PROVIDER_API_KEY",
        "ASSISTANT_PHONE_PROVIDER_BASE_URL",
    ]


def test_phone_http_provider_builds_sms_request_and_records_provider_result(monkeypatch):
    from app.assistant_identity.phone_adapter import HttpAssistantPhoneProvider

    monkeypatch.setenv("ASSISTANT_PHONE_PROVIDER_BASE_URL", "https://phone.test/api")
    monkeypatch.setenv("ASSISTANT_PHONE_PROVIDER_API_KEY", "phone-secret")
    monkeypatch.setenv("ASSISTANT_PHONE_NUMBER", "+15550000000")

    class FakeResponse:
        status_code = 202

        def json(self) -> dict[str, Any]:
            return {"message_id": "sms-provider-1", "status": "queued"}

    class RecordingHttpClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: float) -> FakeResponse:
            self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return FakeResponse()

    http_client = RecordingHttpClient()
    adapter = HttpAssistantPhoneProvider.from_env(http_client=http_client)

    result = adapter.send_sms(
        from_number="",
        to_number="+15551234567",
        body_text="我是 Nomi，张子长的个人助理。他十分钟后到。",
    )

    assert result["status"] == "sent"
    assert result["provider_message_id"] == "sms-provider-1"
    assert result["provider_result"]["status_code"] == 202
    assert http_client.calls[0]["url"] == "https://phone.test/api/sms"
    assert http_client.calls[0]["headers"]["Authorization"] == "Bearer phone-secret"
    assert http_client.calls[0]["json"] == {
        "from": "+15550000000",
        "to": "+15551234567",
        "body": "我是 Nomi，张子长的个人助理。他十分钟后到。",
    }
    assert "Authorization" not in str(result)
    assert "phone-secret" not in str(result)


def test_phone_http_provider_builds_playback_call_request(monkeypatch):
    from app.assistant_identity.phone_adapter import HttpAssistantPhoneProvider

    monkeypatch.setenv("ASSISTANT_PHONE_PROVIDER_BASE_URL", "https://phone.test/api")
    monkeypatch.setenv("ASSISTANT_PHONE_PROVIDER_API_KEY", "phone-secret")
    monkeypatch.setenv("ASSISTANT_PHONE_NUMBER", "+15550000000")
    monkeypatch.setenv("ASSISTANT_PHONE_PROVIDER_NAME", "acme_voice")

    class FakeResponse:
        status_code = 201

        def json(self) -> dict[str, Any]:
            return {"call_id": "call-provider-1", "status": "queued"}

    class RecordingHttpClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: float) -> FakeResponse:
            self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return FakeResponse()

    http_client = RecordingHttpClient()
    adapter = HttpAssistantPhoneProvider.from_env(http_client=http_client)

    result = adapter.create_playback_call(
        from_number="",
        to_number="+15551234567",
        script_text="我是 Nomi，张子长的个人助理。他十分钟后到。",
        voice="serena",
    )

    assert result["status"] == "queued"
    assert result["provider"] == "acme_voice"
    assert result["provider_call_id"] == "call-provider-1"
    assert http_client.calls[0]["url"] == "https://phone.test/api/calls/playback"
    assert http_client.calls[0]["json"]["from"] == "+15550000000"
    assert http_client.calls[0]["json"]["to"] == "+15551234567"
    assert http_client.calls[0]["json"]["instruction"]["mode"] == "tts_playback"
    assert http_client.calls[0]["json"]["instruction"]["voice"] == "serena"


def test_phone_http_provider_builds_duplex_call_request(monkeypatch):
    from app.assistant_identity.phone_adapter import HttpAssistantPhoneProvider

    monkeypatch.setenv("ASSISTANT_PHONE_PROVIDER_BASE_URL", "https://phone.test/api")
    monkeypatch.setenv("ASSISTANT_PHONE_PROVIDER_API_KEY", "phone-secret")
    monkeypatch.setenv("ASSISTANT_PHONE_NUMBER", "+15550000000")
    monkeypatch.setenv("ASSISTANT_PHONE_DUPLEX_WEBHOOK_URL", "https://nomi.test/api/assistant-inbox/phone/calls/duplex/turn")
    monkeypatch.setenv("ASSISTANT_PHONE_DUPLEX_CALL_PATH", "/calls/duplex")

    class FakeResponse:
        status_code = 201

        def json(self) -> dict[str, Any]:
            return {"call_id": "duplex-call-1", "status": "queued"}

    class RecordingHttpClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: float) -> FakeResponse:
            self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return FakeResponse()

    http_client = RecordingHttpClient()
    adapter = HttpAssistantPhoneProvider.from_env(http_client=http_client)

    result = adapter.create_duplex_call(
        from_number="",
        to_number="+15551234567",
        opening_script="我是 Nomi，张子长的个人助理。我可以先帮你记录并转达。",
        voice="serena",
    )

    assert result["status"] == "queued"
    assert result["provider_call_id"] == "duplex-call-1"
    assert result["duplex_mode"] == "turn_based_voice"
    assert http_client.calls[0]["url"] == "https://phone.test/api/calls/duplex"
    assert http_client.calls[0]["json"]["from"] == "+15550000000"
    assert http_client.calls[0]["json"]["to"] == "+15551234567"
    assert http_client.calls[0]["json"]["opening_instruction"]["mode"] == "tts_duplex_opening"
    assert http_client.calls[0]["json"]["duplex_webhook_url"] == "https://nomi.test/api/assistant-inbox/phone/calls/duplex/turn"
    assert "Authorization" not in str(result)
    assert "phone-secret" not in str(result)


def test_duplex_turn_handler_records_transcript_and_generates_reply_instruction():
    from app.assistant_identity.phone_adapter import PhoneDuplexTurnHandler

    result = PhoneDuplexTurnHandler().build_reply_instruction(
        transcript="请告诉张子长我明天下午三点到。",
        voice="serena",
    )

    assert result["mode"] == "tts_reply"
    assert result["v2_duplex_turn"] is True
    assert "Nomi" in result["script_text"]
    assert "转达" in result["script_text"]
