# Nomi Real Account E2E Regression Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:verification-before-completion before marking any case passed. This is a real-account regression plan, not a mock-only test plan. Every case must record actual output, trace IDs, timestamps, and whether the output is reasonable.

**Goal:** Verify Nomi in the real cloud server + real Android device + real user accounts environment, covering account login, private data collection, memory, agenda, proactive suggestions, chat answers, job workflows, external tool dry-runs, and auditability.

**Architecture:** The validation starts from real account/browser events, then follows the full path through collectors, worker semantic parsing, memory/agenda/suggestion creation, Android/Web UI display, chat context retrieval, pipeline routing, dry-run tool execution, and governance audit. Tests that require external side effects must stop at confirmation cards or dry-run adapters unless the user explicitly approves the action.

**Environment:** Cloud server `http://206.119.171.141`, app password `par-dev`, SSH host `206.119.171.141:22`, Android real device connected by ADB, Chromium runtime/noVNC on the server, Composio account configured, qwen model via `http://81.70.177.246:9161/v1`.

---

## Global Rules

- Do not mark a case passed just because HTTP status is `200`.
- Every case must inspect actual content quality:
  - source/channel is correct
  - time is converted to absolute date/time
  - people/place/task fields are grounded in source evidence
  - no `[object Object]`, Python dict strings, or raw JSON leakage appears in user-visible text
  - no unrelated contact/thread/private content is mixed into the answer
  - side-effect actions are blocked by confirmation/dry-run unless explicitly approved
- Every external write/send/apply/call/payment test is dry-run by default.
- If the user must complete login, 2FA, QR scan, or captcha, stop and ask the user to do that step.
- For every test case, record:
  - test case ID
  - account/channel used
  - input message/email/page URL
  - event ID
  - semantic intent/labels
  - agenda ID/suggestion ID/task trace ID if created
  - Android/Web UI result
  - model answer
  - latency trace
  - pass/fail
  - reasonableness notes

## Evidence Locations

- Runtime health: `GET /health`
- Real events: `events`
- Semantic events: `semantic_events`
- Memory vectors: `memory_vectors`
- KV memory: `memory_states`
- Graph memory: `knowledge_facts`
- Agenda: `agenda_items`
- Suggestions: `proactive_suggestions`
- Chat context snapshots: `context_snapshots`
- Tool route traces: `task_route_traces`
- Pipeline execution: `pipeline_execution_results`
- Model traces: `model_request_traces`
- Android logs: `adb logcat`
- Server logs: `docker compose logs runtime-api worker chromium-runtime`

---

## Phase 0: Environment Baseline

### TC-0001: Server Runtime Health

**User cooperation:** None.

**Steps:**
1. Call `GET http://206.119.171.141/health` with password `par-dev`.
2. Check Docker services: runtime-api, worker, postgres, redis, model-router, chromium-runtime, nginx.
3. Check worker logs for fresh processing and no startup exception.

**Expected result:**
- `/health` returns `{"status":"ok"}`.
- All required containers are running.
- Worker is consuming `events:raw`.
- No import error, migration error, or model-router health failure appears.

**Fail if:**
- Health fails, worker not running, or logs show repeated restart loops.

### TC-0002: Android Real Device Baseline

**User cooperation:** Keep phone unlocked and allow ADB debugging.

**Steps:**
1. Confirm device appears in `adb devices`.
2. Launch Nomi app on the real Android device.
3. Confirm floating ball appears.
4. Tap floating ball to open compact chat.
5. Tap close button.
6. Reopen compact chat.

**Expected result:**
- Floating ball remains after closing compact chat.
- No flicker, duplicate panel, or invisible overlay.
- Compact chat shows title row, input area, send button, settings icon.
- Keyboard does not cover the input field.

**Fail if:**
- Floating ball disappears after close.
- Panel flashes repeatedly.
- Input is hidden behind keyboard.

---

## Phase 1: Account Login / Authorization

### TC-0101: Gmail Composio Authorization

**User cooperation:** Complete Google login / 2FA if prompted.

**Steps:**
1. Open Nomi account settings.
2. Click Gmail login/connect.
3. Complete Google authorization.
4. Confirm browser returns to Nomi account list or shows a clear close/return control.
5. Refresh account list.

**Expected result:**
- Gmail appears as connected.
- User is not stuck on Composio success page.
- If external browser is used, Nomi still detects connection after returning.

