# Nomi Owned Communication Identities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Nomi-owned Gmail and WhatsApp identities so Nomi can receive user/external messages and send confirmed outbound messages as Nomi.

**Architecture:** Add a separate assistant identity layer beside the existing user-account collectors. Inbound Nomi-owned Gmail/WhatsApp messages enter an AssistantInboxGateway, become normalized private events, and are classified as user commands, external contact messages, provider statuses, unknown senders, or spam. Outbound messages go through a deterministic draft-confirm-send pipeline with provider adapters, delivery audit, and scoped memory writeback.

**Tech Stack:** FastAPI, psycopg/PostgreSQL, Redis stream enqueue, existing private event and pipeline modules, Composio/Gmail API abstraction, WhatsApp Cloud API abstraction, Android Java UI, pytest, JUnit.

---

## Implementation Status - 2026-06-04

Local implementation and verification are complete for Tasks 1-10 plus the local semantic portion of Task 11:

- Backend schema, default identity registry, contact resolver, inbox gateway, private-event source scoping, outbound draft-confirm-send pipeline, provider adapter contracts, fake Gmail/WhatsApp adapters, trigger routing, tool registry integration, and API endpoints are implemented.
- Android identity models, draft model, API client parsing, and account-list UI rows are implemented and covered by unit tests.
- Local semantic regression is implemented in `scripts/assistant-identity-regression.py` and reported in `docs/superpowers/reports/2026-06-04-assistant-owned-identities-regression.md`.
- Open gaps remain for real Nomi Gmail watch/send provider validation, real WhatsApp Cloud API webhook/send provider validation, and Android live device validation of the new identity/draft UI. These are tracked in `docs/superpowers/reports/2026-06-04-nomi-owned-communication-identities-gaps.md`.

---

## Design Source

Implement against:

- `docs/superpowers/specs/2026-06-04-nomi-owned-communication-identities-design.md`
- `docs/superpowers/specs/2026-05-28-private-event-processing-agenda-design.md`
- `docs/superpowers/specs/2026-05-28-core-pipelines-openclaw-design.md`
- `docs/superpowers/specs/2026-05-28-composio-connect-link-integration.md`

## File Map

### Server Files

- Create: `runtime_api/app/assistant_identity/__init__.py`
- Create: `runtime_api/app/assistant_identity/schema.py`
- Create: `runtime_api/app/assistant_identity/models.py`
- Create: `runtime_api/app/assistant_identity/registry.py`
- Create: `runtime_api/app/assistant_identity/contact_resolver.py`
- Create: `runtime_api/app/assistant_identity/inbox_gateway.py`
- Create: `runtime_api/app/assistant_identity/routing.py`
- Create: `runtime_api/app/assistant_identity/outbound.py`
- Create: `runtime_api/app/assistant_identity/adapters.py`
- Create: `runtime_api/app/assistant_identity/gmail_adapter.py`
- Create: `runtime_api/app/assistant_identity/whatsapp_adapter.py`
- Create: `runtime_api/app/assistant_identity/api.py`
- Modify: `runtime_api/app/main.py`
- Modify: `runtime_api/app/private_events.py`
- Modify: `runtime_api/app/tool_registry.py`
- Modify: `runtime_api/app/pipelines/communication.py`
- Modify: `.env.example`

### Android Files

- Modify: `android_app/app/src/main/java/com/par/assistant/android/AssistantApiClient.java`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/FloatingBallService.java`
- Create: `android_app/app/src/main/java/com/par/assistant/android/AssistantIdentity.java`
- Create: `android_app/app/src/main/java/com/par/assistant/android/AssistantDraft.java`

### Test Files

- Create: `runtime_api/tests/test_assistant_identity_schema.py`
- Create: `runtime_api/tests/test_assistant_identity_registry.py`
- Create: `runtime_api/tests/test_assistant_inbox_gateway.py`
- Create: `runtime_api/tests/test_assistant_trigger_routing.py`
- Create: `runtime_api/tests/test_assistant_outbound_pipeline.py`
- Create: `runtime_api/tests/test_assistant_gmail_adapter.py`
- Create: `runtime_api/tests/test_assistant_whatsapp_adapter.py`
- Create: `runtime_api/tests/test_assistant_identity_api.py`
- Create: `runtime_api/tests/test_assistant_identity_memory_scope.py`
- Create: `android_app/app/src/test/java/com/par/assistant/android/AssistantIdentityUiTest.java`

## Task 1: Schema And Bootstrap

**Files:**
- Create: `runtime_api/app/assistant_identity/schema.py`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_assistant_identity_schema.py`

- [ ] **Step 1: Write failing schema tests**

Create `runtime_api/tests/test_assistant_identity_schema.py`:

```python
from app.assistant_identity.schema import assistant_identity_schema_sql


def test_assistant_identity_schema_contains_required_tables():
    sql = "\n".join(assistant_identity_schema_sql())

    assert "CREATE TABLE IF NOT EXISTS assistant_identities" in sql
    assert "CREATE TABLE IF NOT EXISTS assistant_identity_credentials" in sql
    assert "CREATE TABLE IF NOT EXISTS assistant_inbox_events" in sql
    assert "CREATE TABLE IF NOT EXISTS assistant_message_drafts" in sql
    assert "CREATE TABLE IF NOT EXISTS assistant_outbound_messages" in sql
    assert "CREATE TABLE IF NOT EXISTS assistant_delivery_receipts" in sql
    assert "CREATE TABLE IF NOT EXISTS assistant_contact_bindings" in sql
    assert "CREATE TABLE IF NOT EXISTS assistant_channel_policies" in sql


def test_assistant_identity_schema_preserves_identity_boundaries():
    sql = "\n".join(assistant_identity_schema_sql())

    assert "kind TEXT NOT NULL" in sql
    assert "provider TEXT NOT NULL" in sql
    assert "identity_id UUID" in sql
    assert "source_event_ids UUID[]" in sql
    assert "third_party_send_requires_confirmation BOOLEAN NOT NULL DEFAULT TRUE" in sql
```

- [ ] **Step 2: Verify red**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_assistant_identity_schema.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'app.assistant_identity'`.

- [ ] **Step 3: Implement schema module**

Create `runtime_api/app/assistant_identity/schema.py`:

```python
from __future__ import annotations


