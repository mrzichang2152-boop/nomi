from __future__ import annotations


def delegated_automation_schema_sql() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS delegated_automation_grants (
          grant_id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL DEFAULT 'local_user',
          scenario TEXT NOT NULL,
          platform TEXT NOT NULL,
          surface TEXT NOT NULL,
          action TEXT NOT NULL,
          automation_level TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          daily_limit INTEGER NOT NULL DEFAULT 0,
          batch_limit INTEGER NOT NULL DEFAULT 0,
          cooldown_minutes INTEGER NOT NULL DEFAULT 0,
          valid_until TIMESTAMPTZ,
          requires_target_manifest BOOLEAN NOT NULL DEFAULT TRUE,
          requires_grounded_content BOOLEAN NOT NULL DEFAULT TRUE,
          requires_audit_log BOOLEAN NOT NULL DEFAULT TRUE,
          stop_on_challenge BOOLEAN NOT NULL DEFAULT TRUE,
          stop_on_user_pause BOOLEAN NOT NULL DEFAULT TRUE,
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS delegated_automation_manifests (
          manifest_id TEXT PRIMARY KEY,
          scenario TEXT NOT NULL,
          platform TEXT NOT NULL,
          action TEXT NOT NULL,
          targets JSONB NOT NULL DEFAULT '[]'::jsonb,
          max_actions INTEGER NOT NULL DEFAULT 0,
          created_from_evidence_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS delegated_automation_traces (
          trace_id TEXT PRIMARY KEY,
          grant_id TEXT NOT NULL,
          manifest_id TEXT NOT NULL DEFAULT '',
          target_id TEXT NOT NULL DEFAULT '',
          action TEXT NOT NULL,
          status TEXT NOT NULL,
          started_at TIMESTAMPTZ NOT NULL,
          finished_at TIMESTAMPTZ NOT NULL,
          result_summary TEXT NOT NULL DEFAULT '',
          evidence_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          budget_after JSONB NOT NULL DEFAULT '{}'::jsonb,
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS delegated_automation_grants_scope_idx
        ON delegated_automation_grants(scenario, platform, action, status)
        """,
        """
        CREATE INDEX IF NOT EXISTS delegated_automation_traces_grant_idx
        ON delegated_automation_traces(grant_id, started_at DESC)
        """,
    ]
