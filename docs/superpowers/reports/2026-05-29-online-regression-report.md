# Nomi Online Regression Report

**Run id:** `rg-20260529-001`

**Target:** Online cloud deployment at `206.119.171.141`

**Test plan:** [2026-05-29-online-regression-test-cases.md](/Users/wrf/Documents/background/docs/superpowers/plans/2026-05-29-online-regression-test-cases.md)

**Execution rule:** A case is not passed by HTTP status alone. Each result below includes content-level judgment and trace/evidence checks where available.

---

## Phase 0: Online Preflight

### RG-PRE-001: Service Health And Auth Gate

**Status:** Passed

**Evidence:**
- `GET /health` returned `{"status":"ok"}`.
- `GET /` returned `200` and contained the Nomi/PAR app marker.
- Unauthenticated `POST /api/chat` returned `401` with `invalid password`.
- Authenticated `GET /api/memory/status` returned embedding status: provider `fastembed`, model `sentence-transformers/all-MiniLM-L6-v2`, dimensions `384`.

**Content judgment:** The outputs are structurally correct and meaningful. The service is reachable, the app is served, protected chat is not public, and memory/vector status is explicit.

### RG-PRE-002: Model Endpoint And Controlled Timeout

**Status:** Passed

**Evidence:**
- `POST /api/chat` with `ping rg-20260529-001` returned `200`.
- Answer preview: `Ping 已收到。我在线，随时待命。请问有什么具体任务或问题需要处理？`
- `context_pack_id`: `ctx_c1a594cbdd4346afa8efac8016dbbbc6`
- Token budget: `input_used=10875`, `hard_input_ceiling=212000`, tokenizer backend `conservative_char_estimator`.

**Content judgment:** The answer is short, operational, and does not invent private facts. The context pack is present and under budget. The tokenizer is still using the explicit conservative fallback because `CONTEXT_TOKENIZER_MODEL` is not configured online.

### RG-PRE-003: Realtime WebSocket Channel

**Status:** Passed

**Evidence:**
- WebSocket connected to `/ws`.
- Sent `{"type":"ping"}`.
- Received `{"type":"pong"}`.

**Content judgment:** The realtime channel is alive and can deliver future proactive messages.

### RG-PRE-004: Composio And OpenClaw Capability Status

**Status:** Passed With Configuration Note

**Evidence:**
- Composio status returned `configured=true`, `reachable=true`, user id `nomi_owner`.
- Read-only toolkits configured: `gmail`, `googlecalendar`, `googledrive`, `googledocs`, `googlesheets`, `googletasks`, `google_maps`, `github`, `slack`, `notion`.
- Write toolkits configured: `gmail`, `googlecalendar`, `googledrive`, `googledocs`, `googlesheets`, `googletasks`, `github`, `slack`, `notion`, `todoist`, `linear`, `jira`.
- Toolkit sync endpoint returned `200` with 10 toolkit entries.
- OpenClaw execute returned `mode=dry_run`, `status=blocked`, `needs_confirmation=true`, reason `OPENCLAW_ENABLED is not true; live OpenClaw execution is disabled.`

**Content judgment:** Composio is configured and reachable. OpenClaw correctly refused live execution in safe dry-run/gated mode; this is acceptable for regression because no external action should run during preflight.

---

## Running Notes

- Do not remove synthetic artifacts until final trace checks are complete.
- Any provider authorization gap should be recorded separately from local pipeline behavior.

---

## Phase 1-2: WhatsApp/Gmail Ingestion, Memory, Agenda

**Evidence artifacts:**
- Compact data/agenda/pipeline dump: [2026-05-29-online-regression-phase12-compact.json](/Users/wrf/Documents/background/docs/superpowers/reports/2026-05-29-online-regression-phase12-compact.json)
- Exact inspection helper: [online-regression-phase12-summary.py](/Users/wrf/Documents/background/scripts/online-regression-phase12-summary.py)
- Compact inspection helper: [online-regression-compact-checks.py](/Users/wrf/Documents/background/scripts/online-regression-compact-checks.py)

### RG-WA-001: WhatsApp Exact Meeting

**Status:** Failed

**Evidence:** Event `bfb3dc1d-11f5-4b1b-8aaa-3640c3b44f74` was stored, semantically classified as `约定`, and has one vector. Trace returned `200` with memory, fact, agenda, version, and suggestion.

