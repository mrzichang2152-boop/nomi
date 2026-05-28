# Nomi Implementation Gap Closure Design

**Status:** Draft for execution
**Date:** 2026-05-28
**Owner:** Nomi project

## Purpose

This document records the remaining implementation gaps found by comparing the current codebase against the product and architecture source documents. It is intentionally broader than `prd.md`: it also covers the private-event agenda design, the core-pipeline/OpenClaw design, Android floating-ball requirements, and the current implementation gap notes.

The goal is to make the unfinished work explicit, detailed, and testable. Each gap below includes:

- the source requirement
- the current code reality
- the target behavior
- the recommended implementation approach
- acceptance criteria that check real output quality, not only command success

## Source Documents

The following documents are the source of truth for this gap review:

- `prd.md`
- `prd-implementation-gaps.md`
- `android-floating-ball-requirements.md`
- `docs/superpowers/specs/2026-05-28-private-event-processing-agenda-design.md`
- `docs/superpowers/specs/2026-05-28-core-pipelines-openclaw-design.md`
- `docs/superpowers/plans/2026-05-28-private-event-processing-agenda-implementation.md`
- `docs/superpowers/plans/2026-05-28-core-pipelines-openclaw-implementation.md`

Current code evidence was checked mainly in:

- `runtime_api/app/main.py`
- `worker/app/worker.py`
- `chromium_runtime/app/runtime.py`
- `android_app/app/src/main/java/com/par/assistant/android/`
- `db/init.sql`
- `scripts/validate-private-event-processing.py`
- `scripts/validate-core-pipelines-openclaw.py`

## Current Verified Baseline

The current project is a working Nomi MVP with:

- private event ingestion into local storage and Redis
- protected local raw storage plus redacted model/queue payloads
- worker semantic extraction with rule plus model fallback
- KV/facts/entity graph/vector/timeline memory layers
- basic scoped retrieval and cross-contact leak filtering
- agenda item and agenda version persistence
- proactive suggestion cards and WebSocket delivery
- tool routing into core-pipeline route decisions or OpenClaw fallback
- constrained OpenClaw task packet, job records, retry state, and realtime job events
- Android floating ball, proactive bubble, WebView workbench, and account login entry

Recent verification commands:

```bash
python3 -m pytest -q
python3 scripts/validate-private-event-processing.py
python3 scripts/validate-core-pipelines-openclaw.py
bash scripts/validate-android-floating-ball.sh
```

Observed result at latest review time:

- `241 passed`
- core pipeline/OpenClaw validation produced 23 semantically reasonable stages
- private-event processing validation produced 16 semantically reasonable reports
- Android structure validation passed

This baseline is useful, but it is not the full target described by the source documents.

## Completion Standard

A gap is complete only when all of the following are true:

- The implementation exists in the production path, not only in a validation script.
- Unit and integration tests cover the intended behavior.
- A validation script or fixture prints stage outputs and marks unreasonable content as a failure.
- Sensitive data handling is checked at the actual boundary where data leaves local storage.
- User-facing behavior is verified where applicable, including Web UI or Android paths.
- The relevant source document or this gap document is updated with the verified status and any remaining limitations.

Command success is not enough. For example, an agenda test must inspect whether the title, operation, certainty, missing fields, evidence event ids, and proactive actions are semantically correct.

## Gap 1: Core Pipelines Are Routing Metadata, Not Execution State Machines

### Source Requirement

`2026-05-28-core-pipelines-openclaw-design.md` requires core high-frequency tasks to run through deterministic first-party pipelines. Each pipeline should expose required slots, resolved slots, missing slots, risk, confirmation gates, retry/fallback policy, structured outputs, writeback targets, and trace fields.

### Current Code Reality

`runtime_api/app/main.py` has:

- `core_pipeline_registry()`
- `route_tool_request()`
- task route traces
- OpenClaw fallback packet construction

The code can decide that a request should use `reply_pipeline`, `route_pipeline`, `ride_pipeline`, and so on. It does not yet execute these pipelines as state machines. There is no common `PipelineEngine`, no per-pipeline `run()` contract, no slot resolver, no typed pipeline status, and no result reviewer.

### Target

Core pipelines should become executable, testable units. Routing should produce a route decision, then a pipeline engine should run the selected pipeline until it reaches one of these states:

- `completed_read_only`
- `draft_ready`
- `needs_user_input`
- `confirmation_required`
- `blocked`
- `failed`

External-effect pipelines must stop before sending, booking, buying, paying, archiving, deleting, or writing to third-party systems.

### Recommended Approach

Create a focused pipeline module rather than expanding `runtime_api/app/main.py` further.

Recommended files:

- `runtime_api/app/pipelines/base.py`
- `runtime_api/app/pipelines/registry.py`
- `runtime_api/app/pipelines/engine.py`
- `runtime_api/app/pipelines/core.py`
- `runtime_api/tests/test_core_pipeline_engine.py`

Implementation shape:

1. Define `PipelineInput`, `PipelineResult`, `SlotState`, `RiskState`, and `PipelineTrace`.
2. Move registry metadata into `pipelines/registry.py`.
3. Implement a small `PipelineEngine` that:
   - loads the pipeline definition
   - resolves slots from request, context pack, active agenda, and current UI state
   - computes missing slots
   - applies confirmation gates
   - calls only allowed read/draft/internal-write operations
   - records trace rows
4. Implement initial executable pipelines:
   - `personal_search_pipeline`
   - `chat_response_pipeline`
   - `agenda_pipeline`
   - `task_todo_pipeline`
   - `proactive_suggestion_pipeline`
   - `route_pipeline` as read-only prepare/estimate
   - `ride_pipeline` as prepare-only until final confirmation
   - `reply_pipeline` as draft-only until final confirmation
