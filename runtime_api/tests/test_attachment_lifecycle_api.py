from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from app.attachments.parsers.common import ParseResult, ParsedDerivative
from app.attachments.repository import AttachmentRecord, InMemoryAttachmentRepository
from app.attachments.router import create_attachment_router
from app.attachments.service import AttachmentService


NOW = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
PASSWORD = "par-dev"


class RecordingQueue:
    def __init__(self) -> None:
        self.jobs: list[tuple[uuid.UUID, str]] = []

    def enqueue(self, attachment_id: uuid.UUID, processing_version: str = "attachment-v1") -> bool:
        job = (attachment_id, processing_version)
        if job in self.jobs:
            return False
        self.jobs.append(job)
        return True


def password_guard(password: str | None) -> None:
    if password != PASSWORD:
        raise HTTPException(status_code=401, detail="invalid password")


def build_client(tmp_path: Path):
    repository = InMemoryAttachmentRepository()
    queue = RecordingQueue()
    service = AttachmentService(
        repository=repository,
        storage_root=tmp_path,
        queue=queue,
        now=lambda: NOW,
    )
    app = FastAPI()
    app.include_router(
        create_attachment_router(
            connection_factory=None,
            password_guard=password_guard,
            storage=tmp_path,
            queue=queue,
            repository=repository,
            service=service,
        )
    )
    return TestClient(app, raise_server_exceptions=False), repository, queue


def seed_attachment(
    repository: InMemoryAttachmentRepository,
    root: Path,
    *,
    filename: str = "notes.txt",
    mime_type: str = "text/plain",
    parser_kind: str = "txt",
    payload: bytes = b"private attachment bytes",
    status: str = "ready",
    lifecycle: str = "draft",
    expires_at: datetime | None = None,
    preview: bytes | None = None,
) -> AttachmentRecord:
    attachment_id = uuid.uuid4()
    extension = Path(filename).suffix.lower()
    relative_path = f"originals/{attachment_id.hex[:2]}/{attachment_id}/source{extension}"
    record = AttachmentRecord(
        attachment_id=attachment_id,
        client_upload_id=f"upload-{attachment_id}",
        original_filename=filename,
        safe_filename=filename,
        declared_mime_type=mime_type,
        detected_mime_type=mime_type,
        extension=extension,
        byte_size=len(payload),
        sha256=__import__("hashlib").sha256(payload).hexdigest(),
        storage_relative_path=relative_path,
        status="receiving",
        lifecycle="draft",
        parser_kind=parser_kind,
        processing_version="attachment-v1",
        error_code=None,
        error_detail_safe=None,
        created_at=NOW,
        stored_at=None,
        processed_at=None,
        attached_at=None,
        expires_at=None,
        deleted_at=None,
    )
    repository.create_receiving(record)
    stored = repository.mark_stored(
        attachment_id,
        sha256=record.sha256,
        byte_size=record.byte_size,
        storage_relative_path=relative_path,
        detected_mime_type=mime_type,
        extension=extension,
        parser_kind=parser_kind,
        stored_at=NOW,
        expires_at=expires_at or NOW + timedelta(hours=24),
    )
    original = root / relative_path
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(payload)

    final = stored
    if status == "ready":
        processing = repository.mark_processing(attachment_id, stored.processing_version)
        assert processing is not None
        derivatives: tuple[ParsedDerivative, ...] = ()
        if preview is not None:
            preview_relative = (
                f"derivatives/{attachment_id.hex[:2]}/{attachment_id}/"
                f"{stored.processing_version}/preview.png"
            )
            preview_path = root / preview_relative
            preview_path.parent.mkdir(parents=True, exist_ok=True)
            preview_path.write_bytes(preview)
            derivatives = (
                ParsedDerivative(
                    kind="preview",
                    mime_type="image/png",
                    extension=".png",
                    storage_relative_path=preview_relative,
                    byte_size=len(preview),
                ),
            )
        final = repository.persist_parse_result(
            attachment_id,
            stored.processing_version,
            ParseResult(derivatives=derivatives, summary="fixture parsed"),
            processed_at=NOW,
        )
    elif status == "failed":
        final = repository.mark_failed(
            attachment_id,
            error_code="parse_failed",
            error_detail_safe="文件内容解析失败。",
        )
    elif status != "stored":
        raise ValueError(f"unsupported_fixture_status:{status}")

    if lifecycle == "attached":
        final = repository.mark_attached(attachment_id, attached_at=NOW)
    return final


