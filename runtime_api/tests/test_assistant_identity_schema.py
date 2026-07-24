import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_assistant_identity_schema_contains_required_tables():
    from app.assistant_identity.schema import assistant_identity_schema_sql

    sql = "\n".join(assistant_identity_schema_sql())

    assert "CREATE TABLE IF NOT EXISTS assistant_identities" in sql
    assert "CREATE TABLE IF NOT EXISTS assistant_identity_credentials" in sql
    assert "CREATE TABLE IF NOT EXISTS assistant_inbox_events" in sql
    assert "CREATE TABLE IF NOT EXISTS assistant_message_drafts" in sql
    assert "CREATE TABLE IF NOT EXISTS assistant_outbound_messages" in sql
    assert "CREATE TABLE IF NOT EXISTS assistant_delivery_receipts" in sql
    assert "CREATE TABLE IF NOT EXISTS assistant_contact_bindings" in sql
    assert "CREATE TABLE IF NOT EXISTS assistant_channel_policies" in sql
    assert "CREATE TABLE IF NOT EXISTS assistant_outbound_confirmations" in sql
    assert "CREATE TABLE IF NOT EXISTS assistant_identity_audit_events" in sql


def test_assistant_identity_schema_has_confirmation_and_scope_columns():
    from app.assistant_identity.schema import assistant_identity_schema_sql

    normalized = "\n".join(" ".join(sql.split()) for sql in assistant_identity_schema_sql())

    assert "third_party_send_requires_confirmation BOOLEAN NOT NULL DEFAULT TRUE" in normalized
    assert "visibility_scope TEXT NOT NULL DEFAULT" in normalized
    assert "source_evidence_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]" in normalized
    assert "confirmation_actor TEXT NOT NULL DEFAULT" in normalized
    assert "token_hash TEXT NOT NULL UNIQUE" in normalized
    assert "protected_hash TEXT NOT NULL" in normalized
    assert "expires_at TIMESTAMPTZ NOT NULL" in normalized
    assert "consumed_at TIMESTAMPTZ" in normalized
    assert "invalidated_at TIMESTAMPTZ" in normalized


def test_assistant_outbound_schema_supports_restart_safe_idempotency_and_redacted_audit():
    from app.assistant_identity.schema import assistant_identity_schema_sql

    normalized = "\n".join(" ".join(sql.split()) for sql in assistant_identity_schema_sql())

    assert "idempotency_key TEXT NOT NULL DEFAULT ''" in normalized
    assert "task_id TEXT NOT NULL DEFAULT ''" in normalized
    assert "body_hash TEXT NOT NULL DEFAULT ''" in normalized
    assert "state JSONB NOT NULL DEFAULT '{}'::jsonb" in normalized
    assert "CREATE UNIQUE INDEX IF NOT EXISTS assistant_message_drafts_idempotency_idx" in normalized
    assert "WHERE idempotency_key <> ''" in normalized
    assert "action TEXT NOT NULL" in normalized
    assert "actor TEXT NOT NULL DEFAULT ''" in normalized
    assert "trace_id TEXT NOT NULL" in normalized
    assert "redacted_payload JSONB NOT NULL DEFAULT '{}'::jsonb" in normalized
    assert "confirmation_token" not in normalized.lower()


def test_assistant_inbox_schema_persists_stable_public_event_id():
    from app.assistant_identity.schema import assistant_identity_schema_sql

    normalized = "\n".join(" ".join(sql.split()) for sql in assistant_identity_schema_sql())

    assert "event_id TEXT NOT NULL" in normalized
    assert "CREATE UNIQUE INDEX IF NOT EXISTS assistant_inbox_events_event_id_idx" in normalized


def test_assistant_identity_schema_supports_provider_derived_lifecycle_and_health_history():
    from app.assistant_identity.schema import assistant_identity_schema_sql

    normalized = "\n".join(" ".join(sql.split()) for sql in assistant_identity_schema_sql())

    assert "status TEXT NOT NULL DEFAULT 'unconfigured'" in normalized
    assert "provider TEXT NOT NULL DEFAULT ''" in normalized
    assert "version BIGINT NOT NULL DEFAULT 1" in normalized
    assert "last_verified_at TIMESTAMPTZ" in normalized
    assert "last_error_code TEXT NOT NULL DEFAULT ''" in normalized
    assert "CREATE TABLE IF NOT EXISTS assistant_identity_health_checks" in normalized
    assert "check_type TEXT NOT NULL" in normalized
    assert "latency_ms INTEGER" in normalized
    assert "checked_at TIMESTAMPTZ NOT NULL DEFAULT now()" in normalized
    assert "expires_at TIMESTAMPTZ" in normalized


def test_assistant_identity_schema_migrates_existing_rows_without_raw_tokens():
    from app.assistant_identity.schema import assistant_identity_schema_sql

    normalized = "\n".join(" ".join(sql.split()) for sql in assistant_identity_schema_sql())

    assert "ALTER TABLE assistant_identities ADD COLUMN IF NOT EXISTS provider" in normalized
    assert "ALTER TABLE assistant_identities ADD COLUMN IF NOT EXISTS version" in normalized
    assert "ALTER TABLE assistant_identity_credentials ADD COLUMN IF NOT EXISTS expires_at" in normalized
    assert "access_token" not in normalized.lower()


def test_database_bootstrap_contains_restart_safe_assistant_identity_tables():
    init_sql = (Path(__file__).resolve().parents[2] / "db" / "init.sql").read_text()
    normalized = " ".join(init_sql.split())

    assert "CREATE TABLE IF NOT EXISTS assistant_identities" in normalized
    assert "CREATE TABLE IF NOT EXISTS assistant_message_drafts" in normalized
    assert "CREATE TABLE IF NOT EXISTS assistant_outbound_confirmations" in normalized
    assert "CREATE TABLE IF NOT EXISTS assistant_outbound_messages" in normalized
    assert "CREATE TABLE IF NOT EXISTS assistant_delivery_receipts" in normalized
    assert "CREATE TABLE IF NOT EXISTS assistant_identity_audit_events" in normalized
    assert "token_hash TEXT NOT NULL UNIQUE" in normalized
    assert "confirmation_token" not in normalized.lower()