5. Keep OpenClaw fallback behind the same result reviewer and confirmation gates.

### Acceptance Criteria

- `帮我回复 Alice，说周五八点可以` returns a `reply_pipeline` result with a draft, target contact, channel, and `confirmation_required=true`.
- `查一下去武康路要多久` returns a `route_pipeline` result with read-only route intent and no final confirmation.
- `帮我打车去武康路` returns a `ride_pipeline` result with destination resolved, pickup missing if unavailable, and no booking.
- `帮我付款` returns `needs_user_input` with missing amount and counterparty.
- Every pipeline result stores a trace with route type, pipeline id, required slots, resolved slots, missing slots, risk, source evidence ids, and writeback status.
- Tests assert actual result content, not only status codes.

## Gap 2: Private Event APIs Are Incomplete

### Source Requirement

`2026-05-28-private-event-processing-agenda-design.md` defines API surfaces for agenda, proactive suggestions, event traces, chat messages, conversation traces, and tool routing.

### Current Code Reality

Current runtime routes include:

- `/event`
- `/api/chat`
- `/api/suggestions`
- `/api/tools/route`
- `/api/tools/route/traces`
- `/api/tools/openclaw/*`

Missing or incomplete routes:

- `GET /api/agenda`
- `PATCH /api/agenda/{id}`
- `POST /api/agenda/{id}/snooze`
- `GET /api/proactive/suggestions`
- `POST /api/proactive/suggestions/{id}/action`
- `GET /api/events/{id}/trace`
- `POST /api/chat/messages`
- `GET /api/chat/conversations/{id}/trace`

### Target

The UI, Android app, and future tool layer should use explicit APIs rather than relying on internal tables or generic status updates.

### Recommended Approach

Add a private-event API layer:

- `runtime_api/app/private_events_api.py`
- `runtime_api/app/agenda_api.py`
- `runtime_api/app/suggestions_api.py`
- `runtime_api/app/traces_api.py`

Keep route registration in `main.py` if the project does not yet split routers, but move pure logic into focused helpers.

Implementation details:

1. `GET /api/agenda`
   - filters: `status`, `certainty`, `source`, `from`, `to`, `limit`
   - returns agenda item plus latest version metadata.
2. `PATCH /api/agenda/{id}`
   - supports user corrections for title, time window, place, participants, status, missing fields, and note.
   - writes an `agenda_item_versions` record with operation `user_correction`.
3. `POST /api/agenda/{id}/snooze`
   - updates metadata with `snoozed_until`
   - writes a version record with operation `snooze`.
4. `POST /api/proactive/suggestions/{id}/action`
   - records the exact action clicked.
   - for local actions, updates suggestion/agenda state.
   - for tool actions, hands off to the pipeline router.
5. `GET /api/events/{id}/trace`
   - returns event, semantic event, memory vector metadata, facts, relationships, agenda versions, suggestions, and task route traces connected to the event.
6. `GET /api/chat/conversations/{id}/trace`
   - returns turns, context snapshots, referenced memory ids, agenda ids, suggestion ids, and tool traces.

### Acceptance Criteria

- A fuzzy WhatsApp plan appears in `GET /api/agenda?certainty=fuzzy`.
- Patching an agenda item creates a version record with previous and new values.
- Snoozing a fuzzy plan updates metadata and suppresses duplicate immediate proactive suggestions.
- Clicking `查路线` returns a route pipeline handoff, not just a suggestion status update.
- `GET /api/events/{id}/trace` explains why a suggestion or agenda item exists.

## Gap 3: Agenda Lifecycle Is Partial

### Source Requirement

The agenda design requires create, update details, reschedule, cancel, merge duplicates, mark complete, lower confidence, and request clarification. Every change must write an `agenda_item_version`.

### Current Code Reality

`worker/app/worker.py` can:

- create agenda candidates
- detect simple cancel/reschedule text
- persist agenda items
- write agenda versions
- preserve fuzzy missing fields
- reject unsupported exact time from model output

The lifecycle is still incomplete:

- no explicit merge operation
- no completion detection beyond basic labels
- no confidence decay or lower-confidence path
- no clarification request queue
- no agenda conflict detector
- no notification planner
- no user-facing agenda correction API

### Target

Agenda should behave like Nomi's internal dynamic schedule, not just an extracted event table.

### Recommended Approach

Add an agenda resolver module:

- `worker/app/agenda/resolver.py`
- `worker/app/agenda/lifecycle.py`
- `worker/app/agenda/conflicts.py`
- `worker/tests/test_agenda_lifecycle.py`

Core operations:

- `create`
- `update`
- `reschedule`
- `cancel`
- `merge`
- `complete`
- `lower_confidence`
- `request_clarification`

Implementation details:

1. Keep the hybrid model plus rules parser.
2. Add operation-specific validators.
3. Add a dedupe resolver that compares source account, thread/conversation, participants, type, time window, and place.
4. Add completion rules:
   - "已经搞定", "完成了", "paid", "done", "已经见完"
5. Add lower-confidence rules:
   - source conflict
   - model unsupported field
   - ambiguous actor or participant
6. Add clarification metadata:
   - `clarification_reason`
   - `recommended_question`
   - `recommended_next_check`
7. Add conflict detector:
   - overlapping exact events
   - high-priority deadline collision
   - travel time warning when route context exists

### Acceptance Criteria

- Exact meeting creates exact agenda with no invented missing fields.
- Fuzzy plan creates fuzzy agenda with `exact_time` and/or `exact_place`.
- Reschedule updates the existing item rather than creating an unrelated item.
- Cancel marks the right item canceled.
- Completion marks the item completed and writes a version.
- Duplicate fuzzy plans merge only when participant/thread/topic evidence supports it.
- Ambiguous updates create a clarification suggestion instead of silently overwriting.

