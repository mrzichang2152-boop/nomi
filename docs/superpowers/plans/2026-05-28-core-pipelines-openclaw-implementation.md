# Core Pipelines and OpenClaw Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement the core Pipeline/OpenClaw task routing layer described in `docs/superpowers/specs/2026-05-28-core-pipelines-openclaw-design.md`.

**Architecture:** Keep Nomi as the owner of memory, context, risk, confirmation, and result review. Expand deterministic core pipelines in `runtime_api/app/main.py`, route unsupported long-tail tasks to `openclaw_tool`, and construct constrained OpenClaw task packets with minimized context and forbidden-action gates.

**Tech Stack:** FastAPI, Pydantic, pytest, local runtime API tests, static web UI.

---

### Task 1: Route Decision Schema And Compatibility

**Files:**
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_auth_and_model.py`

- [x] **Step 1: Write failing route decision tests**

Add tests proving that route responses expose a stable `task_route_decision`, preserve legacy `route_type`, and emit `openclaw_tool` for long-tail requests while keeping `legacy_route_type` for compatibility.

- [x] **Step 2: Verify tests fail**

Run: `python3 -m pytest runtime_api/tests/test_auth_and_model.py::test_tool_route_uses_openclaw_for_hubspot_with_legacy_compatibility runtime_api/tests/test_auth_and_model.py::test_tool_route_falls_back_to_openclaw_packet_for_unknown_site -q`

Expected: failures because `task_route_decision`, `legacy_route_type`, and `openclaw_task_packet` do not exist yet.

- [x] **Step 3: Implement route decision output**

Update `route_tool_request()` to return:

- `route_type`
- `legacy_route_type`
- `task_route_decision`
- `execution_guard`
- `routing_reason`

Use `openclaw_tool` for new long-tail routes and `long_tail_tool` only as compatibility metadata.

- [x] **Step 4: Verify tests pass**

Run the two tests from Step 2 again and inspect response fields for sensible route reasons and risk policies.

### Task 2: Expand Deterministic Core Pipeline Registry

**Files:**
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_auth_and_model.py`

- [x] **Step 1: Write failing registry coverage tests**

Add tests that assert the design's core pipelines exist: `event_ingestion_pipeline`, `memory_write_pipeline`, `context_pack_pipeline`, `personal_search_pipeline`, `chat_response_pipeline`, `reply_pipeline`, `email_pipeline`, `agenda_pipeline`, `task_todo_pipeline`, `proactive_suggestion_pipeline`, `route_pipeline`, `ride_pipeline`, `shopping_pipeline`, `payment_bill_pipeline`, `contact_relationship_pipeline`, `document_file_pipeline`, `account_login_pipeline`, and `governance_audit_pipeline`.

- [x] **Step 2: Verify tests fail**

Run: `python3 -m pytest runtime_api/tests/test_auth_and_model.py::test_core_pipeline_registry_matches_design_pipeline_set -q`

Expected: failure because the current registry only contains a subset and uses old names for some pipelines.

- [x] **Step 3: Implement the expanded registry**

Extend `capability_taxonomy()` and `core_pipeline_registry()` with stable pipeline metadata: `id`, `name`, `capability_id`, `steps`, `permission`, `required_slots`, `allowed_tools`, `forbidden_tools`, `writeback_targets`, and `external_effects`.

- [x] **Step 4: Verify tests pass**

Run the registry test and inspect that the pipeline list is not just present, but carries reasonable permissions and confirmation behavior.

### Task 3: OpenClaw Task Packet And Context Minimization

**Files:**
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_auth_and_model.py`

- [x] **Step 1: Write failing packet tests**

Add tests for an unknown website request with mixed context containing unrelated contact memory and sensitive raw text. Expected packet includes a minimal task goal, allowed actions, forbidden actions, max steps, stop-before gates, return schema, and redacted/minimized context.

- [x] **Step 2: Verify tests fail**

Run: `python3 -m pytest runtime_api/tests/test_auth_and_model.py::test_openclaw_packet_minimizes_context_and_forbids_external_effects -q`

Expected: failure because packet construction is not implemented.

- [x] **Step 3: Implement packet construction**

Add helpers:

- `openclaw_forbidden_actions(permission)`
- `openclaw_allowed_actions(capability)`
- `minimize_openclaw_context(context)`
- `build_openclaw_task_packet(request, capability, context, guard)`

The packet should keep only scoped, necessary fields and should not pass broad memory dumps to OpenClaw.

- [x] **Step 4: Verify tests pass**

Run the packet test and inspect the packet to ensure it is safe and useful, not merely present.

### Task 4: Ambiguity And Confirmation Gates

**Files:**
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_auth_and_model.py`