def auth_headers() -> dict[str, str]:
    return {"X-Par-Password": PASSWORD}


def test_authenticated_metadata_polling_returns_only_safe_public_fields(tmp_path):
    client, repository, _ = build_client(tmp_path)
    record = seed_attachment(
        repository,
        tmp_path,
        filename="架构图.png",
        mime_type="image/png",
        parser_kind="image",
        payload=b"original-image",
        preview=b"preview-image",
    )

    response = client.get(f"/api/chat/attachments/{record.attachment_id}", headers=auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "attachment_id": str(record.attachment_id),
        "filename": "架构图.png",
        "mime_type": "image/png",
        "byte_size": len(b"original-image"),
        "status": "ready",
        "lifecycle": "draft",
        "kind": "image",
        "preview_url": f"/api/chat/attachments/{record.attachment_id}/preview",
        "content_url": f"/api/chat/attachments/{record.attachment_id}/content",
        "error_code": None,
        "error_message": None,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
    }
    serialized = json.dumps(body, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "storage_relative_path" not in serialized
    assert "sha256" not in serialized


def test_non_image_metadata_uses_generic_file_card_without_preview_url(tmp_path):
    client, repository, _ = build_client(tmp_path)
    record = seed_attachment(repository, tmp_path, filename="说明.pdf", mime_type="application/pdf", parser_kind="pdf")

    response = client.get(f"/api/chat/attachments/{record.attachment_id}", headers=auth_headers())

    assert response.status_code == 200
    assert response.json()["kind"] == "pdf"
    assert response.json()["preview_url"] is None
    assert response.json()["content_url"].endswith(f"/{record.attachment_id}/content")


@pytest.mark.parametrize("endpoint", ["preview", "content"])
def test_preview_and_content_require_auth_without_returning_private_bytes(tmp_path, endpoint):
    client, repository, _ = build_client(tmp_path)
    secret = b"do-not-return-without-auth"
    record = seed_attachment(
        repository,
        tmp_path,
        filename="private.png",
        mime_type="image/png",
        parser_kind="image",
        payload=secret,
        preview=secret,
    )

    response = client.get(f"/api/chat/attachments/{record.attachment_id}/{endpoint}")

    assert response.status_code == 401
    assert secret not in response.content


def test_image_preview_streams_derived_thumbnail_with_private_security_headers(tmp_path):
    client, repository, _ = build_client(tmp_path)
    preview = b"small-normalized-preview"
    record = seed_attachment(
        repository,
        tmp_path,
        filename="照片.png",
        mime_type="image/png",
        parser_kind="image",
        preview=preview,
    )

    response = client.get(f"/api/chat/attachments/{record.attachment_id}/preview", headers=auth_headers())

    assert response.status_code == 200
    assert response.content == preview
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"


def test_original_download_streams_full_bytes_and_uses_rfc_safe_chinese_filename(tmp_path):
    client, repository, _ = build_client(tmp_path)
    payload = b"0123456789-private-pdf"
    filename = "后端 简历（最终版）.pdf"
    record = seed_attachment(
        repository,
        tmp_path,
        filename=filename,
        mime_type="application/pdf",
        parser_kind="pdf",
        payload=payload,
    )

    response = client.get(
        f"/api/chat/attachments/{record.attachment_id}/content",
        headers={**auth_headers(), "Range": "bytes=0-3"},
    )

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"] == "application/pdf"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert f"filename*=UTF-8''{quote(filename)}" in disposition
    assert str(tmp_path) not in disposition
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers.get("accept-ranges") == "none"


def test_retry_failed_draft_checks_original_and_enqueues_exactly_one_new_processing_version(tmp_path):
    client, repository, queue = build_client(tmp_path)
    record = seed_attachment(repository, tmp_path, status="failed")

    first = client.post(f"/api/chat/attachments/{record.attachment_id}/retry", headers=auth_headers())
    second = client.post(f"/api/chat/attachments/{record.attachment_id}/retry", headers=auth_headers())

    assert first.status_code == 202
    body = first.json()
    assert body["attachment_id"] == str(record.attachment_id)
    assert body["status"] == "processing"
    assert body["error_code"] is None
    assert body["error_message"] is None
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "attachment_retry_not_allowed"
    assert len(queue.jobs) == 1
    assert queue.jobs[0][0] == record.attachment_id
    assert queue.jobs[0][1] != record.processing_version


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_retry_refuses_missing_or_corrupt_durable_original(tmp_path, damage):
    client, repository, queue = build_client(tmp_path)
    record = seed_attachment(repository, tmp_path, status="failed")
    path = tmp_path / str(record.storage_relative_path)
    if damage == "missing":
        path.unlink()
        expected_code = "attachment_original_missing"
    else:
        path.write_bytes(b"tampered")
        expected_code = "attachment_original_corrupt"

    response = client.post(f"/api/chat/attachments/{record.attachment_id}/retry", headers=auth_headers())

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == expected_code
    assert repository.get(record.attachment_id).status == "failed"
    assert queue.jobs == []


def test_delete_draft_removes_original_and_derivatives_then_records_completion(tmp_path):
    client, repository, _ = build_client(tmp_path)
    record = seed_attachment(
        repository,
        tmp_path,
        filename="photo.png",
        mime_type="image/png",
        parser_kind="image",
        preview=b"preview",
    )
    storage_paths = repository.list_storage_paths(record.attachment_id)
    assert all((tmp_path / path).exists() for path in storage_paths)

    response = client.delete(f"/api/chat/attachments/{record.attachment_id}", headers=auth_headers())

    assert response.status_code == 204
    final = repository.get(record.attachment_id)
    assert final is not None and final.lifecycle == "deleted" and final.deleted_at == NOW
    assert all(not (tmp_path / path).exists() for path in storage_paths)


def test_delete_refuses_attached_file_and_preserves_bytes(tmp_path):
    client, repository, _ = build_client(tmp_path)
    record = seed_attachment(repository, tmp_path, lifecycle="attached")
    path = tmp_path / str(record.storage_relative_path)

    response = client.delete(f"/api/chat/attachments/{record.attachment_id}", headers=auth_headers())

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "attachment_already_attached"
    assert path.exists()
    assert repository.get(record.attachment_id).lifecycle == "attached"


def test_expired_draft_returns_gone_instead_of_stale_metadata_or_bytes(tmp_path):
    client, repository, _ = build_client(tmp_path)
    record = seed_attachment(repository, tmp_path, expires_at=NOW - timedelta(seconds=1))

    metadata = client.get(f"/api/chat/attachments/{record.attachment_id}", headers=auth_headers())
    content = client.get(f"/api/chat/attachments/{record.attachment_id}/content", headers=auth_headers())

    assert metadata.status_code == content.status_code == 410
    assert metadata.json()["detail"]["code"] == "attachment_expired"
    assert content.json()["detail"]["code"] == "attachment_expired"


@pytest.mark.parametrize("method,suffix", [("get", ""), ("get", "/preview"), ("get", "/content"), ("post", "/retry"), ("delete", "")])
def test_missing_attachment_id_returns_stable_not_found(method, suffix, tmp_path):
    client, _, _ = build_client(tmp_path)
    missing = uuid.uuid4()

    response = getattr(client, method)(f"/api/chat/attachments/{missing}{suffix}", headers=auth_headers())

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "attachment_not_found",
        "message": "未找到该文件。",
    }
