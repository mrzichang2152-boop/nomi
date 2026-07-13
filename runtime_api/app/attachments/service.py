from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO, Callable, Optional, Protocol, Sequence, Union
from uuid import UUID, uuid4

from app.attachments.detection import detect_attachment
from app.attachments.models import (
    DEFAULT_ATTACHMENT_ONLY_INSTRUCTION,
    AttachmentErrorCode,
    AttachmentLimits,
    AttachmentRejected,
    SAFE_ATTACHMENT_ERROR_MESSAGES,
    validate_chat_input,
)
from app.attachments.queue import RedisAttachmentQueue
from app.attachments.repository import AttachmentRecord, AttachmentRepository
from app.attachments.storage import resolve_storage_path, sanitize_display_filename, write_streamed_original


PROCESSING_VERSION = "attachment-v1"
CLIENT_UPLOAD_ID_CONFLICT_MESSAGE = "同一上传标识对应了不同文件，请重新选择文件。"


class AttachmentQueue(Protocol):
    def enqueue(
        self,
        attachment_id: UUID,
        processing_version: str = PROCESSING_VERSION,
    ) -> Optional[bool]:
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


class AttachmentLifecycleError(RuntimeError):
    def __init__(self, code: str, safe_message: str, *, http_status: int) -> None:
        self.code = code
        self.safe_message = safe_message
        self.http_status = http_status
        super().__init__(safe_message)


class AttachmentSubmissionError(RuntimeError):
    def __init__(self, code: str, safe_message: str, *, http_status: int) -> None:
        self.code = code
        self.safe_message = safe_message
        self.http_status = http_status
        super().__init__(safe_message)


@dataclass(frozen=True)
class UploadedAttachment:
    record: AttachmentRecord
    duplicate: bool = False


@dataclass(frozen=True)
class AttachmentContentReference:
    path: Path
    mime_type: str
    filename: str
    byte_size: int


