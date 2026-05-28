# Nomi Pipeline Management Design

**Status:** Draft for pipeline implementation management
**Date:** 2026-05-28
**Owner:** Nomi project

## Purpose

This document is the standalone management record for Nomi's core pipelines. It answers three questions:

- which pipelines exist or are planned
- how every pipeline should be implemented and verified
- what remains incomplete before a pipeline can be considered production-ready

The pipeline layer does not replace memory, agenda, proactive suggestions, OpenClaw, Composio, or the Android floating ball. It is the deterministic task layer between "Nomi understands something" and "Nomi prepares or performs a user task".

## Current Implementation Reality

The current runtime has a minimal pipeline execution contract in `runtime_api/app/main.py`:

- `capability_taxonomy()` classifies the request by capability keywords.
- `core_pipeline_registry()` defines 18 first-party pipeline records.
- `route_tool_request()` chooses `core_pipeline`, `ask_user`, or `openclaw_tool`.
- `run_core_pipeline()` returns a unified execution result with status, slots, risk, guard, steps, writeback targets, and trace ids.
- `runtime_api/app/pipelines/` now contains first-pass pure pipeline runners for all 18 core pipelines.
- Slot extraction is hybrid model-plus-rules when enabled, but rules remain authoritative on conflicts.
- `pipeline_execution_results` persists execution results separately from route traces.
- `apply_pipeline_writeback_plan()` now materializes local writeback plans for events, quarantines, duplicate skips, memory items, facts, graph entities/edges, agenda items and versions, internal todos/reminders, proactive candidates/suggestions, route cache, search audit, account connections, provider-call traces, confirmation ledger, and pipeline health metrics.
- `context_pack_pipeline` and `personal_search_pipeline` can fall back to local DB retrieval when callers do not pass pre-built evidence.
- `/api/pipelines/health` exposes local pipeline health, provider-call trace, confirmation, and search-audit records for governance inspection.
- Event and conversation traces now return explicit route and pipeline execution references.

Important limitation: these runners are contentful prepare/state-machine runners, not live external provider executors. Maps, Uber, Gmail, WhatsApp, Amazon, payments, Drive, and similar providers still need dedicated adapters and final-action gates before real external actions can happen.

## Pipeline Management Principles

1. Every high-frequency task should have a deterministic first-party pipeline.
2. Every external-effect action must stop before final execution until user confirmation is recorded.
3. Every pipeline result must be auditable from source event, conversation, suggestion, agenda item, and execution result.
4. Models may extract, rank, summarize, or draft, but they cannot silently override rule-grounded evidence.
5. Long-tail workflows stay in OpenClaw until repeated usage proves they deserve a stable pipeline.
6. Internal local writes, such as memory or internal agenda updates, can be automatic when confidence and source evidence are sufficient.
7. External writes, such as sending, booking, buying, paying, sharing, archiving, or changing third-party data, require explicit confirmation.

## Common Pipeline Contract

Every pipeline should expose the same management fields:

```json
{
  "pipeline_id": "ride_pipeline",
  "version": "2026-05-28",
  "capability_id": "local_service.ride.estimate_or_book",
  "status": "needs_user_input",
  "input": {
    "user_request": "帮我打车去武康路",
    "source_event_ids": ["evt_123"],
    "conversation_id": "conv_456",
    "suggestion_id": "sug_789",
    "agenda_item_ids": ["agenda_001"]
  },
  "required_slots": ["pickup", "destination"],
  "resolved_slots": {
    "destination": "武康路"
  },
  "missing_slots": ["pickup"],
  "risk": {
    "permission": "payment_or_purchase",
    "confirmation_required": true,
    "final_user_confirmation": true
  },
  "execution_guard": {
    "permission": "payment_or_purchase",
    "policy": "requires_final_user_confirmation"
  },
  "steps": [
    {"name": "识别目的地", "status": "completed"},
    {"name": "查路线", "status": "pending"}
  ],
  "writeback_targets": ["assistant_turns", "agenda_items", "task_trace"],
  "external_effects": ["book_ride", "payment"]
}
```

## Pipeline Status Model

| Status | Meaning | Allowed next action |
| --- | --- | --- |
| `completed_read_only` | Read-only work completed, no external write needed | Return answer and write trace |
| `draft_ready` | Draft or prepared action is ready | Show draft/action card and wait for user confirmation |
| `needs_user_input` | Required slot is missing or ambiguous | Ask a targeted question |
| `confirmation_required` | All slots are present but action has external effect | Ask final confirmation |
| `blocked` | Risk, policy, provider, or evidence failure prevents execution | Explain blockage and write trace |
| `failed` | Unexpected runtime error | Preserve error, retry policy, and user-visible summary |

## Slot Parsing Policy

Slot parsing should run in this order:

