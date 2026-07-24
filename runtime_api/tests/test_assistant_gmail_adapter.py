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


def test_composio_gmail_adapter_sends_with_only_the_pinned_assistant_account():
    from app.assistant_identity.composio_gmail import ASSISTANT_GMAIL_COMPOSIO_USER_ID
    from app.assistant_identity.gmail_adapter import ComposioAssistantGmailAdapter

    class Tools:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def execute(self, slug: str, **kwargs: Any) -> dict[str, Any]:
            self.calls.append((slug, kwargs))
            return {
                "successful": True,
                "data": {
                    "id": "gmail-provider-42",
                    "threadId": "thread-provider-42",
                    "raw": "must-not-enter-audit",
                },
            }

    class Sdk:
        def __init__(self) -> None:
            self.tools = Tools()

    sdk = Sdk()
    adapter = ComposioAssistantGmailAdapter(
        sdk=sdk,
        connected_account_id="ca_nomi_gmail",
        address="nomi.real@example.com",
    )

    result = adapter.send_message(
        sender="nomi.real@example.com",
        recipient="alice@example.com",
        subject="会议资料",
        body_text="我是 Nomi，资料已整理。",
    )

    assert sdk.tools.calls == [
        (
            "GMAIL_SEND_EMAIL",
            {
                "user_id": ASSISTANT_GMAIL_COMPOSIO_USER_ID,
                "connected_account_id": "ca_nomi_gmail",
                "version": "20260721_00",
                "arguments": {
                    "recipient_email": "alice@example.com",
                    "subject": "会议资料",
                    "body": "我是 Nomi，资料已整理。",
                },
            },
        )
    ]
    assert result == {
        "status": "sent",
        "provider": "composio_gmail",
        "provider_message_id": "gmail-provider-42",
        "provider_thread_id": "thread-provider-42",
        "provider_result": {"successful": True},
        "request": {
            "tool_slug": "GMAIL_SEND_EMAIL",
            "connected_account_id": "ca_nomi_gmail",
            "recipient": "alice@example.com",
            "subject_present": True,
            "body_sha256": "e7b7f12226776c0fc4b41a2eff0bf22bdbb7e96cf5a9a5cb99762ad5b4186499",
        },
    }
    assert "must-not-enter-audit" not in repr(result)