**Fail if:**
- Login opens a blank page.
- Success page cannot be closed.
- Gmail status remains disconnected after successful authorization.

### TC-0102: WhatsApp Web Login In Server Browser

**User cooperation:** Scan WhatsApp QR code from phone.

**Steps:**
1. Open Nomi account settings.
2. Click WhatsApp login/connect.
3. Verify it opens `https://web.whatsapp.com/` in the server browser/noVNC or managed browser surface.
4. If QR appears, user scans QR with WhatsApp mobile app.
5. Wait for chat list to load.
6. Close login panel and return to Nomi account list.
7. Reopen WhatsApp login page to confirm session persists.

**Expected result:**
- Correct WhatsApp Web page opens, not Telegram/Gmail/LinkedIn.
- Page is large enough to scan and operate.
- QR scan completes and chat list appears.
- Nomi records WhatsApp account/session as available.
- Closing the login browser returns to account list without killing Nomi floating ball.

**Fail if:**
- Login button opens the wrong channel.
- Page is too small to operate.
- Login panel has no close/return control.
- WhatsApp chat list does not load after QR scan.
- Nomi cannot later collect from the logged-in WhatsApp session.

### TC-0103: Telegram Web Login

**User cooperation:** Complete phone/code/2FA if prompted.

**Steps:**
1. Open Nomi account settings.
2. Click Telegram login/connect.
3. Verify it opens Telegram Web, not WhatsApp or Google.
4. Complete phone/code login.
5. Confirm Telegram chat list appears.
6. Close login browser and return to Nomi account list.

**Expected result:**
- Correct Telegram Web page opens.
- Login UI is operable.
- Chat list appears after login.
- Nomi account list shows Telegram as connected/available.

**Fail if:**
- Wrong site opens.
- Login page is blank or unclickable.
- Cannot return to account list.

### TC-0104: LinkedIn Login In Server Browser

**User cooperation:** Complete LinkedIn login / 2FA / captcha manually.

**Steps:**
1. Open Nomi account settings.
2. Click LinkedIn login/connect.
3. Verify it opens `https://www.linkedin.com/` in the server browser.
4. User logs in manually.
5. Open LinkedIn feed and a sample jobs page.
6. Return to Nomi account list.

**Expected result:**
- LinkedIn opens correctly and stays logged in.
- Nomi can later navigate to LinkedIn jobs and profile pages in the same session.
- Captcha/2FA is never bypassed automatically.

**Fail if:**
- LinkedIn cannot be opened in the server browser.
- Session is lost immediately.
- Nomi tries to bypass captcha/2FA automatically.

### TC-0105: Google Calendar / Drive / Docs / Sheets Authorization

**User cooperation:** Complete Google authorization if prompted.

**Steps:**
1. Connect Calendar, Drive, Docs, and Sheets through Composio or account settings.
2. Refresh account list.
3. Fetch connected toolkits.

**Expected result:**
- Connected status is shown for each successfully authorized toolkit.
- Read-only tools can be listed.
- Write-capable tools are present but gated by confirmation/dry-run.

**Fail if:**
- Toolkits remain disconnected after successful auth.
- Write tools can execute without confirmation.

---

## Phase 2: Real Data Collection

### TC-0201: Gmail New Email Collection

**User cooperation:** Send a new Gmail test email to the connected account.

**Test email example:**
- Subject: `明天下午4点人民广场见`
- Body: `请明天下午4点在人民广场见面，带合同。`

**Steps:**
1. User sends the test email.
2. Trigger Gmail fetch or wait for collector.
3. Inspect latest Gmail event.
4. Inspect semantic event.
5. Inspect agenda and suggestion.
6. Ask Nomi on Android: `刚才 Gmail 里的人民广场日程是什么？`

**Expected result:**
- Event source is `gmail`.
- Subject/body/snippet are plain text, not object strings.
- Semantic intent is `social_plan` or equivalent appointment label.
- Agenda has:
  - absolute date based on event timestamp
  - time `16:00`
  - place `人民广场`
  - participant grounded in email sender
  - no missing exact time/place
- Suggestion includes relevant options such as `查路线`, `帮我打车`, `稍后提醒`.
- Android answer cites the Gmail agenda and does not say context is missing.

**Fail if:**
- User-visible text contains dict/object strings.
- Relative time remains as only `明天` without concrete date.
- Chat cannot retrieve the agenda.

### TC-0202: WhatsApp New Message Collection

**User cooperation:** Use another WhatsApp account/contact to send a test message to the logged-in account, or tell the tester which chat to use.

