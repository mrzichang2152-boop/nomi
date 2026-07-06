# WhatsApp Full Regression Test Plan

Date: 2026-07-01
Environment: cloud `http://206.119.171.141`, Android real device, real WhatsApp account
Password header: `x-par-password: par-dev`

## Goal

Run a pre-release level regression for all WhatsApp-related behavior. The test must verify content quality and data correctness, not only API success flags.

The scope includes:

- WhatsApp browser/login health.
- WhatsApp message collection from the cloud browser runtime.
- Event persistence and deduplication.
- Long-term memory write and recall.
- Agenda/task creation, update, cancel, and fuzzy-time handling.
- Proactive suggestions and Android floating bubble delivery.
- Chat answer behavior with WhatsApp context.
- Source isolation so WhatsApp answers do not accidentally pull unrelated Gmail/Telegram/LinkedIn context.
- Failure behavior when WhatsApp is logged out, syncing, or storage is broken.

## Test Principles

1. Every injected WhatsApp message uses a unique marker `NOMI_WA_REG_0701_*`.
2. Each case checks the full chain: collector event -> worker processing -> memory/agenda/suggestion -> chat or Android UI.
3. Relative dates must be normalized to absolute dates using Asia/Shanghai and current date `2026-07-01`.
4. No test passes only because an endpoint returned `success=true`; the stored content and generated reply must be semantically reasonable.
5. Duplicate messages must not create duplicate agenda items or repeated proactive suggestions.
6. WhatsApp-specific questions should prefer WhatsApp evidence and avoid unrelated private data from other channels.

## Required User Cooperation

When asked, send the exact messages below from another WhatsApp account to the account logged into Nomi's cloud WhatsApp Web. Send each line as a separate WhatsApp message and keep WhatsApp Web open in the cloud browser while the collector runs.

Batch A:

```text
NOMI_WA_REG_0701_PLAIN 请记住：我的测试暗号是海盐拿铁。
NOMI_WA_REG_0701_MEET 明天下午3点半在人民广场见，带合同。
NOMI_WA_REG_0701_TODO 周五18点前把报价单发我，记得核对成本和利润率。
NOMI_WA_REG_0701_NOISE 哈哈哈今天太阳真大。
```

Batch B:

```text
NOMI_WA_REG_0701_FUZZY 这个周末找时间在静安寺附近喝咖啡，具体时间我晚点确认。
NOMI_WA_REG_0701_RESCHEDULE 人民广场那个见面改到后天下午4点，地点还是人民广场。
NOMI_WA_REG_0701_CANCEL 人民广场那个见面先取消。
NOMI_WA_REG_0701_PAY 请周四前付 INV-WA-0701 这笔 1280 元供应商款。
NOMI_WA_REG_0701_REL Maya 最近对报价不满意，说上次响应太慢。
```

Optional duplicate test:

```text
NOMI_WA_REG_0701_MEET 明天下午3点半在人民广场见，带合同。
```

## Baseline Checks

### W0.1 Cloud Services

Steps:

1. Run `docker compose -p nomi ps` on the cloud server.
2. Call `/health`.
3. Call `/api/collectors/status`.
4. Call `/collectors/health`.

Expected:

- Runtime API, worker, model router, chromium runtime, and database containers are running.
- `/health` returns healthy.
- WhatsApp collector is enabled and not paused.
- WhatsApp health is `healthy` or at least not `logged_out`, `storage_error`, or persistent `syncing`.

Fail if:

- WhatsApp status says `Page.goto: Timeout`, `storage_error`, `logged_out`, or `syncing` without recovery.
- Browser runtime is disconnected or the collector is not running.

### W0.2 Android UI

Steps:

1. Confirm the real device is online via `adb devices`.
2. Capture a screenshot of Nomi.
3. Open the floating chat.

Expected:

- Floating ball exists.
- Chat opens without white screen.
- Long URLs wrap inside message bubbles.
- Account linking does not unexpectedly navigate to chat.

## Regression Cases

### W1 Incoming WhatsApp Event Persistence

Input:

`NOMI_WA_REG_0701_PLAIN 请记住：我的测试暗号是海盐拿铁。`

Steps:

