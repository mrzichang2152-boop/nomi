#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import websocket


def api(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    base_url = os.getenv("REGRESSION_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
    password = os.environ["APP_PASSWORD"]
    timeout = float(os.getenv("REGRESSION_HTTP_TIMEOUT_SECONDS", "90"))
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers={"content-type": "application/json", "x-par-password": password},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode()
            return {"ok": 200 <= response.status < 300, "status": response.status, "json": json.loads(raw) if raw else {}}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw[:1000]
        return {"ok": False, "status": exc.code, "json": parsed}
    except Exception as exc:  # noqa: BLE001 - regression capture script.
        return {"ok": False, "status": "error", "json": {"error": str(exc)}}


def ws_url() -> str:
    base_url = os.getenv("REGRESSION_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
    password = urllib.parse.quote(os.environ["APP_PASSWORD"])
    if base_url.startswith("https://"):
        base = "wss://" + base_url[len("https://") :]
    elif base_url.startswith("http://"):
        base = "ws://" + base_url[len("http://") :]
    else:
        base = base_url
    return f"{base}/ws?password={password}"


def websocket_stream_check() -> dict[str, Any]:
    message = os.getenv("REGRESSION_WS_MESSAGE", "ping online regression streaming check")
    try:
        ws = websocket.create_connection(ws_url(), timeout=float(os.getenv("REGRESSION_WS_TIMEOUT_SECONDS", "90")))
        ws.send(json.dumps({"type": "chat_message", "message": message, "limit": 8, "client_type": "online_regression"}))
        events: list[dict[str, Any]] = []
        started = time.time()
        while time.time() - started < float(os.getenv("REGRESSION_WS_TIMEOUT_SECONDS", "90")):
            raw = ws.recv()
            event = json.loads(raw)
            events.append(event)
            if event.get("type") in {"chat_done", "error"}:
                break
        ws.close()
    except Exception as exc:  # noqa: BLE001 - regression capture script.
        return {"passed": False, "error": str(exc), "events": []}
    delta_text = "".join(str(event.get("delta") or "") for event in events if event.get("type") == "chat_delta")
    done = next((event for event in events if event.get("type") == "chat_done"), None)
    error = next((event for event in events if event.get("type") == "error"), None)
    answer = str((done or {}).get("answer") or delta_text).strip()
    return {
        "passed": bool(done and answer and not error),
        "event_types": [event.get("type") for event in events],
        "answer_preview": answer[:240],
        "conversation_id": (done or {}).get("conversation_id"),
        "error": error,
    }


def collector_capability_check() -> dict[str, Any]:
    response = api("GET", "/api/collectors/status")
    collectors = (response.get("json") or {}).get("collectors") if isinstance(response.get("json"), dict) else []
    by_source = {item.get("source"): item for item in collectors or []}
    gmail = (by_source.get("gmail") or {}).get("capability") or {}
    whatsapp = (by_source.get("whatsapp") or {}).get("capability") or {}
    telegram = (by_source.get("telegram") or {}).get("capability") or {}
    passed = (
        response.get("ok")
        and gmail.get("mode") == "api_or_browser"
        and "composio:gmail" in (gmail.get("adapters") or [])
        and whatsapp.get("mode") == "managed_browser_visible_dom"
        and whatsapp.get("full_history_guarantee") is False
        and telegram.get("mode") == "managed_browser_visible_dom"
        and telegram.get("full_history_guarantee") is False
    )
    return {
        "passed": bool(passed),
        "http_status": response.get("status"),
        "gmail": gmail,
        "whatsapp": whatsapp,
        "telegram": telegram,
    }


def gmail_composio_fetch_check() -> dict[str, Any]:
    if os.getenv("REGRESSION_RUN_GMAIL_COMPOSIO_FETCH", "").lower() not in {"1", "true", "yes"}:
        return {
            "passed": None,
            "skipped": True,
            "reason": "Set REGRESSION_RUN_GMAIL_COMPOSIO_FETCH=1 after confirming Gmail is connected in Composio.",
        }
    response = api(
        "POST",
        "/api/collectors/gmail/composio/fetch",
        {
            "query": os.getenv("REGRESSION_GMAIL_QUERY", "newer_than:1d"),
            "limit": int(os.getenv("REGRESSION_GMAIL_LIMIT", "5")),
        },
    )
    payload = response.get("json") if isinstance(response.get("json"), dict) else {}
    passed = (
        response.get("ok")
        and payload.get("source") == "gmail"
        and payload.get("adapter") == "composio:gmail"
        and isinstance(payload.get("fetched_count"), int)
        and isinstance(payload.get("persisted_count"), int)
        and payload.get("persisted_count") == payload.get("fetched_count")
    )
    return {
        "passed": bool(passed),
        "http_status": response.get("status"),
        "payload": payload,
    }


def pipeline_smoke_check() -> dict[str, Any]:
    route = api("POST", "/api/tools/route", {"request": "帮我查一下去武康路要多久。", "context": {}})
    pipeline = api("POST", "/api/pipelines/run", {"request": "帮我查一下去武康路要多久。", "context": {}})
    route_payload = route.get("json") if isinstance(route.get("json"), dict) else {}
    pipeline_payload = pipeline.get("json") if isinstance(pipeline.get("json"), dict) else {}
    passed = (
        route.get("ok")
        and pipeline.get("ok")
        and (route_payload.get("route_type") == "core_pipeline")
        and ((route_payload.get("pipeline") or {}).get("id") == "route_pipeline")
        and pipeline_payload.get("pipeline_id") == "route_pipeline"
        and pipeline_payload.get("status") in {"ready", "completed", "completed_read_only", "needs_user_input"}
    )
    return {
        "passed": bool(passed),
        "route": {
            "http_status": route.get("status"),
            "route_type": route_payload.get("route_type"),
            "pipeline_id": (route_payload.get("pipeline") or {}).get("id"),
        },
        "pipeline": {
            "http_status": pipeline.get("status"),
            "pipeline_id": pipeline_payload.get("pipeline_id"),
            "status": pipeline_payload.get("status"),
            "resolved_slots": pipeline_payload.get("resolved_slots"),
            "missing_slots": pipeline_payload.get("missing_slots"),
        },
    }


def main() -> int:
    checks = {
        "collector_capability": collector_capability_check(),
        "websocket_streaming_chat": websocket_stream_check(),
        "pipeline_smoke": pipeline_smoke_check(),
        "gmail_composio_fetch": gmail_composio_fetch_check(),
    }
    hard_failures = [
        name
        for name, result in checks.items()
        if result.get("passed") is False and not result.get("skipped")
    ]
    output = {
        "base_url": os.getenv("REGRESSION_BASE_URL", "http://127.0.0.1:8080"),
        "checks": checks,
        "hard_failures": hard_failures,
        "passed": not hard_failures,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 1 if hard_failures else 0


if __name__ == "__main__":
    sys.exit(main())
