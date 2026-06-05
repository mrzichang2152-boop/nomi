from __future__ import annotations


def assistant_identity_schema_sql() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS assistant_identities (
          id UUID PRIMARY KEY,
          identity_id TEXT NOT NULL UNIQUE,
          kind TEXT NOT NULL,
          display_name TEXT NOT NULL DEFAULT 'Nomi',
          address TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'configured',
          capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_identity_credentials (
          id UUID PRIMARY KEY,
          identity_id TEXT NOT NULL REFERENCES assistant_identities(identity_id) ON DELETE CASCADE,
          provider TEXT NOT NULL,
          encrypted_ref TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'configured',
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(identity_id, provider)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_inbox_events (
          id UUID PRIMARY KEY,
          identity_id TEXT NOT NULL REFERENCES assistant_identities(identity_id) ON DELETE CASCADE,
          source_type TEXT NOT NULL,
          conversation_id TEXT NOT NULL DEFAULT '',
          external_message_id TEXT NOT NULL,
          sender_key TEXT NOT NULL,
          sender_class TEXT NOT NULL DEFAULT '',
          classification TEXT NOT NULL,
          normalized_text TEXT NOT NULL DEFAULT '',
          normalized_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          visibility_scope TEXT NOT NULL DEFAULT 'assistant_identity_thread',
          source_evidence_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          occurred_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(identity_id, external_message_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_message_drafts (
          id UUID PRIMARY KEY,
          draft_id TEXT NOT NULL UNIQUE,
          identity_id TEXT NOT NULL REFERENCES assistant_identities(identity_id) ON DELETE CASCADE,
          channel TEXT NOT NULL,
          recipient TEXT NOT NULL,
          subject TEXT NOT NULL DEFAULT '',
          body_text TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'draft',
          confirmation_required BOOLEAN NOT NULL DEFAULT TRUE,
          source_evidence_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          risk_notes JSONB NOT NULL DEFAULT '[]'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_outbound_messages (
          id UUID PRIMARY KEY,
          draft_id TEXT NOT NULL REFERENCES assistant_message_drafts(draft_id) ON DELETE CASCADE,
          identity_id TEXT NOT NULL,
          channel TEXT NOT NULL,
          recipient TEXT NOT NULL,
          provider_message_id TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'sending',
          body_hash TEXT NOT NULL DEFAULT '',
          confirmation_actor TEXT NOT NULL DEFAULT '',
          provider_result JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_delivery_receipts (
          id UUID PRIMARY KEY,
          outbound_message_id UUID REFERENCES assistant_outbound_messages(id) ON DELETE SET NULL,
          identity_id TEXT NOT NULL,
          provider_message_id TEXT NOT NULL,
          status TEXT NOT NULL,
          receipt_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          occurred_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_contact_bindings (
          id UUID PRIMARY KEY,
          contact_id TEXT NOT NULL,
          channel TEXT NOT NULL,
          sender_key TEXT NOT NULL,
          display_name TEXT NOT NULL DEFAULT '',
          trust_level TEXT NOT NULL DEFAULT 'known',
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(channel, sender_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_channel_policies (
          id UUID PRIMARY KEY,
          identity_id TEXT NOT NULL REFERENCES assistant_identities(identity_id) ON DELETE CASCADE,
          channel TEXT NOT NULL,
          third_party_send_requires_confirmation BOOLEAN NOT NULL DEFAULT TRUE,
          low_risk_user_ack_allowed BOOLEAN NOT NULL DEFAULT FALSE,
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(identity_id, channel)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS assistant_inbox_events_classification_idx
        ON assistant_inbox_events(classification, created_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS assistant_message_drafts_status_idx
        ON assistant_message_drafts(status, created_at DESC)
        """,
    ]
