import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_persist_semantics_skips_memory_and_timeline_when_event_already_processed():
    from app.worker import persist_semantics

    executed = []

    class Cursor:
        def __init__(self, rowcount):
            self.rowcount = rowcount

    class Conn:
        def execute(self, sql, params=()):
            executed.append(sql)
            if "INSERT INTO semantic_events" in sql:
                return Cursor(0)
            return Cursor(1)

    persist_semantics(
        Conn(),
        "11111111-1111-1111-1111-111111111111",
        "2026-05-26T00:00:00+00:00",
        {
            "intent": "social_plan",
            "entities": {},
            "importance": 0.9,
            "summary": "重复事件",
            "model_version": "test",
        },
    )

    assert len(executed) == 1
    assert "INSERT INTO semantic_events" in executed[0]


def test_persist_semantics_writes_vector_and_suggestion_for_new_event():
    from app.worker import persist_semantics

    executed = []

    class Cursor:
        def __init__(self, rowcount):
            self.rowcount = rowcount

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            return Cursor(1)

    persist_semantics(
        Conn(),
        "11111111-1111-1111-1111-111111111111",
        "2026-05-26T00:00:00+00:00",
        {
            "intent": "social_plan",
            "entities": {"person": "Caroline"},
            "importance": 0.9,
            "summary": "Caroline plans to go camping in June.",
            "model_version": "test",
        },
    )

    sql_statements = "\n".join(sql for sql, _ in executed)
    assert "INSERT INTO memory_vectors" in sql_statements
    assert "INSERT INTO proactive_suggestions" in sql_statements
    assert "INSERT INTO facts" in sql_statements
    assert "INSERT INTO memory_states" in sql_statements


def test_rule_extract_semantics_marks_nomi_user_instruction_and_feedback():
    from app.worker import rule_extract_semantics

    instruction = rule_extract_semantics(
        "nomi_chat",
        "user_message",
        {
            "role": "user",
            "content": "帮我盯一下周末和 Alex 见面的事",
            "conversation_id": "conv-1",
        },
    )
    feedback = rule_extract_semantics(
        "nomi_chat",
        "user_message",
        {
            "role": "user",
            "content": "这件事不用提醒我，以后别提醒优惠券",
            "conversation_id": "conv-1",
        },
    )

    assert instruction["intent"] == "user_instruction"
    assert instruction["entities"]["conversation_id"] == "conv-1"
    assert "周末和 Alex" in instruction["summary"]
    assert instruction["importance"] >= 0.72
    assert feedback["intent"] == "user_feedback"
    assert "别提醒" in feedback["summary"]
    assert feedback["importance"] >= 0.8


def test_agenda_candidate_for_fuzzy_social_plan_has_missing_exact_time_and_place():
    from app.worker import agenda_candidate_from_semantic

    candidate = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-05-28T09:00:00+00:00",
        {
            "intent": "social_plan",
            "summary": "Alex 说那就周日见。",
            "importance": 0.82,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
            "raw_data": {"chat_name": "Alex", "sender": "Alex", "message": "那就周日吧"},
        },
    )

    assert candidate is not None
    assert candidate["type"] == "appointment"
    assert candidate["certainty"] == "fuzzy"
    assert candidate["status"] == "scheduled"
    assert "exact_time" in candidate["missing_fields"]
    assert "exact_place" in candidate["missing_fields"]
    assert candidate["needs_clarification"] is True
    assert candidate["participants"] == ["Alex"]
    assert candidate["source_event_ids"] == ["11111111-1111-1111-1111-111111111111"]


def test_agenda_dedupe_key_links_reschedule_to_original_conversation():
    from app.worker import agenda_candidate_from_semantic

    original = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-05-28T09:00:00+00:00",
        {
            "intent": "social_plan",
            "summary": "Alex 说那就周日见。",
            "importance": 0.82,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
            "raw_data": {"chat_name": "Alex", "chat_id": "wa-alex", "sender": "Alex", "message": "那就周日吧"},
        },
    )
    reschedule = agenda_candidate_from_semantic(
        "22222222-2222-2222-2222-222222222222",
        "2026-05-28T10:00:00+00:00",
        {
            "intent": "social_plan",
            "summary": "Alex 把见面改到周六。",
            "importance": 0.86,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
            "raw_data": {"chat_name": "Alex", "chat_id": "wa-alex", "sender": "Alex", "message": "改到周六吧"},
        },
    )

    assert original is not None
    assert reschedule is not None
    assert reschedule["operation"] == "reschedule"
    assert reschedule["metadata"]["dedupe_key"] == original["metadata"]["dedupe_key"]