**Content judgment:** Storage and retrieval work, but the exact time `下午3点` was over-redacted to `AMOUNT_1点`. The agenda became `certainty=fuzzy`, `missing_fields=["exact_time"]`, not the expected exact Saturday 15:00 agenda. The proactive suggestion also only offered `稍后提醒/忽略`, missing expected route/ride actions for a meeting at 武康路.

**Gap:** Sensitive-value protection is incorrectly masking ordinary time digits and the regression id; exact schedule semantics are lost.

### RG-WA-002: WhatsApp Fuzzy Meeting

**Status:** Failed

**Evidence:** Event `b14427f6-38ff-4063-9ec0-fc0d50604af8` was stored, classified as appointment/commitment, and vectorized.

**Content judgment:** The message was correctly understood as a vague meeting proposal, and no exact place/time was invented. However, no agenda item was created for the fuzzy appointment, which violates the expected behavior.

**Gap:** Fuzzy appointments can produce suggestions without a corresponding fuzzy agenda record.

### RG-WA-003: Reschedule

**Status:** Failed

**Evidence:** Event `6ea3984e-888f-41dd-90fa-d1b981c54d70` was classified as `改期`, vectorized, and produced agenda `1d36007c-5ab6-4f60-9258-6a90a644012f`.

**Content judgment:** The agenda title and place are plausible, but the system created a new agenda instead of updating the previous Alice meeting. The agenda version operation is `create`, even though the reason says reschedule. The old Saturday item remains active, and `10点` was redacted to `AMOUNT_1点`, so the latest exact time cannot be represented.

**Gap:** Reschedule matching/update is incomplete, and exact time redaction breaks schedule updates.

### RG-WA-004: Cancellation

**Status:** Failed

**Evidence:** Event `c0c9ee65-9cb6-4b8e-a2c0-cbbd5154ce96` was classified as `取消`; agenda `60c1c774-a18a-4e78-8ca9-61b395f26484` has `status=canceled`.

**Content judgment:** The cancellation itself is recognized, but because RG-WA-002 did not create a fuzzy Bob agenda, this does not update an existing agenda. Worse, the cancellation event still produced an open proactive suggestion with `查路线/帮我打车/稍后提醒`, which is semantically wrong for a canceled meeting.

**Gap:** Cancellation handling should suppress travel actions and close/suppress stale meeting suggestions.

### RG-WA-005: Contact Scope And Leakage

**Status:** Passed With Minor Classification Gap

**Evidence:** Alice quote event `ac19363b-44d2-4762-8b83-48d28a877a92` and Bob private signal `68d1964c-7f35-48cc-b3bc-0613aabc6a09` were stored and vectorized. Reply pipeline output for Alice drafted `PHONE_1 报价我会尽快确认`, with leakage review `passed`, no matched private terms, and external message confirmation required.

**Content judgment:** The important safety property holds: Bob's private statement was not inserted into the outbound Alice draft. However, Bob's private signal has `intent=关系信号` but `primary_label=todo`, which is inconsistent.

**Gap:** Relationship signals should keep `relationship_signal` as primary label unless there is a stronger task label.

### RG-GM-001: Gmail Quote Deadline

**Status:** Failed

**Evidence:** Event `9c16ead6-df13-4584-84eb-f3c3b89dc195` was stored, vectorized, searchable, and agenda `a0380761-519a-4217-a620-5c68fc9ebd5d` was created.

**Content judgment:** Search returns the correct quote/deadline email and the answer preserves `Friday 18:00`. The agenda records `Friday 18:00`, but still marks `certainty=fuzzy` and `missing_fields=["exact_time"]`. The email pipeline for `请处理 PHONE_1 报价邮件` routed to `email_pipeline` but returned `needs_user_input` with missing `mailbox` and `email_intent`, even though the source event and thread context were supplied.

**Gap:** Email agenda certainty is too conservative for `Friday 18:00`; email pipeline does not fill obvious mailbox/intent from source context, and the clarification question is English.

### RG-GM-002: Gmail Invoice/Payment

**Status:** Failed

**Evidence:** Event `e6adbb95-1147-4c16-83b2-fa369dcd2661` was stored, vectorized, classified as `付款`, and payment agenda `1381bd98-e593-4b51-b8ac-4d7325b3002c` was created.

**Content judgment:** The system recognizes payment/deadline semantics and does not pay. But invoice id `INV-RG-1001` and amount `1200 USD` were over-redacted into `INV-RG-AMOUNT_1` and `AMOUNT_1`. Request `帮我处理 INV-RG-1001` incorrectly routed to OpenClaw instead of `payment_bill_pipeline`, then blocked.

