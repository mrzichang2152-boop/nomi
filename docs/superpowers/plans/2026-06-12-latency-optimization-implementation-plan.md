# Nomi Latency Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce first `/api/chat` perceived latency and reduce Gmail/WhatsApp/Telegram ingestion-to-suggestion delay from minutes to seconds while preserving correct memory, agenda, and proactive suggestion outputs.

**Architecture:** Split the system into a fast user-waiting path and an asynchronous understanding path. `/api/chat` first routes the request to decide which context is needed, retrieves independent context sources in parallel, streams a non-thinking qwen response, and persists deeper memory asynchronously. Worker ingestion immediately stores raw events, runs rules-first deterministic extraction, uses short-timeout non-thinking model enrichment only when needed, and batches embedding/graph/RAG memory writes.

**Tech Stack:** FastAPI, httpx, asyncio, PostgreSQL, Redis Streams, qwen OpenAI-compatible API, Android WebSocket/SSE client, pytest.

## Implementation Status

- Completed: chat latency trace, chat request router, parallel context retrieval, qwen non-thinking request parameter, worker rules-first semantic path, worker short model timeout, batched memory enrichment, worker bounded concurrency with per-conversation locks.
- Verified: runtime targeted tests, worker semantic tests, Android unit tests, Android/WebSocket runtime contracts, and live qwen non-thinking probe.
- Not completed in this local pass: cloud deployment and true production traffic latency measurement after deployment. The code now emits per-step traces needed for that measurement.

---

## Current Bottlenecks To Remove

1. `/api/chat` always builds a broad context pack before calling the model, even when the user asks a simple question.
2. Context retrieval is mostly sequential: source context, RAG/KV/graph memory, assistant dialogue, active agenda, active task.
3. First qwen call is non-streaming in `/api/chat`, so the user sees nothing until the full model answer returns.
4. Worker event processing is serial within one consumer loop.
5. Worker semantic extraction and agenda extraction pay up to 60 seconds per model call before falling back to rules.
6. Raw events and long-term memory are coupled too tightly: ingestion, semantic extraction, graph/RAG embedding, agenda, and suggestion generation are effectively treated as one online chain.
7. qwen non-thinking mode is not currently enforced as a first-class routing option for chat, semantic parsing, agenda parsing, and suggestions.

## Target Performance

- First token for chat over streaming: under 3 seconds after request reaches runtime API when qwen is healthy.
- Full simple chat response: p95 under 15 seconds.
- Duplicate Android send with the same `client_request_id`: under 1 second and no duplicate assistant turn.
- Raw Gmail/WhatsApp/Telegram event persistence: under 1 second.
- Deterministic agenda/suggestion generation from clear message text: p95 under 5 seconds.
- Ambiguous semantic enrichment: p95 under 12 seconds with model timeout capped at 8 seconds.
- Batched memory enrichment: visible in long-term memory within 30-90 seconds, without blocking chat or event suggestions.

## File Structure

- Modify `runtime_api/app/main.py`
  - Add chat request routing.
  - Add parallel context retrieval.
  - Add fast-path context packing.
  - Keep existing idempotency behavior.
  - Expose timing metadata for trace inspection.
- Modify `runtime_api/app/model_gateway.py`
  - Add non-thinking request options to provider config and request payload.
  - Add per-task timeout and max output token routing.
- Modify `runtime_api/app/model_client.py`
  - Pass qwen non-thinking parameters through OpenAI-compatible requests.
  - Support streaming with the same non-thinking options.
- Create `runtime_api/app/chat_router.py`
  - Classify chat request context needs without calling the full model.
- Create `runtime_api/app/context_parallel.py`
  - Run independent context retrieval tasks concurrently and return normalized sections.
- Modify `worker/app/worker.py`
  - Split raw persistence from memory enrichment.
  - Add rules-first semantic and agenda extraction.
  - Add short-timeout model enrichment.
  - Add queue timing and step timing fields.
- Create `worker/app/event_batcher.py`
  - Batch semantic memory, graph, and embedding work.
- Create `worker/app/worker_concurrency.py`
  - Add bounded concurrent event processing with per-source and per-dedupe-key locks.
- Modify `runtime_api/app/static/app.js`
  - Prefer streaming chat route where available.
  - Show partial response and explicit timeout/degraded state.
- Modify Android app networking files under the Android project
  - Prefer WebSocket/SSE streaming for chat.
  - Preserve keyboard behavior and idempotent `client_request_id`.
- Add tests under `runtime_api/tests/` and `worker/tests/`
  - Verify routing decisions, parallel retrieval, non-thinking payload, rules-first skip, batch memory writes, and timing traces.

---

## Task 1: Add Latency Timing Instrumentation

**Files:**
- Modify: `runtime_api/app/main.py`
- Modify: `worker/app/worker.py`
- Test: `runtime_api/tests/test_chat_latency_trace.py`
- Test: `worker/tests/test_worker_latency_trace.py`

- [ ] **Step 1: Add failing runtime API test**

