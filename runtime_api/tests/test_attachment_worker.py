from __future__ import annotations

import sys
import time
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from app.attachments.models import AttachmentErrorCode, AttachmentRejected
from app.attachments.queue import InMemoryAttachmentQueue, QueueItem
from app.attachments.repository import AttachmentRecord, InMemoryAttachmentRepository
from app.attachments.worker import (
    AttachmentWorker,
    AttachmentWorkerConfig,
    DraftCleaner,
    ParseResult,
)


BASE_TIME = datetime(2026, 7, 13, 8, 0, tzinfo=timezone.utc)


def stored_record(
    *,
    filename: str = "notes.txt",
    parser_kind: str = "txt",
    status: str = "stored",
    lifecycle: str = "draft",
    expires_at: datetime | None = None,
) -> AttachmentRecord:
    attachment_id = uuid.uuid4()
    return AttachmentRecord(
        attachment_id=attachment_id,
        client_upload_id=f"test-{attachment_id}",
        original_filename=filename,
        safe_filename=filename,
        declared_mime_type="text/plain",
        detected_mime_type="text/plain",
        extension=Path(filename).suffix,
        byte_size=7,
        sha256="a" * 64,
        storage_relative_path=f"originals/{attachment_id.hex[:2]}/{attachment_id}/source{Path(filename).suffix}",
        status=status,
        lifecycle=lifecycle,
        parser_kind=parser_kind,
        processing_version="attachment-v1",
        error_code=None,
        error_detail_safe=None,
        created_at=BASE_TIME,
        stored_at=BASE_TIME,
        processed_at=None,
        attached_at=BASE_TIME if lifecycle == "attached" else None,
        expires_at=expires_at or BASE_TIME + timedelta(hours=24),
        deleted_at=None,
    )


def seed_record(repository: InMemoryAttachmentRepository, record: AttachmentRecord) -> AttachmentRecord:
    repository.create_receiving(replace(record, status="receiving"))
    if record.status == "stored":
        return repository.mark_stored(
            record.attachment_id,
            sha256=record.sha256,
            byte_size=record.byte_size,
            storage_relative_path=record.storage_relative_path,
            detected_mime_type=record.detected_mime_type,
            extension=record.extension,
            parser_kind=record.parser_kind,
            stored_at=record.stored_at,
            expires_at=record.expires_at,
        )
    repository._records[record.attachment_id] = record
    return record