class AttachmentSubmissionService:
    def __init__(
        self,
        *,
        limits: Optional[AttachmentLimits] = None,
        now: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.limits = limits or AttachmentLimits()
        self.now = now or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _input_error(exc: ValueError) -> AttachmentSubmissionError:
        code = str(exc)
        status, message = {
            "message_or_attachment_required": (422, "请输入消息或选择至少一个文件。"),
            "duplicate_attachment_id": (422, "同一条消息不能重复选择同一个文件。"),
            "too_many_attachments": (422, "单条消息选择的文件数量超过上限。"),
        }.get(code, (422, "消息或附件参数无效。"))
        return AttachmentSubmissionError(code, message, http_status=status)

    @staticmethod
    def _existing_turn(conn: Any, user_tool_call_id: Optional[str]) -> Optional[dict[str, Any]]:
        if not user_tool_call_id:
            return None
        row = conn.execute(
            """
            SELECT id, conversation_id, event_id, role, content
            FROM assistant_turns
            WHERE tool_call_id = %s AND role = 'user'
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (user_tool_call_id,),
        ).fetchone()
        if not row:
            return None
        bindings = conn.execute(
            """
            SELECT attachment_id
            FROM assistant_turn_attachments
            WHERE turn_id = %s
            ORDER BY ordinal ASC
            """,
            (row[0],),
        ).fetchall()
        return {
            "turn_id": str(row[0]),
            "conversation_id": str(row[1]),
            "event_id": str(row[2]),
            "role": str(row[3]),
            "content": str(row[4]) if len(row) > 4 else "",
            "attachment_ids": [str(binding[0]) for binding in bindings],
        }

    def _locked_drafts(self, conn: Any, attachment_ids: Sequence[UUID]) -> list[dict[str, Any]]:
        if not attachment_ids:
            return []
        rows = conn.execute(
            """
            SELECT id, status, lifecycle, byte_size, expires_at
            FROM chat_attachments
            WHERE id = ANY(%s)
            FOR UPDATE
            """,
            (list(attachment_ids),),
        ).fetchall()
        records = {
            str(row[0]): {
                "attachment_id": UUID(str(row[0])),
                "status": str(row[1]),
                "lifecycle": str(row[2]),
                "byte_size": int(row[3] or 0),
                "expires_at": row[4],
            }
            for row in rows
        }
        ordered: list[dict[str, Any]] = []
        for attachment_id in attachment_ids:
            record = records.get(str(attachment_id))
            if record is None or record["lifecycle"] == "deleted":
                raise AttachmentSubmissionError(
                    "attachment_not_found",
                    "未找到该文件。",
                    http_status=404,
                )
            ordered.append(record)
        return ordered

    def _validate_drafts(self, records: Sequence[dict[str, Any]]) -> None:
        active_now = self.now()
        aggregate_bytes = 0
        for record in records:
            if record["lifecycle"] == "attached":
                raise AttachmentSubmissionError(
                    AttachmentErrorCode.ATTACHMENT_ALREADY_ATTACHED.value,
                    SAFE_ATTACHMENT_ERROR_MESSAGES[AttachmentErrorCode.ATTACHMENT_ALREADY_ATTACHED],
                    http_status=409,
                )
            expires_at = record.get("expires_at")
            if expires_at is not None and expires_at <= active_now:
                raise AttachmentSubmissionError(
                    AttachmentErrorCode.ATTACHMENT_EXPIRED.value,
                    SAFE_ATTACHMENT_ERROR_MESSAGES[AttachmentErrorCode.ATTACHMENT_EXPIRED],
                    http_status=410,
                )
            if record["status"] != "ready":
                raise AttachmentSubmissionError(
                    AttachmentErrorCode.ATTACHMENT_NOT_READY.value,
                    SAFE_ATTACHMENT_ERROR_MESSAGES[AttachmentErrorCode.ATTACHMENT_NOT_READY],
                    http_status=409,
                )
            aggregate_bytes += int(record["byte_size"])
        if aggregate_bytes > self.limits.max_message_attachment_bytes:
            raise AttachmentSubmissionError(
                "attachments_too_large",
                "单条消息中的文件总大小超过允许上限。",
                http_status=413,
            )

    def submit_user_turn(
        self,
        *,
        conn: Any,
        redis_obj: Any,
        message: str,
        attachment_ids: Sequence[UUID],
        conversation_id: Optional[str],
        client_type: str,
        client_request_id: Optional[str],
        user_tool_call_id: Optional[str],
        persist_turn: Callable[..., dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            ordered_ids = [UUID(str(attachment_id)) for attachment_id in attachment_ids]
        except (TypeError, ValueError) as exc:
            raise AttachmentSubmissionError(
                "invalid_attachment_id",
                "文件标识无效，请重新选择文件。",
                http_status=422,
            ) from exc
        try:
            validate_chat_input(message, ordered_ids, self.limits)
        except ValueError as exc:
            raise self._input_error(exc) from exc
        content = message if message.strip() else DEFAULT_ATTACHMENT_ONLY_INSTRUCTION
        normalized_ids = [str(attachment_id) for attachment_id in ordered_ids]

        existing = self._existing_turn(conn, user_tool_call_id) if ordered_ids else None
        if existing is not None:
            if existing["content"] != content or existing["attachment_ids"] != normalized_ids:
                raise AttachmentSubmissionError(
                    "client_request_id_conflict",
                    "同一请求标识对应了不同的消息或文件，请重新发送。",
                    http_status=409,
                )
            return {**existing, "duplicate": True}

        records = self._locked_drafts(conn, ordered_ids)
        self._validate_drafts(records)
        turn = persist_turn(
            conn,
            redis_obj,
            role="user",
            content=content,
            conversation_id=conversation_id,
            client_type=client_type,
            tool_call_id=user_tool_call_id,
        )
        turn_id = str(turn["turn_id"])
        attached_at = self.now()
        for ordinal, attachment_id in enumerate(ordered_ids):
            conn.execute(
                """
                INSERT INTO assistant_turn_attachments (turn_id, attachment_id, ordinal, purpose)
                VALUES (%s, %s, %s, %s)
                """,
                (turn_id, attachment_id, ordinal, "user_context"),
            )
            updated = conn.execute(
                """
                UPDATE chat_attachments
                SET lifecycle = 'attached', attached_at = %s, expires_at = NULL
                WHERE id = %s AND lifecycle = 'draft'
                """,
                (attached_at, attachment_id),
            )
            if updated.rowcount != 1:
                raise AttachmentSubmissionError(
                    AttachmentErrorCode.ATTACHMENT_ALREADY_ATTACHED.value,
                    SAFE_ATTACHMENT_ERROR_MESSAGES[AttachmentErrorCode.ATTACHMENT_ALREADY_ATTACHED],
                    http_status=409,
                )
        return {
            **turn,
            "content": content,
            "attachment_ids": normalized_ids,
            "duplicate": False,
        }


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

    def _record_or_error(self, attachment_id: UUID, *, allow_expired: bool = False) -> AttachmentRecord:
        record = self.repository.get(attachment_id)
        if record is None or record.lifecycle == "deleted":
            raise AttachmentLifecycleError(
                "attachment_not_found",
                "未找到该文件。",
                http_status=404,
            )
        if (
            not allow_expired
            and record.lifecycle == "draft"
            and record.expires_at is not None
            and record.expires_at <= self.now()
        ):
            raise AttachmentLifecycleError(
                AttachmentErrorCode.ATTACHMENT_EXPIRED.value,
                SAFE_ATTACHMENT_ERROR_MESSAGES[AttachmentErrorCode.ATTACHMENT_EXPIRED],
                http_status=410,
            )
        return record

    @staticmethod
    def kind_for(record: AttachmentRecord) -> str:
        return {
            "image": "image",
            "pdf": "pdf",
            "docx": "document",
            "pptx": "presentation",
            "xlsx": "spreadsheet",
            "csv": "text",
            "txt": "text",
            "md": "text",
        }.get(record.parser_kind or "", "file")

    def get(self, attachment_id: UUID) -> AttachmentRecord:
        return self._record_or_error(attachment_id)

    def has_preview(self, record: AttachmentRecord) -> bool:
        if record.status != "ready" or record.parser_kind != "image":
            return False
        derivative = self.repository.get_derivative(
            record.attachment_id,
            kind="preview",
            processing_version=record.processing_version,
        )
        if derivative is None:
            return False
        try:
            return resolve_storage_path(self.storage_root, derivative.storage_relative_path).is_file()
        except AttachmentRejected:
            return False

    def preview(self, attachment_id: UUID) -> AttachmentContentReference:
        record = self._record_or_error(attachment_id)
        if record.status != "ready":
            raise AttachmentLifecycleError(
                AttachmentErrorCode.ATTACHMENT_NOT_READY.value,
                SAFE_ATTACHMENT_ERROR_MESSAGES[AttachmentErrorCode.ATTACHMENT_NOT_READY],
                http_status=409,
            )
        derivative = self.repository.get_derivative(
            attachment_id,
            kind="preview",
            processing_version=record.processing_version,
        )
        if derivative is None:
            raise AttachmentLifecycleError(
                "attachment_preview_not_available",
                "该文件没有可用预览。",
                http_status=404,
            )
        path = resolve_storage_path(self.storage_root, derivative.storage_relative_path)
        if not path.is_file():
            raise AttachmentLifecycleError(
                "attachment_preview_not_available",
                "该文件没有可用预览。",
                http_status=404,
            )
        return AttachmentContentReference(
            path=path,
            mime_type=derivative.mime_type,
            filename=f"preview-{attachment_id}.png",
            byte_size=path.stat().st_size,
        )

    def content(self, attachment_id: UUID) -> AttachmentContentReference:
        record = self._record_or_error(attachment_id)
        if not record.storage_relative_path:
            raise AttachmentLifecycleError(
                "attachment_original_missing",
                "文件原件不存在，请重新上传。",
                http_status=409,
            )
        path = resolve_storage_path(self.storage_root, record.storage_relative_path)
        if not path.is_file():
            raise AttachmentLifecycleError(
                "attachment_original_missing",
                "文件原件不存在，请重新上传。",
                http_status=409,
            )
        return AttachmentContentReference(
            path=path,
            mime_type=record.detected_mime_type or "application/octet-stream",
            filename=record.safe_filename,
            byte_size=path.stat().st_size,
        )

    def _validate_durable_original(self, record: AttachmentRecord) -> Path:
        if not record.storage_relative_path:
            raise AttachmentLifecycleError(
                "attachment_original_missing",
                "文件原件不存在，请重新上传。",
                http_status=409,
            )
        path = resolve_storage_path(self.storage_root, record.storage_relative_path)
        if not path.is_file():
            raise AttachmentLifecycleError(
                "attachment_original_missing",
                "文件原件不存在，请重新上传。",
                http_status=409,
            )
        digest = hashlib.sha256()
        byte_size = 0
        with path.open("rb") as source:
            while chunk := source.read(256 * 1024):
                byte_size += len(chunk)
                digest.update(chunk)
        if byte_size != record.byte_size or not record.sha256 or digest.hexdigest() != record.sha256:
            raise AttachmentLifecycleError(
                "attachment_original_corrupt",
                "文件原件校验失败，请重新上传。",
                http_status=409,
            )
        return path

    def retry(self, attachment_id: UUID) -> AttachmentRecord:
        record = self._record_or_error(attachment_id)
        if record.lifecycle != "draft" or record.status != "failed":
            raise AttachmentLifecycleError(
                "attachment_retry_not_allowed",
                "当前文件状态不能重试。",
                http_status=409,
            )
        self._validate_durable_original(record)
        new_processing_version = f"{PROCESSING_VERSION}-r-{uuid4().hex[:12]}"
        processing = self.repository.prepare_retry(
            attachment_id,
            expected_processing_version=record.processing_version,
            new_processing_version=new_processing_version,
        )
        if processing is None:
            raise AttachmentLifecycleError(
                "attachment_retry_not_allowed",
                "当前文件状态不能重试。",
                http_status=409,
            )
        try:
            enqueued = self.queue.enqueue(attachment_id, new_processing_version)
            if enqueued is False:
                raise RuntimeError("attachment_retry_queue_duplicate")
        except Exception as exc:
            self.repository.mark_failed(
                attachment_id,
                error_code=AttachmentErrorCode.PARSE_FAILED.value,
                error_detail_safe="文件已保存，但处理队列暂时不可用，请重试。",
            )
            raise AttachmentLifecycleError(
                "attachment_queue_unavailable",
                "文件已保存，但处理队列暂时不可用，请重试。",
                http_status=503,
            ) from exc
        return processing

    def delete(self, attachment_id: UUID) -> None:
        record = self._record_or_error(attachment_id, allow_expired=True)
        if record.lifecycle == "attached":
            raise AttachmentLifecycleError(
                AttachmentErrorCode.ATTACHMENT_ALREADY_ATTACHED.value,
                SAFE_ATTACHMENT_ERROR_MESSAGES[AttachmentErrorCode.ATTACHMENT_ALREADY_ATTACHED],
                http_status=409,
            )
        marked = self.repository.mark_lifecycle_deleted(attachment_id)
        if marked is None:
            raise AttachmentLifecycleError(
                "attachment_delete_not_allowed",
                "当前文件不能删除。",
                http_status=409,
            )
        try:
            for relative_path in self.repository.list_storage_paths(attachment_id):
                resolve_storage_path(self.storage_root, relative_path).unlink(missing_ok=True)
        except (AttachmentRejected, OSError) as exc:
            raise AttachmentLifecycleError(
                AttachmentErrorCode.STORAGE_FAILED.value,
                "文件删除失败，请重试。",
                http_status=503,
            ) from exc
        self.repository.complete_deleted(attachment_id, deleted_at=self.now())

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
    "AttachmentContentReference",
    "AttachmentLifecycleError",
    "AttachmentQueue",
    "AttachmentService",
    "AttachmentSubmissionError",
    "AttachmentSubmissionService",
    "AttachmentUploadError",
    "RedisAttachmentQueue",
    "UploadedAttachment",
]