def assistant_identity_schema_sql() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS assistant_identities (
          id UUID PRIMARY KEY,
          kind TEXT NOT NULL,
          display_name TEXT NOT NULL,
          address TEXT NOT NULL,
          provider TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'disabled',
          capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_identity_credentials (
          identity_id UUID PRIMARY KEY REFERENCES assistant_identities(id) ON DELETE CASCADE,
          credential_ref TEXT NOT NULL,
          provider_subject TEXT NOT NULL DEFAULT '',
          expires_at TIMESTAMPTZ,
          last_rotated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_inbox_events (
          id UUID PRIMARY KEY,
          identity_id UUID NOT NULL REFERENCES assistant_identities(id) ON DELETE CASCADE,
          channel TEXT NOT NULL,
          conversation_id TEXT NOT NULL,
          external_message_id TEXT NOT NULL,
          sender_key TEXT NOT NULL,
          classification TEXT NOT NULL,
          normalized_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          private_event_id UUID,
          occurred_at TIMESTAMPTZ NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(identity_id, external_message_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_message_drafts (
          id UUID PRIMARY KEY,
          identity_id UUID NOT NULL REFERENCES assistant_identities(id) ON DELETE CASCADE,
          channel TEXT NOT NULL,
          recipient JSONB NOT NULL DEFAULT '{}'::jsonb,
          subject TEXT NOT NULL DEFAULT '',
          body_text TEXT NOT NULL,
          risk JSONB NOT NULL DEFAULT '{}'::jsonb,
          status TEXT NOT NULL DEFAULT 'draft',
          source_event_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
          created_by_task_id TEXT NOT NULL DEFAULT '',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_outbound_messages (
          id UUID PRIMARY KEY,
          draft_id UUID NOT NULL REFERENCES assistant_message_drafts(id) ON DELETE CASCADE,
          identity_id UUID NOT NULL REFERENCES assistant_identities(id) ON DELETE CASCADE,
          provider_message_id TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'sending',
          provider_response JSONB NOT NULL DEFAULT '{}'::jsonb,
          confirmed_by TEXT NOT NULL DEFAULT '',
          confirmed_at TIMESTAMPTZ,
          sent_at TIMESTAMPTZ
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_delivery_receipts (
          id UUID PRIMARY KEY,
          outbound_message_id UUID REFERENCES assistant_outbound_messages(id) ON DELETE SET NULL,
          identity_id UUID NOT NULL REFERENCES assistant_identities(id) ON DELETE CASCADE,
          channel TEXT NOT NULL,
          provider_message_id TEXT NOT NULL,
          receipt_type TEXT NOT NULL,
          payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          occurred_at TIMESTAMPTZ NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_contact_bindings (
          id UUID PRIMARY KEY,
          channel TEXT NOT NULL,
          external_key_hash TEXT NOT NULL,
          contact_id TEXT NOT NULL,
          trust_level TEXT NOT NULL DEFAULT 'unknown',
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(channel, external_key_hash)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_channel_policies (
          id UUID PRIMARY KEY,
          identity_id UUID NOT NULL REFERENCES assistant_identities(id) ON DELETE CASCADE,
          scope_type TEXT NOT NULL,
          scope_key TEXT NOT NULL DEFAULT '',
          auto_ack_allowed BOOLEAN NOT NULL DEFAULT FALSE,
          third_party_send_requires_confirmation BOOLEAN NOT NULL DEFAULT TRUE,
          style_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    ]
```

Create `runtime_api/app/assistant_identity/__init__.py`:

```python
from app.assistant_identity.schema import assistant_identity_schema_sql

__all__ = ["assistant_identity_schema_sql"]
```

- [ ] **Step 4: Wire bootstrap**

In `runtime_api/app/main.py`, import and run the schema:

```python
from app.assistant_identity import assistant_identity_schema_sql
```

In the existing bootstrap schema function, execute each statement from `assistant_identity_schema_sql()`.

- [ ] **Step 5: Verify green**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_assistant_identity_schema.py -q
```

Expected: `2 passed`.

## Task 2: Data Models And Registry

**Files:**
- Create: `runtime_api/app/assistant_identity/models.py`
- Create: `runtime_api/app/assistant_identity/registry.py`
- Test: `runtime_api/tests/test_assistant_identity_registry.py`

- [ ] **Step 1: Write failing registry tests**

Create `runtime_api/tests/test_assistant_identity_registry.py`:

```python
import uuid

from app.assistant_identity.models import AssistantIdentityIn
from app.assistant_identity.registry import AssistantIdentityRegistry


def test_registry_normalizes_supported_identities():
    registry = AssistantIdentityRegistry()
    identity = registry.normalize(
        AssistantIdentityIn(
            kind="assistant_gmail",
            display_name="Nomi",
            address="nomi@example.com",
            provider="gmail_api",
            capabilities=["receive", "draft", "send"],
        )
    )

    assert identity.kind == "assistant_gmail"
    assert identity.status == "connected"
    assert "send" in identity.capabilities


def test_registry_rejects_user_account_kind():
    registry = AssistantIdentityRegistry()

    try:
        registry.normalize(
            AssistantIdentityIn(
                kind="user_gmail",
                display_name="User",
                address="user@example.com",
                provider="gmail_api",
                capabilities=["send"],
            )
        )
    except ValueError as exc:
        assert "Nomi-owned identity" in str(exc)
    else:
        raise AssertionError("expected user account kind to be rejected")


def test_registry_builds_non_secret_metadata():
    registry = AssistantIdentityRegistry()
    identity = registry.normalize(
        AssistantIdentityIn(
            id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            kind="assistant_whatsapp",
            display_name="Nomi",
            address="+1234567890",
            provider="whatsapp_cloud_api",
            capabilities=["receive", "send_text"],
            metadata={"phone_number_id": "123", "access_token": "secret"},
        )
    )

    assert identity.metadata["phone_number_id"] == "123"
    assert "access_token" not in identity.metadata
```

- [ ] **Step 2: Verify red**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_assistant_identity_registry.py -q
```

Expected: fail because models and registry do not exist.

- [ ] **Step 3: Implement models**

Create `runtime_api/app/assistant_identity/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


SUPPORTED_IDENTITY_KINDS = {"assistant_gmail", "assistant_whatsapp"}
SECRET_METADATA_KEYS = {"access_token", "refresh_token", "client_secret", "webhook_secret", "api_key"}


@dataclass(frozen=True)
class AssistantIdentityIn:
    kind: str
    display_name: str
    address: str
    provider: str
    capabilities: list[str]
    id: uuid.UUID | None = None
    status: str = "connected"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssistantIdentity:
    id: uuid.UUID
    kind: str
    display_name: str
    address: str
    provider: str
    status: str
    capabilities: list[str]
    metadata: dict[str, Any]
    updated_at: datetime
```

- [ ] **Step 4: Implement registry**

Create `runtime_api/app/assistant_identity/registry.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
import uuid

from app.assistant_identity.models import (
    AssistantIdentity,
    AssistantIdentityIn,
    SECRET_METADATA_KEYS,
    SUPPORTED_IDENTITY_KINDS,
)


class AssistantIdentityRegistry:
    def normalize(self, identity: AssistantIdentityIn) -> AssistantIdentity:
        kind = identity.kind.strip().lower()
        if kind not in SUPPORTED_IDENTITY_KINDS:
            raise ValueError("Only Nomi-owned identity kinds are allowed.")
        display_name = identity.display_name.strip() or "Nomi"
        address = identity.address.strip()
        if not address:
            raise ValueError("Assistant identity address is required.")
        provider = identity.provider.strip().lower()
        if not provider:
            raise ValueError("Assistant identity provider is required.")
        metadata = {
            key: value
            for key, value in identity.metadata.items()
            if key.lower() not in SECRET_METADATA_KEYS
        }
        return AssistantIdentity(
            id=identity.id or uuid.uuid4(),
            kind=kind,
            display_name=display_name,
            address=address,
            provider=provider,
            status=identity.status.strip().lower() or "connected",
            capabilities=sorted({item.strip() for item in identity.capabilities if item.strip()}),
            metadata=metadata,
            updated_at=datetime.now(timezone.utc),
        )
```

- [ ] **Step 5: Verify green**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_assistant_identity_registry.py -q
```

Expected: `3 passed`.

## Task 3: Contact Resolver And Inbound Classification

**Files:**
- Create: `runtime_api/app/assistant_identity/contact_resolver.py`
- Create: `runtime_api/app/assistant_identity/inbox_gateway.py`
- Test: `runtime_api/tests/test_assistant_inbox_gateway.py`

- [ ] **Step 1: Write failing inbox tests**

Create `runtime_api/tests/test_assistant_inbox_gateway.py`:

```python
from app.assistant_identity.contact_resolver import ContactResolver
from app.assistant_identity.inbox_gateway import AssistantInboxGateway


def test_user_email_to_nomi_becomes_direct_command():
    resolver = ContactResolver(user_emails={"owner@example.com"}, user_phones=set(), known_contacts={})
    gateway = AssistantInboxGateway(resolver)

    event = gateway.normalize_gmail(
        identity_id="nomi_gmail_primary",
        message={
            "id": "msg-1",
            "thread_id": "thr-1",
            "from": "owner@example.com",
            "to": ["nomi@example.com"],
            "subject": "Nomi",
            "body": "帮我总结今天的邮件",
            "date": "2026-06-04T12:00:00Z",
        },
    )

    assert event["classification"] == "user_direct_command"
    assert event["source_type"] == "assistant_gmail"
    assert event["visibility_scope"] == "assistant_channel_user_direct"


def test_known_external_whatsapp_sender_becomes_external_contact_message():
    resolver = ContactResolver(
        user_emails=set(),
        user_phones={"+111"},
        known_contacts={"+222": "contact_maya"},
    )
    gateway = AssistantInboxGateway(resolver)

    event = gateway.normalize_whatsapp(
        identity_id="nomi_whatsapp_primary",
        payload={
            "wamid": "wamid.1",
            "from": "+222",
            "text": "请转告张子长，会议改到周五。",
            "timestamp": "1780580000",
        },
    )

    assert event["classification"] == "external_contact_message"
    assert event["counterparty_ids"] == ["contact_maya"]
    assert event["visibility_scope"] == "assistant_channel_external_contact"


def test_delivery_status_does_not_become_user_command():
    gateway = AssistantInboxGateway(ContactResolver(set(), set(), {}))

    event = gateway.normalize_whatsapp(
        identity_id="nomi_whatsapp_primary",
        payload={"status": "delivered", "wamid": "wamid.1", "timestamp": "1780580000"},
    )

    assert event["classification"] == "provider_status"
    assert event["event_type"] == "assistant_delivery_status"
```

- [ ] **Step 2: Verify red**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_assistant_inbox_gateway.py -q
```

Expected: fail because resolver and gateway do not exist.

- [ ] **Step 3: Implement contact resolver**

Create `runtime_api/app/assistant_identity/contact_resolver.py`:

```python
from __future__ import annotations

import hashlib


class ContactResolver:
    def __init__(self, user_emails: set[str], user_phones: set[str], known_contacts: dict[str, str]) -> None:
        self.user_emails = {item.strip().lower() for item in user_emails}
        self.user_phones = {self.normalize_phone(item) for item in user_phones}
        self.known_contacts = {
            self.normalize_key(key): value
            for key, value in known_contacts.items()
        }

    def classify_sender(self, value: str) -> dict[str, object]:
        normalized = self.normalize_key(value)
        if normalized in self.user_emails or normalized in self.user_phones:
            return {"sender_class": "user", "counterparty_ids": [], "sender_key": normalized}
        if normalized in self.known_contacts:
            return {
                "sender_class": "known_contact",
                "counterparty_ids": [self.known_contacts[normalized]],
                "sender_key": normalized,
            }
        return {"sender_class": "unknown", "counterparty_ids": [], "sender_key": self.hash_key(normalized)}

    def normalize_key(self, value: str) -> str:
        text = (value or "").strip().lower()
        if "@" in text:
            return text
        return self.normalize_phone(text)

    def normalize_phone(self, value: str) -> str:
        return "".join(ch for ch in (value or "").strip() if ch == "+" or ch.isdigit())

    def hash_key(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Implement inbox gateway**

Create `runtime_api/app/assistant_identity/inbox_gateway.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.assistant_identity.contact_resolver import ContactResolver


class AssistantInboxGateway:
    def __init__(self, resolver: ContactResolver) -> None:
        self.resolver = resolver

    def normalize_gmail(self, identity_id: str, message: dict[str, Any]) -> dict[str, Any]:
        sender = str(message.get("from") or "")
        resolved = self.resolver.classify_sender(sender)
        classification = self._message_classification(str(resolved["sender_class"]))
        return {
            "source_type": "assistant_gmail",
            "source_account_id": identity_id,
            "assistant_identity_id": identity_id,
            "event_type": "assistant_email_received",
            "conversation_id": str(message.get("thread_id") or ""),
            "external_message_id": str(message.get("id") or ""),
            "sender_key": resolved["sender_key"],
            "counterparty_ids": resolved["counterparty_ids"],
            "classification": classification,
            "visibility_scope": self._visibility_scope(classification),
            "normalized_text": str(message.get("body") or message.get("snippet") or ""),
            "normalized_payload": {
                "subject": str(message.get("subject") or ""),
                "from": sender,
                "to": message.get("to") or [],
                "body_text": str(message.get("body") or ""),
            },
            "occurred_at": str(message.get("date") or datetime.now(timezone.utc).isoformat()),
        }

    def normalize_whatsapp(self, identity_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if "status" in payload:
            return {
                "source_type": "assistant_whatsapp",
                "source_account_id": identity_id,
                "assistant_identity_id": identity_id,
                "event_type": "assistant_delivery_status",
                "conversation_id": str(payload.get("wamid") or ""),
                "external_message_id": str(payload.get("wamid") or ""),
                "sender_key": "",
                "counterparty_ids": [],
                "classification": "provider_status",
                "visibility_scope": "provider_status",
                "normalized_text": str(payload.get("status") or ""),
                "normalized_payload": payload,
                "occurred_at": str(payload.get("timestamp") or ""),
            }
        sender = str(payload.get("from") or "")
        resolved = self.resolver.classify_sender(sender)
        classification = self._message_classification(str(resolved["sender_class"]))
        return {
            "source_type": "assistant_whatsapp",
            "source_account_id": identity_id,
            "assistant_identity_id": identity_id,
            "event_type": "assistant_whatsapp_message_received",
            "conversation_id": "whatsapp:" + str(resolved["sender_key"]),
            "external_message_id": str(payload.get("wamid") or ""),
            "sender_key": resolved["sender_key"],
            "counterparty_ids": resolved["counterparty_ids"],
            "classification": classification,
            "visibility_scope": self._visibility_scope(classification),
            "normalized_text": str(payload.get("text") or ""),
            "normalized_payload": payload,
            "occurred_at": str(payload.get("timestamp") or ""),
        }

    def _message_classification(self, sender_class: str) -> str:
        if sender_class == "user":
            return "user_direct_command"
        if sender_class == "known_contact":
            return "external_contact_message"
        return "unknown_sender"

    def _visibility_scope(self, classification: str) -> str:
        if classification == "user_direct_command":
            return "assistant_channel_user_direct"
        if classification == "external_contact_message":
            return "assistant_channel_external_contact"
        if classification == "provider_status":
            return "provider_status"
        return "assistant_channel_unknown_sender"
```

- [ ] **Step 5: Verify green**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_assistant_inbox_gateway.py -q
```

Expected: `3 passed`.

## Task 4: Persist Inbound Events Into Private Event Gateway

**Files:**
- Modify: `runtime_api/app/private_events.py`
- Create: `runtime_api/app/assistant_identity/api.py`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_assistant_identity_memory_scope.py`

- [ ] **Step 1: Write failing memory scope tests**

Create `runtime_api/tests/test_assistant_identity_memory_scope.py`:

```python
from app.assistant_identity.inbox_gateway import AssistantInboxGateway
from app.assistant_identity.contact_resolver import ContactResolver


def test_assistant_owned_event_keeps_separate_scope_from_user_collectors():
    gateway = AssistantInboxGateway(ContactResolver({"owner@example.com"}, set(), {}))
    event = gateway.normalize_gmail(
        "nomi_gmail_primary",
        {
            "id": "msg-1",
            "thread_id": "thr-1",
            "from": "owner@example.com",
            "to": ["nomi@example.com"],
            "subject": "Nomi",
            "body": "帮我查一下 Alice 的报价",
            "date": "2026-06-04T12:00:00Z",
        },
    )

    assert event["source_type"] == "assistant_gmail"
    assert event["source_account_id"] == "nomi_gmail_primary"
    assert event["visibility_scope"] == "assistant_channel_user_direct"
    assert event["source_type"] != "gmail"
```

- [ ] **Step 2: Verify red**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_assistant_identity_memory_scope.py -q
```

Expected: fail until Task 3 modules exist.

- [ ] **Step 3: Add source types to private event validation**

In `runtime_api/app/private_events.py`, add accepted source types:

```python
ASSISTANT_OWNED_SOURCE_TYPES = {
    "assistant_gmail",
    "assistant_whatsapp",
}
```

Make source validation accept existing source types plus `ASSISTANT_OWNED_SOURCE_TYPES`.

- [ ] **Step 4: Add API ingestion helpers**

Create API helpers in `runtime_api/app/assistant_identity/api.py`:

```python
from __future__ import annotations

from typing import Any

from app.assistant_identity.contact_resolver import ContactResolver
from app.assistant_identity.inbox_gateway import AssistantInboxGateway


def build_default_assistant_inbox_gateway() -> AssistantInboxGateway:
    return AssistantInboxGateway(ContactResolver(user_emails=set(), user_phones=set(), known_contacts={}))


def normalized_assistant_event_to_private_payload(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": event["source_type"],
        "event_type": event["event_type"],
        "raw_data": {
            **event["normalized_payload"],
            "assistant_identity_id": event["assistant_identity_id"],
            "classification": event["classification"],
            "visibility_scope": event["visibility_scope"],
            "conversation_id": event["conversation_id"],
            "external_message_id": event["external_message_id"],
            "counterparty_ids": event["counterparty_ids"],
            "normalized_text": event["normalized_text"],
        },
    }
```

- [ ] **Step 5: Verify green**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_assistant_identity_memory_scope.py tests/test_assistant_inbox_gateway.py -q
```

Expected: all tests pass.

## Task 5: Outbound Draft And Confirmation Pipeline

**Files:**
- Create: `runtime_api/app/assistant_identity/outbound.py`
- Modify: `runtime_api/app/pipelines/communication.py`
- Test: `runtime_api/tests/test_assistant_outbound_pipeline.py`

- [ ] **Step 1: Write failing outbound tests**

Create `runtime_api/tests/test_assistant_outbound_pipeline.py`:

```python
from app.assistant_identity.outbound import OutboundMessagePipeline


def test_third_party_email_request_creates_draft_not_send():
    pipeline = OutboundMessagePipeline()

    draft = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient={"email": "alice@example.com", "contact_id": "contact_alice"},
        subject="明天会议资料",
        body_text="我是 Nomi，张子长的个人助理。明天会议资料已整理。",
        source_event_ids=["00000000-0000-0000-0000-000000000001"],
    )

    assert draft["status"] == "draft"
    assert draft["confirmation_required"] is True
    assert draft["send_called"] is False
    assert draft["confirmation_card"]["identity_id"] == "nomi_gmail_primary"


def test_cancelled_draft_never_calls_provider():
    pipeline = OutboundMessagePipeline()
    draft = pipeline.prepare_draft(
        identity_id="nomi_whatsapp_primary",
        channel="whatsapp",
        recipient={"phone": "+222", "contact_id": "contact_maya"},
        subject="",
        body_text="我是 Nomi，张子长的个人助理。收到你的消息。",
        source_event_ids=[],
    )

    cancelled = pipeline.cancel_draft(draft["draft_id"])

    assert cancelled["status"] == "cancelled"
    assert cancelled["send_called"] is False


def test_send_requires_explicit_confirmation_token():
    pipeline = OutboundMessagePipeline()
    draft = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient={"email": "alice@example.com"},
        subject="test",
        body_text="我是 Nomi。",
        source_event_ids=[],
    )

    try:
        pipeline.confirm_and_send(draft["draft_id"], confirmation_token="")
    except PermissionError as exc:
        assert "confirmation" in str(exc).lower()
    else:
        raise AssertionError("expected confirmation to be required")
```

- [ ] **Step 2: Verify red**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_assistant_outbound_pipeline.py -q
```

Expected: fail because outbound module does not exist.

- [ ] **Step 3: Implement outbound pipeline shell**

Create `runtime_api/app/assistant_identity/outbound.py`:

```python
from __future__ import annotations

import uuid


class OutboundMessagePipeline:
    def __init__(self) -> None:
        self._drafts: dict[str, dict] = {}

    def prepare_draft(
        self,
        *,
        identity_id: str,
        channel: str,
        recipient: dict,
        subject: str,
        body_text: str,
        source_event_ids: list[str],
    ) -> dict:
        draft_id = str(uuid.uuid4())
        draft = {
            "draft_id": draft_id,
            "identity_id": identity_id,
            "channel": channel,
            "recipient": recipient,
            "subject": subject,
            "body_text": body_text,
            "source_event_ids": source_event_ids,
            "status": "draft",
            "confirmation_required": True,
            "send_called": False,
            "confirmation_card": {
                "identity_id": identity_id,
                "channel": channel,
                "recipient": recipient,
                "subject": subject,
                "body_preview": body_text[:500],
                "actions": ["send", "edit", "cancel"],
            },
        }
        self._drafts[draft_id] = draft
        return draft

    def cancel_draft(self, draft_id: str) -> dict:
        draft = self._drafts[draft_id]
        draft["status"] = "cancelled"
        draft["send_called"] = False
        return draft

    def confirm_and_send(self, draft_id: str, confirmation_token: str) -> dict:
        if not confirmation_token:
            raise PermissionError("Explicit confirmation is required before sending.")
        draft = self._drafts[draft_id]
        draft["status"] = "confirmed"
        draft["send_called"] = True
        return draft
```

- [ ] **Step 4: Integrate communication pipeline**

Update `runtime_api/app/pipelines/communication.py` so `reply_pipeline` and `email_pipeline` can return an assistant-owned outbound draft when context asks for `sender_identity="nomi"` or `assistant_identity_id`.

The structured result must include:

```json
{
  "status": "draft_ready",
  "external_effect": "assistant_outbound_message",
  "confirmation_required": true,
  "assistant_identity_id": "nomi_gmail_primary",
  "draft": {
    "channel": "gmail",
    "recipient": {"email": "alice@example.com"},
    "subject": "明天会议资料",
    "body_text": "我是 Nomi，张子长的个人助理。..."
  }
}
```

- [ ] **Step 5: Verify green**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_assistant_outbound_pipeline.py -q
```

Expected: `3 passed`.

## Task 6: Gmail Adapter

**Files:**
- Create: `runtime_api/app/assistant_identity/adapters.py`
- Create: `runtime_api/app/assistant_identity/gmail_adapter.py`
- Test: `runtime_api/tests/test_assistant_gmail_adapter.py`

- [ ] **Step 1: Write failing Gmail adapter tests**

Create `runtime_api/tests/test_assistant_gmail_adapter.py`:

```python
from app.assistant_identity.gmail_adapter import GmailMimeBuilder, FakeAssistantGmailAdapter


def test_mime_builder_marks_nomi_identity_and_base64url_encodes():
    raw = GmailMimeBuilder().build_raw_message(
        sender="nomi@example.com",
        recipient="alice@example.com",
        subject="明天会议资料",
        body_text="我是 Nomi，张子长的个人助理。",
    )

    assert "\n" not in raw
    assert raw.endswith("=") is False


def test_fake_gmail_adapter_records_send_without_real_provider():
    adapter = FakeAssistantGmailAdapter()

    result = adapter.send_message(
        sender="nomi@example.com",
        recipient="alice@example.com",
        subject="测试",
        body_text="我是 Nomi。",
        thread_id="",
    )

    assert result["status"] == "sent"
    assert result["provider_message_id"].startswith("fake-gmail-")
    assert adapter.sent_messages[0]["recipient"] == "alice@example.com"
```

- [ ] **Step 2: Verify red**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_assistant_gmail_adapter.py -q
```

Expected: fail because Gmail adapter does not exist.

- [ ] **Step 3: Implement adapter interfaces**

Create `runtime_api/app/assistant_identity/adapters.py`:

```python
from __future__ import annotations

from typing import Protocol


class AssistantOutboundAdapter(Protocol):
    def send_message(self, **kwargs) -> dict:
        ...
```

Create `runtime_api/app/assistant_identity/gmail_adapter.py`:

```python
from __future__ import annotations

import base64
from email.message import EmailMessage
import uuid


class GmailMimeBuilder:
    def build_raw_message(self, sender: str, recipient: str, subject: str, body_text: str) -> str:
        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body_text)
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        return encoded.rstrip("=")


class FakeAssistantGmailAdapter:
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []

    def send_message(self, *, sender: str, recipient: str, subject: str, body_text: str, thread_id: str = "") -> dict:
        payload = {
            "sender": sender,
            "recipient": recipient,
            "subject": subject,
            "body_text": body_text,
            "thread_id": thread_id,
        }
        self.sent_messages.append(payload)
        return {
            "status": "sent",
            "provider": "fake_gmail",
            "provider_message_id": "fake-gmail-" + str(uuid.uuid4()),
            "payload": payload,
        }
```

- [ ] **Step 4: Verify green**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_assistant_gmail_adapter.py -q
```

Expected: `2 passed`.

## Task 7: WhatsApp Cloud Adapter

**Files:**
- Create: `runtime_api/app/assistant_identity/whatsapp_adapter.py`
- Test: `runtime_api/tests/test_assistant_whatsapp_adapter.py`

- [ ] **Step 1: Write failing WhatsApp tests**

Create `runtime_api/tests/test_assistant_whatsapp_adapter.py`:

```python
from app.assistant_identity.whatsapp_adapter import WhatsAppWebhookVerifier, FakeAssistantWhatsAppAdapter


def test_webhook_verifier_accepts_matching_token():
    verifier = WhatsAppWebhookVerifier(verify_token="local-token")

    challenge = verifier.verify(mode="subscribe", token="local-token", challenge="12345")

    assert challenge == "12345"


def test_webhook_verifier_rejects_wrong_token():
    verifier = WhatsAppWebhookVerifier(verify_token="local-token")

    try:
        verifier.verify(mode="subscribe", token="wrong", challenge="12345")
    except PermissionError as exc:
        assert "verify token" in str(exc).lower()
    else:
        raise AssertionError("expected token rejection")


def test_fake_whatsapp_adapter_sends_text():
    adapter = FakeAssistantWhatsAppAdapter()

    result = adapter.send_text(phone_number_id="phone-1", to="+222", body_text="我是 Nomi。")

    assert result["status"] == "sent"
    assert result["provider_message_id"].startswith("fake-whatsapp-")
    assert adapter.sent_messages[0]["to"] == "+222"
```

- [ ] **Step 2: Verify red**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_assistant_whatsapp_adapter.py -q
```

Expected: fail because WhatsApp adapter does not exist.

- [ ] **Step 3: Implement WhatsApp adapter**

Create `runtime_api/app/assistant_identity/whatsapp_adapter.py`:

```python
from __future__ import annotations

import uuid


class WhatsAppWebhookVerifier:
    def __init__(self, verify_token: str) -> None:
        self.verify_token = verify_token

    def verify(self, *, mode: str, token: str, challenge: str) -> str:
        if mode != "subscribe" or token != self.verify_token:
            raise PermissionError("WhatsApp webhook verify token mismatch.")
        return challenge


class FakeAssistantWhatsAppAdapter:
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []

    def send_text(self, *, phone_number_id: str, to: str, body_text: str) -> dict:
        payload = {"phone_number_id": phone_number_id, "to": to, "body_text": body_text}
        self.sent_messages.append(payload)
        return {
            "status": "sent",
            "provider": "fake_whatsapp",
            "provider_message_id": "fake-whatsapp-" + str(uuid.uuid4()),
            "payload": payload,
        }
```

- [ ] **Step 4: Verify green**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_assistant_whatsapp_adapter.py -q
```

Expected: `3 passed`.

## Task 8: API Endpoints

**Files:**
- Create: `runtime_api/app/assistant_identity/api.py`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_assistant_identity_api.py`

- [ ] **Step 1: Write failing API tests**

Create `runtime_api/tests/test_assistant_identity_api.py`:

```python
from fastapi.testclient import TestClient

from app.main import app


def test_assistant_identities_requires_password():
    client = TestClient(app)

    response = client.get("/api/assistant-identities")

    assert response.status_code in {401, 403}


def test_whatsapp_webhook_verification_returns_challenge(monkeypatch):
    monkeypatch.setenv("ASSISTANT_WHATSAPP_VERIFY_TOKEN", "local-token")
    client = TestClient(app)

    response = client.get(
        "/api/assistant-inbox/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "local-token",
            "hub.challenge": "12345",
        },
    )

    assert response.status_code == 200
    assert response.text == "12345"
```

- [ ] **Step 2: Verify red**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_assistant_identity_api.py -q
```

Expected: fail because endpoints do not exist.

- [ ] **Step 3: Implement router**

Create endpoint handlers in `runtime_api/app/assistant_identity/api.py`:

```python
from __future__ import annotations

import os
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.assistant_identity.whatsapp_adapter import WhatsAppWebhookVerifier

router = APIRouter()


@router.get("/api/assistant-inbox/whatsapp/webhook", response_class=PlainTextResponse)
def verify_whatsapp_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> PlainTextResponse:
    verifier = WhatsAppWebhookVerifier(os.getenv("ASSISTANT_WHATSAPP_VERIFY_TOKEN", ""))
    try:
        return PlainTextResponse(verifier.verify(mode=hub_mode, token=hub_verify_token, challenge=hub_challenge))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
```

In `runtime_api/app/main.py`, include the router and protect identity listing with existing password checks:

```python
from app.assistant_identity.api import router as assistant_identity_router

app.include_router(assistant_identity_router)
```

Add `GET /api/assistant-identities` using the existing `require_password` helper.

- [ ] **Step 4: Verify green**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_assistant_identity_api.py -q
```

Expected: tests pass.

## Task 9: Trigger Routing, Tool Registry, And Pipeline Boundary

**Files:**
- Create: `runtime_api/app/assistant_identity/routing.py`
- Modify: `runtime_api/app/tool_registry.py`
- Modify: `runtime_api/app/pipelines/communication.py`
- Test: `runtime_api/tests/test_assistant_trigger_routing.py`
- Test: `runtime_api/tests/test_tool_registry.py`
- Test: `runtime_api/tests/test_assistant_outbound_pipeline.py`

- [ ] **Step 1: Write failing trigger router tests**

Create `runtime_api/tests/test_assistant_trigger_routing.py`:

```python
from app.assistant_identity.routing import AssistantCommunicationTriggerRouter


def test_explicit_nomi_gmail_send_routes_to_core_pipeline_not_agent():
    router = AssistantCommunicationTriggerRouter()

    decision = router.route(
        {
            "trigger_source": "user_explicit_send_request",
            "text": "用 Nomi 自己的邮箱给 Alice 发邮件，说我下午到",
            "channel_hint": "gmail",
            "recipient_hint": "Alice",
            "source_evidence_ids": ["private_event_1"],
        }
    )

    assert decision["route_type"] == "core_pipeline"
    assert decision["pipeline_id"] == "reply_pipeline"
    assert decision["capability_id"] == "assistant.email.send"
    assert decision["confirmation_required"] is True
    assert decision["agent_allowed"] is False
    assert "draft" in decision["allowed_effects"]
    assert "send_without_confirmation" in decision["forbidden_effects"]


def test_explicit_nomi_whatsapp_send_routes_to_core_pipeline_not_agent():
    router = AssistantCommunicationTriggerRouter()

    decision = router.route(
        {
            "trigger_source": "user_explicit_send_request",
            "text": "让 Nomi 用 WhatsApp 告诉 Maya 我晚点到",
            "channel_hint": "whatsapp",
            "recipient_hint": "Maya",
            "source_evidence_ids": ["private_event_2"],
        }
    )

    assert decision["route_type"] == "core_pipeline"
    assert decision["pipeline_id"] == "reply_pipeline"
    assert decision["capability_id"] == "assistant.whatsapp.send"
    assert decision["confirmation_required"] is True
    assert decision["agent_allowed"] is False


def test_proactive_suggestion_action_routes_to_core_pipeline_after_user_click():
    router = AssistantCommunicationTriggerRouter()

    decision = router.route(
        {
            "trigger_source": "proactive_suggestion_action",
            "text": "帮我回复这个客户，告诉他报价单晚上发",
            "channel_hint": "gmail",
            "recipient_hint": "client_42",
            "source_evidence_ids": ["assistant_inbox_event_1"],
        }
    )

    assert decision["route_type"] == "core_pipeline"
    assert decision["capability_id"] == "assistant.email.send"
    assert decision["confirmation_required"] is True
    assert decision["reason"].startswith("User selected")


def test_external_contact_message_does_not_auto_reply():
    router = AssistantCommunicationTriggerRouter()

    decision = router.route(
        {
            "trigger_source": "external_contact_message",
            "text": "你让张子长尽快给我回电话",
            "sender_class": "known_contact",
            "source_evidence_ids": ["assistant_inbox_event_2"],
        }
    )

    assert decision["route_type"] == "none"
    assert decision["pipeline_id"] == "proactive_suggestion_pipeline"
    assert decision["capability_id"] == "assistant.inbox.read"
    assert decision["confirmation_required"] is False
    assert decision["allowed_effects"] == ["store", "summarize", "notify_user_if_relevant"]
    assert "auto_reply" in decision["forbidden_effects"]


def test_long_tail_goal_routes_to_agent_but_only_allows_draft_tool():
    router = AssistantCommunicationTriggerRouter()

    decision = router.route(
        {
            "trigger_source": "user_direct_command",
            "text": "帮我分析这个客户之前的邮件、找出最合适的回复策略，然后让 Nomi 写一封邮件",
            "channel_hint": "gmail",
            "recipient_hint": "client_42",
            "source_evidence_ids": ["private_event_3", "memory_fact_9"],
        }
    )

    assert decision["route_type"] == "agent"
    assert decision["agent_allowed"] is True
    assert decision["agent_allowed_tools"] == ["assistant.outbound.create_draft"]
    assert decision["confirmation_required"] is True
    assert "gmail.messages.send" in decision["forbidden_provider_tools"]
    assert "whatsapp.messages.send" in decision["forbidden_provider_tools"]
    assert "deterministic pipeline was insufficient" in decision["reason"]


def test_agent_outbound_intent_returns_to_deterministic_draft_pipeline():
    router = AssistantCommunicationTriggerRouter()

    decision = router.route(
        {
            "trigger_source": "agent_outbound_request",
            "text": "assistant_outbound_intent: email Alice with final summary",
            "channel_hint": "gmail",
            "recipient_hint": "Alice",
            "source_evidence_ids": ["agent_checkpoint_4"],
        }
    )

    assert decision["route_type"] == "core_pipeline"
    assert decision["pipeline_id"] == "outbound_message_pipeline"
    assert decision["capability_id"] == "assistant.outbound.create_draft"
    assert decision["agent_allowed"] is False
    assert decision["confirmation_required"] is True


def test_provider_status_has_no_outbound_route():
    router = AssistantCommunicationTriggerRouter()

    decision = router.route(
        {
            "trigger_source": "provider_status",
            "text": "whatsapp delivered wamid.123",
            "source_evidence_ids": ["receipt_1"],
        }
    )

    assert decision["route_type"] == "none"
    assert decision["pipeline_id"] == "delivery_state_pipeline"
    assert decision["allowed_effects"] == ["update_state"]
    assert decision["confirmation_required"] is False
```

- [ ] **Step 2: Verify red**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_assistant_trigger_routing.py -q
```

Expected: fail because `app.assistant_identity.routing` does not exist.

- [ ] **Step 3: Implement trigger router**

Create `runtime_api/app/assistant_identity/routing.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class TriggerDecision:
    trigger_id: str
    trigger_source: str
    route_type: str
    pipeline_id: str
    capability_id: str
    confirmation_required: bool
    agent_allowed: bool
    reason: str
    allowed_effects: list[str] = field(default_factory=list)
    forbidden_effects: list[str] = field(default_factory=list)
    agent_allowed_tools: list[str] = field(default_factory=list)
    forbidden_provider_tools: list[str] = field(default_factory=list)
    source_evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AssistantCommunicationTriggerRouter:
    LONG_TAIL_HINTS = (
        "分析",
        "策略",
        "规划",
        "协调",
        "找出",
        "比较",
        "先",
        "整理后",
        "复杂",
    )

    PROVIDER_SEND_TOOLS = (
        "gmail.messages.send",
        "gmail.drafts.send",
        "whatsapp.messages.send",
        "composio.gmail.send",
        "composio.whatsapp.send",
    )

    def route(self, trigger: dict[str, Any]) -> dict[str, Any]:
        source = str(trigger.get("trigger_source") or "unknown")
        text = str(trigger.get("text") or "")
        channel_hint = str(trigger.get("channel_hint") or "").lower()
        evidence = [str(value) for value in trigger.get("source_evidence_ids", [])]

        if source == "provider_status":
            return self._decision(
                source=source,
                route_type="none",
                pipeline_id="delivery_state_pipeline",
                capability_id="assistant.delivery.update",
                confirmation_required=False,
                agent_allowed=False,
                reason="Provider status events only update delivery or sync state.",
                allowed_effects=["update_state"],
                forbidden_effects=["draft", "send", "auto_reply"],
                evidence=evidence,
            )

        if source in {"external_contact_message", "unknown_sender", "noise_or_spam"}:
            return self._decision(
                source=source,
                route_type="none",
                pipeline_id="proactive_suggestion_pipeline",
                capability_id="assistant.inbox.read",
                confirmation_required=False,
                agent_allowed=False,
                reason="Inbound external or low-trust messages are stored and surfaced to the user before any reply.",
                allowed_effects=["store", "summarize", "notify_user_if_relevant"],
                forbidden_effects=["auto_reply", "send_without_confirmation"],
                evidence=evidence,
            )

        if source == "agent_outbound_request":
            return self._decision(
                source=source,
                route_type="core_pipeline",
                pipeline_id="outbound_message_pipeline",
                capability_id="assistant.outbound.create_draft",
                confirmation_required=True,
                agent_allowed=False,
                reason="Agent-produced outbound intent must return to the deterministic draft pipeline.",
                allowed_effects=["draft"],
                forbidden_effects=["send_without_confirmation"],
                evidence=evidence,
            )

        if source in {"user_explicit_send_request", "proactive_suggestion_action"}:
            capability_id = self._capability_for(channel_hint, text)
            return self._decision(
                source=source,
                route_type="core_pipeline",
                pipeline_id="reply_pipeline",
                capability_id=capability_id,
                confirmation_required=True,
                agent_allowed=False,
                reason=self._core_reason(source, capability_id),
                allowed_effects=["draft"],
                forbidden_effects=["send_without_confirmation", "delete", "archive", "block"],
                evidence=evidence,
            )

        if source == "user_direct_command" and self._looks_long_tail(text):
            return self._decision(
                source=source,
                route_type="agent",
                pipeline_id="long_tail_agent_pipeline",
                capability_id="assistant.outbound.create_draft",
                confirmation_required=True,
                agent_allowed=True,
                reason="The deterministic pipeline was insufficient because the request requires planning before drafting.",
                allowed_effects=["plan", "read_scoped_memory", "create_draft"],
                forbidden_effects=["send_without_confirmation", "direct_provider_send"],
                agent_allowed_tools=["assistant.outbound.create_draft"],
                forbidden_provider_tools=list(self.PROVIDER_SEND_TOOLS),
                evidence=evidence,
            )

        capability_id = self._capability_for(channel_hint, text)
        return self._decision(
            source=source,
            route_type="core_pipeline",
            pipeline_id="reply_pipeline",
            capability_id=capability_id,
            confirmation_required=True,
            agent_allowed=False,
            reason="Known communication request resolved by deterministic routing.",
            allowed_effects=["draft"],
            forbidden_effects=["send_without_confirmation"],
            evidence=evidence,
        )

    def _capability_for(self, channel_hint: str, text: str) -> str:
        lower = text.lower()
        if channel_hint == "whatsapp" or "whatsapp" in lower:
            return "assistant.whatsapp.send"
        return "assistant.email.send"

    def _looks_long_tail(self, text: str) -> bool:
        return any(hint in text for hint in self.LONG_TAIL_HINTS)

    def _core_reason(self, source: str, capability_id: str) -> str:
        if source == "proactive_suggestion_action":
            return f"User selected a proactive suggestion; route {capability_id} to draft confirmation."
        return f"Known Nomi-owned communication request; route {capability_id} to draft confirmation."

    def _decision(
        self,
        *,
        source: str,
        route_type: str,
        pipeline_id: str,
        capability_id: str,
        confirmation_required: bool,
        agent_allowed: bool,
        reason: str,
        allowed_effects: list[str],
        forbidden_effects: list[str],
        evidence: list[str],
        agent_allowed_tools: list[str] | None = None,
        forbidden_provider_tools: list[str] | None = None,
    ) -> dict[str, Any]:
        return TriggerDecision(
            trigger_id=str(uuid4()),
            trigger_source=source,
            route_type=route_type,
            pipeline_id=pipeline_id,
            capability_id=capability_id,
            confirmation_required=confirmation_required,
            agent_allowed=agent_allowed,
            reason=reason,
            allowed_effects=allowed_effects,
            forbidden_effects=forbidden_effects,
            agent_allowed_tools=agent_allowed_tools or [],
            forbidden_provider_tools=forbidden_provider_tools or [],
            source_evidence_ids=evidence,
        ).to_dict()
```

- [ ] **Step 4: Verify trigger router green**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_assistant_trigger_routing.py -q
```

Expected: all trigger router tests pass.

- [ ] **Step 5: Write failing capability route tests**

Add to `runtime_api/tests/test_tool_registry.py`:

```python
def test_routes_assistant_owned_email_send_to_confirmation_pipeline():
    from app.tool_registry import default_tool_registry

    route = default_tool_registry(
        connected_adapters={"local": {"assistant_gmail"}}
    ).route_request("用 Nomi 自己的邮箱给 Alice 发邮件")

    assert route["capability_id"] == "assistant.email.send"
    assert route["pipeline_id"] == "reply_pipeline"
    assert route["confirmation_required"] is True
    assert route["permission"] == "external_message"


def test_routes_assistant_owned_whatsapp_send_to_confirmation_pipeline():
    from app.tool_registry import default_tool_registry

    route = default_tool_registry(
        connected_adapters={"local": {"assistant_whatsapp"}}
    ).route_request("让 Nomi 用 WhatsApp 告诉 Maya 我晚点到")

    assert route["capability_id"] == "assistant.whatsapp.send"
    assert route["pipeline_id"] == "reply_pipeline"
    assert route["confirmation_required"] is True
```

- [ ] **Step 6: Verify capability tests red**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest tests/test_tool_registry.py -q
```

Expected: new tests fail because capabilities are not registered.

- [ ] **Step 7: Register capabilities**

In `runtime_api/app/tool_registry.py`, add capabilities:

```python
CapabilityDefinition(
    capability_id="assistant.email.send",
    route_type="core_pipeline",
    pipeline_id="reply_pipeline",
    keywords=("nomi 自己的邮箱", "nomi gmail", "助理邮箱", "用 nomi 发邮件"),
    preferred_adapter="local",
    alternative_adapters=("composio",),
    required_toolkit="assistant_gmail",
    permission="external_message",
    confirmation_required=True,
    reason="Use Nomi-owned Gmail identity; final send requires user confirmation.",
    forbidden_actions=("send_without_confirmation", "delete", "archive"),
)
```

```python
CapabilityDefinition(
    capability_id="assistant.whatsapp.send",
    route_type="core_pipeline",
    pipeline_id="reply_pipeline",
    keywords=("nomi whatsapp", "助理 whatsapp", "用 nomi 发 whatsapp", "用 whatsapp 告诉"),
    preferred_adapter="local",
    alternative_adapters=("openclaw",),
    required_toolkit="assistant_whatsapp",
    permission="external_message",
    confirmation_required=True,
    reason="Use Nomi-owned WhatsApp identity; final send requires user confirmation.",
    forbidden_actions=("send_without_confirmation", "delete", "block"),
)
```

- [ ] **Step 8: Connect communication pipeline to trigger router**

In `runtime_api/app/pipelines/communication.py`, add a helper used by `reply_pipeline` and `email_pipeline` before choosing an adapter:

```python
from __future__ import annotations

from typing import Any

from app.assistant_identity.routing import AssistantCommunicationTriggerRouter


def route_assistant_owned_communication(
    request_text: str,
    *,
    trigger_source: str,
    channel_hint: str = "",
    recipient_hint: str = "",
    source_evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    decision = AssistantCommunicationTriggerRouter().route(
        {
            "trigger_source": trigger_source,
            "text": request_text,
            "channel_hint": channel_hint,
            "recipient_hint": recipient_hint,
            "source_evidence_ids": source_evidence_ids or [],
        }
    )

    if decision["route_type"] == "agent":
        return {
            "status": "agent_required",
            "agent_policy": {
                "allowed_tools": decision["agent_allowed_tools"],
                "forbidden_provider_tools": decision["forbidden_provider_tools"],
                "must_return_to_pipeline": "outbound_message_pipeline",
            },
            "route_decision": decision,
        }

    if decision["route_type"] == "none":
        return {
            "status": "no_outbound_route",
            "route_decision": decision,
        }

    return {
        "status": "draft_route_ready",
        "external_effect": "assistant_outbound_draft",
        "route_decision": decision,
        "confirmation_required": decision["confirmation_required"],
    }
```

Add a focused test to `runtime_api/tests/test_assistant_outbound_pipeline.py`:

```python
def test_communication_pipeline_returns_agent_policy_for_long_tail_request():
    from app.pipelines.communication import route_assistant_owned_communication

    result = route_assistant_owned_communication(
        "帮我分析客户历史邮件，找出回复策略，然后让 Nomi 发邮件",
        trigger_source="user_direct_command",
        channel_hint="gmail",
        recipient_hint="client_42",
        source_evidence_ids=["memory_fact_1"],
    )

    assert result["status"] == "agent_required"
    assert result["agent_policy"]["allowed_tools"] == ["assistant.outbound.create_draft"]
    assert "gmail.messages.send" in result["agent_policy"]["forbidden_provider_tools"]
    assert result["agent_policy"]["must_return_to_pipeline"] == "outbound_message_pipeline"
```

Add a second focused test:

```python
def test_communication_pipeline_returns_draft_route_for_explicit_send_request():
    from app.pipelines.communication import route_assistant_owned_communication

    result = route_assistant_owned_communication(
        "用 Nomi 邮箱给 Alice 发一封邮件",
        trigger_source="user_explicit_send_request",
        channel_hint="gmail",
        recipient_hint="Alice",
        source_evidence_ids=["private_event_7"],
    )

    assert result["status"] == "draft_route_ready"
    assert result["external_effect"] == "assistant_outbound_draft"
    assert result["route_decision"]["capability_id"] == "assistant.email.send"
    assert result["confirmation_required"] is True
```

- [ ] **Step 9: Verify routing and pipeline green**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest \
  tests/test_assistant_trigger_routing.py \
  tests/test_tool_registry.py \
  tests/test_assistant_outbound_pipeline.py \
  -q
```

Expected: all tests pass.

## Task 10: Android Identity And Draft UI

**Files:**
- Create: `android_app/app/src/main/java/com/par/assistant/android/AssistantIdentity.java`
- Create: `android_app/app/src/main/java/com/par/assistant/android/AssistantDraft.java`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/AssistantApiClient.java`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/FloatingBallService.java`
- Test: `android_app/app/src/test/java/com/par/assistant/android/AssistantIdentityUiTest.java`

- [ ] **Step 1: Write failing Android UI tests**

Create `android_app/app/src/test/java/com/par/assistant/android/AssistantIdentityUiTest.java`:

```java
package com.par.assistant.android;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class AssistantIdentityUiTest {
    @Test
    public void identitySubtitleShowsOwnedAssistantBoundary() {
        AssistantIdentity gmail = new AssistantIdentity("nomi_gmail_primary", "assistant_gmail", "Nomi", "nomi@example.com", "connected");

        assertEquals("Nomi Gmail · nomi@example.com · 已连接", gmail.subtitle());
    }

    @Test
    public void draftCardIncludesSendingIdentityRecipientAndActions() {
        AssistantDraft draft = new AssistantDraft(
                "draft-1",
                "Nomi Gmail",
                "Alice",
                "明天会议资料",
                "我是 Nomi，张子长的个人助理。"
        );

        String card = draft.cardText();

        assertTrue(card.contains("将使用：Nomi Gmail"));
        assertTrue(card.contains("收件人：Alice"));
        assertTrue(card.contains("主题：明天会议资料"));
        assertTrue(card.contains("我是 Nomi"));
    }
}
```

- [ ] **Step 2: Verify red**

Run:

```bash
cd /Users/wrf/Documents/background/android_app
JAVA_HOME=/opt/homebrew/opt/openjdk@17 gradle :app:testDebugUnitTest --tests com.par.assistant.android.AssistantIdentityUiTest
```

Expected: fail because classes do not exist.

- [ ] **Step 3: Implement Android models**

Create `AssistantIdentity.java`:

```java
package com.par.assistant.android;

final class AssistantIdentity {
    final String id;
    final String kind;
    final String displayName;
    final String address;
    final String status;

    AssistantIdentity(String id, String kind, String displayName, String address, String status) {
        this.id = id;
        this.kind = kind;
        this.displayName = displayName;
        this.address = address;
        this.status = status;
    }

    String subtitle() {
        String channel = "assistant_whatsapp".equals(kind) ? "Nomi WhatsApp" : "Nomi Gmail";
        String statusLabel = "connected".equals(status) ? "已连接" : "待连接";
        return channel + " · " + address + " · " + statusLabel;
    }
}
```

Create `AssistantDraft.java`:

```java
package com.par.assistant.android;

final class AssistantDraft {
    final String id;
    final String identityLabel;
    final String recipientLabel;
    final String subject;
    final String body;

    AssistantDraft(String id, String identityLabel, String recipientLabel, String subject, String body) {
        this.id = id;
        this.identityLabel = identityLabel;
        this.recipientLabel = recipientLabel;
        this.subject = subject;
        this.body = body;
    }

    String cardText() {
        return "将使用：" + identityLabel
                + "\n收件人：" + recipientLabel
                + (subject == null || subject.isEmpty() ? "" : "\n主题：" + subject)
                + "\n\n" + body;
    }
}
```

- [ ] **Step 4: Add UI routes**

Update `FloatingBallService` settings view with:

- `Nomi 身份`
- Nomi Gmail status row
- Nomi WhatsApp status row
- assistant inbox shortcut
- outbound draft shortcut

Render outbound draft cards in chat using `AssistantDraft.cardText()`.

- [ ] **Step 5: Verify green**

Run:

```bash
cd /Users/wrf/Documents/background/android_app
JAVA_HOME=/opt/homebrew/opt/openjdk@17 gradle :app:testDebugUnitTest --tests com.par.assistant.android.AssistantIdentityUiTest
JAVA_HOME=/opt/homebrew/opt/openjdk@17 gradle :app:testDebugUnitTest :app:assembleDebug
```

Expected: model test passes and APK builds.

## Task 11: End-To-End Regression

**Files:**
- Create: `scripts/assistant-identity-regression.py`
- Create: `docs/superpowers/reports/2026-06-04-assistant-owned-identities-regression.md`

- [ ] **Step 1: Write regression script**

Create `scripts/assistant-identity-regression.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.request


BASE = "http://localhost:8080"
PASSWORD = "par-dev"


def request(path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json", "x-par-password": PASSWORD},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = resp.read().decode("utf-8")
        return json.loads(payload) if payload else {}


def main() -> None:
    results = []
    results.append({"case": "identity_status", "result": request("/api/assistant-identities")})
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run unit regression**

Run:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest \
  tests/test_assistant_identity_schema.py \
  tests/test_assistant_identity_registry.py \
  tests/test_assistant_inbox_gateway.py \
  tests/test_assistant_trigger_routing.py \
  tests/test_assistant_outbound_pipeline.py \
  tests/test_assistant_gmail_adapter.py \
  tests/test_assistant_whatsapp_adapter.py \
  tests/test_assistant_identity_api.py \
  tests/test_assistant_identity_memory_scope.py \
  -q
```

Expected: all tests pass.

- [ ] **Step 3: Run Android regression**

Run:

```bash
cd /Users/wrf/Documents/background/android_app
JAVA_HOME=/opt/homebrew/opt/openjdk@17 gradle :app:testDebugUnitTest :app:assembleDebug
```

Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 4: Verify behavior content**

Manually inspect outputs and write report:

```markdown
# 2026-06-04 Assistant Owned Identities Regression

## Cases

- AI-GM-001 user email to Nomi becomes user_direct_command.
- AI-WA-001 user WhatsApp to Nomi becomes user_direct_command.
- AI-EXT-001 external contact to Nomi becomes external_contact_message.
- AI-DRAFT-001 third-party outbound creates draft, not provider send.
- AI-SEND-001 confirmed draft calls fake provider and records audit.
- AI-SCOPE-001 assistant-owned event scope does not mix with user-owned Gmail/WhatsApp collectors.
- AI-ROUTE-001 explicit Nomi Gmail/WhatsApp send request routes to a deterministic core pipeline, not an agent.
- AI-ROUTE-002 long-tail agent can request only `assistant.outbound.create_draft` and cannot call provider send tools.
- AI-ROUTE-003 external contact message creates an inbox item or proactive suggestion and does not auto-reply.

## Judgment

Each case must record not only pass/fail, but whether the normalized event, route decision, agent boundary, draft card, confirmation state, and memory scope are semantically correct.
```

## Coverage Matrix

| Spec requirement | Plan task |
| --- | --- |
| Nomi-owned identity model | Task 1, Task 2 |
| Credentials separated from model context | Task 2, Task 8, `.env.example` update |
| Gmail inbound and outbound | Task 3, Task 6, Task 8 |
| WhatsApp Cloud API inbound/outbound | Task 3, Task 7, Task 8 |
| Inbound classification | Task 3, Task 4 |
| User direct command routing | Task 3, Task 4, Task 9 |
| Trigger source to pipeline/agent routing | Task 9, Task 11 |
| Agent cannot directly send provider messages | Task 9, Task 11 |
| External-contact message does not auto-reply | Task 3, Task 9, Task 11 |
| External contact assistant inbox | Task 3, Task 8, Task 10 |
| Draft-confirm-send outbound flow | Task 5, Task 6, Task 7, Task 8 |
| Third-party send confirmation required | Task 5, Task 9, Task 11 |
| Delivery receipt/audit | Task 1, Task 7, Task 11 |
| Memory scope separation | Task 4, Task 11 |
| Android identity and draft UI | Task 10 |
| Regression with semantic output checks | Task 11 |

## Development Self-Review

- No design acceptance criterion is left without a task.
- The plan keeps user-owned collectors separate from Nomi-owned identities.
- The plan starts with fake adapters so semantic behavior can be validated before real provider credentials.
- The plan does not allow third-party send without confirmation.
- The plan now has explicit trigger-source routing tests so known communication requests use deterministic pipelines, while long-tail agents can only create local drafts.
- The plan includes output-reasonableness verification, not only successful command exits.
