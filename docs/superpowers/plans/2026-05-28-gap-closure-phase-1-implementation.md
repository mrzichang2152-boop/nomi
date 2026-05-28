# Gap Closure Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the first usable product gaps from `2026-05-28-implementation-gap-closure-design.md`: agenda APIs, suggestion action feedback, event/conversation trace APIs, and active agenda context packs.

**Architecture:** Keep the current single `runtime_api/app/main.py` pattern for this phase to avoid a broad router refactor while the repo is already changing. Add focused helper functions with tests first, then expose password-protected APIs that reuse existing agenda, suggestion, task-route, and chat-context tables.

**Tech Stack:** FastAPI, Pydantic, psycopg, pytest, existing runtime API helpers.

---

### Task 1: Agenda API Read, Correct, And Snooze

**Files:**
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_private_event_gap_closure.py`
- Document: `docs/superpowers/specs/2026-05-28-implementation-gap-closure-design.md`

- [x] **Step 1: Write failing agenda API tests**

Add tests for:

- `GET /api/agenda?certainty=fuzzy` returning only fuzzy agenda items with latest version metadata.
- `PATCH /api/agenda/{id}` updating title/place/status and writing an `agenda_item_versions` row with previous and new values.
- `POST /api/agenda/{id}/snooze` writing `metadata.snoozed_until` and a `snooze` version.

- [x] **Step 2: Run tests to verify RED**

Run:

```bash
python3 -m pytest runtime_api/tests/test_private_event_gap_closure.py::test_agenda_list_filters_fuzzy_items_with_latest_version runtime_api/tests/test_private_event_gap_closure.py::test_agenda_patch_writes_user_correction_version runtime_api/tests/test_private_event_gap_closure.py::test_agenda_snooze_updates_metadata_and_version -q
```

Expected: fail because the `/api/agenda` routes do not exist.

- [x] **Step 3: Implement agenda helpers and routes**

Add:

- `AgendaPatchIn`
- `AgendaSnoozeIn`
- `agenda_item_from_row()`
- `fetch_agenda_items()`
- `update_agenda_item_with_version()`
- `snooze_agenda_item_with_version()`
- `GET /api/agenda`
- `PATCH /api/agenda/{agenda_id}`
- `POST /api/agenda/{agenda_id}/snooze`

- [x] **Step 4: Verify GREEN and inspect response content**

Run the tests from Step 2. Inspect JSON assertions for title, certainty, missing fields, version operation, previous value, and snoozed time.

### Task 2: Suggestion Action Feedback And Pipeline Handoff

**Files:**
- Modify: `db/init.sql`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_private_event_gap_closure.py`
- Document: `docs/superpowers/specs/2026-05-28-implementation-gap-closure-design.md`

- [x] **Step 1: Write failing suggestion action tests**

Add tests for:

- schema bootstrap creates `user_feedback` and `proactive_candidates`.
- `POST /api/proactive/suggestions/{id}/action` records clicked action feedback.
- action `route_lookup` routes to `route_pipeline` and persists a route trace.
- action `ride_prepare` routes to `ride_pipeline` and requires final confirmation before booking.
- action `snooze` updates suggestion metadata/status without deleting evidence.

- [x] **Step 2: Run tests to verify RED**

Run:

```bash
python3 -m pytest runtime_api/tests/test_private_event_gap_closure.py::test_user_feedback_schema_bootstrap runtime_api/tests/test_private_event_gap_closure.py::test_suggestion_action_records_feedback_and_routes_to_pipeline -q
```

Expected: fail because action endpoint and feedback schema do not exist.

- [x] **Step 3: Implement feedback schema and action route**

Add:

- `ensure_proactive_feedback_schema()`
- `SuggestionActionIn`
- `record_user_feedback()`
- `fetch_suggestion_for_action()`
- `apply_suggestion_local_action()`
- `build_suggestion_action_route_request()`
- `POST /api/proactive/suggestions/{suggestion_id}/action`
- `GET /api/proactive/suggestions` alias for existing suggestions list

- [x] **Step 4: Verify GREEN and inspect route decision**

Run tests and ensure the route output contains the expected pipeline, confirmation gate, source suggestion id, and action id.

### Task 3: Event And Conversation Trace APIs

**Files:**
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_private_event_gap_closure.py`
- Document: `docs/superpowers/specs/2026-05-28-implementation-gap-closure-design.md`

- [x] **Step 1: Write failing trace API tests**

Add tests for:

- `GET /api/events/{id}/trace` returning event, semantic event, vector metadata, facts, agenda items, agenda versions, suggestions, and route traces.
- `GET /api/chat/conversations/{id}/trace` returning conversation row, turns, context snapshots, suggestions, and route traces.

- [x] **Step 2: Run tests to verify RED**

Run:

```bash
python3 -m pytest runtime_api/tests/test_private_event_gap_closure.py::test_event_trace_returns_connected_memory_agenda_suggestion_and_routes runtime_api/tests/test_private_event_gap_closure.py::test_conversation_trace_returns_turns_context_and_routes -q
```

Expected: fail because trace APIs do not exist.

- [x] **Step 3: Implement trace helpers and routes**

Add:

- `event_trace()`
- `conversation_trace()`
- row normalizers for each trace section
- password checks on both routes

- [x] **Step 4: Verify GREEN and inspect trace content**

Run tests and ensure source event ids and conversation ids are preserved in the response.

### Task 4: Active Agenda In Context Packs

**Files:**
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_context_pack_and_chat.py`
- Test: `runtime_api/tests/test_private_event_gap_closure.py`
- Document: `docs/superpowers/specs/2026-05-28-implementation-gap-closure-design.md`

- [x] **Step 1: Write failing active agenda context tests**

Add tests proving:

- active agenda items with matching participant/topic are included.
- unrelated agenda items are excluded.
- context snapshots record included agenda ids.

- [x] **Step 2: Run tests to verify RED**

Run:

```bash
python3 -m pytest runtime_api/tests/test_context_pack_and_chat.py::test_build_context_pack_includes_active_agenda_and_excludes_unrelated -q
```

Expected: fail because `build_context_pack()` does not include active agenda.

- [x] **Step 3: Implement active agenda retrieval and context-pack integration**

Add:

- `relevant_agenda_items()`
- `retrieve_active_agenda_context()`
- `agenda_context` field in `build_context_pack()`
- `included_agenda_ids` population
- context prompt rendering for active agenda items

- [x] **Step 4: Verify GREEN and inspect prompt content**

Run the test and inspect that the prompt contains the relevant fuzzy agenda but excludes unrelated agenda.

### Task 5: Phase 1 Regression Validation

**Files:**
- Modify: `scripts/validate-private-event-processing.py`
- Modify: `docs/superpowers/specs/2026-05-28-implementation-gap-closure-design.md`

- [x] **Step 1: Extend validation output**

Add printed stages for:

- agenda list output
- agenda correction version
- suggestion action feedback
- event trace
- conversation trace
- context pack with active agenda

- [x] **Step 2: Run phase regression**

Run:

```bash
python3 -m pytest -q
python3 scripts/validate-private-event-processing.py
python3 scripts/validate-core-pipelines-openclaw.py
bash scripts/validate-android-floating-ball.sh
git diff --check
```

Expected:

- all tests pass
- validation scripts print semantically reasonable stage outputs
- whitespace check passes

- [x] **Step 3: Mark Phase 1 status**

Update `2026-05-28-implementation-gap-closure-design.md` with a short "Phase 1 Implementation Status" section listing completed items and any remaining limitations.
