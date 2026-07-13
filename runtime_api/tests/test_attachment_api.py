from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))


from app.attachments.models import AttachmentLimits
from app.attachments.repository import InMemoryAttachmentRepository
from app.attachments.router import create_attachment_router
from app.attachments.service import AttachmentService, AttachmentUploadError
from attachment_fixture_factory import image_bytes


class RecordingQueue:
    def __init__(self) -> None:
        self.attachment_ids: list[uuid.UUID] = []

    def enqueue(self, attachment_id: uuid.UUID) -> None:
        self.attachment_ids.append(attachment_id)


class DisconnectingStream:
    def __init__(self) -> None:
        self.calls = 0

    def read(self, size: int) -> bytes:
        self.calls += 1
        if self.calls == 1:
            return b"partial"
        raise ConnectionError("private socket detail")


def password_guard(password: str | None) -> None:
    if password != "par-dev":
        raise HTTPException(status_code=401, detail="invalid password")


def build_client(tmp_path: Path, *, limits: AttachmentLimits | None = None):
    repository = InMemoryAttachmentRepository()
    queue = RecordingQueue()
    service = AttachmentService(
        repository=repository,
        storage_root=tmp_path,
        queue=queue,
        limits=limits or AttachmentLimits(),
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
    return TestClient(app, raise_server_exceptions=False), repository, queue, service


def upload_png(client: TestClient, payload: bytes, *, upload_id: str = "android-7f9d"):
    return client.post(
        "/api/chat/attachments",
        headers={"X-Par-Password": "par-dev"},
        files={"file": ("图.png", payload, "image/png")},
        data={"client_upload_id": upload_id},
    )


def test_runtime_app_registers_the_authenticated_upload_route(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    from app import main

    response = TestClient(main.app, raise_server_exceptions=False).post(
        "/api/chat/attachments",
        files={"file": ("photo.png", image_bytes("PNG"), "image/png")},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid password"}


def test_upload_requires_password_and_does_not_create_draft(tmp_path):
    client, repository, queue, _ = build_client(tmp_path)

    response = client.post(
        "/api/chat/attachments",
        files={"file": ("photo.png", image_bytes("PNG"), "image/png")},
        data={"client_upload_id": "missing-auth"},
    )

    assert response.status_code == 401
    assert repository.count() == 0
    assert queue.attachment_ids == []


def test_valid_multipart_upload_returns_safe_attachment_only_metadata(tmp_path):
    client, repository, queue, _ = build_client(tmp_path)
    payload = image_bytes("PNG")

    response = upload_png(client, payload)

    assert response.status_code == 202
    body = response.json()
    assert body == {
        "attachment_id": body["attachment_id"],
        "filename": "图.png",
        "mime_type": "image/png",
        "byte_size": len(payload),
        "status": "stored",
        "kind": "image",
        "created_at": body["created_at"],
        "expires_at": body["expires_at"],
    }
    record = repository.get(uuid.UUID(body["attachment_id"]))
    assert record is not None
    assert record.sha256 and len(record.sha256) == 64
    assert record.storage_relative_path and not Path(record.storage_relative_path).is_absolute()
    assert queue.attachment_ids == [record.attachment_id]


def test_response_never_exposes_hash_absolute_path_or_original_bytes(tmp_path):
    client, _, _, _ = build_client(tmp_path)
    payload = image_bytes("PNG")

    response = upload_png(client, payload)
    serialized = json.dumps(response.json(), ensure_ascii=False)

    assert response.status_code == 202
    assert str(tmp_path) not in serialized
    assert "storage_relative_path" not in serialized
    assert "sha256" not in serialized
    assert payload.hex()[:32] not in serialized
    assert "base64" not in serialized.lower()


def test_oversized_upload_is_rejected_and_partial_file_is_removed(tmp_path):
    limits = AttachmentLimits(max_file_bytes=16)
    client, repository, queue, _ = build_client(tmp_path, limits=limits)

    response = client.post(
        "/api/chat/attachments",
        headers={"X-Par-Password": "par-dev"},
        files={"file": ("large.txt", b"x" * 17, "text/plain")},
        data={"client_upload_id": "too-large"},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "too_large"
    record = repository.find_by_client_upload_id("too-large")
    assert record is not None and record.status == "rejected"
    assert queue.attachment_ids == []
    assert list(tmp_path.rglob("*.part")) == []
    assert list((tmp_path / "originals").rglob("*.*")) == []


def test_interrupted_upload_marks_failed_and_does_not_leak_internal_error(tmp_path):
    _, repository, queue, service = build_client(tmp_path)

    with pytest.raises(AttachmentUploadError) as error:
        service.upload(
            DisconnectingStream(),
            original_filename="notes.txt",
            declared_mime_type="text/plain",
            client_upload_id="disconnect-1",
        )

    assert error.value.code == "storage_failed"
    assert "private socket detail" not in error.value.safe_message
    record = repository.find_by_client_upload_id("disconnect-1")
    assert record is not None and record.status == "failed"
    assert queue.attachment_ids == []
    assert list(tmp_path.rglob("*.part")) == []


def test_repeated_client_upload_id_with_same_bytes_returns_same_draft(tmp_path):
    client, repository, queue, _ = build_client(tmp_path)
    payload = image_bytes("PNG")

    first = upload_png(client, payload)
    second = upload_png(client, payload)

    assert first.status_code == second.status_code == 202
    assert first.json()["attachment_id"] == second.json()["attachment_id"]
    assert repository.count() == 1
    assert len(queue.attachment_ids) == 1
    assert len(list((tmp_path / "originals").rglob("*.png"))) == 1


def test_reused_client_upload_id_with_different_bytes_returns_conflict(tmp_path):
    client, repository, queue, _ = build_client(tmp_path)

    first = upload_png(client, image_bytes("PNG", size=(16, 12)))
    second = upload_png(client, image_bytes("PNG", size=(17, 12)))

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["detail"] == {
        "code": "client_upload_id_conflict",
        "message": "同一上传标识对应了不同文件，请重新选择文件。",
    }
    assert repository.count() == 1
    assert len(queue.attachment_ids) == 1
    assert len(list((tmp_path / "originals").rglob("*.png"))) == 1


def test_rejected_file_keeps_safe_status_but_deletes_hostile_original(tmp_path):
    client, repository, queue, _ = build_client(tmp_path)

    response = client.post(
        "/api/chat/attachments",
        headers={"X-Par-Password": "par-dev"},
        files={"file": ("attack.js", b"alert(document.cookie)", "text/javascript")},
        data={"client_upload_id": "hostile-1"},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "unsupported_type"
    assert detail["message"] == "暂不支持这种文件格式。"
    assert set(detail) == {"code", "message", "attachment_id"}
    record = repository.find_by_client_upload_id("hostile-1")
    assert record is not None
    assert record.status == "rejected"
    assert record.error_code == "unsupported_type"
    assert record.storage_relative_path is None
    assert queue.attachment_ids == []
    assert list((tmp_path / "originals").rglob("*.*")) == []


def test_upload_without_client_upload_id_is_allowed_but_not_idempotent(tmp_path):
    client, repository, queue, _ = build_client(tmp_path)
    payload = image_bytes("PNG")

    responses = [
        client.post(
            "/api/chat/attachments",
            headers={"X-Par-Password": "par-dev"},
            files={"file": ("photo.png", payload, "image/png")},
        )
        for _ in range(2)
    ]

    assert [response.status_code for response in responses] == [202, 202]
    assert responses[0].json()["attachment_id"] != responses[1].json()["attachment_id"]
    assert repository.count() == 2
    assert len(queue.attachment_ids) == 2
