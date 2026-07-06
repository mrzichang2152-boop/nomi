# Memory Recall Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the first production-safe slice of the memory recall routing design: structured route decisions, detailed memory-layer needs, better implicit-context routing, and explicit gap tracking.

**Architecture:** Keep the existing `/api/chat` integration compatible by extending `ChatContextRoute` instead of replacing it. Add detailed route fields and fetch limits while preserving old `needs_memory` and `memory` behavior. Use TDD on `runtime_api/tests/test_chat_router.py` and `runtime_api/tests/test_parallel_context_retrieval.py`.

**Tech Stack:** Python 3, FastAPI runtime modules, pytest.

---

### Task 1: Structured Route Decision

**Files:**
- Modify: `/Users/wrf/Documents/background/runtime_api/app/chat_router.py`
- Test: `/Users/wrf/Documents/background/runtime_api/tests/test_chat_router.py`

- [x] Add failing tests for:
  - implicit reference questions route to `memory_query` without hardcoded memory keywords.
  - short confirmations with pending action route to `action_confirmation`.
  - informational “帮我解释/什么是” questions stay `simple_chat`.
  - job questions route to `job_query` with source, RAG, graph, and tasks context.
  - route exposes detailed memory-layer flags and a serializable decision dict.
- [x] Run targeted tests and confirm the new tests fail for the missing behavior.
- [x] Extend `ChatContextRoute` with detailed fields while preserving old constructor compatibility.
- [x] Add `to_decision()` for trace/debug output.
- [x] Update `route_chat_context()` rules for implicit reference, pending action, job, relationship, and informational requests.
- [x] Run targeted tests and confirm all route tests pass.

### Task 2: Detailed Context Fetch Limits

**Files:**
- Modify: `/Users/wrf/Documents/background/runtime_api/app/chat_router.py`
- Test: `/Users/wrf/Documents/background/runtime_api/tests/test_chat_router.py`

- [x] Add failing tests for detailed limits:
  - `memory_kv`, `memory_graph`, `memory_rag`, and `timeline` are present.
  - simple chat keeps all long-term memory layer limits at zero.
  - relationship/job/task routes allocate appropriate detailed limits.
- [x] Run targeted tests and confirm failure.
- [x] Update `context_fetch_limits()` to emit detailed limits while preserving old `memory`.
- [x] Run targeted tests and confirm pass.

### Task 3: Parallel Retrieval Layer Trace Compatibility

**Files:**
- Modify: `/Users/wrf/Documents/background/runtime_api/app/context_parallel.py`
- Test: `/Users/wrf/Documents/background/runtime_api/tests/test_parallel_context_retrieval.py`

- [x] Add failing test proving detailed memory fetchers can run in parallel when supplied.
- [x] Run targeted test and confirm failure.
- [x] Extend `retrieve_chat_context_parallel()` to support optional `memory_kv`, `memory_graph`, `memory_rag`, and `timeline` fetchers while keeping the existing combined `memory` fetcher behavior.
- [x] Run targeted tests and confirm pass.

### Task 4: Gap Register

**Files:**
- Create: `/Users/wrf/Documents/background/docs/superpowers/reports/2026-06-28-memory-recall-routing-gaps.md`

- [x] Record what was implemented in this slice.
- [x] Record explicit gaps:
  - model-backed semantic router not yet wired.
  - DB-backed route trace table not yet added.
  - `main.py` still uses combined memory fetcher until retrievers are split.
  - online real-account regression not executed in this slice.
- [x] Re-check gap doc before final response.

### Task 5: Verification

**Files:**
- Test command scope:
  - `/Users/wrf/Documents/background/runtime_api/tests/test_chat_router.py`
  - `/Users/wrf/Documents/background/runtime_api/tests/test_parallel_context_retrieval.py`

- [x] Run targeted pytest commands.
- [x] Read failures/output carefully.
- [x] If targeted tests pass, run a broader runtime API subset if feasible.
- [x] Final response must state exact verification evidence and remaining gaps.
