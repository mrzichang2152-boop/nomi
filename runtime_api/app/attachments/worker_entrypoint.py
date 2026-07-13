from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path
from typing import Optional

import psycopg
import redis

from app.attachments.queue import RedisAttachmentQueue
from app.attachments.repository import PostgresAttachmentRepository
from app.attachments.schema import ensure_attachment_schema
from app.attachments.worker import (
    AttachmentOutboxCleaner,
    AttachmentParser,
    AttachmentWorker,
    AttachmentWorkerConfig,
    DraftCleaner,
)


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


def run() -> None:
    config = AttachmentWorkerConfig.from_env()
    storage_root = Path(os.getenv("NOMI_ATTACHMENT_ROOT", "/app/data/attachments"))
    poll_seconds = max(0.1, float(os.getenv("ATTACHMENT_WORKER_POLL_SECONDS", "1")))
    cleanup_interval = max(30.0, float(os.getenv("ATTACHMENT_CLEANUP_INTERVAL_SECONDS", "300")))
    worker_id = os.getenv("ATTACHMENT_WORKER_ID", f"{socket.gethostname()}:{os.getpid()}")

    ensure_attachment_schema(_connection_factory)
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
        result = worker.run_next()
        if result is None:
            time.sleep(poll_seconds)
            continue
        _event(
            "attachment_job_finished",
            attachment_id=result.attachment_id,
            status=result.status,
        )


if __name__ == "__main__":
    run()
