# Chat Context and Dialogue Memory Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 15-round chat context and 15-round batched long-term memory writeback for ordinary Nomi dialogue.

**Architecture:** Keep chat history persistence immediate in `assistant_turns`, but gate Redis long-term memory processing through deterministic `immediate/defer/batch` policy. Both `/api/chat` and WebSocket share the same router limits and persistence helper.

**Tech Stack:** FastAPI/Python runtime API, Postgres/Redis private event pipeline, Python worker, Android Java floating chat context, pytest, Gradle unit tests.

---

## Files

- Modify: `runtime_api/app/chat_router.py`
  - Increase dialogue fetch limits to 15 rounds for regular chat.
- Modify: `runtime_api/app/main.py`
  - Add schema columns/table.
  - Add deterministic immediate-signal classifier.
  - Add dialogue batch creation helper.
  - Add `memory_enqueue_policy` to `persist_assistant_turn`.
  - Expose `dialogue_memory_enqueue` in `/api/chat` and WebSocket context packs.
- Modify: `worker/app/worker.py`
  - Treat `nomi_chat/dialogue_batch` as a summarizable first-class event.
- Modify: `android_app/app/src/main/java/com/par/assistant/android/FloatingChatContext.java`
  - Keep/send up to 30 recent turns within character budget.
- Test: `runtime_api/tests/test_chat_router.py`
- Test: `runtime_api/tests/test_dialogue_memory_batching.py`
- Test: `runtime_api/tests/test_context_pack_and_chat.py`
- Test: `runtime_api/tests/test_realtime_ws.py`
- Test: `worker/tests/test_worker_semantics.py`
- Test: `android_app/app/src/test/java/com/par/assistant/android/FloatingChatContextTest.java`

## Tasks

### Task 1: Router Limits

- [x] Write failing tests asserting default simple chat and short replies fetch 30 turns, answer-format fetches 10 turns.
- [x] Run `PYTHONPATH=runtime_api python3 -m pytest runtime_api/tests/test_chat_router.py -q` and verify failure.
- [x] Update `context_fetch_limits`.
- [x] Re-run the router tests and verify pass.

Verification:

- Initial red test showed old limits (`dialogue=4/0/8`) still active.
- Final router verification: `10 passed in 0.03s`.
- Output reasonableness: regular and short-answer chats now fetch 30 turns; answer-format remains a smaller 10-turn low-latency path.

### Task 2: Dialogue Memory Schema and Policy

- [x] Write failing tests for ordinary turn defer, immediate memory signal, 14-round no batch, and 15th-round batch.
- [x] Run `PYTHONPATH=runtime_api python3 -m pytest runtime_api/tests/test_dialogue_memory_batching.py -q` and verify failure.
- [x] Add schema migration SQL in `ensure_assistant_context_schema`.
- [x] Add deterministic policy helpers.
- [x] Add batch creation helper.
- [x] Update `persist_assistant_turn`.
- [x] Re-run tests and verify pass.

Verification:

- Initial red test failed 7/7 because no dialogue memory policy or batch helper existed.
- Final dialogue batching verification: `7 passed in 0.47s`.
- Output reasonableness: ordinary dialogue is deferred; explicit memory/task/action signals enqueue immediately; exactly 15 complete user+assistant rounds produce one `nomi_chat/dialogue_batch` event.

### Task 3: Chat API and WebSocket Reporting

- [x] Write/update tests asserting `context_pack.dialogue_memory_enqueue` is returned.
- [x] Run runtime chat/WebSocket tests and verify failure.
- [x] Attach the persistence helper result to context packs.
- [x] Re-run runtime chat/WebSocket tests and verify pass.

Verification:

- Initial `/api/chat` test failed because the internal context pack had the field but the public response omitted it.
- Final focused runtime verification: `55 passed in 0.54s`.
- Output reasonableness: API and WebSocket responses now expose whether the turn was skipped, deferred, immediately enqueued, or batched.

### Task 4: Worker Dialogue Batch Semantics

- [x] Write failing worker tests for `nomi_chat/dialogue_batch`.
- [x] Run `PYTHONPATH=worker python3 -m pytest worker/tests/test_worker_semantics.py -q` and verify failure.
- [x] Update worker extraction path to summarize batch turns and suppress low-value chit-chat.
- [x] Re-run worker tests and verify pass.

Verification:

- Initial red test showed `dialogue_batch` was treated as ordinary `conversation_memory`.
- Final worker semantic verification: `76 passed in 0.19s`.
- Output reasonableness: batch events now summarize 30 turns locally, preserve the full readable turn text for vector/RAG, and avoid remote model calls for routine batch writeback.

### Task 5: Android Local Context

- [x] Write failing `FloatingChatContextTest` for 30-turn snapshot and character-budget truncation.
- [x] Run `gradle -p android_app testDebugUnitTest --tests com.par.assistant.android.FloatingChatContextTest` and verify failure.
- [x] Update `FloatingChatContext`.
- [x] Re-run Android test and verify pass.

Verification:

- Initial red test showed `snapshotDelta` had no turn cap when character budget was large.
- Final Android context verification: Gradle build successful, `FloatingChatContextTest` passed.
- Output reasonableness: Android now sends at most 30 local turns while still respecting character budget.

### Task 6: Regression Verification

- [x] Run focused runtime tests:
  `PYTHONPATH=runtime_api python3 -m pytest runtime_api/tests/test_chat_router.py runtime_api/tests/test_dialogue_memory_batching.py runtime_api/tests/test_context_pack_and_chat.py runtime_api/tests/test_realtime_ws.py -q`
- [x] Run focused worker tests:
  `PYTHONPATH=worker python3 -m pytest worker/tests/test_worker_semantics.py worker/tests/test_event_batcher.py -q`
- [x] Run focused Android tests:
  `gradle -p android_app testDebugUnitTest --tests com.par.assistant.android.FloatingChatContextTest --tests com.par.assistant.android.RealtimeClientTest`
- [x] Inspect outputs for correctness, not only exit status.

Verification:

- Runtime focused regression: `55 passed in 0.59s`.
- Worker focused regression: `80 passed in 0.28s`.
- Android focused regression: Gradle `BUILD SUCCESSFUL in 826ms`.
- Output reasonableness: runtime exposes 30-turn fetch limits and memory enqueue status; worker keeps dialogue batches local and searchable; Android sends at most 30 local turns.

## Gaps to Track During Implementation

- Online cloud regression is not part of this local implementation pass unless explicitly requested after tests pass.
- If existing fake DB cursor tests cannot simulate all SQL, add narrow helper-level tests rather than weakening production behavior.

No local implementation gap remains for this plan. Remaining optional next step: deploy to the cloud server and verify real Gmail/WhatsApp/Telegram injection plus Android true-device streaming chat latency.
