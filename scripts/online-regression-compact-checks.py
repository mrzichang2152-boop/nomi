#!/usr/bin/env python3
from __future__ import annotations

import json
import os
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


def iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def j(value: Any) -> Any:
    if isinstance(value, list):
        return [j(item) for item in value]
    if isinstance(value, dict):
        return {str(key): j(item) for key, item in value.items()}
    return iso(value)


def post_json(url: str, body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def source_preview(source: dict[str, Any]) -> dict[str, Any]:
    content = source.get("content") or {}
    raw = content.get("raw_data") or {}
    metadata = content.get("metadata") or {}
    return {
        "rank": source.get("rank"),
        "layer": source.get("layer"),
        "summary": content.get("summary") or content.get("object") or content.get("value"),
        "raw_text": raw.get("text") or raw.get("body") or raw.get("subject"),
        "source_event_ids": content.get("source_event_ids")
        or metadata.get("source_event_ids")
        or raw.get("source_event_ids"),
    }


def main() -> None:
    event_ids = list(EVENT_CASES.values())
    base_url = os.getenv("REGRESSION_BASE_URL", "http://127.0.0.1:8080")
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        events = conn.execute(
            """
            SELECT e.event_id, e.raw_data, s.intent, s.summary, s.entities,
                   COUNT(v.id) AS vector_count
            FROM events e
            LEFT JOIN semantic_events s ON s.event_id = e.event_id
            LEFT JOIN memory_vectors v ON v.event_id = e.event_id
            WHERE e.event_id = ANY(%s::uuid[])
            GROUP BY e.event_id, e.raw_data, s.intent, s.summary, s.entities
            """,
            (event_ids,),
        ).fetchall()
        event_by_id = {str(row[0]): row for row in events}

        agendas = conn.execute(
            """
            SELECT id, type, title, status, certainty, time_window, place, participants,
                   missing_fields, needs_clarification, source_event_ids, metadata
            FROM agenda_items
            WHERE source_event_ids && %s::uuid[]
            ORDER BY updated_at DESC
            """,
            (event_ids,),
        ).fetchall()

        versions = conn.execute(
            """
            SELECT agenda_item_id, operation, previous_value, new_value, reason, source_event_ids
            FROM agenda_item_versions
            WHERE source_event_ids && %s::uuid[]
            ORDER BY created_at DESC
            """,
            (event_ids,),
        ).fetchall()

        suggestions = conn.execute(
            """
            SELECT source_event_id, title, body, priority, status, metadata
            FROM proactive_suggestions
            WHERE source_event_id = ANY(%s::uuid[])
            ORDER BY created_at DESC
            """,
            (event_ids,),
        ).fetchall()

        pipeline_rows = conn.execute(
            """
            SELECT p.id, p.task_trace_id, p.request, p.route_type, p.pipeline_id, p.status,
                   p.resolved_slots, p.missing_slots, p.risk, p.source_event_ids,
                   p.result->'output' AS output,
                   t.source_event_ids AS route_source_event_ids,
                   t.request AS route_request
            FROM pipeline_execution_results p
            LEFT JOIN task_route_traces t ON t.id::text = p.task_trace_id
            WHERE p.source_event_ids && %s::text[]
            ORDER BY p.created_at DESC
            """,
            (event_ids,),
        ).fetchall()

    cases: dict[str, Any] = {}
    for case_id, event_id in EVENT_CASES.items():
        row = event_by_id.get(event_id)
        if not row:
            cases[case_id] = {"event_id": event_id, "missing": True}
            continue
        raw = row[1] or {}
        entities = row[4] or {}
        cases[case_id] = {
            "event_id": event_id,
            "raw_text": raw.get("text") or raw.get("body") or raw.get("subject"),
            "intent": row[2],
            "summary": row[3],
            "labels": entities.get("labels"),
            "primary_label": entities.get("primary_label"),
            "vector_count": row[5],
        }

    searches = {}
    for label, query in {
        "alice_meeting": "RG_Alice PHONE_1 武康路",
        "quote_deadline": "PHONE_1 quote Friday 18:00 margin",
        "invoice": "INV-RG-1001 1200 USD next Tuesday",
    }.items():
        result = post_json(f"{base_url}/search", {"query": query, "limit": 5})
        searches[label] = {
            "answer": result.get("answer"),
            "confidence": result.get("confidence"),
            "layers": result.get("layers"),
            "top_sources": [source_preview(item) for item in (result.get("sources") or [])[:3]],
        }

    out = {
        "cases": cases,
        "agendas": [
            {
                "id": str(row[0]),
                "type": row[1],
                "title": row[2],
                "status": row[3],
                "certainty": row[4],
                "time_window": j(row[5]),
                "place": row[6],
                "participants": row[7],
                "missing_fields": row[8],
                "needs_clarification": row[9],
                "source_event_ids": [str(item) for item in row[10]],
                "metadata": row[11],
            }
            for row in agendas
        ],
        "agenda_versions": [
            {
                "agenda_item_id": str(row[0]),
                "operation": row[1],
                "previous_value": row[2],
                "new_value": row[3],
                "reason": row[4],
                "source_event_ids": [str(item) for item in row[5]],
            }
            for row in versions
        ],
        "suggestions": [
            {
                "source_event_id": str(row[0]),
                "title": row[1],
                "body": row[2],
                "priority": row[3],
                "status": row[4],
                "actions": [item.get("label") for item in ((row[5] or {}).get("actions") or [])],
                "type": (row[5] or {}).get("suggestion_type"),
            }
            for row in suggestions
        ],
        "pipeline_executions": [
            {
                "id": str(row[0]),
                "task_trace_id": row[1],
                "request": row[2],
                "route_type": row[3],
                "pipeline_id": row[4],
                "status": row[5],
                "resolved_slots": row[6],
                "missing_slots": row[7],
                "risk": row[8],
                "source_event_ids": [str(item) for item in row[9]],
                "output": row[10],
                "route_source_event_ids": [str(item) for item in (row[11] or [])],
                "route_request": row[12],
            }
            for row in pipeline_rows
        ],
        "searches": searches,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