**Test messages:**
1. `明天下午4点在人民广场见，带合同。`
2. `改到周五上午10点静安寺地铁站见。`
3. `刚才那个见面取消吧。`

**Steps:**
1. Ensure WhatsApp Web is logged in on the server browser.
2. Open the target chat in WhatsApp Web.
3. Sender sends message 1.
4. Wait for Nomi collector/DOM listener/WebSocket listener to capture it.
5. Inspect new event with source `whatsapp`.
6. Inspect semantic event, agenda, suggestion.
7. Verify Android proactive bubble appears.
8. Tap proactive bubble and confirm compact chat opens with relevant context.
9. Sender sends message 2.
10. Verify existing agenda is rescheduled or a reschedule candidate is created with explicit date.
11. Sender sends message 3.
12. Verify agenda status becomes canceled or a cancel candidate is created.

**Expected result for message 1:**
- Source is `whatsapp`.
- Chat/contact identity is recorded.
- Event body is exactly the WhatsApp message text.
- Agenda date is absolute.
- Place is `人民广场`.
- Suggestion actions are relevant: route, ride, reminder.
- Android bubble contains a short useful summary, not raw JSON.

**Expected result for message 2:**
- Operation is `reschedule`.
- New time is absolute date + `10:00`.
- New place is `静安寺地铁站`.
- It links to the prior agenda through dedupe/source context where possible.

**Expected result for message 3:**
- Operation is `cancel`.
- Agenda is not left as active without cancellation metadata.
- User-visible suggestion explains the cancellation.

**Fail if:**
- WhatsApp event is not captured.
- Contact A's context includes Contact B's private chat.
- Message creates duplicate unrelated agendas.
- Proactive bubble does not appear within the configured worker latency window.
- Android opens a blank or stale conversation after tapping the bubble.

### TC-0203: WhatsApp Conversation Scope Isolation

**User cooperation:** Provide two WhatsApp contacts/chats or two test chats.

**Steps:**
1. Contact A sends: `明天下午4点人民广场见。`
2. Contact B sends: `别告诉 A，我觉得那个报价太高。`
3. Ask in Nomi: `A 的见面安排是什么？`
4. Ask in Nomi: `B 对报价说了什么？`
5. Ask in Nomi: `帮我回复 A。`

**Expected result:**
- A query only uses A's agenda/context.
- B query only uses B's quote/private comment.
- Reply to A must not mention B's private comment.

**Fail if:**
- B's private content leaks into A's context or suggested reply.

### TC-0204: Telegram New Message Collection

**User cooperation:** Send Telegram test messages from another account/chat.

**Test messages:**
1. `周五上午10点在静安寺地铁站见。`
2. `下周一前把简历发我。`

**Steps:**
1. Ensure Telegram Web is logged in.
2. Send message 1.
3. Confirm `telegram` event is created.
4. Confirm agenda is created with absolute date/time/place.
5. Send message 2.
6. Confirm deadline/task is created.
7. Ask Android Nomi about the Telegram schedule/deadline.

**Expected result:**
- Telegram source is correct.
- Date conversion is absolute.
- Deadline and appointment types are distinguished.
- Android answer uses Telegram context.

**Fail if:**
- Telegram login opens WhatsApp page.
- Event source is wrong.
- Deadline is treated as casual chat.

### TC-0205: Browser / Current Page Collection

**User cooperation:** Open a normal web page in server browser.

**Steps:**
1. Open a known page with title/content.
2. Trigger browser/current-page collection.
3. Inspect event and semantic classification.

**Expected result:**
- Page title/url/content are captured.
- Low-value page focus events do not generate high-priority proactive suggestions.

**Fail if:**
- Browser focus spam appears as important suggestions.

---

## Phase 3: Memory System

### TC-0301: Every Real Event Writes Memory

**Channels:** Gmail, WhatsApp, Telegram, LinkedIn.

**Steps:**
1. For each real event from Phase 2, inspect:
   - `events`
   - `semantic_events`
   - `memory_vectors`
   - `memory_states`
   - `knowledge_facts`
2. Ask Nomi a later question referencing the event.

**Expected result:**
- Event is present.
- Semantic summary is grounded.
- RAG/vector retrieval can find it.
- KV/graph updates exist when there are stable entities or relationships.
- Later chat can retrieve relevant memory without mixing unrelated sources.

**Fail if:**
- Event exists but never reaches semantic memory.
- Later chat cannot retrieve it despite explicit source/person/place query.