**Gap:** Invoice ids and amounts need task-aware redaction/release. Payment intent routing must use memory/source context to choose `payment_bill_pipeline`.

### RG-GM-003: Gmail Reply Draft

**Status:** Passed

**Evidence:** Event `6c770a12-d99b-4aef-8093-a7db8c86911c` was stored and vectorized. Reply pipeline produced `draft_ready` with channel `gmail`, recipient `RG_Alice`, draft `我会先核对利润率`, and `external_message` confirmation required.

**Content judgment:** Draft content is grounded and no send action occurred.

---

## Phase 3: Proactive Messaging

**Evidence artifact:** [2026-05-29-online-regression-phase3-proactive.json](/Users/wrf/Documents/background/docs/superpowers/reports/2026-05-29-online-regression-phase3-proactive.json)

### RG-PRO-001: Proactive Card Delivery

**Status:** Passed With Content Degradation

**Evidence:** WebSocket returned `pong`, then received `proactive_message` for suggestion `f53f8bdc-7c45-4a32-829e-195d7f1e4155`, with body `...周日上午AMOUNT_1点...武康路` and actions `查路线/帮我打车/稍后提醒`.

**Content judgment:** Realtime delivery and action payload shape are correct. The displayed message still contains `AMOUNT_1点`, so the card is not user-quality for exact schedule use.

### RG-PRO-002: Dedup/Cooldown

**Status:** Partially Verified

**Evidence:** Current table state has one suggestion per tested source event; `ON CONFLICT (source_event_id)` behavior prevents duplicate rows for the same event.

**Content judgment:** DB-level duplicate suppression exists, but the planned "run proactive evaluation twice and observe no second bubble" was not fully exercised.

**Gap:** Need an explicit proactive evaluation endpoint/test hook to run dedupe without replaying Redis messages manually.

### RG-PRO-003: Suggestion Action Handoff

**Status:** Failed

**Evidence:** Both `route_lookup` and `ride_prepare` action calls returned HTTP `500`.

**Root cause:** Runtime logs show `psycopg.ProgrammingError: cannot adapt type 'dict' using placeholder '%s'` inside `persist_task_route_trace()`. JSONB fields are being inserted as raw Python dicts instead of JSON-wrapped values.

**Content judgment:** The card can display and push, but clicking actions is broken online.

---

## Phase 4-8: Chat, Pipelines, OpenClaw, Composio, Audit

**Evidence artifact:** [2026-05-29-online-regression-phase4-8.json](/Users/wrf/Documents/background/docs/superpowers/reports/2026-05-29-online-regression-phase4-8.json)

### Chat And Core Pipelines

| Case | Status | Content Judgment |
| --- | --- | --- |
| RG-CHAT-001 | Failed | Answer correctly avoided inventing a time, but reported two Alice meetings because reschedule did not update the original and times were redacted. Expected latest Sunday 10:00. |
| RG-CHAT-002 | Passed | Short `可以` was resolved using assistant context; answer said it would check cost/margin and draft a reply. |
| RG-CHAT-003 | Passed With Audit Gap | Reply route/pipeline/chat produced a confirmation-gated draft and no Bob leakage. Route trace persistence failed with dict JSONB error. |
| RG-CHAT-004 | Passed With Audit Gap | Route lookup selected `route_pipeline`, read-only risk, destination `武康路`, no confirmation. Route trace persistence failed. |
| RG-CHAT-005 | Passed With Audit Gap | Ride selected `ride_pipeline`; missing pickup blocks booking; with pickup it prepares options and still requires final confirmation. Route trace persistence failed. |
| RG-CHAT-006 | Failed | Ambiguous payment correctly asks for bill/counterparty, but invoice-specific request still routes to OpenClaw instead of payment pipeline. |
| RG-CHAT-007 | Passed With Audit Gap | Shopping request selects `shopping_pipeline`, prepares purchase plan, blocks purchase pending confirmation. Route trace persistence failed. |
| RG-CHAT-008 | Failed | Document lookup request routed to `personal_search_pipeline` and found no evidence, not `document_file_pipeline`; write action gates correctly but slot extraction produced poor `file_or_query`. |
| RG-CHAT-009 | Passed | Private analysis may use price sensitivity locally; outbound draft to Alice does not mention Bob and remains confirmation-gated. |

### Pipeline Matrix

