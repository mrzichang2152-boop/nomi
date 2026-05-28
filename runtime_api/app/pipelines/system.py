from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any


PIPELINES = {
    "event_ingestion_pipeline": {
        "required_slots": ["source", "event_type", "timestamp"],
        "writeback_targets": ["events", "collector_health", "task_trace"],
        "steps": ["normalize", "dedupe", "append_event_ledger", "emit_processing_jobs"],
    },
    "memory_write_pipeline": {
        "required_slots": ["event_id", "source_scope"],
        "writeback_targets": [
            "memory_items",
            "facts",
            "knowledge_entities",
            "knowledge_edges",
            "memory_vectors",
            "memory_audit_log",
        ],
        "steps": ["classify_scope", "write_kv", "write_graph", "write_rag_chunk", "index_embedding"],
    },
    "context_pack_pipeline": {
        "required_slots": ["request_or_event_id"],
        "writeback_targets": ["context_snapshots"],
        "steps": ["retrieve_scoped_memory", "retrieve_active_agenda", "retrieve_recent_turns", "assemble_context_pack"],
    },
}


def run_system_pipeline(pipeline_id: str, request: str, context: dict[str, Any]) -> dict[str, Any] | None:
    context = context or {}
    if pipeline_id == "event_ingestion_pipeline":
        return _run_event_ingestion(request, context)
    if pipeline_id == "memory_write_pipeline":
        return _run_memory_write(request, context)
    if pipeline_id == "context_pack_pipeline":
        return _run_context_pack(request, context)
    return None


def _base_result(
    *,
    pipeline_id: str,
    request: str,
    resolved_slots: dict[str, Any],
    output: dict[str, Any],
    writeback_plan: list[dict[str, Any]],
    status_override: str | None = None,
) -> dict[str, Any]:
    pipeline = PIPELINES[pipeline_id]
    required_slots = list(pipeline["required_slots"])
    missing_slots = [slot for slot in required_slots if _is_missing(resolved_slots.get(slot))]
    status = "needs_user_input" if missing_slots else status_override or "completed_read_only"
    return {
        "pipeline_id": pipeline_id,
        "status": status,
        "required_slots": required_slots,
        "resolved_slots": resolved_slots,
        "missing_slots": missing_slots,
        "risk": {
            "permission": "read_only",
            "confirmation_required": False,
            "final_user_confirmation": False,
        },
        "execution_guard": {
            "permission": "read_only",
            "policy": "allowed_after_login",
            "requires_confirmation": False,
            "final_user_confirmation": False,
        },
        "external_effects": [],
        "writeback_targets": list(pipeline["writeback_targets"]),
        "steps": _steps(pipeline_id, status),
        "output": output,
        "provider_calls": [],
        "writeback_plan": [] if missing_slots else writeback_plan,
    }