## Gap 4: Context Pack Does Not Include Active Agenda And Active Tasks

### Source Requirement

Context packs should include current event, recent relevant Nomi dialogue, active agenda items, active tasks, active suggestions, user preferences, corrections, scoped KV/graph/RAG memory, and current UI/session state.

### Current Code Reality

`build_context_pack()` includes:

- current query
- memory context
- selected assistant dialogue
- source event ids

But `included_agenda_ids` is currently empty, and active task/suggestion context is not loaded into the context pack.

### Target

Ambiguous private events should be judged with the user's active agenda and Nomi conversation context.

### Recommended Approach

Create a context-pack builder module:

- `runtime_api/app/context_pack.py`
- `runtime_api/tests/test_context_pack_agenda.py`

Implementation details:

1. Add `retrieve_active_agenda_context()`.
2. Add `retrieve_active_suggestion_context()`.
3. Add `retrieve_active_task_trace_context()`.
4. Add context budget rules:
   - same conversation/thread first
   - same counterparty next
   - same topic next
   - global preferences only when relevant
5. Add conflict behavior:
   - if current evidence conflicts with prior Nomi conversation, lower confidence and add clarification reason.

### Acceptance Criteria

- If the user previously told Nomi "盯一下周末和 Alex 见面", a later WhatsApp "那就周日吧" includes that active agenda in the context pack.
- If a different unrelated Nomi conversation mentions Alex, it is excluded.
- Context snapshot stores included agenda ids and reason.
- Validation output prints context sections and flags unrelated context as unreasonable.

## Gap 5: Event Processing Is Still Mostly Serial

### Source Requirement

After ledger append, the following processors should run independently where possible:

- memory ingestion
- sensitivity classification
- dedupe and identity resolution
- embedding/search indexing
- event understanding
- conversation-context indexing
- source health update

After event understanding:

- agenda resolver
- relationship/contact updater
- long-term memory candidate writer
- proactive candidate builder
- tool intent candidate builder

### Current Code Reality

The worker main loop reads Redis stream entries and performs masking, semantic extraction, persistence, vector write, agenda write, suggestion write, and timeline write in a serial path.

### Target

The system should still be simple enough for a single-user 4C/8G server, but the processing stages should be explicit, retryable, and independently testable.

### Recommended Approach

Do not introduce heavyweight distributed infrastructure yet. Use a stage-oriented worker inside the existing worker service.

Recommended files:

- `worker/app/pipeline/stages.py`
- `worker/app/pipeline/orchestrator.py`
- `worker/app/pipeline/traces.py`
- `worker/tests/test_event_pipeline_orchestrator.py`

Implementation details:

1. Create an `EventProcessingContext` object.
2. Split current `persist_semantics()` side effects into named stages:
   - `write_semantic_event`
   - `write_fact_graph_state`
   - `write_vector_index`
   - `resolve_agenda`
   - `build_proactive_candidate`
   - `publish_realtime_if_visible`
   - `write_timeline_event`
3. Run cheap local stages in parallel with `asyncio.gather()` or an internal executor.
4. Keep model calls bounded and serial per event unless concurrency limits are configured.
5. Store stage results and errors in a trace table or event metadata.
6. Add low-value event fast path to avoid calling the model for noisy network/focus events.

### Acceptance Criteria

- A single event trace shows every stage, status, duration, and output summary.
- If vector indexing fails, semantic event and agenda can still persist with a retry marker for vector stage.
- Low-value network events do not block high-priority WhatsApp/Gmail events.
- Validation output shows stage outputs, not only final success.

## Gap 6: Proactive Suggestions Need Candidate, Feedback, And Action Handoff

### Source Requirement

The proactive system should create candidates, score them, surface only useful suggestions, show action cards, and record user responses such as completed, dismissed, ignored, snoozed, or clicked.

### Current Code Reality

`worker/app/worker.py` directly writes `proactive_suggestions`. Actions are included in metadata. Runtime can list suggestions and update status to `open`, `done`, or `dismissed`.

Missing:

- `proactive_candidates` table
- `user_feedback` table
- score breakdown
- cooldown history by candidate
- quiet hours
- suggestion action endpoint
- click-to-pipeline handoff
- feedback learning

### Target

Proactive suggestions should be explainable and controllable. Nomi should know why it interrupted the user, what the user did with the suggestion, and whether future similar suggestions should be suppressed.

### Recommended Approach

Add candidate and feedback persistence:

- `proactive_candidates`
- `user_feedback`
- `suggestion_actions`

Implementation details:

1. Worker creates a candidate first with score components:
   - urgency
   - importance
   - actionability
   - confidence
   - interruption cost
   - cooldown
   - quiet hours
   - feedback history
2. Runtime exposes `POST /api/proactive/suggestions/{id}/action`.
3. Action routing:
   - `route_lookup` goes to `route_pipeline`
   - `ride_prepare` goes to `ride_pipeline`
   - `snooze` updates suggestion and agenda metadata
   - `dismiss` writes feedback and suppresses duplicates
   - `open_source` returns source event trace or remote browser hint
4. Android bubble should preserve actions and let the user choose the most likely next action without opening a full page when possible.

### Acceptance Criteria

- A travel-like WhatsApp plan creates one candidate, one visible suggestion, and actions `查路线`, `帮我打车`, `稍后提醒`.
- A duplicate message within cooldown updates the existing candidate or suppresses visibility.
- Clicking `忽略` writes `user_feedback`.
- Clicking `查路线` produces a task route trace for `route_pipeline`.
- Clicking `帮我打车` prepares a ride request and stops before booking.

