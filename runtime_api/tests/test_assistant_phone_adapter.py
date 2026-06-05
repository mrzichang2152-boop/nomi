import sys
from pathlib import Path


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
