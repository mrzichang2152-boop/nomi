#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

import psycopg


EVENT_CASES = {
    "RG-WA-001": "bfb3dc1d-11f5-4b1b-8aaa-3640c3b44f74",
    "RG-WA-002": "b14427f6-38ff-4063-9ec0-fc0d50604af8",
    "RG-WA-003": "6ea3984e-888f-41dd-90fa-d1b981c54d70",
    "RG-WA-004": "c0c9ee65-9cb6-4b8e-a2c0-cbbd5154ce96",
    "RG-WA-005A": "ac19363b-44d2-4762-8b83-48d28a877a92",
    "RG-WA-005B": "68d1964c-7f35-48cc-b3bc-0613aabc6a09",
    "RG-GM-001": "9c16ead6-df13-4584-84eb-f3c3b89dc195",
    "RG-GM-002": "e6adbb95-1147-4c16-83b2-fa369dcd2661",
    "RG-GM-003": "6c770a12-d99b-4aef-8093-a7db8c86911c",
}

SEARCH_QUERIES = {
    "RG-WA-001": "RG_Alice PHONE_1 武康路",
    "RG-GM-001": "PHONE_1 quote Friday 18:00 margin",
    "RG-GM-002": "INV-RG-1001 1200 USD next Tuesday",
}


def as_json(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, list):
        return [as_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): as_json(item) for key, item in value.items()}
    return value


def compact_event(row: Any) -> dict[str, Any]:
    raw = row[4] or {}
    return {
        "event_id": str(row[0]),
        "source": row[1],
        "event_type": row[2],
        "timestamp": as_json(row[3]),
        "raw_text": raw.get("text") or raw.get("body") or raw.get("subject"),
        "raw_data": raw,
        "intent": row[5],
        "summary": row[6],
        "entities": row[7],
        "importance": float(row[8]) if row[8] is not None else None,
    }