Create `runtime_api/tests/test_chat_latency_trace.py` with:

```python
from fastapi.testclient import TestClient


def test_chat_response_contains_latency_trace(monkeypatch):
    from app import main
    from app.model_gateway import ModelAnswer

    monkeypatch.setattr(main, "require_password", lambda value: None)
    monkeypatch.setattr(main, "retrieve_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_current_source_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "normalize_client_dialogue_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_agenda_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_task_context", lambda *args, **kwargs: [])

    class FakeGateway:
        async def chat(self, messages, temperature=0.4):
            return ModelAnswer(text="ok", provider_id="fake", trace={})

    monkeypatch.setattr(main, "model_gateway", lambda: FakeGateway())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={"message": "ping", "conversation_id": "latency-test"},
        headers={"x-par-password": "test"},
    )

    assert response.status_code == 200
    body = response.json()
    trace = body["context_pack"]["latency_trace"]
    assert trace["total_ms"] >= 0
    assert "context_retrieval_ms" in trace
    assert "model_ms" in trace
```

- [ ] **Step 2: Run runtime timing test and verify it fails**

Run:

```bash
PYTHONPATH=runtime_api python3 -m pytest runtime_api/tests/test_chat_latency_trace.py -q
```

Expected: failure because `latency_trace` is not present.

- [ ] **Step 3: Add runtime latency trace**

In `runtime_api/app/main.py`, add small timing helpers near the chat code:

```python
def monotonic_ms() -> float:
    return time.perf_counter() * 1000.0


def elapsed_ms(start_ms: float) -> int:
    return max(0, int(monotonic_ms() - start_ms))
```

Wrap the chat route phases:

```python
total_start = monotonic_ms()
context_start = monotonic_ms()
# existing context retrieval
context_ms = elapsed_ms(context_start)

model_start = monotonic_ms()
answer_result = await model_gateway().chat(messages)
model_ms = elapsed_ms(model_start)

context_pack["latency_trace"] = {
    "total_ms": elapsed_ms(total_start),
    "context_retrieval_ms": context_ms,
    "model_ms": model_ms,
}
```

- [ ] **Step 4: Add failing worker timing test**

Create `worker/tests/test_worker_latency_trace.py` with:

```python
def test_worker_semantic_trace_contains_step_timing(monkeypatch):
    from app import worker

    monkeypatch.setattr(worker, "call_model", lambda messages: (_ for _ in ()).throw(TimeoutError("slow")))

    semantic = worker.extract_semantics(
        "whatsapp",
        "message",
        {
            "text": "明天下午4点人民广场见，带合同。",
            "conversation_id": "timing-test",
            "sender_name": "Alice",
            "timestamp": "2026-06-12T08:00:00+08:00",
        },
    )

    trace = semantic["entities"]["classification_trace"]
    assert "latency_trace" in trace
    assert trace["latency_trace"]["total_ms"] >= 0
    assert "model_ms" in trace["latency_trace"]
```

- [ ] **Step 5: Run worker timing test and verify it fails**

Run:

```bash
PYTHONPATH=worker python3 -m pytest worker/tests/test_worker_latency_trace.py -q
```

Expected: failure because worker semantic trace has no step timing.

- [ ] **Step 6: Add worker semantic timing**

In `worker/app/worker.py`, wrap `extract_semantics` with timing fields:

```python
start_ms = time.perf_counter() * 1000.0
rule_ms = 0
model_ms = 0
```

Add this to `classification_trace` before returning:

```python
trace = semantic["entities"].setdefault("classification_trace", {})
trace["latency_trace"] = {
    "total_ms": max(0, int(time.perf_counter() * 1000.0 - start_ms)),
    "rule_ms": rule_ms,
    "model_ms": model_ms,
}
```

- [ ] **Step 7: Run timing tests**

Run:

```bash
PYTHONPATH=runtime_api python3 -m pytest runtime_api/tests/test_chat_latency_trace.py -q
PYTHONPATH=worker python3 -m pytest worker/tests/test_worker_latency_trace.py -q
```

Expected: both pass.

---

## Task 2: Add Chat Request Router

**Files:**
- Create: `runtime_api/app/chat_router.py`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_chat_router.py`

- [ ] **Step 1: Write router tests**

Create `runtime_api/tests/test_chat_router.py`:

```python
from app.chat_router import route_chat_context


def test_simple_chat_only_needs_dialogue_context():
    route = route_chat_context("你好，简单介绍一下你能做什么", ui_state=None)

    assert route.intent == "simple_chat"
    assert route.needs_dialogue is True
    assert route.needs_memory is False
    assert route.needs_agenda is False
    assert route.needs_tasks is False
    assert route.needs_source is False


def test_agenda_question_needs_agenda_and_dialogue():
    route = route_chat_context("我今天下午有哪些安排？", ui_state=None)

    assert route.intent == "agenda_query"
    assert route.needs_dialogue is True
    assert route.needs_agenda is True
    assert route.needs_memory is False