1. Read explicit context fields from the current request, active source scope, selected suggestion, agenda item, and current UI state.
2. Apply deterministic rules for known patterns, such as destination, recipient, amount, counterparty, account provider, and document intent.
3. Call the model only when enabled and useful for missing required slots.
4. Accept model values only when they fill missing required slots.
5. Reject model values that conflict with rule-grounded values and record a warning such as `model_conflict:destination`.
6. Do not invent exact times, recipients, payment amounts, or external-effect targets without source evidence.

## Confirmation Policy

No confirmation is needed for:

- local event ingestion
- local memory writes
- bounded context pack creation
- read-only personal search
- read-only route lookup
- showing proactive suggestions
- local audit writes

Confirmation is needed before:

- sending messages or email
- writing to external calendars or task tools
- booking rides or services
- buying products or adding items to external carts when that creates a commitment
- paying, transferring, refunding, or changing subscriptions
- writing, sharing, archiving, deleting, or publishing external documents or data
- changing account settings

## Trace And Persistence Requirements

Every pipeline run should write or return:

- route decision trace in `task_route_traces`
- execution result in `pipeline_execution_results`
- explicit references: `source_event_ids`, `conversation_id`, `suggestion_id`, `agenda_item_ids`
- slot extraction trace with rule slots, model slots, parser mode, confidence, and warnings
- risk and confirmation decision
- provider calls and final outcomes when provider adapters exist

Legacy JSON/text trace lookup can remain for old rows, but all new writes must use explicit references.

## Pipeline Registry Summary

| Pipeline | Current role | Production readiness |
| --- | --- | --- |
| `event_ingestion_pipeline` | Private event normalization and local ledger write | Internal runner has stable dedupe, duplicate skip, schema quarantine, local event writeback, and collector-health writeback; source-specific collectors still external |
| `memory_write_pipeline` | KV, graph, RAG, embedding writes | Internal write-plan runner has layer status, materialized memory/fact/graph writes, audit writes, and vector retry rows when embeddings are unavailable |
| `context_pack_pipeline` | Scoped memory, agenda, and dialogue context | Internal runner has ranking, scope boundary, exclusion metrics, and local retrieval fallback for memory, active agenda, and recent Nomi turns |
| `personal_search_pipeline` | Answer from local memory | Internal runner has scoped ranking, no-evidence reason, ambiguous private-scope question, local facts/memory retrieval fallback, and `search_audit` writeback |
| `chat_response_pipeline` | User-facing streamed Nomi response | Internal runner has stream plan, trace id, writeback-after-stream, and action handoff; actual streaming/storage exists in `/ws` and `/api/chat` |
| `reply_pipeline` | Draft and confirm replies | Internal runner has leakage review and confirmation card; provider send adapters remain |
| `email_pipeline` | Email summarization, triage, task extraction, drafts | Internal runner has candidates, confirmation card, provider-call plan; Gmail/Outlook adapters remain |
| `agenda_pipeline` | Internal agenda create/update/cancel/reschedule | Internal runner has merge, conflict, notification plans, and local agenda/version writeback |
| `task_todo_pipeline` | Todo and follow-up management | Internal runner has create/update/complete/cancel/reschedule lifecycle, reminder adjustment, and local todo/reminder writeback |
| `proactive_suggestion_pipeline` | Decide and deliver proactive cards | Internal runner has duplicate/cooldown suppression, feedback signal, proactive-candidate writeback, suggestion writeback, and notification payload |
| `route_pipeline` | Read-only route/ETA lookup | Provider-ready state machine with normalized route options and local route-cache writeback; Maps adapter missing |
| `ride_pipeline` | Prepare ride and confirm booking | Provider-ready confirmation state machine; Maps/Uber adapters missing |
| `shopping_pipeline` | Product search/compare/prepare purchase | Provider-ready compare/purchase confirmation state machine; commerce adapters missing |
| `payment_bill_pipeline` | Bill/payment detection and confirmation | Provider-ready confirmation state machine; payment adapters intentionally gated |
| `contact_relationship_pipeline` | Contact facts and relationship graph updates | Scoped relationship plan includes super-node mitigation metrics, correction audit plan, graph writeback, and leakage policy |
| `document_file_pipeline` | Find/summarize/write docs and sheets | First-pass document action runner implemented; provider adapters missing |
| `account_login_pipeline` | Controlled browser login setup | Internal runner has controlled browser plan, connection health, and local `account_connections` writeback; provider readiness checks can be deepened |
| `governance_audit_pipeline` | Audit route, risk, confirmation, output, feedback | Internal runner has trace chain, provider-call audit plan, confirmation ledger plan, physical trace tables, and `/api/pipelines/health`; richer UI remains |

## Pipeline Designs

### 1. `event_ingestion_pipeline`

**Goal:** Normalize every private event into a stable local event ledger entry.

**Triggers:** WhatsApp DOM/protocol event, Gmail event, browser-visible account event, Android/Nomi chat turn, manual runtime event.

**Required slots:** `source`, `event_type`, `timestamp`

**Context:** raw event payload, browser profile/session id, account/source scope, collector health metadata.

**Steps:**

