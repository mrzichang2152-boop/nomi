# Nomi Memory Runtime v2 Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 1 Memory Runtime v2 foundation so real source events are explainable, idempotent, evidence-backed, and capable of deterministic answers for high-confidence relationship and agenda facts.

**Architecture:** Add focused `runtime_api/app/memory_runtime` modules around schema SQL, collector state, ingest idempotency, identity resolution, suggestion emission dedupe, and deterministic answer helpers. Keep existing v1 tables and worker/chat paths intact; Phase 1 introduces reusable primitives and tests before wiring broader retrieval.

**Tech Stack:** Python 3, pytest, psycopg/Postgres schema SQL strings, existing runtime API and worker conventions.

---

## File Structure

- Create: `runtime_api/app/memory_runtime/__init__.py`
  - Public exports for Phase 1 modules.
- Create: `runtime_api/app/memory_runtime/schema.py`
  - SQL DDL for v2 Phase 1 tables, indexes, and rollback-safe additive migrations.
- Create: `runtime_api/app/memory_runtime/ingest.py`
  - Source event UID/fingerprint helpers and idempotent ingest payload builder.
- Create: `runtime_api/app/memory_runtime/collector_state.py`
  - Collector state normalization and user-facing status explanation.
- Create: `runtime_api/app/memory_runtime/identity.py`
  - First-person/third-person subject resolution for source messages.
- Create: `runtime_api/app/memory_runtime/suggestions.py`
  - Suggestion emission key builder for proactive suggestion dedupe.
- Create: `runtime_api/app/memory_runtime/deterministic.py`
  - Small deterministic answer helpers for relationship and agenda evidence bundles.
- Modify: `runtime_api/app/assistant_memory.py`
  - Include Phase 1 schema SQL in existing memory schema bootstrap.
- Test: `runtime_api/tests/test_memory_runtime_phase1.py`
  - Focused contract tests covering schema, idempotency, collector explanations, identity ownership, suggestion dedupe, and deterministic answers.

---

## Task 1: Phase 1 Schema Contracts

**Files:**
- Create: `runtime_api/app/memory_runtime/schema.py`
- Create: `runtime_api/app/memory_runtime/__init__.py`
- Modify: `runtime_api/app/assistant_memory.py`
- Test: `runtime_api/tests/test_memory_runtime_phase1.py`

- [x] **Step 1: Write failing schema test**

Add to `runtime_api/tests/test_memory_runtime_phase1.py`:

```python
from runtime_api.app.memory_runtime.schema import memory_runtime_phase1_schema_sql


def joined_schema() -> str:
    return "\n".join(memory_runtime_phase1_schema_sql())


def test_phase1_schema_contains_collector_ingest_identity_suggestion_tables():
    schema = joined_schema()

    for table in [
        "collector_sessions",
        "memory_ingest_events",
        "memory_dead_letters",
        "memory_evidence",
        "memory_retrieval_traces",
        "suggestion_emissions",
        "identity_profiles",
        "identity_links",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema

    for required_index in [
        "memory_ingest_events_source_uid_idx",
        "suggestion_emissions_key_idx",
        "memory_evidence_source_scope_idx",
        "identity_links_external_idx",
    ]:
        assert required_index in schema

    assert "source_event_uid TEXT NOT NULL UNIQUE" in schema
    assert "suggestion_key TEXT NOT NULL UNIQUE" in schema
```

- [x] **Step 2: Run test and verify RED**

Run:

```bash
python3 -m pytest runtime_api/tests/test_memory_runtime_phase1.py::test_phase1_schema_contains_collector_ingest_identity_suggestion_tables -q
```

Expected: FAIL because `runtime_api.app.memory_runtime.schema` does not exist.

- [x] **Step 3: Implement minimal schema module**

Create `runtime_api/app/memory_runtime/schema.py` with `memory_runtime_phase1_schema_sql() -> list[str]` returning additive `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` statements for the Phase 1 tables.

Create `runtime_api/app/memory_runtime/__init__.py` exporting `memory_runtime_phase1_schema_sql`.

Modify `runtime_api/app/assistant_memory.py`:

```python
from runtime_api.app.memory_runtime.schema import memory_runtime_phase1_schema_sql
```

Then append `memory_runtime_phase1_schema_sql()` to `assistant_memory_schema_sql()`.

- [x] **Step 4: Run test and verify GREEN**

Run:

```bash
python3 -m pytest runtime_api/tests/test_memory_runtime_phase1.py::test_phase1_schema_contains_collector_ingest_identity_suggestion_tables -q
```

Expected: PASS.

---

## Task 2: Ingest Idempotency

**Files:**
- Create: `runtime_api/app/memory_runtime/ingest.py`
- Test: `runtime_api/tests/test_memory_runtime_phase1.py`

