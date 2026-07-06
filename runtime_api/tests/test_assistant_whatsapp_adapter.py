import sys
from pathlib import Path
from typing import Any


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


def test_whatsapp_http_adapter_blocks_when_env_config_is_missing(monkeypatch):
    from app.assistant_identity.whatsapp_adapter import WhatsAppCloudHttpAdapter

    for name in [
        "ASSISTANT_WHATSAPP_ACCESS_TOKEN",
        "ASSISTANT_WHATSAPP_PHONE_NUMBER_ID",
    ]:
        monkeypatch.delenv(name, raising=False)

    adapter = WhatsAppCloudHttpAdapter.from_env(http_client=None)

    result = adapter.send_text(phone_number_id="", to="+15551234567", body_text="我是 Nomi。")

    assert result["status"] == "blocked"
    assert result["reason"] == "misconfigured"
    assert result["provider"] == "whatsapp_cloud_api"
    assert result["missing_env"] == [
        "ASSISTANT_WHATSAPP_ACCESS_TOKEN",
        "ASSISTANT_WHATSAPP_PHONE_NUMBER_ID",
    ]


def test_whatsapp_http_adapter_builds_cloud_api_request_and_records_provider_result(monkeypatch):
    from app.assistant_identity.whatsapp_adapter import WhatsAppCloudHttpAdapter

    monkeypatch.setenv("ASSISTANT_WHATSAPP_ACCESS_TOKEN", "wa-secret")
    monkeypatch.setenv("ASSISTANT_WHATSAPP_PHONE_NUMBER_ID", "phone-number-1")
    monkeypatch.setenv("ASSISTANT_WHATSAPP_API_BASE_URL", "https://graph.test/v20.0")

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"messages": [{"id": "wamid.provider.1"}]}

    class RecordingHttpClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: float) -> FakeResponse:
            self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return FakeResponse()

    http_client = RecordingHttpClient()
    adapter = WhatsAppCloudHttpAdapter.from_env(http_client=http_client)

    result = adapter.send_text(phone_number_id="", to="+15551234567", body_text="我是 Nomi。")

    assert result["status"] == "sent"
    assert result["provider_message_id"] == "wamid.provider.1"
    assert result["provider_result"]["body"] == {"messages": [{"id": "wamid.provider.1"}]}
    assert http_client.calls[0]["url"] == "https://graph.test/v20.0/phone-number-1/messages"
    assert http_client.calls[0]["headers"]["Authorization"] == "Bearer wa-secret"
    assert http_client.calls[0]["json"] == {
        "messaging_product": "whatsapp",
        "to": "+15551234567",
        "type": "text",
        "text": {"body": "我是 Nomi。"},
    }
    assert "Authorization" not in str(result)
    assert "wa-secret" not in str(result)
