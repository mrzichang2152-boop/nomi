#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import urllib.parse
import urllib.error
import urllib.request
from typing import Any

import psycopg
import redis
import websockets


MEETING_EVENT_ID = "6ea3984e-888f-41dd-90fa-d1b981c54d70"


def post_json(url: str, body: dict[str, Any], password: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"content-type": "application/json", "x-par-password": password},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return {"status": response.status, "json": json.loads(response.read().decode())}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw[:500]
        return {"status": exc.code, "json": parsed}


def suggestion_to_realtime_message(suggestion: dict[str, Any]) -> dict[str, Any]:
    metadata = suggestion.get("metadata") if isinstance(suggestion.get("metadata"), dict) else {}
    actions = metadata.get("actions") if isinstance(metadata.get("actions"), list) else []
    return {
        "type": "proactive_message",
        "id": suggestion["id"],
        "suggestion_id": suggestion["id"],
        "source_event_id": suggestion["source_event_id"],
        "title": suggestion["title"],
        "body": suggestion["body"],
        "priority": suggestion["priority"],
        "source": metadata.get("source") or metadata.get("collector") or "unknown",
        "metadata": metadata,
        "actions": actions,
        "open_view": "chat",
    }


def fetch_meeting_suggestion() -> dict[str, Any]:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        row = conn.execute(
            """
            SELECT id, source_event_id, title, body, priority, status, metadata
            FROM proactive_suggestions
            WHERE source_event_id = %s
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """,
            (MEETING_EVENT_ID,),
        ).fetchone()
    if not row:
        raise RuntimeError("meeting suggestion not found")
    return {
        "id": str(row[0]),
        "source_event_id": str(row[1]),
        "title": row[2],
        "body": row[3],
        "priority": row[4],
        "status": row[5],
        "metadata": row[6] or {},
    }


async def websocket_probe(message: dict[str, Any]) -> dict[str, Any]:
    password = os.environ["APP_PASSWORD"]
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    channel = os.getenv("REALTIME_CHANNEL", "par:realtime")
    uri = f"ws://127.0.0.1:8080/ws?password={urllib.parse.quote(password)}"
    async with websockets.connect(uri, open_timeout=10) as ws:
        await ws.send(json.dumps({"type": "ping"}))
        pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        client = redis.Redis.from_url(redis_url, decode_responses=True)
        client.publish(channel, json.dumps(message, ensure_ascii=False))
        pushed = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        return {"pong": pong, "pushed": pushed}


def compact_action_result(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("json") or {}
    if not isinstance(payload, dict):
        return {"status": result.get("status"), "error": str(payload)[:500]}
    route = payload.get("route_result") or {}
    return {
        "status": result.get("status"),
        "suggestion_id": payload.get("suggestion_id"),
        "action_id": payload.get("action_id"),
        "feedback_recorded": payload.get("feedback_recorded"),
        "route_type": route.get("route_type"),
        "pipeline_id": (route.get("pipeline") or {}).get("id"),
        "capability_id": (route.get("capability") or {}).get("id"),
        "risk_permission": (route.get("execution_guard") or {}).get("permission"),
        "requires_confirmation": (route.get("execution_guard") or {}).get("requires_confirmation"),
        "task_trace_id": route.get("task_trace_id"),
        "routing_reason": route.get("routing_reason"),
    }


async def main() -> None:
    suggestion = fetch_meeting_suggestion()
    message = suggestion_to_realtime_message(suggestion)
    websocket_result = await websocket_probe(message)
    password = os.environ["APP_PASSWORD"]
    base_url = os.getenv("REGRESSION_BASE_URL", "http://127.0.0.1:8080")
    route_action = post_json(
        f"{base_url}/api/proactive/suggestions/{suggestion['id']}/action",
        {"action_id": "route_lookup", "reason": "online regression route lookup"},
        password,
    )
    ride_action = post_json(
        f"{base_url}/api/proactive/suggestions/{suggestion['id']}/action",
        {"action_id": "ride_prepare", "reason": "online regression ride prepare"},
        password,
    )
    out = {
        "suggestion": {
            "id": suggestion["id"],
            "source_event_id": suggestion["source_event_id"],
            "title": suggestion["title"],
            "body": suggestion["body"],
            "actions": [item.get("label") for item in (suggestion["metadata"].get("actions") or [])],
        },
        "websocket": {
            "pong": websocket_result["pong"],
            "pushed_type": websocket_result["pushed"].get("type"),
            "pushed_title": websocket_result["pushed"].get("title"),
            "pushed_body": websocket_result["pushed"].get("body"),
            "pushed_actions": [item.get("label") for item in (websocket_result["pushed"].get("actions") or [])],
            "pushed_open_view": websocket_result["pushed"].get("open_view"),
        },
        "route_action": compact_action_result(route_action),
        "ride_action": compact_action_result(ride_action),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