def test_memory_question_needs_scoped_memory():
    route = route_chat_context("Alice 之前说 PHONE_1 报价什么时候截止？", ui_state=None)

    assert route.intent == "memory_query"
    assert route.needs_memory is True
    assert route.needs_source is True


def test_task_request_needs_tasks_and_memory():
    route = route_chat_context("帮我跟进这个客户报价并起草回复", ui_state=None)

    assert route.intent == "task_request"
    assert route.needs_tasks is True
    assert route.needs_memory is True
```

- [ ] **Step 2: Run router tests and verify they fail**

Run:

```bash
PYTHONPATH=runtime_api python3 -m pytest runtime_api/tests/test_chat_router.py -q
```

Expected: import failure because `app.chat_router` does not exist.

- [ ] **Step 3: Implement router**

Create `runtime_api/app/chat_router.py`:

```python
from dataclasses import dataclass
from typing import Any
import re


@dataclass(frozen=True)
class ChatContextRoute:
    intent: str
    needs_dialogue: bool = True
    needs_source: bool = False
    needs_memory: bool = False
    needs_agenda: bool = False
    needs_tasks: bool = False
    reason: str = ""


AGENDA_RE = re.compile(r"(今天|明天|后天|本周|下周|日程|安排|会议|见面|截止|提醒)")
MEMORY_RE = re.compile(r"(之前|上次|谁说|说过|聊天记录|邮件|报价|PHONE_|客户|同事|朋友)")
TASK_RE = re.compile(r"(帮我|替我|跟进|起草|发送|回复|投递|申请|打车|导航|购买|下单)")


def route_chat_context(message: str, ui_state: dict[str, Any] | None = None) -> ChatContextRoute:
    text = str(message or "").strip()
    has_ui_source = bool(ui_state and ui_state.get("source"))

    if TASK_RE.search(text):
        return ChatContextRoute(
            intent="task_request",
            needs_dialogue=True,
            needs_source=True or has_ui_source,
            needs_memory=True,
            needs_agenda=bool(AGENDA_RE.search(text)),
            needs_tasks=True,
            reason="task_keyword",
        )

    if AGENDA_RE.search(text):
        return ChatContextRoute(
            intent="agenda_query",
            needs_dialogue=True,
            needs_source=has_ui_source,
            needs_agenda=True,
            reason="agenda_keyword",
        )

    if MEMORY_RE.search(text):
        return ChatContextRoute(
            intent="memory_query",
            needs_dialogue=True,
            needs_source=True,
            needs_memory=True,
            reason="memory_keyword",
        )

    return ChatContextRoute(intent="simple_chat", needs_dialogue=True, reason="default_simple")
```

- [ ] **Step 4: Run router tests**

Run:

```bash
PYTHONPATH=runtime_api python3 -m pytest runtime_api/tests/test_chat_router.py -q
```

Expected: all tests pass.

---

## Task 3: Parallelize Chat Context Retrieval

**Files:**
- Create: `runtime_api/app/context_parallel.py`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_parallel_context_retrieval.py`

- [ ] **Step 1: Write parallel retrieval test**

Create `runtime_api/tests/test_parallel_context_retrieval.py`:

```python
import time

from app.chat_router import ChatContextRoute
from app.context_parallel import retrieve_chat_context_parallel


def test_parallel_context_retrieval_runs_independent_fetchers_concurrently():
    calls = []

    def slow(name):
        def fetch():
            time.sleep(0.15)
            calls.append(name)
            return [name]
        return fetch

    route = ChatContextRoute(
        intent="task_request",
        needs_dialogue=True,
        needs_source=True,
        needs_memory=True,
        needs_agenda=True,
        needs_tasks=True,
    )

    start = time.perf_counter()
    result = retrieve_chat_context_parallel(
        route,
        fetchers={
            "source": slow("source"),
            "memory": slow("memory"),
            "dialogue": slow("dialogue"),
            "agenda": slow("agenda"),
            "tasks": slow("tasks"),
        },
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 0.45
    assert result["source"] == ["source"]
    assert result["memory"] == ["memory"]
    assert result["dialogue"] == ["dialogue"]
    assert result["agenda"] == ["agenda"]
    assert result["tasks"] == ["tasks"]
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
PYTHONPATH=runtime_api python3 -m pytest runtime_api/tests/test_parallel_context_retrieval.py -q
```

Expected: import failure because `context_parallel` does not exist.

- [ ] **Step 3: Implement parallel retrieval helper**

Create `runtime_api/app/context_parallel.py`:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from app.chat_router import ChatContextRoute


Fetchers = dict[str, Callable[[], list[dict[str, Any]] | list[Any]]]


def retrieve_chat_context_parallel(route: ChatContextRoute, fetchers: Fetchers) -> dict[str, list[Any]]:
    enabled = {
        "source": route.needs_source,
        "memory": route.needs_memory,
        "dialogue": route.needs_dialogue,
        "agenda": route.needs_agenda,
        "tasks": route.needs_tasks,
    }
    result: dict[str, list[Any]] = {key: [] for key in enabled}
    active = {key: fetchers[key] for key, should_run in enabled.items() if should_run and key in fetchers}

    if not active:
        return result

    with ThreadPoolExecutor(max_workers=min(5, len(active))) as executor:
        future_to_key = {executor.submit(fetcher): key for key, fetcher in active.items()}
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            result[key] = list(future.result() or [])
    return result
