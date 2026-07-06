# Nomi Latency Optimization Regression Results

Date: 2026-06-12

## Summary

This run implemented the accepted latency optimization plan and verified output quality, not only pass/fail status.

Completed optimizations:

- `/api/chat` now records per-step latency trace: initial user turn persistence, context retrieval, model call, assistant persistence, and total time.
- `/api/chat` now routes context needs before retrieval, so simple chat avoids unnecessary agenda/task/memory/source retrieval.
- Independent context sources are retrieved in parallel when needed.
- qwen OpenAI-compatible calls now use `reasoning_effort: "none"` for non-thinking mode.
- Worker semantic parsing is rules-first for clear agenda/payment/deadline/travel/shopping/todo events.
- Worker model enrichment timeout is capped through `WORKER_ONLINE_MODEL_TIMEOUT_SECONDS` with default 8 seconds.
- Worker memory graph/vector enrichment can be batched without blocking immediate agenda and proactive suggestion creation.
- Worker stream entries can run with bounded concurrency while preserving same-conversation ordering through dedupe locks.

## Verification Commands

Runtime latency, routing, non-thinking, context packing:

```bash
PYTHONPATH=runtime_api python3 -m pytest \
  runtime_api/tests/test_chat_latency_trace.py \
  runtime_api/tests/test_model_non_thinking.py \
  runtime_api/tests/test_chat_router.py \
  runtime_api/tests/test_parallel_context_retrieval.py \
  runtime_api/tests/test_context_pack_and_chat.py -q
```

Result: `34 passed in 0.53s` in the focused run, and included in the final runtime suite below.

Runtime Android/WebSocket contracts:

```bash
PYTHONPATH=runtime_api python3 -m pytest \
  runtime_api/tests/test_realtime_ws.py \
  runtime_api/tests/test_android_runtime_api_contract.py -q
```

Result: `6 passed in 3.60s` in the focused run.

Worker latency, semantic quality, batching, concurrency:

```bash
PYTHONPATH=worker python3 -m pytest \
  worker/tests/test_worker_semantics.py \
  worker/tests/test_event_batcher.py \
  worker/tests/test_worker_latency_trace.py \
  worker/tests/test_worker_non_thinking_model.py \
  worker/tests/test_worker_rules_first_latency.py \
  worker/tests/test_worker_model_timeout_budget.py \
  worker/tests/test_worker_concurrency.py -q
```

Result: `85 passed in 0.23s` across the final targeted worker suite.

Android unit tests:

```bash
cd /Users/wrf/Documents/background/android_app
gradle testDebugUnitTest
```

Result: `BUILD SUCCESSFUL in 451ms`.

Final combined runtime suite:

```bash
PYTHONPATH=runtime_api python3 -m pytest \
  runtime_api/tests/test_chat_latency_trace.py \
  runtime_api/tests/test_model_non_thinking.py \
  runtime_api/tests/test_chat_router.py \
  runtime_api/tests/test_parallel_context_retrieval.py \
  runtime_api/tests/test_context_pack_and_chat.py \
  runtime_api/tests/test_realtime_ws.py \
  runtime_api/tests/test_android_runtime_api_contract.py -q
```

Result: `40 passed in 2.63s`.

## Output Correctness Checks

Chat routing:

- Simple chat routes to `simple_chat`, needs dialogue only, and does not fetch memory/agenda/tasks/source.
- Agenda questions route to agenda context.
- Memory questions route to memory context.
- UI source state still forces source context when the client is on a specific page or channel.

Parallel context:

- Source and memory fetchers that each sleep around 100 ms complete together; total stays under the serial sum.
- Returned sections keep stable names: `source`, `memory`, `dialogue`, `agenda`, `tasks`.
- `latency_trace` includes per-section timing such as `source_ms`, `memory_ms`, and `total_ms`.

Worker rules-first:

- Clear appointment text such as “2026-06-13 周六下午3点在武康路见” is classified as `appointment` without a model call.
- The output keeps the important content and does not degrade to `ordinary_chat`.
- Ambiguous text still uses model enrichment, so rules-first does not overreach.

Memory batching:

- `semantic_events` are still written immediately.
- Immediate agenda and proactive suggestion generation remain online.
- Heavy `facts` and `memory_vectors` writes move to the batch queue when a memory batcher is provided.
- Batch flushes by size and by age, and a flushed batch is not emitted again.
- Concurrent batch additions are protected by a lock, and the expensive flush function runs outside the queue mutation section.

Worker concurrency:

- Same `chat_id` / `thread_id` maps to the same lock key, preserving order for one conversation.
- Different stream entries can be processed with bounded workers.
- The checkpoint advances once to the last stream entry after the batch is processed, avoiding checkpoint regression from out-of-order concurrent completion.

## Live Qwen Probe

Endpoint: `http://81.70.177.246:9161/v1/chat/completions`

Payload included:

```json
{
  "model": "qwen3.6",
  "temperature": 0,
  "max_tokens": 96,
  "stream": false,
  "reasoning_effort": "none"
}
```

Observed result:

- Latency: `1401 ms`
- Content: `我可以帮你整理、排序并提醒今天的日程安排，确保你高效完成每一项任务。`
- `reasoning_content`: empty string
- `reasoning_tokens`: `0`
- `total_tokens`: `66`

Assessment: output is concise, relevant, and confirms this qwen gateway supports non-thinking through `reasoning_effort="none"`.

## Remaining Measurement Gap

This local run verifies code behavior and component latency traces. The remaining step is deployment to the cloud server followed by production-like measurement using real Gmail/WhatsApp/Telegram events:

- First `/api/chat` request latency with real DB and model path.
- Event ingestion to proactive suggestion latency under real Redis/Postgres load.
- Memory batch flush latency and batch size distribution.
- Android perceived latency on the physical Redmi device.

The code now exposes enough trace fields to decide the next optimization from data instead of guessing.