1. Normalize source-specific payload into canonical event fields.
2. Assign event id and source scope.
3. Deduplicate repeated collector events.
4. Store raw event locally.
5. Emit downstream processing job for memory, agenda, suggestions, and task intent.

**Outputs:** local `events` row, collector health update, downstream job payload with redacted model-safe copy.

**Writebacks:** `events`, `collector_health`, `task_trace`

**Risk policy:** local-only; no user confirmation.

**Failure handling:** if canonical fields are missing, store quarantined event with `blocked` status and collector diagnostic.

**Verification:** feed a WhatsApp message and Gmail email fixture; assert event id, source, raw data, timestamp, source scope, and downstream payload are correct.

**Implementation status:** local quarantine and duplicate-skip writebacks are implemented. Remaining work is stronger source-specific normalizers inside the collectors.

### 2. `memory_write_pipeline`

**Goal:** Write every private event and Nomi conversation turn into scoped long-term memory.

**Triggers:** every accepted event and every finalized Nomi turn.

**Required slots:** `event_id`, `source_scope`

**Context:** event text, semantic labels, account/source scope, contact/conversation identity, privacy scope, existing memory entities.

**Steps:**

1. Classify memory scope: user-global, contact-specific, conversation-specific, account-specific, or sensitive-local-only.
2. Write KV facts for stable preferences and profile facts.
3. Write graph entities and relationships with source evidence.
4. Chunk RAG text with source metadata.
5. Compute embeddings and insert vector rows.
6. Record validation warnings for low-confidence or ambiguous facts.

**Outputs:** memory write summary, fact ids, graph entity/edge ids, vector ids.

**Writebacks:** `memory_items`, `facts`, `knowledge_entities`, `knowledge_edges`, `memory_vectors`, `memory_audit_log`

**Risk policy:** local-only; no confirmation. Model-boundary payloads must be redacted.

**Failure handling:** if embedding fails, still write KV/graph facts and queue vector retry.

**Verification:** use a multi-contact fixture where contact B says something about contact A; assert retrieval scope prevents leaking B-only content into A conversation.

**Implementation status:** one orchestrated pipeline result exists, local writeback materializes memory/fact/graph/audit rows, and vector retry rows are recorded when embeddings are unavailable.

### 3. `context_pack_pipeline`

**Goal:** Build bounded context for reasoning, response generation, task routing, and proactive decisions.

**Triggers:** chat response, proactive evaluation, pipeline run, OpenClaw packet creation.

**Required slots:** `request_or_event_id`

**Context:** current request/event, conversation id, source event ids, active agenda, recent Nomi dialogue, scoped memories, selected suggestion.

**Steps:**

1. Determine active scope and contact/conversation boundary.
2. Retrieve recent assistant turns.
3. Retrieve active agenda items relevant to this scope.
4. Retrieve scoped memory from KV, graph, and RAG.
5. Filter unrelated contacts and sensitive cross-scope facts.
6. Assemble minimized context pack with included ids and reason.

**Outputs:** context pack payload, included event/memory/agenda ids, exclusion reasons.

**Writebacks:** `context_snapshots`

**Risk policy:** local-only; no confirmation.

**Failure handling:** if retrieval fails, degrade to recent turns and explicit current event only.

**Verification:** assert a fuzzy agenda follow-up such as "那就周日吧" includes the matching active agenda but excludes unrelated billing agenda.

**Implementation status:** context pack is a first-class pipeline result with included/excluded ids, exclusion metrics, scope boundary, and local retrieval fallback.

### 4. `personal_search_pipeline`

**Goal:** Answer user questions from local memory with scoped evidence.

**Triggers:** "之前谁说过...", "地址在哪", "帮我找...", "我上次和 Alex 说了什么".

**Required slots:** `query`

**Context:** current user query, active conversation/contact scope, memory layers, timeline, agenda, source constraints.

**Steps:**

1. Classify search scope: current conversation, named contact, global user memory, account/source-specific.
2. Retrieve KV/fact hits for exact facts.
3. Retrieve graph neighborhoods for relationships.
4. Retrieve RAG chunks for free text.
5. Rank and deduplicate evidence.
6. Generate answer with citations to source ids.
7. If scope is ambiguous, ask user which scope to search.

**Outputs:** answer, evidence list, confidence, excluded scope summary.

**Writebacks:** `assistant_turns`, `task_trace`, optional search audit row.

**Risk policy:** read-only; no confirmation.

**Failure handling:** return "没找到可靠证据" rather than guessing.

**Verification:** run query fixtures with similar facts from two contacts and assert answer cites only allowed contact/source.

**Implementation status:** scoped ranking, evidence citations, local DB fallback, no-evidence reason, ambiguous private-scope question, and search audit writeback are implemented. A deeper provider-style search UI can still be polished later.

### 5. `chat_response_pipeline`

**Goal:** Stream Nomi's user-facing conversational answer while preserving memory and task context.

**Triggers:** user sends message in H5 or Android conversation panel.

**Required slots:** `conversation_id`, `message`