```

- [ ] **Step 4: Wire into `/api/chat`**

In `runtime_api/app/main.py`, import:

```python
from app.chat_router import route_chat_context
from app.context_parallel import retrieve_chat_context_parallel
```

In `chat`, compute route before context retrieval:

```python
chat_route = route_chat_context(body.message, body.ui_state)
```

Build fetchers:

```python
parallel_context = retrieve_chat_context_parallel(
    chat_route,
    {
        "source": lambda: dedupe_context_items(
            normalize_ui_state_source_context(body.ui_state, request_scope)
            + retrieve_current_source_context(body.message, request_scope, limit=6)
        ),
        "memory": lambda: retrieve_context(body.message, context_candidate_limit, request_scope=request_scope),
        "dialogue": lambda: retrieve_assistant_dialogue_context(
            body.message,
            conversation_id=user_turn["conversation_id"],
            limit=64,
        ),
        "agenda": lambda: retrieve_active_agenda_context(
            body.message,
            conversation_id=user_turn["conversation_id"],
            limit=6,
        ),
        "tasks": lambda: retrieve_active_task_context(
            body.message,
            conversation_id=user_turn["conversation_id"],
            limit=8,
        ),
    },
)
```

Use:

```python
source_context = parallel_context["source"]
context = parallel_context["memory"]
assistant_context = parallel_context["dialogue"]
agenda_context = parallel_context["agenda"]
task_context = parallel_context["tasks"]
context_pack["chat_route"] = chat_route.__dict__
```

- [ ] **Step 5: Run context tests**

Run:

```bash
PYTHONPATH=runtime_api python3 -m pytest runtime_api/tests/test_chat_router.py runtime_api/tests/test_parallel_context_retrieval.py runtime_api/tests/test_context_pack_and_chat.py -q
```

Expected: all pass.

---

## Task 4: Make Qwen Non-Thinking Mode First-Class

**Files:**
- Modify: `runtime_api/app/model_client.py`
- Modify: `runtime_api/app/model_gateway.py`
- Modify: `worker/app/worker.py`
- Test: `runtime_api/tests/test_model_non_thinking.py`
- Test: `worker/tests/test_worker_non_thinking_model.py`

- [ ] **Step 1: Write runtime non-thinking payload test**

The current qwen endpoint at `http://81.70.177.246:9161/v1` is an OpenAI-compatible HTTP service. Live probing showed that top-level `enable_thinking=false` and `chat_template_kwargs.enable_thinking=false` are ignored by this service, while `reasoning_effort="none"` works: response `reasoning_content` is empty and `usage.completion_tokens_details.reasoning_tokens` is `0`. Therefore the implementation must use `reasoning_effort="none"` for this endpoint instead of relying on prompt wording or transformers-native `enable_thinking`.

Create `runtime_api/tests/test_model_non_thinking.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_qwen_payload_disables_thinking(monkeypatch):
    from app.model_client import ChatCompletionClient, ModelClientConfig

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json, headers=None, timeout=None):
            captured.update(json)
            return FakeResponse()

    monkeypatch.setattr("app.model_client.httpx.AsyncClient", lambda *args, **kwargs: FakeClient())

    client = ChatCompletionClient(
        ModelClientConfig(
            provider_type="openai_compatible",
            base_url="http://qwen.local/v1",
            model="qwen3.6",
            api_key="",
            max_output_tokens=128,
            reasoning_effort="none",
        )
    )

    await client.chat([{"role": "user", "content": "只回复 ok"}])

    assert captured["reasoning_effort"] == "none"
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
PYTHONPATH=runtime_api python3 -m pytest runtime_api/tests/test_model_non_thinking.py -q
```

Expected: failure because `reasoning_effort` is not supported in config/payload.

- [ ] **Step 3: Extend model client config**

In `runtime_api/app/model_client.py`, add to `ModelClientConfig`:

```python
reasoning_effort: str = "none"
```

When building the OpenAI-compatible payload, include:

```python
if self.config.reasoning_effort:
    payload["reasoning_effort"] = self.config.reasoning_effort
```

- [ ] **Step 4: Extend model gateway provider config**

In `runtime_api/app/model_gateway.py`, add to `ModelProviderConfig`:

```python
reasoning_effort: str = "none"
```

Pass it into `ModelClientConfig` in `QwenHTTPProvider`.

- [ ] **Step 5: Set non-thinking defaults**

In `runtime_api/app/model_gateway.py`, when loading default providers, use:

```python
reasoning_effort=os.getenv("QWEN_REASONING_EFFORT", "none").strip().lower()
```

Default must be `"none"`. For providers that do not support this field, model gateway should allow disabling the parameter by setting `QWEN_REASONING_EFFORT=""`.