## Gap 7: Scoped Retrieval And Identity Isolation Are Still Heuristic

### Source Requirement

The memory system must prevent cross-contact leakage. Every memory item should carry source account, conversation id, assistant session id, active task id, suggestion id, counterparty ids, topic ids, visibility scope, and sensitivity level.

### Current Code Reality

The worker writes a `memory_scope` into vector metadata and relationship metadata. Runtime filters some third-party private negative context before reply generation. The policy is inferred mostly from user text and available raw metadata.

Missing:

- stable contact ids
- source account ids
- explicit counterparty ids from collectors
- full conversation/thread ids for WhatsApp/Gmail
- old data backfill
- retrieval-time scope requirements for every API
- complete handling of `private_third_party`, `thread_scoped`, and `topic_scoped`

### Target

Nomi should be able to answer within the right social boundary. In a conversation with contact A, it should not accidentally use contact B's private negative opinion about A.

### Recommended Approach

Add identity and scope services:

- `runtime_api/app/memory_scope.py`
- `worker/app/identity_resolution.py`
- `worker/app/scope_writer.py`
- `scripts/backfill-memory-scope.py`

Implementation details:

1. Define normalized scope schema:
   - `source_type`
   - `source_account_id`
   - `conversation_id`
   - `thread_id`
   - `assistant_session_id`
   - `active_task_id`
   - `suggestion_id`
   - `counterparty_ids`
   - `topic_ids`
   - `visibility_scope`
   - `sensitivity_level`
2. Update collectors to pass best-effort source/account/thread/contact metadata.
3. Add a contact/entity resolver:
   - alias map
   - canonical contact names
   - source-specific ids when available
   - user corrections
4. Enforce retrieval policies in:
   - `/api/chat`
   - `/search`
   - `/api/tools/route`
   - proactive suggestion generation
   - pipeline context pack
5. Add backfill for existing memory vectors and facts.

### Acceptance Criteria

- `帮我回复 Alice` excludes Bob's private complaint about Alice.
- `帮我分析 Alice 和 Bob 的关系` may include cross-contact evidence because the user explicitly asked for analysis.
- Global user preferences remain available across conversations.
- A user correction "不是公司 Alex，是健身房 Alex" changes later entity resolution.
- Every returned context item includes scope and a reason why it was allowed.

## Gap 8: OpenClaw Execution Needs Production-Grade Boundaries

### Source Requirement

OpenClaw should be a controlled long-tail executor. Nomi keeps memory ownership, risk checks, confirmation, result review, and writeback.

### Current Code Reality

Implemented:

- constrained packet
- context minimization
- explicit sensitive field release
- dry-run/live adapter
- jobs and events
- retry scheduling
- realtime job events

Missing:

- true upstream streaming while Gateway is still running
- independent worker service
- result reviewer before user display/writeback
- writeback of final task outcome into memory, agenda, and conversation
- promotion analytics for repeated OpenClaw tasks
- robust provider abstraction beyond the OpenResponses-compatible call

### Target

OpenClaw should be safe to use as a long-tail tool without becoming the assistant's brain or receiving broad memory access.

### Recommended Approach

Implementation phases:

1. Add `OpenClawResultReviewer`.
   - Validates schema.
   - Checks forbidden action boundary.
   - Summarizes raw logs into user-safe output.
   - Flags `verification_failed` if output does not match expected status.
2. Move job runner to a separate worker process option.
   - Keep in-process runner for simple single-user deployment.
   - Add separate `openclaw-worker` service in Docker Compose as an optional profile.
3. Add streaming adapter.
   - Support SSE or chunked response if Gateway provides it.
   - Persist tool events as they arrive.
4. Add result writeback.
   - Write task outcome to assistant turns.
   - Update agenda/task state when relevant.
   - Write user feedback after confirmation/cancel.
5. Add promotion analytics.
   - Count repeated route types and tasks.
   - Suggest promotion when a long-tail workflow repeats and has stable slots.

### Acceptance Criteria

- Gateway events appear in workbench while the job is still running, not only after the adapter returns.
- A result containing forbidden action evidence is blocked before display.
- A completed OpenClaw job writes a task outcome trace.
- Failed OpenClaw jobs produce a short user-safe explanation and next safe step.
- Repeated HubSpot or spreadsheet tasks are counted as promotion candidates, but still route through OpenClaw until promoted.

## Gap 9: Composio And Long-Tail Tool Selection Are Only Status-Level

### Source Requirement

The product direction says high-frequency tasks use deterministic pipelines, while long-tail tasks can use OpenClaw. Composio/Zapier/MCP catalog can be used as provider/tool inventory, but Nomi must choose the task path first.

### Current Code Reality

`/api/tools/composio/status` checks whether Composio is configured and reachable. The tool catalog includes many suggested adapters, but there is no full Composio catalog import, classification, per-tool schema storage, or actual Composio tool execution path.

### Target

Nomi should:

1. Match high-frequency intents to core pipelines.
2. For unsupported long-tail tasks, choose an OpenClaw or provider-backed tool path.
3. Use Composio catalog metadata as tool inventory, not as the top-level router.

### Recommended Approach

Add a tool inventory layer:

- `runtime_api/app/tools/catalog_importer.py`
- `runtime_api/app/tools/tool_classifier.py`
- `runtime_api/app/tools/provider_router.py`
- `runtime_api/tests/test_tool_inventory.py`

Implementation details:

1. Import Composio MCP/tools list into local storage.
2. Classify tools into a 3-4 level taxonomy:
   - domain
   - object
   - action
   - external-effect risk