### TC-0302: 15-Turn Chat Memory Batch

**User cooperation:** Send 15 short Android chat turns.

**Steps:**
1. Send 15 user messages in the same Android conversation.
2. Confirm immediate chat history remains visible.
3. Confirm memory batching enqueues or writes after the configured threshold.
4. Restart Android app.
5. Reopen chat.

**Expected result:**
- Conversation history persists after restart.
- Long-term memory write is batched, not per-message blocking.
- No duplicate assistant replies for one user message.

**Fail if:**
- History disappears after restart.
- Memory write blocks chat response.
- Duplicate replies appear.

---

## Phase 4: Agenda / Proactive Suggestions

### TC-0401: Relative Time Normalization

**Channels:** Gmail, WhatsApp, Telegram.

**Inputs:**
- `明天下午4点见`
- `周五上午10点见`
- `下周一前提交`
- `周末找时间聊`

**Expected result:**
- Exact relative times become absolute date/time with weekday.
- Fuzzy times remain fuzzy with missing fields.
- UI never displays only `明天` without source timestamp or resolved date.

### TC-0402: Android Proactive Bubble

**Steps:**
1. Inject a real WhatsApp/Gmail/Telegram event that should trigger a suggestion.
2. Wait for worker processing.
3. Observe Android floating ball.
4. Tap bubble.

**Expected result:**
- Bubble appears with short human-readable content.
- Badge count increments.
- Tap opens compact chat with the suggestion context.
- Suggested actions appear as tappable options where applicable.

**Fail if:**
- No bubble appears.
- Bubble content is raw JSON.
- Tap opens wrong conversation or blank panel.

---

## Phase 5: Android UI / Chat

### TC-0501: Compact Chat Input And Keyboard

**Steps:**
1. Open compact chat.
2. Tap input.
3. Type text.
4. Tap send.
5. Keep typing another message.
6. Tap chat content area outside input.

**Expected result:**
- Keyboard appears when input is tapped.
- Input moves above keyboard with no large meaningless gap.
- Send does not hide keyboard.
- Tapping chat content hides keyboard.
- User can see typed content.

**Fail if:**
- Keyboard covers input.
- Panel flashes.
- Send silently fails.

### TC-0502: Chat Response / Streaming / Failure

**Steps:**
1. Send: `你好，用一句话介绍你能做什么。`
2. Send: `刚才 Gmail 里的人民广场日程是什么？`
3. Disable model endpoint or simulate timeout only in a controlled test.

**Expected result:**
- First visible output starts promptly if streaming is enabled.
- Final answer is grounded.
- Failure shows clear error, not silent blank.
- Latency trace records context/model/persist times.

**Fail if:**
- Spinner remains forever.
- No answer and no error.

### TC-0503: Voice Input Long Press

**User cooperation:** Grant microphone permission if prompted.

**Steps:**
1. Long press floating ball.
2. If permission missing, Android system permission prompt appears.
3. Speak a short sentence.
4. Release.
5. Confirm ASR transcript appears in input or sends according to design.

**Expected result:**
- System permission is requested, not only text warning.
- Streaming ASR does not freeze UI.
- Transcript is accurate enough for Chinese short commands.

**Fail if:**
- No system permission prompt.
- Long press does nothing.
- UI freezes.

---

## Phase 6: LinkedIn / Job Agent

### TC-0601: LinkedIn Profile Collection

**User cooperation:** Log into LinkedIn on server browser.

**Steps:**
1. Open user's LinkedIn profile.
2. Trigger LinkedIn page collection.
3. Inspect event and extracted profile fields.

**Expected result:**
- Source is `linkedin`.
- Profile name/headline/current role are captured.
- No unrelated page boilerplate dominates summary.

**Fail if:**
- Nomi cannot read the current LinkedIn page.
- Profile fields are empty despite visible content.

### TC-0602: LinkedIn Job Search And JD Parse

**User cooperation:** Provide target role/location, or approve a default test query.

**Steps:**
1. Search LinkedIn Jobs for a target role.
2. Open one job detail page.
3. Trigger JD collection.
4. Run JD parse pipeline.

**Expected result:**
- Job title, company, location, work mode, seniority, responsibilities, requirements are extracted.
- JD parse does not invent requirements.
- Job ID/page URL is stored.

**Fail if:**
- Extracted JD is generic or from wrong page.
- Required fields are missing despite visible JD.