- [x] **Step 1: Write failing ingest tests**

Append:

```python
from runtime_api.app.memory_runtime.ingest import (
    build_source_event_uid,
    build_source_fingerprint,
    normalize_ingest_payload,
)


def test_source_event_uid_prefers_platform_message_id():
    uid = build_source_event_uid(
        source="whatsapp",
        account_id="wa:user",
        conversation_id="chat-a",
        message_id="msg-123",
        speaker_id="wang",
        text="明天下午3点半人民广场见",
        source_created_at="2026-07-01T19:29:00+08:00",
    )

    assert uid == "whatsapp:wa:user:chat-a:msg-123"


def test_source_event_uid_falls_back_to_stable_fingerprint():
    first = build_source_event_uid(
        source="telegram",
        account_id="tg:user",
        conversation_id="chat-b",
        message_id="",
        speaker_id="maya",
        text="周五10点静安寺地铁站见 Maya",
        source_created_at="2026-07-01T19:30:12+08:00",
    )
    second = build_source_event_uid(
        source="telegram",
        account_id="tg:user",
        conversation_id="chat-b",
        message_id=None,
        speaker_id="maya",
        text=" 周五10点静安寺地铁站见 Maya ",
        source_created_at="2026-07-01T19:30:45+08:00",
    )

    assert first == second
    assert first.startswith("telegram:tg:user:chat-b:fp:")


def test_normalize_ingest_payload_preserves_trace_fields():
    payload = normalize_ingest_payload(
        source="whatsapp",
        account_id="wa:user",
        conversation_id="chat-a",
        contact_id="大刚",
        speaker_id="wang",
        message_id="msg-1",
        text="我儿子叫王刚",
        source_created_at="2026-07-01T19:29:00+08:00",
        observed_at="2026-07-01T19:29:03+08:00",
        raw_event_id="event-1",
    )

    assert payload["source_event_uid"] == "whatsapp:wa:user:chat-a:msg-1"
    assert payload["source_fingerprint"] == build_source_fingerprint(
        source="whatsapp",
        account_id="wa:user",
        conversation_id="chat-a",
        speaker_id="wang",
        text="我儿子叫王刚",
        source_created_at="2026-07-01T19:29:00+08:00",
    )
    assert payload["status"] == "raw_written"
```

- [x] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest runtime_api/tests/test_memory_runtime_phase1.py::test_source_event_uid_prefers_platform_message_id runtime_api/tests/test_memory_runtime_phase1.py::test_source_event_uid_falls_back_to_stable_fingerprint runtime_api/tests/test_memory_runtime_phase1.py::test_normalize_ingest_payload_preserves_trace_fields -q
```

Expected: FAIL because `runtime_api.app.memory_runtime.ingest` does not exist.

- [x] **Step 3: Implement minimal ingest helpers**

Implement normalized text, 1-minute source timestamp bucketing for fingerprint fallback, SHA-256 16-character fingerprint, and payload builder.

- [x] **Step 4: Run tests and verify GREEN**

Run the same pytest command. Expected: PASS.

---

## Task 3: Collector State Explanations

**Files:**
- Create: `runtime_api/app/memory_runtime/collector_state.py`
- Test: `runtime_api/tests/test_memory_runtime_phase1.py`

- [x] **Step 1: Write failing collector tests**

Append:

```python
from runtime_api.app.memory_runtime.collector_state import (
    normalize_collector_state,
    explain_collector_gap,
)


def test_collector_state_explains_login_required_without_claiming_no_records():
    state = normalize_collector_state(
        source="gmail",
        account_id="gmail:user",
        login_state="login_required",
        last_success_event_at="2026-07-01T10:00:00+08:00",
        last_error_code="oauth_expired",
        last_error_message="需要重新登录",
    )

    explanation = explain_collector_gap(state, question="我最近有要开的会吗？")

    assert explanation["source"] == "gmail"
    assert explanation["can_claim_no_records"] is False
    assert "需要重新登录" in explanation["message"]
    assert "2026-07-01T10:00:00+08:00" in explanation["message"]


def test_collecting_state_allows_normal_memory_answer():
    state = normalize_collector_state(
        source="whatsapp",
        account_id="wa:user",
        login_state="collecting",
        last_success_event_at="2026-07-03T10:00:00+08:00",
    )

    explanation = explain_collector_gap(state, question="明天我有哪些安排？")

    assert explanation["can_claim_no_records"] is True
    assert explanation["severity"] == "ok"
```

- [x] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest runtime_api/tests/test_memory_runtime_phase1.py::test_collector_state_explains_login_required_without_claiming_no_records runtime_api/tests/test_memory_runtime_phase1.py::test_collecting_state_allows_normal_memory_answer -q
```

