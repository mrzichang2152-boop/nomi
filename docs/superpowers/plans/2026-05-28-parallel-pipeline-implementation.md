# Parallel Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Nomi's pipeline layer in parallel, giving every planned core pipeline a concrete state-machine runner, content-level tests, and trace-compatible outputs.

**Architecture:** Keep `runtime_api/app/main.py` as the current API boundary, but move pipeline-specific execution into focused modules under `runtime_api/app/pipelines/`. Each worker owns a disjoint module/test pair. The parent session owns shared integration, final review, and full regression.

**Tech Stack:** Python, FastAPI runtime helpers, pytest, existing PostgreSQL/Redis abstractions, existing Qwen model client conventions.

---

## Shared Contract

Every worker must return pipeline results shaped for the existing `run_core_pipeline()` contract:

```python
{
    "pipeline_id": "route_pipeline",
    "status": "completed_read_only",
    "required_slots": ["destination"],
    "resolved_slots": {"destination": "武康路"},
    "missing_slots": [],
    "risk": {"permission": "read_only", "confirmation_required": False, "final_user_confirmation": False},
    "execution_guard": {"permission": "read_only", "policy": "allowed_after_login"},
    "external_effects": [],
    "writeback_targets": ["assistant_turns", "task_trace"],
    "steps": [{"name": "识别目的地", "status": "completed"}],
    "output": {"summary": "readable user-facing result or proposal"},
    "provider_calls": [],
    "writeback_plan": []
}
```

No worker may enable real external effects. Provider-backed actions must stop at `draft_ready`, `needs_user_input`, `confirmation_required`, or `blocked`.

## Parallel Work Packages

### Worker A: Input, Memory, Context

**Owns files:**

- Create/modify: `runtime_api/app/pipelines/system.py`
- Create/modify: `runtime_api/tests/test_pipeline_system.py`

**Pipelines:**

- `event_ingestion_pipeline`
- `memory_write_pipeline`
- `context_pack_pipeline`

**Acceptance:**

- Event ingestion normalizes source/event/timestamp and emits a downstream job plan.
- Memory write returns separate KV/graph/RAG/vector write plans and degrades when embedding is unavailable.
- Context pack returns included/excluded evidence ids and does not include unrelated contact data.

### Worker B: Search And Communication

**Owns files:**

- Create/modify: `runtime_api/app/pipelines/communication.py`
- Create/modify: `runtime_api/tests/test_pipeline_communication.py`

**Pipelines:**

- `personal_search_pipeline`
- `chat_response_pipeline`
- `reply_pipeline`
- `email_pipeline`

**Acceptance:**

- Personal search ranks scoped evidence and returns citations.
- Chat response returns a streaming-ready plan and context snapshot writeback plan.
- Reply produces a draft and blocks send until confirmation.
- Email extracts summarize/task/draft actions and blocks send/archive/label until confirmation.

### Worker C: Agenda, Todo, Proactive

**Owns files:**

- Create/modify: `runtime_api/app/pipelines/agenda.py`
- Create/modify: `runtime_api/tests/test_pipeline_agenda.py`

**Pipelines:**

- `agenda_pipeline`
- `task_todo_pipeline`
- `proactive_suggestion_pipeline`

**Acceptance:**

- Agenda handles create, reschedule, cancel, fuzzy missing fields, and unsupported exact-time rejection.
- Todo extracts owner, title, due window, and reminder plan.
- Proactive suggestions return action cards with correct risk labels and duplicate/cooldown metadata.

### Worker D: External Task Preparation

**Owns files:**

- Create/modify: `runtime_api/app/pipelines/actions.py`
- Create/modify: `runtime_api/tests/test_pipeline_actions.py`

**Pipelines:**

- `route_pipeline`
- `ride_pipeline`
- `shopping_pipeline`
- `payment_bill_pipeline`
- `document_file_pipeline`
- `account_login_pipeline`

**Acceptance:**

- Route returns read-only route request or provider-needed status.
- Ride resolves pickup/destination and never books without final confirmation.
- Shopping prepares comparison/cart proposal and never purchases.
- Payment asks for amount/counterparty when vague and never transfers.
- Document file prepares read/summary/write proposal and blocks writes/shares.
- Account login opens/records provider login preparation without handling credentials.

### Parent Session: Governance And Integration

**Owns files:**

- Create/modify: `runtime_api/app/pipelines/__init__.py`
- Create/modify: `runtime_api/app/pipelines/base.py`
- Modify: `runtime_api/app/main.py`
- Modify: `runtime_api/tests/test_core_pipeline_engine.py`
- Modify: `scripts/validate-core-pipelines-openclaw.py`
- Modify: `docs/superpowers/specs/2026-05-28-pipeline-management-design.md`

**Pipelines:**

- `governance_audit_pipeline`
- integration for all pipeline modules

**Acceptance:**

- `run_core_pipeline()` delegates to the new pipeline runner where available.
- All 18 pipelines return content-bearing execution results.
- Existing API responses remain backward-compatible.
- Validation prints semantically reasonable outputs for representative pipelines.

## Execution Order

- [x] Dispatch Workers A-D in parallel with strict ownership.
- [x] Parent creates shared base interfaces and integration shim.
- [x] Parent adds tests proving `run_core_pipeline()` uses module runners.
- [x] Merge worker outputs and resolve import/API mismatches.
- [x] Run targeted tests per worker.
- [x] Run full `python3 -m pytest -q`.
- [x] Run `python3 scripts/validate-core-pipelines-openclaw.py`.
- [x] Run `python3 scripts/validate-private-event-processing.py`.
- [x] Run `git diff --check`.
- [x] Update pipeline management design with implemented status and remaining gaps.

## Wave 2 Internal Completion On 2026-05-28

Completed without connecting real external services:

- system pipelines: stable dedupe key, duplicate skip, schema quarantine, memory layer status/retry plan, context ranking/exclusion metrics
- communication pipelines: private-scope ambiguity question, evidence ranking, leakage blocking, confirmation cards, email internal candidates/provider plans, chat action handoff
- agenda/proactive pipelines: merge plan, conflict plan, notification plan, todo lifecycle, reminder adjustment, duplicate/cooldown suppression, notification payload
- action pipelines: unified provider call plan, confirmation cards, safety checks, blocked effects, normalized provider-style outputs
- governance/integration: provider-call audit and confirmation-ledger writeback plans, top-level module control fields preserved through `run_core_pipeline()`

Observed focused verification before full regression:

- `python3 -m pytest runtime_api/tests/test_pipeline_system.py runtime_api/tests/test_pipeline_communication.py runtime_api/tests/test_pipeline_agenda.py runtime_api/tests/test_pipeline_actions.py runtime_api/tests/test_core_pipeline_engine.py -q` -> `64 passed`
- `python3 scripts/validate-core-pipelines-openclaw.py` -> 20 stages, all reasonable; Wave 2 internal stage has 14 semantic checks, all true

Fresh final verification:

- `python3 -m pytest -q` -> `234 passed`
- `python3 scripts/validate-private-event-processing.py` -> 16 reports, all reasonable
- `git diff --check` -> no whitespace errors

Remaining after this wave:

- real provider adapters are intentionally not connected in this wave
- physical provider-call trace and confirmation-ledger tables/UI are planned but not yet created

## Quality Bar

Each pipeline is only considered implemented when its test checks actual output content: slots, status, user-visible summary, confirmation/risk fields, writeback plan, and provider/external-effect blocking. Passing commands alone are not enough.
