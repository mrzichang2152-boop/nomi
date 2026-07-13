from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, ContextManager, Optional, Protocol, Sequence
from uuid import UUID


@dataclass(frozen=True)
class AttachmentRecord:
    attachment_id: UUID
    client_upload_id: Optional[str]
    original_filename: str
    safe_filename: str
    declared_mime_type: Optional[str]
    detected_mime_type: Optional[str]
    extension: Optional[str]
    byte_size: int
    sha256: Optional[str]
    storage_relative_path: Optional[str]
    status: str
    lifecycle: str
    parser_kind: Optional[str]
    processing_version: str
    error_code: Optional[str]
    error_detail_safe: Optional[str]
    created_at: datetime
    stored_at: Optional[datetime]
    processed_at: Optional[datetime]
    attached_at: Optional[datetime]
    expires_at: Optional[datetime]
    deleted_at: Optional[datetime]


class AttachmentRepository(Protocol):
    def create_receiving(self, record: AttachmentRecord) -> AttachmentRecord:
        ...

    def get(self, attachment_id: UUID) -> Optional[AttachmentRecord]:
        ...

    def find_by_client_upload_id(self, client_upload_id: str) -> Optional[AttachmentRecord]:
        ...

    def mark_stored(self, attachment_id: UUID, **changes: object) -> AttachmentRecord:
        ...

    def mark_rejected(self, attachment_id: UUID, **changes: object) -> AttachmentRecord:
        ...

    def mark_failed(self, attachment_id: UUID, **changes: object) -> AttachmentRecord:
        ...

    def mark_processing(self, attachment_id: UUID) -> Optional[AttachmentRecord]:
        ...

    def mark_ready(self, attachment_id: UUID, **changes: object) -> AttachmentRecord:
        ...

    def mark_attached(self, attachment_id: UUID, *, attached_at: datetime) -> AttachmentRecord:
        ...

    def list_expired_drafts(
        self,
        *,
        now: datetime,
        stale_receiving_before: datetime,
    ) -> Sequence[AttachmentRecord]:
        ...

    def mark_lifecycle_deleted(self, attachment_id: UUID) -> Optional[AttachmentRecord]:
        ...

    def complete_deleted(self, attachment_id: UUID, *, deleted_at: datetime) -> AttachmentRecord:
        ...


class InMemoryAttachmentRepository:
    def __init__(self) -> None:
        self._records: dict[UUID, AttachmentRecord] = {}
        self._client_upload_ids: dict[str, UUID] = {}
        self._lock = threading.RLock()

    def create_receiving(self, record: AttachmentRecord) -> AttachmentRecord:
        with self._lock:
            if record.client_upload_id and record.client_upload_id in self._client_upload_ids:
                existing_id = self._client_upload_ids[record.client_upload_id]
                return self._records[existing_id]
            self._records[record.attachment_id] = record
            if record.client_upload_id:
                self._client_upload_ids[record.client_upload_id] = record.attachment_id
            return record

    def get(self, attachment_id: UUID) -> Optional[AttachmentRecord]:
        with self._lock:
            return self._records.get(attachment_id)

    def find_by_client_upload_id(self, client_upload_id: str) -> Optional[AttachmentRecord]:
        with self._lock:
            attachment_id = self._client_upload_ids.get(client_upload_id)
            return self._records.get(attachment_id) if attachment_id else None

    def _update(self, attachment_id: UUID, **changes: object) -> AttachmentRecord:
        with self._lock:
            current = self._records[attachment_id]
            updated = replace(current, **changes)
            self._records[attachment_id] = updated
            return updated

    def mark_stored(self, attachment_id: UUID, **changes: object) -> AttachmentRecord:
        return self._update(attachment_id, status="stored", **changes)

    def mark_rejected(self, attachment_id: UUID, **changes: object) -> AttachmentRecord:
        return self._update(attachment_id, status="rejected", **changes)

    def mark_failed(self, attachment_id: UUID, **changes: object) -> AttachmentRecord:
        return self._update(attachment_id, status="failed", **changes)

    def mark_processing(self, attachment_id: UUID) -> Optional[AttachmentRecord]:
        with self._lock:
            current = self._records.get(attachment_id)
            if current is None or current.lifecycle == "deleted":
                return None
            if current.status not in {"stored", "failed", "processing"}:
                return None
            updated = replace(
                current,
                status="processing",
                error_code=None,
                error_detail_safe=None,
            )
            self._records[attachment_id] = updated
            return updated

    def mark_ready(self, attachment_id: UUID, **changes: object) -> AttachmentRecord:
        return self._update(
            attachment_id,
            status="ready",
            error_code=None,
            error_detail_safe=None,
            **changes,
        )

    def mark_attached(self, attachment_id: UUID, *, attached_at: datetime) -> AttachmentRecord:
        return self._update(
            attachment_id,
            lifecycle="attached",
            attached_at=attached_at,
            expires_at=None,
        )

    def list_expired_drafts(
        self,
        *,
        now: datetime,
        stale_receiving_before: datetime,
    ) -> Sequence[AttachmentRecord]:
        with self._lock:
            return sorted(
                (
                    record
                    for record in self._records.values()
                    if record.lifecycle == "draft"
                    and (
                        (record.expires_at is not None and record.expires_at <= now)
                        or (record.status == "receiving" and record.created_at <= stale_receiving_before)
                    )
                ),
                key=lambda record: (record.created_at, str(record.attachment_id)),
            )

    def mark_lifecycle_deleted(self, attachment_id: UUID) -> Optional[AttachmentRecord]:
        with self._lock:
            current = self._records.get(attachment_id)
            if current is None or current.lifecycle != "draft":
                return None
            updated = replace(current, lifecycle="deleted", deleted_at=None)
            self._records[attachment_id] = updated
            return updated

    def complete_deleted(self, attachment_id: UUID, *, deleted_at: datetime) -> AttachmentRecord:
        with self._lock:
            current = self._records[attachment_id]
            if current.lifecycle != "deleted":
                raise ValueError("attachment_not_marked_deleted")
            updated = replace(current, deleted_at=deleted_at)
            self._records[attachment_id] = updated
            return updated

    def count(self) -> int:
        with self._lock:
            return len(self._records)


