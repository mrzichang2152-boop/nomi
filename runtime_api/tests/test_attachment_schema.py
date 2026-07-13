from __future__ import annotations

from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from app.attachments.schema import attachment_schema_sql


ROOT = Path(__file__).resolve().parents[2]


def normalized_sql(statements: list[str] | tuple[str, ...]) -> str:
    return " ".join(" ".join(statement.split()) for statement in statements).lower()


def assert_attachment_schema_contract(sql: str) -> None:
    for table in (
        "chat_attachments",
        "chat_attachment_derivatives",
        "chat_attachment_chunks",
        "assistant_turn_attachments",
    ):
        assert f"create table if not exists {table}" in sql

    assert "client_upload_id text" in sql
    assert "storage_relative_path text" in sql
    assert "status text not null" in sql
    assert "lifecycle text not null default 'draft'" in sql
    assert "processing_version text not null" in sql
    assert "locator jsonb not null default '{}'::jsonb" in sql
    assert "embedding vector(384)" in sql
    assert "references chat_attachments(id) on delete cascade" in sql
    assert "references assistant_turns(id) on delete cascade" in sql
    assert "primary key (turn_id, attachment_id)" in sql
    assert "unique (turn_id, ordinal)" in sql
    assert "unique index if not exists chat_attachments_client_upload_id_uidx" in sql
    assert "chat_attachments_expiry_idx" in sql
    assert "check (status in ('receiving', 'stored', 'processing', 'ready', 'rejected', 'failed'))" in sql
    assert "check (lifecycle in ('draft', 'attached', 'deleted'))" in sql


def test_runtime_attachment_schema_contains_constraints_and_indexes():
    assert_attachment_schema_contract(normalized_sql(attachment_schema_sql()))


def test_fresh_install_schema_matches_runtime_attachment_contract():
    init_sql = " ".join((ROOT / "db" / "init.sql").read_text(encoding="utf-8").split()).lower()
    assert_attachment_schema_contract(init_sql)


def test_main_bootstraps_attachment_schema_after_assistant_context_schema():
    source = (ROOT / "runtime_api" / "app" / "main.py").read_text(encoding="utf-8")
    assistant_index = source.index("ensure_assistant_context_schema()")
    attachment_index = source.index("ensure_attachment_schema()")

    assert attachment_index > assistant_index
