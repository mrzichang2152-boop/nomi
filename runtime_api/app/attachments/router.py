from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Callable, ContextManager, Iterator, Optional
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.responses import Response, StreamingResponse

from app.attachments.repository import AttachmentRepository, PostgresAttachmentRepository
from app.attachments.service import (
    AttachmentContentReference,
    AttachmentLifecycleError,
    AttachmentQueue,
    AttachmentService,
    AttachmentUploadError,
)


class AttachmentUploadResponse(BaseModel):
    attachment_id: UUID
    filename: str
    mime_type: str
    byte_size: int
    status: str
    kind: str
    created_at: datetime
    expires_at: datetime


class AttachmentStatusResponse(BaseModel):
    attachment_id: UUID
    filename: str
    mime_type: str
    byte_size: int
    status: str
    lifecycle: str
    kind: str
    preview_url: Optional[str]
    content_url: str
    error_code: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    expires_at: Optional[datetime]


def _raise_lifecycle_error(error: AttachmentLifecycleError) -> None:
    raise HTTPException(
        status_code=error.http_status,
        detail={"code": error.code, "message": error.safe_message},
    ) from error


def _iter_file(source: BinaryIO, chunk_size: int = 256 * 1024) -> Iterator[bytes]:
    try:
        while chunk := source.read(chunk_size):
            yield chunk
    finally:
        source.close()


def _content_disposition(disposition: str, filename: str) -> str:
    extension = Path(filename).suffix.lower()
    ascii_extension = extension if extension.isascii() and extension.replace(".", "").isalnum() else ""
    fallback = f"attachment{ascii_extension}"
    return f'{disposition}; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename)}'


def _stream_reference(reference: AttachmentContentReference, *, disposition: str) -> StreamingResponse:
    response = StreamingResponse(
        _iter_file(reference.path.open("rb")),
        media_type=reference.mime_type,
        headers={
            "Content-Disposition": _content_disposition(disposition, reference.filename),
            "Content-Length": str(reference.byte_size),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Accept-Ranges": "none",
        },
    )
    return response


def create_attachment_router(
    connection_factory: Optional[Callable[[], ContextManager[object]]],
    password_guard: Callable[[Optional[str]], None],
    storage: Path | str,
    queue: AttachmentQueue,
    *,
    repository: Optional[AttachmentRepository] = None,
    service: Optional[AttachmentService] = None,
) -> APIRouter:
    active_repository = repository
    if active_repository is None:
        if connection_factory is None:
            raise ValueError("connection_factory_or_repository_required")
        active_repository = PostgresAttachmentRepository(connection_factory)
    active_service = service or AttachmentService(
        repository=active_repository,
        storage_root=storage,
        queue=queue,
    )
    router = APIRouter()

    def status_response(record) -> AttachmentStatusResponse:
        attachment_id = record.attachment_id
        preview_url = None
        if active_service.has_preview(record):
            preview_url = f"/api/chat/attachments/{attachment_id}/preview"
        return AttachmentStatusResponse(
            attachment_id=attachment_id,
            filename=record.safe_filename,
            mime_type=record.detected_mime_type or "application/octet-stream",
            byte_size=record.byte_size,
            status=record.status,
            lifecycle=record.lifecycle,
            kind=active_service.kind_for(record),
            preview_url=preview_url,
            content_url=f"/api/chat/attachments/{attachment_id}/content",
            error_code=record.error_code,
            error_message=record.error_detail_safe,
            created_at=record.created_at,
            expires_at=record.expires_at,
        )

    @router.post(
        "/api/chat/attachments",
        status_code=202,
        response_model=AttachmentUploadResponse,
    )
    def upload_attachment(
        file: UploadFile = File(...),
        client_upload_id: Optional[str] = Form(default=None),
        x_par_password: Optional[str] = Header(default=None),
    ) -> AttachmentUploadResponse:
        password_guard(x_par_password)
        try:
            uploaded = active_service.upload(
                file.file,
                original_filename=file.filename or "attachment",
                declared_mime_type=file.content_type,
                client_upload_id=client_upload_id,
            )
        except AttachmentUploadError as error:
            detail: dict[str, object] = {
                "code": error.code,
                "message": error.safe_message,
            }
            if error.attachment_id is not None and error.code not in {
                "client_upload_id_conflict",
                "invalid_client_upload_id",
            }:
                detail["attachment_id"] = str(error.attachment_id)
            raise HTTPException(status_code=error.http_status, detail=detail) from error
        record = uploaded.record
        if record.detected_mime_type is None or record.expires_at is None:
            raise HTTPException(status_code=503, detail={"code": "attachment_metadata_incomplete"})
        return AttachmentUploadResponse(
            attachment_id=record.attachment_id,
            filename=record.safe_filename,
            mime_type=record.detected_mime_type,
            byte_size=record.byte_size,
            status=record.status,
            kind=active_service.kind_for(record),
            created_at=record.created_at,
            expires_at=record.expires_at,
        )

    @router.get(
        "/api/chat/attachments/{attachment_id}",
        response_model=AttachmentStatusResponse,
    )
    def get_attachment(
        attachment_id: UUID,
        x_par_password: Optional[str] = Header(default=None),
    ) -> AttachmentStatusResponse:
        password_guard(x_par_password)
        try:
            record = active_service.get(attachment_id)
        except AttachmentLifecycleError as error:
            _raise_lifecycle_error(error)
        return status_response(record)

    @router.get("/api/chat/attachments/{attachment_id}/preview")
    def preview_attachment(
        attachment_id: UUID,
        x_par_password: Optional[str] = Header(default=None),
    ) -> StreamingResponse:
        password_guard(x_par_password)
        try:
            reference = active_service.preview(attachment_id)
        except AttachmentLifecycleError as error:
            _raise_lifecycle_error(error)
        return _stream_reference(reference, disposition="inline")

    @router.get("/api/chat/attachments/{attachment_id}/content")
    def download_attachment(
        attachment_id: UUID,
        x_par_password: Optional[str] = Header(default=None),
    ) -> StreamingResponse:
        password_guard(x_par_password)
        try:
            reference = active_service.content(attachment_id)
        except AttachmentLifecycleError as error:
            _raise_lifecycle_error(error)
        return _stream_reference(reference, disposition="attachment")

    @router.post(
        "/api/chat/attachments/{attachment_id}/retry",
        status_code=202,
        response_model=AttachmentStatusResponse,
    )
    def retry_attachment(
        attachment_id: UUID,
        x_par_password: Optional[str] = Header(default=None),
    ) -> AttachmentStatusResponse:
        password_guard(x_par_password)
        try:
            record = active_service.retry(attachment_id)
        except AttachmentLifecycleError as error:
            _raise_lifecycle_error(error)
        return status_response(record)

    @router.delete("/api/chat/attachments/{attachment_id}", status_code=204)
    def delete_attachment(
        attachment_id: UUID,
        x_par_password: Optional[str] = Header(default=None),
    ) -> Response:
        password_guard(x_par_password)
        try:
            active_service.delete(attachment_id)
        except AttachmentLifecycleError as error:
            _raise_lifecycle_error(error)
        return Response(status_code=204)

    return router


__all__ = [
    "AttachmentStatusResponse",
    "AttachmentUploadResponse",
    "create_attachment_router",
]