def test_persist_agenda_writes_item_and_version_with_reason():
    from app.worker import persist_agenda

    executed = []

    class Cursor:
        rowcount = 1

        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchone(self):
            return self.rows[0] if self.rows else None

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            normalized = " ".join(sql.split())
            if "SELECT id FROM agenda_items" in normalized:
                return Cursor()
            if "INSERT INTO agenda_items" in normalized:
                return Cursor([("22222222-2222-2222-2222-222222222222",)])
            return Cursor()

    persist_agenda(
        Conn(),
        "11111111-1111-1111-1111-111111111111",
        "2026-05-28T09:00:00+00:00",
        {
            "intent": "social_plan",
            "summary": "Alex 说那就周日见。",
            "importance": 0.82,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
            "raw_data": {"chat_name": "Alex", "sender": "Alex", "message": "那就周日吧"},
        },
    )

    agenda_sql, agenda_params = next(item for item in executed if "INSERT INTO agenda_items" in item[0])
    version_sql, version_params = next(item for item in executed if "INSERT INTO agenda_item_versions" in item[0])
    assert "certainty" in agenda_sql
    assert "missing_fields" in agenda_sql
    assert agenda_params[2] == "appointment"
    assert agenda_params[4] == "fuzzy"
    assert "exact_time" in agenda_params[7]
    assert "exact_place" in agenda_params[7]
    assert "Alex" in agenda_params[6]
    assert "INSERT INTO agenda_item_versions" in version_sql
    assert version_params[2] == "create"
    assert "Alex 说那就周日见" in version_params[5]


def test_suggestion_for_social_plan_includes_route_ride_and_snooze_actions():
    from app.worker import suggestion_for_event

    suggestion = suggestion_for_event(
        "11111111-1111-1111-1111-111111111111",
        {
            "intent": "social_plan",
            "summary": "Alex 约你周日去武康路见面。",
            "importance": 0.86,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
        },
    )

    assert suggestion is not None
    actions = suggestion["metadata"]["actions"]
    labels = [item["label"] for item in actions]
    assert labels == ["查路线", "帮我打车", "稍后提醒"]
    assert actions[1]["risk"] == "external_execution"
    assert actions[1]["requires_confirmation"] is True


def test_persist_semantics_does_not_write_stable_semantic_memory_directly():
    from app.worker import persist_semantics

    executed = []

    class Cursor:
        def __init__(self, rowcount):
            self.rowcount = rowcount

        def fetchone(self):
            return ["test", "event"]

    class Conn:
        def execute(self, sql, params=()):
            executed.append(sql)
            return Cursor(1)

    persist_semantics(
        Conn(),
        "11111111-1111-1111-1111-111111111111",
        "2026-05-26T00:00:00+00:00",
        {
            "intent": "schedule",
            "entities": {"source": "calendar"},
            "importance": 0.9,
            "summary": "今天 09:30 有产品评审会。",
            "model_version": "test",
        },
    )

    assert "INSERT INTO semantic_memory" not in "\n".join(executed)


def test_persist_vector_records_actual_embedding_provider(monkeypatch):
    from app import worker

    def fake_embedding(text):
        return [1.0] + [0.0] * 383, "test_provider"

    monkeypatch.setattr(worker, "text_embedding_with_provider", fake_embedding)
    monkeypatch.setattr(worker, "embedding_status", lambda: {"provider": "fastembed", "model": "test-model"})
    executed = []

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))

    worker.persist_vector(
        Conn(),
        "11111111-1111-1111-1111-111111111111",
        "test",
        "event",
        {
            "intent": "remember",
            "entities": {},
            "importance": 0.9,
            "summary": "Caroline researched adoption agencies.",
        },
    )

    metadata = executed[0][1][-1]

    assert '"embedding_provider": "test_provider"' in metadata
    assert '"embedding_model": "test-model"' in metadata