Expected: FAIL because collector state module is missing.

- [x] **Step 3: Implement collector state helpers**

Implement allowed states: `unknown`, `logged_out`, `login_required`, `logged_in`, `collecting`, `degraded`, `blocked`. Only `collecting` and fresh enough `logged_in` may allow “no records” claims.

- [x] **Step 4: Run tests and verify GREEN**

Run same pytest command. Expected: PASS.

---

## Task 4: Identity Ownership Resolution

**Files:**
- Create: `runtime_api/app/memory_runtime/identity.py`
- Test: `runtime_api/tests/test_memory_runtime_phase1.py`

- [x] **Step 1: Write failing identity tests**

Append:

```python
from runtime_api.app.memory_runtime.identity import resolve_fact_subject


def test_first_person_whatsapp_fact_belongs_to_speaker_not_user():
    result = resolve_fact_subject(
        text="我儿子叫王刚",
        source="whatsapp",
        owner_user_id="default",
        speaker_id="wang",
        speaker_display_name="大刚",
        known_entities=[],
    )

    assert result["subject_id"] == "wang"
    assert result["subject_label"] == "大刚"
    assert result["ownership"] == "speaker"
    assert result["confidence"] >= 0.8


def test_third_person_fact_uses_named_subject():
    result = resolve_fact_subject(
        text="王超他儿子叫张红",
        source="whatsapp",
        owner_user_id="default",
        speaker_id="wang",
        speaker_display_name="大刚",
        known_entities=["王超", "张红"],
    )

    assert result["subject_label"] == "王超"
    assert result["ownership"] == "named_entity"
    assert result["confidence"] >= 0.8


def test_first_person_chat_with_nomi_belongs_to_owner():
    result = resolve_fact_subject(
        text="我儿子叫王刚",
        source="android_chat",
        owner_user_id="default",
        speaker_id="default",
        speaker_display_name="我",
        known_entities=[],
    )

    assert result["subject_id"] == "default"
    assert result["ownership"] == "owner"
```

- [x] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest runtime_api/tests/test_memory_runtime_phase1.py::test_first_person_whatsapp_fact_belongs_to_speaker_not_user runtime_api/tests/test_memory_runtime_phase1.py::test_third_person_fact_uses_named_subject runtime_api/tests/test_memory_runtime_phase1.py::test_first_person_chat_with_nomi_belongs_to_owner -q
```

Expected: FAIL because identity module is missing.

- [x] **Step 3: Implement minimal identity resolver**

Implement first-person source ownership and a conservative third-person pattern for `X 他/她/的? 儿子/女儿/朋友/同事` with known entity fallback.

- [x] **Step 4: Run tests and verify GREEN**

Run same pytest command. Expected: PASS.

---

## Task 5: Suggestion Emission Dedupe

**Files:**
- Create: `runtime_api/app/memory_runtime/suggestions.py`
- Test: `runtime_api/tests/test_memory_runtime_phase1.py`

- [x] **Step 1: Write failing suggestion tests**

Append:

```python
from runtime_api.app.memory_runtime.suggestions import build_suggestion_key


def test_suggestion_key_dedupes_same_evidence_version():
    first = build_suggestion_key(
        suggestion_type="agenda_followup",
        primary_evidence_id="ev-1",
        primary_evidence_version="hash-a",
        target_user_id="default",
        channel="android",
    )
    second = build_suggestion_key(
        suggestion_type="agenda_followup",
        primary_evidence_id="ev-1",
        primary_evidence_version="hash-a",
        target_user_id="default",
        channel="android",
    )

    assert first == second


def test_suggestion_key_changes_when_evidence_version_changes():
    old = build_suggestion_key("agenda_followup", "ev-1", "hash-a", "default", "android")
    new = build_suggestion_key("agenda_followup", "ev-1", "hash-b", "default", "android")

    assert old != new
```

- [x] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest runtime_api/tests/test_memory_runtime_phase1.py::test_suggestion_key_dedupes_same_evidence_version runtime_api/tests/test_memory_runtime_phase1.py::test_suggestion_key_changes_when_evidence_version_changes -q
```

Expected: FAIL because suggestions module is missing.

- [x] **Step 3: Implement suggestion key builder**

Use normalized fields and SHA-256 to produce deterministic `suggestion_type:target_user_id:channel:<hash>` keys.

- [x] **Step 4: Run tests and verify GREEN**

Run same pytest command. Expected: PASS.

---

## Task 6: Deterministic Answers for Phase 1 Facts

**Files:**
- Create: `runtime_api/app/memory_runtime/deterministic.py`
- Test: `runtime_api/tests/test_memory_runtime_phase1.py`

- [x] **Step 1: Write failing deterministic answer tests**

Append:

```python
from runtime_api.app.memory_runtime.deterministic import (
    answer_relationship_question,
    answer_agenda_time_question,
)


def test_answer_relationship_question_uses_active_edge_evidence():
    answer = answer_relationship_question(
        question="张红是谁？",
        edges=[
            {
                "subject_label": "王超",
                "relation_type": "has_son",
                "object_label": "张红",
                "status": "active",
                "confidence": 0.9,
                "source": "whatsapp",
                "source_created_at": "2026-07-01T19:29:00+08:00",
            }
        ],
    )

    assert answer["answered"] is True
    assert answer["answer"] == "张红是王超的儿子。"
    assert answer["evidence"][0]["source"] == "whatsapp"


def test_answer_agenda_time_question_uses_absolute_date_and_ignores_cancelled():
    answer = answer_agenda_time_question(
        question="人民广场会面是几月几号几点？",
        agenda_items=[
            {
                "title": "人民广场见面",
                "status": "canceled",
                "start_at": "2026-07-04T15:30:00+08:00",
                "place": "人民广场",
            },
            {
                "title": "人民广场见面",
                "status": "scheduled",
                "start_at": "2026-07-05T15:30:00+08:00",
                "place": "人民广场",
                "source": "whatsapp",
            },
        ],
    )

    assert answer["answered"] is True
    assert "2026-07-05" in answer["answer"]
    assert "15:30" in answer["answer"]
    assert "明天" not in answer["answer"]
```

- [x] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest runtime_api/tests/test_memory_runtime_phase1.py::test_answer_relationship_question_uses_active_edge_evidence runtime_api/tests/test_memory_runtime_phase1.py::test_answer_agenda_time_question_uses_absolute_date_and_ignores_cancelled -q
```

Expected: FAIL because deterministic module is missing.

- [x] **Step 3: Implement deterministic helpers**

Implement relation phrase mapping for `has_son` and agenda answer formatting using absolute ISO date/time.

- [x] **Step 4: Run tests and verify GREEN**

Run same pytest command. Expected: PASS.

---

## Task 7: Focused Phase 1 Regression

**Files:**
- Test: `runtime_api/tests/test_memory_runtime_phase1.py`

- [x] **Step 1: Run all Phase 1 tests**

Run:

```bash
python3 -m pytest runtime_api/tests/test_memory_runtime_phase1.py -q
```

Expected: all tests pass.

- [x] **Step 2: Run existing adjacent tests**

Run:

```bash
python3 -m pytest runtime_api/tests/test_chat_router.py runtime_api/tests/test_context_pack_and_chat.py worker/tests/test_worker_semantics.py -q
```

Expected: existing adjacent tests pass or failures are documented as pre-existing/unrelated with exact failing names.

- [x] **Step 3: Update gap report if needed**

If any Phase 1 spec item remains unimplemented, create or update:

`docs/superpowers/reports/2026-07-03-memory-runtime-v2-phase1-gaps.md`

with:

- gap
- affected spec line/section
- current implementation status
- next step
- whether it blocks cloud/device regression

---

## Self-Review

- Spec coverage: this plan covers Phase 1 only. Phase 2+ graph/RAG/cache integration remains intentionally out of this first development slice.
- No placeholders: every task has concrete files, tests, commands, and expected results.
- Type consistency: Phase 1 APIs use plain dicts and strings to fit current code style and avoid premature ORM abstractions.

## Execution Record

- Phase 1 RED check: `python3 -m pytest runtime_api/tests/test_memory_runtime_phase1.py -q` initially failed because `runtime_api.app.memory_runtime` did not exist.
- Schema closure RED check: `python3 -m pytest runtime_api/tests/test_memory_runtime_phase1.py::test_phase1_schema_creates_tables_before_indexes_that_reference_them -q` failed until `memory_assertions`, `memory_nodes`, and `memory_edges` table definitions were added before indexes.
- Phase 1 GREEN check: `python3 -m pytest runtime_api/tests/test_memory_runtime_phase1.py -q` returned `14 passed`.
- Adjacent regression found and fixed: `runtime_api/tests/test_context_pack_and_chat.py::test_chat_endpoint_builds_request_scope_caps_context_candidates_and_persists_answer_trace` exposed that layered memory retrieval was reading 24 candidates through `limit * 3`, then 8 candidates after the first tightening. The final behavior reads the main candidate window of 12 and then filters layer-specific KV/Graph/RAG/Timeline results.
- Adjacent regression GREEN check: `python3 -m pytest runtime_api/tests/test_chat_router.py runtime_api/tests/test_context_pack_and_chat.py worker/tests/test_worker_semantics.py -q` returned `196 passed`.
- Gap report: no Phase 1 implementation gap was left after local verification. Cloud/device wiring remains outside this Phase 1 local foundation slice.
