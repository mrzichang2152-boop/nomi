# 2026-06-15 Cloud Latency Regression Run

## Scope

Goal: deploy the current local workspace to the private cloud server, then collect real online latency evidence from:

- Runtime `/api/chat`
- Gmail / WhatsApp / Telegram private event injection
- Worker semantic extraction, agenda creation, proactive suggestions, memory vectors, and facts
- Android-path chat request latency trace

Cloud target:

- Runtime API / Web: `http://206.119.171.141`
- noVNC: `http://206.119.171.141:6080/vnc.html`
- Compose project: `background`

## Deployment

Status: deployed.

Steps performed:

1. Synced the current local working tree to `/opt/nomi`.
2. Generated `/opt/nomi/.env` for the online server.
3. Started the app using `docker compose -p background up -d --build` so existing Postgres, Redis, and Chromium profile volumes were preserved.
4. Rebuilt and restarted `worker` after fixing a worker concurrency deadlock.

Service status after deployment:

- `background-postgres-1`: healthy
- `background-redis-1`: healthy
- `background-model-router-1`: healthy
- `background-runtime-api-1`: running
- `background-worker-1`: running
- `background-chromium-runtime-1`: running on `6080`
- `background-nginx-1`: running on `80`

Health checks:

- `GET /health`: returned `{"status":"ok"}`
- `GET /collectors/health`: returned collector statuses. WhatsApp was healthy with DOM lines; Gmail/Telegram pages were reopened for recovery.

## Runtime Chat Latency

### Chat 1

Request: `请只回复：pong`

Result: semantically correct.

- Wall time: `27841ms`
- Answer: `pong`
- `total_ms`: `27296`
- `initial_persist_ms`: `66`
- `context_retrieval_ms`: `316`
- `model_ms`: `26810`
- `persist_ms`: `55`

Context retrieval steps:

- `source_ms`: `7`
- `memory_ms`: `315`
- `dialogue_ms`: `171`
- `agenda_ms`: `0`
- `tasks_ms`: `214`

Judgment: context retrieval is not the main bottleneck. The model call dominates.

### Chat 2

Request: `请用一句话说明你现在是否可用`

Result: semantically correct.

- Wall time: `14262ms`
- Answer: `我现在随时可用，请告诉我您需要什么帮助。`
- `total_ms`: `13775`
- `initial_persist_ms`: `60`
- `context_retrieval_ms`: `41`
- `model_ms`: `13557`
- `persist_ms`: `113`

Context retrieval steps:

- `source_ms`: `0`
- `memory_ms`: `0`
- `dialogue_ms`: `41`
- `agenda_ms`: `0`
- `tasks_ms`: `0`

Judgment: simple chat now avoids unnecessary memory / agenda / task retrieval, but qwen response latency is still too high for a short answer.

## Event Injection Regression

Injected events:

| Source | Event type | Result |
|---|---|---|
| Gmail | `gmail_thread_snapshot` | Passed |
| WhatsApp | `whatsapp_message` | Passed |
| Telegram | `telegram_message_preview` | Initially failed with worker deadlock, then passed after fix |

### Failure Found And Fixed

First Telegram run failed with:

```text
DeadlockDetected: deadlock detected
INSERT INTO agenda_items
```

Root cause:

- Worker concurrency allowed multiple event threads to call `ensure_agenda_schema()`.
- `ensure_agenda_schema()` ran `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` inside per-event processing.
- Concurrent DDL/schema checks competed with agenda inserts and caused a Postgres deadlock.

Fix:

- Added a process-level lock and ready flag around `ensure_agenda_schema()`.
- Added a regression test proving concurrent calls execute the DDL once instead of once per worker thread.

Verification:

```text
PYTHONPATH=worker python3 -m pytest worker/tests/test_worker_concurrency.py::test_agenda_schema_ddl_runs_once_with_concurrent_workers -q
1 passed

PYTHONPATH=worker python3 -m pytest worker/tests/test_worker_concurrency.py worker/tests/test_worker_latency_trace.py worker/tests/test_worker_rules_first_latency.py worker/tests/test_worker_model_timeout_budget.py worker/tests/test_worker_non_thinking_model.py -q
10 passed
```

## Event Output Quality After Fix

### Gmail

Input: interview email asking to schedule tomorrow at 15:00.

Output:

- Intent: `social_plan`
- Importance: `0.7`
- Parser mode: `rules_first`
- Semantic delay: `0.834s`
- Memory vectors: `1`
- Facts: `1`
- Agenda items: `1`
- Suggestions: `1`

Reasonableness:

- Correctly recognized as a schedule/interview-related item.
- Correctly produced a suggestion with actions: `补充时间地点`, `稍后提醒`, `查看原消息`.
- Gap: English relative time `tomorrow at 15:00` was not normalized into an absolute `start` timestamp. It was kept in `raw_text` with `has_exact_time=true` and missing `exact_place`. This is conservative but incomplete.

