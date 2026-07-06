# WhatsApp Full Regression Run

Date: 2026-07-01
Plan: `docs/superpowers/plans/2026-07-01-whatsapp-full-regression-test-plan.md`
Cloud: `http://206.119.171.141`
Android device: `DQYTCYFMO7VSEAJB`
Status: remediated for Batch A API/DB verification - 初始真实 WhatsApp 链路发现关键缺陷；已完成针对性修复、数据清理和线上复验。Android 真机视觉截图未在最终修复后重新采集，仍需单独补 UI 证据。

## Baseline

### W0.1 Cloud Services

Commands executed:

```bash
curl -m 12 -fsS http://206.119.171.141/health
curl -m 12 -fsS -H 'x-par-password: par-dev' http://206.119.171.141/api/collectors/status
curl -m 12 -fsS http://206.119.171.141/collectors/health
ssh root@206.119.171.141 'cd /opt/nomi && docker compose -p nomi ps'
```

Observed:

- `/health`: `{"status":"ok"}`.
- Docker services running:
  - `nomi-chromium-runtime-1`: up, port `6080`.
  - `nomi-runtime-api-1`: up.
  - `nomi-worker-1`: up.
  - `nomi-model-router-1`: up and healthy.
  - `nomi-postgres-1`: up and healthy.
  - `nomi-redis-1`: up and healthy.
  - `nomi-nginx-1`: up, port `80`.
- `/api/collectors/status` for WhatsApp:
  - `enabled=true`.
  - `paused=false`.
  - `health_status=healthy`.
  - `browser_login_status=logged_in`.
  - `collection_status=healthy`.
  - `status_label=已登录`.
  - `status_detail=WhatsApp Web 已登录，可采集当前可见页面。`
  - Initial details: URL `https://web.whatsapp.com/`, title `(2) WhatsApp`, line count `23`, confidence `0.8`.
  - After opening the target chat: title `(1) WhatsApp`, line count `33`, `login_state=logged_in`.
- `/collectors/health` includes a stale/parallel `runtime` degraded entry: `Chromium unavailable: All connection attempts failed`, but the WhatsApp collector itself is currently healthy with fresh update time `2026-07-01T11:16:59Z`.

Conclusion:

- PASS for WhatsApp regression entry condition.
- Note: keep watching runtime health because the global health list still contains a non-WhatsApp degraded runtime record.

### W0.2 Android UI

Commands executed:

```bash
adb devices
adb exec-out screencap -p > /tmp/nomi-whatsapp-regression/w0-device.png
```

Observed:

- `adb devices`: `DQYTCYFMO7VSEAJB device`.
- Screenshot: `/tmp/nomi-whatsapp-regression/w0-device.png`.
- Real device is unlocked, on home screen, Nomi floating ball is visible.
- No stale modal or blocking browser page is visible.

Conclusion:

- PASS for Android entry condition.

## Message Batch A

The user intentionally sent natural WhatsApp messages instead of synthetic `NOMI_WA_REG_*` prefixes, which is closer to real production behavior. The messages were sent as separate messages:

```text
请记住：我的测试暗号是海盐拿铁。 测试码P1
明天下午3点半在人民广场见，带合同。 测试码M1
周五18点前把报价单发我，记得核对成本和利润率。 测试码T1
哈哈哈今天太阳真大。 测试码N1
```

Pre-check:

- `events` containing `测试码P1/M1/T1/N1`: initially `0` before user send.
- `memory_items` containing `海盐拿铁`: initially `0`.
- There are existing older `人民广场` agenda/suggestion rows from previous tests, including `NOMI_REG_WA_0629` and `NOMI_DEDUPE_PROBE_0701`.
- Therefore new case pass/fail must be based on `测试码P1/M1/T1/N1` markers and source-event linkage, not only by location keywords.

## Case Results

### W1 WhatsApp Ingestion

Expected:

- All four messages should be captured as four separate `whatsapp_message` events.
- Sender should be the real counterparty, not the previous message text.
- Chat-list preview may capture the latest preview, but opening the chat must not corrupt sender/message pairing.

Observed:

- Initial chat-list capture only collected M1 and N1:
  - M1 event `8f2589c5-0849-5f3b-a766-01a531d94cd4`, sender `大刚`, scope `chat_list_preview`.
  - N1 event `e4fe33d6-3d29-5bbb-b2bf-04b205142c19`, sender `大刚`, scope `chat_list_preview`.