**Context:** user turn, context pack, active task, source references, model config, safe prompt.

**Steps:**

1. Store user turn and create/resolve conversation id.
2. Build context pack.
3. Classify whether the message also implies a task/tool intent.
4. Stream model response to the client.
5. Store assistant turn.
6. If task intent exists, create action cards or pipeline handoff.

**Outputs:** streamed assistant text, conversation id, optional action cards, referenced memory/agenda ids.

**Writebacks:** `assistant_turns`, `events`, `context_snapshots`, `task_trace`

**Risk policy:** read-only unless an attached action enters another pipeline.

**Failure handling:** if model streaming fails, return a short local fallback and preserve user turn.

**Verification:** assert streamed chunks arrive in order, final assistant turn is stored, and context ids match the trace.

**Implementation status:** `/ws` streams model deltas and stores final assistant turns; the pipeline returns a stream plan and action handoff that shares the same trace/writeback contract.

### 6. `reply_pipeline`

**Goal:** Draft and optionally send a reply through WhatsApp, email, Slack, or similar channels.

**Triggers:** "帮我回复 Alice，说...", proactive reply suggestion, selected message action.

**Required slots:** `recipient`, `channel`, `message_intent`

**Context:** active source scope, current conversation, recent messages with that recipient, relevant memory scoped to that recipient, user instruction.

**Steps:**

1. Resolve recipient and channel.
2. Retrieve only the target conversation and target-contact memory.
3. Draft reply.
4. Run cross-contact leakage check.
5. Show draft and target recipient/channel to user.
6. Send only after explicit confirmation.
7. Write sent/dismissed outcome.

**Outputs:** reply draft, target channel, target recipient, evidence ids, confirmation request.

**Writebacks:** `assistant_turns`, `task_trace`, `memory_items`

**External effects:** `send_message`

**Risk policy:** `external_message`; user confirmation before sending.

**Failure handling:** if recipient/channel is ambiguous, ask a targeted question. If leakage check fails, block and explain.

**Verification:** "帮我回复她" should use active WhatsApp conversation to fill Alice; a model-proposed different recipient must be rejected.

**Implementation status:** draft-only contract, scoped target card, final-confirmation gate, and leakage reviewer are implemented. Real send adapters remain external-provider work.

### 7. `email_pipeline`

**Goal:** Process email by summarizing, extracting tasks, drafting replies, and preparing label/archive actions.

**Triggers:** Gmail/Outlook event, "总结这封邮件", "帮我回这封邮件", "把这个归档".

**Required slots:** `mailbox`, `email_intent`

**Context:** selected email/thread id, mailbox account, sender, subject, body summary, attachments metadata, related agenda/memory.

**Steps:**

1. Resolve mailbox and target email/thread.
2. Classify email intent: summarize, task extract, draft reply, label, archive.
3. Extract agenda/todo/payment candidates.
4. Draft response or action plan.
5. Show write/send/archive actions for confirmation.
6. Execute provider write only after confirmation.
7. Persist result and derived memory/agenda.

**Outputs:** summary, extracted tasks, draft reply, proposed email actions.

**Writebacks:** `assistant_turns`, `agenda_items`, `task_trace`, `memory_items`

**External effects:** `send_email`, `archive_email`, `label_email`

**Risk policy:** reading is allowed after login; send/archive/label requires confirmation.

**Failure handling:** if target email is unclear, ask user to choose thread/email.

**Verification:** use an invoice email fixture; assert payment agenda candidate is created but payment is not executed.

**Implementation status:** internal summarize/task/payment/reply/action-plan outputs and confirmation requirements are implemented. Gmail/Outlook thread adapters remain external-provider work.

### 8. `agenda_pipeline`

**Goal:** Create, update, cancel, reschedule, merge, and clarify internal agenda items from private evidence.

**Triggers:** appointment/deadline/payment/fuzzy plan in WhatsApp/email/Nomi chat, user correction, proactive action.

**Required slots:** `time_window`, `title`

**Context:** source event, semantic event, current conversation, existing agenda candidates, participants, place, time phrase, cancellation/reschedule cues.

**Steps:**

1. Parse candidate with model-plus-rule validation.
2. Determine operation: create, update details, reschedule, cancel, merge, complete, lower confidence, clarify.
3. Match existing agenda by dedupe key, participants, source scope, and time/place similarity.
4. Validate fuzzy vs exact time; reject unsupported exact guesses.
5. Write agenda item and `agenda_item_versions`.
6. Trigger proactive suggestion when action is useful.
7. Optional external calendar write only after confirmation.

**Outputs:** agenda item, version record, operation, confidence, missing fields, clarification need.

**Writebacks:** `agenda_items`, `agenda_item_versions`, `proactive_candidates`, `task_trace`

**External effects:** optional `write_calendar`

**Risk policy:** internal agenda writes can be automatic; external calendar writes require confirmation.

**Failure handling:** ambiguous participant/time/place stays fuzzy and requests clarification instead of guessing.

