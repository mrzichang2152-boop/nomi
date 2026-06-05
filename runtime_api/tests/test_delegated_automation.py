import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")
os.environ.setdefault("APP_PASSWORD", "secret")


def fixed_now() -> datetime:
    return datetime(2026, 6, 5, 9, 0, 0, tzinfo=timezone.utc)


def grant_payload(**overrides):
    payload = {
        "grant_id": "grant_job_linkedin_message",
        "user_id": "local_user",
        "scenario": "job_agent",
        "platform": "linkedin",
        "surface": "cloud_playwright_browser",
        "action": "send_message",
        "automation_level": "L4",
        "status": "active",
        "daily_limit": 2,
        "batch_limit": 2,
        "cooldown_minutes": 0,
        "valid_until": "2026-06-30T23:59:59+00:00",
        "requires_target_manifest": True,
        "requires_grounded_content": True,
        "requires_audit_log": True,
        "stop_on_challenge": True,
        "stop_on_user_pause": True,
        "created_at": "2026-06-05T08:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def manifest_payload(target_ids=None, **overrides):
    targets = []
    for target_id in target_ids or ["target_1"]:
        targets.append(
            {
                "target_id": target_id,
                "target_type": "person",
                "name": "Maya",
                "role": "Recruiter",
                "company": "Example AI",
                "profile_url": f"https://www.linkedin.com/in/{target_id}",
                "reason": "Recruiter for the AI Product Manager role.",
                "related_job_id": "job_123",
                "draft_id": "draft_456",
                "risk": "medium",
                "status": "pending",
            }
        )
    payload = {
        "manifest_id": "manifest_linkedin_outreach",
        "scenario": "job_agent",
        "platform": "linkedin",
        "action": "send_message",
        "targets": targets,
        "max_actions": len(targets),
        "created_from_evidence_ids": ["job_123", "resume_1"],
    }
    payload.update(overrides)
    return payload


def completed_trace_payload(grant_id="grant_job_linkedin_message", manifest_id="manifest_linkedin_outreach", target_id="target_1"):
    return {
        "trace_id": f"trace_{target_id}",
        "grant_id": grant_id,
        "manifest_id": manifest_id,
        "target_id": target_id,
        "action": "send_message",
        "status": "completed",
        "started_at": "2026-06-05T09:00:00+00:00",
        "finished_at": "2026-06-05T09:00:05+00:00",
        "result_summary": f"Message sent to {target_id}.",
        "evidence_ids": ["screenshot_1", "dom_evt_1", "draft_456"],
        "budget_after": {"used_today": 1, "remaining_today": 1},
    }


def test_l4_batch_action_requires_grant_manifest_and_grounded_evidence():
    from app.delegated_automation.models import DelegationGrant, TargetManifest
    from app.delegated_automation.policy import evaluate_delegated_action

    missing_grant = evaluate_delegated_action(
        grant=None,
        manifest=None,
        target_id="target_1",
        traces=[],
        now=fixed_now(),
        content_evidence_ids=["jd_1"],
    )
    assert missing_grant.allowed is False
    assert "missing_grant" in missing_grant.reasons

    grant = DelegationGrant.from_dict(grant_payload())
    missing_manifest = evaluate_delegated_action(
        grant=grant,
        manifest=None,
        target_id="target_1",
        traces=[],
        now=fixed_now(),
        content_evidence_ids=["jd_1"],
    )
    assert missing_manifest.allowed is False
    assert "missing_target_manifest" in missing_manifest.reasons

    manifest = TargetManifest.from_dict(manifest_payload())
    missing_evidence = evaluate_delegated_action(
        grant=grant,
        manifest=manifest,
        target_id="target_1",
        traces=[],
        now=fixed_now(),
        content_evidence_ids=[],
    )
    assert missing_evidence.allowed is False
    assert "missing_grounded_content" in missing_evidence.reasons


def test_l4_grant_allows_one_grounded_manifest_target_and_builds_trace_budget():
    from app.delegated_automation.models import DelegationGrant, TargetManifest
    from app.delegated_automation.policy import build_execution_trace, evaluate_delegated_action

    grant = DelegationGrant.from_dict(grant_payload(daily_limit=2, batch_limit=2))
    manifest = TargetManifest.from_dict(manifest_payload(["target_1", "target_2"]))

    decision = evaluate_delegated_action(
        grant=grant,
        manifest=manifest,
        target_id="target_1",
        traces=[],
        now=fixed_now(),
        content_evidence_ids=["jd_1", "resume_1", "draft_456"],
    )

    assert decision.allowed is True
    assert decision.stop_condition is None
    assert decision.budget["used_today"] == 0
    assert decision.budget["remaining_today"] == 2
    assert decision.target["target_id"] == "target_1"
    assert decision.action == "send_message"

    trace = build_execution_trace(
        decision=decision,
        trace_id="trace_target_1",
        status="completed",
        result_summary="Message sent to Maya.",
        evidence_ids=["screenshot_1", "dom_evt_1", "draft_456"],
        now=fixed_now(),
    )

    assert trace.status == "completed"
    assert trace.target_id == "target_1"
    assert trace.evidence_ids == ["screenshot_1", "dom_evt_1", "draft_456"]
    assert trace.budget_after == {"used_today": 1, "remaining_today": 1}


def test_daily_quota_duplicate_and_platform_challenge_stop_next_action():
    from app.delegated_automation.models import DelegationGrant, ExecutionTrace, TargetManifest
    from app.delegated_automation.policy import evaluate_delegated_action

    grant = DelegationGrant.from_dict(grant_payload(daily_limit=1, batch_limit=1))
    manifest = TargetManifest.from_dict(manifest_payload(["target_1", "target_2"]))
    completed_trace = ExecutionTrace.from_dict(completed_trace_payload(target_id="target_1"))

    exhausted = evaluate_delegated_action(
        grant=grant,
        manifest=manifest,
        target_id="target_2",
        traces=[completed_trace],
        now=fixed_now(),
        content_evidence_ids=["jd_1", "resume_1"],
    )
    assert exhausted.allowed is False
    assert exhausted.stop_condition == "quota_exhausted"
    assert "daily_limit_reached" in exhausted.reasons

    duplicate = evaluate_delegated_action(
        grant=grant,
        manifest=manifest,
        target_id="target_1",
        traces=[completed_trace],
        now=fixed_now(),
        content_evidence_ids=["jd_1", "resume_1"],
    )
    assert duplicate.allowed is False
    assert duplicate.stop_condition == "duplicate_target"
    assert "duplicate_target" in duplicate.reasons

    challenge = evaluate_delegated_action(
        grant=grant,
        manifest=manifest,
        target_id="target_2",
        traces=[],
        now=fixed_now(),
        page_state={"captcha": True},
        content_evidence_ids=["jd_1", "resume_1"],
    )
    assert challenge.allowed is False
    assert challenge.stop_condition == "platform_challenge"
    assert "platform_challenge" in challenge.reasons


def test_user_owned_whatsapp_and_gmail_automation_surfaces_are_out_of_scope():
    from app.delegated_automation.models import DelegationGrant, TargetManifest
    from app.delegated_automation.policy import evaluate_delegated_action

    manifest = TargetManifest.from_dict(manifest_payload(["target_1"]))
    for surface in ["user_whatsapp", "user_gmail", "personal_whatsapp", "personal_gmail"]:
        grant = DelegationGrant.from_dict(grant_payload(surface=surface))
        decision = evaluate_delegated_action(
            grant=grant,
            manifest=manifest,
            target_id="target_1",
            traces=[],
            now=fixed_now(),
            content_evidence_ids=["evt_1"],
        )
        assert decision.allowed is False
        assert decision.stop_condition == "personal_account_surface_out_of_scope"
        assert "personal_account_surface_out_of_scope" in decision.reasons


def test_store_persists_grants_manifests_traces_and_pause():
    from app.delegated_automation.models import DelegationGrant, ExecutionTrace, TargetManifest
    from app.delegated_automation.store import InMemoryDelegatedAutomationStore

    store = InMemoryDelegatedAutomationStore()
    grant = store.upsert_grant(DelegationGrant.from_dict(grant_payload()))
    manifest = store.upsert_manifest(TargetManifest.from_dict(manifest_payload(["target_1"])))
    trace = store.append_trace(ExecutionTrace.from_dict(completed_trace_payload()))

    assert store.get_grant(grant.grant_id).status == "active"
    assert store.get_manifest(manifest.manifest_id).targets[0].target_id == "target_1"
    assert store.traces_for_grant(grant.grant_id)[0].trace_id == trace.trace_id

    paused = store.pause_grant(grant.grant_id, reason="user_requested_pause")
    assert paused.status == "paused"
    assert store.get_grant(grant.grant_id).metadata["pause_reason"] == "user_requested_pause"


def test_delegated_automation_endpoints_require_password_and_expose_evaluate_trace_flow():
    from app.main import app

    client = TestClient(app)
    missing_password = client.post("/api/delegated-automation/grants", json=grant_payload())
    assert missing_password.status_code == 401

    headers = {"x-par-password": "secret"}
    grant_response = client.post("/api/delegated-automation/grants", headers=headers, json=grant_payload())
    assert grant_response.status_code == 200
    grant = grant_response.json()["grant"]
    assert grant["grant_id"] == "grant_job_linkedin_message"
    assert grant["automation_level"] == "L4"

    manifest_response = client.post(
        "/api/delegated-automation/manifests",
        headers=headers,
        json=manifest_payload(["target_1"]),
    )
    assert manifest_response.status_code == 200
    manifest = manifest_response.json()["manifest"]
    assert manifest["manifest_id"] == "manifest_linkedin_outreach"
    assert manifest["targets"][0]["reason"] == "Recruiter for the AI Product Manager role."

    decision_response = client.post(
        "/api/delegated-automation/evaluate",
        headers=headers,
        json={
            "grant_id": grant["grant_id"],
            "manifest_id": manifest["manifest_id"],
            "target_id": "target_1",
            "content_evidence_ids": ["jd_1", "resume_1", "draft_456"],
            "now": "2026-06-05T09:00:00+00:00",
        },
    )
    assert decision_response.status_code == 200
    decision = decision_response.json()["decision"]
    assert decision["allowed"] is True
    assert decision["budget"]["remaining_today"] == 2
    assert decision["target"]["target_id"] == "target_1"

    trace_response = client.post(
        "/api/delegated-automation/traces",
        headers=headers,
        json={
            "decision": decision,
            "trace_id": "api_trace_target_1",
            "status": "completed",
            "result_summary": "Message sent to Maya.",
            "evidence_ids": ["screenshot_1", "dom_evt_1", "draft_456"],
            "now": "2026-06-05T09:00:05+00:00",
        },
    )
    assert trace_response.status_code == 200
    trace = trace_response.json()["trace"]
    assert trace["trace_id"] == "api_trace_target_1"
    assert trace["budget_after"] == {"used_today": 1, "remaining_today": 1}

    paused = client.post(
        "/api/delegated-automation/grants/grant_job_linkedin_message/pause",
        headers=headers,
        json={"reason": "user_clicked_pause_all"},
    )
    assert paused.status_code == 200
    assert paused.json()["grant"]["status"] == "paused"
    assert paused.json()["grant"]["metadata"]["pause_reason"] == "user_clicked_pause_all"