def create_original(root: Path, record: AttachmentRecord, payload: bytes = b"content") -> Path:
    path = root / str(record.storage_relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


class SuccessfulParser:
    def __init__(self) -> None:
        self.calls: list[uuid.UUID] = []

    def parse(self, record: AttachmentRecord, source_path: Path) -> ParseResult:
        self.calls.append(record.attachment_id)
        return ParseResult(summary=f"parsed:{source_path.read_text()}", chunk_count=1, derivative_count=0)


class RejectingParser:
    def parse(self, record: AttachmentRecord, source_path: Path) -> ParseResult:
        raise AttachmentRejected(AttachmentErrorCode.COMPLEXITY_LIMIT)


class SelectiveParser:
    def parse(self, record: AttachmentRecord, source_path: Path) -> ParseResult:
        if record.safe_filename.startswith("corrupt"):
            raise ValueError("raw parser stack /private/path")
        return ParseResult(summary="valid", chunk_count=1, derivative_count=0)


class SlowParser:
    def parse(self, record: AttachmentRecord, source_path: Path) -> ParseResult:
        time.sleep(0.08)
        return ParseResult(summary="too late", chunk_count=1, derivative_count=0)


class CrashingParser:
    def parse(self, record: AttachmentRecord, source_path: Path) -> ParseResult:
        raise SystemExit("worker process crashed")


def build_worker(tmp_path: Path, parser, *, timeout: float = 1.0, lease_seconds: int = 30):
    repository = InMemoryAttachmentRepository()
    queue = InMemoryAttachmentQueue()
    worker = AttachmentWorker(
        repository=repository,
        queue=queue,
        storage_root=tmp_path,
        parser=parser,
        config=AttachmentWorkerConfig(
            lightweight_concurrency=2,
            office_concurrency=1,
            vision_concurrency=1,
            parse_timeout_seconds=timeout,
            lease_seconds=lease_seconds,
        ),
        worker_id="worker-a",
    )
    return worker, repository, queue


def enqueue_record(repository, queue, root, record):
    seed_record(repository, record)
    create_original(root, record)
    assert queue.enqueue(record.attachment_id, record.processing_version) is True


def test_queue_has_one_item_per_attachment_and_processing_version():
    queue = InMemoryAttachmentQueue()
    attachment_id = uuid.uuid4()

    assert queue.enqueue(attachment_id, "attachment-v1") is True
    assert queue.enqueue(attachment_id, "attachment-v1") is False
    assert queue.enqueue(attachment_id, "attachment-v2") is True
    assert queue.pending_count == 2


def test_stale_processing_version_job_is_acked_without_mutating_attachment(tmp_path):
    worker, repository, queue = build_worker(tmp_path, SuccessfulParser())
    record = stored_record()
    seed_record(repository, record)
    create_original(tmp_path, record)
    queue.enqueue(record.attachment_id, "attachment-v0")

    result = worker.run_next(now=BASE_TIME)

    final = repository.get(record.attachment_id)
    assert result is not None and result.status == "skipped"
    assert final is not None and final.status == "stored"
    assert final.processing_version == "attachment-v1"
    assert queue.inflight_count == 0


def test_worker_transitions_stored_to_processing_to_ready_and_acks_job(tmp_path):
    parser = SuccessfulParser()
    worker, repository, queue = build_worker(tmp_path, parser)
    record = stored_record()
    enqueue_record(repository, queue, tmp_path, record)

    result = worker.run_next(now=BASE_TIME)

    final = repository.get(record.attachment_id)
    assert result is not None and result.status == "ready"
    assert result.parse_result == ParseResult(summary="parsed:content", chunk_count=1, derivative_count=0)
    assert final is not None and final.status == "ready"
    assert final.processed_at == BASE_TIME
    assert parser.calls == [record.attachment_id]
    assert queue.pending_count == queue.inflight_count == 0
    assert queue.completed_keys == {f"{record.attachment_id}:attachment-v1"}


def test_parser_rejection_uses_stable_rejected_status_and_safe_message(tmp_path):
    worker, repository, queue = build_worker(tmp_path, RejectingParser())
    record = stored_record(filename="huge.docx", parser_kind="docx")
    enqueue_record(repository, queue, tmp_path, record)

    result = worker.run_next(now=BASE_TIME)

    final = repository.get(record.attachment_id)
    assert result is not None and result.status == "rejected"
    assert final is not None
    assert final.status == "rejected"
    assert final.error_code == "complexity_limit"
    assert final.error_detail_safe == "文件结构过于复杂，无法安全处理。"


def test_worker_failure_isolated_and_next_job_runs(tmp_path):
    worker, repository, queue = build_worker(tmp_path, SelectiveParser())
    first = stored_record(filename="corrupt.pdf", parser_kind="pdf")
    second = stored_record(filename="valid.txt", parser_kind="txt")
    enqueue_record(repository, queue, tmp_path, first)
    enqueue_record(repository, queue, tmp_path, second)

    first_result = worker.run_next(now=BASE_TIME)
    second_result = worker.run_next(now=BASE_TIME)

    first_final = repository.get(first.attachment_id)
    second_final = repository.get(second.attachment_id)
    assert first_result is not None and first_result.status == "failed"
    assert second_result is not None and second_result.status == "ready"
    assert first_final is not None and first_final.status == "failed"
    assert first_final.error_detail_safe == "文件解析失败，可重试或重新选择文件。"
    assert "/private/path" not in str(first_final.error_detail_safe)
    assert second_final is not None and second_final.status == "ready"


def test_worker_timeout_is_terminal_for_current_attempt_and_safe(tmp_path):
    worker, repository, queue = build_worker(tmp_path, SlowParser(), timeout=0.01)
    record = stored_record()
    enqueue_record(repository, queue, tmp_path, record)

    result = worker.run_next(now=BASE_TIME)

    final = repository.get(record.attachment_id)
    assert result is not None and result.status == "failed"
    assert final is not None and final.error_code == "parse_timeout"
    assert final.error_detail_safe == "文件处理超时，请重试。"
    assert queue.inflight_count == 0


def test_active_lease_blocks_second_worker_and_expired_lease_is_requeued():
    queue = InMemoryAttachmentQueue()
    item = QueueItem(uuid.uuid4(), "attachment-v1")
    queue.enqueue(item.attachment_id, item.processing_version)

    claimed = queue.claim("worker-a", lease_seconds=10, now=BASE_TIME)
    blocked = queue.claim("worker-b", lease_seconds=10, now=BASE_TIME + timedelta(seconds=2))
    recovered = queue.recover_expired(now=BASE_TIME + timedelta(seconds=11))
    reclaimed = queue.claim("worker-b", lease_seconds=10, now=BASE_TIME + timedelta(seconds=11))

    assert claimed == item
    assert blocked is None
    assert recovered == 1
    assert reclaimed == item


def test_worker_crash_leaves_lease_and_recovery_finishes_same_job(tmp_path):
    crashing_worker, repository, queue = build_worker(tmp_path, CrashingParser(), lease_seconds=5)
    record = stored_record()
    enqueue_record(repository, queue, tmp_path, record)

    with pytest.raises(SystemExit, match="worker process crashed"):
        crashing_worker.run_next(now=BASE_TIME)

    after_crash = repository.get(record.attachment_id)
    assert after_crash is not None and after_crash.status == "processing"
    assert queue.inflight_count == 1
    assert queue.recover_expired(now=BASE_TIME + timedelta(seconds=6)) == 1

    recovered_worker = AttachmentWorker(
        repository=repository,
        queue=queue,
        storage_root=tmp_path,
        parser=SuccessfulParser(),
        config=crashing_worker.config,
        worker_id="worker-b",
    )
    result = recovered_worker.run_next(now=BASE_TIME + timedelta(seconds=6))
    assert result is not None and result.status == "ready"


def test_expired_draft_cleanup_is_two_phase_and_excludes_attached_files(tmp_path):
    repository = InMemoryAttachmentRepository()
    expired = stored_record(expires_at=BASE_TIME - timedelta(seconds=1))
    attached = stored_record(
        lifecycle="attached",
        expires_at=BASE_TIME - timedelta(days=1),
    )
    for record in (expired, attached):
        seed_record(repository, record)
        if record.lifecycle == "attached":
            repository.mark_attached(record.attachment_id, attached_at=BASE_TIME - timedelta(hours=1))
        create_original(tmp_path, record)
    cleaner = DraftCleaner(repository=repository, storage_root=tmp_path)

    report = cleaner.cleanup(now=BASE_TIME)

    expired_final = repository.get(expired.attachment_id)
    attached_final = repository.get(attached.attachment_id)
    assert report.deleted_attachment_ids == [expired.attachment_id]
    assert expired_final is not None and expired_final.lifecycle == "deleted"
    assert expired_final.deleted_at == BASE_TIME
    assert not (tmp_path / str(expired.storage_relative_path)).exists()
    assert attached_final is not None and attached_final.lifecycle == "attached"
    assert (tmp_path / str(attached.storage_relative_path)).exists()


def test_cleanup_removes_stale_receiving_record_and_orphan_part(tmp_path):
    repository = InMemoryAttachmentRepository()
    stale = stored_record(status="receiving", expires_at=BASE_TIME + timedelta(days=1))
    stale = replace(stale, created_at=BASE_TIME - timedelta(hours=2), stored_at=None)
    repository.create_receiving(stale)
    temporary = tmp_path / "temporary"
    temporary.mkdir(parents=True)
    orphan = temporary / "orphan.part"
    orphan.write_bytes(b"partial")
    old_timestamp = (BASE_TIME - timedelta(hours=2)).timestamp()
    orphan.touch()
    import os

    os.utime(orphan, (old_timestamp, old_timestamp))
    cleaner = DraftCleaner(
        repository=repository,
        storage_root=tmp_path,
        stale_receiving_seconds=3600,
        orphan_part_seconds=3600,
    )

    report = cleaner.cleanup(now=BASE_TIME)

    final = repository.get(stale.attachment_id)
    assert final is not None and final.lifecycle == "deleted" and final.deleted_at == BASE_TIME
    assert report.deleted_attachment_ids == [stale.attachment_id]
    assert report.removed_orphan_parts == 1
    assert not orphan.exists()


def test_cleanup_retries_two_phase_physical_deletion_after_first_failure(tmp_path):
    repository = InMemoryAttachmentRepository()
    record = stored_record(expires_at=BASE_TIME - timedelta(seconds=1))
    seed_record(repository, record)
    blocked_path = tmp_path / str(record.storage_relative_path)
    blocked_path.mkdir(parents=True)
    cleaner = DraftCleaner(repository=repository, storage_root=tmp_path)

    first = cleaner.cleanup(now=BASE_TIME)

    pending = repository.get(record.attachment_id)
    assert first.deleted_attachment_ids == []
    assert pending is not None and pending.lifecycle == "deleted" and pending.deleted_at is None

    blocked_path.rmdir()
    blocked_path.write_bytes(b"content")
    second = cleaner.cleanup(now=BASE_TIME + timedelta(seconds=1))

    final = repository.get(record.attachment_id)
    assert second.deleted_attachment_ids == [record.attachment_id]
    assert final is not None and final.deleted_at == BASE_TIME + timedelta(seconds=1)
    assert not blocked_path.exists()


def test_worker_config_defaults_match_private_two_core_server_budget(monkeypatch):
    for key in [
        "ATTACHMENT_LIGHTWEIGHT_CONCURRENCY",
        "ATTACHMENT_OFFICE_CONCURRENCY",
        "ATTACHMENT_VISION_CONCURRENCY",
        "ATTACHMENT_PARSE_TIMEOUT_SECONDS",
        "ATTACHMENT_DRAFT_TTL_SECONDS",
    ]:
        monkeypatch.delenv(key, raising=False)

    config = AttachmentWorkerConfig.from_env()

    assert config.lightweight_concurrency == 2
    assert config.office_concurrency == 1
    assert config.vision_concurrency == 1
    assert config.parse_timeout_seconds == 120
    assert config.draft_ttl_seconds == 86400


def test_attachment_worker_compose_has_bounded_non_root_private_storage():
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()

    assert "  attachment-worker:\n" in compose
    attachment_worker = compose.split("  attachment-worker:\n", 1)[1].split("\n  worker:\n", 1)[0]
    assert 'cpus: "0.75"' in attachment_worker
    assert "mem_limit: 768m" in attachment_worker
    assert 'user: "65532:65532"' in attachment_worker
    assert "read_only: true" in attachment_worker
    assert "NOMI_ATTACHMENT_ROOT: ${NOMI_ATTACHMENT_ROOT:-/app/data/attachments}" in attachment_worker
    assert "attachment_data:${NOMI_ATTACHMENT_ROOT:-/app/data/attachments}" in attachment_worker

    runtime_api = compose.split("  runtime-api:\n", 1)[1].split("\n  opencode-artifact-worker:\n", 1)[0]
    assert "attachment_data:${NOMI_ATTACHMENT_ROOT:-/app/data/attachments}" in runtime_api
    assert "NOMI_ATTACHMENT_ROOT: ${NOMI_ATTACHMENT_ROOT:-/app/data/attachments}" in runtime_api
    assert "  attachment_data:\n" in compose
