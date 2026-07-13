from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, ContextManager, Optional
from uuid import UUID

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel

from app.attachments.repository import AttachmentRepository, PostgresAttachmentRepository
from app.attachments.service import AttachmentQueue, AttachmentService, AttachmentUploadError


class AttachmentUploadResponse(BaseModel):
    attachment_id: UUID
    filename: str
    mime_type: str
    byte_size: int
    status: str
    kind: str
    created_at: datetime
    expires_at: datetime


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
        kind_by_parser = {
            "image": "image",
            "pdf": "pdf",
            "docx": "document",
            "pptx": "presentation",
            "xlsx": "spreadsheet",
            "csv": "text",
            "txt": "text",
            "md": "text",
        }
        return AttachmentUploadResponse(
            attachment_id=record.attachment_id,
            filename=record.safe_filename,
            mime_type=record.detected_mime_type,
            byte_size=record.byte_size,
            status=record.status,
            kind=kind_by_parser.get(record.parser_kind or "", "file"),
            created_at=record.created_at,
            expires_at=record.expires_at,
        )

    return router


__all__ = ["AttachmentUploadResponse", "create_attachment_router"]