- After opening the chat, all four messages appeared in the DOM and were persisted, but the parser produced corrupted rows:
  - P1 event `fe203b25-46cd-51b2-aa1f-a028727c0871`, sender incorrectly became `你好呀`.
  - M1 event `15c533d8-2a82-57d8-a87b-d9f5712008b3`, sender incorrectly became the P1 message text.
  - T1 event `fa78b991-ebe7-538b-864d-ac0ce3e92206`, sender incorrectly became the M1 message text.
  - N1 event `fad05188-09a3-5236-a5e1-470994339d5d`, sender incorrectly became the T1 message text.
  - A noise row `c60f094f-1f98-5455-8120-5423c522724d` was emitted with message `输入消息`.
  - A mutation observer row `f3fb6cf5-59f8-5c91-87c6-6628f8f2c6ca` merged encryption notice, P1, M1, T1, N1, timestamps, and input UI into one giant message.

Conclusion:

- FAIL.
- The collector is not production-safe yet. It captures real content, but opened-chat parsing corrupts message ownership and creates merged/noise events.

### W2 Memory Write And Recall: P1 Secret

Expected:

- P1 should be stored as a user/counterparty fact: `测试暗号=海盐拿铁`.
- Asking `我在 WhatsApp 里说的测试暗号是什么？` should answer `海盐拿铁`.

Observed:

- P1 was stored in `memory_vectors`, but semantic classification was `generic_event` / `ordinary_chat`; it was not promoted into reliable KV/graph fact memory.
- API question `wa-reg-0701-q-secret-2` answered `不确定`.
- The context pack did not include the P1 WhatsApp source event even though the raw event existed.

Conclusion:

- FAIL.
- Memory persistence exists, but recall/routing and fact extraction do not satisfy this use case.

### W3 Agenda Creation: M1 Meeting

Expected:

- M1 should create exactly one agenda item:
  - Date: `2026-07-02`.
  - Time: `15:30`.
  - Place: `人民广场`.
  - Participant: `大刚` or the WhatsApp chat counterparty.
  - Reminder policy: offline event, at least 40 minutes before.

Observed:

- Multiple agenda rows were created for the same meeting.
- Time was parsed as `2026-07-02T15:00:00+08:00`, not `15:30`.
- One duplicate agenda had participant incorrectly set to the P1 message text.
- The merged mutation-observer event created a bogus agenda with title beginning `消息和通话已进行端到端加密...` and time `2026-07-02T07:53:00+08:00`, incorrectly using an old visible chat timestamp.
- Asking `人民广场会面的具体日期和时间是什么？` returned older June agenda records, not the fresh July 2 WhatsApp meeting.

Conclusion:

- FAIL.
- Date anchoring partially works, but `点半` parsing, dedupe, source filtering, and agenda retrieval ranking are wrong.

### W4 Noise Handling: N1 Weather Chat

Expected:

- N1 should be stored as ordinary chat.
- It should not generate agenda, task, or proactive suggestion.

Observed:

- Initial N1 preview was correctly classified as `chat` / ordinary chat.
- After opening the chat, N1 was also included inside the merged mutation-observer event that generated a bad agenda and proactive suggestion.

Conclusion:

- PARTIAL FAIL.
- Single-message classification is acceptable, but merged-event filtering is not.

### W5 Deadline / Todo Detection: T1 Quote

Expected:

- T1 should be classified as a deadline/task:
  - Deadline: `2026-07-03 18:00` if current date is `2026-07-01` and “周五” means the nearest upcoming Friday.
  - Action: send quotation sheet.
  - Checklist: verify cost and profit margin.

Observed:

- T1 event `fa78b991-ebe7-538b-864d-ac0ce3e92206` was classified as `generic_event` / `ordinary_chat`.
- No proper deadline/task was surfaced in chat.
- Asking `报价单什么时候截止？需要做什么？` answered that no quotation-sheet information existed.

Conclusion:

- FAIL.
- Deadline/todo rules do not cover a realistic WhatsApp business message.

### W12 Proactive Suggestion

Expected:

- M1 should generate a single useful proactive suggestion such as `明天 15:30 人民广场见，建议 14:50 左右提醒/查路线/打车`.
- T1 should generate a task/deadline suggestion.
- P1 and N1 should not generate urgent proactive suggestions.
- UI bubble should not show DOM/system noise.

