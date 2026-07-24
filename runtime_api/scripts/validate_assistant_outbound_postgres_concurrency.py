from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg

from app.assistant_identity.outbound import OutboundMessagePipeline
from app.assistant_identity.outbound_repository import PostgresAssistantOutboundRepository
from app.assistant_identity.schema import assistant_identity_schema_sql


class BlockingAdapter:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()

    def send_message(self, **values):
        with self.lock:
            self.calls.append(dict(values))
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("validation did not release provider")
        return {
            "status": "sent",
            "provider": "postgres_concurrency_validation",
            "provider_message_id": "pg-send-once",
            "provider_result": {"accepted": True},
        }


def main() -> None:
    database_url = os.environ["ASSISTANT_IDENTITY_POSTGRES_TEST_URL"]
    os.environ["ASSISTANT_GMAIL_ADDRESS"] = "nomi@example.com"
    with psycopg.connect(database_url) as connection:
        for statement in assistant_identity_schema_sql():
            connection.execute(statement)

    repository = PostgresAssistantOutboundRepository(
        connection_factory=lambda: psycopg.connect(database_url)
    )
    adapter = BlockingAdapter()
    web = OutboundMessagePipeline(repository=repository, gmail_adapter=adapter)
    android = OutboundMessagePipeline(repository=repository, gmail_adapter=adapter)
    draft = web.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="Postgres concurrency validation",
        body_text="Two confirmation tokens must still produce one provider call.",
        source_evidence_ids=["evt-pg-concurrency-validation"],
        idempotency_key=f"pg-concurrency-validation-{uuid4().hex}",
    )
    web_confirmation = web.issue_confirmation(draft["draft_id"], actor="local_owner")
    android_confirmation = android.issue_confirmation(draft["draft_id"], actor="local_owner")
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(
                web.confirm_and_send,
                draft["draft_id"],
                web_confirmation["confirmation_token"],
                actor="local_owner",
            )
            if not adapter.entered.wait(timeout=3):
                raise AssertionError("first provider call did not start")
            second = pool.submit(
                android.confirm_and_send,
                draft["draft_id"],
                android_confirmation["confirmation_token"],
                actor="local_owner",
            )
            adapter.release.set()
            first.result(timeout=5)
            second.result(timeout=5)

        current = repository.get_draft(draft["draft_id"])
        result = {
            "provider_call_count": len(adapter.calls),
            "final_status": current.get("status") if current else "missing",
            "revision": current.get("revision") if current else None,
            "passed": len(adapter.calls) == 1 and current is not None and current.get("status") == "sent",
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if not result["passed"]:
            raise SystemExit(1)
    finally:
        with psycopg.connect(database_url) as connection:
            connection.execute(
                "DELETE FROM assistant_outbound_confirmations WHERE draft_id = %s",
                (draft["draft_id"],),
            )
            connection.execute(
                "DELETE FROM assistant_outbound_messages WHERE draft_id = %s",
                (draft["draft_id"],),
            )
            connection.execute(
                "DELETE FROM assistant_message_drafts WHERE draft_id = %s",
                (draft["draft_id"],),
            )


if __name__ == "__main__":
    main()
