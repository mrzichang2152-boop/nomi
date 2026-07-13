from __future__ import annotations

from typing import Any, Callable, ContextManager


ATTACHMENT_PROCESSING_VERSION = "attachment-v1"


def attachment_schema_sql() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS chat_attachments (
          id UUID PRIMARY KEY,
          client_upload_id TEXT,
          sha256 TEXT,
          original_filename TEXT NOT NULL,
          safe_filename TEXT NOT NULL,
          declared_mime_type TEXT,
          detected_mime_type TEXT,
          extension TEXT,
          byte_size BIGINT NOT NULL DEFAULT 0,
          storage_relative_path TEXT,
          status TEXT NOT NULL,
          lifecycle TEXT NOT NULL DEFAULT 'draft',
          parser_kind TEXT,
          processing_version TEXT NOT NULL DEFAULT 'attachment-v1',
          error_code TEXT,
          error_detail_safe TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          stored_at TIMESTAMPTZ,
          processed_at TIMESTAMPTZ,
          attached_at TIMESTAMPTZ,
          expires_at TIMESTAMPTZ,
          deleted_at TIMESTAMPTZ,
          CHECK (status IN ('receiving', 'stored', 'processing', 'ready', 'rejected', 'failed')),
          CHECK (lifecycle IN ('draft', 'attached', 'deleted')),
          CHECK (byte_size >= 0)
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS chat_attachments_client_upload_id_uidx
        ON chat_attachments(client_upload_id)
        WHERE client_upload_id IS NOT NULL
        """,
        """
        CREATE INDEX IF NOT EXISTS chat_attachments_expiry_idx
        ON chat_attachments(expires_at)
        WHERE lifecycle = 'draft'
        """,
        """
        CREATE INDEX IF NOT EXISTS chat_attachments_sha256_idx
        ON chat_attachments(sha256, processing_version)
        WHERE sha256 IS NOT NULL
        """,
        """
        CREATE TABLE IF NOT EXISTS chat_attachment_derivatives (
          id UUID PRIMARY KEY,
          attachment_id UUID NOT NULL REFERENCES chat_attachments(id) ON DELETE CASCADE,
          kind TEXT NOT NULL,
          mime_type TEXT,
          storage_relative_path TEXT,
          byte_size BIGINT NOT NULL DEFAULT 0,
          locator JSONB NOT NULL DEFAULT '{}'::jsonb,
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          processing_version TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (byte_size >= 0)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS chat_attachment_derivatives_attachment_idx
        ON chat_attachment_derivatives(attachment_id, kind, created_at)
        """,
        """
        CREATE TABLE IF NOT EXISTS chat_attachment_chunks (
          id UUID PRIMARY KEY,
          attachment_id UUID NOT NULL REFERENCES chat_attachments(id) ON DELETE CASCADE,
          ordinal INTEGER NOT NULL,
          text TEXT NOT NULL,
          token_count INTEGER NOT NULL,
          locator JSONB NOT NULL DEFAULT '{}'::jsonb,
          content_hash TEXT NOT NULL,
          embedding vector(384),
          processing_version TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (attachment_id, processing_version, ordinal),
          CHECK (ordinal >= 0),
          CHECK (token_count >= 0)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS chat_attachment_chunks_attachment_idx
        ON chat_attachment_chunks(attachment_id, processing_version, ordinal)
        """,
        """
        CREATE INDEX IF NOT EXISTS chat_attachment_chunks_text_idx
        ON chat_attachment_chunks USING GIN (to_tsvector('simple', text))
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_turn_attachments (
          turn_id UUID NOT NULL REFERENCES assistant_turns(id) ON DELETE CASCADE,
          attachment_id UUID NOT NULL REFERENCES chat_attachments(id) ON DELETE CASCADE,
          ordinal INTEGER NOT NULL,
          purpose TEXT NOT NULL DEFAULT 'user_provided',
          PRIMARY KEY (turn_id, attachment_id),
          UNIQUE (turn_id, ordinal),
          CHECK (ordinal >= 0)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS assistant_turn_attachments_attachment_idx
        ON assistant_turn_attachments(attachment_id, turn_id)
        """,
    ]


def ensure_attachment_schema(
    connection_factory: Callable[[], ContextManager[Any]],
) -> None:
    with connection_factory() as conn:
        for statement in attachment_schema_sql():
            conn.execute(statement)