**Verification:** fuzzy weekend meeting, exact tonight meeting, cancel, reschedule, and unsupported model exact-time cases must all produce reasonable agenda outputs.

**Implementation status:** create/update/reschedule/cancel/complete operations, duplicate merge plan, conflict plan, fuzzy/exact notification plan, and agenda/version writeback are implemented. External calendar write remains confirmation-gated provider work.

### 9. `task_todo_pipeline`

**Goal:** Manage commitments, follow-ups, deadlines, and lightweight tasks.

**Triggers:** "记得...", "提醒我...", "我答应...", "截止...", email/task phrases, follow-up suggestions.

**Required slots:** `task_title`

**Context:** source event, speaker/owner, due date phrase, related contact/project, active agenda, prior tasks.

**Steps:**

1. Detect commitment/todo/deadline.
2. Resolve task owner: user, contact, team, or unknown.
3. Parse due window if present.
4. Deduplicate against existing agenda/todo items.
5. Write internal task as agenda/todo item.
6. Schedule reminder/proactive suggestion.
7. External task tool write only after confirmation.

**Outputs:** todo item, due window, owner, confidence, reminder plan.

**Writebacks:** `agenda_items`, `agenda_item_versions`, `proactive_suggestions`, `task_trace`

**External effects:** optional `write_task`

**Risk policy:** local task writes automatic when evidence is strong; external writes require confirmation.

**Failure handling:** if owner or due date is unclear, store fuzzy task and ask later only when useful.

**Verification:** a commitment message and an email deadline should create different task types with correct owner/evidence.

**Implementation status:** todo create/update/complete/cancel/reschedule lifecycle, owner/due/source extraction, reminder adjustment, and internal todo/reminder writeback are implemented. External task-tool write remains confirmation-gated provider work.

### 10. `proactive_suggestion_pipeline`

**Goal:** Decide when Nomi should proactively notify the user and generate action cards.

**Triggers:** important private event, agenda due/changed, todo deadline, travel need, payment risk, missed reply, user preference signal.

**Required slots:** `candidate_type`, `source_event_ids`

**Context:** event semantic labels, agenda/todo state, user activity, cooldown history, previous feedback, current Android/WebSocket sessions.

**Steps:**

1. Score importance and urgency.
2. Check cooldown and duplicate suppression.
3. Generate concise suggestion title/body.
4. Generate action cards, such as `查路线`, `帮我打车`, `稍后提醒`, `起草回复`.
5. Persist suggestion.
6. Push over WebSocket/Android realtime channel.
7. Record user action feedback.

**Outputs:** proactive suggestion, action card list, realtime payload.

**Writebacks:** `proactive_candidates`, `proactive_suggestions`, `user_feedback`, `task_trace`

**Risk policy:** showing suggestion is allowed; action execution follows target pipeline policy.

**Failure handling:** if delivery fails, keep suggestion open for workbench/Android fetch.

**Verification:** WhatsApp meeting at a place should produce route/ride/snooze action cards with correct risk labels.

**Implementation status:** suggestion scoring, duplicate suppression, cooldown handling, feedback signal accounting, action-card risks, notification payload, candidate writeback, and suggestion writeback are implemented. Further tuning is product iteration rather than an unimplemented pipeline contract.

### 11. `route_pipeline`

**Goal:** Provide read-only routes, ETA, and location options.

**Triggers:** "查路线", "怎么去", detected meeting location, proactive route action.

**Required slots:** `destination`

**Context:** destination, current/pickup location if known, time window, transport preference, map provider config.

**Steps:**

1. Resolve destination from request, agenda, suggestion, or selected event.
2. Resolve optional origin/current location.
3. Call map provider for route options.
4. Normalize ETA, distance, mode, and map link.
5. Return answer/action card without final confirmation.
6. Persist route lookup result.

**Outputs:** route summary, ETA, alternatives, map link, confidence.

**Writebacks:** `assistant_turns`, `task_trace`, optional route cache.

**Risk policy:** read-only; no confirmation.

**Failure handling:** missing destination asks user. Missing origin can use "请设置出发地" instead of blocking if provider allows.

**Verification:** "查一下去武康路要多久" should resolve destination and return read-only status; no booking/payment effects.

**Implementation status:** destination/origin resolution, read-only guard, provider-call plan, normalized provider-ready request/options shape, and local route-cache writeback are implemented. Real Maps ETA calls remain external-provider work.

### 12. `ride_pipeline`

**Goal:** Prepare ride request and optionally book after user confirmation.

**Triggers:** "帮我打车", proactive "帮我打车", meeting requires travel, airport/hotel route.

**Required slots:** `pickup`, `destination`

**Context:** destination from request/agenda, current location, time window, ride preferences, provider login state, payment risk.

**Steps:**

1. Resolve destination and pickup.
2. If pickup missing, ask for pickup or use current location only when available and user-approved.
3. Call route provider for ETA.
4. Call ride provider for vehicle/price estimates.
5. Show options and final confirmation.
6. Book only after confirmation.
7. Persist booking result and reminder/agenda update.