def _run_event_ingestion(request: str, context: dict[str, Any]) -> dict[str, Any]:
    source = _normalize_token(_context_value(context, "source"))
    event_type = _normalize_token(_context_value(context, "event_type"))
    timestamp = _normalize_timestamp(_context_value(context, "timestamp"))
    resolved_slots = _drop_missing(
        {
            "source": source,
            "event_type": event_type,
            "timestamp": timestamp,
        }
    )

    missing_slots = [slot for slot in PIPELINES["event_ingestion_pipeline"]["required_slots"] if _is_missing(resolved_slots.get(slot))]
    if missing_slots:
        return _base_result(
            pipeline_id="event_ingestion_pipeline",
            request=request,
            resolved_slots=resolved_slots,
            output={"summary": f"Missing required event fields: {', '.join(missing_slots)}."},
            writeback_plan=[],
        )

    source_scope = context.get("source_scope") or context.get("active_source_scope") or {}
    raw_event = context.get("raw_event") or context.get("event") or {}
    dedupe_key = str(context.get("dedupe_key") or _stable_dedupe_key(source, event_type, timestamp, raw_event, request))
    event_id = str(context.get("event_id") or _stable_event_id(source, event_type, timestamp, raw_event, request))
    canonical_event = {
        "event_id": event_id,
        "dedupe_key": dedupe_key,
        "source": source,
        "event_type": event_type,
        "timestamp": timestamp,
        "source_scope": source_scope,
        "raw_event": raw_event,
        "summary": request,
    }

    schema_errors = list(context.get("schema_errors") or [])
    if schema_errors:
        quarantine_record = {
            "event_id": event_id,
            "dedupe_key": dedupe_key,
            "source": source,
            "event_type": event_type,
            "timestamp": timestamp,
            "schema_errors": schema_errors,
            "raw_event": raw_event,
            "summary": request,
        }
        return _base_result(
            pipeline_id="event_ingestion_pipeline",
            request=request,
            resolved_slots=resolved_slots,
            output={
                "summary": "Collector event rejected by schema validation and quarantined.",
                "canonical_event": canonical_event,
                "quarantine_record": quarantine_record,
                "downstream_jobs": [],
            },
            writeback_plan=[
                {"target": "event_quarantine", "operation": "insert", "payload": quarantine_record},
                {
                    "target": "collector_health",
                    "operation": "record_ingestion",
                    "payload": {"source": source, "event_type": event_type, "status": "rejected_schema"},
                },
            ],
            status_override="blocked",
        )

    duplicate_of = context.get("duplicate_of")
    if context.get("event_exists") or duplicate_of:
        duplicate_payload = {
            "event_id": event_id,
            "dedupe_key": dedupe_key,
            "duplicate_of": duplicate_of or event_id,
            "source": source,
            "event_type": event_type,
        }
        return _base_result(
            pipeline_id="event_ingestion_pipeline",
            request=request,
            resolved_slots=resolved_slots,
            output={
                "summary": "Duplicate collector event skipped without downstream jobs.",
                "canonical_event": canonical_event,
                "downstream_jobs": [],
            },
            writeback_plan=[
                {"target": "duplicate_skip", "operation": "record", "payload": duplicate_payload},
                {
                    "target": "collector_health",
                    "operation": "record_ingestion",
                    "payload": {"source": source, "event_type": event_type, "status": "skipped_duplicate"},
                },
            ],
        )

    downstream_jobs = [
        {
            "pipeline_id": "memory_write_pipeline",
            "context": {
                "event_id": event_id,
                "source_scope": source_scope,
                "event_text": _event_text(raw_event, request),
            },
        },
        {
            "pipeline_id": "proactive_suggestion_pipeline",
            "context": {
                "source_event_ids": [event_id],
                "candidate_type": event_type,
                "source_scope": source_scope,
            },
        },
    ]
    return _base_result(
        pipeline_id="event_ingestion_pipeline",
        request=request,
        resolved_slots=resolved_slots,
        output={
            "summary": "Canonical event normalized and downstream processing jobs planned.",
            "canonical_event": canonical_event,
            "downstream_jobs": downstream_jobs,
        },
        writeback_plan=[
            {"target": "events", "operation": "upsert", "payload": canonical_event},
            {
                "target": "collector_health",
                "operation": "record_ingestion",
                "payload": {"source": source, "event_type": event_type, "status": "accepted"},
            },
            {
                "target": "task_trace",
                "operation": "append",
                "payload": {"event_id": event_id, "downstream_jobs": downstream_jobs},
            },
        ],
    )


