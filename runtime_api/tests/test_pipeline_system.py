import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_event_ingestion_normalizes_canonical_event_and_downstream_jobs():
    from app.pipelines.system import run_system_pipeline

    result = run_system_pipeline(
        "event_ingestion_pipeline",
        "New WhatsApp message from Alice",
        {
            "source": " WhatsApp ",
            "event_type": " MESSAGE ",
            "timestamp": "2026-05-28T09:15:00+08:00",
            "raw_event": {"text": "Dinner at 7?"},
            "source_scope": {"kind": "contact", "id": "alice"},
        },
    )

    assert result["pipeline_id"] == "event_ingestion_pipeline"
    assert result["status"] == "completed_read_only"
    assert result["missing_slots"] == []
    assert result["risk"]["confirmation_required"] is False
    assert result["external_effects"] == []
    assert result["provider_calls"] == []

    canonical_event = result["output"]["canonical_event"]
    assert canonical_event["source"] == "whatsapp"
    assert canonical_event["event_type"] == "message"
    assert canonical_event["timestamp"] == "2026-05-28T09:15:00+08:00"
    assert canonical_event["source_scope"] == {"kind": "contact", "id": "alice"}
    assert canonical_event["raw_event"] == {"text": "Dinner at 7?"}
    assert canonical_event["dedupe_key"].startswith("event:whatsapp:message:")

    downstream = result["output"]["downstream_jobs"]
    assert [job["pipeline_id"] for job in downstream] == [
        "memory_write_pipeline",
        "proactive_suggestion_pipeline",
    ]
    assert downstream[0]["context"]["event_id"] == canonical_event["event_id"]
    assert any(plan["target"] == "events" for plan in result["writeback_plan"])


def test_event_ingestion_skips_duplicate_without_downstream_jobs():
    from app.pipelines.system import run_system_pipeline

    context = {
        "source": "gmail",
        "event_type": "email",
        "timestamp": "2026-05-28T09:15:00+08:00",
        "raw_event": {"message_id": "msg-1", "subject": "Status"},
        "event_exists": True,
    }

    first = run_system_pipeline("event_ingestion_pipeline", "Status mail", context)
    second = run_system_pipeline("event_ingestion_pipeline", "Status mail", dict(context))

    assert first["status"] == "completed_read_only"
    assert first["output"]["canonical_event"]["dedupe_key"] == second["output"]["canonical_event"]["dedupe_key"]
    assert first["output"]["downstream_jobs"] == []
    assert {plan["target"]: plan for plan in first["writeback_plan"]}["duplicate_skip"]["operation"] == "record"
    assert {plan["target"]: plan for plan in first["writeback_plan"]}["collector_health"]["payload"]["status"] == "skipped_duplicate"


def test_event_ingestion_schema_errors_quarantine_and_block_jobs():
    from app.pipelines.system import run_system_pipeline

    result = run_system_pipeline(
        "event_ingestion_pipeline",
        "Malformed collector payload",
        {
            "source": "calendar",
            "event_type": "invite",
            "timestamp": "2026-05-28T09:15:00+08:00",
            "raw_event": {"title": ""},
            "schema_errors": ["missing attendee", "empty title"],
        },
    )

    assert result["status"] == "blocked"
    assert result["output"]["downstream_jobs"] == []
    assert result["output"]["quarantine_record"]["schema_errors"] == ["missing attendee", "empty title"]
    plans = {plan["target"]: plan for plan in result["writeback_plan"]}
    assert plans["event_quarantine"]["operation"] == "insert"
    assert plans["collector_health"]["payload"]["status"] == "rejected_schema"


def test_event_ingestion_missing_required_slots_needs_user_input():
    from app.pipelines.system import run_system_pipeline

    result = run_system_pipeline(
        "event_ingestion_pipeline",
        "Incomplete collector payload",
        {"source": "gmail"},
    )

    assert result["status"] == "needs_user_input"
    assert result["resolved_slots"] == {"source": "gmail"}
    assert result["missing_slots"] == ["event_type", "timestamp"]
    assert result["output"]["summary"].startswith("Missing required event fields")
    assert result["writeback_plan"] == []


def test_memory_write_returns_layer_plans_and_queues_vector_retry_without_embedding():
    from app.pipelines.system import run_system_pipeline

    result = run_system_pipeline(
        "memory_write_pipeline",
        "Remember Alice likes quiet restaurants",
        {
            "event_id": "evt-123",
            "source_scope": {"kind": "contact", "id": "alice"},
            "event_text": "Alice likes quiet restaurants.",
            "semantic_labels": ["preference", "restaurant"],
            "embedding_available": False,
        },
    )

    assert result["pipeline_id"] == "memory_write_pipeline"
    assert result["status"] == "completed_read_only"
    assert result["missing_slots"] == []
    assert result["writeback_targets"] == [
        "memory_items",
        "facts",
        "knowledge_entities",
        "knowledge_edges",
        "memory_vectors",
        "memory_audit_log",
    ]

    layers = result["output"]["memory_layers"]
    assert result["output"]["layer_statuses"] == {
        "kv": "planned",
        "graph": "planned",
        "rag": "planned",
        "vector": "queued_for_retry",
    }
    assert layers["kv"]["status"] == "planned"
    assert layers["kv"]["fact"]["source_event_id"] == "evt-123"
    assert layers["graph"]["status"] == "planned"
    assert layers["rag"]["chunk"]["text"] == "Alice likes quiet restaurants."
    assert layers["vector"]["status"] == "queued_for_retry"
    assert layers["vector"]["retry_reason"] == "embedding_unavailable"
    assert result["output"]["retry_plan"] == {
        "reason": "embedding_unavailable",
        "next_attempt_policy": "retry_when_embedding_available",
        "source_event_id": "evt-123",
        "chunk_id": layers["vector"]["chunk_id"],
    }
    plans = {plan["target"]: plan for plan in result["writeback_plan"]}
    assert plans["memory_vectors"]["operation"] == "upsert_or_retry"
    assert plans["memory_audit_log"]["payload"]["status"] == "retry"


