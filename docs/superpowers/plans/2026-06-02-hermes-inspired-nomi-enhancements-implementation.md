# Hermes-Inspired Nomi Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the six Hermes-inspired Nomi enhancements from `docs/superpowers/specs/2026-06-02-hermes-inspired-nomi-enhancements-design.md` without replacing the existing private-event, memory, pipeline, OpenClaw, Composio, or Android architecture.

**Architecture:** Build the enhancements as server-side modules that plug into existing runtime API entrypoints. Start with model reliability because qwen3.6 failures currently affect user-visible chat, then add curated memory/session search, event gateway normalization, durable task recovery, tool registry, and workflow distillation.

**Tech Stack:** Python FastAPI runtime API, PostgreSQL via psycopg, Redis/WebSocket realtime channel, pytest, existing Android/Web H5 clients.

---

## File Structure

- Create `runtime_api/app/model_gateway.py`: provider registry, health checks, circuit breaker, streaming/non-streaming gateway, model status payloads.
- Modify `runtime_api/app/model_client.py`: keep Qwen-compatible HTTP adapter and reuse parsing helpers.
- Modify `runtime_api/app/main.py`: initialize model schema, add `/api/model/status`, replace direct `QwenClient` calls in chat/WebSocket/model-assisted parsers where appropriate.
- Create `runtime_api/tests/test_model_gateway.py`: unit tests for provider selection, fallback, health classification, and error payloads.
- Modify `runtime_api/tests/test_auth_and_model.py`: API status tests for `/api/model/status`.
- Modify `runtime_api/tests/test_realtime_ws.py`: websocket failure tests should verify gateway error payloads are clear and nonblank.
- Later create `runtime_api/app/assistant_memory.py`, `runtime_api/app/private_events.py`, `runtime_api/app/task_orchestrator.py`, `runtime_api/app/tool_registry.py`, and `runtime_api/app/workflow_distillation.py`.

## Task 1: Model Provider Routing And Fallback

**Files:**
- Create: `runtime_api/app/model_gateway.py`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_model_gateway.py`
- Test: `runtime_api/tests/test_auth_and_model.py`
- Test: `runtime_api/tests/test_realtime_ws.py`

- [x] **Step 1: Write failing gateway tests**

```python
@pytest.mark.asyncio
async def test_gateway_falls_back_when_primary_stream_fails():
    primary = FakeProvider("primary", stream_error=RuntimeError("connection refused"))
    fallback = FakeProvider("fallback", stream_chunks=["你", "好"])
    gateway = ModelGateway([primary, fallback])

    chunks = []
    async for chunk in gateway.stream_chat([{"role": "user", "content": "hi"}]):
        chunks.append(chunk.delta)

    assert chunks == ["你", "好"]
    assert gateway.status()["active_provider_id"] == "fallback"
    assert gateway.status()["providers"][0]["state"] == "open"