def test_memory_scope_for_whatsapp_records_conversation_and_blocks_private_negative_reply_use():
    from app.worker import memory_scope_for_event

    scope = memory_scope_for_event(
        "whatsapp",
        "whatsapp_message",
        {
            "chat_name": "Bob",
            "sender": "Bob",
            "message": "Alice is unreliable and I do not trust her.",
        },
        {
            "entities": {"source": "whatsapp", "subject": "Bob", "predicate": "negative_opinion_about", "object": "Alice"},
            "summary": "Bob 私下说 Alice 不可靠。",
        },
    )

    assert scope["conversation_label"] == "Bob"
    assert scope["speaker"] == "Bob"
    assert "alice" in scope["related_entities"]
    assert scope["sensitivity"] == "third_party_private_negative"
    assert "reply_to_contact" in scope["not_usable_contexts"]


def test_persist_vector_records_memory_scope_metadata(monkeypatch):
    from app import worker

    monkeypatch.setattr(worker, "text_embedding_with_provider", lambda text: ([1.0] + [0.0] * 383, "test_provider"))
    monkeypatch.setattr(worker, "embedding_status", lambda: {"provider": "fastembed", "model": "test-model"})
    executed = []

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))

    worker.persist_vector(
        Conn(),
        "11111111-1111-1111-1111-111111111111",
        "whatsapp",
        "whatsapp_message",
        {
            "intent": "conversation_memory",
            "entities": {"source": "whatsapp"},
            "importance": 0.8,
            "summary": "Alice 确认周五八点吃饭。",
            "raw_data": {"chat_name": "Alice", "sender": "Alice", "message": "Friday 8 works."},
        },
    )

    metadata = executed[0][1][-1]

    assert '"memory_scope"' in metadata
    assert '"conversation_label": "Alice"' in metadata


def test_locomo_seed_semantics_are_local_and_fact_dense(monkeypatch):
    from app.worker import extract_semantics

    def fail_model_call(messages):
        raise AssertionError("locomo seed should not call the remote model")

    monkeypatch.setattr("app.worker.call_model", fail_model_call)

    semantic = extract_semantics(
        "locomo_seed",
        "long_term_memory_qa",
        {
            "question": "What did Caroline research?",
            "answer": "Adoption agencies",
            "category": 1,
            "sample_index": 0,
            "evidence": ["D2:8"],
        },
    )

    assert semantic["intent"] == "long_term_memory_fact"
    assert "What did Caroline research?" in semantic["summary"]
    assert "Adoption agencies" in semantic["summary"]
    assert semantic["importance"] >= 0.75


def test_longmemeval_turn_semantics_are_local(monkeypatch):
    from app.worker import extract_semantics

    def fail_model_call(messages):
        raise AssertionError("long memory benchmark turns should not call the remote model")

    monkeypatch.setattr("app.worker.call_model", fail_model_call)

    semantic = extract_semantics(
        "longmemeval_conversation",
        "conversation_turn",
        {
            "role": "user",
            "content": "I graduated with a degree in Business Administration.",
            "question_id": "e47becba",
        },
    )

    assert semantic["intent"] == "conversation_memory"
    assert "Business Administration" in semantic["summary"]
    assert semantic["entities"]["person"] == "user"


def test_normalize_entity_name_collapses_case_and_whitespace():
    from app.worker import normalize_entity_name

    assert normalize_entity_name("  Caroline. ") == "caroline"
    assert normalize_entity_name("Adoption Agencies") == "adoption agencies"


def test_longmemeval_fact_uses_question_as_subject_and_answer_as_object():
    from app.worker import fact_from_semantic

    fact = fact_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        {
            "intent": "conversation_memory",
            "entities": {
                "source": "longmemeval_conversation",
                "question": "What degree did I graduate with?",
                "answer": "Business Administration",
                "person": "user",
            },
            "importance": 0.6,
            "summary": "user said: I graduated with a degree in Business Administration.",
        },
    )

    assert fact["subject"] == "what degree did i graduate with"
    assert fact["predicate"] == "benchmark_answer"
    assert fact["object"] == "business administration"


def test_locomo_seed_fact_uses_question_as_graph_subject():
    from app.worker import fact_from_semantic

    fact = fact_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        {
            "intent": "long_term_memory_fact",
            "entities": {
                "source": "locomo_seed",
                "question": "What is Caroline's identity?",
                "answer": "Transgender woman",
            },
            "importance": 0.78,
            "summary": "长期记忆测试事实：问题「What is Caroline's identity?」的答案是「Transgender woman」。",
        },
    )

    assert fact["subject"] == "what is caroline s identity"
    assert fact["predicate"] == "benchmark_answer"
    assert fact["object"] == "transgender woman"


