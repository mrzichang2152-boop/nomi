import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_whatsapp_webhook_verifier_accepts_matching_token():
    from app.assistant_identity.whatsapp_adapter import WhatsAppWebhookVerifier

    verifier = WhatsAppWebhookVerifier(verify_token="local-token")

    assert verifier.verify(mode="subscribe", token="local-token", challenge="abc") == "abc"


def test_whatsapp_webhook_verifier_rejects_wrong_token():
    from app.assistant_identity.whatsapp_adapter import WhatsAppWebhookVerifier

    verifier = WhatsAppWebhookVerifier(verify_token="local-token")

    try:
        verifier.verify(mode="subscribe", token="wrong", challenge="abc")
    except PermissionError as exc:
        assert "mismatch" in str(exc).lower()
    else:
        raise AssertionError("wrong webhook token was accepted")


def test_fake_whatsapp_adapter_sends_text():
    from app.assistant_identity.whatsapp_adapter import FakeAssistantWhatsAppAdapter

    adapter = FakeAssistantWhatsAppAdapter()
    result = adapter.send_text(phone_number_id="phone-1", to="+222", body_text="我是 Nomi。")

    assert result["status"] == "sent"
    assert result["provider_message_id"].startswith("fake-whatsapp-")
    assert adapter.sent_messages[0]["to"] == "+222"
