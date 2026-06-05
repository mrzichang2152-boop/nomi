# Long-Tail Agent Runtime V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the V2 long-tail agent runtime as a Nomi-owned graph runner with event-sourced trace, ActionRequest/PolicyGate enforcement, independent verification, durable checkpoints, and explicit gap tracking.

**Architecture:** Build a small Nomi-native runtime in `runtime_api/app/long_tail_agent.py` first, then connect it to existing routing, OpenClaw, Composio, Android/H5 delivery, and workflow distillation. The first implementation slice is deliberately foundational: event log source-of-truth, action schema, policy gate, verifier evidence rules, and schema SQL.

**Tech Stack:** Python, FastAPI runtime modules, Postgres schema SQL, pytest, existing runtime API patterns.

---

### Task 1: Event Source, ActionRequest, PolicyGate, And Evidence Verifier

**Files:**
- Create: `runtime_api/app/long_tail_agent.py`
- Create: `runtime_api/tests/test_long_tail_agent_runtime.py`
- Modify: `docs/superpowers/reports/2026-06-03-long-tail-agent-runtime-v2-gaps.md`

- [x] **Step 1: Write failing tests**

Tests must cover:

- append-only task events with monotonic sequence and idempotency reuse;
- derived state rebuilt from the event log;
- `ActionRequest` blocks `browser.submit` before execution;
- `ActionRequest` requires confirmation for `email.send`;
- safe `browser.fill_field` is allowed when it matches the step allowlist;
- verifier rejects executor output with no independent evidence;
- verifier accepts browser output with URL/title/field evidence;
- schema SQL includes V2 tables.

- [x] **Step 2: Run tests and confirm they fail for missing implementation**

Run:

```bash
python3 -m pytest runtime_api/tests/test_long_tail_agent_runtime.py -q
```

Expected: fails because `app.long_tail_agent` does not exist or required symbols are missing.

- [x] **Step 3: Implement minimal runtime primitives**

Implement:

- `LongTailEventStore`
- `ActionRequest`
- `PolicyGate`
- `StepVerifier`
- `long_tail_agent_schema_sql`

- [x] **Step 4: Run focused tests and inspect semantic output**

Run:

```bash
python3 -m pytest runtime_api/tests/test_long_tail_agent_runtime.py -q
```

Expected: all tests pass and assertions inspect actual policy/verifier decisions.

### Task 2: Graph Runner Skeleton

**Files:**
- Modify: `runtime_api/app/long_tail_agent.py`
- Modify: `runtime_api/tests/test_long_tail_agent_runtime.py`
- Modify: `docs/superpowers/reports/2026-06-03-long-tail-agent-runtime-v2-gaps.md`

- [x] Add `LongTailGraphRunner.create_task`.
- [x] Add planner/validator placeholders that produce structured events but do not call live tools.
- [x] Add one-step `run_next` that builds a step packet and stops before executor integration.
- [x] Verify event order and derived state.

### Task 3: Durable Human-In-The-Loop And External Effects

**Files:**
- Modify: `runtime_api/app/long_tail_agent.py`
- Modify: `runtime_api/tests/test_long_tail_agent_runtime.py`
- Modify: `docs/superpowers/reports/2026-06-03-long-tail-agent-runtime-v2-gaps.md`

- [x] Add external-effect state machine.
- [x] Add confirmation event requirement before execution.
- [x] Add compensation proposal semantics.
- [x] Recover external-effect state from task event log after controller-local memory is lost.
- [x] Expose external-effect propose/confirm/execute through password-protected API endpoints.
- [x] Verify rollback never claims third-party state reversal.
- [x] Return UI-ready rollback action cards and expose compensation proposal through API.

### Task 4: Adapter Boundary

**Files:**
- Modify: `runtime_api/app/long_tail_agent.py`
- Modify: `runtime_api/app/tool_registry.py`
- Modify: `runtime_api/tests/test_long_tail_agent_runtime.py`
- Modify: `runtime_api/tests/test_tool_registry.py`
- Modify: `docs/superpowers/reports/2026-06-03-long-tail-agent-runtime-v2-gaps.md`

