import base64
import sys
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_gmail_mime_builder_outputs_base64url_raw_message():
    from app.assistant_identity.gmail_adapter import GmailMimeBuilder

    raw = GmailMimeBuilder().build_raw_message(
        sender="nomi@example.com",
        recipient="alice@example.com",
        subject="Hello",
        body_text="我是 Nomi，张子长的个人助理。",
    )

    decoded = base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8")

    assert "From: nomi@example.com" in decoded
    assert "To: alice@example.com" in decoded
    assert "Subject: Hello" in decoded
    assert "Nomi" in decoded


def test_fake_gmail_adapter_records_send_without_real_provider():
    from app.assistant_identity.gmail_adapter import FakeAssistantGmailAdapter

    adapter = FakeAssistantGmailAdapter()
    result = adapter.send_message(
        sender="nomi@example.com",
        recipient="alice@example.com",
        subject="Hello",
        body_text="我是 Nomi。",
    )

    assert result["status"] == "sent"
    assert result["provider_message_id"].startswith("fake-gmail-")
    assert adapter.sent_messages[0]["recipient"] == "alice@example.com"


def test_gmail_http_adapter_blocks_when_env_config_is_missing(monkeypatch):
    from app.assistant_identity.gmail_adapter import GmailHttpAdapter

    for name in [
        "ASSISTANT_GMAIL_ADDRESS",
        "ASSISTANT_GMAIL_ACCESS_TOKEN",
    ]:
        monkeypatch.delenv(name, raising=False)

    adapter = GmailHttpAdapter.from_env(http_client=None)

    result = adapter.send_message(
        sender="",
        recipient="alice@example.com",
        subject="Hello",
        body_text="我是 Nomi。",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "misconfigured"
    assert result["provider"] == "gmail"
    assert result["missing_env"] == [
        "ASSISTANT_GMAIL_ACCESS_TOKEN",
        "ASSISTANT_GMAIL_ADDRESS",
    ]


def test_gmail_http_adapter_builds_send_request_and_records_provider_result(monkeypatch):
    from app.assistant_identity.gmail_adapter import GmailHttpAdapter

    monkeypatch.setenv("ASSISTANT_GMAIL_ADDRESS", "nomi@example.com")
    monkeypatch.setenv("ASSISTANT_GMAIL_ACCESS_TOKEN", "secret-token")
    monkeypatch.setenv("ASSISTANT_GMAIL_API_BASE_URL", "https://gmail.test/gmail/v1")

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"id": "gmail-provider-1", "threadId": "thread-provider-1"}

    class RecordingHttpClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: float) -> FakeResponse:
            self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return FakeResponse()

    http_client = RecordingHttpClient()
    adapter = GmailHttpAdapter.from_env(http_client=http_client)

    result = adapter.send_message(
        sender="nomi@example.com",
        recipient="alice@example.com",
        subject="Hello",
        body_text="我是 Nomi，张子长的个人助理。",
        thread_id="thread-local-1",
    )

    assert result["status"] == "sent"
    assert result["provider_message_id"] == "gmail-provider-1"
    assert result["provider_result"]["status_code"] == 200
    assert http_client.calls[0]["url"] == "https://gmail.test/gmail/v1/users/nomi@example.com/messages/send"
    assert http_client.calls[0]["headers"]["Authorization"] == "Bearer secret-token"
    assert http_client.calls[0]["json"]["threadId"] == "thread-local-1"

    decoded = base64.urlsafe_b64decode(http_client.calls[0]["json"]["raw"].encode("ascii")).decode("utf-8")
    assert "From: nomi@example.com" in decoded
    assert "To: alice@example.com" in decoded
    assert "Subject: Hello" in decoded

    assert "Authorization" not in str(result)
    assert "secret-token" not in str(result)
