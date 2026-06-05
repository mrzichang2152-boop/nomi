# Delegated Automation Permission Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend foundation that lets Nomi evaluate, limit, pause, and audit delegated high-impact automation actions such as LinkedIn outreach, Apply/Submit, and bounded batch execution.

**Architecture:** Implement a small pure Python policy engine plus an in-memory store and password-protected FastAPI endpoints. The engine owns grants, target manifests, quota/budget checks, stop conditions, duplicate checks, and append-only traces; scenario pipelines and Playwright/Composio executors will call this foundation before performing external actions.

**Tech Stack:** Python 3, FastAPI, Pydantic-compatible dictionaries, pytest, existing `runtime_api/app/main.py` route style, existing `x-par-password` auth.

---

## File Structure

- Create `runtime_api/app/delegated_automation/__init__.py` for package exports.
- Create `runtime_api/app/delegated_automation/models.py` for dataclasses and JSON conversion helpers.
- Create `runtime_api/app/delegated_automation/policy.py` for pure decision logic.
- Create `runtime_api/app/delegated_automation/store.py` for in-memory grant, manifest, and trace storage.
- Create `runtime_api/app/delegated_automation/schema.py` for Postgres table DDL.
- Create `runtime_api/tests/test_delegated_automation.py` for TDD coverage of the foundation.
- Modify `runtime_api/app/main.py` only to import the new schema helper, ensure schema on startup, create a module-level store, and expose password-protected API endpoints.
- Create `docs/superpowers/reports/2026-06-05-delegated-automation-implementation-gaps.md` to explicitly mark implemented and remaining gaps.

## Task 1: Pure Policy Engine

**Files:**
- Create: `runtime_api/app/delegated_automation/models.py`
- Create: `runtime_api/app/delegated_automation/policy.py`
- Create: `runtime_api/app/delegated_automation/store.py`
- Test: `runtime_api/tests/test_delegated_automation.py`

- [x] **Step 1: Write failing tests for grant, manifest, quota, stop, duplicate, and out-of-scope personal account behavior**

```python
def test_l4_batch_action_requires_grant_manifest_and_grounded_evidence():
    assert evaluate_delegated_action(None, None, "target_1", [], now=fixed_now()).allowed is False

def test_l4_grant_allows_one_grounded_manifest_target_and_records_budget_trace():
    grant = linkedin_message_grant(daily_limit=2, batch_limit=2)
    manifest = linkedin_manifest(["target_1"])
    decision = evaluate_delegated_action(grant, manifest, "target_1", [], now=fixed_now(), content_evidence_ids=["jd_1", "resume_1"])
    assert decision.allowed is True

def test_daily_quota_duplicate_and_platform_challenge_stop_next_action():
    grant = linkedin_message_grant(daily_limit=1, batch_limit=1)
    trace = completed_trace(grant, "target_1")
    assert evaluate_delegated_action(grant, linkedin_manifest(["target_2"]), "target_2", [trace], now=fixed_now(), content_evidence_ids=["jd_1"]).allowed is False
    assert evaluate_delegated_action(grant, linkedin_manifest(["target_1"]), "target_1", [], now=fixed_now(), content_evidence_ids=["jd_1"]).allowed is True
    challenge = evaluate_delegated_action(grant, linkedin_manifest(["target_2"]), "target_2", [], now=fixed_now(), page_state={"captcha": True}, content_evidence_ids=["jd_1"])
    assert challenge.allowed is False
    assert challenge.stop_condition == "platform_challenge"

def test_user_owned_whatsapp_and_gmail_automation_surfaces_are_out_of_scope():
    grant = linkedin_message_grant(surface="user_whatsapp")
    decision = evaluate_delegated_action(grant, linkedin_manifest(["target_1"]), "target_1", [], now=fixed_now(), content_evidence_ids=["evt_1"])
    assert decision.allowed is False
    assert "personal_account_surface_out_of_scope" in decision.reasons
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd runtime_api && pytest tests/test_delegated_automation.py -q`

