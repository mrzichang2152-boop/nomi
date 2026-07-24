from __future__ import annotations

import copy
import re
import threading
from datetime import datetime, timezone
from typing import Any, Callable, ContextManager, Protocol
from uuid import uuid4

from psycopg.types.json import Jsonb


_SENSITIVE_KEY_PARTS = (
    "token",
    "password",
    "secret",
    "credential",
    "body",
    "recipient",
    "address",
    "subject",
    "request_headers",
    "authorization",
)
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")


class AssistantAuditRepository(Protocol):
    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        ...

    def list(
        self,
        *,
        identity_id: str = "",
        draft_id: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        ...


class InMemoryAssistantAuditRepository:
    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        stored = copy.deepcopy(event)
        with self._lock:
            self._events.append(stored)
        return copy.deepcopy(stored)

    def list(
        self,
        *,
        identity_id: str = "",
        draft_id: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        with self._lock:
            events = [
                copy.deepcopy(event)
                for event in self._events
                if (not identity_id or event.get("identity_id") == identity_id)
                and (not draft_id or event.get("draft_id") == draft_id)
            ]
        return events[-max(1, int(limit)) :]


class PostgresAssistantAuditRepository:
    def __init__(self, connection_factory: Callable[[], ContextManager[object]]) -> None:
        self.connection_factory = connection_factory

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                INSERT INTO assistant_identity_audit_events (
                  id, trace_id, action, actor, identity_id, draft_id,
                  policy_result, status, redacted_payload, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING trace_id, action, actor, identity_id, draft_id,
                          policy_result, status, redacted_payload, created_at
                """,
                (
                    uuid4(),
                    event["trace_id"],
                    event["action"],
                    event.get("actor", ""),
                    event.get("identity_id", ""),
                    event.get("draft_id", ""),
                    event.get("policy_result", ""),
                    event["status"],
                    Jsonb(event.get("redacted_payload") or {}),
                    event["created_at"],
                ),
            ).fetchone()
        return self._event(row)

    def list(
        self,
        *,
        identity_id: str = "",
        draft_id: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        values: list[object] = []
        if identity_id:
            conditions.append("identity_id = %s")
            values.append(identity_id)
        if draft_id:
            conditions.append("draft_id = %s")
            values.append(draft_id)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        values.append(max(1, min(1000, int(limit))))
        with self.connection_factory() as connection:
            rows = connection.execute(
                f"""
                SELECT trace_id, action, actor, identity_id, draft_id,
                       policy_result, status, redacted_payload, created_at
                FROM assistant_identity_audit_events
                {where}
                ORDER BY created_at ASC
                LIMIT %s
                """,
                tuple(values),
            ).fetchall()
        return [self._event(row) for row in rows]

    @staticmethod
    def _event(row: object) -> dict[str, Any]:
        values = tuple(row)
        return {
            "trace_id": str(values[0]),
            "action": str(values[1]),
            "actor": str(values[2] or ""),
            "identity_id": str(values[3] or ""),
            "draft_id": str(values[4] or ""),
            "policy_result": str(values[5] or ""),
            "status": str(values[6]),
            "redacted_payload": dict(values[7] or {}),
            "created_at": values[8].isoformat(),
        }


class AssistantIdentityAuditor:
    def __init__(
        self,
        repository: AssistantAuditRepository | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def record(
        self,
        action: str,
        *,
        actor: str,
        identity_id: str,
        status: str,
        draft_id: str = "",
        policy_result: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "trace_id": str(uuid4()),
            "action": str(action),
            "actor": str(actor or ""),
            "identity_id": str(identity_id or ""),
            "draft_id": str(draft_id or ""),
            "policy_result": str(policy_result or ""),
            "status": str(status),
            "redacted_payload": self.redact(payload or {}),
            "created_at": self._clock().isoformat(),
        }
        if self.repository is not None:
            return self.repository.append(event)
        return event

    @classmethod
    def redact(cls, value: Any, *, key: str = "") -> Any:
        lowered = key.casefold()
        if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {
                str(item_key): cls.redact(item_value, key=str(item_key))
                for item_key, item_value in value.items()
            }
        if isinstance(value, list):
            return [cls.redact(item) for item in value]
        if isinstance(value, tuple):
            return [cls.redact(item) for item in value]
        if isinstance(value, str):
            return _PHONE.sub("[REDACTED_PHONE]", _EMAIL.sub("[REDACTED_EMAIL]", value))
        return value