**Outputs:** ride proposal, ETA, price options, provider status, confirmation request.

**Writebacks:** `assistant_turns`, `agenda_items`, `task_trace`, `memory_items`

**External effects:** `book_ride`, `payment`

**Risk policy:** final confirmation required before booking/payment.

**Failure handling:** if Uber/provider unavailable, fall back to route link or OpenClaw browser prepare-only flow.

**Verification:** "帮我打车去武康路" with no pickup must return `needs_user_input`; with pickup must return `confirmation_required`, not book.

**Implementation status:** pickup/destination slot handling, `needs_user_input` for missing pickup, ride proposal/confirmation card, provider-call plan, and no-booking safety checks are implemented. Maps/Uber estimate and booking adapters remain external-provider work.

### 13. `shopping_pipeline`

**Goal:** Search, compare, and prepare shopping actions without purchasing until confirmed.

**Triggers:** "帮我买...", "比价...", shopping intent in chat/email, delivery issue.

**Required slots:** `product_intent`

**Context:** product name, constraints, budget, preferences, shipping account, prior purchases, provider login state.

**Steps:**

1. Resolve product intent and constraints.
2. Retrieve user shopping preferences if relevant.
3. Search provider/catalog/browser results.
4. Compare price, delivery, ratings, seller trust, return policy.
5. Present recommendations and risks.
6. Add to cart or purchase only after explicit confirmation.
7. Persist result and user preference feedback.

**Outputs:** comparison table, recommendation, cart/purchase confirmation action.

**Writebacks:** `assistant_turns`, `task_trace`, `memory_items`

**External effects:** `add_to_cart`, `purchase`, `payment`

**Risk policy:** final confirmation before cart commitment, purchase, or payment.

**Failure handling:** if product is ambiguous, ask clarifying constraints; if provider missing, use OpenClaw prepare-only.

**Verification:** "帮我买一根 iPhone 充电线" should ask/derive constraints, show options, and not purchase.

**Implementation status:** product intent/constraints, compare-vs-purchase states, confirmation card, safety checks, and no-purchase guard are implemented. Commerce provider adapters and live catalog ranking remain external-provider work.

### 14. `payment_bill_pipeline`

**Goal:** Detect bills, reimbursements, invoices, payment reminders, and prepare safe payment-related actions.

**Triggers:** invoice email, "我欠/他欠", "帮我付款", reimbursement messages.

**Required slots:** `counterparty`, `amount_or_bill`

**Context:** invoice/email source, payment due date, counterparty, amount, currency, prior bills, user payment preferences.

**Steps:**

1. Detect bill/payment intent.
2. Extract amount, counterparty, due date, invoice id, payment method if available.
3. Validate source evidence and ambiguity.
4. Create internal agenda/todo/payment reminder.
5. Show payment plan or ask for missing fields.
6. Execute external payment only after final confirmation and provider-specific review.
7. Persist result.

**Outputs:** payment summary, missing fields, reminder, confirmation request.

**Writebacks:** `agenda_items`, `memory_items`, `task_trace`

**External effects:** `payment`, `transfer`

**Risk policy:** always final confirmation for money movement.

**Failure handling:** vague "帮我付款" asks for amount and counterparty. Unsupported provider blocks before payment.

**Verification:** invoice email creates payment agenda; "帮我付款" returns missing `amount_or_bill` and `counterparty`.

**Implementation status:** bill/payment slot extraction, missing amount/counterparty handling, reminder/payment-plan output, confirmation card, and no-transfer safety checks are implemented. Banking/payment adapters intentionally remain external-provider work.

### 15. `contact_relationship_pipeline`

**Goal:** Maintain contact facts, preferences, relationship signals, and isolation scopes.

**Triggers:** repeated chats, explicit preference facts, birthdays, relationship changes, sensitive social signals.

**Required slots:** `contact_or_actor`

**Context:** source conversation, speaker/actor, mentioned contacts, fact candidate, relationship edge, sensitivity label.

**Steps:**

1. Extract contact/entity candidate.
2. Determine whether fact is about speaker, user, third party, or relationship.
3. Assign source scope and sensitivity.
4. Update graph entity/edge or contact fact.
5. Preserve source event evidence.
6. Avoid leaking third-party private statements into another contact's context.
7. Support user correction/deletion later.

**Outputs:** contact fact, relationship edge, confidence, evidence ids, scope.

**Writebacks:** `knowledge_entities`, `knowledge_edges`, `memory_items`, `task_trace`

**Risk policy:** local-only; no confirmation, but user correction must be supported.

**Failure handling:** if actor/subject is ambiguous, keep low-confidence scoped fact or skip graph write.

**Verification:** if B says A is unreliable, that fact must not be recalled while chatting with A unless user explicitly asks global search.

**Implementation status:** first-class relationship pipeline result, scoped graph/memory writeback plan, cross-contact leakage policy, user-correction audit plan, and super-node mitigation metrics are implemented.