1. Wait for the collector cycle.
2. Query collector events for marker `NOMI_WA_REG_0701_PLAIN`.
3. Query worker logs for processing of that event.

Expected:

- Exactly one canonical WhatsApp event is stored for the marker.
- Event source is `whatsapp`.
- Event type is `whatsapp_message`.
- Raw data includes message text, sender/contact context if available, capture scope, and timestamp/captured_at.

Fail if:

- No event exists.
- More than one non-deduped event exists after one message.
- The event is attributed to another source.

### W2 Memory Write And Recall

Input:

Same as W1.

Steps:

1. Query memory/debug for `海盐拿铁`.
2. Ask Nomi on the real Android device: `我在 WhatsApp 里说的测试暗号是什么？`
3. Inspect chat trace/source context.

Expected:

- Memory contains a WhatsApp-derived item for the secret phrase.
- The answer states `海盐拿铁`.
- Trace/source context contains WhatsApp evidence.
- The answer does not include unrelated Gmail/Telegram/LinkedIn memories.

Fail if:

- `source_context=[]` for this question.
- Answer says unknown or guesses.
- Answer uses an unrelated source.

### W3 Absolute Agenda Creation From Relative Time

Input:

`NOMI_WA_REG_0701_MEET 明天下午3点半在人民广场见，带合同。`

Steps:

1. Query events by marker.
2. Query agenda entries by marker or content `人民广场`.
3. Query suggestions by marker/content.
4. Ask Nomi: `人民广场会面的时间是几点？`

Expected:

- Agenda time is normalized to `2026-07-02 15:30` Asia/Shanghai.
- Agenda title/body must not store only `明天`.
- Location is `人民广场`.
- Context mentions `带合同`.
- Source is WhatsApp with evidence count.
- Offline reminder policy applies: reminder should be around 40 minutes before, unless overridden by travel logic.
- Chat answer includes the absolute date and time, for example `2026年7月2日15:30`.

Fail if:

- Agenda stores only `明天` or an ambiguous date.
- Answer says only `下午4点` or omits the date.
- Duplicate agenda/suggestions are created from a single message.

### W4 Non-Action Noise Does Not Create Agenda

Input:

`NOMI_WA_REG_0701_NOISE 哈哈哈今天太阳真大。`

Steps:

1. Verify event and memory ingestion.
2. Query agenda and suggestions for the marker.

Expected:

- Event may be stored as memory/raw event.
- No agenda item.
- No proactive high-priority suggestion.

Fail if:

- A todo/meeting/payment is created.

### W5 Deadline / Todo

Input:

`NOMI_WA_REG_0701_TODO 周五18点前把报价单发我，记得核对成本和利润率。`

Steps:

1. Query agenda/task entries.
2. Ask Nomi: `报价单什么时候截止？`

Expected:

- Deadline is normalized to `2026-07-03 18:00` Asia/Shanghai because 2026-07-01 is Wednesday.
- Task content includes `报价单`, `核对成本`, and `利润率`.
- Answer cites the deadline and relevant WhatsApp source.

Fail if:

- It only says `周五18点` without date.
- It asks what `需要` refers to when the previous context makes it clear.

### W6 Fuzzy Weekend Appointment

Input:

`NOMI_WA_REG_0701_FUZZY 这个周末找时间在静安寺附近喝咖啡，具体时间我晚点确认。`

Steps:

1. Query agenda/task entries.
2. Query suggestions.

Expected:

- Item is stored as tentative/fuzzy.
- Date window is `2026-07-04` to `2026-07-05`.
- Specific time is marked missing/needs clarification.
- Suggestion asks user to confirm exact time instead of inventing one.

Fail if:

- Nomi invents a specific time.
- No missing-field signal exists.

### W7 Reschedule

Input:

`NOMI_WA_REG_0701_RESCHEDULE 人民广场那个见面改到后天下午4点，地点还是人民广场。`

Steps:

1. Query original W3 agenda item.
2. Query new/updated agenda item.
3. Ask Nomi: `人民广场会面现在改到什么时候？`

Expected:

- The active agenda is updated to `2026-07-03 16:00` Asia/Shanghai.
- The previous `2026-07-02 15:30` item is not still active as a separate duplicate.
- Trace or metadata links the reschedule event to the original event.