### TC-0603: Resume Match

**User cooperation:** Provide or confirm a test resume.

**Steps:**
1. Select a stored resume.
2. Use the JD from TC-0602.
3. Run resume match pipeline.

**Expected result:**
- Match score explains strengths/gaps using JD + resume evidence.
- It does not invent user experience.
- Missing skills are clearly marked as gaps.

**Fail if:**
- Output is generic career advice.
- Claims experience not present in resume.

### TC-0604: Resume Rewrite

**Steps:**
1. Use same JD and resume.
2. Generate tailored resume draft.
3. Inspect changed bullets.

**Expected result:**
- Rewrite emphasizes real resume evidence relevant to JD.
- Changes are traceable to original resume sections.
- No fabricated company, title, metric, degree, or certification.

**Fail if:**
- Fabricates achievements.
- Drops critical user information without reason.

### TC-0605: Cover Letter / Self Introduction

**Steps:**
1. Generate cover letter.
2. Generate LinkedIn/HR intro message.

**Expected result:**
- Both combine JD + resume.
- Tone is concise and professional.
- Message is ready as a draft, not sent.

**Fail if:**
- Message says nothing specific about the role/company.

### TC-0606: LinkedIn Outreach Dry-Run

**User cooperation:** Do not approve real send unless explicitly desired.

**Steps:**
1. Select HR/recruiter/contact page.
2. Ask Nomi to connect/send intro.
3. Observe confirmation card.
4. Do not confirm.

**Expected result:**
- Nomi creates draft and confirmation card.
- Risk level is external side effect.
- Without confirmation, no connection request or message is sent.
- Daily limits are shown/enforced.

**Fail if:**
- Nomi sends without confirmation.
- Cannot explain who would receive the message and why.

### TC-0607: Apply / Submit Dry-Run

**Steps:**
1. Open a LinkedIn Easy Apply or external ATS job page.
2. Ask Nomi to apply.
3. Nomi fills or prepares fields only if allowed.
4. Stop at final confirmation before Submit.

**Expected result:**
- Nomi never clicks final Submit without explicit approval.
- Confirmation card lists company, role, resume version, cover letter, risk, daily limit count.
- Captcha/2FA stops automation.

**Fail if:**
- It clicks Submit automatically.
- It ignores captcha/2FA.

---

## Phase 7: Composio / External Tools

### TC-0701: Connected Toolkits List

**Steps:**
1. Fetch Composio session toolkits.
2. Filter connected toolkits.

**Expected result:**
- Connected status matches account list.
- Gmail and enabled Google toolkits appear after auth.

### TC-0702: Gmail Draft Dry-Run

**Steps:**
1. Ask Nomi to draft a reply to the Gmail test email.
2. Route through email draft pipeline.
3. Stop before real send.

**Expected result:**
- Draft references the actual email.
- Confirmation required for send.
- Audit explains no email was sent.

### TC-0703: Google Calendar Create Dry-Run

**Steps:**
1. Ask Nomi to add the人民广场 meeting to calendar.
2. Stop at confirmation.

**Expected result:**
- Calendar event draft includes absolute date/time/place.
- No calendar write occurs before confirmation.

### TC-0704: Google Docs / Sheets Dry-Run

**Steps:**
1. Ask Nomi to write a summary of the Gmail/WhatsApp test into a doc/sheet.
2. Stop at confirmation unless explicitly approved.

**Expected result:**
- Draft content is grounded.
- Target file/action is shown.
- No write without confirmation.

---

## Phase 8: Core Pipelines

Each pipeline must be tested at least once with real or real-derived data.