3. Attach tool schemas and required auth state.
4. Route:
   - core capability matched: use core pipeline
   - unsupported provider task with a clear tool: use provider adapter through OpenClaw or direct provider wrapper
   - unknown browser workflow: use OpenClaw browser execution
   - high-risk ambiguous task: ask user
5. Keep confirmation gates identical across Composio, Zapier, MCP, and OpenClaw.

### Acceptance Criteria

- `帮我给客户补 HubSpot 备注` initially routes to OpenClaw/provider long-tail with confirmation.
- `帮我回复 Alice` does not route directly to a messaging MCP; it routes to `reply_pipeline`.
- Tool schemas are stored locally with provider, auth state, risk, and allowed actions.
- A missing-provider-auth route returns a login/connect action, not a broken tool call.

## Gap 10: Collector Runtime Is Functional But Not PRD-Complete

### Source Requirement

`prd.md` requires Managed Chromium Runtime with persistent sessions, DOM injection, WebSocket hook, network hook, crash restart, collector health, degraded mode, and reliable automatic semantic event collection.

### Current Code Reality

Implemented:

- Playwright managed runtime
- collector settings
- page recovery
- DOM injection for WhatsApp
- network metadata hook
- focus hook
- collector health and degraded details
- Gmail visible inbox/thread parsing
- WhatsApp visible chat/history/current observer parsing
- Calendar visible event parsing
- Telegram visible preview parsing
- Bookmark file parsing

Limitations:

- WebSocket hook records open/close metadata, not protocol payloads.
- WhatsApp still lacks internal conversation/message ids and full history traversal.
- Gmail still lacks internal thread/message ids, star/importance/category, and attachment content.
- Calendar lacks API-level event id, participants beyond visible UI, reminders, and full month/history sync.
- Telegram lacks full conversation open/history sync.
- Bookmark collector is periodic file read, not a change listener.
- Degraded DOM snapshots are not persisted as independent diagnostic events.
- HTTPS/TLS deployment remains missing.

### Target

Collectors should be reliable enough for the product promise while still avoiding invasive screen recording or keyboard logging.

### Recommended Approach

Prioritize collector improvements by user value:

1. Gmail thread id and source metadata
2. WhatsApp conversation/message identity best effort
3. Calendar API or deeper visible sync
4. Degraded diagnostic events
5. Noise reduction for network/focus events
6. HTTPS/TLS deployment

Implementation details:

- Keep DOM-based collection as primary.
- Treat protocol/WebSocket payload capture as optional and high-risk. Do not enable raw protocol payload capture by default.
- Add stable source metadata wherever page UI or URL can provide it.
- Store collector diagnostic events for parser failures.
- Add per-source quality metrics:
  - last successful parse
  - degraded count
  - event count per hour
  - parser version

### Acceptance Criteria

- Gmail open-thread event includes stable best-effort thread/source id when visible or derivable.
- WhatsApp event includes stable conversation label and source metadata and never mixes two open conversations.
- Calendar visible event includes participants/location when visible and marks missing fields explicitly.
- Degraded parser failure creates a diagnostic event with safe DOM sample.
- Collector status page shows quality trend, not only latest health.

## Gap 11: Android Client Still Has Product And Security Gaps

### Source Requirement

`android-floating-ball-requirements.md` requires Android as a mobile entrance and proactive message display layer. The user also requested:

- default should be only a floating Nomi avatar
- tap opens a compact chat panel
- full workbench opens via icon and can close while floating ball remains
- login accounts should live in settings
- proactive messages should appear as bubbles
- workbench chat should stream

### Current Code Reality

Implemented:

- floating Nomi avatar
- closeable compact panel
- settings entry for account login
- noVNC remote browser entry
- WebSocket proactive message client
- proactive bubble
- WebView workbench with close button

Limitations:

- compact native panel chat uses REST `/api/chat`, not WebSocket streaming.
- proactive bubble does not expose quick actions such as `查路线`, `帮我打车`, `稍后提醒`.
- suggestion polling fallback still exists, but user preference is WebSocket-first.
- password is stored in `SharedPreferences`, not Android Keystore or encrypted preferences.
- settings page lacks quiet mode, notification toggle, reconnect strategy control, and proactive-message toggle.
- native UI tests are thin; most Android checks are structural or manual.

### Target

Android should feel like a polished lightweight Nomi companion, not a rough remote-control shell.

### Recommended Approach

Implementation phases:

1. Native chat streaming
   - Reuse WebSocket `/ws`.
   - Send `chat_message` from native panel.
   - Append `chat_delta` chunks to the current Nomi message.
2. Proactive bubble quick actions
   - Parse `actions` from realtime payload.
   - Show one or two compact action chips in the bubble or panel.
   - Route action clicks to `/api/proactive/suggestions/{id}/action`.
3. Secure config
   - Use AndroidX Security `EncryptedSharedPreferences` when available.
   - Fall back to SharedPreferences only for emulator/dev if dependency is unavailable.
4. Settings page
   - proactive message toggle
   - system notification toggle
   - quiet hours
   - reconnect backoff display
5. Tests
   - core unit tests for WebSocket message parsing
   - Robolectric or instrumentation tests for close behavior if the project adds Android test dependencies

### Acceptance Criteria

- Native compact panel streams Nomi responses token by token.
- A proactive travel bubble can show `查路线` and `帮我打车`.
- Closing the full workbench leaves the floating avatar visible.
- Password is encrypted at rest on Android when the platform supports it.
- Quiet mode suppresses bubbles/notifications but keeps the WebSocket connected.

## Gap 12: Result Writeback And Governance Are Incomplete

### Source Requirement

Both core-pipeline and private-event designs require final task outcomes, confirmations, dismissals, corrections, tool calls, and writebacks to become memory-backed events.

### Current Code Reality

