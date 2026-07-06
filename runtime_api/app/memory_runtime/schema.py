from __future__ import annotations


def memory_runtime_phase1_schema_sql() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS collector_sessions (
          id UUID PRIMARY KEY,
          source TEXT NOT NULL DEFAULT '',
          account_id TEXT NOT NULL DEFAULT '',
          browser_profile_id TEXT NOT NULL DEFAULT '',
          login_state TEXT NOT NULL DEFAULT 'unknown',
          last_heartbeat_at TIMESTAMPTZ,
          last_success_event_at TIMESTAMPTZ,
          last_error_code TEXT NOT NULL DEFAULT '',
          last_error_message TEXT NOT NULL DEFAULT '',
          reconnect_attempts INTEGER NOT NULL DEFAULT 0,
          session_version TEXT NOT NULL DEFAULT '',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_ingest_events (
          id UUID PRIMARY KEY,
          source_event_uid TEXT NOT NULL UNIQUE,
          source_fingerprint TEXT NOT NULL DEFAULT '',
          source TEXT NOT NULL DEFAULT '',
          account_id TEXT NOT NULL DEFAULT '',
          conversation_id TEXT NOT NULL DEFAULT '',
          contact_id TEXT NOT NULL DEFAULT '',
          speaker_id TEXT NOT NULL DEFAULT '',
          message_id TEXT NOT NULL DEFAULT '',
          source_created_at TIMESTAMPTZ,
          observed_at TIMESTAMPTZ,
          payload_hash TEXT NOT NULL DEFAULT '',
          raw_event_id TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'raw_written',
          attempts INTEGER NOT NULL DEFAULT 0,
          last_error TEXT NOT NULL DEFAULT '',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_dead_letters (
          id UUID PRIMARY KEY,
          ingest_event_id UUID,
          failure_stage TEXT NOT NULL DEFAULT '',
          error_code TEXT NOT NULL DEFAULT '',
          error_message TEXT NOT NULL DEFAULT '',
          payload_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_evidence (
          id UUID PRIMARY KEY,
          source_event_id TEXT NOT NULL DEFAULT '',
          source TEXT NOT NULL DEFAULT '',
          account_id TEXT NOT NULL DEFAULT '',
          conversation_id TEXT NOT NULL DEFAULT '',
          contact_id TEXT NOT NULL DEFAULT '',
          speaker_id TEXT NOT NULL DEFAULT '',
          observed_at TIMESTAMPTZ,
          source_created_at TIMESTAMPTZ,
          source_version TEXT NOT NULL DEFAULT '',
          text_excerpt TEXT NOT NULL DEFAULT '',
          raw_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
          scope JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_retrieval_traces (
          id UUID PRIMARY KEY,
          request_event_id TEXT NOT NULL DEFAULT '',
          query TEXT NOT NULL DEFAULT '',
          route_decision JSONB NOT NULL DEFAULT '{}'::jsonb,
          fetch_plan JSONB NOT NULL DEFAULT '{}'::jsonb,
          retrieved_items JSONB NOT NULL DEFAULT '[]'::jsonb,
          filtered_items JSONB NOT NULL DEFAULT '[]'::jsonb,
          final_evidence_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
          latency JSONB NOT NULL DEFAULT '{}'::jsonb,
          answer_cache JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS suggestion_emissions (
          id UUID PRIMARY KEY,
          suggestion_key TEXT NOT NULL UNIQUE,
          suggestion_type TEXT NOT NULL DEFAULT '',
          primary_evidence_id UUID,
          primary_evidence_version TEXT NOT NULL DEFAULT '',
          target_user_id TEXT NOT NULL DEFAULT '',
          channel TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'queued',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS identity_profiles (
          id UUID PRIMARY KEY,
          owner_user_id TEXT NOT NULL DEFAULT 'default',
          canonical_name TEXT NOT NULL DEFAULT '',
          display_names TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          identity_type TEXT NOT NULL DEFAULT 'unknown',
          confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
          scope JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS identity_links (
          id UUID PRIMARY KEY,
          identity_id UUID,
          source TEXT NOT NULL DEFAULT '',
          external_id TEXT NOT NULL DEFAULT '',
          display_name TEXT NOT NULL DEFAULT '',
          link_confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
          evidence_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
          status TEXT NOT NULL DEFAULT 'active',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_assertions (
          id UUID PRIMARY KEY,
          assertion_type TEXT NOT NULL DEFAULT 'fact',
          subject TEXT NOT NULL DEFAULT '',
          predicate TEXT NOT NULL DEFAULT '',
          object TEXT NOT NULL DEFAULT '',
          value JSONB NOT NULL DEFAULT '{}'::jsonb,
          confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'active',
          valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
          valid_until TIMESTAMPTZ,
          evidence_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
          supersedes_id UUID,
          scope JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_nodes (
          id UUID PRIMARY KEY,
          node_type TEXT NOT NULL DEFAULT 'unknown',
          canonical_name TEXT NOT NULL DEFAULT '',
          aliases TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          scope JSONB NOT NULL DEFAULT '{}'::jsonb,
          payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_edges (
          id UUID PRIMARY KEY,
          from_node_id UUID,
          to_node_id UUID,
          relation_type TEXT NOT NULL DEFAULT '',
          fact_text TEXT NOT NULL DEFAULT '',
          confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
          valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
          valid_until TIMESTAMPTZ,
          invalidated_by UUID,
          evidence_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
          scope JSONB NOT NULL DEFAULT '{}'::jsonb,
          payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS memory_ingest_events_source_uid_idx
        ON memory_ingest_events(source_event_uid)
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS suggestion_emissions_key_idx
        ON suggestion_emissions(suggestion_key)
        """,
        """
        CREATE INDEX IF NOT EXISTS memory_evidence_source_scope_idx
        ON memory_evidence(source, account_id, conversation_id, source_created_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS memory_assertions_lookup_idx
        ON memory_assertions(subject, predicate, object, status, updated_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS memory_edges_relation_idx
        ON memory_edges(relation_type, valid_until, updated_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS memory_nodes_name_idx
        ON memory_nodes(canonical_name)
        """,
        """
        CREATE INDEX IF NOT EXISTS memory_retrieval_traces_request_idx
        ON memory_retrieval_traces(request_event_id, created_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS identity_links_external_idx
        ON identity_links(source, external_id)
        """,
    ]
