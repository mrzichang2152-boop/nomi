from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Protocol
from uuid import UUID

from app.attachments.models import (
    AttachmentErrorCode,
    AttachmentRejected,
    SAFE_ATTACHMENT_ERROR_MESSAGES,
)
from app.attachments.parsers.common import ParseResult, ParsedDerivative
from app.attachments.queue import QueueItem
from app.attachments.repository import AttachmentRecord, AttachmentRepository
from app.attachments.storage import resolve_storage_path


@dataclass(frozen=True)
class WorkerRunResult:
    attachment_id: UUID
    status: str
    parse_result: Optional[ParseResult] = None


@dataclass(frozen=True)
class CleanupReport:
    deleted_attachment_ids: list[UUID]
    removed_orphan_parts: int


@dataclass(frozen=True)
class AttachmentWorkerConfig:
    lightweight_concurrency: int = 2
    office_concurrency: int = 1
    vision_concurrency: int = 1
    parse_timeout_seconds: float = 120
    lease_seconds: int = 180
    draft_ttl_seconds: int = 86400

    @classmethod
    def from_env(cls) -> "AttachmentWorkerConfig":
        return cls(
            lightweight_concurrency=max(1, int(os.getenv("ATTACHMENT_LIGHTWEIGHT_CONCURRENCY", "2"))),
            office_concurrency=max(1, int(os.getenv("ATTACHMENT_OFFICE_CONCURRENCY", "1"))),
            vision_concurrency=max(1, int(os.getenv("ATTACHMENT_VISION_CONCURRENCY", "1"))),
            parse_timeout_seconds=max(0.01, float(os.getenv("ATTACHMENT_PARSE_TIMEOUT_SECONDS", "120"))),
            lease_seconds=max(1, int(os.getenv("ATTACHMENT_LEASE_SECONDS", "180"))),
            draft_ttl_seconds=max(60, int(os.getenv("ATTACHMENT_DRAFT_TTL_SECONDS", "86400"))),
        )


class AttachmentParser(Protocol):
    def parse(self, record: AttachmentRecord, source_path: Path) -> ParseResult:
        ...


class AttachmentQueue(Protocol):
    def claim(self, worker_id: str, *, lease_seconds: int, now: Optional[datetime] = None) -> Optional[QueueItem]:
        ...

    def ack(self, item: QueueItem, worker_id: str) -> bool:
        ...


