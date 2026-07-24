from __future__ import annotations

import json
import hashlib
import uuid
from typing import Any

from app.web_search.schema import SearchRequest, SearchResponse


def web_search_schema_sql() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS web_search_runs (
          run_id TEXT PRIMARY KEY,
          safe_query TEXT NOT NULL,
          original_query_hash TEXT NOT NULL,
          safe_query_hash TEXT NOT NULL,
          query_sensitivity TEXT NOT NULL,
          mode TEXT NOT NULL,
          status TEXT NOT NULL,
          providers_attempted JSONB NOT NULL DEFAULT '[]'::jsonb,
          redaction_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
          error_summary JSONB NOT NULL DEFAULT '[]'::jsonb,
          latency_ms INTEGER NOT NULL DEFAULT 0,
          cache_hit BOOLEAN NOT NULL DEFAULT FALSE,
          trace_context JSONB NOT NULL DEFAULT '{}'::jsonb,
          routing_trace JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "ALTER TABLE web_search_runs ADD COLUMN IF NOT EXISTS routing_trace JSONB NOT NULL DEFAULT '{}'::jsonb",
        """
        CREATE TABLE IF NOT EXISTS web_search_sources (
          source_id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL REFERENCES web_search_runs(run_id) ON DELETE CASCADE,
          provider TEXT NOT NULL,
          title TEXT NOT NULL,
          url TEXT NOT NULL,
          canonical_url TEXT NOT NULL,
          domain TEXT NOT NULL DEFAULT '',
          published_at TEXT,
          snippet TEXT NOT NULL DEFAULT '',
          content_hash TEXT NOT NULL DEFAULT '',
          relevance_score DOUBLE PRECISION NOT NULL DEFAULT 0,
          trust_tier TEXT NOT NULL DEFAULT 'unknown',
          content_status TEXT NOT NULL DEFAULT 'snippet_only',
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS web_claim_citations (
          id UUID PRIMARY KEY,
          assistant_event_id TEXT NOT NULL,
          conversation_id TEXT NOT NULL DEFAULT '',
          claim_text TEXT NOT NULL,
          source_id TEXT NOT NULL,
          validation_status TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS web_search_runs_created_idx ON web_search_runs(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS web_search_sources_run_idx ON web_search_sources(run_id)",
        "CREATE INDEX IF NOT EXISTS web_claim_citations_event_idx ON web_claim_citations(assistant_event_id, created_at)",
    ]


def persist_search_run(
    conn: Any,
    *,
    request: SearchRequest,
    response: SearchResponse,
    original_query_hash: str,
) -> None:
    conn.execute(
        """
        INSERT INTO web_search_runs
          (run_id, safe_query, original_query_hash, safe_query_hash, query_sensitivity,
           mode, status, providers_attempted, redaction_summary, error_summary,
           latency_ms, cache_hit, trace_context, routing_trace)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb, %s::jsonb)
        ON CONFLICT (run_id) DO NOTHING
        """,
        (
            response.run_id,
            response.query,
            original_query_hash,
            hashlib.sha256(response.query.encode("utf-8")).hexdigest(),
            str(response.redaction_summary.get("sensitivity") or request.query_sensitivity),
            response.mode,
            response.status,
            json.dumps(response.providers_attempted),
            json.dumps(response.redaction_summary),
            json.dumps([error.model_dump(mode="json") for error in response.errors]),
            response.latency_ms,
            response.cache_hit,
            json.dumps(request.trace_context, ensure_ascii=False, default=str),
            json.dumps(response.routing_trace, ensure_ascii=False, default=str),
        ),
    )
    for source in response.sources:
        conn.execute(
            """
            INSERT INTO web_search_sources
              (source_id, run_id, provider, title, url, canonical_url, domain, published_at,
               snippet, content_hash, relevance_score, trust_tier, content_status, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (source_id) DO UPDATE SET
              run_id = EXCLUDED.run_id,
              snippet = EXCLUDED.snippet,
              relevance_score = EXCLUDED.relevance_score,
              metadata = EXCLUDED.metadata
            """,
            (
                source.source_id,
                response.run_id,
                source.provider,
                source.title,
                source.url,
                source.canonical_url,
                source.domain,
                source.published_at,
                source.snippet,
                source.content_hash,
                source.relevance_score,
                source.trust_tier,
                source.content_status,
                json.dumps(source.metadata, ensure_ascii=False, default=str),
            ),
        )


def persist_claim_citations(
    conn: Any,
    *,
    assistant_event_id: str,
    conversation_id: str,
    report: dict[str, Any],
) -> None:
    for binding in report.get("bindings") or []:
        if not isinstance(binding, dict):
            continue
        claim = str(binding.get("claim") or "").strip()
        source_id = str(binding.get("source_id") or "").strip()
        if not claim or not source_id:
            continue
        conn.execute(
            """
            INSERT INTO web_claim_citations
              (id, assistant_event_id, conversation_id, claim_text, source_id, validation_status)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                uuid.uuid4(),
                assistant_event_id,
                conversation_id,
                claim,
                source_id,
                str(binding.get("validation_status") or "marker_bound"),
            ),
        )
