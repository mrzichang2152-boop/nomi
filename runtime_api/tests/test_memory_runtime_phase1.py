from runtime_api.app.memory_runtime.collector_state import (
    explain_collector_gap,
    normalize_collector_state,
)
from runtime_api.app.memory_runtime.deterministic import (
    answer_agenda_time_question,
    answer_relationship_question,
)
from runtime_api.app.memory_runtime.identity import resolve_fact_subject
from runtime_api.app.memory_runtime.ingest import (
    build_source_event_uid,
    build_source_fingerprint,
    normalize_ingest_payload,
)
from runtime_api.app.memory_runtime.schema import memory_runtime_phase1_schema_sql
from runtime_api.app.memory_runtime.suggestions import build_suggestion_key


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


def test_phase1_schema_creates_tables_before_indexes_that_reference_them():
    schema = joined_schema()

    for table in ["memory_assertions", "memory_nodes", "memory_edges"]:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema
        assert schema.index(f"CREATE TABLE IF NOT EXISTS {table}") < schema.index(f"ON {table}(")


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