class PostgresAttachmentRepository:
    _COLUMNS = (
        "id, client_upload_id, original_filename, safe_filename, declared_mime_type, "
        "detected_mime_type, extension, byte_size, sha256, storage_relative_path, status, "
        "lifecycle, parser_kind, processing_version, error_code, error_detail_safe, "
        "created_at, stored_at, processed_at, attached_at, expires_at, deleted_at"
    )

    def __init__(self, connection_factory: Callable[[], ContextManager[object]]) -> None:
        self.connection_factory = connection_factory

    @staticmethod
    def _record(row: object) -> Optional[AttachmentRecord]:
        if row is None:
            return None
        values = tuple(row)
        return AttachmentRecord(
            attachment_id=values[0],
            client_upload_id=values[1],
            original_filename=values[2],
            safe_filename=values[3],
            declared_mime_type=values[4],
            detected_mime_type=values[5],
            extension=values[6],
            byte_size=values[7],
            sha256=values[8],
            storage_relative_path=values[9],
            status=values[10],
            lifecycle=values[11],
            parser_kind=values[12],
            processing_version=values[13],
            error_code=values[14],
            error_detail_safe=values[15],
            created_at=values[16],
            stored_at=values[17],
            processed_at=values[18],
            attached_at=values[19],
            expires_at=values[20],
            deleted_at=values[21],
        )

    def create_receiving(self, record: AttachmentRecord) -> AttachmentRecord:
        with self.connection_factory() as connection:
            cursor = connection.execute(
                f"""
                INSERT INTO chat_attachments (
                  id, client_upload_id, original_filename, safe_filename, declared_mime_type,
                  detected_mime_type, extension, byte_size, sha256, storage_relative_path,
                  status, lifecycle, parser_kind, processing_version, error_code,
                  error_detail_safe, created_at, stored_at, processed_at, attached_at,
                  expires_at, deleted_at
                ) VALUES (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (client_upload_id) WHERE client_upload_id IS NOT NULL
                DO NOTHING
                RETURNING {self._COLUMNS}
                """,
                (
                    record.attachment_id,
                    record.client_upload_id,
                    record.original_filename,
                    record.safe_filename,
                    record.declared_mime_type,
                    record.detected_mime_type,
                    record.extension,
                    record.byte_size,
                    record.sha256,
                    record.storage_relative_path,
                    record.status,
                    record.lifecycle,
                    record.parser_kind,
                    record.processing_version,
                    record.error_code,
                    record.error_detail_safe,
                    record.created_at,
                    record.stored_at,
                    record.processed_at,
                    record.attached_at,
                    record.expires_at,
                    record.deleted_at,
                ),
            )
            inserted = self._record(cursor.fetchone())
        if inserted is not None:
            return inserted
        if record.client_upload_id:
            existing = self.find_by_client_upload_id(record.client_upload_id)
            if existing is not None:
                return existing
        raise RuntimeError("attachment_receiving_insert_failed")

    def get(self, attachment_id: UUID) -> Optional[AttachmentRecord]:
        with self.connection_factory() as connection:
            row = connection.execute(
                f"SELECT {self._COLUMNS} FROM chat_attachments WHERE id = %s",
                (attachment_id,),
            ).fetchone()
        return self._record(row)

    def find_by_client_upload_id(self, client_upload_id: str) -> Optional[AttachmentRecord]:
        with self.connection_factory() as connection:
            row = connection.execute(
                f"SELECT {self._COLUMNS} FROM chat_attachments WHERE client_upload_id = %s",
                (client_upload_id,),
            ).fetchone()
        return self._record(row)

    def _update(
        self,
        attachment_id: UUID,
        *,
        status: Optional[str],
        changes: dict[str, object],
    ) -> AttachmentRecord:
        allowed = {
            "sha256",
            "byte_size",
            "storage_relative_path",
            "detected_mime_type",
            "extension",
            "parser_kind",
            "error_code",
            "error_detail_safe",
            "stored_at",
            "expires_at",
            "processed_at",
            "attached_at",
            "lifecycle",
            "deleted_at",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unsupported_attachment_update:{','.join(sorted(unknown))}")
        assignments: list[str] = []
        values: list[object] = []
        if status is not None:
            assignments.append("status = %s")
            values.append(status)
        for key, value in changes.items():
            assignments.append(f"{key} = %s")
            values.append(value)
        values.append(attachment_id)
        with self.connection_factory() as connection:
            row = connection.execute(
                f"""
                UPDATE chat_attachments
                SET {', '.join(assignments)}
                WHERE id = %s
                RETURNING {self._COLUMNS}
                """,
                tuple(values),
            ).fetchone()
        record = self._record(row)
        if record is None:
            raise KeyError(str(attachment_id))
        return record

    def mark_stored(self, attachment_id: UUID, **changes: object) -> AttachmentRecord:
        return self._update(attachment_id, status="stored", changes=changes)

    def mark_rejected(self, attachment_id: UUID, **changes: object) -> AttachmentRecord:
        return self._update(attachment_id, status="rejected", changes=changes)

    def mark_failed(self, attachment_id: UUID, **changes: object) -> AttachmentRecord:
        return self._update(attachment_id, status="failed", changes=changes)

    def mark_processing(self, attachment_id: UUID) -> Optional[AttachmentRecord]:
        with self.connection_factory() as connection:
            locked = connection.execute(
                f"""
                SELECT {self._COLUMNS}
                FROM chat_attachments
                WHERE id = %s
                  AND lifecycle <> 'deleted'
                  AND status IN ('stored', 'failed', 'processing')
                FOR UPDATE SKIP LOCKED
                """,
                (attachment_id,),
            ).fetchone()
            if locked is None:
                return None
            row = connection.execute(
                f"""
                UPDATE chat_attachments
                SET status = 'processing', error_code = NULL, error_detail_safe = NULL
                WHERE id = %s
                RETURNING {self._COLUMNS}
                """,
                (attachment_id,),
            ).fetchone()
        return self._record(row)

    def mark_ready(self, attachment_id: UUID, **changes: object) -> AttachmentRecord:
        return self._update(
            attachment_id,
            status="ready",
            changes={"error_code": None, "error_detail_safe": None, **changes},
        )

    def mark_attached(self, attachment_id: UUID, *, attached_at: datetime) -> AttachmentRecord:
        return self._update(
            attachment_id,
            status=None,
            changes={"lifecycle": "attached", "attached_at": attached_at, "expires_at": None},
        )

    def list_expired_drafts(
        self,
        *,
        now: datetime,
        stale_receiving_before: datetime,
    ) -> Sequence[AttachmentRecord]:
        with self.connection_factory() as connection:
            rows = connection.execute(
                f"""
                SELECT {self._COLUMNS}
                FROM chat_attachments
                WHERE lifecycle = 'draft'
                  AND (
                    (expires_at IS NOT NULL AND expires_at <= %s)
                    OR (status = 'receiving' AND created_at <= %s)
                  )
                ORDER BY created_at, id
                """,
                (now, stale_receiving_before),
            ).fetchall()
        return [record for row in rows if (record := self._record(row)) is not None]

    def mark_lifecycle_deleted(self, attachment_id: UUID) -> Optional[AttachmentRecord]:
        with self.connection_factory() as connection:
            row = connection.execute(
                f"""
                UPDATE chat_attachments
                SET lifecycle = 'deleted', deleted_at = NULL
                WHERE id = %s AND lifecycle = 'draft'
                RETURNING {self._COLUMNS}
                """,
                (attachment_id,),
            ).fetchone()
        return self._record(row)

    def complete_deleted(self, attachment_id: UUID, *, deleted_at: datetime) -> AttachmentRecord:
        record = self._update(
            attachment_id,
            status=None,
            changes={"deleted_at": deleted_at},
        )
        if record.lifecycle != "deleted":
            raise ValueError("attachment_not_marked_deleted")
        return record


__all__ = [
    "AttachmentRecord",
    "AttachmentRepository",
    "InMemoryAttachmentRepository",
    "PostgresAttachmentRepository",
]
