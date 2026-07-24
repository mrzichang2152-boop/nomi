from __future__ import annotations

import copy
import hashlib
import threading
from datetime import datetime, timezone
from typing import Callable, ContextManager, MutableMapping, Protocol
from uuid import uuid4

from psycopg.types.json import Jsonb


class AssistantOutboundRepository(Protocol):
    def get_draft(self, draft_id: str) -> dict | None:
        ...

    def get_draft_by_idempotency_key(self, idempotency_key: str) -> dict | None:
        ...

    def save_draft(self, draft: dict) -> dict:
        ...

    def transition_draft(
        self,
        draft: dict,
        *,
        expected_statuses: set[str],
        expected_revision: int,
    ) -> dict | None:
        ...

    def list_drafts_since(self, since: datetime) -> list[dict]:
        ...

    def get_confirmation(self, confirmation_token: str) -> dict | None:
        ...

    def save_confirmation(self, confirmation: dict) -> dict:
        ...

    def claim_confirmation_and_transition_draft(
        self,
        confirmation_token: str,
        *,
        draft_id: str,
        protected_hash: str,
        actor: str,
        expected_revision: int,
        claimed_draft: dict,
        claimed_at: datetime,
    ) -> dict | None:
        ...

    def invalidate_confirmations(self, draft_id: str, *, invalidated_at: object) -> None:
        ...

    def record_delivery_receipt(
        self,
        *,
        identity_id: str,
        provider_message_id: str,
        status: str,
        receipt_payload: dict,
        occurred_at: datetime,
    ) -> dict:
        ...