class AttachmentWorker:
    _OFFICE_KINDS = frozenset({"docx", "pptx", "xlsx"})
    _VISION_KINDS = frozenset({"image"})

    def __init__(
        self,
        *,
        repository: AttachmentRepository,
        queue: AttachmentQueue,
        storage_root: Path,
        parser: AttachmentParser,
        config: Optional[AttachmentWorkerConfig] = None,
        worker_id: str = "attachment-worker",
    ) -> None:
        self.repository = repository
        self.queue = queue
        self.storage_root = Path(storage_root)
        self.parser = parser
        self.config = config or AttachmentWorkerConfig.from_env()
        self.worker_id = worker_id
        self._semaphores = {
            "lightweight": threading.BoundedSemaphore(self.config.lightweight_concurrency),
            "office": threading.BoundedSemaphore(self.config.office_concurrency),
            "vision": threading.BoundedSemaphore(self.config.vision_concurrency),
        }

    def _category(self, record: AttachmentRecord) -> str:
        kind = str(record.parser_kind or "").lower()
        if kind in self._OFFICE_KINDS:
            return "office"
        if kind in self._VISION_KINDS:
            return "vision"
        return "lightweight"

    def _parse_with_timeout(self, record: AttachmentRecord, source_path: Path) -> ParseResult:
        semaphore = self._semaphores[self._category(record)]

        def invoke() -> ParseResult:
            with semaphore:
                return self.parser.parse(record, source_path)

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="attachment-parser")
        future = executor.submit(invoke)
        try:
            return future.result(timeout=self.config.parse_timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise TimeoutError("attachment_parse_timeout") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _materialize_derivatives(
        self,
        record: AttachmentRecord,
        result: ParseResult,
    ) -> ParseResult:
        materialized: list[ParsedDerivative] = []
        for derivative in result.derivatives:
            if not derivative.payload:
                materialized.append(derivative)
                continue
            extension = derivative.extension if derivative.extension.startswith(".") else f".{derivative.extension}"
            relative_path = (
                Path("derivatives")
                / record.attachment_id.hex[:2]
                / str(record.attachment_id)
                / record.processing_version
                / f"{uuid.uuid4().hex}{extension}"
            )
            destination = resolve_storage_path(self.storage_root, str(relative_path))
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(f"{destination.suffix}.part")
            try:
                with temporary.open("wb") as output:
                    output.write(derivative.payload)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
            materialized.append(
                replace(
                    derivative,
                    payload=b"",
                    storage_relative_path=str(relative_path),
                )
            )
        return replace(result, derivatives=tuple(materialized), derivative_count=len(materialized))

    def run_next(self, *, now: Optional[datetime] = None) -> Optional[WorkerRunResult]:
        active_now = now or datetime.now(timezone.utc)
        item = self.queue.claim(
            self.worker_id,
            lease_seconds=self.config.lease_seconds,
            now=active_now,
        )
        if item is None:
            return None

        record = self.repository.mark_processing(item.attachment_id, item.processing_version)
        if record is None:
            self.queue.ack(item, self.worker_id)
            return WorkerRunResult(item.attachment_id, "skipped")

        if not record.storage_relative_path:
            final = self.repository.mark_failed(
                item.attachment_id,
                error_code=AttachmentErrorCode.PARSE_FAILED.value,
                error_detail_safe="文件解析失败，可重试或重新选择文件。",
            )
            self.queue.ack(item, self.worker_id)
            return WorkerRunResult(final.attachment_id, final.status)

        source_path = resolve_storage_path(self.storage_root, record.storage_relative_path)
        try:
            parse_result = self._parse_with_timeout(record, source_path)
        except AttachmentRejected as rejected:
            final = self.repository.mark_rejected(
                item.attachment_id,
                error_code=rejected.code,
                error_detail_safe=rejected.safe_message,
            )
            self.queue.ack(item, self.worker_id)
            return WorkerRunResult(final.attachment_id, final.status)
        except TimeoutError:
            final = self.repository.mark_failed(
                item.attachment_id,
                error_code=AttachmentErrorCode.PARSE_TIMEOUT.value,
                error_detail_safe=SAFE_ATTACHMENT_ERROR_MESSAGES[AttachmentErrorCode.PARSE_TIMEOUT],
            )
            self.queue.ack(item, self.worker_id)
            return WorkerRunResult(final.attachment_id, final.status)
        except Exception:
            final = self.repository.mark_failed(
                item.attachment_id,
                error_code=AttachmentErrorCode.PARSE_FAILED.value,
                error_detail_safe="文件解析失败，可重试或重新选择文件。",
            )
            self.queue.ack(item, self.worker_id)
            return WorkerRunResult(final.attachment_id, final.status)

        persisted_result: Optional[ParseResult] = None
        try:
            persisted_result = self._materialize_derivatives(record, parse_result)
            final = self.repository.persist_parse_result(
                item.attachment_id,
                item.processing_version,
                persisted_result,
                processed_at=active_now,
            )
        except Exception:
            if persisted_result is not None:
                for derivative in persisted_result.derivatives:
                    if not derivative.storage_relative_path:
                        continue
                    try:
                        resolve_storage_path(
                            self.storage_root,
                            derivative.storage_relative_path,
                        ).unlink(missing_ok=True)
                    except OSError:
                        pass
            final = self.repository.mark_failed(
                item.attachment_id,
                error_code=AttachmentErrorCode.PARSE_FAILED.value,
                error_detail_safe="文件解析失败，可重试或重新选择文件。",
            )
            self.queue.ack(item, self.worker_id)
            return WorkerRunResult(final.attachment_id, final.status)
        self.queue.ack(item, self.worker_id)
        return WorkerRunResult(final.attachment_id, final.status, parse_result=persisted_result)


class AttachmentOutboxCleaner:
    def __init__(
        self,
        *,
        repository: AttachmentRepository,
        storage_root: Path,
        lease_seconds: int = 120,
    ) -> None:
        self.repository = repository
        self.storage_root = Path(storage_root)
        self.lease_seconds = max(1, int(lease_seconds))

    def run_next(self, *, now: Optional[datetime] = None) -> Optional[str]:
        active_now = now or datetime.now(timezone.utc)
        item = self.repository.claim_cleanup_outbox(
            now=active_now,
            lease_seconds=self.lease_seconds,
        )
        if item is None:
            return None
        try:
            resolve_storage_path(
                self.storage_root,
                item.storage_relative_path,
            ).unlink(missing_ok=True)
        except (AttachmentRejected, OSError):
            retry_delay = min(3600, 2 ** min(max(1, item.attempt_count), 10))
            self.repository.retry_cleanup_outbox(
                item.outbox_id,
                available_at=active_now + timedelta(seconds=retry_delay),
                error_code="physical_delete_failed",
            )
            return "retry_scheduled"
        self.repository.complete_cleanup_outbox(
            item.outbox_id,
            completed_at=active_now,
        )
        return "completed"


class DraftCleaner:
    def __init__(
        self,
        *,
        repository: AttachmentRepository,
        storage_root: Path,
        stale_receiving_seconds: int = 3600,
        orphan_part_seconds: int = 3600,
    ) -> None:
        self.repository = repository
        self.storage_root = Path(storage_root)
        self.stale_receiving_seconds = stale_receiving_seconds
        self.orphan_part_seconds = orphan_part_seconds

    def cleanup(self, *, now: Optional[datetime] = None) -> CleanupReport:
        active_now = now or datetime.now(timezone.utc)
        candidates = self.repository.list_expired_drafts(
            now=active_now,
            stale_receiving_before=active_now - timedelta(seconds=self.stale_receiving_seconds),
        )
        deleted_ids: list[UUID] = []
        for candidate in candidates:
            marked = self.repository.mark_lifecycle_deleted(candidate.attachment_id)
            if marked is None:
                continue
            storage_paths = self.repository.list_storage_paths(marked.attachment_id)
            deletion_failed = False
            for relative_path in storage_paths:
                path = resolve_storage_path(self.storage_root, relative_path)
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    deletion_failed = True
                    break
            if deletion_failed:
                continue
            self.repository.complete_deleted(marked.attachment_id, deleted_at=active_now)
            deleted_ids.append(marked.attachment_id)

        removed_parts = 0
        cutoff = (active_now - timedelta(seconds=self.orphan_part_seconds)).timestamp()
        temporary_root = self.storage_root / "temporary"
        if temporary_root.exists():
            for part in temporary_root.rglob("*.part"):
                try:
                    if part.is_file() and part.stat().st_mtime <= cutoff:
                        part.unlink()
                        removed_parts += 1
                except OSError:
                    continue
        return CleanupReport(deleted_ids, removed_parts)


__all__ = [
    "AttachmentOutboxCleaner",
    "AttachmentParser",
    "AttachmentWorker",
    "AttachmentWorkerConfig",
    "CleanupReport",
    "DraftCleaner",
    "ParseResult",
    "WorkerRunResult",
]
