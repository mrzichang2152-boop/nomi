from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable, ContextManager, Protocol
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.assistant_identity.composio_gmail import (
    ASSISTANT_GMAIL_COMPOSIO_USER_ID,
    ASSISTANT_GMAIL_IDENTITY_ID,
    assistant_gmail_toolkit_version,
)
from app.assistant_identity.inbox_gateway import AssistantInboxGateway
from app.assistant_identity.registry import AssistantIdentityRegistry


ASSISTANT_GMAIL_NEW_MESSAGE_TRIGGER = "GMAIL_NEW_GMAIL_MESSAGE"
ASSISTANT_GMAIL_FETCH_TOOL = "GMAIL_FETCH_EMAILS"
ASSISTANT_GMAIL_MAX_SYNC_BATCH = 50


class AssistantGmailInboundSyncError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AssistantGmailInboundProvider(Protocol):
    def create_new_message_trigger(
        self,
        *,
        user_id: str,
        connected_account_id: str,
    ) -> str:
        ...

    def fetch_messages(
        self,
        *,
        user_id: str,
        connected_account_id: str,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        ...


class AssistantInboxEventRepository(Protocol):
    def insert_if_new(self, event: dict[str, Any]) -> bool:
        ...

    def list(
        self,
        identity_id: str = "",
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        ...

    def get(self, event_id: str) -> dict[str, Any] | None:
        ...


class InMemoryAssistantInboxEventRepository:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.RLock()

    def insert_if_new(self, event: dict[str, Any]) -> bool:
        identity_id = str(event.get("identity_id") or "").strip()
        external_message_id = str(event.get("external_message_id") or "").strip()
        if not identity_id or not external_message_id:
            raise ValueError("assistant_inbox_event_key_missing")
        key = (identity_id, external_message_id)
        with self._lock:
            if key in self._records:
                return False
            self._records[key] = dict(event)
            return True

    def list(
        self,
        identity_id: str = "",
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        with self._lock:
            records = [
                dict(event)
                for (stored_identity_id, _), event in self._records.items()
                if not identity_id or stored_identity_id == identity_id
            ]
        return records[-max(1, limit) :]

    def get(self, event_id: str) -> dict[str, Any] | None:
        normalized_event_id = str(event_id or "").strip()
        with self._lock:
            for event in self._records.values():
                if str(event.get("event_id") or "") == normalized_event_id:
                    return dict(event)
        return None


class PostgresAssistantInboxEventRepository:
    def __init__(self, connection_factory: Callable[[], ContextManager[object]]) -> None:
        self.connection_factory = connection_factory

    def insert_if_new(self, event: dict[str, Any]) -> bool:
        event_id = str(event.get("event_id") or "").strip()
        identity_id = str(event.get("identity_id") or "").strip()
        external_message_id = str(event.get("external_message_id") or "").strip()
        if not event_id or not identity_id or not external_message_id:
            raise ValueError("assistant_inbox_event_key_missing")
        memory_scope = event.get("memory_scope")
        if not isinstance(memory_scope, dict):
            memory_scope = {}
        visibility_scope = str(
            memory_scope.get("visibility_scope")
            or event.get("visibility_scope")
            or "assistant_identity_thread"
        )
        source_evidence_ids = event.get("source_evidence_ids")
        if not isinstance(source_evidence_ids, list):
            source_evidence_ids = []
        occurred_at = _parse_datetime(event.get("occurred_at"))
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                INSERT INTO assistant_inbox_events (
                  id, event_id, identity_id, source_type, conversation_id,
                  external_message_id, sender_key, sender_class,
                  classification, normalized_text, normalized_payload,
                  visibility_scope, source_evidence_ids, occurred_at
                ) VALUES (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (identity_id, external_message_id) DO NOTHING
                RETURNING external_message_id
                """,
                (
                    uuid4(),
                    event_id,
                    identity_id,
                    str(event.get("source_type") or "assistant_gmail"),
                    str(event.get("conversation_id") or ""),
                    external_message_id,
                    str(event.get("sender_key") or ""),
                    str((event.get("sender") or {}).get("sender_class") or "")
                    if isinstance(event.get("sender"), dict)
                    else "",
                    str(event.get("classification") or "unknown_sender"),
                    str(event.get("normalized_text") or ""),
                    Jsonb(dict(event.get("normalized_payload") or {})),
                    visibility_scope,
                    source_evidence_ids,
                    occurred_at,
                ),
            ).fetchone()
        return row is not None

    def _row_to_event(self, row: object) -> dict[str, Any]:
        values = list(row)
        return {
            "event_id": values[0],
            "identity_id": values[1],
            "source_type": values[2],
            "source_account_id": values[1],
            "conversation_id": values[3],
            "external_message_id": values[4],
            "sender_key": values[5],
            "sender": {"sender_class": values[6]},
            "classification": values[7],
            "normalized_text": values[8],
            "normalized_payload": dict(values[9] or {}),
            "memory_scope": {"visibility_scope": values[10]},
            "source_evidence_ids": list(values[11] or []),
            "occurred_at": values[12].isoformat() if values[12] else "",
            "created_at": values[13].isoformat() if values[13] else "",
        }

    def list(
        self,
        identity_id: str = "",
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        bounded_limit = min(max(1, int(limit)), 1000)
        where_sql = "WHERE identity_id = %s" if identity_id else ""
        params: tuple[object, ...] = (
            (identity_id, bounded_limit) if identity_id else (bounded_limit,)
        )
        with self.connection_factory() as connection:
            rows = connection.execute(
                f"""
                SELECT event_id, identity_id, source_type, conversation_id, external_message_id,
                       sender_key, sender_class, classification, normalized_text,
                       normalized_payload, visibility_scope, source_evidence_ids,
                       occurred_at, created_at
                FROM assistant_inbox_events
                {where_sql}
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                params,
            ).fetchall()
        return [self._row_to_event(row) for row in reversed(rows)]

    def get(self, event_id: str) -> dict[str, Any] | None:
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                SELECT event_id, identity_id, source_type, conversation_id, external_message_id,
                       sender_key, sender_class, classification, normalized_text,
                       normalized_payload, visibility_scope, source_evidence_ids,
                       occurred_at, created_at
                FROM assistant_inbox_events
                WHERE event_id = %s
                """,
                (event_id,),
            ).fetchone()
        return self._row_to_event(row) if row is not None else None


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def assistant_gmail_incremental_query(last_sync_at: object) -> str:
    last_sync = _parse_datetime(last_sync_at)
    if last_sync is None:
        return "newer_than:1d"
    return f"after:{max(0, int(last_sync.timestamp()) - 60)}"


def _serialized(value: object) -> object:
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return value.model_dump()
    if hasattr(value, "dict") and callable(value.dict):
        return value.dict()
    return value


def _nested_messages(value: object) -> list[dict[str, Any]]:
    normalized = _serialized(value)
    if isinstance(normalized, list):
        return [dict(item) for item in normalized if isinstance(item, dict)]
    if not isinstance(normalized, dict):
        return []
    for key in ("messages", "items", "results"):
        item = normalized.get(key)
        if isinstance(item, list):
            return [dict(entry) for entry in item if isinstance(entry, dict)]
    for key in ("data", "result", "response_data", "responseData"):
        item = normalized.get(key)
        messages = _nested_messages(item)
        if messages:
            return messages
    return []


def _trigger_id(value: object) -> str:
    normalized = _serialized(value)
    if isinstance(normalized, dict):
        return str(
            normalized.get("trigger_id")
            or normalized.get("triggerId")
            or normalized.get("id")
            or ""
        )
    return str(
        getattr(normalized, "trigger_id", "")
        or getattr(normalized, "triggerId", "")
        or getattr(normalized, "id", "")
    )


class ComposioSdkAssistantGmailInboundProvider:
    def __init__(self, sdk: object) -> None:
        self.sdk = sdk

    def create_new_message_trigger(
        self,
        *,
        user_id: str,
        connected_account_id: str,
    ) -> str:
        trigger = self.sdk.triggers.create(
            slug=ASSISTANT_GMAIL_NEW_MESSAGE_TRIGGER,
            user_id=user_id,
            connected_account_id=connected_account_id,
            trigger_config={},
        )
        identifier = _trigger_id(trigger)
        if not identifier:
            raise AssistantGmailInboundSyncError("assistant_gmail_trigger_invalid")
        return identifier

    def fetch_messages(
        self,
        *,
        user_id: str,
        connected_account_id: str,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        result = self.sdk.tools.execute(
            ASSISTANT_GMAIL_FETCH_TOOL,
            user_id=user_id,
            connected_account_id=connected_account_id,
            version=assistant_gmail_toolkit_version(),
            arguments={"query": query, "max_results": min(max(1, limit), 50)},
        )
        normalized = _serialized(result)
        if isinstance(normalized, dict) and normalized.get("successful") is False:
            raise AssistantGmailInboundSyncError("assistant_gmail_fetch_failed")
        return _nested_messages(normalized)

    def build_trigger_subscription(
        self,
        *,
        trigger_id: str,
        handler: Callable[[dict[str, Any]], object],
    ) -> object:
        subscription = self.sdk.triggers.subscribe()

        @subscription.handle(trigger_id=trigger_id)
        def handle_event(data: object) -> None:
            normalized = _serialized(data)
            handler(dict(normalized) if isinstance(normalized, dict) else {})

        return subscription


def _message_from_payload(value: object) -> dict[str, Any]:
    normalized = _serialized(value)
    if not isinstance(normalized, dict):
        return {}
    for key in ("message", "email"):
        item = normalized.get(key)
        if isinstance(item, dict):
            return _message_from_payload(item)
    for key in ("data", "payload", "event"):
        item = normalized.get(key)
        if isinstance(item, dict):
            nested = _message_from_payload(item)
            if nested:
                return nested
    return dict(normalized)


def _normalize_message(message: dict[str, Any]) -> dict[str, Any]:
    preview = message.get("preview")
    if not isinstance(preview, dict):
        preview = {}
    return {
        "id": str(
            message.get("id")
            or message.get("message_id")
            or message.get("messageId")
            or message.get("history_id")
            or message.get("historyId")
            or ""
        ).strip(),
        "thread_id": str(
            message.get("thread_id")
            or message.get("threadId")
            or message.get("thread")
            or ""
        ).strip(),
        "from": str(message.get("from") or message.get("sender") or "").strip(),
        "to": message.get("to") or message.get("recipients") or [],
        "subject": str(message.get("subject") or ""),
        "body": str(
            message.get("body")
            or message.get("text")
            or message.get("plain_text")
            or message.get("messageText")
            or message.get("snippet")
            or preview.get("body")
            or ""
        ),
        "date": str(
            message.get("date")
            or message.get("received_at")
            or message.get("receivedAt")
            or message.get("messageTimestamp")
            or message.get("timestamp")
            or ""
        ),
    }


class AssistantGmailInboundSyncService:
    def __init__(
        self,
        *,
        registry: AssistantIdentityRegistry,
        health_service: object,
        provider: AssistantGmailInboundProvider,
        event_repository: AssistantInboxEventRepository,
        gateway: AssistantInboxGateway | None = None,
    ) -> None:
        self.registry = registry
        self.health_service = health_service
        self.provider = provider
        self.event_repository = event_repository
        self.gateway = gateway or AssistantInboxGateway()
        self._subscription: object | None = None
        self._subscription_trigger_id = ""
        self._subscription_thread: threading.Thread | None = None

    def _ensure_trigger_subscription(self, trigger_id: str) -> bool:
        if (
            self._subscription_trigger_id == trigger_id
            and self._subscription_thread is not None
            and self._subscription_thread.is_alive()
        ):
            return True
        builder = getattr(self.provider, "build_trigger_subscription", None)
        if not callable(builder):
            return True
        try:
            subscription = builder(
                trigger_id=trigger_id,
                handler=self.ingest_trigger,
            )
            wait_forever = getattr(subscription, "wait_forever", None)
            if not callable(wait_forever):
                return False
            thread = threading.Thread(
                target=wait_forever,
                name="nomi-assistant-gmail-trigger",
                daemon=True,
            )
            thread.start()
        except Exception:
            return False
        self._subscription = subscription
        self._subscription_trigger_id = trigger_id
        self._subscription_thread = thread
        return True

    def _identity_and_account(self):
        identity = self.registry.get(ASSISTANT_GMAIL_IDENTITY_ID)
        if identity is None or identity.kind != "assistant_gmail":
            raise AssistantGmailInboundSyncError(
                "assistant_gmail_identity_not_found"
            )
        provider_connection = dict(
            identity.metadata.get("provider_connection") or {}
        )
        connected_account_id = str(
            provider_connection.get("connected_account_id") or ""
        ).strip()
        if not connected_account_id:
            raise AssistantGmailInboundSyncError(
                "assistant_gmail_connected_account_missing"
            )
        if (
            str(provider_connection.get("composio_user_id") or "")
            != ASSISTANT_GMAIL_COMPOSIO_USER_ID
        ):
            raise AssistantGmailInboundSyncError(
                "assistant_gmail_account_scope_mismatch"
            )
        return identity, connected_account_id

    def _save_inbound_state(
        self,
        *,
        mode: str,
        trigger_id: str = "",
        last_sync_at: str = "",
    ) -> None:
        identity, _ = self._identity_and_account()
        metadata = dict(identity.metadata)
        inbound = dict(metadata.get("inbound") or {})
        inbound.update({"mode": mode})
        if trigger_id:
            inbound["trigger_id"] = trigger_id
        if last_sync_at:
            inbound["last_sync_at"] = last_sync_at
        metadata["inbound"] = inbound
        capabilities = list(identity.capabilities)
        if "receive" not in capabilities:
            capabilities.append("receive")
        self.registry.repository.save(
            replace(identity, metadata=metadata, capabilities=capabilities),
            expected_version=identity.version,
        )

    def configure_inbound(self, *, fetch_limit: int = 50) -> dict[str, Any]:
        identity, connected_account_id = self._identity_and_account()
        inbound = dict(identity.metadata.get("inbound") or {})
        persisted_trigger_id = str(inbound.get("trigger_id") or "").strip()
        if inbound.get("mode") == "trigger" and persisted_trigger_id:
            if not self._ensure_trigger_subscription(persisted_trigger_id):
                return {
                    "status": "configured",
                    "mode": "bounded_incremental_sync",
                    "identity_id": ASSISTANT_GMAIL_IDENTITY_ID,
                    **self.sync_once(
                        query="newer_than:1d",
                        fetch_limit=fetch_limit,
                        trigger_error_code="assistant_gmail_subscription_unavailable",
                    ),
                }
            self.health_service.record(
                ASSISTANT_GMAIL_IDENTITY_ID,
                "inbound",
                "passed",
                details={
                    "mode": "trigger",
                    "trigger_id": persisted_trigger_id,
                    "managed_polling_latency_possible": True,
                    "reused": True,
                },
            )
            return {
                "status": "configured",
                "mode": "trigger",
                "trigger_id": persisted_trigger_id,
                "identity_id": ASSISTANT_GMAIL_IDENTITY_ID,
                "reused": True,
            }
        try:
            trigger_id = self.provider.create_new_message_trigger(
                user_id=ASSISTANT_GMAIL_COMPOSIO_USER_ID,
                connected_account_id=connected_account_id,
            )
        except Exception:
            result = self.sync_once(
                query="newer_than:1d",
                fetch_limit=fetch_limit,
                trigger_error_code="assistant_gmail_trigger_unavailable",
            )
            return {
                "status": "configured",
                "mode": "bounded_incremental_sync",
                "identity_id": ASSISTANT_GMAIL_IDENTITY_ID,
                **result,
            }
        if not trigger_id:
            raise AssistantGmailInboundSyncError("assistant_gmail_trigger_invalid")
        if not self._ensure_trigger_subscription(trigger_id):
            return {
                "status": "configured",
                "mode": "bounded_incremental_sync",
                "identity_id": ASSISTANT_GMAIL_IDENTITY_ID,
                **self.sync_once(
                    query="newer_than:1d",
                    fetch_limit=fetch_limit,
                    trigger_error_code="assistant_gmail_subscription_unavailable",
                ),
            }
        self._save_inbound_state(mode="trigger", trigger_id=trigger_id)
        self.health_service.record(
            ASSISTANT_GMAIL_IDENTITY_ID,
            "inbound",
            "passed",
            details={
                "mode": "trigger",
                "trigger_id": trigger_id,
                "managed_polling_latency_possible": True,
            },
        )
        return {
            "status": "configured",
            "mode": "trigger",
            "trigger_id": trigger_id,
            "identity_id": ASSISTANT_GMAIL_IDENTITY_ID,
        }

    def sync_once(
        self,
        *,
        query: str = "newer_than:1d",
        fetch_limit: int = 50,
        trigger_error_code: str = "",
    ) -> dict[str, Any]:
        _, connected_account_id = self._identity_and_account()
        bounded_limit = min(max(1, int(fetch_limit)), ASSISTANT_GMAIL_MAX_SYNC_BATCH)
        try:
            messages = self.provider.fetch_messages(
                user_id=ASSISTANT_GMAIL_COMPOSIO_USER_ID,
                connected_account_id=connected_account_id,
                query=query.strip() or "newer_than:1d",
                limit=bounded_limit,
            )
        except Exception as exc:
            self.health_service.record(
                ASSISTANT_GMAIL_IDENTITY_ID,
                "inbound",
                "degraded",
                error_code="assistant_gmail_fetch_failed",
                details={"mode": "bounded_incremental_sync"},
            )
            raise AssistantGmailInboundSyncError(
                "assistant_gmail_fetch_failed"
            ) from exc
        counts = self._persist_messages(messages)
        now = datetime.now(timezone.utc).isoformat()
        self._save_inbound_state(
            mode="bounded_incremental_sync",
            last_sync_at=now,
        )
        details = {
            "mode": "bounded_incremental_sync",
            "fetched_count": len(messages),
            "created_count": counts["created_count"],
            "duplicate_count": counts["duplicate_count"],
            "max_batch_size": bounded_limit,
            "trigger_error_code": trigger_error_code,
        }
        self.health_service.record(
            ASSISTANT_GMAIL_IDENTITY_ID,
            "inbound",
            "passed",
            details=details,
        )
        return {
            "fetched_count": len(messages),
            **counts,
        }

    def ingest_trigger(self, payload: dict[str, Any]) -> dict[str, str]:
        message = _normalize_message(_message_from_payload(payload))
        external_message_id = str(message.get("id") or "").strip()
        if not external_message_id:
            return {
                "status": "rejected",
                "reason": "assistant_gmail_message_id_missing",
            }
        event = self.gateway.normalize_gmail(
            identity_id=ASSISTANT_GMAIL_IDENTITY_ID,
            message=message,
        )
        created = self.event_repository.insert_if_new(event)
        return {
            "status": "created" if created else "duplicate",
            "external_message_id": external_message_id,
        }

    def _persist_messages(self, messages: list[dict[str, Any]]) -> dict[str, int]:
        created_count = 0
        duplicate_count = 0
        for raw_message in messages:
            message = _normalize_message(raw_message)
            if not message["id"]:
                continue
            event = self.gateway.normalize_gmail(
                identity_id=ASSISTANT_GMAIL_IDENTITY_ID,
                message=message,
            )
            if self.event_repository.insert_if_new(event):
                created_count += 1
            else:
                duplicate_count += 1
        return {
            "created_count": created_count,
            "duplicate_count": duplicate_count,
        }
