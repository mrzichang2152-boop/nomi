from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime
from typing import Callable, ContextManager, MutableMapping, Protocol
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.assistant_identity.models import (
    AssistantCredentialRef,
    AssistantIdentity,
    AssistantIdentityHealthCheck,
    _utcnow,
)


class AssistantIdentityVersionConflict(RuntimeError):
    def __init__(self, identity_id: str, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"assistant_identity_version_conflict:{identity_id}:"
            f"expected={expected_version}:actual={actual_version}"
        )
        self.identity_id = identity_id
        self.expected_version = expected_version
        self.actual_version = actual_version


class AssistantIdentityRepository(Protocol):
    def add_if_missing(self, identity: AssistantIdentity) -> AssistantIdentity:
        ...

    def list(self) -> list[AssistantIdentity]:
        ...

    def get(self, identity_id: str) -> AssistantIdentity | None:
        ...

    def save(
        self,
        identity: AssistantIdentity,
        *,
        expected_version: int,
    ) -> AssistantIdentity:
        ...


class InMemoryAssistantIdentityRepository:
    def __init__(
        self,
        *,
        records: MutableMapping[str, AssistantIdentity] | None = None,
    ) -> None:
        self._records = records if records is not None else {}
        self._lock = threading.RLock()

    def add_if_missing(self, identity: AssistantIdentity) -> AssistantIdentity:
        with self._lock:
            current = self._records.get(identity.identity_id)
            if current is not None:
                return current
            self._records[identity.identity_id] = identity
            return identity

    def list(self) -> list[AssistantIdentity]:
        with self._lock:
            return list(self._records.values())

    def get(self, identity_id: str) -> AssistantIdentity | None:
        with self._lock:
            return self._records.get(identity_id)

    def save(
        self,
        identity: AssistantIdentity,
        *,
        expected_version: int,
    ) -> AssistantIdentity:
        with self._lock:
            current = self._records.get(identity.identity_id)
            if current is None:
                raise KeyError(identity.identity_id)
            if current.version != expected_version:
                raise AssistantIdentityVersionConflict(
                    identity.identity_id,
                    expected_version,
                    current.version,
                )
            updated = replace(
                identity,
                version=current.version + 1,
                created_at=current.created_at,
                updated_at=_utcnow(),
            )
            self._records[updated.identity_id] = updated
            return updated