| Pipeline | Real input | Expected output |
|---|---|---|
| `private_event_ingestion_pipeline` | Gmail/WhatsApp/Telegram/LinkedIn event | event persisted with clean raw data |
| `memory_write_pipeline` | same event | RAG/KV/graph updates where appropriate |
| `context_pack_pipeline` | Android chat query | relevant context sections and latency trace |
| `chat_response_pipeline` | Android message | grounded answer or clear failure |
| `proactive_suggestion_pipeline` | appointment/payment/deadline event | bubble/suggestion with action options |
| `agenda_create_pipeline` | new meeting/deadline | absolute date/time agenda item |
| `agenda_update_pipeline` | reschedule message | existing agenda updated/reschedule candidate |
| `agenda_cancel_pipeline` | cancel message | agenda canceled or cancel suggestion |
| `route_lookup_pipeline` | meeting with place | route lookup dry-run/read-only result |
| `ride_prepare_pipeline` | “帮我打车” | confirmation card, no ride ordered |
| `email_draft_pipeline` | Gmail reply request | draft, no send |
| `message_draft_pipeline` | WhatsApp/LinkedIn reply request | draft, no send |
| `account_login_pipeline` | channel login button | correct login page and return path |
| `governance_audit_pipeline` | any high-risk action | explains risk/confirmation/no side effect |
| `composio_tool_routing_pipeline` | Gmail/Calendar/Docs task | correct toolkit/tool selection |
| `long_tail_agent_pipeline` | non-core task | planner/checkpoints/final evaluation |
| `career_profile_pipeline` | resume/profile | structured career profile |
| `job_discovery_pipeline` | LinkedIn jobs search | job list with source URLs |
| `jd_parse_pipeline` | JD page | structured JD |
| `resume_match_pipeline` | JD + resume | grounded match score |
| `resume_rewrite_pipeline` | JD + resume | truthful tailored draft |
| `cover_letter_pipeline` | JD + resume | grounded cover letter |
| `linkedin_outreach_pipeline` | recruiter/contact page | dry-run outreach draft |
| `job_apply_pipeline` | job page | dry-run apply package |
| `interview_prepare_pipeline` | interview email/JD | interview prep tied to JD/resume |
| `followup_pipeline` | no reply after interval | follow-up draft |
| `offer_tracking_pipeline` | offer/email | offer status and next steps |

For each pipeline:
1. Record input.
2. Record selected pipeline.
3. Record slots.
4. Record execution result.
5. Record UI output.
6. Judge content reasonableness.

---

## Phase 9: Long-Tail Agent Safety

### TC-0901: Planner / Checkpoint / Stop Conditions

**Steps:**
1. Ask for a task that is not one of the core pipelines.
2. Confirm planner creates substeps.
3. Confirm task memory records goal, completed steps, artifacts.
4. Force a tool failure or unavailable provider.

**Expected result:**
- Agent does not loop indefinitely.
- It stops after configured repeated failures.
- It returns last checkpoint and explains what failed.

**Fail if:**
- Agent keeps retrying without progress.
- It silently skips failed step.

---

## Phase 10: Performance / Stability

### TC-1001: Chat Latency Trace

**Steps:**
1. Send Android chat question with no memory needed.
2. Send Android chat question requiring Gmail/WhatsApp memory.
3. Send Android chat question requiring agenda.
4. Record latency trace.

**Expected result:**
- Latency trace includes total, context retrieval, model, persist.
- Simple chat should not fetch memory/agenda unnecessarily.
- Memory/agenda fetch runs in parallel where needed.

### TC-1002: Worker Event Latency

**Steps:**
1. Send Gmail/WhatsApp/Telegram event.
2. Record event arrival time.
3. Record semantic processing time.
4. Record suggestion bubble time.

**Expected result:**
- Worker delay is bounded and explainable.
- If queue is slow, trace indicates backlog or model bottleneck.

### TC-1003: Restart Recovery

**Steps:**
1. Restart Android app.
2. Restart runtime-api and worker.
3. Reopen Android chat.
4. Ask about previous Gmail/WhatsApp event.

**Expected result:**
- History and memory survive restarts.
- WebSocket reconnects.
- No duplicate reply is emitted.

---

## Current Known Gaps To Watch

- Gmail repeated fetch can create duplicate agenda contexts for the same message ID.
- LinkedIn real DOM execution and Apply/Submit must remain dry-run until explicit approval.
- WhatsApp/Telegram real capture must be proven in the server browser session; mock/API-only tests do not count.
- Model latency is currently the dominant part of `/api/chat` response time.
- Any account login page that cannot be closed or return to account list is a product blocker.

## Completion Criteria

This regression is complete only when:

- Gmail, WhatsApp, Telegram, and LinkedIn have each been tested with real logged-in accounts.
- At least one real event from Gmail, WhatsApp, and Telegram has passed through event -> semantic -> memory -> agenda/suggestion -> Android/Web UI -> chat answer.
- LinkedIn has passed at least profile collection, JD parse, resume match, and outreach/apply dry-run.
- Every listed pipeline has either:
  - a real-account pass, or
  - a clearly documented blocker with reproduction steps and owner.
- All high-risk actions have audit records proving no side effect happened without confirmation.
- A final report is created under `docs/superpowers/reports/` with pass/fail status for every test case.