def test_memory_write_marks_vector_audit_ok_when_embedding_available():
    from app.pipelines.system import run_system_pipeline

    result = run_system_pipeline(
        "memory_write_pipeline",
        "Remember Alice likes tea",
        {
            "event_id": "evt-456",
            "source_scope": {"kind": "contact", "id": "alice"},
            "event_text": "Alice likes tea.",
            "embedding_available": True,
        },
    )

    assert result["output"]["layer_statuses"]["vector"] == "planned"
    assert "retry_plan" not in result["output"]
    plans = {plan["target"]: plan for plan in result["writeback_plan"]}
    assert plans["memory_vectors"]["operation"] == "upsert_or_retry"
    assert plans["memory_audit_log"]["payload"]["status"] == "ok"


def test_context_pack_filters_evidence_by_scope_and_reports_exclusions():
    from app.pipelines.system import run_system_pipeline

    result = run_system_pipeline(
        "context_pack_pipeline",
        "Build context for Alice chat",
        {
            "request_or_event_id": "req-9",
            "current_scope": {"kind": "contact", "id": "alice"},
            "evidence_items": [
                {"id": "evt-alice", "type": "event", "scope": {"kind": "contact", "id": "alice"}},
                {"id": "mem-global", "type": "memory", "scope": "global"},
                {"id": "mem-user", "type": "memory", "scope": {"kind": "user", "id": "wrf"}},
                {"id": "evt-bob", "type": "event", "scope": {"kind": "contact", "id": "bob"}},
                {"id": "mem-hidden", "type": "memory", "scope": {"kind": "conversation", "id": "other-chat"}},
            ],
            "active_agenda": [
                {"id": "agenda-alice", "scope": {"kind": "contact", "id": "alice"}},
                {"id": "agenda-bob", "scope": {"kind": "contact", "id": "bob"}},
            ],
            "recent_turns": [{"id": "turn-1", "text": "Alice asked about dinner."}],
        },
    )

    assert result["status"] == "completed_read_only"
    assert result["output"]["included_event_ids"] == ["evt-alice"]
    assert result["output"]["included_memory_ids"] == ["mem-global", "mem-user"]
    assert result["output"]["included_agenda_ids"] == ["agenda-alice"]
    assert result["output"]["recent_turn_ids"] == ["turn-1"]

    exclusions = {item["id"]: item["reason"] for item in result["output"]["excluded_evidence"]}
    assert exclusions == {
        "evt-bob": "scope_mismatch",
        "mem-hidden": "scope_mismatch",
        "agenda-bob": "scope_mismatch",
    }
    assert result["output"]["exclusion_metrics"] == {"scope_mismatch": 3}
    assert result["output"]["scope_boundary"] == {
        "current_scope": {"kind": "contact", "id": "alice"},
        "allowed_scope_kinds": ["global", "user", "contact"],
        "excluded_scope_kinds": ["conversation", "contact"],
    }


def test_context_pack_ranks_included_evidence_by_score_then_recency():
    from app.pipelines.system import run_system_pipeline

    result = run_system_pipeline(
        "context_pack_pipeline",
        "Build ranked context",
        {
            "request_or_event_id": "req-rank",
            "current_scope": {"kind": "contact", "id": "alice"},
            "evidence_items": [
                {
                    "id": "old-high",
                    "type": "memory",
                    "scope": {"kind": "contact", "id": "alice"},
                    "score": 0.9,
                    "timestamp": "2026-05-20T10:00:00+08:00",
                },
                {
                    "id": "new-high",
                    "type": "event",
                    "scope": {"kind": "contact", "id": "alice"},
                    "score": 0.9,
                    "timestamp": "2026-05-28T10:00:00+08:00",
                },
                {
                    "id": "mid",
                    "type": "memory",
                    "scope": {"kind": "contact", "id": "alice"},
                    "score": 0.4,
                    "timestamp": "2026-05-29T10:00:00+08:00",
                },
            ],
        },
    )

    assert [item["id"] for item in result["output"]["included_evidence"]] == ["new-high", "old-high", "mid"]
    assert result["output"]["included_event_ids"] == ["new-high"]
    assert result["output"]["included_memory_ids"] == ["old-high", "mid"]


def test_unknown_pipeline_id_returns_none():
    from app.pipelines.system import run_system_pipeline

    assert run_system_pipeline("route_pipeline", "Where to?", {}) is None