def get_json(url: str, *, password: str | None = None, body: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    headers = {"content-type": "application/json"}
    if password:
        headers["x-par-password"] = password
    request = urllib.request.Request(url, data=payload, headers=headers, method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return {"status": response.status, "json": json.loads(response.read().decode())}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw[:500]
        return {"status": exc.code, "json": parsed}
    except Exception as exc:  # noqa: BLE001 - this is an inspection script.
        return {"status": "error", "error": str(exc)}


def main() -> None:
    event_ids = list(EVENT_CASES.values())
    password = os.getenv("APP_PASSWORD")
    base_url = os.getenv("REGRESSION_BASE_URL", "http://127.0.0.1:8080")

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute(
            """
            SELECT e.event_id, e.source, e.event_type, e.timestamp, e.raw_data,
                   s.intent, s.summary, s.entities, s.importance
            FROM events e
            LEFT JOIN semantic_events s ON s.event_id = e.event_id
            WHERE e.event_id = ANY(%s::uuid[])
            ORDER BY e.timestamp
            """,
            (event_ids,),
        ).fetchall()
        by_id = {str(row[0]): compact_event(row) for row in rows}

        vector_counts = {
            str(row[0]): int(row[1])
            for row in conn.execute(
                """
                SELECT event_id, COUNT(*)
                FROM memory_vectors
                WHERE event_id = ANY(%s::uuid[])
                GROUP BY event_id
                """,
                (event_ids,),
            ).fetchall()
        }

        agenda_rows = conn.execute(
            """
            SELECT id, type, title, status, certainty, time_window, place,
                   participants, missing_fields, needs_clarification, confidence,
                   source_event_ids, metadata, updated_at
            FROM agenda_items
            WHERE source_event_ids && %s::uuid[]
            ORDER BY updated_at DESC
            """,
            (event_ids,),
        ).fetchall()

        version_rows = conn.execute(
            """
            SELECT agenda_item_id, operation, previous_value, new_value, reason,
                   source_event_ids, confidence, created_at
            FROM agenda_item_versions
            WHERE source_event_ids && %s::uuid[]
            ORDER BY created_at DESC
            """,
            (event_ids,),
        ).fetchall()

        suggestion_rows = conn.execute(
            """
            SELECT id, source_event_id, title, body, priority, status, metadata, created_at
            FROM proactive_suggestions
            WHERE source_event_id = ANY(%s::uuid[])
            ORDER BY created_at DESC
            """,
            (event_ids,),
        ).fetchall()

        route_rows = conn.execute(
            """
            SELECT id, request, route_type, capability_id, pipeline_id,
                   risk_permission, confirmation_required, task_route_decision,
                   source_event_ids, conversation_id, suggestion_id, agenda_item_ids, created_at
            FROM task_route_traces
            WHERE source_event_ids && %s::text[]
            ORDER BY created_at DESC
            """,
            (event_ids,),
        ).fetchall()

        pipeline_rows = conn.execute(
            """
            SELECT id, request, route_type, capability_id, pipeline_id, status,
                   resolved_slots, missing_slots, risk, execution_guard,
                   source_event_ids, conversation_id, suggestion_id, agenda_item_ids, result, created_at
            FROM pipeline_execution_results
            WHERE source_event_ids && %s::text[]
            ORDER BY created_at DESC
            """,
            (event_ids,),
        ).fetchall()

    cases = {}
    for case_id, event_id in EVENT_CASES.items():
        trace = get_json(f"{base_url}/api/events/{event_id}/trace", password=password)
        trace_json = trace.get("json") if isinstance(trace.get("json"), dict) else {}
        cases[case_id] = {
            "event": by_id.get(event_id),
            "vector_count": vector_counts.get(event_id, 0),
            "trace_status": trace.get("status"),
            "trace_counts": {
                "memory_vectors": len(trace_json.get("memory_vectors") or []),
                "facts": len(trace_json.get("facts") or []),
                "agenda_items": len(trace_json.get("agenda_items") or []),
                "agenda_versions": len(trace_json.get("agenda_versions") or []),
                "suggestions": len(trace_json.get("suggestions") or []),
                "route_traces": len(trace_json.get("route_traces") or []),
                "pipeline_executions": len(trace_json.get("pipeline_executions") or []),
            },
        }

    searches = {}
    for case_id, query in SEARCH_QUERIES.items():
        result = get_json(f"{base_url}/search", body={"query": query, "limit": 5})
        payload = result.get("json") if isinstance(result.get("json"), dict) else {}
        searches[case_id] = {
            "status": result.get("status"),
            "query": query,
            "answer": payload.get("answer"),
            "top_sources": [
                {
                    "rank": source.get("rank"),
                    "layer": source.get("layer"),
                    "title": source.get("title"),
                    "snippet": source.get("snippet"),
                    "source_event_ids": source.get("source_event_ids"),
                }
                for source in (payload.get("sources") or [])[:3]
            ],
        }

    out = {
        "event_case_ids": EVENT_CASES,
        "cases": cases,
        "agendas": [
            {
                "id": str(row[0]),
                "type": row[1],
                "title": row[2],
                "status": row[3],
                "certainty": row[4],
                "time_window": as_json(row[5]),
                "place": row[6],
                "participants": row[7],
                "missing_fields": row[8],
                "needs_clarification": row[9],
                "confidence": row[10],
                "source_event_ids": [str(item) for item in row[11]],
                "metadata": row[12],
                "updated_at": as_json(row[13]),
            }
            for row in agenda_rows
        ],
        "agenda_versions": [
            {
                "agenda_item_id": str(row[0]),
                "operation": row[1],
                "previous_value": row[2],
                "new_value": row[3],
                "reason": row[4],
                "source_event_ids": [str(item) for item in row[5]],
                "confidence": row[6],
                "created_at": as_json(row[7]),
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
                "created_at": as_json(row[7]),
            }
            for row in suggestion_rows
        ],
        "route_traces": [
            {
                "id": str(row[0]),
                "request": row[1],
                "route_type": row[2],
                "capability_id": row[3],
                "pipeline_id": row[4],
                "risk_permission": row[5],
                "confirmation_required": row[6],
                "decision": row[7],
                "source_event_ids": [str(item) for item in row[8]],
                "conversation_id": row[9],
                "suggestion_id": row[10],
                "agenda_item_ids": [str(item) for item in row[11]],
                "created_at": as_json(row[12]),
            }
            for row in route_rows
        ],
        "pipeline_executions": [
            {
                "id": str(row[0]),
                "request": row[1],
                "route_type": row[2],
                "capability_id": row[3],
                "pipeline_id": row[4],
                "status": row[5],
                "resolved_slots": row[6],
                "missing_slots": row[7],
                "risk": row[8],
                "execution_guard": row[9],
                "source_event_ids": [str(item) for item in row[10]],
                "conversation_id": row[11],
                "suggestion_id": row[12],
                "agenda_item_ids": [str(item) for item in row[13]],
                "result": row[14],
                "created_at": as_json(row[15]),
            }
            for row in pipeline_rows
        ],
        "searches": searches,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