- [ ] **Step 6: Write worker non-thinking test**

Create `worker/tests/test_worker_non_thinking_model.py`:

```python
def test_worker_model_payload_disables_qwen_thinking(monkeypatch):
    from app import worker

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "{\"intent\":\"普通聊天\",\"entities\":{},\"importance\":0.1,\"summary\":\"测试\"}"}}]}

    def fake_post(url, json, timeout):
        captured.update(json)
        return FakeResponse()

    monkeypatch.setattr(worker.httpx, "post", fake_post)
    monkeypatch.setenv("MODEL_ROUTER_URL", "")
    worker.call_model([{"role": "user", "content": "test"}])

    assert captured["reasoning_effort"] == "none"
```

- [ ] **Step 7: Update worker direct model payload**

In `worker/app/worker.py`, add to the direct model payload:

```python
"reasoning_effort": "none",
```

For model-router calls, include:

```python
"reasoning_effort": "none",
```

- [ ] **Step 8: Run non-thinking tests**

Run:

```bash
PYTHONPATH=runtime_api python3 -m pytest runtime_api/tests/test_model_non_thinking.py -q
PYTHONPATH=worker python3 -m pytest worker/tests/test_worker_non_thinking_model.py -q
```

Expected: both pass and payload explicitly disables thinking through `reasoning_effort="none"`.

---

## Task 5: Rules-First Worker Semantic And Agenda Extraction

**Files:**
- Modify: `worker/app/worker.py`
- Test: `worker/tests/test_worker_rules_first_latency.py`

- [ ] **Step 1: Write rules-first skip-model test**

Create `worker/tests/test_worker_rules_first_latency.py`:

```python
def test_clear_appointment_skips_model_call(monkeypatch):
    from app import worker

    calls = []

    def fail_if_called(messages):
        calls.append(messages)
        raise AssertionError("model should not be called for clear appointment")

    monkeypatch.setattr(worker, "call_model", fail_if_called)

    semantic = worker.extract_semantics(
        "whatsapp",
        "message",
        {
            "text": "明天下午4点在人民广场见，带合同。",
            "sender_name": "Alice",
            "conversation_id": "rules-first",
            "timestamp": "2026-06-12T08:00:00+08:00",
        },
    )

    trace = semantic["entities"]["classification_trace"]
    assert calls == []
    assert trace["parser_mode"] == "rules_first"
    assert semantic["entities"]["primary_label"] == "约定"
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
PYTHONPATH=worker python3 -m pytest worker/tests/test_worker_rules_first_latency.py -q
```

Expected: failure because model is still called.

- [ ] **Step 3: Add deterministic-confidence gate**

In `worker/app/worker.py`, add:

```python
RULES_FIRST_PRIMARY_LABELS = {"约定", "改期", "取消", "截止日期", "付款", "出行", "购物", "待办"}


def rules_first_confident(semantic: dict[str, Any]) -> bool:
    entities = semantic.get("entities") if isinstance(semantic.get("entities"), dict) else {}
    primary = str(entities.get("primary_label") or "")
    importance = bounded_float(semantic.get("importance"))
    text = semantic_text(semantic)
    has_time_or_action = bool(EXACT_TIME_RE.search(text) or re.search(r"(明天|后天|周[一二三四五六日天]|截止|付款|支付|打车|导航|购买|下单|取消|改到)", text))
    return primary in RULES_FIRST_PRIMARY_LABELS and importance >= 0.55 and has_time_or_action
```

In `extract_semantics`, after fallback enrichment and before model call:

```python
if rules_first_confident(fallback):
    return enrich_semantic_classification(
        source,
        event_type,
        raw_data,
        fallback,
        parser_mode="rules_first",
    )
```

- [ ] **Step 4: Add agenda model skip for rules-first**

In `hybrid_agenda_candidate_from_semantic`, if semantic parser mode is `rules_first`, skip `model_agenda_candidate_from_semantic`:

```python
trace = ((semantic.get("entities") or {}).get("classification_trace") or {})
if trace.get("parser_mode") == "rules_first":
    rule_candidate = agenda_candidate_from_semantic(event_id, timestamp, semantic)
    return rules_fallback_agenda_candidate(rule_candidate, None, ["rules_first_skipped_model"])
```

- [ ] **Step 5: Run rules-first tests**

Run:

```bash
PYTHONPATH=worker python3 -m pytest worker/tests/test_worker_rules_first_latency.py worker/tests/test_worker_semantics.py -q
```

Expected: all pass; deterministic events avoid model calls.

---

## Task 6: Short-Timeout Model Enrichment

**Files:**
- Modify: `worker/app/worker.py`
- Modify: `runtime_api/app/model_client.py`
- Test: `worker/tests/test_worker_model_timeout_budget.py`

- [ ] **Step 1: Write timeout config test**

Create `worker/tests/test_worker_model_timeout_budget.py`:

```python
def test_worker_model_uses_short_online_timeout(monkeypatch):
    from app import worker

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}]}

    def fake_post(url, json, timeout):
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(worker.httpx, "post", fake_post)
    monkeypatch.setenv("MODEL_ROUTER_URL", "")
    monkeypatch.setenv("WORKER_ONLINE_MODEL_TIMEOUT_SECONDS", "8")

    worker.call_model([{"role": "user", "content": "test"}])

    assert captured["timeout"] == 8
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
PYTHONPATH=worker python3 -m pytest worker/tests/test_worker_model_timeout_budget.py -q
```

Expected: failure because timeout is fixed at 60.

- [ ] **Step 3: Add worker timeout helper**

In `worker/app/worker.py`, add:

```python
def worker_online_model_timeout_seconds() -> float:
    raw = os.getenv("WORKER_ONLINE_MODEL_TIMEOUT_SECONDS", "8")
    try:
        value = float(raw)
    except ValueError:
        value = 8.0
    return min(max(value, 1.0), 15.0)
```

Use it in both model-router and direct `httpx.post` calls:

```python
timeout=worker_online_model_timeout_seconds()
```

- [ ] **Step 4: Run timeout tests**

Run:

```bash
PYTHONPATH=worker python3 -m pytest worker/tests/test_worker_model_timeout_budget.py worker/tests/test_worker_semantics.py -q
```

Expected: all pass.

---

## Task 7: Raw Event Immediate Write And Batched Memory Enrichment

**Files:**
- Create: `worker/app/event_batcher.py`
- Modify: `worker/app/worker.py`
- Test: `worker/tests/test_event_batcher.py`

- [ ] **Step 1: Write batcher tests**

Create `worker/tests/test_event_batcher.py`:

```python
from app.event_batcher import MemoryBatcher


def test_batcher_flushes_by_size():
    flushed = []
    batcher = MemoryBatcher(max_items=3, max_age_seconds=60, flush_fn=lambda items: flushed.append(list(items)))

    assert batcher.add({"id": "1"}) == []
    assert batcher.add({"id": "2"}) == []
    batches = batcher.add({"id": "3"})

    assert len(batches) == 1
    assert [item["id"] for item in batches[0]] == ["1", "2", "3"]


def test_batcher_flushes_by_age(monkeypatch):
    now = {"value": 1000.0}
    flushed = []
    batcher = MemoryBatcher(max_items=10, max_age_seconds=5, flush_fn=lambda items: flushed.append(list(items)), now=lambda: now["value"])

    assert batcher.add({"id": "1"}) == []
    now["value"] = 1006.0
    batches = batcher.flush_due()

    assert len(batches) == 1
    assert batches[0][0]["id"] == "1"
```

- [ ] **Step 2: Run batcher tests and verify they fail**

Run:

```bash
PYTHONPATH=worker python3 -m pytest worker/tests/test_event_batcher.py -q
```

Expected: import failure because `event_batcher` does not exist.

- [ ] **Step 3: Implement batcher**

Create `worker/app/event_batcher.py`:

```python
from collections.abc import Callable
from typing import Any
import time


class MemoryBatcher:
    def __init__(
        self,
        *,
        max_items: int,
        max_age_seconds: float,
        flush_fn: Callable[[list[dict[str, Any]]], None],
        now: Callable[[], float] | None = None,
    ) -> None:
        self.max_items = max(1, max_items)
        self.max_age_seconds = max(0.1, max_age_seconds)
        self.flush_fn = flush_fn
        self.now = now or time.time
        self.items: list[dict[str, Any]] = []
        self.first_item_at: float | None = None

    def add(self, item: dict[str, Any]) -> list[list[dict[str, Any]]]:
        if not self.items:
            self.first_item_at = self.now()
        self.items.append(item)
        if len(self.items) >= self.max_items:
            return [self.flush()]
        return []

    def flush_due(self) -> list[list[dict[str, Any]]]:
        if not self.items or self.first_item_at is None:
            return []
        if self.now() - self.first_item_at >= self.max_age_seconds:
            return [self.flush()]
        return []

    def flush(self) -> list[dict[str, Any]]:
        batch = list(self.items)
        self.items.clear()
        self.first_item_at = None
        if batch:
            self.flush_fn(batch)
        return batch
```

- [ ] **Step 4: Wire batcher into worker enrichment**

In `worker/app/worker.py`, preserve immediate raw event storage in the current processing path. Move embedding/RAG/graph enrichment calls into a function that can accept a list:

```python
def enrich_memory_batch(items: list[dict[str, Any]]) -> None:
    for item in items:
        enrich_single_memory_item(item)
```

Use `MemoryBatcher(max_items=20, max_age_seconds=30, flush_fn=enrich_memory_batch)` from the worker loop. Raw event and deterministic agenda/suggestion writes must still happen before the item is added to the batch.

- [ ] **Step 5: Run worker tests**

Run:

```bash
PYTHONPATH=worker python3 -m pytest worker/tests/test_event_batcher.py worker/tests/test_worker_semantics.py -q
```

Expected: all pass.

---

## Task 8: Worker Concurrency With Dedupe-Key Locking