def test_state_payload_keeps_multiple_entity_facts():
    from app.worker import state_payload_for_fact

    payload = state_payload_for_fact(
        {
            "subject": "caroline",
            "predicate": "conversation_memory",
            "object": "Caroline said: I mentor a transgender teen.",
            "confidence": 0.68,
        },
        {"summary": "Caroline said: I mentor a transgender teen."},
    )

    assert payload["subject"] == "caroline"
    assert payload["facts"][0]["predicate"] == "conversation_memory"
    assert "mentor a transgender teen" in payload["facts"][0]["summary"]


def test_state_key_groups_identity_preference_project_and_goal():
    from app.worker import state_key_for_fact

    assert state_key_for_fact({"subject": "user", "predicate": "identity", "object": "developer"}) == "profile:user:identity"
    assert state_key_for_fact({"subject": "user", "predicate": "preference", "object": "quiet hotels"}) == "profile:user:preference"
    assert state_key_for_fact({"subject": "par", "predicate": "active_project", "object": "personal assistant"}) == "project:par"
    assert state_key_for_fact({"subject": "user", "predicate": "long_term_goal", "object": "build private AI assistant"}) == "goal:user"


def test_state_payload_records_state_category_and_current_value():
    from app.worker import state_payload_for_fact

    payload = state_payload_for_fact(
        {
            "subject": "user",
            "predicate": "preference",
            "object": "quiet hotels",
            "confidence": 0.82,
        },
        {"summary": "用户偏好安静的酒店。"},
    )

    assert payload["subject"] == "user"
    assert payload["state_category"] == "preference"
    assert payload["current_value"] == "quiet hotels"
    assert payload["facts"][0]["summary"] == "用户偏好安静的酒店。"


def test_fact_from_semantic_prefers_structured_subject_predicate_object():
    from app.worker import fact_from_semantic

    fact = fact_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        {
            "intent": "preference",
            "entities": {
                "subject": "user",
                "predicate": "preference",
                "object": "quiet hotels",
            },
            "importance": 0.82,
            "summary": "用户偏好安静的酒店。",
        },
    )

    assert fact["subject"] == "user"
    assert fact["predicate"] == "preference"
    assert fact["object"] == "quiet hotels"


def test_memory_state_upsert_preserves_state_category_and_current_value():
    from app.worker import persist_fact_graph_and_state

    executed = []

    class Cursor:
        def fetchone(self):
            return ["99999999-9999-9999-9999-999999999999"]

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            return Cursor()

    persist_fact_graph_and_state(
        Conn(),
        "11111111-1111-1111-1111-111111111111",
        "2026-05-26T00:00:00+00:00",
        {
            "intent": "preference",
            "entities": {"subject": "user", "predicate": "preference", "object": "quiet hotels"},
            "importance": 0.82,
            "summary": "用户偏好安静的酒店。",
        },
    )

    memory_state_sql, memory_state_params = next(item for item in executed if "INSERT INTO memory_states" in item[0])
    assert "state_category" in memory_state_sql
    assert "current_value" in memory_state_sql
    assert memory_state_params[0] == "profile:user:preference"
    assert "quiet hotels" in memory_state_params[1]


def test_canonical_entity_name_uses_alias_map_and_keeps_original_alias():
    from app.worker import canonical_entity_name

    canonical, alias = canonical_entity_name(" Chen Ziyang ", {"Chen Ziyang": "陈子扬"})

    assert canonical == "陈子扬"
    assert alias == "chen ziyang"


def test_upsert_entity_writes_alias_when_canonical_differs():
    from app.worker import upsert_entity

    executed = []

    class Cursor:
        def fetchone(self):
            return ["99999999-9999-9999-9999-999999999999"]

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            return Cursor()

    upsert_entity(Conn(), "Chen Ziyang", "person", aliases={"Chen Ziyang": "陈子扬"})

    sql, params = executed[0]
    assert "aliases" in sql
    assert params[2] == "陈子扬"
    assert params[3] == ["chen ziyang"]


