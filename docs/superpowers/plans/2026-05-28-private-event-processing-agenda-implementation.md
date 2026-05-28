# Private Event Processing and Agenda Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement the first working slice of Nomi's private event processing design: user-Nomi dialogue memory, bounded context packs, agenda extraction, proactive action cards, and stage-level verification.

**Architecture:** Extend the existing PostgreSQL-backed runtime and worker instead of adding a new service. Runtime API stores direct Nomi chat turns as private events and builds context packs; worker persists semantic output into memory, agenda, vectors, facts, and proactive suggestions.

**Tech Stack:** FastAPI, psycopg, Redis streams/pubsub, pytest, PostgreSQL JSONB/vector tables, existing Qwen-compatible model client.

---

### Task 1: Schema for Dialogue, Context, and Agenda

**Files:**
- Modify: `db/init.sql`
- Modify: `runtime_api/app/main.py`
- Modify: `worker/app/worker.py`

- [x] **Step 1: Write failing schema tests**

Add tests that require `assistant_conversations`, `assistant_turns`, `context_snapshots`, `agenda_items`, and `agenda_item_versions` to be created by runtime schema bootstrap.

- [x] **Step 2: Run schema tests and verify failure**

Run: `pytest runtime_api/tests/test_context_pack_and_chat.py -q`
Expected: fail because schema bootstrap and helpers do not exist.

- [x] **Step 3: Implement schema helpers**

Add `ensure_assistant_context_schema()` in runtime and `ensure_agenda_schema()` in worker. Update `db/init.sql` with the same tables.

- [x] **Step 4: Run schema tests and inspect SQL**

Run: `pytest runtime_api/tests/test_context_pack_and_chat.py -q`
Expected: pass and assertions should confirm the expected table names and indexes are emitted.

### Task 2: Persist User-Nomi Chat Turns as Events and Memory Inputs

**Files:**
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_context_pack_and_chat.py`

- [x] **Step 1: Write failing API tests**

Test `/api/chat` stores the user turn before model generation, stores the assistant turn after final answer, queues both events to `events:raw`, and returns a `conversation_id`.

- [x] **Step 2: Run API tests and verify failure**

Run: `pytest runtime_api/tests/test_context_pack_and_chat.py -q`
Expected: fail because `/api/chat` currently only retrieves context and calls the model.

- [x] **Step 3: Implement chat turn persistence**

Add helpers to create or reuse an assistant conversation, insert protected/encrypted events with source `nomi_chat`, insert `assistant_turns`, and enqueue both turns for worker processing.

- [x] **Step 4: Run tests and inspect queued payloads**

Run: `pytest runtime_api/tests/test_context_pack_and_chat.py -q`
Expected: pass; queued payloads should include sanitized user and assistant text, role, conversation id, and source `nomi_chat`.

### Task 3: Build Bounded Context Packs

**Files:**
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_context_pack_and_chat.py`

- [x] **Step 1: Write failing context-pack tests**

Test relevant Nomi dialogue and user corrections are included, unrelated dialogue is excluded, and context snapshots record included ids and reason.

- [x] **Step 2: Run context-pack tests and verify failure**

Run: `pytest runtime_api/tests/test_context_pack_and_chat.py -q`
Expected: fail because there is no context-pack builder or snapshot writer.

- [x] **Step 3: Implement context-pack helpers**

Add `build_context_pack()`, `retrieve_assistant_dialogue_context()`, `persist_context_snapshot()`, and include the context pack in chat/model prompts and traces.

- [x] **Step 4: Run tests and inspect context output**

Run: `pytest runtime_api/tests/test_context_pack_and_chat.py -q`
Expected: pass; assertions should prove useful dialogue is present and unrelated dialogue is absent.

### Task 4: Agenda Extraction and Versioning

**Files:**
- Modify: `worker/app/worker.py`
- Test: `worker/tests/test_worker_semantics.py`

- [x] **Step 1: Write failing agenda tests**

Test exact meetings create exact agenda items, fuzzy plans create missing-field agenda items, and cancel/reschedule events update agenda versions.

- [x] **Step 2: Run agenda tests and verify failure**

Run: `pytest worker/tests/test_worker_semantics.py -q`
Expected: fail because agenda persistence does not exist.

- [x] **Step 3: Implement agenda resolver**

Add rule-based agenda extraction from semantic intent/entities/raw text, insert/update `agenda_items`, and append `agenda_item_versions` with evidence.

- [x] **Step 4: Run tests and inspect agenda params**

Run: `pytest worker/tests/test_worker_semantics.py -q`
Expected: pass; assertions should check actual title, certainty, missing fields, status, and evidence event id.

### Task 5: Proactive Suggestions With Action Buttons

**Files:**
- Modify: `worker/app/worker.py`
- Modify: `runtime_api/app/main.py`
- Test: `worker/tests/test_worker_semantics.py`
- Test: `runtime_api/tests/test_vector_and_suggestions.py`

- [x] **Step 1: Write failing suggestion tests**

Test travel/social plans produce `查路线`, `帮我打车`, `稍后提醒`; payment/email events produce reminder/source actions; realtime payload preserves actions.

- [x] **Step 2: Run tests and verify failure**

Run: `pytest worker/tests/test_worker_semantics.py runtime_api/tests/test_vector_and_suggestions.py -q`
Expected: fail because suggestion metadata does not include typed action cards.

- [x] **Step 3: Implement action-card metadata**

Extend suggestion metadata with action objects and expose them from REST and WebSocket responses.

- [x] **Step 4: Run tests and inspect suggestion payloads**

Run: `pytest worker/tests/test_worker_semantics.py runtime_api/tests/test_vector_and_suggestions.py -q`
Expected: pass; assertions should inspect labels, action ids, risk, and next-step routing.

### Task 6: Stage-Level Regression Evaluation

**Files:**
- Create: `scripts/validate-private-event-processing.py`
- Test: existing pytest suites

- [x] **Step 1: Write evaluation script**

Create a deterministic validation script that prints each stage output for sample Nomi chat, WhatsApp fuzzy plan, reschedule, cancellation, payment, and unrelated dialogue cases.

- [x] **Step 2: Run full verification**

Run: `pytest runtime_api/tests worker/tests -q`
Expected: all tests pass.

Run: `python scripts/validate-private-event-processing.py`
Expected: report should mark each stage as `reasonable: true` and print the evidence, context, agenda, and suggestion decisions.