- [x] **Step 1: Write failing ambiguity tests**

Add tests for vague/high-risk requests such as `帮我处理一下这个客户` and ambiguous payment/booking requests. Expected route is `ask_user`, not OpenClaw, when ambiguity changes recipient, payment, booking, writeback, or external effects.

- [x] **Step 2: Verify tests fail**

Run: `python3 -m pytest runtime_api/tests/test_auth_and_model.py::test_ambiguous_external_effect_request_asks_user_before_openclaw -q`

Expected: failure because vague requests currently fall through to a generic route.

- [x] **Step 3: Implement ambiguity guard**

Add a small deterministic ambiguity classifier that blocks vague high-risk external actions before core pipeline or OpenClaw execution.

- [x] **Step 4: Verify tests pass**

Run the ambiguity test and inspect the response to ensure it asks for the missing recipient/action/effect instead of pretending it can proceed.

### Task 5: UI Route Display

**Files:**
- Modify: `runtime_api/app/static/app.js`

- [x] **Step 1: Add route display expectations through existing API behavior**

Use existing API response tests as the source of truth. No separate frontend unit test suite exists, so verify by code review and static output labels.

- [x] **Step 2: Update route result rendering**

Show `OpenClaw 长尾执行` for `openclaw_tool`, show `需要澄清` for `ask_user`, and show packet/guard summaries when present.

- [x] **Step 3: Verify static rendering logic**

Inspect `renderRouteResult()` output paths and run the runtime API tests to ensure response shape remains compatible.

### Task 6: Validation Script And Spec Gap Marking

**Files:**
- Create: `scripts/validate-core-pipelines-openclaw.py`
- Modify: `docs/superpowers/specs/2026-05-28-core-pipelines-openclaw-design.md`

- [x] **Step 1: Write validation script**

The script should call pure Python functions from `runtime_api/app/main.py` with sample requests and print structured stages covering core pipeline routing, OpenClaw fallback, ambiguity guard, confirmation gates, packet minimization, and registry coverage.

- [x] **Step 2: Run validation script**

Run: `python3 scripts/validate-core-pipelines-openclaw.py`

Expected: every stage reports `reasonable: true`, and each sample output includes a clear route reason.

- [x] **Step 3: Mark implementation status and gaps in the spec**

Append an implementation verification section to the design doc. Mark implemented items, partial items, and remaining gaps. The section must say what was actually verified, not only that tests passed.

- [x] **Step 4: Final regression**

Run:

```bash
python3 -m pytest runtime_api/tests/test_auth_and_model.py -q
python3 scripts/validate-core-pipelines-openclaw.py
python3 -m pytest -q
git diff --check
```

Expected: pytest passes, validation stages are reasonable, and diff check has no whitespace errors.

### Task 7: Trace Browsing And Explicit Sensitive Field Release

**Files:**
- Modify: `runtime_api/app/main.py`
- Modify: `runtime_api/app/static/index.html`
- Modify: `runtime_api/app/static/app.js`
- Modify: `runtime_api/app/static/styles.css`
- Test: `runtime_api/tests/test_auth_and_model.py`
- Validate: `scripts/validate-core-pipelines-openclaw.py`

- [x] **Step 1: Write failing route trace browsing test**

Add a test proving `GET /api/tools/route/traces` requires authorization, supports route type/capability/keyword filters, and returns OpenClaw packet plus minimized context summary.

- [x] **Step 2: Implement route trace browsing**

Add `fetch_task_route_traces()`, row normalization, and the password-protected route trace API. Render recent traces in the governance page so decisions are auditable from the workbench.

- [x] **Step 3: Write failing sensitive field release tests**

