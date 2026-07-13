from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path
from typing import Any, Optional

import psycopg
import redis

from app.attachments.queue import RedisAttachmentQueue
from app.attachments.repository import PostgresAttachmentRepository
from app.attachments.schema import ensure_attachment_schema
from app.attachments.worker import (
    AttachmentFullInspectionWorker,
    AttachmentOutboxCleaner,
    AttachmentParser,
    AttachmentWorker,
    AttachmentWorkerConfig,
    DatabaseAttachmentLocatorInspector,
    DraftCleaner,
    PostgresFullInspectionRepository,
)
from app.task_orchestrator import task_orchestrator_schema_sql


def _connection_factory():
    return psycopg.connect(os.environ["DATABASE_URL"])


def _load_parser() -> Optional[AttachmentParser]:
    try:
        from app.attachments.parsers import build_default_attachment_parser
    except ModuleNotFoundError:
        return None
    return build_default_attachment_parser()


def _event(name: str, **details: object) -> None:
    print(json.dumps({"event": name, **details}, ensure_ascii=False, default=str), flush=True)


def _ensure_task_schema() -> None:
    with _connection_factory() as conn:
        for statement in task_orchestrator_schema_sql():
            conn.execute(statement)


def run_worker_cycle(
    attachment_worker: Any,
    full_inspection_worker: Any,
) -> tuple[Any, Any]:
    return attachment_worker.run_next(), full_inspection_worker.run_next()


def run() -> None:
    config = AttachmentWorkerConfig.from_env()
    storage_root = Path(os.getenv("NOMI_ATTACHMENT_ROOT", "/app/data/attachments"))
    poll_seconds = max(0.1, float(os.getenv("ATTACHMENT_WORKER_POLL_SECONDS", "1")))
    cleanup_interval = max(30.0, float(os.getenv("ATTACHMENT_CLEANUP_INTERVAL_SECONDS", "300")))
    worker_id = os.getenv("ATTACHMENT_WORKER_ID", f"{socket.gethostname()}:{os.getpid()}")

    ensure_attachment_schema(_connection_factory)
    _ensure_task_schema()
    repository = PostgresAttachmentRepository(_connection_factory)
    redis_client = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    queue = RedisAttachmentQueue(redis_client)
    cleaner = DraftCleaner(repository=repository, storage_root=storage_root)
    outbox_cleaner = AttachmentOutboxCleaner(repository=repository, storage_root=storage_root)

    parser = _load_parser()
    if parser is None:
        _event("attachment_worker_waiting_for_parser", worker_id=worker_id)
        while parser is None:
            time.sleep(5)
            parser = _load_parser()

    worker = AttachmentWorker(
        repository=repository,
        queue=queue,
        storage_root=storage_root,
        parser=parser,
        config=config,
        worker_id=worker_id,
    )
    full_inspection_worker = AttachmentFullInspectionWorker(
        repository=PostgresFullInspectionRepository(_connection_factory),
        inspector=DatabaseAttachmentLocatorInspector(_connection_factory),
        worker_id=f"{worker_id}:full-inspection",
        lease_seconds=config.lease_seconds,
    )
    _event(
        "attachment_worker_started",
        worker_id=worker_id,
        lightweight_concurrency=config.lightweight_concurrency,
        office_concurrency=config.office_concurrency,
        vision_concurrency=config.vision_concurrency,
        parse_timeout_seconds=config.parse_timeout_seconds,
    )

    last_cleanup = 0.0
    while True:
        now_monotonic = time.monotonic()
        queue.recover_expired()
        if now_monotonic - last_cleanup >= cleanup_interval:
            report = cleaner.cleanup()
            outbox_completed = 0
            outbox_retried = 0
            for _ in range(100):
                outbox_status = outbox_cleaner.run_next()
                if outbox_status is None:
                    break
                if outbox_status == "completed":
                    outbox_completed += 1
                elif outbox_status == "retry_scheduled":
                    outbox_retried += 1
            _event(
                "attachment_cleanup_finished",
                deleted_count=len(report.deleted_attachment_ids),
                removed_orphan_parts=report.removed_orphan_parts,
                outbox_completed=outbox_completed,
                outbox_retried=outbox_retried,
            )
            last_cleanup = now_monotonic
        result, inspection_result = run_worker_cycle(worker, full_inspection_worker)
        if result is None and inspection_result is None:
            time.sleep(poll_seconds)
            continue
        if result is not None:
            _event(
                "attachment_job_finished",
                attachment_id=result.attachment_id,
                status=result.status,
            )
        if inspection_result is not None:
            _event(
                "attachment_full_inspection_batch_finished",
                task_run_id=inspection_result.task_run_id,
                task_step_id=inspection_result.task_step_id,
                status=inspection_result.status,
                coverage_status=inspection_result.coverage_status,
                progress=inspection_result.progress,
            )


if __name__ == "__main__":
    run()
