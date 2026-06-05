#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


ALICE_EVENT_ID = "6ea3984e-888f-41dd-90fa-d1b981c54d70"
ALICE_REPLY_EVENT_ID = "ac19363b-44d2-4762-8b83-48d28a877a92"
QUOTE_EMAIL_EVENT_ID = "9c16ead6-df13-4584-84eb-f3c3b89dc195"
INVOICE_EVENT_ID = "e6adbb95-1147-4c16-83b2-fa369dcd2661"


def api(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    base_url = os.getenv("REGRESSION_BASE_URL", "http://127.0.0.1:8080")
    password = os.environ["APP_PASSWORD"]
    timeout = float(os.getenv("REGRESSION_HTTP_TIMEOUT_SECONDS", "240"))
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
            return {"status": response.status, "json": json.loads(raw) if raw else {}}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw[:1000]
        return {"status": exc.code, "json": parsed}
    except Exception as exc:  # noqa: BLE001 - regression capture script.
        return {"status": "error", "json": {"error": str(exc)}}


def route(request: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    return api("POST", "/api/tools/route", {"request": request, "context": context or {}})


def run_pipeline(request: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    return api("POST", "/api/pipelines/run", {"request": request, "context": context or {}})


def chat(message: str, **extra: Any) -> dict[str, Any]:
    body = {"message": message, "limit": 12, "client_type": "online_regression"}
    body.update(extra)
    return api("POST", "/api/chat", body)


def compact_route(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("json") if isinstance(result.get("json"), dict) else {}
    pipeline = payload.get("pipeline") or {}
    guard = payload.get("execution_guard") or {}
    packet = payload.get("openclaw_task_packet") or {}
    return {
        "http_status": result.get("status"),
        "route_type": payload.get("route_type"),
        "pipeline_id": pipeline.get("id"),
        "capability_id": (payload.get("capability") or {}).get("id"),
        "risk_permission": guard.get("permission"),
        "requires_confirmation": guard.get("requires_confirmation"),
        "trace_persisted": payload.get("trace_persisted"),
        "trace_persistence_reason": payload.get("trace_persistence_reason"),
        "task_trace_id": payload.get("task_trace_id"),
        "openclaw_packet": {
            "goal": packet.get("goal"),
            "allowed_actions": packet.get("allowed_actions"),
            "forbidden_actions": packet.get("forbidden_actions"),
            "minimal_context_keys": sorted((packet.get("minimal_context") or {}).keys()) if isinstance(packet.get("minimal_context"), dict) else None,
        }
        if packet
        else None,
    }


def compact_pipeline(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("json") if isinstance(result.get("json"), dict) else {}
    return {
        "http_status": result.get("status"),
        "pipeline_id": payload.get("pipeline_id"),
        "route_type": payload.get("route_type"),
        "status": payload.get("status"),
        "resolved_slots": payload.get("resolved_slots"),
        "missing_slots": payload.get("missing_slots"),
        "risk": payload.get("risk"),
        "execution_guard": payload.get("execution_guard"),
        "source_event_ids": payload.get("source_event_ids"),
        "conversation_id": payload.get("conversation_id"),
        "task_trace_id": payload.get("task_trace_id"),
        "pipeline_execution_id": payload.get("pipeline_execution_id"),
        "output": payload.get("output"),
    }


def compact_chat(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("json") if isinstance(result.get("json"), dict) else {}
    context_pack = payload.get("context_pack") or {}
    return {
        "http_status": result.get("status"),
        "answer": payload.get("answer") if result.get("status") == 200 else payload,
        "conversation_id": payload.get("conversation_id"),
        "context_pack_id": context_pack.get("context_pack_id"),
        "included_event_ids": context_pack.get("included_event_ids"),
        "included_agenda_ids": context_pack.get("included_agenda_ids"),
        "assistant_dialogue_count": context_pack.get("assistant_dialogue_count"),
        "scope_filters_applied": context_pack.get("scope_filters_applied"),
        "token_budget": context_pack.get("token_budget"),
    }


def main() -> None:
    results: dict[str, Any] = {}

    results["RG-CHAT-001"] = compact_chat(
        chat(
            "RG_Alice 约我什么时候在哪里见？",
            ui_state={"counterparty_ids": ["rg_alice"], "conversation_label": "RG_Alice"},
        )
    )
    results["RG-CHAT-002"] = compact_chat(
        chat(
            "可以",
            conversation_id="00000000-0000-0000-0000-000000000242",
            client_context_delta=[
                {
                    "role": "assistant",
                    "content": "需要我先帮你核对 PHONE_1 的成本与利润率，然后再起草给 RG_Alice 的回复吗？",
                }
            ],
        )
    )

    reply_context = {
        "source_event_ids": [ALICE_REPLY_EVENT_ID],
        "active_source_scope": {
            "source": "whatsapp",
            "conversation_id": "WX_RG_ALICE_THREAD",
            "counterparty_ids": ["rg_alice"],
        },
    }
    results["RG-CHAT-003"] = {
        "route": compact_route(route("帮我回复 RG_Alice，说我会周五前确认 PHONE_1 报价。", reply_context)),
        "pipeline": compact_pipeline(run_pipeline("帮我回复 RG_Alice，说我会周五前确认 PHONE_1 报价。", reply_context)),
        "chat": compact_chat(chat("帮我回复 RG_Alice，说我会周五前确认 PHONE_1 报价。", ui_state=reply_context)),
    }

    results["RG-CHAT-004"] = {
        "route": compact_route(route("帮我查一下去武康路要多久。")),
        "pipeline": compact_pipeline(run_pipeline("帮我查一下去武康路要多久。")),
    }
    results["RG-CHAT-005"] = {
        "route": compact_route(route("帮我打车去武康路。")),
        "pipeline_missing_pickup": compact_pipeline(run_pipeline("帮我打车去武康路。")),
        "pipeline_with_pickup": compact_pipeline(run_pipeline("帮我打车去武康路。", {"pickup": "当前定位"})),
    }
    results["RG-CHAT-006"] = {
        "ambiguous_route": compact_route(route("帮我付款。")),
        "ambiguous_pipeline": compact_pipeline(run_pipeline("帮我付款。")),
        "invoice_route": compact_route(route("帮我处理 INV-RG-1001", {"source_event_ids": [INVOICE_EVENT_ID]})),
        "invoice_pipeline": compact_pipeline(run_pipeline("帮我处理 INV-RG-1001", {"source_event_ids": [INVOICE_EVENT_ID]})),
    }
    results["RG-CHAT-007"] = {
        "route": compact_route(route("帮我买一个适合 PHONE_1 的保护壳。")),
        "pipeline": compact_pipeline(run_pipeline("帮我买一个适合 PHONE_1 的保护壳。")),
    }
    results["RG-CHAT-008"] = {
        "route": compact_route(route("帮我找一下 PHONE_1 报价单，并总结给我。")),
        "pipeline": compact_pipeline(run_pipeline("帮我找一下 PHONE_1 报价单，并总结给我。")),
        "write_route": compact_route(route("把总结写进表格。")),
        "write_pipeline": compact_pipeline(run_pipeline("把总结写进表格。")),
    }
    results["RG-CHAT-009"] = {
        "private_analysis": compact_chat(chat("RG_Alice 对 PHONE_1 报价有什么偏好吗？")),
        "outbound_draft": compact_pipeline(run_pipeline("帮我回复 RG_Alice，说报价我会尽量清楚说明依据。", reply_context)),
    }

    catalog = api("GET", "/api/tools/catalog")
    catalog_payload = catalog.get("json") if isinstance(catalog.get("json"), dict) else {}
    results["RG-PIPE-001"] = {
        "http_status": catalog.get("status"),
        "tool_count": len(catalog_payload.get("tools") or []),
        "core_tool_ids": catalog_payload.get("phases", {}).get("core"),
        "has_pipeline_registry_endpoint": False,
    }
    results["RG-PIPE-002"] = {
        "route": compact_route(route("帮我回复 RG_Alice，说收到", reply_context)),
        "pipeline": compact_pipeline(run_pipeline("帮我回复 RG_Alice，说收到", reply_context)),
        "traces": api("GET", "/api/tools/route/traces?q=RG_Alice&limit=10"),
    }
    results["RG-PIPE-003"] = {
        "reply_slot_parser": compact_pipeline(
            run_pipeline(
                "帮我回复她，就说周五八点可以",
                {
                    "active_source_scope": {
                        "source": "whatsapp",
                        "conversation_id": "WX_RG_ALICE_THREAD",
                        "counterparty_ids": ["rg_alice"],
                        "conversation_label": "RG_Alice",
                    }
                },
            )
        ),
        "route_slot_parser": compact_pipeline(run_pipeline("查路线去武康路")),
    }

    open_route = route("帮我在这个冷门网站填报名表，但不要提交。", {"current_url": "https://example.invalid/form"})
    open_packet = (open_route.get("json") or {}).get("openclaw_task_packet") if isinstance(open_route.get("json"), dict) else {}
    job = api(
        "POST",
        "/api/tools/openclaw/jobs",
        {"packet": open_packet or {}, "execution_guard": (open_route.get("json") or {}).get("execution_guard") or {}, "trace_id": (open_route.get("json") or {}).get("task_trace_id")},
    )
    job_payload = job.get("json") if isinstance(job.get("json"), dict) else {}
    job_id = job_payload.get("job_id") or (job_payload.get("job") or {}).get("id")
    run_once = api("POST", f"/api/tools/openclaw/jobs/{job_id}/run-once") if job_id else {"status": "skipped", "json": {}}
    results["RG-OPEN-001"] = {
        "route": compact_route(open_route),
        "job": job,
        "run_once": run_once,
    }

    login_route = route("帮我登录某网站，需要用到账号 rg_user@example.test 和测试密码字段。")
    release = api(
        "POST",
        "/api/tools/openclaw/field-release",
        {"field": "password", "value": "synthetic-test-password", "purpose": "online regression synthetic login", "task_id": "rg-open-002"},
    )
    results["RG-OPEN-002"] = {
        "login_route": compact_route(login_route),
        "field_release": release,
    }

    results["RG-COMP-001"] = {
        "status": api("GET", "/api/tools/composio/status"),
        "integration_status": api("GET", "/api/integrations/composio/status"),
        "readonly_toolkits": api("GET", "/api/integrations/composio/toolkits?session_kind=readonly"),
    }
    results["RG-COMP-002"] = {
        "calendar_route": compact_route(route("把 RG_Alice 周日见面写进 Google Calendar", {"source_event_ids": [ALICE_EVENT_ID]})),
        "maps_route": compact_route(route("查去武康路的路线")),
        "drive_route": compact_route(route("在 Google Drive 找 PHONE_1 报价单并总结")),
    }

    quote_chat = compact_chat(chat("RG_Alice 的 PHONE_1 报价什么时候截止？"))
    conversation_id = quote_chat.get("conversation_id")
    results["RG-AUDIT-001"] = {
        "whatsapp_trace": api("GET", f"/api/events/{ALICE_EVENT_ID}/trace"),
        "invoice_trace": api("GET", f"/api/events/{INVOICE_EVENT_ID}/trace"),
    }
    results["RG-AUDIT-002"] = {
        "quote_chat": quote_chat,
        "conversation_trace": api("GET", f"/api/chat/conversations/{conversation_id}/trace") if conversation_id else {"status": "skipped", "json": {}},
    }
    results["RG-AUDIT-003"] = {
        "memory_governance": api("GET", "/api/memory/governance?q=rg-PHONE_1&limit=20"),
    }

    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