**Files:**
- Create: `worker/app/worker_concurrency.py`
- Modify: `worker/app/worker.py`
- Test: `worker/tests/test_worker_concurrency.py`

- [ ] **Step 1: Write concurrency lock test**

Create `worker/tests/test_worker_concurrency.py`:

```python
from app.worker_concurrency import DedupeLockRegistry


def test_same_dedupe_key_reuses_same_lock():
    registry = DedupeLockRegistry()

    first = registry.lock_for("agenda:a")
    second = registry.lock_for("agenda:a")
    third = registry.lock_for("agenda:b")

    assert first is second
    assert first is not third
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
PYTHONPATH=worker python3 -m pytest worker/tests/test_worker_concurrency.py -q
```

Expected: import failure.

- [ ] **Step 3: Implement lock registry**

Create `worker/app/worker_concurrency.py`:

```python
import threading


class DedupeLockRegistry:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def lock_for(self, key: str) -> threading.Lock:
        normalized = str(key or "default")
        with self._guard:
            lock = self._locks.get(normalized)
            if lock is None:
                lock = threading.Lock()
                self._locks[normalized] = lock
            return lock
```

- [ ] **Step 4: Add bounded worker concurrency**

In `worker/app/worker.py`, use `ThreadPoolExecutor` around independent stream entries:

```python
worker_concurrency = int(os.getenv("WORKER_CONCURRENCY", "4"))
```

For each entry, derive a lock key from source/conversation/dedupe candidate. Process different keys concurrently; process same key under `DedupeLockRegistry.lock_for(key)`.

- [ ] **Step 5: Run worker tests**

Run:

```bash
PYTHONPATH=worker python3 -m pytest worker/tests/test_worker_concurrency.py worker/tests/test_worker_semantics.py -q
```

Expected: all pass.

---

## Task 9: Streaming Chat As The Default Client Path

**Files:**
- Modify: `runtime_api/app/main.py`
- Modify: `runtime_api/app/static/app.js`
- Modify: Android chat networking files
- Test: `runtime_api/tests/test_realtime_ws.py`
- Test: `runtime_api/tests/test_android_runtime_api_contract.py`

- [ ] **Step 1: Verify existing streaming tests**

Run:

```bash
PYTHONPATH=runtime_api python3 -m pytest runtime_api/tests/test_realtime_ws.py runtime_api/tests/test_android_runtime_api_contract.py -q
```

Expected: existing streaming/WebSocket behavior passes before changes.

- [ ] **Step 2: Add client behavior contract**

Extend `runtime_api/tests/test_android_runtime_api_contract.py` with an assertion that chat clients can send `client_request_id` and receive streamed chunks with the same conversation id.

Expected behavior:

```python
assert chunk["type"] == "delta"
assert chunk["conversation_id"] == "android-chat"
assert final["type"] == "done"
```

- [ ] **Step 3: Update Web client**

In `runtime_api/app/static/app.js`, prefer the streaming route for chat. The UI must:

```javascript
// Create assistant bubble immediately.
// Append each delta to the same assistant bubble.
// Keep input enabled unless send is already in-flight for the same client_request_id.
// Show "连接超时，已保留你的消息，可以重试" when stream fails.
```

- [ ] **Step 4: Update Android client**

Android must:

```kotlin
// Generate a stable client_request_id per send tap.
// Open streaming connection.
// Render assistant placeholder immediately.
// Append deltas into that placeholder.
// Keep keyboard open after tapping send.
// Hide keyboard only when user taps outside the input and chat panel.
// On timeout, show visible failed state and allow retry with a new client_request_id.
```

- [ ] **Step 5: Run client contract tests**

Run:

```bash
PYTHONPATH=runtime_api python3 -m pytest runtime_api/tests/test_realtime_ws.py runtime_api/tests/test_android_runtime_api_contract.py -q
```

Expected: all pass.

---

## Task 10: Regression Test Matrix

**Files:**
- Modify: `docs/superpowers/plans/2026-06-10-nomi-regression-test-plan.md` if present
- Create: `docs/superpowers/reports/2026-06-12-latency-optimization-regression-results.md`

- [ ] **Step 1: Run runtime unit tests**

Run:

```bash
PYTHONPATH=runtime_api python3 -m pytest \
  runtime_api/tests/test_chat_router.py \
  runtime_api/tests/test_parallel_context_retrieval.py \
  runtime_api/tests/test_chat_latency_trace.py \
  runtime_api/tests/test_model_non_thinking.py \
  runtime_api/tests/test_context_pack_and_chat.py \
  runtime_api/tests/test_realtime_ws.py \
  runtime_api/tests/test_android_runtime_api_contract.py \
  -q
```

Expected: all pass.

- [ ] **Step 2: Run worker unit tests**

Run:

```bash
PYTHONPATH=worker python3 -m pytest \
  worker/tests/test_worker_latency_trace.py \
  worker/tests/test_worker_rules_first_latency.py \
  worker/tests/test_worker_model_timeout_budget.py \
  worker/tests/test_worker_non_thinking_model.py \
  worker/tests/test_event_batcher.py \
  worker/tests/test_worker_concurrency.py \
  worker/tests/test_worker_semantics.py \
  -q
```

Expected: all pass.

- [ ] **Step 3: Run local integration latency smoke test**

Inject four events:

1. Gmail deadline: "PHONE_1 报价周五 18:00 截止。"
2. WhatsApp appointment: "明天下午4点人民广场见，带合同。"
3. WhatsApp reschedule: "人民广场见面改到周五上午10点。"
4. Telegram interview: "周三下午2点和 Maya 做面试复盘。"

Expected:

- Raw event exists within 1 second of injection.
- Clear appointment/deadline events show `parser_mode=rules_first`.
- Agenda records preserve explicit dates after relative-time normalization.
- Suggestions are generated with action labels like "稍后提醒", "查路线", "准备回复" when applicable.
- No event waits for a 60-second model timeout.

- [ ] **Step 4: Run online `/api/chat` latency smoke test**

Send:

```json
{
  "message": "请只回复：模型可用",
  "conversation_id": "latency-online",
  "client_request_id": "latency-online-1"
}
```

Expected:

- Streaming path creates assistant placeholder immediately.
- First token or first visible progress state appears under 3 seconds.
- Final answer is semantically correct.
- `context_pack.latency_trace.model_ms` records qwen latency.
- Repeating the same `client_request_id` returns duplicate cached response under 1 second.

- [ ] **Step 5: Record results**

Create `docs/superpowers/reports/2026-06-12-latency-optimization-regression-results.md` with:

```markdown
# Latency Optimization Regression Results

## Runtime Unit Tests
- Command:
- Result:

## Worker Unit Tests
- Command:
- Result:

## Local Integration
- Raw event persistence latency:
- Rules-first parser modes:
- Agenda correctness:
- Suggestion correctness:

## Online Chat
- First visible response latency:
- Final response latency:
- Duplicate request latency:
- Output correctness:

## Remaining Issues
- Issue:
- Evidence:
- Next action:
```

Every issue listed must include exact evidence from logs, HTTP output, database rows, or Android screen behavior.

---

## Deployment Plan

- [ ] **Step 1: Build containers locally**

Run:

```bash
docker compose build runtime-api worker model-router
```

Expected: build succeeds.

- [ ] **Step 2: Run local services**

Run:

```bash
docker compose up -d postgres redis runtime-api worker model-router
```

Expected: services are healthy.

- [ ] **Step 3: Deploy to cloud server**

Run the existing deployment script for `206.119.171.141` after tests pass. Preserve environment variables:

```bash
QWEN_ENABLE_THINKING=0
WORKER_ONLINE_MODEL_TIMEOUT_SECONDS=8
WORKER_CONCURRENCY=4
```

Expected: runtime API, worker, Redis, PostgreSQL, and model-router restart cleanly.

- [ ] **Step 4: Verify online health**

Expected:

- `/api/health` returns healthy.
- `/api/model/status` shows qwen provider available.
- Worker logs show no repeating 60-second model timeout for deterministic events.

---

## Acceptance Criteria

The optimization is acceptable only when all of the following are true:

1. First `/api/chat` no longer blocks the UI without visible progress.
2. qwen requests explicitly use non-thinking mode by default.
3. Simple chat does not retrieve agenda/task/RAG unless the router marks them as needed.
4. Needed context retrieval runs concurrently.
5. Raw events and user dialogue are persisted immediately.
6. Long-term memory enrichment is batched and does not block chat response or proactive suggestion generation.
7. Clear Gmail/WhatsApp/Telegram events use rules-first parsing and skip model calls.
8. Ambiguous worker model calls have an 8-second default online timeout.
9. Worker can process independent events concurrently without duplicate agenda creation.
10. Regression results include not only pass/fail, but also output correctness and latency evidence for each major step.

## Known Tradeoffs

1. Rules-first parsing may miss nuance in ambiguous social messages. This is acceptable only for high-confidence deterministic events.
2. Batched memory means semantic memory/RAG may lag raw event storage. Chat must compensate by reading recent raw events when needed.
3. Streaming improves perceived latency but does not make a slow qwen completion faster. Model latency still needs to be tracked.
4. Worker concurrency requires dedupe locks. Without locks, agenda and suggestion duplicates are likely under bursty ingestion.

## Self-Review

- Spec coverage: Covers chat routing, parallel retrieval, raw/event memory split, rules-first worker, prompt/model compactness through non-thinking and short timeout, streaming, worker concurrency, and regression evidence.
- Placeholder scan: No placeholder-only tasks are present; every task includes files, tests, commands, and expected results.
- Type consistency: New modules use explicit names `chat_router.py`, `context_parallel.py`, `event_batcher.py`, and `worker_concurrency.py`; referenced tests import those exact modules.
- Scope check: This is a single performance optimization plan with multiple coordinated tasks. The tasks can be parallelized by component but share one latency goal.
