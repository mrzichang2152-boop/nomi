import sys
from pathlib import Path
from typing import get_type_hints


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_assistant_adapter_contracts_expose_send_methods():
    from app.assistant_identity.adapters import (
        AssistantGmailAdapter,
        AssistantPhoneCallAdapter,
        AssistantSmsAdapter,
        AssistantWhatsAppAdapter,
    )

    gmail_hints = get_type_hints(AssistantGmailAdapter.send_message)
    whatsapp_hints = get_type_hints(AssistantWhatsAppAdapter.send_text)
    sms_hints = get_type_hints(AssistantSmsAdapter.send_sms)
    call_hints = get_type_hints(AssistantPhoneCallAdapter.create_playback_call)

    assert "sender" in gmail_hints
    assert "recipient" in gmail_hints
    assert "phone_number_id" in whatsapp_hints
    assert "to" in whatsapp_hints
    assert "from_number" in sms_hints
    assert "to_number" in sms_hints
    assert "script_text" in call_hints
    assert gmail_hints["return"] == dict[str, object]
    assert whatsapp_hints["return"] == dict[str, object]
    assert sms_hints["return"] == dict[str, object]
    assert call_hints["return"] == dict[str, object]


def test_fake_provider_adapters_match_required_methods():
    from app.assistant_identity.gmail_adapter import FakeAssistantGmailAdapter
    from app.assistant_identity.phone_adapter import FakeAssistantPhoneCallAdapter, FakeAssistantSmsAdapter
    from app.assistant_identity.whatsapp_adapter import FakeAssistantWhatsAppAdapter

    assert hasattr(FakeAssistantGmailAdapter(), "send_message")
    assert hasattr(FakeAssistantWhatsAppAdapter(), "send_text")
    assert hasattr(FakeAssistantSmsAdapter(), "send_sms")
    assert hasattr(FakeAssistantPhoneCallAdapter(), "create_playback_call")
