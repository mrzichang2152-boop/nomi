from __future__ import annotations

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_postgres_repository_preserves_state_and_rejects_stale_writes():
    database_url = os.getenv("ASSISTANT_IDENTITY_POSTGRES_TEST_URL", "").strip()
    if not database_url:
        pytest.skip("ASSISTANT_IDENTITY_POSTGRES_TEST_URL is not configured")

    import psycopg

    from app.assistant_identity.models import AssistantIdentity
    from app.assistant_identity.repository import (
        AssistantIdentityVersionConflict,
        PostgresAssistantIdentityRepository,
    )
    from app.assistant_identity.schema import assistant_identity_schema_sql

    identity_id = f"nomi_gmail_contract_{uuid4().hex}"
    with psycopg.connect(database_url) as connection:
        try:
            for statement in assistant_identity_schema_sql():
                connection.execute(statement)
            repository = PostgresAssistantIdentityRepository(
                connection_factory=lambda: nullcontext(connection)
            )
            created = repository.add_if_missing(
                AssistantIdentity(
                    identity_id=identity_id,
                    kind="assistant_gmail",
                    display_name="Nomi",
                    address="",
                    status="unconfigured",
                    capabilities=["receive", "draft", "send", "thread_reply"],
                )
            )
            verified = repository.save(
                replace(
                    created,
                    provider="composio_gmail",
                    address="nomi.contract@example.com",
                    status="verifying",
                ),
                expected_version=created.version,
            )

            restored = repository.get(identity_id)
            duplicate_bootstrap = repository.add_if_missing(
                replace(created, address="placeholder@example.com")
            )

            assert restored == verified
            assert restored is not None
            assert restored.version == 2
            assert restored.address == "nomi.contract@example.com"
            assert duplicate_bootstrap.address == "nomi.contract@example.com"

            with pytest.raises(AssistantIdentityVersionConflict) as conflict:
                repository.save(
                    replace(created, display_name="stale"),
                    expected_version=created.version,
                )
            assert conflict.value.actual_version == 2
        finally:
            connection.rollback()


def test_postgres_outbound_claim_allows_only_one_cross_surface_send(monkeypatch):
    database_url = os.getenv("ASSISTANT_IDENTITY_POSTGRES_TEST_URL", "").strip()
    if not database_url:
        pytest.skip("ASSISTANT_IDENTITY_POSTGRES_TEST_URL is not configured")

    import psycopg

    from app.assistant_identity.outbound import OutboundMessagePipeline
    from app.assistant_identity.outbound_repository import PostgresAssistantOutboundRepository
    from app.assistant_identity.schema import assistant_identity_schema_sql

    class BlockingAdapter:
        def __init__(self):
            self.calls = []
            self.entered = threading.Event()
            self.release = threading.Event()
            self.lock = threading.Lock()

        def send_message(self, **values):
            with self.lock:
                self.calls.append(dict(values))
            self.entered.set()
            if not self.release.wait(timeout=5):
                raise TimeoutError("test did not release provider")
            return {
                "status": "sent",
                "provider": "postgres_concurrency_test",
                "provider_message_id": "pg-send-once",
                "provider_result": {"accepted": True},
            }

    with psycopg.connect(database_url) as connection:
        for statement in assistant_identity_schema_sql():
            connection.execute(statement)

    repository = PostgresAssistantOutboundRepository(
        connection_factory=lambda: psycopg.connect(database_url)
    )
    adapter = BlockingAdapter()
    first_surface = OutboundMessagePipeline(repository=repository, gmail_adapter=adapter)
    second_surface = OutboundMessagePipeline(repository=repository, gmail_adapter=adapter)
    monkeypatch.setenv("ASSISTANT_GMAIL_ADDRESS", "nomi@example.com")
    draft = first_surface.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="Postgres 并发确认",
        body_text="两端同时确认也只能发出一次。",
        source_evidence_ids=["evt-pg-concurrency"],
        idempotency_key=f"pg-concurrency-{uuid4().hex}",
    )
    web = first_surface.issue_confirmation(draft["draft_id"], actor="local_owner")
    android = second_surface.issue_confirmation(draft["draft_id"], actor="local_owner")

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(
                first_surface.confirm_and_send,
                draft["draft_id"],
                web["confirmation_token"],
                actor="local_owner",
            )
            assert adapter.entered.wait(timeout=3)
            second = pool.submit(
                second_surface.confirm_and_send,
                draft["draft_id"],
                android["confirmation_token"],
                actor="local_owner",
            )
            adapter.release.set()
            first.result(timeout=5)
            second.result(timeout=5)

        assert len(adapter.calls) == 1
        assert repository.get_draft(draft["draft_id"])["status"] == "sent"
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