Observed:

- Correct-ish M1 suggestion exists, but it uses the wrong parsed time inherited from agenda.
- A bad snapshot suggestion exists: `(2) WhatsApp`.
- A bad mutation-observer suggestion exists with body beginning `消息和通话已进行端到端加密...`.
- Real Android screenshot `/tmp/nomi-whatsapp-regression/w-after-user-sent.png` shows a proactive bubble with WhatsApp encryption notice noise, not the user’s actual event/task.

Conclusion:

- FAIL.
- Proactive suggestion generation must filter snapshots, UI chrome, encryption notices, merged chat bodies, and input placeholders before any user-facing notification.

## Current Blocking / Failure Summary

1. WhatsApp opened-chat parser corrupts sender/message pairing.
2. WhatsApp mutation observer can merge a full chat transcript into one event.
3. UI/system text such as encryption notices, `(1) WhatsApp`, `(2) WhatsApp`, and `输入消息` is allowed into semantic processing.
4. `明天下午3点半` is parsed as `15:00`, not `15:30`.
5. Deadline/todo messages like `周五18点前把报价单发我` are missed.
6. Fresh WhatsApp agenda is not preferred in chat answers; old agenda rows are retrieved instead.
7. Proactive Android bubble can display noise and duplicates.

## Initial Verdict

This regression does **not** pass. The system can see WhatsApp Web and persist some events, but the end-to-end product behavior is not reliable enough for release because it produces wrong agenda times, noisy proactive suggestions, and incorrect answers to direct questions about the messages that were just sent.

## Remediation Summary

The first run exposed real defects instead of synthetic-test noise. The fixes below were implemented and deployed to the cloud server:

1. Agenda dedupe no longer depends on unstable WhatsApp participant extraction for exact-time events. The key now uses normalized start time, semantic text hash, and place when available. This prevents the same message from creating duplicates just because one observer path identified the participant as `大刚` and another path misread it as nearby chat text.
2. Active agenda retrieval now excludes dated past items by default unless the user explicitly asks for previous/history items.
3. Agenda retrieval now prefers exact place matches when the query names a specific place, so a query about `人民广场` no longer pulls unrelated `上海博物馆` or older same-key meetings.
4. Duplicate agenda rows from the initial faulty run were merged or dismissed:
   - Kept M1 agenda `8858f95d-248a-41cb-acf6-181ca56aa6c0`.
   - Dismissed duplicate M1 agenda `84f6d5dd-39b3-4a61-a80d-fe3eadd0dcc0`.
   - Kept T1 agenda `fa9d8ba2-40d8-4427-9684-1c56d6a7f374`.
   - Dismissed duplicate T1 agenda `8e3accb9-4ca7-4a3d-b349-baff51041913`.
   - Dismissed old explicit-regression `NOMI_REG_WA_0629` agenda and the merged UI-transcript agenda that included encryption notice/input chrome.
5. Reminder rows were regenerated from the canonical agenda rows:
   - Offline appointment M1 uses 40-minute lead time and offers `查路线`, `帮我打车`, `稍后提醒`.
   - Deadline T1 uses 60-minute lead time and offers `查看待办`, `稍后提醒`.
   - The old incorrect “打开会议” reminder for T1 was canceled.

## Fresh Verification After Fix

### Local Regression Tests

Command executed:

```bash
python3 -m pytest worker/tests/test_worker_semantics.py runtime_api/tests/test_context_pack_and_chat.py runtime_api/tests/test_vector_and_suggestions.py -q --tb=short
```

Observed:

```text
192 passed in 0.65s
```

Conclusion:

- PASS for the worker semantic, chat-context, vector, and suggestion regression tests touched by this fix.

### Current Active Agenda Rows

Command executed on cloud:

```sql
SELECT id,type,status,title,time_window->>'display' AS display, COALESCE(place,'') AS place, participants
FROM agenda_items
WHERE status IN ('scheduled','pending')
  AND (
    title ILIKE '%测试码M1%'
    OR title ILIKE '%测试码T1%'
    OR title ILIKE '%测试码N1%'
    OR metadata::text ILIKE '%测试码M1%'
    OR metadata::text ILIKE '%测试码T1%'
    OR metadata::text ILIKE '%测试码N1%'
  )
ORDER BY created_at DESC;
```

Observed:

```text
fa9d8ba2-40d8-4427-9684-1c56d6a7f374 | deadline    | scheduled | 周五18点前把报价单发我，记得核对成本和利润率。 测试码T1 | 2026-07-03 周五 18:00 |          | ["大刚"]
8858f95d-248a-41cb-acf6-181ca56aa6c0 | appointment | scheduled | 明天下午3点半在人民广场见，带合同。 测试码M1            | 2026-07-02 周四 15:30 | 人民广场 | ["大刚"]
```

Conclusion:

- PASS for active agenda state.
- M1 is stored as an appointment with absolute date/time `2026-07-02 周四 15:30`.
- T1 is stored as a deadline with absolute date/time `2026-07-03 周五 18:00`.
- N1 did not produce an active agenda row.

Additional N1 check:

```sql
SELECT id,type,status,title,time_window->>'display' AS display
FROM agenda_items
WHERE title ILIKE '%测试码N1%' OR metadata::text ILIKE '%测试码N1%';
```

Observed:

```text
c0d83643-f607-4fa0-87aa-19d7eac47055 | appointment | dismissed | merged UI transcript containing 测试码N1 | 2026-07-02 周四 07:53
```

Conclusion:

- PASS after cleanup: the only N1-related agenda row is a dismissed bad row from the original faulty run; there is no active N1 schedule.

### Reminder Rows

Command executed on cloud:

```sql
SELECT agenda_item_id,status,lead_minutes,starts_at,remind_at,title,body,metadata->'actions' AS actions
FROM agenda_reminders
WHERE agenda_item_id IN (
  '8858f95d-248a-41cb-acf6-181ca56aa6c0',
  'fa9d8ba2-40d8-4427-9684-1c56d6a7f374'
)
ORDER BY created_at DESC;
```

Observed:

- T1 canonical reminder:
  - `status=pending`
  - `lead_minutes=60`
  - `starts_at=2026-07-03 10:00:00+00`
  - `remind_at=2026-07-03 09:00:00+00`
  - title: `截止提醒：周五18点前把报价单发我，记得核对成本和利润率。 测试码T1`
  - body: `提醒：你需要在 2026-07-03 周五 18:00 前完成：周五18点前把报价单发我，记得核对成本和利润率。 测试码T1。`
  - actions: `查看待办`, `稍后提醒`
- Old T1 online-meeting reminder:
  - `status=canceled`
  - `lead_minutes=10`
  - contained wrong `打开会议` action.
- M1 canonical reminder:
  - `status=pending`
  - `lead_minutes=40`
  - `starts_at=2026-07-02 07:30:00+00`
  - `remind_at=2026-07-02 06:50:00+00`
  - title: `即将出发：人民广场见面`
  - body: `提醒：你 2026-07-02 周四 15:30 要去人民广场见面，记得带合同。`
  - actions: `查路线`, `帮我打车`, `稍后提醒`

Conclusion:

- PASS for reminder semantics.
- Offline meeting reminder uses 40-minute lead time.
- Deadline reminder no longer has online-meeting language or `打开会议`.

### Online Chat Answers

Command executed on cloud with `runtime-api` `TestClient`:

```text
Q: 我的测试暗号是什么？
A: 你的测试暗号是**海盐拿铁**。

Q: 人民广场见面的具体时间是哪天几点？
A: 根据日程安排，在人民广场见面的具体时间是 **2026年7月2日（周四）下午 15:30**。

Q: 报价单需要什么时候前发？要注意什么？
A: 根据日程记录，报价单需要在 **2026年7月3日（周五）18:00 前** 发出。
   注意事项：核对成本、核对利润率。

Q: 今天太阳真大这条普通聊天需要创建日程吗？
A: 不需要。这句话只是闲聊，不包含具体的时间、地点或待办事项，无法创建日程。
```

Conclusion:

- PASS for the four Batch A user-facing answers.
- The answers are content-correct and use absolute dates where needed.

## Remaining Gaps

1. The initial report's Android screenshots were captured before the fixes. Final post-fix verification above is API/DB level. A separate Android screenshot/video pass should still verify that the floating bubble no longer displays stale long-link/noise content.
2. P1 answer is correct, but there may still be older duplicate fact memories from previous test runs. This did not affect the answer, but memory fact dedupe should be productized.
3. The system now handles this four-message real WhatsApp batch correctly after cleanup, but more natural messages without explicit `测试码` should be included in the next broader WhatsApp regression.