| Case | Status | Content Judgment |
| --- | --- | --- |
| RG-PIPE-001 | Failed | `/api/tools/catalog` exposes tools but not the 18 core pipeline registry, so online registry validation cannot confirm all pipeline definitions. |
| RG-PIPE-002 | Failed | Pipeline execution result persists, but `/api/tools/route/traces?q=RG_Alice` returned empty because route trace persistence fails. |
| RG-PIPE-003 | Failed | Route slot parser keeps destination `武康路`, but reply parser did not infer recipient `RG_Alice` from UI/source scope for `帮我回复她...`. |

### OpenClaw

| Case | Status | Content Judgment |
| --- | --- | --- |
| RG-OPEN-001 | Failed | Unsupported form routes to OpenClaw with good allowed/forbidden actions and minimal context, but job creation returns HTTP `500` with the same raw dict JSONB adaptation error. |
| RG-OPEN-002 | Partially Passed | Login route redacts/minimizes context; field release endpoint creates approval id `sfr_d1134a1dfb20e883`. Rebuild/use of the released field was not completed because OpenClaw job creation is broken. |

### Composio

| Case | Status | Content Judgment |
| --- | --- | --- |
| RG-COMP-001 | Blocked By Permission | Composio is configured and reachable, but all listed readonly toolkits are `connected=false`. This is an authorization state, not a local routing failure. |
| RG-COMP-002 | Failed | Calendar route is correct and gated. Maps route for `查去武康路的路线` misroutes to `ride_pipeline`; Drive document request routes to personal search instead of document pipeline. |

### Governance And Trace

| Case | Status | Content Judgment |
| --- | --- | --- |
| RG-AUDIT-001 | Failed | Event traces include semantic event, memory vector, fact, agenda, and suggestion, but route traces are absent due persistence failure. |
| RG-AUDIT-002 | Passed With Audit Gap | Chat answer for quote deadline is grounded (`周五 18:00`) and conversation trace has context snapshot. Route/pipeline trace sections are empty for the chat. |
| RG-AUDIT-003 | Passed With Cleanup Caveat | Regression artifacts are discoverable by the redacted marker `rg-PHONE_1`; original `rg-20260529-001` was over-redacted, so cleanup must use event ids or `rg-PHONE_1`. |

---

## High Priority Failures Found

1. **Unhandled 500 in route trace/OpenClaw persistence.** `persist_task_route_trace()` and `enqueue_openclaw_execution_job()` insert dicts into JSONB columns without JSON adaptation. This breaks suggestion buttons and OpenClaw jobs.
2. **Over-redaction destroys schedule and invoice semantics.** `3点`, `10点`, `1200 USD`, `INV-RG-1001`, and even `rg-20260529-001` became `AMOUNT_1`/`PHONE_1`.
3. **Agenda update semantics are incomplete.** Fuzzy meetings are missing, reschedules create duplicates, cancellations create new canceled items and can still show travel actions.
4. **Task routing gaps remain.** Invoice handling routes to OpenClaw instead of payment pipeline; Drive/document lookup routes to personal search; Maps route phrase can route to ride.
5. **Trace/audit explicit references are still unreliable.** Route traces are empty or not linked; many pipeline responses have `source_event_ids=null` even when context provided.
6. **Pipeline slot parser still misses context.** `帮我回复她...` with Alice UI scope fails to resolve recipient.
7. **Composio toolkits are configured but not connected.** Provider calls are blocked by account authorization, while local routes should continue to work.

## Local Fix Pass

**Status:** Fixed locally, pending online redeploy/regression.

**Code-level fixes completed:**
- JSONB persistence now wraps task route decisions, OpenClaw packets/guards/events, and OpenClaw last results with psycopg `Jsonb`, preventing the `cannot adapt type 'dict'` 500s.
- Route intent priority now keeps route-only requests such as `查去武康路的路线` on `route_pipeline`, while explicit ride verbs still route to `ride_pipeline`.
- Invoice identifiers such as `INV-RG-1001` now route to `payment_bill_pipeline` and fill `amount_or_bill` when counterparty context is available.
- Quote/document requests such as `帮我找一下 PHONE_1 报价单，并总结给我` now route to `document_file_pipeline` and extract `PHONE_1 报价单` as the file/query.
- Reply slot parsing now uses the active source scope for pronouns such as `她/他/对方`, resolving Alice-like active conversations without relying on the model.
- Pipeline execution results now expose explicit `source_event_ids`, `conversation_id`, `suggestion_id`, and `agenda_item_ids` at top level as well as inside `input`.
- `/api/pipelines/registry` now exposes the 18 core pipeline definitions.
- Masking rules no longer turn Chinese clock times (`3点`, `10点`), invoice ids, or regression ids (`rg-20260529-001`) into amount/phone placeholders.
- Chinese appointment labels/intents from the semantic model now create fuzzy agenda candidates when exact time/place is absent.
- Cancellation suggestions no longer offer route or ride actions.

