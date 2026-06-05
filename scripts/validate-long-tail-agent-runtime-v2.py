#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime_api"))

from app.long_tail_agent import (  # noqa: E402
    ExecutorAdapterRegistry,
    ExternalEffectController,
    LongTailEventStore,
    LongTailGraphRunner,
    PolicyGate,
    StepVerifier,
)


def emit(stage: str, output: dict, reasonable: bool, reason: str) -> None:
    print(
        json.dumps(
            {
                "stage": stage,
                "reasonable": reasonable,
                "reason": reason,
                "output": output,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def online_json_request(base_url: str, password: str, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {"x-par-password": password}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read().decode("utf-8")
        return int(response.status), json.loads(body or "{}")


def validate_online_deployed_api_mode(plan: dict) -> None:
    base_url = os.getenv("NOMI_ONLINE_BASE_URL", "").strip()
    password = os.getenv("NOMI_ONLINE_PASSWORD", "").strip()
    if not base_url or not password:
        emit(
            "online_deployed_api_mode",
            {
                "status": "skipped",
                "required_env": ["NOMI_ONLINE_BASE_URL", "NOMI_ONLINE_PASSWORD"],
            },
            True,
            "Online API validation is available but was not run because online target env vars are not configured.",
        )
        return

    try:
        route_status, route = online_json_request(
            base_url,
            password,
            "POST",
            "/api/agent-tasks/route",
            {"request": "线上验证：帮我检查网页字段但不要提交", "context": {"validation": "long_tail_runtime_v2"}},
        )
        create_status, created = online_json_request(
            base_url,
            password,
            "POST",
            "/api/agent-tasks",
            {
                "original_goal": "线上验证：帮我检查网页字段但不要提交",
                "route_decision": route,
                "plan": plan,
            },
        )
        task_id = str(created.get("task_id") or "")
        state_status, state_payload = online_json_request(base_url, password, "GET", f"/api/agent-tasks/{task_id}")
        events_status, events_payload = online_json_request(base_url, password, "GET", f"/api/agent-tasks/{task_id}/events")
        event_types = [event.get("event_type") for event in events_payload.get("events", [])]
        output = {
            "status": "validated",
            "route_status": route_status,
            "create_status": create_status,
            "state_status": state_status,
            "events_status": events_status,
            "route_type": route.get("route_type"),
            "capability_id": route.get("capability_id"),
            "task_id": task_id,
            "task_status": (state_payload.get("state") or {}).get("status"),
            "event_count": len(event_types),
            "event_types": event_types[:8],
        }
        emit(
            "online_deployed_api_mode",
            output,
            route_status == 200
            and create_status == 200
            and state_status == 200
            and events_status == 200
            and route.get("route_type") == "long_tail_agent"
            and bool(task_id)
            and "task.created" in event_types
            and "plan.validated" in event_types,
            "Online deployed API routes, creates, reads state, and reads events against the real service.",
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
        emit(
            "online_deployed_api_mode",
            {"status": "failed", "error": type(exc).__name__, "message": str(exc)[:500]},
            False,
            "Online deployed API validation failed before semantic outputs could be verified.",
        )


def main() -> int:
    event_store = LongTailEventStore()
    runner = LongTailGraphRunner(event_store=event_store, verifier=StepVerifier())
    registry = ExecutorAdapterRegistry(event_store=event_store, policy_gate=PolicyGate())
    external_effects = ExternalEffectController(event_store=event_store)
    plan = {
        "task_goal": "Inspect the page without submitting.",
        "success_criteria": ["Page title is known.", "Visible fields are listed.", "No submit action occurs."],
        "steps": [
            {
                "step_id": "inspect_page",
                "step_type": "browser_page_read",
                "objective": "Identify page title and visible form fields.",
                "expected_outputs": ["page_title", "field_list"],
                "allowed_actions": ["browser.observe", "browser.screenshot"],
                "forbidden_actions": ["browser.submit"],
                "verification_criteria": ["Page title is reported.", "Fields are listed."],
            }
        ],
    }

    task = runner.create_task(
        original_goal="帮我检查报名网页，整理字段，但不要提交",
        route_decision={"route_type": "long_tail_agent", "capability_id": "long_tail.browser_or_tool_task"},
        plan=plan,
    )
    emit(
        "task_created",
        task,
        task["status"] == "running" and task["current_node"] == "select_step",
        "The task is a validated graph run and has not executed any external action.",
    )

    packet = runner.run_next(task["task_id"])
    emit(
        "step_packet",
        packet,
        packet["step_id"] == "inspect_page" and "browser.submit" in packet["forbidden_actions"],
        "The packet is scoped to one step and carries stop-before-submit constraints.",
    )

    runner = LongTailGraphRunner(event_store=event_store, verifier=StepVerifier())
    recovered = runner.recover_task(task["task_id"])
    emit(
        "restart_recovery",
        {
            "task_id": recovered["task_id"],
            "status": recovered["status"],
            "current_node": recovered["current_node"],
            "current_step_id": recovered.get("current_step_id"),
            "completed_steps": recovered["completed_steps"],
            "plan_version": recovered["plan_version"],
        },
        recovered["current_node"] == "awaiting_executor"
        and recovered.get("current_step_id") == "inspect_page"
        and recovered["completed_steps"] == [],
        "A restarted runner recovers the pending executor step from the event log.",
    )

    runner.request_human_input(
        task["task_id"],
        step_id="inspect_page",
        input_type="clarification",
        question="是否继续只读检查网页？",
        options=[{"id": "continue_read_only", "label": "继续只读检查"}],
    )
    waiting_state = runner.get_task_state(task["task_id"])
    emit(
        "human_input_waiting",
        {
            "current_node": waiting_state["current_node"],
            "current_step_id": waiting_state.get("current_step_id"),
            "pending_human_input": waiting_state.get("pending_human_input"),
        },
        waiting_state["current_node"] == "waiting_for_human_input"
        and waiting_state.get("pending_human_input", {}).get("question") == "是否继续只读检查网页？",
        "Human-input request exposes the exact question/options before continuing.",
    )

    runner.record_human_input(
        task["task_id"],
        step_id="inspect_page",
        input_type="clarification",
        response={"choice": "continue_read_only"},
    )
    resolved_state = runner.get_task_state(task["task_id"])
    emit(
        "human_input_resolved",
        {
            "current_node": resolved_state["current_node"],
            "current_step_id": resolved_state.get("current_step_id"),
            "pending_human_input": resolved_state.get("pending_human_input"),
        },
        resolved_state["current_node"] == "select_step" and "pending_human_input" not in resolved_state,
        "User input clears the pending request and returns the graph to step selection.",
    )

    external_effect = external_effects.propose(
        task_id=task["task_id"],
        step_id="inspect_page",
        action_request_id="act_demo_external_effect",
        effect_type="email.send",
        proposal={"recipient": "user@example.test", "subject": "Draft summary"},
    )
    premature_execute = external_effects.execute(
        external_effect["effect_id"],
        execution_payload={"provider": "demo", "message_id": "msg_before_confirm"},
    )
    emit(
        "external_effect_waiting_confirmation",
        {"effect": external_effect, "premature_execute": premature_execute},
        external_effect["status"] == "waiting_for_confirmation"
        and premature_execute["may_execute"] is False
        and "before user confirmation" in premature_execute["reason"],
        "External effects are proposed but blocked before user confirmation.",
    )

    confirmed = external_effects.confirm(
        external_effect["effect_id"],
        confirmation_payload={"confirmed_by": "user", "scope": "demo_validation"},
    )
    executed = external_effects.execute(
        external_effect["effect_id"],
        execution_payload={"provider": "demo", "message_id": "msg_after_confirm"},
    )
    emit(
        "external_effect_confirmed_and_executed",
        {"confirmed": confirmed, "executed": executed},
        confirmed["status"] == "confirmed"
        and executed["status"] == "executed"
        and executed["may_execute"] is True,
        "After confirmation, the external effect can execute and records execution payload.",
    )

    blocked_submit = registry.propose_action(
        task_id=task["task_id"],
        step_id="inspect_page",
        adapter="browser",
        action_type="browser.submit",
        target={"kind": "button", "visible_label": "Submit"},
        input_summary={},
        risk_level="external_write",
        expected_effect="Submit the form.",
        allowed_actions={"browser.observe", "browser.screenshot", "browser.submit"},
    )
    emit(
        "policy_block_submit",
        blocked_submit,
        blocked_submit["policy_report"]["status"] == "blocked",
        "PolicyGate blocks submit before the browser adapter can execute it.",
    )

    allowed_observe = registry.propose_action(
        task_id=task["task_id"],
        step_id="inspect_page",
        adapter="browser",
        action_type="browser.observe",
        target={"kind": "page", "value": "current"},
        input_summary={},
        risk_level="read_only",
        expected_effect="Read current page title and fields.",
        allowed_actions={"browser.observe", "browser.screenshot"},
    )
    emit(
        "policy_allow_observe",
        allowed_observe,
        allowed_observe["policy_report"]["status"] == "allowed",
        "Read-only observation is allowed for this step.",
    )

    dry_run_observe = registry.execute_dry_run(
        task_id=task["task_id"],
        step_id="inspect_page",
        adapter="openclaw",
        action_type="browser.observe",
        target={"kind": "page", "value": "current"},
        input_summary={},
        risk_level="read_only",
        expected_effect="Read current page title and fields without live adapter execution.",
        allowed_actions={"browser.observe", "browser.screenshot"},
        executor_trace={
            "provider_trace_id": "openclaw_dry_validate",
            "executor_trace_id": "browser_observe_dry_validate",
            "adapter_mode": "dry_run",
        },
    )
    emit(
        "adapter_dry_run_observe",
        dry_run_observe,
        dry_run_observe["mode"] == "dry_run"
        and dry_run_observe["status"] == "skipped_live_execution"
        and dry_run_observe["dry_run_result"]["external_side_effect"] is False
        and dry_run_observe["executor_trace"]["executor_trace_id"] == "browser_observe_dry_validate",
        "Adapter dry-run records trace ids and explicitly skips live external execution.",
    )

    live_call_count = {"observe": 0, "blocked": 0}

    def fake_live_observe(action_request: dict) -> dict:
        live_call_count["observe"] += 1
        return {
            "status": "completed",
            "summary": "Observed demo page title without changing remote state.",
            "external_side_effect": False,
            "provider_trace_id": "openclaw_live_validate",
            "executor_trace_id": "browser_observe_live_validate",
        }

    live_observe = registry.execute_live(
        task_id=task["task_id"],
        step_id="inspect_page",
        adapter="openclaw",
        action_type="browser.observe",
        target={"kind": "page", "value": "current"},
        input_summary={"scope": "title_and_visible_fields"},
        risk_level="read_only",
        expected_effect="Read current page title and fields through a live adapter boundary.",
        allowed_actions={"browser.observe", "browser.screenshot"},
        executor=fake_live_observe,
        executor_trace={"provider": "openclaw", "adapter_mode": "live"},
    )
    emit(
        "adapter_live_observe",
        live_observe,
        live_observe["mode"] == "live"
        and live_observe["status"] == "completed"
        and live_observe["policy_report"]["status"] == "allowed"
        and live_observe["live_result"]["external_side_effect"] is False
        and live_observe["executor_trace"]["provider_trace_id"] == "openclaw_live_validate"
        and live_call_count["observe"] == 1,
        "Live adapter execution is wrapped by ActionRequest/PolicyGate and records provider trace ids.",
    )

    def forbidden_live_submit(action_request: dict) -> dict:
        live_call_count["blocked"] += 1
        return {"status": "completed", "external_side_effect": True}

    blocked_live = registry.execute_live(
        task_id=task["task_id"],
        step_id="inspect_page",
        adapter="browser",
        action_type="browser.submit",
        target={"kind": "button", "visible_label": "Submit"},
        input_summary={},
        risk_level="external_write",
        expected_effect="Submit the form.",
        allowed_actions={"browser.observe", "browser.screenshot", "browser.submit"},
        executor=forbidden_live_submit,
        executor_trace={"provider": "managed_browser", "adapter_mode": "live"},
    )
    emit(
        "adapter_live_policy_block",
        blocked_live,
        blocked_live["status"] == "blocked_by_policy"
        and blocked_live["policy_report"]["status"] == "blocked"
        and blocked_live["live_result"]["external_side_effect"] is False
        and live_call_count["blocked"] == 0,
        "Policy blocks a live submit before the adapter callback can run.",
    )

    fallback_store = LongTailEventStore()
    fallback_runner = LongTailGraphRunner(event_store=fallback_store, verifier=StepVerifier())
    fallback_task = fallback_runner.create_task(
        original_goal="帮我起草邮件但不要发送",
        route_decision={"route_type": "long_tail_agent", "capability_id": "long_tail.message_draft"},
        plan={
            "task_goal": "Draft an email without sending.",
            "success_criteria": ["Draft exists.", "No email is sent."],
            "steps": [
                {
                    "step_id": "draft_email",
                    "step_type": "draft_creation",
                    "objective": "Prepare draft content without calling email.send.",
                    "expected_outputs": ["draft_subject", "draft_body"],
                    "allowed_actions": ["email.create_draft"],
                    "forbidden_actions": ["email.send"],
                    "verification_criteria": ["Draft identity exists.", "No send action occurred."],
                }
            ],
        },
    )
    fallback_runner.run_next(fallback_task["task_id"])
    fallback = fallback_runner.complete_current_step(
        fallback_task["task_id"],
        executor_result={
            "status": "passed",
            "summary": "Drafted and sent the email.",
            "outputs": {"draft_subject": "Quote", "draft_body": "Hello Alice"},
            "evidence": [{"type": "draft_payload_hash", "value": "sha256:draft"}],
            "action_events": [{"action_type": "email.send", "status": "sent"}],
        },
    )
    emit(
        "fallback_external_action_card",
        fallback,
        fallback["status"] == "fallback"
        and fallback["verifier_report"]["status"] == "blocked"
        and fallback["fallback_decision"]["action_card"]["actions"][0]["id"] == "review_external_effects"
        and "不能假装已经撤回第三方动作" in fallback["fallback_decision"]["action_card"]["message"],
        "Verifier-blocked external actions surface a rollback/compensation review card instead of silently passing.",
    )

    completion = runner.complete_current_step(
        task["task_id"],
        executor_result={
            "status": "passed",
            "summary": "Found page title and visible fields.",
            "outputs": {"page_title": "Apply Now", "field_list": ["name", "email"]},
            "evidence": [
                {"type": "browser_observation", "label": "Page title", "value": "Apply Now"},
                {"type": "dom_excerpt", "label": "Fields", "value": "Name Email"},
            ],
            "action_events": [{"action_id": allowed_observe["action_request"]["action_id"], "action_type": "browser.observe"}],
        },
    )
    emit(
        "verification_passed",
        completion,
        completion["verifier_report"]["status"] == "passed",
        "Verifier passes only after independent browser/DOM evidence is present.",
    )

    final = runner.evaluate_final(task["task_id"])
    emit(
        "final_delivery_external_effect_card",
        final,
        final["status"] == "passed"
        and final["delivery"]["message"].startswith("已完成")
        and final["delivery"]["actions"][0]["id"] == "review_external_effect_rollback"
        and final["delivery"]["actions"][0]["effect_id"] == external_effect["effect_id"],
        "Final delivery is grounded in verified completed steps and exposes executed-effect rollback/compensation review.",
    )

    event_types = [event["event_type"] for event in event_store.task_events(task["task_id"])]
    trace = {"event_types": event_types, "event_count": len(event_types)}
    emit(
        "event_trace",
        trace,
        all(
            required in event_types
            for required in [
                "task.created",
                "plan.validated",
                "step_packet.built",
                "human_input.requested",
                "human_input.received",
                "external_effect.proposed",
                "external_effect.confirmed",
                "external_effect.executed",
                "executor.action_requested",
                "policy.checked",
                "executor.dry_run_completed",
                "step.verified",
                "final.evaluated",
                "delivery.created",
            ]
        ),
        "Trace includes graph, human-input, external-effect, dry-run adapter, policy, verifier, and final delivery events.",
    )

    os.environ["DATABASE_URL"] = "postgresql://test"
    os.environ["REDIS_URL"] = "redis://test"
    os.environ["APP_PASSWORD"] = "secret"

    from fastapi.testclient import TestClient  # noqa: WPS433
    from app import main as runtime_main  # noqa: WPS433

    api_store = LongTailEventStore()
    runtime_main._LONG_TAIL_EVENT_STORE = api_store
    runtime_main._LONG_TAIL_RUNNER = LongTailGraphRunner(event_store=api_store, verifier=StepVerifier())
    client = TestClient(runtime_main.app)
    route_response = client.post(
        "/api/agent-tasks/route",
        headers={"x-par-password": "secret"},
        json={"request": "帮我打开网页填写报名表但不要提交", "context": {}},
    )
    route = route_response.json()
    create_response = client.post(
        "/api/agent-tasks",
        headers={"x-par-password": "secret"},
        json={
            "original_goal": "帮我打开网页填写报名表但不要提交",
            "route_decision": route,
            "plan": plan,
        },
    )
    created = create_response.json()
    state_response = client.get(
        f"/api/agent-tasks/{created['task_id']}",
        headers={"x-par-password": "secret"},
    )
    events_response = client.get(
        f"/api/agent-tasks/{created['task_id']}/events",
        headers={"x-par-password": "secret"},
    )
    api_state = state_response.json()["state"]
    api_event_types = [event["event_type"] for event in events_response.json()["events"]]
    emit(
        "api_mode_state_and_events",
        {"route": route, "state": api_state, "event_types": api_event_types},
        route_response.status_code == 200
        and route.get("route_type") == "long_tail_agent"
        and create_response.status_code == 200
        and state_response.status_code == 200
        and events_response.status_code == 200
        and api_state.get("status") == "running"
        and "task.created" in api_event_types
        and "plan.validated" in api_event_types,
        "API mode routes, creates, reads state, and reads event trace through password-protected endpoints.",
    )

    proposed_effect_response = client.post(
        f"/api/agent-tasks/{created['task_id']}/external-effects",
        headers={"x-par-password": "secret"},
        json={
            "step_id": "inspect_page",
            "action_request_id": "act_api_external_effect",
            "effect_type": "email.send",
            "proposal": {"recipient": "user@example.test", "subject": "API validation summary"},
        },
    )
    proposed_effect = proposed_effect_response.json()
    runtime_main._LONG_TAIL_EFFECT_CONTROLLER = ExternalEffectController(event_store=api_store)
    blocked_effect_response = client.post(
        f"/api/agent-tasks/{created['task_id']}/external-effects/{proposed_effect['effect_id']}/execute",
        headers={"x-par-password": "secret"},
        json={"execution_payload": {"message_id": "before_confirm"}},
    )
    confirmed_effect_response = client.post(
        f"/api/agent-tasks/{created['task_id']}/external-effects/{proposed_effect['effect_id']}/confirm",
        headers={"x-par-password": "secret"},
        json={"confirmation": {"confirmed_by": "user", "scope": "api_validation"}},
    )
    executed_effect_response = client.post(
        f"/api/agent-tasks/{created['task_id']}/external-effects/{proposed_effect['effect_id']}/execute",
        headers={"x-par-password": "secret"},
        json={"execution_payload": {"message_id": "after_confirm"}},
    )
    api_effect_event_types = [
        event["event_type"]
        for event in client.get(
            f"/api/agent-tasks/{created['task_id']}/events",
            headers={"x-par-password": "secret"},
        ).json()["events"]
    ]
    blocked_effect = blocked_effect_response.json()
    confirmed_effect = confirmed_effect_response.json()
    executed_effect = executed_effect_response.json()
    emit(
        "api_external_effect_state_machine",
        {
            "proposed": proposed_effect,
            "blocked": blocked_effect,
            "confirmed": confirmed_effect,
            "executed": executed_effect,
            "event_types": api_effect_event_types,
        },
        proposed_effect_response.status_code == 200
        and blocked_effect_response.status_code == 200
        and confirmed_effect_response.status_code == 200
        and executed_effect_response.status_code == 200
        and proposed_effect.get("status") == "waiting_for_confirmation"
        and blocked_effect.get("may_execute") is False
        and confirmed_effect.get("status") == "confirmed"
        and executed_effect.get("status") == "executed"
        and executed_effect.get("may_execute") is True
        and api_effect_event_types[-3:]
        == ["external_effect.proposed", "external_effect.confirmed", "external_effect.executed"],
        "API external-effect endpoints use the controller state machine and recover state from the event log.",
    )
    runtime_main._LONG_TAIL_EFFECT_CONTROLLER = ExternalEffectController(event_store=api_store)
    rollback_effect_response = client.post(
        f"/api/agent-tasks/{created['task_id']}/external-effects/{proposed_effect['effect_id']}/rollback",
        headers={"x-par-password": "secret"},
    )
    compensation_effect_response = client.post(
        f"/api/agent-tasks/{created['task_id']}/external-effects/{proposed_effect['effect_id']}/compensation",
        headers={"x-par-password": "secret"},
        json={"proposal": {"type": "draft_correction_email", "reason": "API validation compensation"}},
    )
    rollback_effect = rollback_effect_response.json()
    compensation_effect = compensation_effect_response.json()
    emit(
        "api_external_effect_rollback_card",
        {"rollback": rollback_effect, "compensation": compensation_effect},
        rollback_effect_response.status_code == 200
        and compensation_effect_response.status_code == 200
        and rollback_effect.get("external_world_can_rollback") is False
        and rollback_effect.get("action_card", {}).get("actions", [{}])[0].get("id") == "prepare_compensation"
        and compensation_effect.get("status") == "waiting_for_compensation_confirmation",
        "API rollback explains that only Nomi internal state can roll back and offers a compensation action card.",
    )
    app_js = (ROOT / "runtime_api" / "app" / "static" / "app.js").read_text(encoding="utf-8")
    app_css = (ROOT / "runtime_api" / "app" / "static" / "styles.css").read_text(encoding="utf-8")
    static_surface = {
        "has_delivery_handler": 'event.type === "agent_task_delivery"' in app_js,
        "has_fallback_handler": 'event.type === "agent_task_fallback"' in app_js,
        "has_rollback_handler": "review_external_effect_rollback" in app_js
        and "external-effects/${effectId}/rollback" in app_js,
        "has_compensation_handler": "prepare_compensation" in app_js
        and "external-effects/${effectId}/compensation" in app_js,
        "has_pending_agent_event_bridge": "nomi-pending-agent-event" in app_js
        and "consumePendingAgentEvent" in app_js
        and "handleRealtimeMessage(event)" in app_js,
        "has_action_card_styles": ".long-tail-action-card" in app_css,
    }
    emit(
        "static_workbench_action_card_surface",
        static_surface,
        all(static_surface.values()),
        "H5 workbench can display long-tail delivery/fallback cards and open rollback/compensation flows.",
    )
    validate_online_deployed_api_mode(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