```

- [x] **Step 2: Verify the test fails before implementation**

Run: `python3 -m pytest runtime_api/tests/test_model_gateway.py -q`

Expected: FAIL because `app.model_gateway` does not exist.

- [x] **Step 3: Implement minimal `ModelGateway`**

Implement:

- `ModelProviderConfig`
- `ProviderRuntimeState`
- `ModelGateway.stream_chat`
- `ModelGateway.chat`
- `ModelGateway.health_status`
- provider failure classification
- in-memory circuit breaker state

- [x] **Step 4: Verify gateway tests pass**

Run: `python3 -m pytest runtime_api/tests/test_model_gateway.py -q`

Expected: PASS.

- [x] **Step 5: Add status endpoint failing test**

```python
def test_model_status_endpoint_reports_primary_provider(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    client = TestClient(main.app)
    response = client.get("/api/model/status", headers={"x-par-password": "secret"})

    assert response.status_code == 200
    assert response.json()["providers"][0]["provider_id"]
```

- [x] **Step 6: Implement `/api/model/status` and schema hooks**

Add endpoint and local tables:

- `model_providers`
- `model_health_checks`
- `model_request_traces`

The endpoint may return in-memory provider state even when test DB persistence is disabled.

- [x] **Step 7: Wire chat and WebSocket through `ModelGateway`**

Replace direct `QwenClient(MODEL_BASE_URL, MODEL_NAME).chat(...)` and `.stream_chat(...)` in primary chat paths with gateway calls. Ensure errors become explicit user-visible events.

- [x] **Step 8: Run focused regression**

Run:

```bash
python3 -m pytest runtime_api/tests/test_model_gateway.py runtime_api/tests/test_auth_and_model.py runtime_api/tests/test_realtime_ws.py runtime_api/tests/test_context_pack_and_chat.py -q
```

Expected: all selected tests pass, and model unavailable paths return clear error messages.

Completed verification:

```bash
python3 -m pytest runtime_api/tests/test_model_gateway.py runtime_api/tests/test_auth_and_model.py runtime_api/tests/test_realtime_ws.py runtime_api/tests/test_context_pack_and_chat.py -q
# 78 passed

python3 -m pytest runtime_api/tests -q
# 216 passed

python3 -m py_compile runtime_api/app/model_gateway.py runtime_api/app/main.py
# exit 0
```

## Task 2: Curated Memory And Session Search

**Files:**
- Create: `runtime_api/app/assistant_memory.py`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_assistant_memory.py`
- Test: `runtime_api/tests/test_context_pack_and_chat.py`

- [x] **Step 1: Write failing tests for short-reply resolution**

Test that after Nomi asks whether to核对成本与利润率, the user reply "需要" includes the prior assistant question and active task in the context pack.

- [x] **Step 2: Implement assistant profile memory tables**

Add:

- `assistant_profile_memories`
- `conversation_summaries`
- `conversation_session_index`

- [x] **Step 3: Implement token-aware session search**

Use existing token estimator and context budget rules. Short replies must boost previous assistant questions and active task state.

- [x] **Step 4: Verify context snapshots**

Tests must inspect included prior question, active task reference, exclusion reasons, and token budget output.

Completed verification:

```bash
python3 -m pytest runtime_api/tests/test_assistant_memory.py runtime_api/tests/test_context_pack_and_chat.py::test_build_context_pack_exposes_session_search_for_short_reply runtime_api/tests/test_context_pack_and_chat.py::test_chat_endpoint_persists_turns_uses_context_pack_and_returns_trace -q
# 5 passed
```

## Task 3: Multi-Channel Private Event Gateway

**Files:**
- Create: `runtime_api/app/private_events.py`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_private_event_gateway.py`

- [x] **Step 1: Write failing envelope normalization tests**

Test Gmail, WhatsApp, Telegram, browser, and Nomi chat inputs normalize to the same event envelope shape.

- [x] **Step 2: Implement event envelope and dedupe hash**

Add source ids, source account, conversation id, occurred/observed timestamps, sensitivity, visibility scope, raw payload reference, and dedupe hash.

- [x] **Step 3: Route normalized events into existing memory/event processors**

Ensure every normalized event is persisted before classification decisions.

- [x] **Step 4: Verify duplicate prevention**

Run tests proving duplicate source events do not create duplicate agenda/proactive outputs.

Completed verification:

```bash
python3 -m pytest runtime_api/tests/test_private_event_gateway.py runtime_api/tests/test_context_pack_and_chat.py::test_schema_bootstrap_creates_private_event_gateway_tables -q
# 5 passed
```

## Task 4: Background Task Orchestration And Recovery

**Files:**
- Create: `runtime_api/app/task_orchestrator.py`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_task_orchestrator.py`

- [x] **Step 1: Write failing durable task tests**

Test that a queued task with an expired lease resumes once and does not duplicate output.

- [x] **Step 2: Implement `task_runs`, `task_steps`, and `notification_outbox`**

Persist inputs before execution and outputs after execution.

- [x] **Step 3: Implement WebSocket replay and ack**

Reconnect should replay active unacked notifications and skip dismissed/acked ones.

- [x] **Step 4: Verify restart behavior**

Tests must inspect task status transitions, retry counts, outbox delivery status, and duplicate suppression.

Completed verification:

```bash
python3 -m pytest runtime_api/tests/test_task_orchestrator.py runtime_api/tests/test_context_pack_and_chat.py::test_schema_bootstrap_creates_task_orchestrator_tables -q
# 4 passed
```

## Task 5: MCP, Composio, And OpenClaw Tool Plugin Architecture

**Files:**
- Create: `runtime_api/app/tool_registry.py`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_tool_registry.py`
- Test: `runtime_api/tests/test_core_pipeline_engine.py`

- [x] **Step 1: Write failing capability-first routing tests**

Test that "帮我打车", "帮我发邮件", and long-tail website tasks route to capability first, then adapter.

- [x] **Step 2: Implement capability catalog and adapter registry**

Adapters include Composio, OpenClaw, browser, and local system tools.

- [x] **Step 3: Integrate permission gates**

Read-only runs may execute; external messages, rides, purchases, payments, and destructive actions require explicit final confirmation.

- [x] **Step 4: Verify connection-missing behavior**

If Gmail/Calendar/etc. are not connected, Nomi should surface a connect-account action rather than silently failing.

Completed verification:

```bash
python3 -m pytest runtime_api/tests/test_tool_registry.py runtime_api/tests/test_context_pack_and_chat.py::test_schema_bootstrap_creates_tool_registry_tables runtime_api/tests/test_core_pipeline_engine.py::test_route_tool_request_includes_capability_first_tool_registry_decision -q
# 6 passed
```

Manual output review:

- Ride request routes to `ride.prepare_booking` -> `ride_pipeline` -> `composio`, with final confirmation required.
- Missing Gmail connection returns `connect_required` with `connect_action.toolkit=gmail`, not a silent tool failure.
- Long-tail website form task routes to OpenClaw with minimal context and `submit/pay/purchase/book` forbidden.

## Task 6: Skill And Pipeline Distillation

**Files:**
- Create: `runtime_api/app/workflow_distillation.py`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_workflow_distillation.py`

- [x] **Step 1: Write failing workflow candidate tests**

Repeated successful OpenClaw/Composio traces should create a pipeline candidate but not enable it automatically.

- [x] **Step 2: Implement pattern mining tables**

Add:

- `workflow_patterns`
- `pipeline_candidates`
- `skill_evaluation_runs`

- [x] **Step 3: Implement candidate evaluation**

Evaluate positive, ambiguous, unsafe, and failure cases. Store reasonableness review.

- [x] **Step 4: Implement human approval gate**

Only approved candidates can become enabled local skills or deterministic pipeline definitions.

Completed verification:

```bash
python3 -m pytest runtime_api/tests/test_workflow_distillation.py runtime_api/tests/test_context_pack_and_chat.py::test_schema_bootstrap_creates_workflow_distillation_tables -q
# 6 passed
```

Manual output review:

- Repeated read-only OpenClaw trace creates `candidate_supplier_quote_download_summary_pipeline`, preserves step order, and remains `enabled=false`.
- Purchase/payment candidate keeps `final_user_confirmation=true`, blocks external effects, and remains `pending_review`.
- A candidate cannot be enabled before offline evaluation passes and a reviewer approves it.

## Final Regression

Run:

```bash
python3 -m pytest runtime_api/tests -q
```

Then run online smoke checks against the cloud server:

- `/api/model/status`
- WebSocket chat when qwen3.6 is unavailable
- one normalized Gmail-like event
- one normalized WhatsApp-like event
- one proactive suggestion replay
- one core pipeline route
- one OpenClaw long-tail route
- one Composio missing-connection route

The final report must include actual intermediate outputs and whether they are reasonable, not only pass/fail status.

## Self-Review

- The plan covers all six sections in the spec.
- Task 1 is first because current model unavailability blocks user-facing verification.
- Every task starts with failing tests.
- External-effect actions remain behind confirmation gates.
- Existing KV + knowledge graph + RAG memory is extended, not replaced.
- Existing core pipeline and OpenClaw routing remains the routing backbone.