class InMemoryAssistantOutboundRepository:
    def __init__(
        self,
        *,
        drafts: MutableMapping[str, dict] | None = None,
        confirmations: MutableMapping[str, dict] | None = None,
    ) -> None:
        self._drafts = drafts if drafts is not None else {}
        self._confirmations = confirmations if confirmations is not None else {}
        self._idempotency_index: dict[str, str] = {}
        self._receipts: list[dict] = []
        self._lock = threading.RLock()
        for draft_id, draft in self._drafts.items():
            key = str(draft.get("idempotency_key") or "").strip()
            if key:
                self._idempotency_index[key] = draft_id

    def get_draft(self, draft_id: str) -> dict | None:
        with self._lock:
            draft = self._drafts.get(draft_id)
            return copy.deepcopy(draft) if draft is not None else None

    def get_draft_by_idempotency_key(self, idempotency_key: str) -> dict | None:
        key = str(idempotency_key or "").strip()
        if not key:
            return None
        with self._lock:
            draft_id = self._idempotency_index.get(key)
            draft = self._drafts.get(draft_id or "")
            return copy.deepcopy(draft) if draft is not None else None

    def save_draft(self, draft: dict) -> dict:
        stored = copy.deepcopy(draft)
        stored.setdefault("revision", 1)
        draft_id = str(stored["draft_id"])
        key = str(stored.get("idempotency_key") or "").strip()
        with self._lock:
            if key:
                current_id = self._idempotency_index.get(key)
                if current_id and current_id != draft_id:
                    return copy.deepcopy(self._drafts[current_id])
                self._idempotency_index[key] = draft_id
            self._drafts[draft_id] = stored
        return copy.deepcopy(stored)

    def transition_draft(
        self,
        draft: dict,
        *,
        expected_statuses: set[str],
        expected_revision: int,
    ) -> dict | None:
        stored = copy.deepcopy(draft)
        draft_id = str(stored["draft_id"])
        with self._lock:
            current = self._drafts.get(draft_id)
            if current is None:
                return None
            current_status = str(current.get("status") or "")
            current_revision = int(current.get("revision") or 1)
            if (
                current_status not in expected_statuses
                or current_revision != int(expected_revision)
            ):
                return None
            stored["revision"] = current_revision + 1
            key = str(stored.get("idempotency_key") or "").strip()
            if key:
                self._idempotency_index[key] = draft_id
            self._drafts[draft_id] = stored
        return copy.deepcopy(stored)

    def list_drafts_since(self, since: datetime) -> list[dict]:
        with self._lock:
            drafts = []
            for draft in self._drafts.values():
                raw_timestamp = draft.get("updated_at") or draft.get("created_at")
                if not raw_timestamp:
                    continue
                timestamp = datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
                if timestamp >= since:
                    drafts.append(copy.deepcopy(draft))
            return drafts

    def get_confirmation(self, confirmation_token: str) -> dict | None:
        with self._lock:
            confirmation = self._confirmations.get(confirmation_token)
            return copy.deepcopy(confirmation) if confirmation is not None else None

    def save_confirmation(self, confirmation: dict) -> dict:
        stored = copy.deepcopy(confirmation)
        token = str(stored["confirmation_token"])
        with self._lock:
            self._confirmations[token] = stored
        return copy.deepcopy(stored)

    def claim_confirmation_and_transition_draft(
        self,
        confirmation_token: str,
        *,
        draft_id: str,
        protected_hash: str,
        actor: str,
        expected_revision: int,
        claimed_draft: dict,
        claimed_at: datetime,
    ) -> dict | None:
        token = str(confirmation_token or "").strip()
        with self._lock:
            confirmation = self._confirmations.get(token)
            current = self._drafts.get(str(draft_id))
            if (
                confirmation is None
                or str(confirmation.get("draft_id") or "") != str(draft_id)
                or str(confirmation.get("protected_hash") or "") != str(protected_hash)
                or str(confirmation.get("actor") or "") != str(actor)
                or confirmation.get("consumed_at") is not None
                or confirmation.get("invalidated_at") is not None
                or current is None
                or str(current.get("status") or "") != "draft"
                or int(current.get("revision") or 1) != int(expected_revision)
            ):
                return None
            transitioned = copy.deepcopy(claimed_draft)
            transitioned["revision"] = int(expected_revision) + 1
            self._drafts[str(draft_id)] = transitioned
            updated = copy.deepcopy(confirmation)
            updated["consumed_at"] = claimed_at
            self._confirmations[token] = updated
            for other_token, other_confirmation in list(self._confirmations.items()):
                if (
                    other_token != token
                    and str(other_confirmation.get("draft_id") or "") == str(draft_id)
                    and other_confirmation.get("consumed_at") is None
                    and other_confirmation.get("invalidated_at") is None
                ):
                    invalidated = copy.deepcopy(other_confirmation)
                    invalidated["invalidated_at"] = claimed_at
                    self._confirmations[other_token] = invalidated
            return copy.deepcopy(transitioned)

    def invalidate_confirmations(self, draft_id: str, *, invalidated_at: object) -> None:
        with self._lock:
            for token, confirmation in list(self._confirmations.items()):
                if (
                    confirmation.get("draft_id") == draft_id
                    and confirmation.get("consumed_at") is None
                ):
                    updated = copy.deepcopy(confirmation)
                    updated["invalidated_at"] = invalidated_at
                    self._confirmations[token] = updated

    def record_delivery_receipt(
        self,
        *,
        identity_id: str,
        provider_message_id: str,
        status: str,
        receipt_payload: dict,
        occurred_at: datetime,
    ) -> dict:
        with self._lock:
            matched_draft_id = ""
            for draft_id, draft in self._drafts.items():
                if (
                    draft.get("identity_id") == identity_id
                    and draft.get("provider_message_id") == provider_message_id
                ):
                    updated = copy.deepcopy(draft)
                    updated["status"] = status
                    updated["updated_at"] = occurred_at.isoformat()
                    self._drafts[draft_id] = updated
                    matched_draft_id = draft_id
                    break
            if not matched_draft_id:
                raise KeyError("outbound_message_not_found")
            receipt = {
                "receipt_id": str(uuid4()),
                "draft_id": matched_draft_id,
                "identity_id": identity_id,
                "provider_message_id": provider_message_id,
                "status": status,
                "receipt_payload": copy.deepcopy(receipt_payload),
                "occurred_at": occurred_at.isoformat(),
            }
            self._receipts.append(receipt)
            return copy.deepcopy(receipt)


