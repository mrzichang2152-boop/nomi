from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO, Callable, Optional, Protocol, Union
from uuid import UUID, uuid4

from app.attachments.detection import detect_attachment
from app.attachments.models import (
    AttachmentErrorCode,
    AttachmentLimits,
    AttachmentRejected,
    SAFE_ATTACHMENT_ERROR_MESSAGES,
)
from app.attachments.queue import RedisAttachmentQueue
from app.attachments.repository import AttachmentRecord, AttachmentRepository
from app.attachments.storage import resolve_storage_path, sanitize_display_filename, write_streamed_original


PROCESSING_VERSION = "attachment-v1"
CLIENT_UPLOAD_ID_CONFLICT_MESSAGE = "同一上传标识对应了不同文件，请重新选择文件。"


class AttachmentQueue(Protocol):
    def enqueue(self, attachment_id: UUID) -> None:
        ...


class AttachmentUploadError(RuntimeError):
    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        http_status: int,
        attachment_id: Optional[UUID] = None,
    ) -> None:
        self.code = code
        self.safe_message = safe_message
        self.http_status = http_status
        self.attachment_id = attachment_id
        super().__init__(safe_message)


@dataclass(frozen=True)
class UploadedAttachment:
    record: AttachmentRecord
    duplicate: bool = False


