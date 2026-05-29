# 256K Context Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fixed-turn chat context with a server-side, token-aware, scope-aware context pack that can plan around a 256K model window.

**Architecture:** The runtime API owns context assembly through budget helpers in `runtime_api/app/main.py`. Android sends only current message plus a bounded local delta. Tests assert selected context content, exclusion reasons, token metadata, and short-reply behavior.

**Tech Stack:** FastAPI, Pydantic, pytest, Java Android unit tests, existing PostgreSQL/Redis abstractions.

---

### Task 1: Runtime Token Budget And Context Pack

**Files:**
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_context_pack_and_chat.py`

- [x] **Step 1: Add failing tests**

Add tests that verify:

- `build_context_pack` includes more than 8 relevant same-conversation turns when token budget allows.
- `build_context_pack` excludes unrelated contact-scoped candidates and records the exclusion.
- `build_context_pack` truncates oversized single items with a warning and source id.
- short replies prioritize the immediate prior assistant question.

- [x] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest runtime_api/tests/test_context_pack_and_chat.py -q
```

Expected before implementation: at least the new token-budget fields or exclusion/truncation assertions fail.

- [x] **Step 3: Implement runtime context helpers**

Add helpers for:

- conservative token estimation;
- per-item text truncation;
- candidate normalization;
- scope filtering;
- section packing;
- context snapshot metadata fields.

- [x] **Step 4: Run runtime tests and inspect output**

Run:

```bash
python3 -m pytest runtime_api/tests/test_context_pack_and_chat.py -q
```

Expected after implementation: all tests pass, and assertions confirm actual selected/excluded context is reasonable.

### Task 2: Chat API Client Delta And Dedupe

**Files:**
- Modify: `runtime_api/app/main.py`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/FloatingChatContext.java`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/FloatingBallService.java`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/AssistantApiClient.java`
- Test: `runtime_api/tests/test_context_pack_and_chat.py`
- Test: `android_app/app/src/test/java/com/par/assistant/android/FloatingChatContextTest.java`

- [x] **Step 1: Add failing tests**

Add tests that verify:

- the server accepts `client_context_delta`;
- the current user message is not duplicated into context when it also appears in the client delta;
- Android snapshots local context before adding the current user turn;
- Android caps local delta by token/character budget, not a fixed 8-turn count.

- [x] **Step 2: Run targeted tests and verify failure**

Run:

```bash
python3 -m pytest runtime_api/tests/test_context_pack_and_chat.py -q
cd android_app && JAVA_HOME=/opt/homebrew/Cellar/openjdk@17/17.0.19/libexec/openjdk.jdk/Contents/Home gradle :app:testDebugUnitTest --tests com.par.assistant.android.FloatingChatContextTest
```

- [x] **Step 3: Implement API and Android changes**

Rename the request payload concept from `client_context` to `client_context_delta`, keep backward compatibility for existing clients, and make Android snapshot before adding the current user turn.

- [x] **Step 4: Run targeted tests and inspect assertions**

Run the same targeted commands and confirm tests assert real payload shape and dedupe behavior.

### Task 3: Regression And Build Verification

**Files:**
- Runtime API and Android files touched above.

- [x] **Step 1: Run runtime regression**

Run:

```bash
python3 -m pytest runtime_api/tests/test_context_pack_and_chat.py runtime_api/tests/test_private_event_gap_closure.py -q
```

- [x] **Step 2: Run Android unit tests and build**

Run:

```bash
cd android_app && JAVA_HOME=/opt/homebrew/Cellar/openjdk@17/17.0.19/libexec/openjdk.jdk/Contents/Home gradle :app:testDebugUnitTest :app:assembleDebug
```

- [x] **Step 3: Inspect context output**

Use at least one chat test or smoke response to confirm:

- `context_pack.token_budget.input_used` exists;
- `context_pack.sections` includes same conversation and memory sections;
- `context_pack.excluded` records unrelated sensitive/context-mismatched sources;
- final answer for "需要" uses the prior Nomi question.

- [x] **Step 4: Commit**

Commit runtime, Android, test, and plan changes with a message that describes the context-budget implementation.

### Task 4: Gap Closure After Design Review

**Files:**
- Modify: `runtime_api/app/main.py`
- Modify: `runtime_api/tests/test_context_pack_and_chat.py`
- Modify: `runtime_api/tests/test_realtime_ws.py`
- Modify: `docs/superpowers/specs/2026-05-29-256k-context-budget-design.md`

- [x] **Step 1: Add failing tests for missing context-pack layers**

Added tests that verify `source_context`, `task_context`, `context_pack_id`, `retrieval_modes`, and `scope_filters_applied` are present and content-bearing, not just empty metadata.

- [x] **Step 2: Add failing test for chat request scope and answer trace**

Added an `/api/chat` test that verifies the endpoint derives request scope from `ui_state`, fetches a wider candidate set with that scope, includes source/task context, and persists a snapshot containing the final assistant answer id.

- [x] **Step 3: Implement the missing runtime behavior**

Implemented request-scope inference, UI source normalization, active task/suggestion retrieval, layered context sections, final answer trace writeback, and wider context candidates for chat/WebSocket paths.

- [x] **Step 4: Inspect a realistic context-pack sample**

Ran a local sample for an Alice WhatsApp reply with a pending quote-check pipeline and a Bob private memory. The output included Alice source/task/KV/graph/RAG context, excluded Bob with a `Different contact scope` reason, and recorded tokenizer fallback metadata.

- [x] **Step 5: Record residual limitations**

Updated the 256K design with implemented behavior and remaining limitations: conservative tokenizer, truncation instead of model summarization, heuristic scoring, client-provided current-source context, and pending online validation.