Expected: FAIL because `app.delegated_automation` does not exist yet.

- [x] **Step 3: Implement minimal dataclasses, decision logic, store, and JSON helpers**

Implement `DelegationGrant`, `TargetManifest`, `ManifestTarget`, `ExecutionTrace`, `AutomationBudget`, `AutomationDecision`, `evaluate_delegated_action`, `build_execution_trace`, and `InMemoryDelegatedAutomationStore`.

- [x] **Step 4: Run tests to verify policy engine passes**

Run: `cd runtime_api && pytest tests/test_delegated_automation.py -q`

Expected: PASS for pure engine tests.

## Task 2: API And Schema

**Files:**
- Create: `runtime_api/app/delegated_automation/schema.py`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_delegated_automation.py`

- [x] **Step 1: Write failing endpoint tests**

```python
def test_delegated_automation_endpoints_require_password_and_expose_evaluate_trace_flow():
    response = TestClient(app).post("/api/delegated-automation/grants", json={})
    assert response.status_code == 401

    grant = client.post("/api/delegated-automation/grants", headers=headers, json=grant_payload()).json()["grant"]
    manifest = client.post("/api/delegated-automation/manifests", headers=headers, json=manifest_payload()).json()["manifest"]
    decision = client.post("/api/delegated-automation/evaluate", headers=headers, json={
        "grant_id": grant["grant_id"],
        "manifest_id": manifest["manifest_id"],
        "target_id": "target_1",
        "content_evidence_ids": ["jd_1", "resume_1"]
    }).json()
    assert decision["allowed"] is True
    trace = client.post("/api/delegated-automation/traces", headers=headers, json={...}).json()["trace"]
    assert trace["budget_after"]["remaining_today"] == 0
```

- [x] **Step 2: Run endpoint tests to verify failure**

Run: `cd runtime_api && pytest tests/test_delegated_automation.py::test_delegated_automation_endpoints_require_password_and_expose_evaluate_trace_flow -q`

Expected: FAIL because endpoints do not exist.

- [x] **Step 3: Add schema DDL and password-protected endpoints**

Implement `delegated_automation_schema_sql()`, `ensure_delegated_automation_schema()`, and endpoints:

- `POST /api/delegated-automation/grants`
- `GET /api/delegated-automation/grants`
- `POST /api/delegated-automation/manifests`
- `POST /api/delegated-automation/evaluate`
- `POST /api/delegated-automation/traces`
- `POST /api/delegated-automation/grants/{grant_id}/pause`

- [x] **Step 4: Run endpoint tests to verify pass**

Run: `cd runtime_api && pytest tests/test_delegated_automation.py -q`

Expected: PASS.

## Task 3: Gap Ledger And Regression

**Files:**
- Create: `docs/superpowers/reports/2026-06-05-delegated-automation-implementation-gaps.md`

- [x] **Step 1: Mark implemented scope and remaining gaps**

Document that V1 now has backend policy, quota, manifest, stop, trace, and API support. Mark remaining gaps: Playwright executor adapter, UI permission center, persisted DB-backed store, Job Agent pipeline integration, real LinkedIn/ATS execution.

- [x] **Step 2: Run focused regression**

Run:

```bash
cd runtime_api && pytest tests/test_delegated_automation.py tests/test_core_pipeline_engine.py::test_pipeline_registry_endpoint_exposes_capabilities -q
```

Expected: PASS or a clear unrelated failure to be recorded with evidence.

## Self-Review

- Spec coverage: grant, manifest, budget/quota, stop conditions, audit trace, user pause, password-protected API, and out-of-scope personal Gmail/WhatsApp rules are covered.
- Gaps are explicit: this plan does not pretend to implement real Playwright/Composio execution or Android UI.
- No hidden escalation: every evaluated action must name grant, manifest, action, platform, surface, target, and evidence.