def _run_memory_write(request: str, context: dict[str, Any]) -> dict[str, Any]:
    resolved_slots = _drop_missing(
        {
            "event_id": _context_value(context, "event_id"),
            "source_scope": _context_value(context, "source_scope"),
        }
    )
    missing_slots = [slot for slot in PIPELINES["memory_write_pipeline"]["required_slots"] if _is_missing(resolved_slots.get(slot))]
    if missing_slots:
        return _base_result(
            pipeline_id="memory_write_pipeline",
            request=request,
            resolved_slots=resolved_slots,
            output={"summary": f"Missing required memory fields: {', '.join(missing_slots)}."},
            writeback_plan=[],
        )

    event_id = str(resolved_slots["event_id"])
    source_scope = resolved_slots["source_scope"]
    event_text = str(context.get("event_text") or context.get("text") or request)
    labels = list(context.get("semantic_labels") or [])
    memory_id = str(context.get("memory_id") or f"mem_{_digest(event_id + event_text)[:12]}")
    chunk_id = f"chunk_{_digest(memory_id + ':rag')[:12]}"
    vector_status = "planned" if context.get("embedding_available", True) is not False else "queued_for_retry"
    layers = {
        "kv": {
            "status": "planned",
            "fact": {
                "id": f"fact_{_digest(memory_id + ':kv')[:12]}",
                "source_event_id": event_id,
                "scope": source_scope,
                "text": event_text,
                "labels": labels,
            },
        },
        "graph": {
            "status": "planned",
            "entities": context.get("entities") or [],
            "edges": context.get("relationships") or [],
            "source_event_id": event_id,
        },
        "rag": {
            "status": "planned",
            "chunk": {
                "id": chunk_id,
                "source_event_id": event_id,
                "scope": source_scope,
                "text": event_text,
                "metadata": {"labels": labels},
            },
        },
        "vector": {
            "status": vector_status,
            "source_event_id": event_id,
            "chunk_id": chunk_id,
        },
    }
    retry_plan = None
    if vector_status == "queued_for_retry":
        layers["vector"]["retry_reason"] = "embedding_unavailable"
        retry_plan = {
            "reason": "embedding_unavailable",
            "next_attempt_policy": "retry_when_embedding_available",
            "source_event_id": event_id,
            "chunk_id": chunk_id,
        }

    layer_statuses = {layer: details["status"] for layer, details in layers.items()}
    output = {
        "summary": "Memory layer writes planned without external effects.",
        "memory_id": memory_id,
        "memory_layers": layers,
        "layer_statuses": layer_statuses,
    }
    if retry_plan:
        output["retry_plan"] = retry_plan

    return _base_result(
        pipeline_id="memory_write_pipeline",
        request=request,
        resolved_slots=resolved_slots,
        output=output,
        writeback_plan=[
            {"target": "memory_items", "operation": "upsert", "payload": {"id": memory_id, "source_event_id": event_id}},
            {"target": "facts", "operation": "upsert", "payload": layers["kv"]["fact"]},
            {"target": "knowledge_entities", "operation": "upsert_many", "payload": layers["graph"]["entities"]},
            {"target": "knowledge_edges", "operation": "upsert_many", "payload": layers["graph"]["edges"]},
            {"target": "memory_vectors", "operation": "upsert_or_retry", "payload": layers["vector"]},
            {
                "target": "memory_audit_log",
                "operation": "append",
                "payload": {
                    "event_id": event_id,
                    "memory_id": memory_id,
                    "vector_status": vector_status,
                    "status": "retry" if vector_status == "queued_for_retry" else "ok",
                },
            },
        ],
    )


def _run_context_pack(request: str, context: dict[str, Any]) -> dict[str, Any]:
    resolved_slots = _drop_missing({"request_or_event_id": _context_value(context, "request_or_event_id")})
    missing_slots = [slot for slot in PIPELINES["context_pack_pipeline"]["required_slots"] if _is_missing(resolved_slots.get(slot))]
    if missing_slots:
        return _base_result(
            pipeline_id="context_pack_pipeline",
            request=request,
            resolved_slots=resolved_slots,
            output={"summary": f"Missing required context field: {', '.join(missing_slots)}."},
            writeback_plan=[],
        )

    current_scope = context.get("current_scope") or context.get("source_scope") or "global"
    included_evidence: list[dict[str, Any]] = []
    excluded_evidence: list[dict[str, Any]] = []
    for item in context.get("evidence_items") or []:
        if _scope_allowed(item.get("scope"), current_scope):
            included_evidence.append(item)
        else:
            excluded_evidence.append(_excluded_evidence(item))

    included_evidence.sort(key=_evidence_rank_key)

    included_agenda: list[dict[str, Any]] = []
    for item in context.get("active_agenda") or []:
        if _scope_allowed(item.get("scope"), current_scope):
            included_agenda.append(item)
        else:
            excluded_evidence.append(_excluded_evidence(item))

    recent_turns = list(context.get("recent_turns") or [])
    included_event_ids = [str(item.get("id")) for item in included_evidence if item.get("type") == "event" and item.get("id")]
    included_memory_ids = [str(item.get("id")) for item in included_evidence if item.get("type") == "memory" and item.get("id")]
    included_agenda_ids = [str(item.get("id")) for item in included_agenda if item.get("id")]
    output = {
        "summary": "Scoped context pack assembled.",
        "request_or_event_id": resolved_slots["request_or_event_id"],
        "current_scope": current_scope,
        "included_event_ids": included_event_ids,
        "included_memory_ids": included_memory_ids,
        "included_agenda_ids": included_agenda_ids,
        "recent_turn_ids": [str(item.get("id")) for item in recent_turns if item.get("id")],
        "included_evidence": included_evidence,
        "included_agenda": included_agenda,
        "recent_turns": recent_turns,
        "excluded_evidence": excluded_evidence,
        "exclusion_metrics": _exclusion_metrics(excluded_evidence),
        "scope_boundary": _scope_boundary(current_scope, excluded_evidence),
    }
    return _base_result(
        pipeline_id="context_pack_pipeline",
        request=request,
        resolved_slots=resolved_slots,
        output=output,
        writeback_plan=[
            {
                "target": "context_snapshots",
                "operation": "insert",
                "payload": {
                    "request_or_event_id": resolved_slots["request_or_event_id"],
                    "current_scope": current_scope,
                    "included_event_ids": included_event_ids,
                    "included_memory_ids": included_memory_ids,
                    "included_agenda_ids": included_agenda_ids,
                    "excluded_evidence": excluded_evidence,
                    "exclusion_metrics": output["exclusion_metrics"],
                    "scope_boundary": output["scope_boundary"],
                },
            }
        ],
    )