### WhatsApp

Input: `明天上午10点在静安寺地铁站见，我把合同带上。你可以顺便帮我看一下报价利润率吗？`

Output:

- Intent: `social_plan`
- Importance: `0.2`
- Parser mode: `rules_first`
- Semantic delay: `9.297s`
- Memory vectors: `1`
- Facts: `1`
- Agenda items: `1`
- Suggestions: `1`

Reasonableness:

- Correctly normalized `明天上午10点` from source timestamp `2026-06-15T14:41:20+08:00` to `2026-06-16 周二 10:00`.
- Correctly extracted place: `静安寺地铁站`.
- Correctly extracted participant: `RG_Alice`.
- Correctly suggested actions: `查路线`, `帮我打车`, `稍后提醒`.
- Gap: priority / importance `0.2` is low for an actionable meeting plus cost/profit follow-up. This should probably be raised by rules.

### Telegram

Input: `周五下午3点武康路咖啡店见，聊一下新客户方案。需要你提前准备路线。`

Output:

- Intent: `schedule`
- Importance: `0.2`
- Parser mode: `rules_first`
- Semantic delay: `9.300s`
- Memory vectors: `1`
- Facts: `1`
- Agenda items: `1`
- Suggestions: `1`

Reasonableness:

- Correctly normalized `周五下午3点` to `2026-06-19 周五 15:00`.
- Correctly extracted place: `武康路咖啡店`.
- Correctly extracted participant: `Maya`.
- Correctly suggested actions: `查路线`, `帮我打车`, `稍后提醒`.
- Gap: priority / importance `0.2` is low for an actionable meeting with route preparation.

## Worker Latency

After the deadlock fix:

| Source | Semantic delay | Rule latency trace | Memory batch result |
|---|---:|---|---|
| Gmail | `0.834s` | `model_ms=0`, `total_ms=0` | vector/fact persisted |
| WhatsApp | `9.297s` | `model_ms=0`, `total_ms=0` | vector/fact persisted |
| Telegram | `9.300s` | `model_ms=0`, `total_ms=0` | vector/fact persisted |

Worker log:

```text
worker memory batch enriched count=3 latency_ms=2943
```

Judgment:

- Semantic extraction itself is fast because these cases use rules-first parsing and skip model calls.
- The remaining 9s delay for WhatsApp/Telegram is queue scheduling / worker batch concurrency / noisy collector traffic, not semantic model latency.
- Memory enrichment batch cost is acceptable at ~2.9s for 3 items on this server.

## Android Path

ADB status:

- `adb devices -l`: no device listed.
- `system_profiler SPUSBDataType`: no Android / Xiaomi / Redmi USB device visible.

Result:

- True-device UI automation could not be collected in this run because the phone was not exposed to adb.
- A server-side Android-equivalent request was sent with `client_type=android-proxy-regression`.

Android-equivalent request:

`根据刚才 WhatsApp 里 Alice 的安排，我什么时候去哪里见她？请一句话回答。`

Output:

- Wall time: `34421ms`
- Answer: `明天（6月16日）上午10点在静安寺地铁站见她。`
- `total_ms`: `33816`
- `context_retrieval_ms`: `68`
- `model_ms`: `33551`
- `persist_ms`: `105`
- `agenda_context`: `4661 tokens`, `6 items`

Reasonableness:

- Answer is correct and uses the WhatsApp-created agenda.
- Latency is not acceptable for mobile chat UX.
- The bottleneck is again model latency, with possible contribution from sending too many agenda items into the prompt.

## Optimization Decision

Based on this run, do not optimize DB first.

Evidence:

- Simple chat context retrieval is `41ms`.
- Agenda/memory chat retrieval is `68ms`.
- The slow part is model latency: `13.6s`, `26.8s`, `33.6s`.

Priority:

1. **Model / prompt path**
   - Reduce prompt payload for simple and agenda queries.
   - Cap agenda context more aggressively for narrow user questions.
   - Verify whether qwen non-thinking mode is actually being honored by the served endpoint.
   - Add shorter model timeout or streaming-first UX for Android.

2. **Worker queue**
   - Keep the agenda schema DDL guard.
   - Reduce noisy browser/focus/network event pressure.
   - Give user-message events priority over telemetry events.
   - Keep batching memory enrichment, but flush high-value user messages sooner.

3. **DB**
   - Not the next bottleneck for chat latency in this run.
   - DB may need indexes later, but current evidence does not justify starting there.

## Open Gaps

- True Android device latency was not collected because adb did not see the connected phone.
- Gmail English relative time normalization is incomplete.
- Actionable WhatsApp/Telegram meeting priority is too low at `0.2`.
- `/api/chat` remains too slow because `model_ms` dominates.
- Agenda query packed 6 agenda items / 4661 tokens for a narrow question; context selection should be tighter.