Implemented:

- assistant turns become `nomi_chat` events
- memory correction writes `memory_audit_log`
- task route traces exist
- OpenClaw job events exist

Missing:

- suggestion action feedback as events
- tool confirmation/cancel/complete as events
- final task outcomes as assistant turns or task history
- deletion audit beyond partial governance actions
- unified trace page for memory, agenda, suggestions, and tool decisions

### Target

Nomi should remember what it did, what it asked, what the user chose, and whether the task succeeded.

### Recommended Approach

Add a governance writeback contract:

- `TaskOutcome`
- `UserDecision`
- `SuggestionFeedback`
- `ToolCallTrace`
- `MemoryCorrectionTrace`

Implementation details:

1. Every external-effect confirmation creates a `user_decision` event.
2. Every tool execution creates a `tool_call` event with safe summary and local trace id.
3. Every task final result creates a `task_outcome` event.
4. Every dismissal/snooze creates `user_feedback`.
5. Trace APIs aggregate all related artifacts by event id, suggestion id, task id, or conversation id.

### Acceptance Criteria

- If the user clicks `帮我打车` then cancels at confirmation, Nomi stores that cancellation.
- If a suggestion is dismissed, later similar suggestions are suppressed or scored lower.
- A task trace shows route decision, confirmation, tool result, final outcome, and memory writeback.

## Gap 13: Model Router And Privacy Boundaries Need Operational Hardening

### Source Requirement

`prd.md` requires local raw storage, desensitization before model requests, model-router service, model output versioning, and reliable degradation when external APIs fail.

### Current Code Reality

Implemented:

- rule-based redaction
- local encrypted raw payload
- model-router service
- model version field in semantic output
- Qwen-compatible model client

Limitations:

- DLP remains regex/rule based.
- model-router has no circuit breaker, retry queue, cost tracking, or quality feedback.
- high-sensitivity raw model approval path is not fully user-facing.
- model failure handling varies by path.

### Target

Model calls should be observable, bounded, and safe enough for private assistant workloads.

### Recommended Approach

1. Add model call ledger:
   - task
   - model
   - redaction summary
   - token estimate if available
   - latency
   - status
   - error
2. Add circuit breaker:
   - stop sending after repeated failures
   - keep events pending or rules-only
3. Add quality feedback:
   - parser warnings
   - user corrections
   - validation failures
4. Add high-sensitivity approval policy:
   - local-only default for critical data
   - explicit release when raw value is required

### Acceptance Criteria

- A model outage leaves events in rules-fallback or pending state with trace.
- A sensitive Gmail event does not send raw code/token/account data to model.
- Model call ledger can answer which model saw what type of redacted context.

## Gap 14: Deployment And Ops Are Still MVP-Level

### Source Requirement

`prd.md` expects private-cloud deployment with Docker, persistence, health checks, and public access hardening.

### Current Code Reality

Implemented:

- Docker Compose services
- Postgres/Redis/runtime/worker/model-router shape
- local dev and cloud validation paths

Limitations:

- HTTPS/TLS is missing.
- OpenClaw worker is not a separate supervised service.
- daily maintenance runs in runtime-api process.
- high-noise collector throughput can backlog the worker.
- no full observability dashboard.

### Target

For a single-user private cloud, deployment should be reliable without becoming enterprise-heavy.

### Recommended Approach

1. Add HTTPS/TLS via nginx/caddy with Let's Encrypt.
2. Add optional `openclaw-worker` profile.
3. Add worker priority lanes:
   - high: WhatsApp/Gmail/Calendar/Nomi chat
   - medium: Search/Bookmark
   - low: network/focus
4. Add dashboard metrics:
   - queue depth
   - worker lag
   - model failure count
   - collector degraded count
   - suggestion count and dismissal rate
5. Keep single-node defaults simple.

### Acceptance Criteria

- Public workbench can run over HTTPS.
- Worker lag stays bounded under noisy focus/network events.
- Health page shows queue depth, model status, collector status, and recent failures.

## Deliberately Out Of Scope

The following are not part of this gap-closure document because they were explicitly de-prioritized or removed from the current target:

- local model deployment as a required first-release feature
- Android launcher replacement
- Android native data collection from SMS, contacts, notifications, photos, accessibility, or screen OCR
- autonomous external actions without user confirmation
- automatic credential entry by Nomi

## Recommended Execution Order

### Phase 1: Make The Existing MVP Explainable And Controllable

1. Add missing agenda and trace APIs.
2. Add suggestion action endpoint and feedback records.
3. Add context pack active agenda/task retrieval.
4. Add validation fixtures proving context improves ambiguous judgments.

Reason: these make the current memory, agenda, and proactive system usable from UI and Android.

### Phase 2: Turn Routing Into Real Pipeline Execution

1. Extract pipeline registry from `runtime_api/app/main.py`.
2. Add pipeline engine and result schema.
3. Implement initial executable core pipelines for search, chat, agenda, todo, route, ride prepare, reply draft.
4. Add result reviewer and writeback.

Reason: this closes the largest architecture gap without waiting for more tools.

### Phase 3: Strengthen Scope, Identity, And Feedback

1. Add normalized memory scope schema.
2. Update collectors and worker to write richer scope.
3. Add backfill script.
4. Add user correction driven identity resolution.
5. Add feedback-driven suggestion suppression.

Reason: this prevents embarrassing cross-contact leakage and makes Nomi learn from user choices.

### Phase 4: Productionize OpenClaw And Composio

1. Add OpenClaw result reviewer.
2. Add true streaming if provider supports it.
3. Add separate worker service option.
4. Add Composio catalog import and provider routing.
5. Keep confirmation gates identical across all providers.