def _steps(pipeline_id: str, status: str) -> list[dict[str, str]]:
    step_status = "pending" if status == "needs_user_input" else "completed"
    return [{"name": step, "status": step_status} for step in PIPELINES[pipeline_id]["steps"]]


def _context_value(context: dict[str, Any], key: str) -> Any:
    value = context.get(key)
    if value is None and isinstance(context.get("slots"), dict):
        value = context["slots"].get(key)
    return value


def _drop_missing(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if not _is_missing(value)}


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or value == []


def _normalize_token(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _normalize_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or value == "":
        return ""
    return str(value).strip()


def _stable_event_id(source: str, event_type: str, timestamp: str, raw_event: Any, request: str) -> str:
    payload = f"{source}|{event_type}|{timestamp}|{raw_event!r}|{request}"
    return f"evt_{_digest(payload)[:16]}"


def _stable_dedupe_key(source: str, event_type: str, timestamp: str, raw_event: Any, request: str) -> str:
    payload = f"{source}|{event_type}|{timestamp}|{raw_event!r}|{request}"
    return f"event:{source}:{event_type}:{_digest(payload)[:24]}"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _event_text(raw_event: Any, request: str) -> str:
    if isinstance(raw_event, dict):
        for key in ("text", "body", "subject", "message"):
            if raw_event.get(key):
                return str(raw_event[key])
    return request


def _scope_allowed(item_scope: Any, current_scope: Any) -> bool:
    normalized_item = _normalize_scope(item_scope)
    normalized_current = _normalize_scope(current_scope)
    if normalized_item in {("global", ""), ("user", "")}:
        return True
    if normalized_item[0] == "user":
        return True
    return normalized_item == normalized_current


def _excluded_evidence(item: dict[str, Any]) -> dict[str, Any]:
    scope_kind, scope_id = _normalize_scope(item.get("scope"))
    return {
        "id": item.get("id"),
        "reason": "scope_mismatch",
        "scope": item.get("scope"),
        "scope_kind": scope_kind,
        "scope_id": scope_id,
    }


def _exclusion_metrics(excluded_evidence: list[dict[str, Any]]) -> dict[str, int]:
    metrics: dict[str, int] = {}
    for item in excluded_evidence:
        reason = str(item.get("reason") or "unknown")
        metrics[reason] = metrics.get(reason, 0) + 1
    return metrics


def _scope_boundary(current_scope: Any, excluded_evidence: list[dict[str, Any]]) -> dict[str, Any]:
    current_kind, _ = _normalize_scope(current_scope)
    allowed = ["global", "user"]
    if current_kind not in allowed:
        allowed.append(current_kind)
    excluded_kinds = [str(item.get("scope_kind")) for item in excluded_evidence if item.get("scope_kind")]
    priority = {"conversation": 0, "contact": 1}
    unique_excluded = sorted(set(excluded_kinds), key=lambda kind: (priority.get(kind, 99), kind))
    return {
        "current_scope": current_scope,
        "allowed_scope_kinds": allowed,
        "excluded_scope_kinds": unique_excluded,
    }


def _evidence_rank_key(item: dict[str, Any]) -> tuple[float, float]:
    return (-_score_value(item.get("score")), -_timestamp_value(item.get("timestamp") or item.get("created_at") or item.get("updated_at")))


def _score_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _timestamp_value(value: Any) -> float:
    if not value:
        return 0.0
    if isinstance(value, datetime):
        return value.timestamp()
    try:
        normalized = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return 0.0


def _normalize_scope(scope: Any) -> tuple[str, str]:
    if scope is None:
        return ("global", "")
    if isinstance(scope, str):
        return (scope.strip().lower(), "")
    if isinstance(scope, dict):
        kind = str(scope.get("kind") or scope.get("type") or "").strip().lower()
        scope_id = str(scope.get("id") or scope.get("scope_id") or "").strip()
        if not kind:
            kind = "global"
        return (kind, scope_id)
    return (str(scope).strip().lower(), "")