class AttachmentService:
    def __init__(
        self,
        *,
        repository: AttachmentRepository,
        storage_root: Union[str, Path],
        queue: AttachmentQueue,
        limits: Optional[AttachmentLimits] = None,
        now: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.repository = repository
        self.storage_root = Path(storage_root)
        self.queue = queue
        self.limits = limits or AttachmentLimits()
        self.now = now or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _normalize_client_upload_id(value: Optional[str]) -> Optional[str]:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        if len(normalized) > 200 or any(ord(character) < 32 for character in normalized):
            raise AttachmentUploadError(
                "invalid_client_upload_id",
                "上传标识无效，请重新选择文件。",
                http_status=422,
            )
        return normalized

    def _new_record(
        self,
        *,
        attachment_id: UUID,
        client_upload_id: Optional[str],
        original_filename: str,
        declared_mime_type: Optional[str],
    ) -> AttachmentRecord:
        return AttachmentRecord(
            attachment_id=attachment_id,
            client_upload_id=client_upload_id,
            original_filename=original_filename,
            safe_filename=sanitize_display_filename(original_filename),
            declared_mime_type=declared_mime_type,
            detected_mime_type=None,
            extension=None,
            byte_size=0,
            sha256=None,
            storage_relative_path=None,
            status="receiving",
            lifecycle="draft",
            parser_kind=None,
            processing_version=PROCESSING_VERSION,
            error_code=None,
            error_detail_safe=None,
            created_at=self.now(),
            stored_at=None,
            processed_at=None,
            attached_at=None,
            expires_at=None,
            deleted_at=None,
        )

    def _delete_stored_path(self, relative_path: str) -> None:
        path = resolve_storage_path(self.storage_root, relative_path)
        if path.exists():
            path.unlink()

    def _upload_error(
        self,
        rejected: AttachmentRejected,
        attachment_id: UUID,
    ) -> AttachmentUploadError:
        status = 413 if rejected.code == AttachmentErrorCode.TOO_LARGE.value else 422
        return AttachmentUploadError(
            rejected.code,
            rejected.safe_message,
            http_status=status,
            attachment_id=attachment_id,
        )

    def _resolve_duplicate(
        self,
        existing: AttachmentRecord,
        source: BinaryIO,
        *,
        original_filename: str,
    ) -> UploadedAttachment:
        comparison_id = uuid4()
        try:
            comparison = write_streamed_original(
                source,
                self.storage_root,
                comparison_id,
                original_filename=original_filename,
                max_bytes=self.limits.max_file_bytes,
            )
        except AttachmentRejected as rejected:
            raise AttachmentUploadError(
                "client_upload_id_conflict",
                CLIENT_UPLOAD_ID_CONFLICT_MESSAGE,
                http_status=409,
                attachment_id=existing.attachment_id,
            ) from rejected
        self._delete_stored_path(comparison.relative_path)
        if existing.sha256 != comparison.sha256 or existing.byte_size != comparison.byte_size:
            raise AttachmentUploadError(
                "client_upload_id_conflict",
                CLIENT_UPLOAD_ID_CONFLICT_MESSAGE,
                http_status=409,
                attachment_id=existing.attachment_id,
            )
        if existing.status == "rejected":
            code = existing.error_code or AttachmentErrorCode.UNSUPPORTED_TYPE.value
            message = existing.error_detail_safe or SAFE_ATTACHMENT_ERROR_MESSAGES[AttachmentErrorCode(code)]
            raise AttachmentUploadError(code, message, http_status=422, attachment_id=existing.attachment_id)
        if existing.status not in {"stored", "processing", "ready"}:
            raise AttachmentUploadError(
                "client_upload_id_in_progress",
                "同一文件正在处理中，请稍后重试。",
                http_status=409,
                attachment_id=existing.attachment_id,
            )
        return UploadedAttachment(existing, duplicate=True)

    def upload(
        self,
        source: BinaryIO,
        *,
        original_filename: str,
        declared_mime_type: Optional[str],
        client_upload_id: Optional[str],
    ) -> UploadedAttachment:
        normalized_upload_id = self._normalize_client_upload_id(client_upload_id)
        if normalized_upload_id:
            existing = self.repository.find_by_client_upload_id(normalized_upload_id)
            if existing is not None:
                return self._resolve_duplicate(existing, source, original_filename=original_filename)

        attachment_id = uuid4()
        receiving = self.repository.create_receiving(
            self._new_record(
                attachment_id=attachment_id,
                client_upload_id=normalized_upload_id,
                original_filename=original_filename,
                declared_mime_type=declared_mime_type,
            )
        )
        if receiving.attachment_id != attachment_id:
            return self._resolve_duplicate(receiving, source, original_filename=original_filename)

        try:
            stored = write_streamed_original(
                source,
                self.storage_root,
                attachment_id,
                original_filename=original_filename,
                max_bytes=self.limits.max_file_bytes,
            )
        except AttachmentRejected as rejected:
            self.repository.mark_rejected(
                attachment_id,
                error_code=rejected.code,
                error_detail_safe=rejected.safe_message,
            )
            raise self._upload_error(rejected, attachment_id) from rejected
        except Exception as exc:
            safe_message = SAFE_ATTACHMENT_ERROR_MESSAGES[AttachmentErrorCode.STORAGE_FAILED]
            self.repository.mark_failed(
                attachment_id,
                error_code=AttachmentErrorCode.STORAGE_FAILED.value,
                error_detail_safe=safe_message,
            )
            raise AttachmentUploadError(
                AttachmentErrorCode.STORAGE_FAILED.value,
                safe_message,
                http_status=503,
                attachment_id=attachment_id,
            ) from exc

        absolute_path = resolve_storage_path(self.storage_root, stored.relative_path)
        try:
            detected = detect_attachment(
                absolute_path,
                stored.safe_display_filename,
                declared_mime_type=declared_mime_type,
            )
        except AttachmentRejected as rejected:
            self._delete_stored_path(stored.relative_path)
            self.repository.mark_rejected(
                attachment_id,
                sha256=stored.sha256,
                byte_size=stored.byte_size,
                storage_relative_path=None,
                error_code=rejected.code,
                error_detail_safe=rejected.safe_message,
            )
            raise self._upload_error(rejected, attachment_id) from rejected

        stored_at = self.now()
        record = self.repository.mark_stored(
            attachment_id,
            sha256=stored.sha256,
            byte_size=stored.byte_size,
            storage_relative_path=stored.relative_path,
            detected_mime_type=detected.mime_type,
            extension=detected.extension,
            parser_kind=detected.parser_kind,
            error_code=None,
            error_detail_safe=None,
            stored_at=stored_at,
            expires_at=stored_at + timedelta(hours=24),
        )
        try:
            self.queue.enqueue(attachment_id)
        except Exception as exc:
            safe_message = "文件已保存，但处理队列暂时不可用，请重试。"
            self.repository.mark_failed(
                attachment_id,
                error_code=AttachmentErrorCode.PARSE_FAILED.value,
                error_detail_safe=safe_message,
            )
            raise AttachmentUploadError(
                AttachmentErrorCode.PARSE_FAILED.value,
                safe_message,
                http_status=503,
                attachment_id=attachment_id,
            ) from exc
        return UploadedAttachment(record)


__all__ = [
    "AttachmentQueue",
    "AttachmentService",
    "AttachmentUploadError",
    "RedisAttachmentQueue",
    "UploadedAttachment",
]