class PostgresAssistantIdentityRepository:
    _COLUMNS = (
        "identity_id, kind, provider, display_name, address, status, capabilities, "
        "metadata, version, last_verified_at, last_error_code, created_at, updated_at"
    )

    def __init__(self, connection_factory: Callable[[], ContextManager[object]]) -> None:
        self.connection_factory = connection_factory

    @staticmethod
    def _identity(row: object) -> AssistantIdentity | None:
        if row is None:
            return None
        values = tuple(row)
        return AssistantIdentity(
            identity_id=str(values[0]),
            kind=str(values[1]),
            provider=str(values[2] or ""),
            display_name=str(values[3]),
            address=str(values[4] or ""),
            status=str(values[5]),
            capabilities=list(values[6] or []),
            metadata=dict(values[7] or {}),
            version=int(values[8]),
            last_verified_at=values[9],
            last_error_code=str(values[10] or ""),
            created_at=values[11],
            updated_at=values[12],
        )

    def add_if_missing(self, identity: AssistantIdentity) -> AssistantIdentity:
        with self.connection_factory() as connection:
            row = connection.execute(
                f"""
                INSERT INTO assistant_identities (
                  id, identity_id, kind, provider, display_name, address, status,
                  capabilities, metadata, version, last_verified_at, last_error_code,
                  created_at, updated_at
                ) VALUES (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (identity_id) DO NOTHING
                RETURNING {self._COLUMNS}
                """,
                (
                    uuid4(),
                    identity.identity_id,
                    identity.kind,
                    identity.provider,
                    identity.display_name,
                    identity.address,
                    identity.status,
                    Jsonb(identity.capabilities),
                    Jsonb(identity.metadata),
                    identity.version,
                    identity.last_verified_at,
                    identity.last_error_code,
                    identity.created_at,
                    identity.updated_at,
                ),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    f"SELECT {self._COLUMNS} FROM assistant_identities WHERE identity_id = %s",
                    (identity.identity_id,),
                ).fetchone()
        stored = self._identity(row)
        if stored is None:
            raise RuntimeError("assistant_identity_bootstrap_failed")
        return stored

    def list(self) -> list[AssistantIdentity]:
        with self.connection_factory() as connection:
            rows = connection.execute(
                f"SELECT {self._COLUMNS} FROM assistant_identities ORDER BY created_at, identity_id"
            ).fetchall()
        return [identity for row in rows if (identity := self._identity(row)) is not None]

    def get(self, identity_id: str) -> AssistantIdentity | None:
        with self.connection_factory() as connection:
            row = connection.execute(
                f"SELECT {self._COLUMNS} FROM assistant_identities WHERE identity_id = %s",
                (identity_id,),
            ).fetchone()
        return self._identity(row)

    def save(
        self,
        identity: AssistantIdentity,
        *,
        expected_version: int,
    ) -> AssistantIdentity:
        now = _utcnow()
        with self.connection_factory() as connection:
            row = connection.execute(
                f"""
                UPDATE assistant_identities
                SET kind = %s,
                    provider = %s,
                    display_name = %s,
                    address = %s,
                    status = %s,
                    capabilities = %s,
                    metadata = %s,
                    version = version + 1,
                    last_verified_at = %s,
                    last_error_code = %s,
                    updated_at = %s
                WHERE identity_id = %s AND version = %s
                RETURNING {self._COLUMNS}
                """,
                (
                    identity.kind,
                    identity.provider,
                    identity.display_name,
                    identity.address,
                    identity.status,
                    Jsonb(identity.capabilities),
                    Jsonb(identity.metadata),
                    identity.last_verified_at,
                    identity.last_error_code,
                    now,
                    identity.identity_id,
                    expected_version,
                ),
            ).fetchone()
            if row is None:
                current = connection.execute(
                    "SELECT version FROM assistant_identities WHERE identity_id = %s",
                    (identity.identity_id,),
                ).fetchone()
                if current is None:
                    raise KeyError(identity.identity_id)
                raise AssistantIdentityVersionConflict(
                    identity.identity_id,
                    expected_version,
                    int(current[0]),
                )
        updated = self._identity(row)
        if updated is None:
            raise RuntimeError("assistant_identity_update_failed")
        return updated


class AssistantCredentialRepository(Protocol):
    def get(self, identity_id: str, provider: str) -> AssistantCredentialRef | None:
        ...

    def put(self, credential: AssistantCredentialRef) -> AssistantCredentialRef:
        ...

    def delete(self, identity_id: str, provider: str) -> bool:
        ...


class InMemoryAssistantCredentialRepository:
    def __init__(
        self,
        *,
        records: MutableMapping[tuple[str, str], AssistantCredentialRef] | None = None,
    ) -> None:
        self._records = records if records is not None else {}
        self._lock = threading.RLock()

    def get(self, identity_id: str, provider: str) -> AssistantCredentialRef | None:
        with self._lock:
            return self._records.get((identity_id, provider))

    def put(self, credential: AssistantCredentialRef) -> AssistantCredentialRef:
        with self._lock:
            stored = replace(credential, updated_at=_utcnow())
            self._records[(stored.identity_id, stored.provider)] = stored
            return stored

    def delete(self, identity_id: str, provider: str) -> bool:
        with self._lock:
            return self._records.pop((identity_id, provider), None) is not None


