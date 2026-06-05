#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from typing import Any

import psycopg


EMPTY = ""


def as_list(value: Any) -> list[str]:
    if not value:
        return []
    return [str(item) for item in value]


def iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def main() -> None:
    patterns = ("%RG_Alice%", "%RG_Bob%", "%INV-RG-1001%", "%RG_Alice%", "%INV-RG-1001%")
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute(
            """
            SELECT e.event_id, e.timestamp, e.source, e.event_type, e.raw_data,
                   s.intent, s.entities, s.importance, s.summary
            FROM events e
            LEFT JOIN semantic_events s ON s.event_id = e.event_id
            WHERE e.raw_data::text ILIKE %s
               OR e.raw_data::text ILIKE %s
               OR e.raw_data::text ILIKE %s
               OR COALESCE(s.summary, %s) ILIKE %s
               OR COALESCE(s.summary, %s) ILIKE %s
            ORDER BY e.timestamp DESC
            LIMIT 80
            """,
            (*patterns[:3], EMPTY, patterns[3], EMPTY, patterns[4]),
        ).fetchall()
        event_ids = [str(row[0]) for row in rows]
        event_id_filter = event_ids or ["00000000-0000-0000-0000-000000000000"]
        agenda_rows = conn.execute(
            """
            SELECT id, type, title, status, certainty, time_window, place, participants,
                   missing_fields, needs_clarification, confidence, source_event_ids, metadata, updated_at
            FROM agenda_items
            WHERE source_event_ids && %s::uuid[]
               OR title ILIKE %s
               OR participants::text ILIKE %s
               OR metadata::text ILIKE %s
            ORDER BY updated_at DESC
            LIMIT 80
            """,
            (event_id_filter, "%RG_%", "%RG_%", "%RG_%"),
        ).fetchall()
        version_rows = conn.execute(
            """
            SELECT agenda_item_id, operation, previous_value, new_value, reason,
                   source_event_ids, confidence, created_at
            FROM agenda_item_versions
            WHERE source_event_ids && %s::uuid[]
            ORDER BY created_at DESC
            LIMIT 80
            """,
            (event_id_filter,),
        ).fetchall()
        suggestion_rows = conn.execute(
            """
            SELECT id, source_event_id, title, body, priority, status, metadata, created_at
            FROM proactive_suggestions
            WHERE source_event_id = ANY(%s::uuid[])
               OR title ILIKE %s
               OR body ILIKE %s
               OR metadata::text ILIKE %s
            ORDER BY created_at DESC
            LIMIT 80
            """,
            (event_id_filter, "%RG_%", "%RG_%", "%RG_%"),
        ).fetchall()
        vector_rows = conn.execute(
            """
            SELECT event_id, source, event_type, content, metadata
            FROM memory_vectors
            WHERE event_id = ANY(%s::uuid[])
            ORDER BY event_id
            """,
            (event_id_filter,),
        ).fetchall()
        route_rows = conn.execute(
            """
            SELECT id, route_type, capability_id, pipeline_id, risk_permission,
                   confirmation_required, task_route_decision,
                   source_event_ids, conversation_id, created_at
            FROM task_route_traces
            WHERE task_route_decision::text ILIKE %s OR source_event_ids && %s::text[]
            ORDER BY created_at DESC
            LIMIT 40
            """,
            ("%RG_Alice%", event_id_filter),
        ).fetchall()
        pipeline_rows = conn.execute(
            """
            SELECT id, pipeline_id, status, resolved_slots, missing_slots, risk,
                   source_event_ids, created_at
            FROM pipeline_execution_results
            WHERE result::text ILIKE %s OR source_event_ids && %s::text[]
            ORDER BY created_at DESC
            LIMIT 60
            """,
            ("%RG_%", event_id_filter),
        ).fetchall()

    out = {
        "events": [
            {
                "event_id": str(row[0]),
                "timestamp": iso(row[1]),
                "source": row[2],
                "event_type": row[3],
                "raw_data": row[4],
                "intent": row[5],
                "entities": row[6],
                "importance": row[7],
                "summary": row[8],
            }
            for row in rows
        ],
        "vectors": [
            {"event_id": str(row[0]), "source": row[1], "event_type": row[2], "content": row[3], "metadata": row[4]}
            for row in vector_rows
        ],
        "agendas": [
            {
                "id": str(row[0]),
                "type": row[1],
                "title": row[2],
                "status": row[3],
                "certainty": row[4],
                "time_window": row[5],
                "place": row[6],
                "participants": row[7],
                "missing_fields": row[8],
                "needs_clarification": row[9],
                "confidence": row[10],
                "source_event_ids": as_list(row[11]),
                "metadata": row[12],
                "updated_at": iso(row[13]),
            }
            for row in agenda_rows
        ],
        "versions": [
            {
                "agenda_item_id": str(row[0]),
                "operation": row[1],
                "previous_value": row[2],
                "new_value": row[3],
                "reason": row[4],
                "source_event_ids": as_list(row[5]),
                "confidence": row[6],
                "created_at": iso(row[7]),
            }
            for row in version_rows
        ],
        "suggestions": [
            {
                "id": str(row[0]),
                "source_event_id": str(row[1]),
                "title": row[2],
                "body": row[3],
                "priority": row[4],
                "status": row[5],
                "metadata": row[6],
                "created_at": iso(row[7]),
            }
            for row in suggestion_rows
        ],
        "route_traces": [
            {
                "id": str(row[0]),
                "route_type": row[1],
                "capability_id": row[2],
                "pipeline_id": row[3],
                "risk_permission": row[4],
                "confirmation_required": row[5],
                "decision": row[6],
                "source_event_ids": as_list(row[7]),
                "conversation_id": str(row[8]) if row[8] else None,
                "created_at": iso(row[9]),
            }
            for row in route_rows
        ],
        "pipeline_executions": [
            {
                "id": str(row[0]),
                "pipeline_id": row[1],
                "status": row[2],
                "resolved_slots": row[3],
                "missing_slots": row[4],
                "risk": row[5],
                "source_event_ids": as_list(row[6]),
                "created_at": iso(row[7]),
            }
            for row in pipeline_rows
        ],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