class PostgresAssistantOutboundRepository:
    def __init__(self, connection_factory: Callable[[], ContextManager[object]]) -> None:
        self.connection_factory = connection_factory

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(str(token).encode("utf-8")).hexdigest()

    def get_draft(self, draft_id: str) -> dict | None:
        with self.connection_factory() as connection:
            row = connection.execute(
                "SELECT state FROM assistant_message_drafts WHERE draft_id = %s",
                (draft_id,),
            ).fetchone()
        return dict(row[0]) if row is not None else None

    def get_draft_by_idempotency_key(self, idempotency_key: str) -> dict | None:
        key = str(idempotency_key or "").strip()
        if not key:
            return None
        with self.connection_factory() as connection:
            row = connection.execute(
                "SELECT state FROM assistant_message_drafts WHERE idempotency_key = %s",
                (key,),
            ).fetchone()
        return dict(row[0]) if row is not None else None

    def save_draft(self, draft: dict) -> dict:
        stored = copy.deepcopy(draft)
        stored.setdefault("revision", 1)
        key = str(stored.get("idempotency_key") or "").strip()
        with self.connection_factory() as connection:
            if key:
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (key,),
                )
                existing = connection.execute(
                    "SELECT draft_id, state FROM assistant_message_drafts WHERE idempotency_key = %s",
                    (key,),
                ).fetchone()
                if existing is not None and str(existing[0]) != str(stored["draft_id"]):
                    return dict(existing[1])
            row = connection.execute(
                """
                INSERT INTO assistant_message_drafts (
                  id, draft_id, identity_id, channel, recipient, subject, body_text,
                  body_hash, status, confirmation_required, idempotency_key, task_id,
                  source_evidence_ids, risk_notes, state, created_at, updated_at
                ) VALUES (
                  %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s
                )
                ON CONFLICT (draft_id) DO UPDATE SET
                  recipient = EXCLUDED.recipient,
                  subject = EXCLUDED.subject,
                  body_text = EXCLUDED.body_text,
                  body_hash = EXCLUDED.body_hash,
                  status = EXCLUDED.status,
                  confirmation_required = EXCLUDED.confirmation_required,
                  idempotency_key = EXCLUDED.idempotency_key,
                  task_id = EXCLUDED.task_id,
                  source_evidence_ids = EXCLUDED.source_evidence_ids,
                  risk_notes = EXCLUDED.risk_notes,
                  state = EXCLUDED.state,
                  updated_at = EXCLUDED.updated_at
                RETURNING state
                """,
                (
                    uuid4(),
                    stored["draft_id"],
                    stored["identity_id"],
                    stored["channel"],
                    stored["recipient"],
                    stored.get("subject", ""),
                    stored["body_text"],
                    stored.get("body_hash", ""),
                    stored.get("status", "draft"),
                    bool(stored.get("confirmation_required", True)),
                    key,
                    str(stored.get("task_id") or ""),
                    list(stored.get("source_evidence_ids") or []),
                    Jsonb(list(stored.get("risk_notes") or [])),
                    Jsonb(stored),
                    stored.get("created_at") or self._now(),
                    stored.get("updated_at") or self._now(),
                ),
            ).fetchone()
            if stored.get("send_called") or stored.get("call_called"):
                connection.execute(
                    """
                    INSERT INTO assistant_outbound_messages (
                      id, draft_id, identity_id, channel, recipient,
                      provider_message_id, status, body_hash, confirmation_actor,
                      provider_result, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (draft_id) DO UPDATE SET
                      provider_message_id = EXCLUDED.provider_message_id,
                      status = EXCLUDED.status,
                      confirmation_actor = EXCLUDED.confirmation_actor,
                      provider_result = EXCLUDED.provider_result,
                      updated_at = EXCLUDED.updated_at
                    """,
                    (
                        uuid4(),
                        stored["draft_id"],
                        stored["identity_id"],
                        stored["channel"],
                        stored["recipient"],
                        str(stored.get("provider_message_id") or stored.get("provider_call_id") or ""),
                        stored.get("status", "sending"),
                        stored.get("body_hash", ""),
                        stored.get("confirmation_actor", ""),
                        Jsonb(stored.get("provider_result") or {}),
                        stored.get("sent_at") or stored.get("called_at") or self._now(),
                        stored.get("updated_at") or self._now(),
                    ),
                )
        return dict(row[0]) if row is not None else stored

    def transition_draft(
        self,
        draft: dict,
        *,
        expected_statuses: set[str],
        expected_revision: int,
    ) -> dict | None:
        stored = copy.deepcopy(draft)
        stored["revision"] = int(expected_revision) + 1
        statuses = sorted(str(status) for status in expected_statuses)
        if not statuses:
            return None
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                UPDATE assistant_message_drafts
                SET recipient = %s,
                    subject = %s,
                    body_text = %s,
                    body_hash = %s,
                    status = %s,
                    confirmation_required = %s,
                    source_evidence_ids = %s,
                    risk_notes = %s,
                    state = %s,
                    updated_at = %s
                WHERE draft_id = %s
                  AND status = ANY(%s)
                  AND COALESCE((state->>'revision')::integer, 1) = %s
                RETURNING state
                """,
                (
                    stored.get("recipient", ""),
                    stored.get("subject", ""),
                    stored.get("body_text", ""),
                    stored.get("body_hash", ""),
                    stored.get("status", "draft"),
                    bool(stored.get("confirmation_required", True)),
                    list(stored.get("source_evidence_ids") or []),
                    Jsonb(list(stored.get("risk_notes") or [])),
                    Jsonb(stored),
                    stored.get("updated_at") or self._now(),
                    stored["draft_id"],
                    statuses,
                    int(expected_revision),
                ),
            ).fetchone()
            if row is None:
                return None
            if stored.get("send_called") or stored.get("call_called"):
                connection.execute(
                    """
                    INSERT INTO assistant_outbound_messages (
                      id, draft_id, identity_id, channel, recipient,
                      provider_message_id, status, body_hash, confirmation_actor,
                      provider_result, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (draft_id) DO UPDATE SET
                      provider_message_id = EXCLUDED.provider_message_id,
                      status = EXCLUDED.status,
                      confirmation_actor = EXCLUDED.confirmation_actor,
                      provider_result = EXCLUDED.provider_result,
                      updated_at = EXCLUDED.updated_at
                    """,
                    (
                        uuid4(),
                        stored["draft_id"],
                        stored["identity_id"],
                        stored["channel"],
                        stored["recipient"],
                        str(stored.get("provider_message_id") or stored.get("provider_call_id") or ""),
                        stored.get("status", "sending"),
                        stored.get("body_hash", ""),
                        stored.get("confirmation_actor", ""),
                        Jsonb(stored.get("provider_result") or {}),
                        stored.get("sent_at") or stored.get("called_at") or self._now(),
                        stored.get("updated_at") or self._now(),
                    ),
                )
        return dict(row[0])

    def list_drafts_since(self, since: datetime) -> list[dict]:
        with self.connection_factory() as connection:
            rows = connection.execute(
                """
                SELECT state
                FROM assistant_message_drafts
                WHERE updated_at >= %s
                ORDER BY updated_at DESC
                """,
                (since,),
            ).fetchall()
        return [dict(row[0]) for row in rows]

    def get_confirmation(self, confirmation_token: str) -> dict | None:
        token = str(confirmation_token or "").strip()
        if not token:
            return None
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                SELECT draft_id, actor, protected_hash, expires_at, consumed_at,
                       invalidated_at, state
                FROM assistant_outbound_confirmations
                WHERE token_hash = %s
                """,
                (self._token_hash(token),),
            ).fetchone()
        if row is None:
            return None
        return {
            **dict(row[6] or {}),
            "confirmation_token": token,
            "draft_id": str(row[0]),
            "actor": str(row[1]),
            "protected_hash": str(row[2]),
            "expires_at": row[3],
            "consumed_at": row[4],
            "invalidated_at": row[5],
        }

    def save_confirmation(self, confirmation: dict) -> dict:
        stored = copy.deepcopy(confirmation)
        token = str(stored.pop("confirmation_token"))
        now = self._now()
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                INSERT INTO assistant_outbound_confirmations (
                  id, draft_id, token_hash, actor, protected_hash, expires_at,
                  consumed_at, invalidated_at, state, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (token_hash) DO UPDATE SET
                  consumed_at = EXCLUDED.consumed_at,
                  invalidated_at = EXCLUDED.invalidated_at,
                  state = EXCLUDED.state,
                  updated_at = EXCLUDED.updated_at
                RETURNING draft_id, actor, protected_hash, expires_at, consumed_at,
                          invalidated_at, state
                """,
                (
                    uuid4(),
                    stored["draft_id"],
                    self._token_hash(token),
                    stored["actor"],
                    stored["protected_hash"],
                    stored["expires_at"],
                    stored.get("consumed_at"),
                    stored.get("invalidated_at"),
                    Jsonb(
                        {
                            key: value
                            for key, value in stored.items()
                            if key
                            not in {
                                "draft_id",
                                "actor",
                                "protected_hash",
                                "expires_at",
                                "issued_at",
                                "consumed_at",
                                "invalidated_at",
                            }
                        }
                    ),
                    stored.get("issued_at") or now,
                    now,
                ),
            ).fetchone()
        return {
            **dict(row[6] or {}),
            "confirmation_token": token,
            "draft_id": str(row[0]),
            "actor": str(row[1]),
            "protected_hash": str(row[2]),
            "expires_at": row[3],
            "consumed_at": row[4],
            "invalidated_at": row[5],
        }

    def claim_confirmation_and_transition_draft(
        self,
        confirmation_token: str,
        *,
        draft_id: str,
        protected_hash: str,
        actor: str,
        expected_revision: int,
        claimed_draft: dict,
        claimed_at: datetime,
    ) -> dict | None:
        token = str(confirmation_token or "").strip()
        if not token:
            return None
        transitioned = copy.deepcopy(claimed_draft)
        transitioned["revision"] = int(expected_revision) + 1
        with self.connection_factory() as connection:
            confirmation = connection.execute(
                """
                SELECT actor, protected_hash, expires_at, consumed_at, invalidated_at
                FROM assistant_outbound_confirmations
                WHERE token_hash = %s
                  AND draft_id = %s
                FOR UPDATE
                """,
                (self._token_hash(token), draft_id),
            ).fetchone()
            if (
                confirmation is None
                or str(confirmation[0]) != str(actor)
                or str(confirmation[1]) != str(protected_hash)
                or confirmation[2] < claimed_at
                or confirmation[3] is not None
                or confirmation[4] is not None
            ):
                return None
            row = connection.execute(
                """
                UPDATE assistant_message_drafts
                SET status = %s,
                    confirmation_required = %s,
                    state = %s,
                    updated_at = %s
                WHERE draft_id = %s
                  AND status = 'draft'
                  AND COALESCE((state->>'revision')::integer, 1) = %s
                RETURNING state
                """,
                (
                    transitioned.get("status", "sending"),
                    bool(transitioned.get("confirmation_required", False)),
                    Jsonb(transitioned),
                    transitioned.get("updated_at") or claimed_at,
                    draft_id,
                    int(expected_revision),
                ),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE assistant_outbound_confirmations
                SET consumed_at = %s, updated_at = %s
                WHERE token_hash = %s
                """,
                (claimed_at, self._now(), self._token_hash(token)),
            )
            connection.execute(
                """
                UPDATE assistant_outbound_confirmations
                SET invalidated_at = %s, updated_at = %s
                WHERE draft_id = %s
                  AND token_hash <> %s
                  AND consumed_at IS NULL
                  AND invalidated_at IS NULL
                """,
                (claimed_at, self._now(), draft_id, self._token_hash(token)),
            )
            connection.execute(
                """
                INSERT INTO assistant_outbound_messages (
                  id, draft_id, identity_id, channel, recipient,
                  provider_message_id, status, body_hash, confirmation_actor,
                  provider_result, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, '', %s, %s, %s, %s, %s, %s)
                ON CONFLICT (draft_id) DO UPDATE SET
                  status = EXCLUDED.status,
                  confirmation_actor = EXCLUDED.confirmation_actor,
                  provider_result = EXCLUDED.provider_result,
                  updated_at = EXCLUDED.updated_at
                """,
                (
                    uuid4(),
                    transitioned["draft_id"],
                    transitioned["identity_id"],
                    transitioned["channel"],
                    transitioned["recipient"],
                    transitioned.get("status", "sending"),
                    transitioned.get("body_hash", ""),
                    transitioned.get("confirmation_actor", ""),
                    Jsonb(transitioned.get("provider_result") or {}),
                    transitioned.get("sent_at") or transitioned.get("called_at") or claimed_at,
                    transitioned.get("updated_at") or claimed_at,
                ),
            )
        return dict(row[0])

    def invalidate_confirmations(self, draft_id: str, *, invalidated_at: object) -> None:
        with self.connection_factory() as connection:
            connection.execute(
                """
                UPDATE assistant_outbound_confirmations
                SET invalidated_at = %s, updated_at = %s
                WHERE draft_id = %s AND consumed_at IS NULL
                """,
                (invalidated_at, self._now(), draft_id),
            )

    def record_delivery_receipt(
        self,
        *,
        identity_id: str,
        provider_message_id: str,
        status: str,
        receipt_payload: dict,
        occurred_at: datetime,
    ) -> dict:
        with self.connection_factory() as connection:
            outbound = connection.execute(
                """
                SELECT id, draft_id
                FROM assistant_outbound_messages
                WHERE identity_id = %s AND provider_message_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (identity_id, provider_message_id),
            ).fetchone()
            if outbound is None:
                raise KeyError("outbound_message_not_found")
            receipt_id = uuid4()
            connection.execute(
                """
                INSERT INTO assistant_delivery_receipts (
                  id, outbound_message_id, identity_id, provider_message_id,
                  status, receipt_payload, occurred_at, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    receipt_id,
                    outbound[0],
                    identity_id,
                    provider_message_id,
                    status,
                    Jsonb(receipt_payload),
                    occurred_at,
                    self._now(),
                ),
            )
            connection.execute(
                """
                UPDATE assistant_outbound_messages
                SET status = %s, updated_at = %s
                WHERE id = %s
                """,
                (status, occurred_at, outbound[0]),
            )
            connection.execute(
                """
                UPDATE assistant_message_drafts
                SET status = %s,
                    state = jsonb_set(state, '{status}', to_jsonb(%s::text), true),
                    updated_at = %s
                WHERE draft_id = %s
                """,
                (status, status, occurred_at, outbound[1]),
            )
        return {
            "receipt_id": str(receipt_id),
            "draft_id": str(outbound[1]),
            "identity_id": identity_id,
            "provider_message_id": provider_message_id,
            "status": status,
            "receipt_payload": copy.deepcopy(receipt_payload),
            "occurred_at": occurred_at.isoformat(),
        }