Reason: long-tail execution should be powerful but tightly boxed.

### Phase 5: Collector And Android Polish

1. Add stable source metadata to Gmail/WhatsApp/Calendar where possible.
2. Persist degraded diagnostics.
3. Add Android native WebSocket chat streaming.
4. Add Android quick actions and secure preferences.
5. Add quiet mode and notification settings.

Reason: this improves daily usability and trust.

### Phase 6: Ops Hardening

1. Add HTTPS/TLS.
2. Add queue/worker/model observability.
3. Add priority queues or low-value event suppression.
4. Add optional supervised OpenClaw worker.

Reason: this keeps the private-cloud deployment stable on a 4C/8G server.

## Regression Validation Requirements

Every implementation phase must update or add validation scripts. The output should include real intermediate content.

Required validation scenarios:

- WhatsApp fuzzy plan: writes memory, creates fuzzy agenda, suggests clarification or route/ride actions.
- WhatsApp reschedule: updates existing agenda and writes a version.
- WhatsApp cancel: cancels the right agenda item.
- Gmail payment deadline: writes memory, creates payment agenda/todo, suggests reminder/source review.
- Nomi correction: changes later entity resolution.
- Cross-contact privacy: reply to A excludes B's private negative opinion.
- Proactive action click: action creates route/pipeline trace and feedback.
- Ride prepare: stops before booking and asks for final confirmation.
- OpenClaw long-tail: receives only minimized context and stops before submit/payment/message.
- Android proactive bubble: displays message and opens chat context.

Required command set after each phase:

```bash
python3 -m pytest -q
python3 scripts/validate-private-event-processing.py
python3 scripts/validate-core-pipelines-openclaw.py
bash scripts/validate-android-floating-ball.sh
```

If a command passes but the printed stage output is semantically wrong, the phase is not complete.

## Phase 1 Implementation Status

**Status:** Implemented and verified on 2026-05-28.

Phase 1 closes the first runtime-facing parts of Gap 2, Gap 3, Gap 4, and Gap 6:

- `GET /api/agenda` lists agenda items with filters and latest version metadata.
- `PATCH /api/agenda/{id}` writes a `user_correction` agenda version with previous and new values.
- `POST /api/agenda/{id}/snooze` keeps the agenda item and writes snooze metadata plus a `snooze` version.
- `GET /api/proactive/suggestions` aliases the existing open-suggestion list for the proactive API surface.
- `POST /api/proactive/suggestions/{id}/action` records `user_feedback`, routes tool actions into the task router, persists route traces, and handles local actions such as snooze.
- `GET /api/events/{id}/trace` returns the connected event, semantic event, memory vectors, facts, agenda items, agenda versions, proactive suggestions, and task route traces.
- `GET /api/chat/conversations/{id}/trace` returns conversation metadata, turns, context snapshots, suggestions, and route traces.
- `POST /api/chat/messages` is now a compatibility alias for `/api/chat` and uses the same context-pack/chat pipeline.
- Chat context packs now include relevant active agenda items and persist `included_agenda_ids` into context snapshots.

Additional validation was added to `scripts/validate-private-event-processing.py`. It now prints concrete outputs for:

- active agenda selection, including exclusion of an unrelated server bill
- agenda API list/correction and version content
- proactive action feedback for `route_lookup`, `ride_prepare`, and `snooze`
- event and conversation trace evidence chains

Verified commands:

```bash
python3 -m pytest -q
python3 scripts/validate-private-event-processing.py
python3 scripts/validate-core-pipelines-openclaw.py
bash scripts/validate-android-floating-ball.sh
git diff --check
```

Observed results:

- `168 passed`
- private-event validation printed 16 stages and every stage was `reasonable: true`
- core pipeline/OpenClaw validation printed all stages as `reasonable: true`
- Android floating ball structure validation printed `Android floating ball structure looks good`
- `git diff --check` exited cleanly

Superseded limitations carried into later phases:

- Core pipelines now have executable state machines and local writeback/retrieval; provider calls are still intentionally blocked until real adapters are added.
- `ride_prepare` now returns a confirmation-gated ride proposal and provider-call plan, but it does not call a map or ride provider for live estimates.
- New route and pipeline execution traces store explicit `source_event_ids`, `conversation_id`, `suggestion_id`, and `agenda_item_ids`; schema startup also backfills these columns from older JSON payloads when possible.
- Agenda/context behavior is validated by the private-event processing regression; external calendar/task-provider sync remains out of scope for this pass.

## Phase 2 Implementation Status

**Status:** Implemented and verified on 2026-05-28.

Phase 2 partially closes Gap 1 by adding a minimal executable core-pipeline contract:

- `run_core_pipeline()` wraps task routing and returns a typed state-machine result.
- `POST /api/pipelines/run` exposes the same contract behind password protection.
- The result includes `pipeline_id`, `status`, `required_slots`, `resolved_slots`, `missing_slots`, `risk`, `execution_guard`, `external_effects`, `writeback_targets`, and step states.
- Reply requests can reach `draft_ready` with recipient/channel/message slots and external-message confirmation.
- Route requests can reach `completed_read_only` with destination slots and no final confirmation.
- Ride requests resolve destination but stay in `needs_user_input` when pickup is missing, preserving final confirmation before booking/payment.
- Vague payment requests stay in `needs_user_input` with amount/counterparty missing.

Remaining limitations after Phase 2:

- The engine does not yet call provider APIs such as Maps, Uber, Gmail, WhatsApp, Amazon, or payment services.
- Only the common contract and core slot heuristics are implemented. Provider-backed per-pipeline `run()` modules are still needed.
- Slot extraction now has a model-plus-rule path after the Phase 2 hardening pass below. It remains conservative: rule slots win, model slots fill missing required fields, and conflicts are preserved as validation warnings rather than silently overwriting local evidence.
- Pipeline execution results now persist to a dedicated `pipeline_execution_results` table when persistence is enabled.

