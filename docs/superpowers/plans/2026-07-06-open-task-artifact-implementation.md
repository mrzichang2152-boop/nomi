# Open Task Artifact Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Nomi open-task artifact loop so requests like “依据王总资料写一份 PPT” create a tracked task instead of being answered as ordinary chat.

**Architecture:** Add a small artifact-task module that classifies artifact requests, plans scoped evidence retrieval, creates task metadata, and returns a task card from `/api/chat`. Reuse the existing `task_runs/task_steps/notification_outbox` substrate, then extend it with artifact/evidence tables and APIs.

**Tech Stack:** FastAPI, Postgres schema SQL, Python unit tests, existing Android/Web chat contracts.

---

### Task 1: Artifact Task Router and Evidence Planner

**Files:**
- Create: `runtime_api/app/artifact_tasks.py`
- Test: `runtime_api/tests/test_artifact_tasks.py`

- [x] **Step 1: Write failing tests**

```python
def test_ppt_request_routes_to_artifact_creation_task():
    from app.artifact_tasks import route_artifact_task

    route = route_artifact_task("帮我依据刚刚王总给的资料，写一份 PPT")

    assert route["message_kind"] == "task_request"
    assert route["task_type"] == "artifact_creation"
    assert route["artifact_type"] == "pptx"
    assert route["requires_task_run"] is True
    assert route["risk_level"] == "medium"


def test_plain_question_stays_chat_answer():
    from app.artifact_tasks import route_artifact_task

    route = route_artifact_task("王总刚刚说了什么？")

    assert route["message_kind"] == "chat_answer"
    assert route["requires_task_run"] is False


def test_wang_zong_recent_material_plan_has_scoped_sources_and_missing_inputs():
    from app.artifact_tasks import build_context_requirement_plan

    plan = build_context_requirement_plan("帮我依据刚刚王总给的资料，写一份 PPT")

    assert plan["needed_context"][0]["entity_hint"] == "王总"
    assert "whatsapp" in plan["needed_context"][0]["source"]
    assert "PPT用途" in plan["missing_user_inputs"]
    assert plan["can_start_without_missing_inputs"] is True
```

- [x] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest runtime_api/tests/test_artifact_tasks.py -q`

Expected: FAIL because `app.artifact_tasks` does not exist.

- [x] **Step 3: Implement minimal router and planner**

Create `route_artifact_task`, `build_context_requirement_plan`, and deterministic Chinese heuristics for PPT/document/table artifact requests.

- [x] **Step 4: Verify green**

Run: `python3 -m pytest runtime_api/tests/test_artifact_tasks.py -q`

Expected: PASS.

### Task 2: Artifact Schema and In-Memory Task Factory

**Files:**
- Modify: `runtime_api/app/task_orchestrator.py`
- Test: `runtime_api/tests/test_task_orchestrator.py`

- [x] **Step 1: Write failing tests**

Add assertions that schema SQL creates:

```python
assert "CREATE TABLE IF NOT EXISTS task_artifacts" in combined
assert "CREATE TABLE IF NOT EXISTS task_evidence_links" in combined
assert "task_artifacts_task_idx" in combined
```

Add an in-memory test that `TaskOrchestrator.create_task_run(...)` accepts payload, source evidence ids, pipeline id, and route type.

- [x] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest runtime_api/tests/test_task_orchestrator.py -q`

Expected: FAIL on missing artifact tables / fields.

- [x] **Step 3: Implement schema and payload support**

Extend `task_orchestrator_schema_sql` and `TaskOrchestrator.create_task_run`.

- [x] **Step 4: Verify green**

Run: `python3 -m pytest runtime_api/tests/test_task_orchestrator.py -q`

Expected: PASS.

### Task 3: `/api/chat` Artifact Task Handoff

**Files:**
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_context_pack_and_chat.py`

- [x] **Step 1: Write failing integration test**

Post `{"message": "帮我依据刚刚王总给的资料，写一份 PPT"}` to `/api/chat` with DB and context retrieval monkeypatched. Expected response contains:

```python
assert payload["task"]["task_type"] == "artifact_creation"
assert payload["task"]["artifact_type"] == "pptx"
assert payload["context_pack"]["task_route"]["message_kind"] == "task_request"
assert "PPT" in payload["answer"]
```

The fake model gateway must not be called.

- [x] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest runtime_api/tests/test_context_pack_and_chat.py::<new_test_name> -q`

Expected: FAIL because `/api/chat` treats it as normal model chat.

- [x] **Step 3: Implement handoff**

After initial user-turn persistence and before model call, route artifact requests. Build scoped context/evidence plan, persist/record task metadata, persist assistant turn with a task-card answer, and return task metadata in the response.

- [x] **Step 4: Verify green**

Run the focused test and related chat tests.

### Task 4: Artifact APIs and Download Shell

**Files:**
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_artifact_tasks.py`

- [x] **Step 1: Write failing tests**

Test `GET /api/tasks/{task_id}` returns task state and `GET /api/tasks/{task_id}/artifacts` returns an empty artifact list for a planning task.

- [x] **Step 2: Run test to verify it fails**

Run focused pytest.

- [x] **Step 3: Implement minimal APIs**

Use existing password guard, no external side effects.

- [x] **Step 4: Verify green**

Run focused pytest.

### Task 5: Gap Tracker

**Files:**
- Create: `docs/superpowers/reports/2026-07-06-open-task-artifact-gaps.md`

- [x] **Step 1: Record completed scope and gaps**

Document which parts of the spec are implemented, which remain: real PPTX generation, slide verifier, Android artifact card, Web task detail page, Playwright/Composio attachment retrieval.

- [x] **Step 2: Verify repository**

Run:

```bash
git diff --check
python3 -m pytest runtime_api/tests/test_artifact_tasks.py runtime_api/tests/test_task_orchestrator.py -q
```

Expected: no diff whitespace errors; focused tests pass.

## Self Review

- Spec coverage: Phase 1 is covered end to end. Phase 2/3/4 remain explicit gaps.
- Placeholder scan: No TODO/TBD placeholders.
- Type consistency: Uses `task_run_id`, `task_type`, `artifact_type`, `task_route`, `task_artifacts`, and `task_evidence_links` consistently with the spec and existing schema style.