- [x] Normalize OpenClaw, Composio, and browser adapter action proposals into `ActionRequest`.
- [x] Ensure adapters cannot execute before PolicyGate approval.
- [x] Persist provider/executor child trace ids in long-tail events for local adapter proposals.
- [x] Add adapter dry-run execution that records provider/executor child trace ids without live external effects.
- [ ] Persist provider/executor child trace ids from real live adapter executions.

### Task 5: API And Schema Integration

**Files:**
- Modify: `runtime_api/app/main.py`
- Modify: `runtime_api/tests/test_auth_and_model.py`
- Create or modify API tests for `/api/agent-tasks`.
- Modify: `docs/superpowers/reports/2026-06-03-long-tail-agent-runtime-v2-gaps.md`

- [x] Add schema bootstrap.
- [x] Add password-protected long-tail task endpoints.
- [x] Verify API responses include events, current node, final delivery state, resume recovery, human input, and confirmation events.
- [x] Verify route endpoint normalizes OpenClaw-style long-tail requests to `long_tail_agent` with top-level `capability_id`.
- [x] Verify pending-human-input UI payload shape.

### Task 6: Online Regression And Gap Closure

**Files:**
- Create: `scripts/validate-long-tail-agent-runtime-v2.py`
- Modify: `docs/superpowers/reports/2026-06-03-long-tail-agent-runtime-v2-gaps.md`

- [x] Add regression script that prints every intermediate artifact and a `reasonable` judgment.
- [x] Run local tests.
- [x] Add local restart recovery stage to the regression script.
- [x] Add human-input waiting/resolved stages to the regression script.
- [x] Add external-effect confirmation/execution stages to the regression script.
- [x] Add local API route/create/state/events mode to the regression script.
- [x] Add API external-effect state-machine mode to the regression script.
- [x] Add API rollback/compensation card mode to the regression script.
- [x] Add local V2 lease manager semantics for active/expired/released leases.
- [ ] Run online/server regression when deployment is requested.
- [x] Mark remaining gaps honestly in the gap report for this implementation pass.

### Task 7: Remaining Runtime Hardening

**Files:**
- Modify: `runtime_api/app/long_tail_agent.py`
- Modify: `runtime_api/app/main.py`
- Modify: `runtime_api/tests/test_long_tail_agent_runtime.py`
- Modify: `docs/superpowers/reports/2026-06-03-long-tail-agent-runtime-v2-gaps.md`

- [x] Recover graph state from event log after a local runner restart.
- [x] Continue an awaiting-executor step after recovery and verify its result.
- [x] Continue the next incomplete step after recovery from a completed checkpoint.
- [x] Persist long-tail events, plans, checkpoints, leases, action requests, policy reports, verifier reports, and external effects through Postgres operations.
- [x] Persist append-only long-tail task events through `PostgresLongTailEventStore`.
- [x] Select Postgres-backed event store from `main.py` for non-test DATABASE_URL values.
- [x] Persist task runs, plans, step packets, action requests, policy reports, and checkpoints through dedicated Postgres materialized tables.
- [x] Persist verifier reports, memory patches, human inputs, and external effects through dedicated Postgres materialized tables.
- [x] Persist leases through `long_tail_task_runs` lease fields.
- [x] Add recovery scanner for due or expired-lease graph tasks.
- [x] Wire recovery scanner into an actual background recovery loop outside test DB mode.
- [ ] Run online process-restart observation against deployed Postgres recovery loop.
- [x] Wire `recover_task` into `/api/agent-tasks/{task_id}/resume` for local event-store tasks.
- [ ] Wire `recover_task` into `/api/agent-tasks/{task_id}/resume` for persistent Postgres-backed tasks.
- [x] Add local adapter proposal trace capture for provider/executor child trace ids.
- [x] Add live adapter dry-run mode that records provider/executor child trace ids.