Add tests proving the release endpoint requires a password and that raw sensitive values enter OpenClaw packets only through an auditable `approved_sensitive_fields` release. Add regression coverage so phone numbers and timestamps do not pollute sensitivity explanations as payment amounts.

- [x] **Step 4: Implement field release flow**

Add `build_sensitive_field_release()`, approved-release extraction, packet context support, and a basic tools-page form that creates a release for the next route.

- [x] **Step 5: Extend validation script and spec gaps**

Validate trace filtering, packet auditability, explicit release metadata, narrow raw-value inclusion, and updated known gaps.

### Task 8: OpenClaw Execution Jobs, Events, And Retry Scheduling

**Files:**
- Modify: `runtime_api/app/main.py`
- Modify: `runtime_api/app/static/app.js`
- Test: `runtime_api/tests/test_auth_and_model.py`
- Validate: `scripts/validate-core-pipelines-openclaw.py`
- Document: `docs/superpowers/specs/2026-05-28-core-pipelines-openclaw-design.md`

- [x] **Step 1: Write failing execution-event and retry tests**

Add tests proving live OpenClaw responses normalize tool events, transient failures become `retry_scheduled`, and job enqueue writes both a job row and an initial event.

- [x] **Step 2: Implement job schema and enqueue API**

Add `openclaw_execution_jobs` and `openclaw_execution_events`, plus `POST /api/tools/openclaw/jobs`.

- [x] **Step 3: Implement run-once execution and status API**

Add `run_openclaw_execution_job_once()`, `GET /api/tools/openclaw/jobs/{job_id}`, and `POST /api/tools/openclaw/jobs/{job_id}/run-once`. Record attempt, tool, retry/completion/failure events.

- [x] **Step 4: Wire basic workbench controls**

Allow an OpenClaw route card to enqueue a job, manually run one attempt, and refresh events.

- [x] **Step 5: Extend validation and mark remaining gaps**

Validate event redaction, retry classification, job event sequence, and document that an automatic background job runner is still pending.

### Task 9: In-Process OpenClaw Background Runner

**Files:**
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_auth_and_model.py`
- Validate: `scripts/validate-core-pipelines-openclaw.py`
- Document: `docs/superpowers/specs/2026-05-28-core-pipelines-openclaw-design.md`

- [x] **Step 1: Write failing due-job pickup tests**

Add tests proving the runner selects only due `queued` / `retry_scheduled` jobs, uses `FOR UPDATE SKIP LOCKED`, and respects a bounded batch limit.

- [x] **Step 2: Implement due-job fetch and one-pass processor**

Add `fetch_due_openclaw_execution_job_ids()` and `process_due_openclaw_execution_jobs_once()` so the execution loop can be tested without sleeping.

- [x] **Step 3: Attach runner to app lifespan**

Start `openclaw_execution_job_runner_loop()` when `ENABLE_OPENCLAW_JOB_RUNNER=true`; make interval and batch size configurable.

- [x] **Step 4: Extend validation and gap notes**

Validate due-job pickup semantics and document that this is an in-process runner, not a separately supervised worker service.

### Task 10: OpenClaw Job Realtime Events

**Files:**
- Modify: `runtime_api/app/main.py`
- Modify: `runtime_api/app/static/app.js`
- Test: `runtime_api/tests/test_auth_and_model.py`
- Validate: `scripts/validate-core-pipelines-openclaw.py`
- Document: `docs/superpowers/specs/2026-05-28-core-pipelines-openclaw-design.md`

- [x] **Step 1: Write failing realtime publish tests**

Add tests proving `record_openclaw_execution_event()` publishes an `openclaw_job_event` to `REALTIME_CHANNEL` with redacted payloads, and that `run_openclaw_execution_job_once()` publishes attempt/tool/retry events.

- [x] **Step 2: Publish job events through existing realtime channel**

Add `publish_realtime_message_safely()` and wire job event recording, job enqueue, manual run-once, and background runner execution to publish realtime job-event messages.

- [x] **Step 3: Update workbench event handling**

Handle `openclaw_job_event` in the existing WebSocket client and update known OpenClaw job cards without requiring manual refresh.

- [x] **Step 4: Extend validation and gap notes**

Validate publish payload shape and redaction, then mark that realtime workbench updates are implemented while true upstream Gateway streaming remains pending.
