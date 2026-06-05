import base64
import sys
from pathlib import Path


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
