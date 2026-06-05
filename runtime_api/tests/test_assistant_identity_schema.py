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


def test_assistant_identity_schema_has_confirmation_and_scope_columns():
    from app.assistant_identity.schema import assistant_identity_schema_sql

    normalized = "\n".join(" ".join(sql.split()) for sql in assistant_identity_schema_sql())

    assert "third_party_send_requires_confirmation BOOLEAN NOT NULL DEFAULT TRUE" in normalized
    assert "visibility_scope TEXT NOT NULL DEFAULT" in normalized
    assert "source_evidence_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]" in normalized
    assert "confirmation_actor TEXT NOT NULL DEFAULT" in normalized