### 16. `document_file_pipeline`

**Goal:** Search, summarize, draft, and update documents, sheets, and files.

**Triggers:** "找文件", "总结这个文档", "写到表格", Drive/Docs/Sheets task, uploaded/local file task.

**Required slots:** `file_or_query`, `document_intent`

**Context:** selected file, account provider, document metadata, permission state, user instruction, write/share risk.

**Steps:**

1. Resolve target file or search query.
2. Read metadata and content if permission allows.
3. Summarize, extract, or draft changes.
4. Show proposed edits for write/share actions.
5. Execute write/share only after confirmation.
6. Persist file action trace and derived memory.

**Outputs:** summary, extracted data, draft patch, confirmation action.

**Writebacks:** `assistant_turns`, `task_trace`, `memory_items`

**External effects:** `write_document`, `share_file`

**Risk policy:** read can be allowed after login; writes/shares require confirmation.

**Failure handling:** if multiple files match, ask user to choose; if format unsupported, fall back to local parser/OpenClaw as read-only.

**Verification:** a PPTX/local document summary should cite file identity and avoid writing without confirmation.

**Implementation status:** file/query intent handling, read-only summary/search plan, write/share confirmation card, provider-call plan, and external-write blocking are implemented. Provider-backed document adapters remain external-provider work.

### 17. `account_login_pipeline`

**Goal:** Help the user connect/log into accounts in the controlled browser without taking over credentials.

**Triggers:** user chooses login channel in Android/H5, "登录 Gmail", "连接 WhatsApp", account expired.

**Required slots:** `account_provider`

**Context:** provider id, browser profile, current login state, collector requirement, user device.

**Steps:**

1. Resolve account provider.
2. Open controlled browser/login page.
3. Let user manually enter credentials and pass MFA.
4. Detect successful login/session state.
5. Record connection status, account label, and collector readiness.
6. Offer next recommended channels to connect.

**Outputs:** login URL/session instruction, connection status, provider health.

**Writebacks:** `collector_settings`, `account_connections`, `task_trace`

**External effects:** browser navigation/session creation.

**Risk policy:** user handles credentials; Nomi must not generate, store, or send credentials outside the local browser/session store.

**Failure handling:** if provider blocks automated browser, explain and offer supported alternative such as manual session import only when product policy allows.

**Verification:** selecting Gmail opens correct login flow and records only connection metadata, not password content.

**Implementation status:** login provider resolution, controlled-browser plan, credential-handling guard, account connection writeback, connection health, and collector readiness signal are implemented. Provider-specific deep readiness checks remain external-provider work.

### 18. `governance_audit_pipeline`

**Goal:** Record task decisions, risk reasons, confirmations, outputs, feedback, and source references.

**Triggers:** every routed task, pipeline execution, OpenClaw job, external action, user feedback, correction.

**Required slots:** `task_id`

**Context:** route decision, execution result, confirmation event, provider result, user feedback, source references.

**Steps:**

1. Persist route decision.
2. Persist pipeline execution result.
3. Persist confirmation/denial when applicable.
4. Persist provider calls and outcomes.
5. Link event/conversation/suggestion/agenda references.
6. Redact sensitive outbound trace fields where needed.
7. Render trace in governance/debug UI.

**Outputs:** auditable trace chain and user-visible explanation.

**Writebacks:** `task_route_traces`, `pipeline_execution_results`, `user_feedback`, `memory_audit_log`

**Risk policy:** local-only; no confirmation.

**Failure handling:** trace write failures should not execute external effects; for read-only tasks they should return with a warning.

**Verification:** event trace and conversation trace should show route traces plus pipeline executions with explicit references.

**Implementation status:** explicit references, pipeline execution table, provider-call trace table, confirmation ledger, pipeline health metrics, local writeback materialization, and health API are implemented. Richer visual governance dashboard is product UI polish.

## Promotion Policy For New Pipelines

A long-tail OpenClaw or Composio workflow should be promoted into a core pipeline when all are true:

- the task repeats frequently
- required slots are stable
- confirmation gates are clear
- mistakes have meaningful user cost
- the task belongs to Nomi's core assistant promise

Candidate future pipelines:

- CRM update pipeline
- project/issue update pipeline
- spreadsheet extraction/update pipeline
- travel booking pipeline
- restaurant reservation pipeline
- package/delivery support pipeline

## Implementation Roadmap

### Phase A: Extract Pipeline Engine From `main.py`

Create focused modules:

- `runtime_api/app/pipelines/registry.py`
- `runtime_api/app/pipelines/router.py`
- `runtime_api/app/pipelines/slots.py`
- `runtime_api/app/pipelines/engine.py`
- `runtime_api/app/pipelines/persistence.py`

Acceptance: existing tests pass and `main.py` delegates pipeline logic to these modules.

Status on 2026-05-28: partially complete. `runtime_api/app/pipelines/base.py` and focused runner modules now exist, and `main.py` delegates direct/core execution to them. Registry/router/slots/persistence are still partly in `main.py`; those should be extracted in a later refactor once behavior stabilizes.