def test_relationship_upsert_records_confidence_metadata():
    from app.worker import persist_fact_graph_and_state

    executed = []

    class Cursor:
        def fetchone(self):
            return ["99999999-9999-9999-9999-999999999999"]

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            return Cursor()

    persist_fact_graph_and_state(
        Conn(),
        "11111111-1111-1111-1111-111111111111",
        "2026-05-26T00:00:00+00:00",
        {
            "intent": "collaborates_with",
            "entities": {"subject": "user", "predicate": "collaborates_with", "object": "陈子扬"},
            "importance": 0.76,
            "summary": "用户和陈子扬一起测试 WhatsApp 采集。",
        },
    )

    relationship_sql, relationship_params = next(item for item in executed if "INSERT INTO relationships" in item[0])
    assert "metadata" in relationship_sql
    assert "source_event_id" in relationship_params[-1]
    assert "用户和陈子扬一起测试" in relationship_params[-1]


def test_vector_content_uses_full_source_payload_for_email_and_chat():
    from app.worker import vector_content_for_event

    email_content = vector_content_for_event(
        "gmail",
        "gmail_thread_snapshot",
        {
            "summary": "项目资料邮件。",
            "entities": {},
            "raw_data": {
                "subject": "项目资料",
                "sender": "Alice",
                "body": "这里是完整正文，请查看附件。",
                "attachments": ["requirements.pdf"],
            },
        },
    )
    chat_content = vector_content_for_event(
        "whatsapp",
        "whatsapp_message",
        {
            "summary": "测试消息。",
            "entities": {},
            "raw_data": {"chat_name": "PAR Dev Group", "sender": "Alice", "message": "新的项目更新"},
        },
    )

    assert "项目资料" in email_content
    assert "完整正文" in email_content
    assert "requirements.pdf" in email_content
    assert "PAR Dev Group" in chat_content
    assert "新的项目更新" in chat_content


def test_compute_importance_uses_focus_actions_relationship_and_repeat_frequency():
    from app.worker import compute_importance

    high = compute_importance(
        source="focus",
        event_type="deep_focus",
        raw_data={"focus_score": 0.8, "signals": {"input": 2, "copy": 1}, "relationship_weight": 0.6, "repeat_frequency": 3},
        base=0.2,
    )
    low = compute_importance(
        source="focus",
        event_type="deep_focus",
        raw_data={"focus_score": 0.2, "signals": {"input": 0, "copy": 0}, "relationship_weight": 0, "repeat_frequency": 0},
        base=0.2,
    )

    assert high > low
    assert 0 <= low <= 1
    assert 0 <= high <= 1
    assert high >= 0.65


def test_rule_extract_semantics_uses_focus_score_for_deep_focus_importance():
    from app.worker import rule_extract_semantics

    semantic = rule_extract_semantics(
        "focus",
        "deep_focus",
        {
            "url": "https://example.com/research",
            "title": "Research",
            "duration": 180,
            "focus_score": 0.74,
            "signals": {"scroll": 3, "click": 2, "input": 1, "copy": 1},
        },
    )

    assert semantic["intent"] == "focused_attention"
    assert semantic["importance"] >= 0.6
    assert "Research" in semantic["summary"]


def test_suggestion_for_gmail_todo_has_type_confidence_expiry_and_dedupe():
    from app.worker import suggestion_for_event

    suggestion = suggestion_for_event(
        "11111111-1111-1111-1111-111111111111",
        {
            "intent": "payment_reminder",
            "entities": {"source": "gmail", "subject": "订单待付款", "timestamp_label": "今天"},
            "importance": 0.82,
            "summary": "新订单需要尽快完成付款。",
        },
    )

    assert suggestion["title"] == "处理邮件待办"
    assert "新订单需要尽快完成付款" in suggestion["body"]
    assert suggestion["priority"] >= 0.8
    assert suggestion["metadata"]["suggestion_type"] == "email_todo"
    assert suggestion["metadata"]["confidence"] >= 0.8
    assert suggestion["metadata"]["dedupe_key"] == "email_todo:gmail:payment_reminder:新订单需要尽快完成付款。"
    assert suggestion["metadata"]["expires_at"]


def test_suggestion_for_calendar_schedule_has_reminder_type():
    from app.worker import suggestion_for_event

    suggestion = suggestion_for_event(
        "22222222-2222-2222-2222-222222222222",
        {
            "intent": "schedule",
            "entities": {"source": "calendar", "title": "产品评审会", "date_context": "2026年5月26日"},
            "importance": 0.9,
            "summary": "今天 09:30 有产品评审会。",
        },
    )

    assert suggestion["title"] == "跟进日程安排"
    assert suggestion["metadata"]["suggestion_type"] == "calendar_reminder"
    assert suggestion["metadata"]["dedupe_key"].startswith("calendar_reminder:calendar:schedule:")


