# Core Pipeline Engine Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn core pipeline routing metadata into a minimal executable state-machine contract with slots, missing slots, risk gates, statuses, and auditable outputs.

**Architecture:** Keep the first implementation in `runtime_api/app/main.py` to avoid a broad router split while the API surface is moving, but expose pure helpers that can later move to `runtime_api/app/pipelines/`. The engine reuses `route_tool_request()` and `core_pipeline_registry()` and adds deterministic slot resolution plus typed pipeline results.

**Tech Stack:** FastAPI, Pydantic, pytest, existing task routing helpers.

---

### Task 1: Add Executable Pipeline Contract

**Files:**
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_core_pipeline_engine.py`
- Document: `docs/superpowers/specs/2026-05-28-implementation-gap-closure-design.md`

- [x] **Step 1: Write failing tests for executable pipeline outputs**

Add tests for:

- reply request returns `draft_ready`, resolved recipient/channel/message intent, and external-message confirmation.
- route request returns `completed_read_only`, resolved destination, and no final confirmation.
- ride request returns `needs_user_input` when pickup is missing, resolved destination, and final confirmation protection.
- vague payment request returns `needs_user_input` with amount/counterparty missing.

- [x] **Step 2: Run tests to verify RED**

Run:

```bash
python3 -m pytest runtime_api/tests/test_core_pipeline_engine.py -q
```

Expected: fail because `run_core_pipeline()` does not exist.

- [x] **Step 3: Implement the minimal engine**

Add:

- `extract_pipeline_slots()`
- `missing_pipeline_slots()`
- `pipeline_status_for_result()`
- `build_pipeline_execution_result()`
- `run_core_pipeline()`

The output must contain:

- `route_type`
- `pipeline_id`
- `status`
- `required_slots`
- `resolved_slots`
- `missing_slots`
- `risk`
- `execution_guard`
- `external_effects`
- `steps`
- `writeback_targets`

- [x] **Step 4: Verify GREEN and inspect output content**

Run the tests from Step 2. Inspect that the output status and slot content are semantically reasonable, not merely present.

### Task 2: Add API And Validation Coverage

**Files:**
- Modify: `runtime_api/app/main.py`
- Modify: `scripts/validate-core-pipelines-openclaw.py`
- Test: `runtime_api/tests/test_core_pipeline_engine.py`
- Document: `docs/superpowers/specs/2026-05-28-implementation-gap-closure-design.md`

- [x] **Step 1: Write failing API test**

Add a test for `POST /api/pipelines/run` proving it returns a pipeline execution result and still enforces the password.

- [x] **Step 2: Run test to verify RED**

Run:

```bash
python3 -m pytest runtime_api/tests/test_core_pipeline_engine.py::test_pipeline_run_endpoint_returns_execution_contract -q
```

Expected: fail with `404`.

- [x] **Step 3: Implement endpoint and validation stage**

Add:

- `PipelineRunIn`
- `POST /api/pipelines/run`
- a `core_pipeline_engine_status_contract` stage in `scripts/validate-core-pipelines-openclaw.py`

- [x] **Step 4: Run regression**

Run:

```bash
python3 -m pytest -q
python3 scripts/validate-core-pipelines-openclaw.py
git diff --check
```

Expected: tests pass and validation output shows reasonable executable statuses for reply, route, ride, and payment ambiguity.