**Local verification:**
- `python3 -m pytest -q` passed with `267 passed`.
- Manual content checks confirmed:
  - `查去武康路的路线` -> `route_pipeline`, destination `武康路`.
  - `帮我处理 INV-RG-1001` with counterparty context -> `payment_bill_pipeline`, confirmation required, no payment executed.
  - `帮我找一下 PHONE_1 报价单，并总结给我` -> `document_file_pipeline`, read-only summarize action.
  - `帮我回复她，就说周五八点可以` with Alice active scope -> `reply_pipeline`, `draft_ready`, no send.
  - Cancelled meeting suggestions -> `snooze/open_source`, no route/ride.

**Remaining after local fix:** Superseded by the online verification section below.

## Online Fix Verification

**Status:** High-priority runtime failures fixed online; historical pre-fix data still needs a fresh Phase 1-2 ingestion run for a fully clean report.

**Deployment actions:**
- Rebuilt and restarted `runtime-api` on the cloud server after code fixes.
- Rebuilt and restarted `worker` for the memory/agenda/suggestion fixes.
- Updated Nginx to use Docker DNS dynamic resolution for `runtime-api` and long read/send timeouts on `/`, then force-recreated the Nginx container. This matters because a single-file bind mount can otherwise keep the old config inode after `rsync`.

**Fresh online verification:**
- `GET /health` through public Nginx returned `200`.
- `GET /api/pipelines/registry` returned `count=18`.
- Route-only request `查去武康路的路线` now selects `route_pipeline`, read-only, destination `武康路`.
- Invoice request `帮我处理 INV-RG-1001` with the source Gmail event now selects `payment_bill_pipeline`, resolves `counterparty=RG_CFO` and `amount_or_bill=INV-RG-1001`, and remains `confirmation_required`.
- Document request `帮我找一下 PHONE_1 报价单，并总结给我。` now selects `document_file_pipeline`, resolves clean `file_or_query=PHONE_1 报价单`, and runs as read-only summarize.
- Reply request with active Alice scope resolves `recipient=Alice/RG_Alice`, produces a draft, and does not send.
- OpenClaw route trace/job creation no longer 500s. The test job is queued and `run-once` safely returns dry-run blocked because live OpenClaw execution is disabled.
- New WhatsApp meeting/cancellation events are processed asynchronously by worker into semantic events, agenda items, and proactive suggestions. Meeting suggestions include `查路线 / 帮我打车 / 稍后提醒`; cancellation suggestions only include local/review actions and no travel action.

**Phase 4-8 long-timeout rerun artifact:**
- [2026-05-29-online-regression-phase4-8-rerun-long-timeout.json](/Users/wrf/Documents/background/docs/superpowers/reports/2026-05-29-online-regression-phase4-8-rerun-long-timeout.json)
- With `REGRESSION_HTTP_TIMEOUT_SECONDS=240`, all Phase 4-8 HTTP checks returned `200` or safe dry-run statuses. Earlier `504` results were caused by Nginx/read timeout and script timeout, not by route/pipeline logic.

**Remaining risks/gaps:**
- The old Phase 1-2 artifacts were ingested before masking fixes, so they still contain historical placeholders such as `AMOUNT_1` in stored summaries. They are not retroactively corrected.
- Composio sessions are configured and reachable, but listed toolkits are still `connected=false`; this is an account authorization gap.
- Qwen chat latency is high under sequential regression load; some chat calls exceeded the previous 90 second script timeout. Nginx no longer cuts them off, but UX/performance still needs monitoring.

## Final Regression Status

**Status:** Fixed for the high-priority runtime failures found in this pass; full fresh ingestion regression still pending.

The online stack is alive, route/pipeline/OpenClaw JSONB failures are fixed, Nginx no longer breaks after `runtime-api` rebuilds, and no-send/no-book/no-pay confirmation behavior remains intact. A clean full pass still requires rerunning Phase 1-2 with fresh post-fix synthetic data and connecting the desired Composio accounts.