def test_composio_gmail_adapter_rejects_sender_mismatch_without_tool_execution():
    from app.assistant_identity.gmail_adapter import ComposioAssistantGmailAdapter

    class Tools:
        calls: list[object] = []

        def execute(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            self.calls.append((args, kwargs))
            return {"successful": True}

    class Sdk:
        tools = Tools()

    adapter = ComposioAssistantGmailAdapter(
        sdk=Sdk(),
        connected_account_id="ca_nomi_gmail",
        address="nomi.real@example.com",
    )

    result = adapter.send_message(
        sender="user.personal@example.com",
        recipient="alice@example.com",
        subject="Hi",
        body_text="Hello",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "assistant_gmail_sender_mismatch"
    assert Sdk.tools.calls == []


def test_composio_gmail_adapter_marks_unknown_delivery_when_execute_raises():
    from app.assistant_identity.gmail_adapter import ComposioAssistantGmailAdapter

    class Tools:
        def execute(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise ConnectionError("connection closed after request upload")

    class Sdk:
        tools = Tools()

    adapter = ComposioAssistantGmailAdapter(
        sdk=Sdk(),
        connected_account_id="ca_nomi_gmail",
        address="nomi.real@example.com",
    )

    result = adapter.send_message(
        sender="nomi.real@example.com",
        recipient="alice@example.com",
        subject="Hi",
        body_text="Hello",
    )

    assert result["status"] == "delivery_unknown"
    assert result["reason"] == "composio_gmail_delivery_requires_verification"
    assert result["provider_result"]["successful"] is None
    assert result["provider_result"]["error_type"] == "ConnectionError"


def test_composio_gmail_adapter_replies_to_exact_thread_when_present():
    from app.assistant_identity.gmail_adapter import ComposioAssistantGmailAdapter

    class Tools:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def execute(self, slug: str, **kwargs: Any) -> dict[str, Any]:
            self.calls.append((slug, kwargs))
            return {"successful": True, "data": {"id": "reply-1"}}

    class Sdk:
        def __init__(self) -> None:
            self.tools = Tools()

    sdk = Sdk()
    adapter = ComposioAssistantGmailAdapter(
        sdk=sdk,
        connected_account_id="ca_nomi_gmail",
        address="nomi.real@example.com",
    )

    result = adapter.send_message(
        sender="nomi.real@example.com",
        recipient="alice@example.com",
        subject="ignored-for-thread-reply",
        body_text="收到，我会转达。",
        thread_id="thread-exact-1",
    )

    assert result["status"] == "sent"
    assert sdk.tools.calls[0] == (
        "GMAIL_REPLY_TO_THREAD",
        {
            "user_id": "nomi-owned::nomi_gmail_primary",
            "connected_account_id": "ca_nomi_gmail",
            "version": "20260721_00",
            "arguments": {
                "recipient_email": "alice@example.com",
                "message_body": "收到，我会转达。",
                "thread_id": "thread-exact-1",
            },
        },
    )


def test_registry_backed_composio_adapter_resolves_pinned_account_at_send_time():
    from app.assistant_identity.gmail_adapter import (
        RegistryBackedComposioAssistantGmailAdapter,
    )

    class Identity:
        identity_id = "nomi_gmail_primary"
        kind = "assistant_gmail"
        status = "connected"
        address = "nomi.real@example.com"
        capabilities = ["draft", "send", "thread_reply"]
        metadata = {
            "provider_connection": {
                "connected_account_id": "ca_nomi_gmail",
                "composio_user_id": "nomi-owned::nomi_gmail_primary",
            }
        }

    class Registry:
        def get(self, identity_id: str):
            assert identity_id == "nomi_gmail_primary"
            return Identity()

    class Tools:
        def __init__(self) -> None:
            self.calls = []

        def execute(self, slug: str, **kwargs: Any):
            self.calls.append((slug, kwargs))
            return {"successful": True, "data": {"id": "sent-live-1"}}

    class Sdk:
        def __init__(self) -> None:
            self.tools = Tools()

    sdk = Sdk()
    adapter = RegistryBackedComposioAssistantGmailAdapter(
        registry=Registry(),
        sdk_factory=lambda: sdk,
    )

    result = adapter.send_message(
        sender="",
        recipient="alice@example.com",
        subject="进度",
        body_text="我是 Nomi。",
    )

    assert result["status"] == "sent"
    assert result["provider_message_id"] == "sent-live-1"
    assert sdk.tools.calls[0][1]["connected_account_id"] == "ca_nomi_gmail"


def test_registry_backed_composio_adapter_blocks_unverified_identity_before_sdk_creation():
    from app.assistant_identity.gmail_adapter import (
        RegistryBackedComposioAssistantGmailAdapter,
    )

    class Identity:
        identity_id = "nomi_gmail_primary"
        kind = "assistant_gmail"
        status = "authorization_pending"
        address = ""
        capabilities = []
        metadata = {}

    class Registry:
        def get(self, identity_id: str):
            return Identity()

    created = []
    adapter = RegistryBackedComposioAssistantGmailAdapter(
        registry=Registry(),
        sdk_factory=lambda: created.append(True),
    )

    result = adapter.send_message(
        sender="",
        recipient="alice@example.com",
        subject="进度",
        body_text="我是 Nomi。",
    )

    assert result == {
        "status": "blocked",
        "reason": "assistant_gmail_identity_not_verified",
        "provider": "composio_gmail",
        "provider_result": {"successful": False},
    }
    assert created == []