### Phase B: Make The Three Most Useful User-Facing Pipelines Real

Implement provider-backed or provider-ready state machines for:

1. `personal_search_pipeline`
2. `reply_pipeline`
3. `route_pipeline`

Acceptance: each has content-level validation, trace output, and user-facing result quality checks.

Status on 2026-05-28: provider-ready internal runners exist for all three. `personal_search_pipeline` filters and ranks scoped evidence, asks for scope when private hits are ambiguous, reports no-evidence reasons, reads local facts/memory when needed, and writes `search_audit`; `reply_pipeline` drafts without sending, runs leakage review, and returns confirmation cards; `route_pipeline` prepares read-only route requests, normalizes provider-style route options, and writes local `route_cache`. Send adapters and Maps calls remain external-provider work.

### Phase C: Complete Agenda/Todo/Proactive Loop

Finish:

- agenda merge/complete/conflict/notification planning
- todo lifecycle
- proactive cooldown and feedback learning

Acceptance: WhatsApp/email fixture stream creates memory, agenda/todo, suggestion card, action route, and trace with reasonable output at every stage.

Status on 2026-05-28: internal agenda/todo/proactive runners now cover merge, conflict, notification planning, todo lifecycle, reminder adjustment, duplicate suppression, cooldown, feedback signals, notification payload, and local writeback for agenda versions, internal todos/reminders, proactive candidates, and suggestions. Real delivery tuning remains product polish.

### Phase D: External Action Providers

Add carefully gated adapters for:

- Gmail/Outlook
- Google Maps
- Uber or browser-based ride prepare
- Drive/Docs/Sheets
- Amazon/browser shopping prepare

Acceptance: all external-effect tests stop at confirmation unless a test explicitly simulates user approval.

Status on 2026-05-28: prepare-only runners exist for route, ride, shopping, payment, document, account-login, reply, and email. They do not execute real external effects. Provider adapters remain intentionally unimplemented.

### Phase E: Governance And Productization

Add:

- provider-call trace table
- confirmation ledger
- pipeline dashboard
- per-pipeline health metrics
- replayable fixture validation

Acceptance: a user or developer can inspect why any suggestion/action happened and what evidence was used.

Status on 2026-05-28: route and pipeline execution traces with explicit references exist. Governance runner returns provider-call audit plus confirmation-ledger writeback plans; local writeback now materializes `provider_call_traces`, `confirmation_ledger`, `pipeline_health_metrics`, and `/api/pipelines/health`. Richer visual dashboard remains UI polish.

## Implementation Verification On 2026-05-28

The parallel implementation added:

- `runtime_api/app/pipelines/base.py`
- `runtime_api/app/pipelines/system.py`
- `runtime_api/app/pipelines/communication.py`
- `runtime_api/app/pipelines/agenda.py`
- `runtime_api/app/pipelines/actions.py`
- integration from `run_core_pipeline()` to module runners
- content-level tests for system, communication, agenda, action, contact, governance, and direct dispatch behavior
- Wave 2 internal completion checks for dedupe/quarantine, scoped search, leakage blocking, email candidates, chat action handoff, agenda merge, todo lifecycle, proactive suppression, action confirmation plans, account login credential handling, and governance audit plans

Verification commands:

```bash
python3 -m pytest runtime_api/tests/test_pipeline_system.py runtime_api/tests/test_pipeline_communication.py runtime_api/tests/test_pipeline_agenda.py runtime_api/tests/test_pipeline_actions.py runtime_api/tests/test_core_pipeline_engine.py -q
python3 scripts/validate-core-pipelines-openclaw.py
```

Observed results:

- pipeline-focused pytest subset after local writeback/retrieval hardening: `73 passed`
- full regression after local writeback/retrieval hardening: `241 passed`
- core pipeline/OpenClaw validation after local writeback/retrieval hardening: 23 stages, all `reasonable: true`; it now includes local writeback materialization, historical trace-reference backfill, and context-pack local retrieval fallback checks
- private event processing validation after Wave 2: 16 reports, all `reasonable: true`
- `git diff --check`: no whitespace errors

Remaining provider/non-behavior work:

- Provider-backed adapters are still not live.
- Registry, routing, slot parsing, and persistence helpers are still partly in `main.py`; this is a maintainability refactor, not a behavior gap.
- Richer visual dashboard UI remains product polish; the local health/governance API is implemented.

## Done Definition

A pipeline is production-ready only when:

- route matching is accurate for positive and negative examples
- required slots are parsed by rules and optionally model-assisted
- missing or conflicting slots produce targeted questions
- external effects are guarded by confirmation
- provider adapters are isolated and testable
- output is semantically reasonable on fixture data
- route trace and execution result are persisted with explicit references
- source document and tests are updated

Command success alone is not enough. Validation must inspect whether the actual titles, slots, evidence ids, missing fields, confirmations, and user-facing outputs are correct.