Fail if:

- Both old and new items remain active without explanation.
- Answer returns old time.

### W8 Cancellation

Input:

`NOMI_WA_REG_0701_CANCEL 人民广场那个见面先取消。`

Steps:

1. Query agenda item status.
2. Query proactive suggestions.
3. Ask Nomi: `人民广场会面还要去吗？`

Expected:

- Related meeting is canceled or marked inactive.
- No route/ride reminder remains active for the canceled event.
- Chat answer states it was canceled, with source from WhatsApp.

Fail if:

- Meeting still appears active.
- Nomi still suggests ride/reminder for it.

### W9 Payment / High-Risk Action Gate

Input:

`NOMI_WA_REG_0701_PAY 请周四前付 INV-WA-0701 这笔 1280 元供应商款。`

Steps:

1. Query tasks/suggestions.
2. Ask Nomi: `帮我处理 INV-WA-0701 付款。`

Expected:

- Payment/deadline task is recognized.
- Any payment action is confirmation-gated.
- No real payment is executed.
- Suggestion asks for user confirmation and shows risk.

Fail if:

- Nomi claims payment was made.
- No confirmation gate appears for payment.

### W10 Relationship Signal

Input:

`NOMI_WA_REG_0701_REL Maya 最近对报价不满意，说上次响应太慢。`

Steps:

1. Query memory and relationship graph/debug output for `Maya`.
2. Ask Nomi: `Maya 最近有什么需要注意的吗？`

Expected:

- Relationship/memory item records dissatisfaction and slow-response signal.
- No agenda is created unless the system frames it as follow-up suggestion.
- Answer suggests follow-up carefully and cites WhatsApp evidence.

Fail if:

- It creates a hard meeting/deadline without explicit time.
- It ignores the relationship signal.

### W11 Duplicate Message Handling

Input:

Send the W3 meeting message a second time.

Steps:

1. Query events, agenda, and suggestions by marker.
2. Observe Android proactive bubble.

Expected:

- Raw duplicate may be visible as a duplicate candidate, but canonical agenda/suggestion should not duplicate.
- Android should not show repeated identical proactive bubbles.

Fail if:

- Multiple identical `跟进近期安排` suggestions appear.
- Agenda has duplicated active meetings.

### W12 Android Proactive Suggestion Delivery

Input:

Use W3/W5.

Steps:

1. Watch Android floating bubble after worker processing.
2. Tap suggestion bubble.
3. Capture screenshot.

Expected:

- One concise suggestion appears.
- It includes a clear reason and action options such as `稍后提醒`, `查路线`, or `确认`.
- Tapping opens the relevant chat/context, not a stale unrelated page.
- Long links/text do not overflow the bubble.

Fail if:

- Bubble repeats.
- It opens the wrong view.
- UI contains raw noise such as `0 notifications total`.

### W13 Source Isolation

Steps:

1. Ask Nomi: `我在 WhatsApp 里说的测试暗号是什么？`
2. Ask Nomi: `Telegram 里有没有提到海盐拿铁？`

Expected:

- WhatsApp answer returns the secret phrase.
- Telegram-specific question should not falsely attribute the WhatsApp phrase to Telegram.

Fail if:

- Source scopes are mixed.

### W14 Collector Failure Reporting

Steps:

1. If WhatsApp collector is unhealthy, capture `/collectors/health`.
2. Check account connection status UI.

Expected:

- The UI distinguishes `待检测`, `采集异常`, `未登录`, and `同步中`.
- Failure reason is actionable, for example `WhatsApp storage error`, `not logged in`, or `page timeout`.

Fail if:

- UI only says `异常` without detail.
- Test proceeds as if WhatsApp was healthy.

## Evidence To Capture For Each Case

- Message marker.
- Cloud event ID.
- Memory ID or debug result.
- Agenda ID/status/time.
- Suggestion ID/status/actions.
- Chat trace ID and source context.
- Android screenshot if UI is involved.
- Pass/fail conclusion and failure reason.

## Run Report Template

For each case:

```text
Case:
Input:
Observed event:
Observed memory:
Observed agenda/task:
Observed suggestion:
Observed Android UI:
Observed chat answer:
Trace/source context:
Conclusion:
Issue to fix:
```
