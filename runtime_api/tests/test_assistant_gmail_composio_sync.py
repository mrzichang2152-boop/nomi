import sys
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _connected_registry():
    from app.assistant_identity.composio_gmail import (
        ASSISTANT_GMAIL_COMPOSIO_USER_ID,
        ASSISTANT_GMAIL_IDENTITY_ID,
    )
    from app.assistant_identity.models import AssistantIdentity
    from app.assistant_identity.registry import AssistantIdentityRegistry

    registry = AssistantIdentityRegistry()
    registry.add(
        AssistantIdentity(
            identity_id=ASSISTANT_GMAIL_IDENTITY_ID,
            kind="assistant_gmail",
            provider="composio_gmail",
            display_name="Nomi",
            address="nomi.real@example.com",
            status="connected",
            capabilities=["draft", "send", "thread_reply"],
            metadata={
                "provider_connection": {
                    "composio_user_id": ASSISTANT_GMAIL_COMPOSIO_USER_ID,
                    "connected_account_id": "ca_nomi_gmail",
                    "account_status": "ACTIVE",
                }
            },
        )
    )
    return registry


class FakeHealthService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(
        self,
        identity_id: str,
        check_type: str,
        status: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        item = {
            "identity_id": identity_id,
            "check_type": check_type,
            "status": status,
            **kwargs,
        }
        self.records.append(item)
        return item


def test_in_memory_inbox_repository_reads_stable_event_id_across_list_and_detail():
    from app.assistant_identity.gmail_sync import InMemoryAssistantInboxEventRepository

    repository = InMemoryAssistantInboxEventRepository()
    event = {
        "event_id": "assistant-inbox-stable-1",
        "identity_id": "nomi_gmail_primary",
        "external_message_id": "gmail-stable-1",
        "normalized_text": "稳定事件",
    }

    assert repository.insert_if_new(event) is True
    assert repository.get("assistant-inbox-stable-1") == event
    assert repository.list() == [event]


def test_incremental_query_uses_overlap_and_accepts_invalid_or_missing_timestamp():
    from app.assistant_identity.gmail_sync import assistant_gmail_incremental_query

    assert assistant_gmail_incremental_query(None) == "newer_than:1d"
    assert assistant_gmail_incremental_query("not-a-date") == "newer_than:1d"
    assert (
        assistant_gmail_incremental_query("2026-07-21T10:00:00+00:00")
        == "after:1784627940"
    )


def test_trigger_setup_is_pinned_to_nomi_account_and_enables_receive():
    from app.assistant_identity.composio_gmail import (
        ASSISTANT_GMAIL_COMPOSIO_USER_ID,
        ASSISTANT_GMAIL_IDENTITY_ID,
    )
    from app.assistant_identity.gmail_sync import (
        AssistantGmailInboundSyncService,
        InMemoryAssistantInboxEventRepository,
    )

    class Provider:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def create_new_message_trigger(self, **kwargs: Any) -> str:
            self.calls.append(kwargs)
            return "trigger_nomi_gmail"

        def fetch_messages(self, **kwargs: Any) -> list[dict[str, Any]]:
            raise AssertionError("fallback must not run when trigger setup succeeds")

    provider = Provider()
    registry = _connected_registry()
    health = FakeHealthService()
    service = AssistantGmailInboundSyncService(
        registry=registry,
        health_service=health,
        provider=provider,
        event_repository=InMemoryAssistantInboxEventRepository(),
    )

    result = service.configure_inbound()

    assert provider.calls == [
        {
            "user_id": ASSISTANT_GMAIL_COMPOSIO_USER_ID,
            "connected_account_id": "ca_nomi_gmail",
        }
    ]
    assert result == {
        "status": "configured",
        "mode": "trigger",
        "trigger_id": "trigger_nomi_gmail",
        "identity_id": ASSISTANT_GMAIL_IDENTITY_ID,
    }
    identity = registry.get(ASSISTANT_GMAIL_IDENTITY_ID)
    assert identity is not None
    assert "receive" in identity.capabilities
    assert identity.metadata["inbound"]["mode"] == "trigger"
    assert health.records[-1]["status"] == "passed"
    assert health.records[-1]["details"] == {
        "mode": "trigger",
        "trigger_id": "trigger_nomi_gmail",
        "managed_polling_latency_possible": True,
    }


def test_trigger_unavailable_uses_bounded_incremental_sync_and_suppresses_duplicates():
    from app.assistant_identity.composio_gmail import (
        ASSISTANT_GMAIL_COMPOSIO_USER_ID,
        ASSISTANT_GMAIL_IDENTITY_ID,
    )
    from app.assistant_identity.gmail_sync import (
        AssistantGmailInboundSyncService,
        InMemoryAssistantInboxEventRepository,
    )
    from app.assistant_identity.inbox_gateway import AssistantInboxGateway
    from app.assistant_identity.contact_resolver import ContactResolver

    class Provider:
        def __init__(self) -> None:
            self.fetch_calls: list[dict[str, Any]] = []

        def create_new_message_trigger(self, **kwargs: Any) -> str:
            raise RuntimeError("trigger_not_supported")

        def fetch_messages(self, **kwargs: Any) -> list[dict[str, Any]]:
            self.fetch_calls.append(kwargs)
            return [
                {
                    "id": "gmail-in-1",
                    "thread_id": "thread-1",
                    "from": "owner@example.com",
                    "to": ["nomi.real@example.com"],
                    "subject": "请处理会议资料",
                    "body": "请把资料发给 Alice。",
                    "date": "2026-07-21T10:00:00Z",
                },
                {
                    "id": "gmail-in-1",
                    "thread_id": "thread-1",
                    "from": "owner@example.com",
                    "subject": "重复历史记录",
                    "body": "这封不应重复写入。",
                },
            ]

    provider = Provider()
    registry = _connected_registry()
    repository = InMemoryAssistantInboxEventRepository()
    health = FakeHealthService()
    service = AssistantGmailInboundSyncService(
        registry=registry,
        health_service=health,
        provider=provider,
        event_repository=repository,
        gateway=AssistantInboxGateway(
            ContactResolver(user_keys={"owner@example.com"})
        ),
    )

    result = service.configure_inbound(fetch_limit=500)

    assert provider.fetch_calls == [
        {
            "user_id": ASSISTANT_GMAIL_COMPOSIO_USER_ID,
            "connected_account_id": "ca_nomi_gmail",
            "query": "newer_than:1d",
            "limit": 50,
        }
    ]
    assert result["status"] == "configured"
    assert result["mode"] == "bounded_incremental_sync"
    assert result["created_count"] == 1
    assert result["duplicate_count"] == 1
    assert result["fetched_count"] == 2
    stored = repository.list(ASSISTANT_GMAIL_IDENTITY_ID)
    assert len(stored) == 1
    assert stored[0]["external_message_id"] == "gmail-in-1"
    assert stored[0]["classification"] == "user_direct_command"
    assert stored[0]["normalized_text"] == "请把资料发给 Alice。"
    assert "reply" not in stored[0]
    assert "send" not in stored[0]
    assert health.records[-1]["status"] == "passed"
    assert health.records[-1]["details"] == {
        "mode": "bounded_incremental_sync",
        "fetched_count": 2,
        "created_count": 1,
        "duplicate_count": 1,
        "max_batch_size": 50,
        "trigger_error_code": "assistant_gmail_trigger_unavailable",
    }


def test_trigger_delivery_is_idempotent_and_rejects_missing_message_id():
    from app.assistant_identity.composio_gmail import ASSISTANT_GMAIL_IDENTITY_ID
    from app.assistant_identity.gmail_sync import (
        AssistantGmailInboundSyncService,
        InMemoryAssistantInboxEventRepository,
    )

    class Provider:
        def create_new_message_trigger(self, **kwargs: Any) -> str:
            return "trigger"

        def fetch_messages(self, **kwargs: Any) -> list[dict[str, Any]]:
            return []

    repository = InMemoryAssistantInboxEventRepository()
    service = AssistantGmailInboundSyncService(
        registry=_connected_registry(),
        health_service=FakeHealthService(),
        provider=Provider(),
        event_repository=repository,
    )
    payload = {
        "data": {
            "message": {
                "id": "trigger-message-1",
                "threadId": "trigger-thread-1",
                "from": "alice@example.com",
                "subject": "项目进展",
                "body": "请问进展如何？",
            }
        }
    }

    first = service.ingest_trigger(payload)
    duplicate = service.ingest_trigger(payload)
    invalid = service.ingest_trigger({"data": {"message": {"body": "no id"}}})

    assert first == {
        "status": "created",
        "external_message_id": "trigger-message-1",
    }
    assert duplicate == {
        "status": "duplicate",
        "external_message_id": "trigger-message-1",
    }
    assert invalid == {
        "status": "rejected",
        "reason": "assistant_gmail_message_id_missing",
    }
    assert len(repository.list(ASSISTANT_GMAIL_IDENTITY_ID)) == 1


def test_incremental_sync_normalizes_current_composio_gmail_message_fields():
    from app.assistant_identity.composio_gmail import ASSISTANT_GMAIL_IDENTITY_ID
    from app.assistant_identity.gmail_sync import (
        AssistantGmailInboundSyncService,
        InMemoryAssistantInboxEventRepository,
    )

    class Provider:
        def fetch_messages(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {
                    "messageId": "gmail-current-1",
                    "threadId": "gmail-thread-current-1",
                    "sender": "Alice <alice@example.com>",
                    "to": "nomi.real@example.com",
                    "subject": "项目碰面",
                    "messageText": "明天下午三点在人民广场见，带合同。",
                    "messageTimestamp": "2026-07-22T09:26:27Z",
                    "preview": {
                        "subject": "项目碰面",
                        "body": "明天下午三点在人民广场见，带合同。",
                    },
                }
            ]

    repository = InMemoryAssistantInboxEventRepository()
    service = AssistantGmailInboundSyncService(
        registry=_connected_registry(),
        health_service=FakeHealthService(),
        provider=Provider(),
        event_repository=repository,
    )

    result = service.sync_once(query="newer_than:1d", fetch_limit=10)

    assert result == {
        "fetched_count": 1,
        "created_count": 1,
        "duplicate_count": 0,
    }
    stored = repository.list(ASSISTANT_GMAIL_IDENTITY_ID)
    assert len(stored) == 1
    event = stored[0]
    assert event["external_message_id"] == "gmail-current-1"
    assert event["conversation_id"] == "gmail-thread-current-1"
    assert event["normalized_text"] == "明天下午三点在人民广场见，带合同。"
    assert event["normalized_payload"]["from"] == "Alice <alice@example.com>"
    assert event["normalized_payload"]["subject"] == "项目碰面"
    assert event["occurred_at"] == "2026-07-22T09:26:27Z"


def test_inbound_setup_fails_closed_without_pinned_assistant_account():
    from app.assistant_identity.composio_gmail import ASSISTANT_GMAIL_IDENTITY_ID
    from app.assistant_identity.gmail_sync import (
        AssistantGmailInboundSyncError,
        AssistantGmailInboundSyncService,
        InMemoryAssistantInboxEventRepository,
    )

    registry = _connected_registry()
    identity = registry.get(ASSISTANT_GMAIL_IDENTITY_ID)
    assert identity is not None
    from dataclasses import replace

    registry.repository.save(
        replace(identity, metadata={}),
        expected_version=identity.version,
    )
    service = AssistantGmailInboundSyncService(
        registry=registry,
        health_service=FakeHealthService(),
        provider=object(),
        event_repository=InMemoryAssistantInboxEventRepository(),
    )

    try:
        service.configure_inbound()
    except AssistantGmailInboundSyncError as exc:
        assert exc.code == "assistant_gmail_connected_account_missing"
    else:
        raise AssertionError("missing pinned account must fail closed")


def test_repeated_inbound_configuration_reuses_persisted_trigger():
    from app.assistant_identity.composio_gmail import ASSISTANT_GMAIL_IDENTITY_ID
    from app.assistant_identity.gmail_sync import (
        AssistantGmailInboundSyncService,
        InMemoryAssistantInboxEventRepository,
    )

    class Provider:
        def __init__(self) -> None:
            self.create_count = 0

        def create_new_message_trigger(self, **kwargs: Any) -> str:
            self.create_count += 1
            return "trigger-stable"

        def fetch_messages(self, **kwargs: Any) -> list[dict[str, Any]]:
            return []

    registry = _connected_registry()
    provider = Provider()
    service = AssistantGmailInboundSyncService(
        registry=registry,
        health_service=FakeHealthService(),
        provider=provider,
        event_repository=InMemoryAssistantInboxEventRepository(),
    )

    first = service.configure_inbound()
    second = service.configure_inbound()

    assert first["trigger_id"] == "trigger-stable"
    assert second == {
        "status": "configured",
        "mode": "trigger",
        "trigger_id": "trigger-stable",
        "identity_id": ASSISTANT_GMAIL_IDENTITY_ID,
        "reused": True,
    }
    assert provider.create_count == 1


def test_composio_inbound_provider_uses_current_trigger_and_fetch_contracts():
    from app.assistant_identity.composio_gmail import (
        ASSISTANT_GMAIL_COMPOSIO_USER_ID,
    )
    from app.assistant_identity.gmail_sync import (
        ASSISTANT_GMAIL_FETCH_TOOL,
        ASSISTANT_GMAIL_NEW_MESSAGE_TRIGGER,
        ComposioSdkAssistantGmailInboundProvider,
    )

    class Triggers:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def create(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            return {"trigger_id": "tr_current"}

    class Tools:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def execute(self, slug: str, **kwargs: Any) -> dict[str, Any]:
            self.calls.append((slug, kwargs))
            return {
                "successful": True,
                "data": {
                    "messages": [
                        {
                            "id": "message-current",
                            "threadId": "thread-current",
                            "body": "hello",
                        }
                    ]
                },
            }

    class Sdk:
        def __init__(self) -> None:
            self.triggers = Triggers()
            self.tools = Tools()

    sdk = Sdk()
    provider = ComposioSdkAssistantGmailInboundProvider(sdk)

    trigger_id = provider.create_new_message_trigger(
        user_id=ASSISTANT_GMAIL_COMPOSIO_USER_ID,
        connected_account_id="ca_nomi_gmail",
    )
    messages = provider.fetch_messages(
        user_id=ASSISTANT_GMAIL_COMPOSIO_USER_ID,
        connected_account_id="ca_nomi_gmail",
        query="after:1784563200",
        limit=999,
    )

    assert trigger_id == "tr_current"
    assert sdk.triggers.calls == [
        {
            "slug": ASSISTANT_GMAIL_NEW_MESSAGE_TRIGGER,
            "user_id": ASSISTANT_GMAIL_COMPOSIO_USER_ID,
            "connected_account_id": "ca_nomi_gmail",
            "trigger_config": {},
        }
    ]
    assert sdk.tools.calls == [
        (
            ASSISTANT_GMAIL_FETCH_TOOL,
            {
                "user_id": ASSISTANT_GMAIL_COMPOSIO_USER_ID,
                "connected_account_id": "ca_nomi_gmail",
                "version": "20260721_00",
                "arguments": {
                    "query": "after:1784563200",
                    "max_results": 50,
                },
            },
        )
    ]
    assert messages == [
        {
            "id": "message-current",
            "threadId": "thread-current",
            "body": "hello",
        }
    ]


def test_composio_trigger_subscription_forwards_matching_event_to_handler():
    from app.assistant_identity.gmail_sync import (
        ComposioSdkAssistantGmailInboundProvider,
    )

    class Subscription:
        def __init__(self) -> None:
            self.trigger_id = ""
            self.callback = None

        def handle(self, *, trigger_id: str):
            self.trigger_id = trigger_id

            def decorator(callback):
                self.callback = callback
                return callback

            return decorator

        def wait_forever(self) -> None:
            raise AssertionError("building the subscription must not block the caller")

    class Triggers:
        def __init__(self) -> None:
            self.subscription = Subscription()

        def subscribe(self):
            return self.subscription

    class Sdk:
        def __init__(self) -> None:
            self.triggers = Triggers()

    sdk = Sdk()
    provider = ComposioSdkAssistantGmailInboundProvider(sdk)
    received: list[dict[str, Any]] = []

    subscription = provider.build_trigger_subscription(
        trigger_id="trigger_nomi_gmail",
        handler=lambda event: received.append(event),
    )

    assert subscription is sdk.triggers.subscription
    assert subscription.trigger_id == "trigger_nomi_gmail"
    assert subscription.callback is not None
    subscription.callback({"data": {"message": {"id": "gmail-live-1"}}})
    assert received == [{"data": {"message": {"id": "gmail-live-1"}}}]