## Phase 2 Hardening Implementation Status

**Status:** Implemented and verified on 2026-05-28.

This hardening pass closes the three follow-up gaps found after the initial Phase 2 implementation:

- Slot parsing now uses a hybrid model-plus-rule contract in `extract_pipeline_slots_with_trace()`. Deterministic rules run first. The model may fill missing required slots when `PIPELINE_SLOT_MODEL_ENABLED=true` or the request context sets `use_model_slots=true`. The validator rejects conflicting model values, records warnings such as `model_conflict:destination`, and keeps the rule-derived value.
- Pipeline execution results now have a dedicated persistence table, `pipeline_execution_results`, with route trace id, pipeline id, status, required/resolved/missing slots, risk, execution guard, explicit source references, and the full result JSON.
- `POST /api/pipelines/run` attempts safe persistence through `persist_pipeline_execution_result_safely()`. Test-mode persistence stays disabled unless explicitly enabled, so unit tests do not accidentally require PostgreSQL.
- Task route traces now store explicit references: `source_event_ids`, `conversation_id`, `suggestion_id`, and `agenda_item_ids`.
- Event and conversation trace APIs query the explicit references first and also include matching `pipeline_executions`. JSON/text matching remains only as a backward-compatible fallback for old rows.

Verified commands:

```bash
python3 -m pytest runtime_api/tests/test_core_pipeline_engine.py -q
python3 scripts/validate-core-pipelines-openclaw.py
python3 scripts/validate-private-event-processing.py
python3 -m pytest -q
git diff --check
```

Observed results:

- `runtime_api/tests/test_core_pipeline_engine.py`: `23 passed`
- core pipeline/OpenClaw validation printed 23 stages and every stage was `reasonable: true`
- private-event validation printed 16 stages and every stage was `reasonable: true`
- full pytest suite: `241 passed`
- `git diff --check` exited cleanly

Remaining limitations after hardening:

- The model slot parser is intentionally gated. In normal offline/dev runs it uses deterministic rules only unless explicitly enabled or requested by context. This avoids making local validation depend on a remote model being healthy.
- Provider-backed execution is still not implemented for Maps, Uber, Gmail, WhatsApp, Amazon, payments, and similar external systems. Current core pipelines stop at structured prepare/draft/confirmation states.
- Existing historical trace rows are backfilled into explicit columns when startup schema maintenance runs. JSON/text fallback remains as read compatibility, not as the primary linking strategy.

## Phase 2 Local Writeback And Retrieval Closure Status

**Status:** Implemented and verified on 2026-05-28.

This pass closes the non-external gaps found when comparing the 18 pipeline runners against the pipeline management design:

- Pipeline results now carry `version` and `pipeline_version`.
- `apply_pipeline_writeback_plan()` materializes local writeback plans instead of only returning them.
- New local persistence targets are bootstrapped in runtime and Docker init SQL: `pipeline_writeback_events`, `event_quarantine`, `duplicate_skip`, `memory_items`, `knowledge_entities`, `knowledge_edges`, `memory_vector_retries`, `context_snapshot_plans`, `internal_todos`, `internal_reminders`, `provider_call_traces`, `confirmation_ledger`, `pipeline_health_metrics`, `search_audit`, `account_connections`, and `route_cache`.
- Event ingestion writeback can persist accepted events, quarantine schema failures, and record duplicate skips.
- Agenda pipeline writeback can persist internal agenda items plus `agenda_item_versions`.
- Todo and reminder writeback persist local internal rows.
- Proactive pipeline writeback now records candidates and suggestions.
- Route pipeline writes local route-cache records.
- Personal search writes `search_audit`.
- Governance audit plans materialize provider-call traces and confirmation-ledger rows.
- Account-login pipeline writes local account-connection state without handling credentials.
- Startup schema maintenance backfills historical route and pipeline execution trace references from JSON payloads into explicit columns when possible.
- `context_pack_pipeline` can retrieve local facts/memory, active agenda, and recent Nomi turns when callers do not pre-supply evidence.
- `personal_search_pipeline` can retrieve local facts and memory items with scoped citations when callers do not pre-supply memory hits.
- Contact relationship pipeline now reports super-node mitigation metrics and emits correction audit plans.
- `/api/pipelines/health` exposes local pipeline health, provider-call, confirmation, and search audit records.

Verified commands:

```bash
python3 -m pytest runtime_api/tests/test_core_pipeline_engine.py runtime_api/tests/test_pipeline_actions.py runtime_api/tests/test_pipeline_agenda.py runtime_api/tests/test_pipeline_communication.py runtime_api/tests/test_pipeline_system.py -q
python3 -m pytest -q
python3 scripts/validate-core-pipelines-openclaw.py
python3 scripts/validate-private-event-processing.py
```

Observed results:

- focused pipeline subset: `73 passed`
- full pytest suite: `241 passed`
- core pipeline/OpenClaw validation: 23 stages, all `reasonable: true`; the validation now prints local writeback materialization, historical trace-reference backfill, and local context retrieval output
- private event processing validation: 16 reports, all `reasonable: true`

Remaining provider/non-behavior work after this pass:

- Real external adapters are still intentionally not connected: Maps, Uber, Gmail/Outlook, WhatsApp send, Amazon/commerce, payment, Drive/Docs/Sheets, and similar providers.
- Registry/router/slot/persistence extraction from `main.py` remains a maintainability refactor rather than a behavior gap.
- The visual pipeline dashboard is still UI polish; the local governance/health API exists.