class PostgresAssistantCredentialRepository:
    _COLUMNS = (
        "identity_id, provider, encrypted_ref, status, expires_at, metadata, updated_at"
    )

    def __init__(self, connection_factory: Callable[[], ContextManager[object]]) -> None:
        self.connection_factory = connection_factory

    @staticmethod
    def _credential(row: object) -> AssistantCredentialRef | None:
        if row is None:
            return None
        values = tuple(row)
        return AssistantCredentialRef(
            identity_id=str(values[0]),
            provider=str(values[1]),
            encrypted_ref=str(values[2] or ""),
            status=str(values[3]),
            expires_at=values[4],
            metadata=dict(values[5] or {}),
            updated_at=values[6],
        )

    def get(self, identity_id: str, provider: str) -> AssistantCredentialRef | None:
        with self.connection_factory() as connection:
            row = connection.execute(
                f"""
                SELECT {self._COLUMNS}
                FROM assistant_identity_credentials
                WHERE identity_id = %s AND provider = %s
                """,
                (identity_id, provider),
            ).fetchone()
        return self._credential(row)

    def put(self, credential: AssistantCredentialRef) -> AssistantCredentialRef:
        now = _utcnow()
        with self.connection_factory() as connection:
            row = connection.execute(
                f"""
                INSERT INTO assistant_identity_credentials (
                  id, identity_id, provider, encrypted_ref, status, expires_at,
                  metadata, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (identity_id, provider) DO UPDATE SET
                  encrypted_ref = EXCLUDED.encrypted_ref,
                  status = EXCLUDED.status,
                  expires_at = EXCLUDED.expires_at,
                  metadata = EXCLUDED.metadata,
                  updated_at = EXCLUDED.updated_at
                RETURNING {self._COLUMNS}
                """,
                (
                    uuid4(),
                    credential.identity_id,
                    credential.provider,
                    credential.encrypted_ref,
                    credential.status,
                    credential.expires_at,
                    Jsonb(credential.metadata),
                    now,
                ),
            ).fetchone()
        stored = self._credential(row)
        if stored is None:
            raise RuntimeError("assistant_credential_store_failed")
        return stored

    def delete(self, identity_id: str, provider: str) -> bool:
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                DELETE FROM assistant_identity_credentials
                WHERE identity_id = %s AND provider = %s
                RETURNING identity_id
                """,
                (identity_id, provider),
            ).fetchone()
        return row is not None


class AssistantIdentityHealthRepository(Protocol):
    def append(self, check: AssistantIdentityHealthCheck) -> AssistantIdentityHealthCheck:
        ...

    def list(self, identity_id: str) -> list[AssistantIdentityHealthCheck]:
        ...


class InMemoryAssistantIdentityHealthRepository:
    def __init__(self) -> None:
        self._records: list[AssistantIdentityHealthCheck] = []
        self._lock = threading.RLock()

    def append(self, check: AssistantIdentityHealthCheck) -> AssistantIdentityHealthCheck:
        with self._lock:
            self._records.append(check)
            return check

    def list(self, identity_id: str) -> list[AssistantIdentityHealthCheck]:
        with self._lock:
            return sorted(
                (item for item in self._records if item.identity_id == identity_id),
                key=lambda item: item.checked_at,
                reverse=True,
            )


class PostgresAssistantIdentityHealthRepository:
    _COLUMNS = (
        "id, identity_id, check_type, status, latency_ms, error_code, details, checked_at"
    )

    def __init__(self, connection_factory: Callable[[], ContextManager[object]]) -> None:
        self.connection_factory = connection_factory

    @staticmethod
    def _check(row: object) -> AssistantIdentityHealthCheck | None:
        if row is None:
            return None
        values = tuple(row)
        return AssistantIdentityHealthCheck(
            check_id=str(values[0]),
            identity_id=str(values[1]),
            check_type=str(values[2]),
            status=str(values[3]),
            latency_ms=int(values[4]) if values[4] is not None else None,
            error_code=str(values[5] or ""),
            details=dict(values[6] or {}),
            checked_at=values[7],
        )

    def append(self, check: AssistantIdentityHealthCheck) -> AssistantIdentityHealthCheck:
        with self.connection_factory() as connection:
            row = connection.execute(
                f"""
                INSERT INTO assistant_identity_health_checks (
                  id, identity_id, check_type, status, latency_ms, error_code,
                  details, checked_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {self._COLUMNS}
                """,
                (
                    check.check_id,
                    check.identity_id,
                    check.check_type,
                    check.status,
                    check.latency_ms,
                    check.error_code,
                    Jsonb(check.details),
                    check.checked_at,
                ),
            ).fetchone()
        stored = self._check(row)
        if stored is None:
            raise RuntimeError("assistant_identity_health_append_failed")
        return stored

    def list(self, identity_id: str) -> list[AssistantIdentityHealthCheck]:
        with self.connection_factory() as connection:
            rows = connection.execute(
                f"""
                SELECT {self._COLUMNS}
                FROM assistant_identity_health_checks
                WHERE identity_id = %s
                ORDER BY checked_at DESC, id DESC
                """,
                (identity_id,),
            ).fetchall()
        return [check for row in rows if (check := self._check(row)) is not None]