def test_persist_suggestion_publishes_realtime_event():
    from app.worker import persist_suggestion

    published = []
    executed = []

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))

    class Redis:
        def publish(self, channel, payload):
            published.append((channel, payload))

    persist_suggestion(
        Conn(),
        "11111111-1111-1111-1111-111111111111",
        {
            "intent": "payment_reminder",
            "entities": {"source": "gmail", "subject": "订单待付款"},
            "importance": 0.86,
            "summary": "新订单需要尽快完成付款。",
        },
        redis_client=Redis(),
    )

    assert "INSERT INTO proactive_suggestions" in executed[0][0]
    assert published[0][0] == "par:realtime"
    assert '"type": "proactive_message"' in published[0][1]
    assert "处理邮件待办" in published[0][1]


def test_suggestion_suppresses_low_value_generic_events():
    from app.worker import suggestion_for_event

    assert suggestion_for_event(
        "33333333-3333-3333-3333-333333333333",
        {
            "intent": "generic_event",
            "entities": {"source": "focus"},
            "importance": 0.4,
            "summary": "用户停留在普通页面。",
        },
    ) is None


def test_mask_value_redacts_codes_payment_orders_tokens_and_addresses_but_keeps_semantics():
    from app.worker import mask_value

    masked = mask_value(
        {
            "subject": "安全提醒：邮箱验证码 839201",
            "snippet": "订单号 498397 已通过支付宝付款 199.00 元，收货地址 上海市浦东新区世纪大道100号，token=abc123secret&code=zz991",
            "cookie": "sessionid=abcdef1234567890",
            "url": "https://example.com/reset?token=abc123secret&email=user@example.com&code=839201",
        }
    )

    rendered = str(masked)
    assert "839201" not in rendered
    assert "498397" not in rendered
    assert "199.00" not in rendered
    assert "世纪大道100号" not in rendered
    assert "abc123secret" not in rendered
    assert "abcdef1234567890" not in rendered
    assert "user@example.com" not in rendered
    assert "安全提醒" in rendered
    assert "支付宝付款" in rendered
    assert "订单号" in rendered
    assert "收货地址" in rendered


def test_mask_value_redacts_identity_financial_and_oauth_fragment_values():
    from app.worker import mask_value

    masked = mask_value(
        {
            "profile": "身份证 110105199001011234，护照 E12345678，银行卡 6222020202020202020",
            "oauth_url": "myapp://callback#access_token=tok_abc123&id_token=id_456&refresh_token=ref_789",
            "nested": {"authorization": "Bearer secret-token", "normal_note": "保留项目语义"},
        }
    )

    rendered = str(masked)
    assert "110105199001011234" not in rendered
    assert "E12345678" not in rendered
    assert "6222020202020202020" not in rendered
    assert "tok_abc123" not in rendered
    assert "id_456" not in rendered
    assert "ref_789" not in rendered
    assert "secret-token" not in rendered
    assert "身份证" in rendered
    assert "护照" in rendered
    assert "银行卡" in rendered
    assert "保留项目语义" in rendered


def test_mask_value_preserves_calendar_times_while_redacting_amounts():
    from app.worker import mask_value

    masked = mask_value(
        {
            "title": "今天 09:30 有产品评审会",
            "start_time": "09:30",
            "end_time": "10:00",
            "payment": "金额 199.00 元",
        }
    )

    rendered = str(masked)
    assert "09:30" in rendered
    assert "10:00" in rendered
    assert "199.00" not in rendered
    assert "AMOUNT_1" in rendered


def test_call_model_uses_model_router_when_configured(monkeypatch):
    monkeypatch.setenv("MODEL_ROUTER_URL", "http://model-router:8090")

    import app.worker as worker

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"content": "{\"summary\":\"来自 router\"}", "model": "qwen3.6", "route": "external_llm"}

    def fake_post(url, json, timeout):
        calls.append((url, json, timeout))
        return Response()

    monkeypatch.setattr(worker.httpx, "post", fake_post)

    content = worker.call_model([{"role": "user", "content": "提取语义"}])

    assert content == "{\"summary\":\"来自 router\"}"
    assert calls[0][0] == "http://model-router:8090/model/route"
    assert calls[0][1]["task"] == "semantic_extraction"
    assert calls[0][1]["messages"][0]["content"] == "提取语义"
