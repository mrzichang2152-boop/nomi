import json
import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")
os.environ.setdefault("AGENDA_MODEL_ENABLED", "0")


def test_persist_semantics_skips_memory_and_timeline_when_event_already_processed():
    from app.worker import persist_semantics

    executed = []

    class Cursor:
        def __init__(self, rowcount):
            self.rowcount = rowcount

        def fetchone(self):
            return None

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

        def fetchone(self):
            return None

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


def test_dialogue_batch_semantics_summarizes_complete_rounds_without_model_call(monkeypatch):
    from app.worker import extract_semantics, semantic_text, vector_content_for_event

    def fail_model_call(messages):
        raise AssertionError("dialogue batches should be summarized locally before memory persistence")

    monkeypatch.setattr("app.worker.call_model", fail_model_call)

    turns = []
    for idx in range(15):
        turns.append(
            {
                "role": "user",
                "content": f"第{idx + 1}轮：帮我关注 PHONE_1 报价和利润率",
                "created_at": f"2026-06-16T10:{idx:02d}:00+08:00",
            }
        )
        turns.append(
            {
                "role": "assistant",
                "content": "收到。我会结合报价截止和利润率继续提醒。",
                "created_at": f"2026-06-16T10:{idx:02d}:20+08:00",
            }
        )

    semantic = extract_semantics(
        "nomi_chat",
        "dialogue_batch",
        {
            "conversation_id": "conv-job-1",
            "round_count": 15,
            "turns": turns,
        },
    )

    assert semantic["intent"] == "dialogue_batch_summary"
    assert semantic["entities"]["turn_count"] == 30
    assert semantic["entities"]["round_count"] == 15
    assert semantic["entities"]["conversation_id"] == "conv-job-1"
    assert semantic["entities"]["primary_label"] in {"deadline", "todo", "important_fact"}
    assert "PHONE_1 报价和利润率" in semantic["summary"]
    assert "user: 第1轮" in semantic_text(semantic)
    assert "assistant: 收到" in vector_content_for_event("nomi_chat", "dialogue_batch", semantic)


def test_extract_semantics_merges_model_and_rule_event_labels(monkeypatch):
    from app import worker

    monkeypatch.setattr(
        worker,
        "call_model",
        lambda messages: """
        {
          "intent": "social_plan",
          "entities": {
            "source": "whatsapp",
            "labels": ["appointment", "travel"],
            "primary_label": "appointment",
            "actors": ["Alex"],
            "place_expressions": ["武康路"]
          },
          "importance": 0.88,
          "summary": "Alex 约用户周末去武康路见面。"
        }
        """,
    )

    semantic = worker.extract_semantics(
        "whatsapp",
        "whatsapp_message",
        {"chat_name": "Alex", "sender": "Alex", "message": "周末去武康路见吧"},
    )

    assert semantic["intent"] == "social_plan"
    assert semantic["entities"]["primary_label"] == "appointment"
    assert "appointment" in semantic["entities"]["labels"]
    assert "travel" in semantic["entities"]["labels"]
    assert semantic["entities"]["classification_trace"]["parser_mode"] == "hybrid_model_rules"
    assert "appointment" in semantic["entities"]["classification_trace"]["rule_labels"]


def test_whatsapp_memory_instruction_is_classified_as_important_fact(monkeypatch):
    from app import worker

    monkeypatch.setattr(worker, "call_model", lambda messages: (_ for _ in ()).throw(AssertionError("rules should handle explicit memory instructions")))

    semantic = worker.extract_semantics(
        "whatsapp",
        "whatsapp_message",
        {"chat_name": "大刚", "sender": "大刚", "message": "请记住：我的测试暗号是海盐拿铁。 测试码P1"},
    )

    labels = semantic["entities"]["labels"]
    assert semantic["intent"] in {"conversation_memory", "preference_update", "generic_event"}
    assert "important_fact" in labels
    assert semantic["entities"]["primary_label"] == "important_fact"
    assert "海盐拿铁" in semantic["summary"]


def test_whatsapp_family_relation_fact_is_structured_without_model(monkeypatch):
    from app import worker

    monkeypatch.setattr(worker, "call_model", lambda messages: (_ for _ in ()).throw(AssertionError("family facts should be rules-first")))

    semantic = worker.extract_semantics(
        "whatsapp",
        "whatsapp_message",
        {"chat_name": "大刚", "sender": "大刚", "message": "我儿子叫王刚"},
    )

    labels = semantic["entities"]["labels"]
    assert semantic["intent"] == "conversation_memory"
    assert "important_fact" in labels
    assert "relationship_signal" in labels
    assert semantic["entities"]["primary_label"] == "important_fact"
    assert semantic["entities"]["subject"] == "大刚"
    assert semantic["entities"]["predicate"] == "son_name"
    assert semantic["entities"]["object"] == "王刚"
    assert semantic["entities"]["family_relation"] == "son"
    assert semantic["entities"]["person"] == "大刚"
    assert "儿子" in semantic["summary"]
    assert "王刚" in semantic["summary"]
    assert "大刚" in semantic["summary"]

    fact = worker.fact_from_semantic("11111111-1111-1111-1111-111111111111", semantic)
    assert fact["subject"] == "大刚"
    assert fact["predicate"] == "son_name"
    assert fact["object"] == "王刚"
    assert fact["confidence"] >= 0.7


def test_whatsapp_third_person_family_relation_fact_is_structured_without_model(monkeypatch):
    from app import worker

    monkeypatch.setattr(worker, "call_model", lambda messages: (_ for _ in ()).throw(AssertionError("family facts should be rules-first")))

    semantic = worker.extract_semantics(
        "whatsapp",
        "whatsapp_message",
        {"chat_name": "大刚", "sender": "大刚", "message": "王超他儿子叫张红"},
    )

    labels = semantic["entities"]["labels"]
    assert semantic["intent"] == "conversation_memory"
    assert "important_fact" in labels
    assert "relationship_signal" in labels
    assert semantic["entities"]["primary_label"] == "important_fact"
    assert semantic["entities"]["subject"] == "王超"
    assert semantic["entities"]["predicate"] == "son_name"
    assert semantic["entities"]["object"] == "张红"
    assert semantic["entities"]["family_relation"] == "son"
    assert semantic["entities"]["person"] == "王超"
    assert semantic["entities"]["speaker"] == "大刚"
    assert semantic["entities"]["source_speaker"] == "大刚"
    assert semantic["entities"]["related_person"] == "张红"
    assert "王超" in semantic["summary"]
    assert "儿子" in semantic["summary"]
    assert "张红" in semantic["summary"]

    fact = worker.fact_from_semantic("11111111-1111-1111-1111-111111111111", semantic)
    assert fact["subject"] == "王超"
    assert fact["predicate"] == "son_name"
    assert fact["object"] == "张红"
    assert fact["confidence"] >= 0.7


def test_outgoing_whatsapp_family_relation_fact_still_belongs_to_user(monkeypatch):
    from app import worker

    monkeypatch.setattr(worker, "call_model", lambda messages: (_ for _ in ()).throw(AssertionError("family facts should be rules-first")))

    semantic = worker.extract_semantics(
        "whatsapp",
        "whatsapp_message",
        {"chat_name": "大刚", "sender": "我", "message_direction": "outgoing", "message": "我儿子叫王刚"},
    )

    assert semantic["entities"]["subject"] == "user"
    assert semantic["entities"]["person"] == "user"
    assert semantic["entities"]["predicate"] == "son_name"
    assert semantic["entities"]["object"] == "王刚"


def test_chinese_fact_intent_alias_normalizes_to_conversation_memory():
    from app.worker import intent_for_primary_label

    assert intent_for_primary_label("important_fact", "陈述事实") == "conversation_memory"
    assert intent_for_primary_label("important_fact", "事实陈述") == "conversation_memory"


def test_whatsapp_deadline_before_phrase_creates_deadline_agenda_without_model(monkeypatch):
    from app import worker

    monkeypatch.setattr(worker, "call_model", lambda messages: (_ for _ in ()).throw(AssertionError("deadline phrase should be rules-first")))

    semantic = worker.extract_semantics(
        "whatsapp",
        "whatsapp_message",
        {
            "chat_name": "大刚",
            "sender": "大刚",
            "message": "周五18点前把报价单发我，记得核对成本和利润率。 测试码T1",
        },
    )
    labels = semantic["entities"]["labels"]

    assert "deadline" in labels
    assert "todo" in labels
    assert semantic["entities"]["primary_label"] == "deadline"

    candidate = worker.agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-07-01T11:29:00+00:00",
        semantic,
    )

    assert candidate is not None
    assert candidate["type"] == "deadline"
    assert candidate["time_window"]["start"] == "2026-07-03T18:00:00+08:00"
    assert candidate["time_window"]["display"] == "2026-07-03 周五 18:00"


def test_agenda_time_parser_handles_dianban_as_half_past():
    from app.worker import extract_time_of_day, resolved_agenda_time_window

    assert extract_time_of_day("明天下午3点半在人民广场见") == (15, 30)

    time_window = resolved_agenda_time_window(
        "明天下午3点半在人民广场见，带合同。",
        "2026-07-01T11:29:00+00:00",
    )

    assert time_window["start"] == "2026-07-02T15:30:00+08:00"
    assert time_window["display"] == "2026-07-02 周四 15:30"


def test_agenda_time_parser_does_not_treat_iso_date_tail_before_colon_as_hour():
    from app.worker import extract_time_of_day, resolved_agenda_time_window

    text = (
        "NOMI_REAL_GMAIL_20260727_A CedarHarbor deadline 2026-08-14："
        "Real regression marker. Deadline 2026-08-14."
    )

    assert extract_time_of_day(text) is None

    time_window = resolved_agenda_time_window(
        text,
        "2026-07-27T14:01:15+00:00",
    )

    assert time_window["date"] == "2026-08-14"
    assert "start" not in time_window
    assert time_window["display"] == "2026-08-14 周五"


def test_whatsapp_snapshot_is_low_value_and_not_an_agenda_candidate():
    from app import worker

    semantic = worker.extract_semantics(
        "whatsapp",
        "whatsapp_snapshot",
        {
            "title": "(2) WhatsApp",
            "visible_text": "明天下午3点半在人民广场见，带合同。 测试码M1",
            "line_count": 23,
        },
    )

    assert worker.should_skip_agenda_candidate(semantic, semantic["raw_data"]) is True
    assert worker.agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-07-01T11:29:00+00:00",
        semantic,
    ) is None


def test_linkedin_job_detail_snapshot_never_becomes_agenda_candidate(monkeypatch):
    from app import worker

    monkeypatch.setattr(
        worker,
        "call_model",
        lambda messages: """
        {
          "is_agenda": true,
          "type": "appointment",
          "operation": "create",
          "title": "BJAK Backend Engineer 页面跟进",
          "status": "scheduled",
          "certainty": "fuzzy",
          "time_window": {"raw_text": "3 months ago"},
          "place": "",
          "participants": ["BJAK"],
          "missing_fields": ["exact_time", "exact_place"],
          "needs_clarification": true,
          "confidence": 0.74,
          "reason": "页面里有 3 months ago 和 Apply"
        }
        """,
    )

    semantic = worker.extract_semantics(
        "linkedin",
        "linkedin_job_description_snapshot",
        {
            "url": "https://www.linkedin.com/jobs/view/4388714215/",
            "title": "Backend Engineer, AI (Agent Systems) | BJAK | LinkedIn",
            "visible_text": (
                "0 notifications\nSkip to footer\nBJAK\n"
                "Backend Engineer, AI (Agent Systems)\n"
                "Beijing, Beijing, China\n3 months ago\nApply\nSubmit application"
            ),
            "job_pages": [
                {
                    "job_id": "linkedin_job_4388714215",
                    "source": "linkedin_browser_observation",
                    "title": "Backend Engineer, AI (Agent Systems)",
                    "company": "BJAK",
                    "location": "Beijing, Beijing, China",
                    "url": "https://www.linkedin.com/jobs/view/4388714215/",
                    "description": "Build agent systems. Apply now.",
                }
            ],
        },
    )

    assert worker.should_skip_agenda_candidate(semantic, semantic["raw_data"]) is True
    assert worker.hybrid_agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-07-04T17:27:55+00:00",
        semantic,
    ) is None


def test_linkedin_job_detail_snapshot_semantics_are_rules_only(monkeypatch):
    from app import worker

    model_called = False

    def model_call(messages):
        nonlocal model_called
        model_called = True
        return "{}"

    monkeypatch.setattr(worker, "call_model", model_call)

    semantic = worker.extract_semantics(
        "linkedin",
        "linkedin_job_description_snapshot",
        {
            "url": "https://www.linkedin.com/jobs/view/4388714215/",
            "title": "Backend Engineer, AI (Agent Systems) | BJAK | LinkedIn",
            "visible_text": "BJAK\nBackend Engineer, AI (Agent Systems)\n3 months ago\nApply",
            "job_pages": [
                {
                    "job_id": "linkedin_job_4388714215",
                    "source": "linkedin_browser_observation",
                    "title": "Backend Engineer, AI (Agent Systems)",
                    "company": "BJAK",
                    "url": "https://www.linkedin.com/jobs/view/4388714215/",
                }
            ],
        },
    )

    assert model_called is False
    assert semantic["intent"] == "generic_event"
    assert semantic["entities"]["primary_label"] == "low_value"
    assert semantic["entities"]["classification_trace"]["parser_mode"] == "rules_only_browser_observation"


def test_linkedin_job_search_results_stay_low_value_even_with_page_action_words(monkeypatch):
    from app import worker

    def model_call(messages):
        raise AssertionError("LinkedIn browser observations should not call the semantic model")

    monkeypatch.setattr(worker, "call_model", model_call)

    semantic = worker.extract_semantics(
        "linkedin",
        "linkedin_job_search_results",
        {
            "url": "https://www.linkedin.com/jobs/search/?keywords=AI%20Agent%20Backend%20Engineer&location=China",
            "title": "(18) AI Agent Backend Engineer Jobs in China | LinkedIn",
            "text": (
                "0 notifications total\nJobs\nTasks\nBefore you apply\n"
                "AI Agent Engineer (MJ000014)\nLianLian\nHangzhou\n"
                "Staff Software Engineer - AI agent, Productivity\nAirwallex\nShanghai"
            ),
            "job_results": [
                {
                    "title": "AI Agent Engineer (MJ000014)",
                    "company": "LianLian",
                    "location": "Hangzhou",
                    "url": "https://www.linkedin.com/jobs/view/4386306575/",
                },
                {
                    "title": "Staff Software Engineer - AI agent, Productivity",
                    "company": "Airwallex",
                    "location": "Shanghai",
                    "url": "https://www.linkedin.com/jobs/view/4428797241/",
                },
            ],
        },
    )

    assert semantic["intent"] == "generic_event"
    assert semantic["entities"]["primary_label"] == "low_value"
    assert semantic["entities"]["labels"] == ["low_value"]
    assert semantic["entities"]["classification_trace"]["parser_mode"] == "rules_only_browser_observation"
    assert worker.suggestion_for_event("11111111-1111-1111-1111-111111111111", semantic) is None


def test_extract_semantics_keeps_rule_payment_label_when_model_misses_it(monkeypatch):
    from app import worker

    monkeypatch.setenv("WORKER_RULES_FIRST_ENABLED", "0")
    monkeypatch.setattr(
        worker,
        "call_model",
        lambda messages: """
        {
          "intent": "generic_event",
          "entities": {"source": "gmail", "labels": ["ordinary_chat"], "primary_label": "ordinary_chat"},
          "importance": 0.4,
          "summary": "一封普通邮件。"
        }
        """,
    )

    semantic = worker.extract_semantics(
        "gmail",
        "gmail_thread_snapshot",
        {"subject": "Invoice due", "body": "云服务器账单需要在明天前付款"},
    )

    assert semantic["intent"] == "payment_reminder"
    assert semantic["entities"]["primary_label"] == "payment"
    assert "payment" in semantic["entities"]["labels"]
    assert "ordinary_chat" not in semantic["entities"]["labels"]
    assert "付款" in semantic["summary"]
    assert "rule_overrode_low_value_model_label" in semantic["entities"]["classification_trace"]["validation_warnings"]


def test_extract_semantics_keeps_rule_deadline_for_gmail_before_datetime_when_model_misses_it(monkeypatch):
    from app import worker

    monkeypatch.setenv("WORKER_RULES_FIRST_ENABLED", "0")
    monkeypatch.setattr(
        worker,
        "call_model",
        lambda messages: """
        {
          "intent": "generic_event",
          "entities": {"source": "gmail", "labels": ["low_value"], "primary_label": "low_value"},
          "importance": 0.4,
          "summary": "Example AI recruiter follow-up."
        }
        """,
    )

    semantic = worker.extract_semantics(
        "gmail",
        "gmail_message",
        {
            "subject": "Example AI AI PM follow-up",
            "body": "Please send your tailored resume and available interview slots before 2026-06-15 18:00.",
            "text": "Example AI recruiter asks for tailored resume and availability before 2026-06-15 18:00.",
        },
    )

    assert semantic["intent"] == "task_request"
    assert semantic["entities"]["primary_label"] == "deadline"
    assert "deadline" in semantic["entities"]["labels"]
    assert "low_value" not in semantic["entities"]["labels"]
    assert "rule_overrode_low_value_model_label" in semantic["entities"]["classification_trace"]["validation_warnings"]


def test_extract_semantics_suppresses_linkedin_gmail_notification_before_agenda_rules(monkeypatch):
    from app import worker

    monkeypatch.setattr(worker, "call_model", lambda messages: (_ for _ in ()).throw(AssertionError("low-value platform notifications should not call model")))

    semantic = worker.extract_semantics(
        "gmail",
        "gmail_message_snapshot",
        {
            "sender": "LinkedIn",
            "subject": "You have 2 new messages",
            "body": (
                "You have 2 new messages\n"
                "View messages:https://www.linkedin.com/comm/messaging/?midToken=REDACTED#1357 to:\n"
                "See the latest updates to our AI Security & Governance platform in action with live demos.\n"
                "Chat with our experts about tackling your biggest AI security challenges."
            ),
        },
    )

    assert semantic["intent"] == "generic_event"
    assert semantic["entities"]["primary_label"] == "low_value"
    assert semantic["entities"]["labels"] == ["low_value"]
    assert semantic["entities"]["classification_trace"]["parser_mode"] == "rules_only_low_value_private_signal"
    assert worker.suggestion_for_event("11111111-1111-1111-1111-111111111113", semantic) is None
    assert worker.agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111113",
        "2026-06-26T19:17:37+08:00",
        semantic,
    ) is None


def test_extract_semantics_detects_brief_chinese_meeting_text(monkeypatch):
    from app import worker

    monkeypatch.setattr(
        worker,
        "call_model",
        lambda messages: """
        {
          "intent": "generic_event",
          "entities": {"source": "whatsapp", "labels": ["ordinary_chat"], "primary_label": "ordinary_chat"},
          "importance": 0.2,
          "summary": "普通聊天。"
        }
        """,
    )

    semantic = worker.extract_semantics(
        "whatsapp",
        "whatsapp_message",
        {
            "sender": "RG_Alice",
            "counterparty_id": "rg_alice",
            "text": "2026年6月13日周六下午3点在武康路见，记得带 PHONE_1 报价单。",
        },
    )

    assert semantic["intent"] == "social_plan"
    assert semantic["entities"]["primary_label"] == "appointment"
    assert "appointment" in semantic["entities"]["labels"]
    assert "ordinary_chat" not in semantic["entities"]["labels"]


def test_extract_semantics_preserves_source_and_normalizes_chinese_appointment_intent(monkeypatch):
    from app import worker

    monkeypatch.setenv("WORKER_RULES_FIRST_ENABLED", "0")
    monkeypatch.setattr(
        worker,
        "call_model",
        lambda messages: """
        {
          "intent": "约定",
          "entities": {
            "time": "明天下午3点",
            "location": "武康路咖啡店",
            "item": "报价单"
          },
          "importance": 0.84,
          "summary": "明天下午3点在武康路咖啡店见，带报价单。"
        }
        """,
    )

    semantic = worker.extract_semantics(
        "whatsapp",
        "whatsapp_message",
        {
            "chat_name": "陈子扬",
            "sender": "陈子扬",
            "message": "明天下午3点在武康路咖啡店见，麻烦带报价单。",
        },
    )

    assert semantic["intent"] == "social_plan"
    assert semantic["entities"]["source"] == "whatsapp"
    assert semantic["entities"]["event_type"] == "whatsapp_message"
    assert semantic["entities"]["primary_label"] == "appointment"
    assert semantic["entities"]["time"] == "明天下午3点"


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


def test_whatsapp_fuzzy_place_chat_is_classified_and_persisted_as_fuzzy_appointment(monkeypatch):
    from app import worker

    monkeypatch.setattr(
        worker,
        "call_model",
        lambda messages: (_ for _ in ()).throw(RuntimeError("simulate semantic model timeout")),
    )

    semantic = worker.extract_semantics(
        "whatsapp",
        "whatsapp_message",
        {
            "chat_name": "大刚",
            "sender": "大刚",
            "message": "明天下午在保利广场详细聊一下呗",
            "received_at": "2026-07-02T14:48:23+08:00",
        },
    )

    assert semantic["intent"] == "social_plan"
    assert semantic["entities"]["primary_label"] == "appointment"
    assert "appointment" in semantic["entities"]["labels"]
    assert semantic["entities"]["classification_trace"]["parser_mode"] == "rules_first"
    assert semantic["importance"] >= 0.72

    candidate = worker.agenda_candidate_from_semantic(
        "78038b27-a7bf-568a-bf0f-f1fa2218f46c",
        "2026-07-02T06:48:23+00:00",
        semantic,
    )

    assert candidate is not None
    assert candidate["type"] == "appointment"
    assert candidate["certainty"] == "fuzzy"
    assert candidate["place"] == "保利广场"
    assert candidate["time_window"]["date"] == "2026-07-03"
    assert candidate["time_window"]["display"] == "2026-07-03 周五"
    assert candidate["time_window"]["has_exact_time"] is False
    assert candidate["time_window"]["has_fuzzy_time"] is True
    assert "exact_time" in candidate["missing_fields"]
    assert "exact_place" not in candidate["missing_fields"]


def test_agenda_candidate_ignores_casual_chat_with_relative_time():
    from app.worker import agenda_candidate_from_semantic

    candidate = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-06-16T09:00:00+08:00",
        {
            "intent": "普通聊天",
            "summary": "Alice 问明天是不是会下雨，提醒用户带伞。",
            "importance": 0.32,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message", "labels": ["普通聊天"]},
            "raw_data": {
                "chat_name": "Alice",
                "sender": "Alice",
                "message": "明天是不是会下雨啊，你出门记得带伞",
            },
        },
    )

    assert candidate is None


def test_agenda_candidate_ignores_nomi_chat_planning_request_without_schedule_command():
    from app.worker import agenda_candidate_from_semantic

    candidate = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-06-16T09:00:00+08:00",
        {
            "intent": "user_instruction",
            "summary": "用户想制定明天准备产品经理面试的三步计划。",
            "importance": 0.52,
            "entities": {"source": "nomi_chat", "event_type": "chat_message", "labels": ["用户指令"]},
            "raw_data": {
                "source": "nomi_chat",
                "role": "user",
                "message": "帮我制定一个明天准备产品经理面试的三步计划。",
            },
        },
    )

    assert candidate is None


def test_agenda_candidate_keeps_nomi_chat_explicit_reminder_request():
    from app.worker import agenda_candidate_from_semantic

    candidate = agenda_candidate_from_semantic(
        "22222222-2222-2222-2222-222222222222",
        "2026-06-16T09:00:00+08:00",
        {
            "intent": "user_instruction",
            "summary": "用户要求提醒自己明天准备产品经理面试。",
            "importance": 0.72,
            "entities": {"source": "nomi_chat", "event_type": "chat_message", "labels": ["用户指令", "待办"]},
            "raw_data": {
                "source": "nomi_chat",
                "role": "user",
                "message": "提醒我明天准备产品经理面试。",
            },
        },
    )

    assert candidate is not None
    assert candidate["type"] == "todo"
    assert "exact_time" in candidate["missing_fields"]


def test_agenda_candidate_for_cancel_keeps_cancel_operation_without_route_need():
    from app.worker import agenda_candidate_from_semantic, suggestion_for_event

    semantic = {
        "intent": "cancel",
        "summary": "Alex 说周日武康路见面的安排取消了，不用过去。",
        "importance": 0.86,
        "entities": {"source": "whatsapp", "event_type": "whatsapp_message", "labels": ["cancel", "appointment"]},
        "raw_data": {
            "chat_name": "Alex",
            "sender": "Alex",
            "message": "周日武康路见面的安排取消了，不用过去",
        },
    }

    candidate = agenda_candidate_from_semantic(
        "22222222-2222-2222-2222-222222222222",
        "2026-06-16T09:00:00+08:00",
        semantic,
    )
    suggestion = suggestion_for_event("22222222-2222-2222-2222-222222222222", semantic)

    assert candidate is not None
    assert candidate["operation"] == "cancel"
    assert candidate["status"] == "canceled"
    assert candidate["missing_fields"] == []
    action_ids = [item["id"] for item in suggestion["metadata"]["actions"]]
    assert "route_lookup" not in action_ids
    assert "ride_prepare" not in action_ids


def test_whatsapp_not_meeting_anymore_creates_cancel_agenda_without_model(monkeypatch):
    from app import worker

    monkeypatch.setattr(worker, "call_model", lambda messages: (_ for _ in ()).throw(AssertionError("cancel phrase should be rules-first")))

    semantic = worker.extract_semantics(
        "whatsapp",
        "whatsapp_message",
        {
            "chat_name": "大刚",
            "sender": "大刚",
            "message": "我们明天不见面了，改电话聊",
        },
    )

    assert "cancel" in semantic["entities"]["labels"]
    candidate = worker.agenda_candidate_from_semantic(
        "33333333-3333-3333-3333-333333333333",
        "2026-07-02T08:32:51+00:00",
        semantic,
    )

    assert candidate is not None
    assert candidate["operation"] == "cancel"
    assert candidate["status"] == "canceled"
    assert candidate["type"] == "appointment"


def test_not_a_meeting_policy_reminder_is_todo_not_appointment(monkeypatch):
    from app import worker

    monkeypatch.setattr(worker, "call_model", lambda messages: (_ for _ in ()).throw(AssertionError("reminder phrase should be rules-first")))

    semantic = worker.extract_semantics(
        "whatsapp",
        "whatsapp_message",
        {
            "chat_name": "大刚",
            "sender": "大刚",
            "message": "明天3点半别忘了，不是开会，是提醒你看一下保单",
        },
    )
    candidate = worker.agenda_candidate_from_semantic(
        "44444444-4444-4444-4444-444444444444",
        "2026-07-02T08:32:24+00:00",
        semantic,
    )

    assert candidate is not None
    assert candidate["type"] == "todo"
    assert candidate["status"] == "scheduled"
    assert "exact_place" not in candidate["missing_fields"]
    assert "保单" in candidate["title"]


def test_agenda_candidate_accepts_chinese_appointment_label_from_model():
    from app.worker import agenda_candidate_from_semantic

    candidate = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-05-28T09:00:00+00:00",
        {
            "intent": "约定",
            "summary": "Bob 说周末我们见一下吧，具体时间地点晚点发。",
            "importance": 0.84,
            "entities": {
                "source": "whatsapp",
                "event_type": "whatsapp_message",
                "labels": ["appointment"],
                "primary_label": "appointment",
            },
            "raw_data": {
                "chat_name": "Bob",
                "chat_id": "wa-bob",
                "sender": "Bob",
                "message": "周末我们见一下吧，具体时间地点我晚点发你",
            },
        },
    )

    assert candidate is not None
    assert candidate["type"] == "appointment"
    assert candidate["certainty"] == "fuzzy"
    assert candidate["needs_clarification"] is True
    assert set(candidate["missing_fields"]) == {"exact_time", "exact_place"}
    assert candidate["participants"] == ["Bob"]


def test_agenda_candidate_for_exact_meeting_has_no_missing_fields():
    from app.worker import agenda_candidate_from_semantic

    candidate = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-05-28T09:00:00+00:00",
        {
            "intent": "social_plan",
            "summary": "Alex 约我今晚 7点在武康路见面。",
            "importance": 0.9,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
            "raw_data": {"chat_name": "Alex", "sender": "Alex", "message": "今晚 7点在武康路见面吧"},
        },
    )

    assert candidate is not None
    assert candidate["type"] == "appointment"
    assert candidate["certainty"] == "exact"
    assert candidate["place"] == "武康路"
    assert candidate["missing_fields"] == []
    assert candidate["needs_clarification"] is False
    assert candidate["time_window"]["has_exact_time"] is True
    assert candidate["time_window"]["start"] == "2026-05-28T19:00:00+08:00"


def test_agenda_candidate_resolves_explicit_date_time_and_square_place():
    from app.worker import agenda_candidate_from_semantic

    candidate = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-06-09T05:00:00+00:00",
        {
            "intent": "social_plan",
            "summary": "赵测试约我 2026-06-10 15:00 在人民广场见。",
            "importance": 0.86,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
            "raw_data": {"chat_name": "赵测试", "sender": "赵测试", "message": "2026-06-10 15:00 在人民广场见，带合同。"},
        },
    )

    assert candidate is not None
    assert candidate["certainty"] == "exact"
    assert candidate["place"] == "人民广场"
    assert candidate["missing_fields"] == []
    assert candidate["time_window"]["start"] == "2026-06-10T15:00:00+08:00"
    assert candidate["time_window"]["display"] == "2026-06-10 周三 15:00"


def test_agenda_candidate_resolves_tomorrow_afternoon_to_concrete_local_date():
    from app.worker import agenda_candidate_from_semantic

    candidate = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-06-02T05:00:00+00:00",
        {
            "intent": "social_plan",
            "summary": "赵测试约我明天下午4点在人民广场见面。",
            "importance": 0.8,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
            "raw_data": {"chat_name": "赵测试", "sender": "赵测试", "message": "明天下午4点在人民广场见，带合同。"},
        },
    )

    assert candidate is not None
    assert candidate["time_window"]["date"] == "2026-06-03"
    assert candidate["time_window"]["weekday"] == "周三"
    assert candidate["time_window"]["start"] == "2026-06-03T16:00:00+08:00"
    assert candidate["time_window"]["display"] == "2026-06-03 周三 16:00"
    assert "exact_time" not in candidate["missing_fields"]


def test_agenda_candidate_resolves_weekday_morning_to_concrete_local_date():
    from app.worker import agenda_candidate_from_semantic

    candidate = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-06-02T05:00:00+00:00",
        {
            "intent": "social_plan",
            "summary": "Maya 约我周五上午10点在静安寺地铁站见面。",
            "importance": 0.8,
            "entities": {"source": "telegram", "event_type": "telegram_message"},
            "raw_data": {"chat_name": "Maya", "sender": "Maya", "message": "周五上午10点静安寺地铁站见。"},
        },
    )

    assert candidate is not None
    assert candidate["time_window"]["date"] == "2026-06-05"
    assert candidate["time_window"]["weekday"] == "周五"
    assert candidate["time_window"]["start"] == "2026-06-05T10:00:00+08:00"
    assert candidate["time_window"]["display"] == "2026-06-05 周五 10:00"
    assert candidate["place"] == "静安寺地铁站"


def test_agenda_candidate_resolves_english_next_weekday_time_to_concrete_local_date():
    from app.worker import agenda_candidate_from_semantic

    candidate = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-06-15T10:47:44+00:00",
        {
            "intent": "social_plan",
            "summary": "Product Manager interview next Tuesday: can you join next Tuesday at 10:00 AM?",
            "importance": 0.8,
            "entities": {"source": "gmail", "event_type": "gmail_message_snapshot"},
            "raw_data": {
                "subject": "Product Manager interview next Tuesday",
                "sender": "Alpha HR",
                "body": "Can you join a product manager interview next Tuesday at 10:00 AM?",
            },
        },
    )

    assert candidate is not None
    assert candidate["time_window"]["date"] == "2026-06-23"
    assert candidate["time_window"]["weekday"] == "周二"
    assert candidate["time_window"]["start"] == "2026-06-23T10:00:00+08:00"
    assert candidate["time_window"]["display"] == "2026-06-23 周二 10:00"
    assert "exact_time" not in candidate["missing_fields"]


def test_agenda_candidate_extracts_place_before_meet_without_at_marker():
    from app.worker import agenda_candidate_from_semantic

    candidate = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-06-09T05:00:00+00:00",
        {
            "intent": "social_plan",
            "summary": "Alex 约我周六下午3点武康路见。",
            "importance": 0.82,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
            "raw_data": {"chat_name": "Alex", "sender": "Alex", "message": "周六下午3点武康路见。"},
        },
    )

    assert candidate is not None
    assert candidate["place"] == "武康路"
    assert "exact_place" not in candidate["missing_fields"]


def test_agenda_candidate_handles_interview_reschedule_and_pending_zoom_link():
    from app.worker import agenda_candidate_from_semantic

    candidate = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-06-09T05:00:00+00:00",
        {
            "intent": "generic_event",
            "summary": "Maya 说面试 panel 改到明天10:30，Zoom 链接稍后发。",
            "importance": 0.86,
            "entities": {"source": "telegram", "event_type": "telegram_message"},
            "raw_data": {"chat_name": "Maya", "sender": "Maya", "message": "面试 panel 改到明天10:30，Zoom 链接我稍后发。"},
        },
    )

    assert candidate is not None
    assert candidate["type"] == "appointment"
    assert candidate["operation"] == "reschedule"
    assert candidate["time_window"]["start"] == "2026-06-10T10:30:00+08:00"
    assert candidate["metadata"]["pending_artifacts"] == ["zoom_link"]
    assert "exact_link" in candidate["missing_fields"]
    assert "exact_place" not in candidate["missing_fields"]
    assert candidate["needs_clarification"] is True


def test_rule_summary_agenda_title_and_suggestion_body_use_readable_message_text():
    from app.worker import agenda_candidate_from_semantic, rule_extract_semantics, suggestion_for_event

    raw_data = {
        "run_id": "rg-readable",
        "channel": "whatsapp",
        "chat_id": "wa-readable",
        "contact": "Bob",
        "direction": "inbound",
        "text": "2026-06-13 15:00在武康路咖啡店见，我带合同。",
        "received_at": "2026-06-12T10:31:00+08:00",
    }

    semantic = rule_extract_semantics("whatsapp", "whatsapp_message", raw_data)
    semantic["intent"] = "social_plan"
    semantic["importance"] = 0.72
    semantic["entities"]["labels"] = ["appointment"]
    semantic["entities"]["primary_label"] = "appointment"
    semantic["raw_data"] = raw_data

    candidate = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-06-12T02:31:00+00:00",
        semantic,
    )
    suggestion = suggestion_for_event("11111111-1111-1111-1111-111111111111", semantic)

    assert semantic["summary"] == "2026-06-13 15:00在武康路咖啡店见，我带合同。"
    assert candidate is not None
    assert candidate["title"] == "2026-06-13 15:00在武康路咖啡店见，我带合同。"
    assert candidate["time_window"]["raw_text"] == "2026-06-13 15:00在武康路咖啡店见，我带合同。"
    assert suggestion is not None
    assert suggestion["body"] == "这条信息可能需要跟进：2026-06-13 15:00在武康路咖啡店见，我带合同。"
    assert "run_id" not in suggestion["body"]


def test_agenda_time_ignores_identifier_digits_before_colon_and_uses_explicit_time():
    from app.worker import agenda_candidate_from_semantic

    candidate = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-06-12T02:40:00+00:00",
        {
            "intent": "task_request",
            "summary": "Nomi regression job deadline fix5：Please submit before 2026-06-15 18:00.",
            "importance": 0.55,
            "entities": {"source": "gmail", "event_type": "gmail_message", "labels": ["deadline"], "primary_label": "deadline"},
            "raw_data": {
                "thread_id": "gmail-job-003",
                "subject": "Nomi regression job deadline fix5",
                "body": "Please submit before 2026-06-15 18:00.",
            },
        },
    )

    assert candidate is not None
    assert candidate["time_window"]["start"] == "2026-06-15T18:00:00+08:00"


def test_agenda_place_extracts_location_still_phrase():
    from app.worker import agenda_candidate_from_semantic

    candidate = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-06-12T02:42:00+00:00",
        {
            "intent": "schedule",
            "summary": "刚才那个见面改到2026-06-14 10:00，地点还是武康路咖啡店。",
            "importance": 0.62,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message", "labels": ["reschedule", "appointment"], "primary_label": "reschedule"},
            "raw_data": {"chat_id": "wa-friend-cara", "contact": "Cara", "text": "刚才那个见面改到2026-06-14 10:00，地点还是武康路咖啡店。"},
        },
    )

    assert candidate is not None
    assert candidate["place"] == "武康路咖啡店"
    assert candidate["certainty"] == "exact"
    assert candidate["missing_fields"] == []


def test_low_confidence_fuzzy_social_plan_only_asks_for_clarification_actions():
    from app.worker import suggestion_for_event

    suggestion = suggestion_for_event(
        "11111111-1111-1111-1111-111111111111",
        {
            "intent": "social_plan",
            "summary": "Alex 说可能周末聊下。",
            "importance": 0.5,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message", "labels": ["appointment"], "primary_label": "appointment"},
            "raw_data": {"chat_name": "Alex", "sender": "Alex", "message": "可能周末聊下。"},
        },
    )

    assert suggestion is not None
    actions = suggestion["metadata"]["actions"]
    labels = [item["label"] for item in actions]
    assert "补充时间地点" in labels
    assert "稍后提醒" in labels
    assert "查路线" not in labels
    assert "帮我打车" not in labels


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


def test_agenda_dedupe_key_separates_distinct_appointments_in_same_chat():
    from app.worker import agenda_candidate_from_semantic

    telegram_meeting = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-06-30T09:39:33+00:00",
        {
            "intent": "social_plan",
            "summary": "NOMI_REG_TG_0629 周五10点静安寺地铁站见 Maya",
            "importance": 0.82,
            "entities": {"source": "telegram", "event_type": "telegram_message_preview"},
            "raw_data": {
                "chat_name": "Ask",
                "message": "NOMI_REG_TG_0629 周五10点静安寺地铁站见 Maya",
                "capture_scope": "telegram_open_chat_message",
            },
        },
    )
    whatsapp_meeting_seen_in_same_chat = agenda_candidate_from_semantic(
        "22222222-2222-2222-2222-222222222222",
        "2026-06-30T09:39:34+00:00",
        {
            "intent": "social_plan",
            "summary": "NOMI_REG_WA_0629 明天15:30人民广场见，带合同",
            "importance": 0.82,
            "entities": {"source": "telegram", "event_type": "telegram_message_preview"},
            "raw_data": {
                "chat_name": "Ask",
                "message": "NOMI_REG_WA_0629 明天15:30人民广场见，带合同",
                "capture_scope": "telegram_open_chat_message",
            },
        },
    )

    assert telegram_meeting is not None
    assert whatsapp_meeting_seen_in_same_chat is not None
    assert telegram_meeting["metadata"]["dedupe_key"] != whatsapp_meeting_seen_in_same_chat["metadata"]["dedupe_key"]
    assert telegram_meeting["place"] == "静安寺地铁站"
    assert whatsapp_meeting_seen_in_same_chat["place"] == "人民广场"


def test_agenda_dedupe_key_ignores_unstable_whatsapp_participant_for_same_message():
    from app.worker import agenda_candidate_from_semantic

    timestamp = "2026-07-01T11:29:00+00:00"
    message = "明天下午3点半在人民广场见，带合同。 测试码M1"
    history_candidate = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        timestamp,
        {
            "intent": "social_plan",
            "summary": message,
            "importance": 0.92,
            "entities": {"source": "whatsapp", "event_type": "history_scroll_sync"},
            "raw_data": {
                "chat_name": "大刚",
                "sender": "大刚",
                "message": message,
                "capture_scope": "whatsapp_open_chat_message",
            },
        },
    )
    observer_candidate = agenda_candidate_from_semantic(
        "22222222-2222-2222-2222-222222222222",
        timestamp,
        {
            "intent": "social_plan",
            "summary": message,
            "importance": 0.9,
            "entities": {"source": "whatsapp", "event_type": "mutation_observer"},
            "raw_data": {
                "chat_name": "你好呀",
                "sender": "你好呀",
                "message": message,
                "capture_scope": "whatsapp_open_chat_message",
            },
        },
    )

    assert history_candidate is not None
    assert observer_candidate is not None
    assert history_candidate["time_window"]["display"] == "2026-07-02 周四 15:30"
    assert observer_candidate["time_window"]["display"] == "2026-07-02 周四 15:30"
    assert history_candidate["place"] == "人民广场"
    assert observer_candidate["place"] == "人民广场"
    assert history_candidate["metadata"]["dedupe_key"] == observer_candidate["metadata"]["dedupe_key"]


def test_hybrid_agenda_uses_valid_model_candidate_with_rule_safety(monkeypatch):
    from app import worker

    monkeypatch.setenv("AGENDA_MODEL_ENABLED", "1")

    def fake_model(messages):
        return """
        {
          "is_agenda": true,
          "type": "appointment",
          "operation": "create",
          "title": "周日和 Alex 去武康路见面",
          "certainty": "fuzzy",
          "time_window": {"raw_text": "周日"},
          "place": "武康路",
          "participants": ["Alex"],
          "missing_fields": ["exact_time"],
          "needs_clarification": true,
          "confidence": 0.91,
          "reason": "对话明确提到周日见面和武康路，但没有精确时间。"
        }
        """

    monkeypatch.setattr(worker, "call_model", fake_model)
    candidate = worker.hybrid_agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-05-28T09:00:00+00:00",
        {
            "intent": "social_plan",
            "summary": "Alex 说周日去武康路见。",
            "importance": 0.82,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
            "raw_data": {"chat_name": "Alex", "chat_id": "wa-alex", "sender": "Alex", "message": "周日去武康路见吧"},
        },
    )

    assert candidate is not None
    assert candidate["title"] == "周日和 Alex 去武康路见面"
    assert candidate["place"] == "武康路"
    assert candidate["participants"] == ["Alex"]
    assert candidate["certainty"] == "fuzzy"
    assert candidate["missing_fields"] == ["exact_time"]
    assert candidate["needs_clarification"] is True
    assert candidate["metadata"]["parser_mode"] == "hybrid_model_rules"
    assert candidate["metadata"]["model_candidate"]["confidence"] == 0.91
    assert candidate["metadata"]["rule_candidate"]["type"] == "appointment"


def test_hybrid_agenda_uses_rules_fast_path_for_complete_exact_candidate(monkeypatch):
    from app import worker

    monkeypatch.setenv("AGENDA_MODEL_ENABLED", "1")

    def fail_model(messages):
        raise AssertionError("model should not be called for complete exact rule candidate")

    monkeypatch.setattr(worker, "call_model", fail_model)
    candidate = worker.hybrid_agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-06-20T13:06:15+00:00",
        {
            "intent": "social_plan",
            "summary": "明天下午4点人民广场见",
            "importance": 0.8,
            "entities": {"source": "gmail", "event_type": "gmail_message_snapshot"},
            "raw_data": {
                "subject": "明天下午4点人民广场见",
                "body": "请明天下午4点在人民广场见面，带合同。",
                "from": '"张子长" <sender@example.com>',
            },
        },
    )

    assert candidate is not None
    assert candidate["title"] == "明天下午4点人民广场见"
    assert candidate["place"] == "人民广场"
    assert candidate["certainty"] == "exact"
    assert candidate["missing_fields"] == []
    assert candidate["needs_clarification"] is False
    assert candidate["time_window"]["start"] == "2026-06-21T16:00:00+08:00"
    assert candidate["metadata"]["parser_mode"] == "rules_first_exact"
    assert candidate["metadata"]["validation_warnings"] == []
    assert candidate["metadata"]["rule_candidate"]["type"] == "appointment"


def test_hybrid_agenda_rejects_model_invented_exact_time(monkeypatch):
    from app import worker

    monkeypatch.setenv("AGENDA_MODEL_ENABLED", "1")

    def fake_model(messages):
        return """
        {
          "is_agenda": true,
          "type": "appointment",
          "operation": "create",
          "title": "周末和 Alex 晚上八点见面",
          "certainty": "exact",
          "time_window": {"raw_text": "周六晚上八点", "start": "2026-05-30T20:00:00+08:00"},
          "place": "武康路",
          "participants": ["Alex"],
          "missing_fields": [],
          "needs_clarification": false,
          "confidence": 0.94,
          "reason": "模型猜测了晚上八点。"
        }
        """

    monkeypatch.setattr(worker, "call_model", fake_model)
    candidate = worker.hybrid_agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-05-28T09:00:00+00:00",
        {
            "intent": "social_plan",
            "summary": "Alex 说周末去武康路见。",
            "importance": 0.82,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
            "raw_data": {"chat_name": "Alex", "sender": "Alex", "message": "周末去武康路见吧"},
        },
    )

    assert candidate is not None
    assert candidate["certainty"] == "fuzzy"
    assert candidate["title"] == "Alex 说周末去武康路见。"
    assert candidate["time_window"]["raw_text"] == "Alex 说周末去武康路见。\n周末去武康路见吧"
    assert "exact_time" in candidate["missing_fields"]
    assert candidate["confidence"] == 0.82
    assert candidate["needs_clarification"] is True
    assert candidate["metadata"]["parser_mode"] == "hybrid_model_rules"
    assert "unsupported_exact_time" in candidate["metadata"]["validation_warnings"]
    assert "unsupported_title_detail" in candidate["metadata"]["validation_warnings"]


def test_hybrid_agenda_falls_back_to_rules_when_model_is_invalid(monkeypatch):
    from app import worker

    monkeypatch.setenv("AGENDA_MODEL_ENABLED", "1")
    monkeypatch.setattr(worker, "call_model", lambda messages: "not json")
    candidate = worker.hybrid_agenda_candidate_from_semantic(
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
    assert candidate["title"] == "Alex 说那就周日见。"
    assert candidate["metadata"]["parser_mode"] == "rules_fallback"
    assert candidate["metadata"]["validation_warnings"]


def test_agenda_candidate_skips_nomi_assistant_response_with_task_words():
    from app.worker import agenda_candidate_from_semantic

    candidate = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-06-04T09:00:00+00:00",
        {
            "intent": "assistant_response",
            "summary": "assistant said to Nomi: 已收到。请问需要执行哪项检查或处理什么任务？",
            "importance": 0.34,
            "entities": {"source": "nomi_chat", "role": "assistant", "event_type": "assistant_message"},
            "raw_data": {
                "role": "assistant",
                "content": "已收到。请问需要执行哪项检查或处理什么任务？",
                "conversation_id": "conv-1",
            },
        },
    )

    assert candidate is None


def test_hybrid_agenda_does_not_fallback_when_model_says_not_agenda(monkeypatch):
    from app import worker

    monkeypatch.setenv("AGENDA_MODEL_ENABLED", "1")
    monkeypatch.setattr(
        worker,
        "call_model",
        lambda messages: """
        {
          "is_agenda": false,
          "type": null,
          "operation": "lower_confidence",
          "title": "",
          "status": null,
          "certainty": null,
          "time_window": null,
          "place": "",
          "participants": [],
          "missing_fields": [],
          "needs_clarification": false,
          "confidence": 0.0,
          "reason": "只是普通对话，不是日程或待办。"
        }
        """,
    )

    candidate = worker.hybrid_agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-06-04T09:00:00+00:00",
        {
            "intent": "conversation_memory",
            "summary": "用户说：我在看手机报价，先不处理。",
            "importance": 0.45,
            "entities": {"source": "nomi_chat", "role": "user", "event_type": "user_message"},
            "raw_data": {
                "role": "user",
                "content": "我在看手机报价，先不处理。",
                "conversation_id": "conv-1",
            },
        },
    )

    assert candidate is None


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
            if "FROM agenda_items WHERE metadata->>'dedupe_key'" in normalized:
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


def test_persist_agenda_creates_offline_time_reminder_40_minutes_before_start():
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
            if "FROM agenda_items WHERE metadata->>'dedupe_key'" in normalized:
                return Cursor()
            if "INSERT INTO agenda_items" in normalized:
                return Cursor([("22222222-2222-2222-2222-222222222222",)])
            return Cursor()

    persist_agenda(
        Conn(),
        "11111111-1111-1111-1111-111111111111",
        "2026-06-29T09:00:00+08:00",
        {
            "intent": "social_plan",
            "summary": "NOMI_REG_WA_0629 明天15:30人民广场见，带合同",
            "importance": 0.9,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
            "raw_data": {
                "chat_name": "陈子扬",
                "sender": "陈子扬",
                "message": "NOMI_REG_WA_0629 明天15:30人民广场见，带合同",
            },
        },
    )

    reminder_sql, reminder_params = next(item for item in executed if "INSERT INTO agenda_reminders" in item[0])
    metadata = json.loads(reminder_params[8])
    assert "agenda_reminders" in reminder_sql
    assert str(reminder_params[1]) == "22222222-2222-2222-2222-222222222222"
    assert reminder_params[4] == 40
    assert reminder_params[5] == "agenda_reminder:22222222-2222-2222-2222-222222222222:2026-06-30T15:30:00+08:00:40m"
    assert reminder_params[2].isoformat() == "2026-06-30T15:30:00+08:00"
    assert reminder_params[3].isoformat() == "2026-06-30T14:50:00+08:00"
    assert metadata["reminder_policy"]["event_modality"] == "offline"
    assert metadata["reminder_policy"]["reason"] == "detected_physical_location"
    assert "查路线" in json.dumps(metadata["actions"], ensure_ascii=False)


def test_persist_agenda_creates_online_meeting_reminder_10_minutes_before_start():
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
            if "FROM agenda_items WHERE metadata->>'dedupe_key'" in normalized:
                return Cursor()
            if "INSERT INTO agenda_items" in normalized:
                return Cursor([("33333333-3333-3333-3333-333333333333",)])
            return Cursor()

    persist_agenda(
        Conn(),
        "11111111-1111-1111-1111-111111111111",
        "2026-06-29T09:00:00+08:00",
        {
            "intent": "schedule",
            "summary": "明天15:00 Zoom线上会议 https://zoom.us/j/123",
            "importance": 0.88,
            "entities": {"source": "gmail", "event_type": "gmail_thread_snapshot"},
            "raw_data": {
                "subject": "项目同步会",
                "sender": "pm@example.com",
                "body": "明天15:00 Zoom线上会议 https://zoom.us/j/123",
            },
        },
    )

    reminder_sql, reminder_params = next(item for item in executed if "INSERT INTO agenda_reminders" in item[0])
    metadata = json.loads(reminder_params[8])
    assert "agenda_reminders" in reminder_sql
    assert reminder_params[4] == 10
    assert reminder_params[2].isoformat() == "2026-06-30T15:00:00+08:00"
    assert reminder_params[3].isoformat() == "2026-06-30T14:50:00+08:00"
    assert metadata["reminder_policy"]["event_modality"] == "online"
    assert metadata["reminder_policy"]["reason"] == "detected_online_meeting"
    assert "打开会议" in json.dumps(metadata["actions"], ensure_ascii=False)


def test_persist_agenda_creates_deadline_reminder_without_meeting_copy():
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
            if "FROM agenda_items WHERE metadata->>'dedupe_key'" in normalized:
                return Cursor()
            if "INSERT INTO agenda_items" in normalized:
                return Cursor([("55555555-5555-5555-5555-555555555555",)])
            return Cursor()

    persist_agenda(
        Conn(),
        "11111111-1111-1111-1111-111111111111",
        "2026-07-01T20:27:18+08:00",
        {
            "intent": "task_request",
            "summary": "周五18点前把报价单发我，记得核对成本和利润率。 测试码T1",
            "importance": 0.8,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message", "labels": ["deadline", "todo"]},
            "raw_data": {
                "chat_name": "大刚",
                "sender": "大刚",
                "message": "周五18点前把报价单发我，记得核对成本和利润率。 测试码T1",
            },
        },
    )

    reminder_sql, reminder_params = next(item for item in executed if "INSERT INTO agenda_reminders" in item[0])
    metadata = json.loads(reminder_params[8])
    assert "agenda_reminders" in reminder_sql
    assert reminder_params[4] == 60
    assert reminder_params[2].isoformat() == "2026-07-03T18:00:00+08:00"
    assert reminder_params[3].isoformat() == "2026-07-03T17:00:00+08:00"
    assert metadata["reminder_policy"]["event_modality"] == "deadline"
    assert metadata["reminder_policy"]["reason"] == "detected_deadline"
    assert "会议链接" not in reminder_params[7]
    assert "打开会议" not in json.dumps(metadata["actions"], ensure_ascii=False)


def test_persist_agenda_does_not_create_time_reminder_for_fuzzy_event():
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
            if "FROM agenda_items WHERE metadata->>'dedupe_key'" in normalized:
                return Cursor()
            if "INSERT INTO agenda_items" in normalized:
                return Cursor([("44444444-4444-4444-4444-444444444444",)])
            return Cursor()

    persist_agenda(
        Conn(),
        "11111111-1111-1111-1111-111111111111",
        "2026-06-29T09:00:00+08:00",
        {
            "intent": "social_plan",
            "summary": "Maya 说周末找时间见。",
            "importance": 0.82,
            "entities": {"source": "telegram", "event_type": "telegram_message"},
            "raw_data": {"chat_name": "Maya", "sender": "Maya", "message": "周末找时间见"},
        },
    )

    assert not any("INSERT INTO agenda_reminders" in sql for sql, _ in executed)


def test_dispatch_due_agenda_reminders_publishes_realtime_suggestion_once():
    from app.worker import dispatch_due_agenda_reminders

    executed = []
    published = []

    class Cursor:
        rowcount = 1

        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            normalized = " ".join(sql.split())
            if "FROM agenda_reminders r" in normalized:
                return Cursor(
                    [
                        (
                            "55555555-5555-5555-5555-555555555555",
                            "22222222-2222-2222-2222-222222222222",
                            "agenda_reminder:22222222-2222-2222-2222-222222222222:2026-06-30T15:30:00+08:00:40m",
                            "即将出发：人民广场见面",
                            "提醒：你 2026-06-30 周二 15:30 要去人民广场见面，记得带合同。",
                            {
                                "source": "whatsapp",
                                "actions": [{"id": "route_lookup", "label": "查路线"}],
                                "source_event_ids": ["11111111-1111-1111-1111-111111111111"],
                            },
                            ["11111111-1111-1111-1111-111111111111"],
                        )
                    ]
                )
            if "FROM events" in normalized:
                return Cursor([(params[0],)])
            if "FROM proactive_suggestions" in normalized:
                return Cursor()
            return Cursor()

    class Redis:
        def publish(self, channel, payload):
            published.append((channel, payload))

    dispatched = dispatch_due_agenda_reminders(Conn(), Redis(), limit=10)

    assert dispatched == 1
    assert any("INSERT INTO proactive_suggestions" in sql for sql, _ in executed)
    assert any("UPDATE agenda_reminders" in sql and "sent_at" in sql for sql, _ in executed)
    assert published[0][0] == "par:realtime"
    payload = json.loads(published[0][1])
    assert payload["type"] == "proactive_message"
    assert payload["title"] == "即将出发：人民广场见面"
    assert payload["actions"][0]["label"] == "查路线"


def test_dispatch_due_agenda_reminders_without_source_event_uses_null_fk():
    from app.worker import dispatch_due_agenda_reminders

    executed = []
    published = []

    class Cursor:
        rowcount = 1

        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            normalized = " ".join(sql.split())
            if "FROM agenda_reminders r" in normalized:
                return Cursor(
                    [
                        (
                            "55555555-5555-5555-5555-555555555555",
                            "22222222-2222-2222-2222-222222222222",
                            "agenda_reminder:22222222-2222-2222-2222-222222222222:2026-06-30T15:30:00+08:00:40m",
                            "即将出发：人民广场见面",
                            "提醒：你 2026-06-30 周二 15:30 要去人民广场见面，记得带合同。",
                            {"source": "agenda", "actions": [{"id": "route_lookup", "label": "查路线"}]},
                            [],
                        )
                    ]
                )
            if "FROM proactive_suggestions" in normalized:
                return Cursor()
            return Cursor()

    class Redis:
        def publish(self, channel, payload):
            published.append((channel, payload))

    dispatched = dispatch_due_agenda_reminders(Conn(), Redis(), limit=10)

    assert dispatched == 1
    insert_params = next(params for sql, params in executed if "INSERT INTO proactive_suggestions" in sql)
    assert insert_params[1] is None
    payload = json.loads(published[0][1])
    assert payload["source_event_id"] == ""


def test_dispatch_due_agenda_reminders_skips_stale_source_event_ids():
    from app.worker import dispatch_due_agenda_reminders

    executed = []
    published = []
    missing_event_id = "c1b886d2-120b-58c8-8350-5d0efe0e8813"
    valid_event_id = "b4d40ebe-d118-4280-b79e-6e912761b286"

    class Cursor:
        rowcount = 1

        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            normalized = " ".join(sql.split())
            if "FROM agenda_reminders r" in normalized:
                return Cursor(
                    [
                        (
                            "ae01e221-5b9c-4fef-b917-bc6b9d4d1e62",
                            "17a11760-fb46-4133-8e97-8c29584e3e37",
                            "agenda_reminder:17a11760-fb46-4133-8e97-8c29584e3e37:2026-07-03T10:00:00+08:00:40m",
                            "即将出发：静安寺地铁站见面",
                            "提醒：你 2026-07-03 周五 10:00 要去静安寺地铁站见面。",
                            {"source": "telegram", "source_event_ids": [missing_event_id, valid_event_id]},
                            [missing_event_id, valid_event_id],
                        )
                    ]
                )
            if "FROM events" in normalized:
                return Cursor([(valid_event_id,)] if params and params[0] == valid_event_id else [])
            if "FROM proactive_suggestions" in normalized:
                return Cursor()
            return Cursor()

    class Redis:
        def publish(self, channel, payload):
            published.append((channel, payload))

    dispatched = dispatch_due_agenda_reminders(Conn(), Redis(), limit=10)

    assert dispatched == 1
    insert_params = next(params for sql, params in executed if "INSERT INTO proactive_suggestions" in sql)
    assert insert_params[1] == valid_event_id
    payload = json.loads(published[0][1])
    assert payload["source_event_id"] == valid_event_id


def test_maybe_dispatch_due_agenda_reminders_respects_scan_interval(monkeypatch):
    import app.worker as worker

    calls = []

    monkeypatch.setattr(worker, "WORKER_REMINDER_SCAN_INTERVAL_SECONDS", 30)
    monkeypatch.setattr(worker.time, "monotonic", lambda: 100.0)

    def fake_dispatch(redis_client, last_scan_at):
        calls.append((redis_client, last_scan_at))
        return 100.0

    monkeypatch.setattr(worker, "_dispatch_due_agenda_reminders_if_due", fake_dispatch)

    assert worker.maybe_dispatch_due_agenda_reminders("redis", 80.0) == 80.0
    assert calls == []
    assert worker.maybe_dispatch_due_agenda_reminders("redis", 69.0) == 100.0
    assert calls == [("redis", 69.0)]


def test_persist_agenda_version_records_previous_value_when_updating_existing_item():
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
            if "FROM agenda_items WHERE metadata->>'dedupe_key'" in normalized:
                return Cursor(
                    [
                        (
                            "22222222-2222-2222-2222-222222222222",
                            "appointment",
                            "Alex 说那就周日见。",
                            "scheduled",
                            "fuzzy",
                            {"raw_text": "那就周日吧", "has_exact_time": False, "has_fuzzy_time": True},
                            "",
                            ["Alex"],
                            ["exact_time", "exact_place"],
                            True,
                            0.82,
                            ["77777777-7777-7777-7777-777777777777"],
                            {"dedupe_key": "agenda:appointment:whatsapp:wa alex"},
                        )
                    ]
                )
            return Cursor()

    persist_agenda(
        Conn(),
        "11111111-1111-1111-1111-111111111111",
        "2026-05-28T10:00:00+00:00",
        {
            "intent": "social_plan",
            "summary": "Alex 把见面改到周六。",
            "importance": 0.86,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
            "raw_data": {"chat_name": "Alex", "chat_id": "wa-alex", "sender": "Alex", "message": "改到周六吧"},
        },
    )

    version_sql, version_params = next(item for item in executed if "INSERT INTO agenda_item_versions" in item[0])
    previous_value = json.loads(version_params[3])
    new_value = json.loads(version_params[4])
    assert "INSERT INTO agenda_item_versions" in version_sql
    assert version_params[2] == "reschedule"
    assert previous_value["title"] == "Alex 说那就周日见。"
    assert previous_value["certainty"] == "fuzzy"
    assert previous_value["missing_fields"] == ["exact_time", "exact_place"]
    assert previous_value["source_event_ids"] == ["77777777-7777-7777-7777-777777777777"]
    assert new_value["title"] == "Alex 把见面改到周六。"
    assert new_value["source_event_ids"] == ["11111111-1111-1111-1111-111111111111"]


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
    assert suggestion["metadata"]["source"] == "whatsapp"
    assert labels == ["查路线", "帮我打车", "稍后提醒"]
    assert actions[1]["risk"] == "external_execution"
    assert actions[1]["requires_confirmation"] is True


def test_suggestion_for_chinese_appointment_intent_and_label_includes_route_ride_actions():
    from app.worker import suggestion_for_event

    suggestion = suggestion_for_event(
        "11111111-1111-1111-1111-111111111111",
        {
            "intent": "约定",
            "summary": "明天下午3点在武康路咖啡店见，麻烦带报价单。",
            "importance": 0.84,
            "entities": {
                "source": "whatsapp",
                "event_type": "whatsapp_message",
                "labels": ["appointment"],
                "primary_label": "appointment",
            },
        },
    )

    assert suggestion is not None
    assert suggestion["title"] == "跟进近期安排"
    assert suggestion["metadata"]["source"] == "whatsapp"
    action_ids = [item["id"] for item in suggestion["metadata"]["actions"]]
    assert action_ids == ["route_lookup", "ride_prepare", "snooze"]


def test_suggestion_for_nomi_chat_events_are_suppressed_at_source():
    from app.worker import suggestion_for_event

    user_message_suggestion = suggestion_for_event(
        "11111111-1111-1111-1111-111111111111",
        {
            "intent": "user_instruction",
            "summary": "user said to Nomi: 保利广场的安排缺什么信息？请给出来源。",
            "importance": 0.76,
            "entities": {
                "source": "nomi_chat",
                "event_type": "user_message",
                "labels": ["todo", "user_instruction"],
                "primary_label": "todo",
                "conversation_id": "conv-1",
            },
            "raw_data": {
                "source": "nomi_chat",
                "event_type": "user_message",
                "role": "user",
                "content": "保利广场的安排缺什么信息？请给出来源。",
            },
        },
    )
    dialogue_batch_suggestion = suggestion_for_event(
        "22222222-2222-2222-2222-222222222222",
        {
            "intent": "dialogue_batch_summary",
            "summary": "Nomi 对话批次摘要：用户关注人民广场会面，最后回复为下午4点。",
            "importance": 0.78,
            "entities": {
                "source": "nomi_chat",
                "event_type": "dialogue_batch",
                "labels": ["todo"],
                "primary_label": "todo",
                "conversation_id": "conv-1",
            },
            "raw_data": {
                "source": "nomi_chat",
                "event_type": "dialogue_batch",
                "conversation_id": "conv-1",
            },
        },
    )

    assert user_message_suggestion is None
    assert dialogue_batch_suggestion is None


def test_suggestion_suppresses_whatsapp_title_badge_snapshot():
    from app.worker import suggestion_for_event

    suggestion = suggestion_for_event(
        "33333333-3333-3333-3333-333333333333",
        {
            "intent": "social_plan",
            "summary": "(2) WhatsApp",
            "importance": 0.9,
            "entities": {
                "source": "whatsapp",
                "event_type": "whatsapp_snapshot",
                "labels": ["appointment"],
                "primary_label": "appointment",
            },
            "raw_data": {"title": "(2) WhatsApp", "source": "whatsapp", "event_type": "whatsapp_snapshot"},
        },
    )

    assert suggestion is None


def test_suggestion_suppresses_focus_page_title_even_with_appointment_label():
    from app.worker import suggestion_for_event

    suggestion = suggestion_for_event(
        "11111111-1111-1111-1111-111111111111",
        {
            "intent": "schedule",
            "summary": "Gmail: Secure, AI-Powered Email for Everyone | Google Workspace",
            "importance": 0.43,
            "entities": {
                "source": "focus",
                "event_type": "deep_focus",
                "labels": ["appointment"],
                "primary_label": "appointment",
            },
        },
    )

    assert suggestion is None


def test_agenda_candidate_suppresses_focus_page_title_even_with_appointment_label():
    from app.worker import agenda_candidate_from_semantic

    candidate = agenda_candidate_from_semantic(
        "11111111-1111-1111-1111-111111111111",
        "2026-06-10T10:00:00+08:00",
        {
            "intent": "schedule",
            "summary": "Gmail: Secure, AI-Powered Email for Everyone | Google Workspace",
            "importance": 0.43,
            "entities": {
                "source": "focus",
                "event_type": "deep_focus",
                "labels": ["appointment"],
                "primary_label": "appointment",
            },
            "raw_data": {
                "source": "focus",
                "event_type": "deep_focus",
                "title": "Gmail: Secure, AI-Powered Email for Everyone | Google Workspace",
            },
        },
    )

    assert candidate is None


def test_suggestion_for_canceled_meeting_does_not_offer_route_or_ride():
    from app.worker import suggestion_for_event

    suggestion = suggestion_for_event(
        "11111111-1111-1111-1111-111111111111",
        {
            "intent": "cancel",
            "summary": "Alex 说周日武康路见面的安排取消了，不用过去。",
            "importance": 0.86,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message", "labels": ["cancel", "appointment"]},
        },
    )

    assert suggestion is not None
    assert suggestion["title"] == "确认取消安排"
    assert suggestion["metadata"]["suggestion_type"] == "calendar_cancellation"
    action_ids = [item["id"] for item in suggestion["metadata"]["actions"]]
    assert "route_lookup" not in action_ids
    assert "ride_prepare" not in action_ids
    assert "snooze" in action_ids or "open_source" in action_ids


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


def test_linkedin_browser_observation_persists_vector_without_generic_fact_graph(monkeypatch):
    from app import worker

    executed = []

    class Cursor:
        rowcount = 1

        def fetchone(self):
            return ["99999999-9999-9999-9999-999999999999"]

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            return Cursor()

    monkeypatch.setattr(worker, "text_embedding_with_provider", lambda content: ([0.1, 0.2, 0.3], "test"))
    monkeypatch.setattr(worker, "vector_literal", lambda embedding: "[0.1,0.2,0.3]")
    monkeypatch.setattr(worker, "embedding_status", lambda: {"model": "test-embedding"})

    worker.persist_memory_enrichment(
        Conn(),
        "11111111-1111-1111-1111-111111111111",
        "2026-07-04T17:27:55+00:00",
        {
            "intent": "generic_event",
            "entities": {
                "source": "linkedin",
                "event_type": "linkedin_job_search_results",
                "labels": ["low_value"],
                "primary_label": "low_value",
            },
            "importance": 0.2,
            "summary": "LinkedIn 搜索到 AI Agent Engineer 和 Staff Software Engineer 岗位。",
            "raw_data": {
                "source": "linkedin",
                "event_type": "linkedin_job_search_results",
                "job_results": [
                    {"title": "AI Agent Engineer", "company": "LianLian"},
                    {"title": "Staff Software Engineer", "company": "Airwallex"},
                ],
            },
        },
        "linkedin",
        "linkedin_job_search_results",
    )

    combined_sql = "\n".join(sql for sql, _ in executed)
    assert "INSERT INTO memory_vectors" in combined_sql
    assert "INSERT INTO facts" not in combined_sql
    assert "INSERT INTO relationships" not in combined_sql
    assert "INSERT INTO memory_states" not in combined_sql


def test_job_recruiter_company_role_relationships_are_persisted():
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
        "2026-06-09T00:00:00+00:00",
        {
            "intent": "career_opportunity",
            "entities": {
                "source": "gmail",
                "event_type": "gmail_thread_snapshot",
                "recruiter": "RG_Maya",
                "company": "Example AI",
                "role": "AI PM role",
            },
            "importance": 0.88,
            "summary": "RG_Maya 是 Example AI 的 recruiter，正在跟进 AI PM role。",
            "raw_data": {
                "subject": "AI PM role at Example AI",
                "sender": "RG_Maya",
                "body": "I am the recruiter for Example AI and would like to discuss the AI PM role.",
            },
        },
    )

    relationship_params = [params for sql, params in executed if "INSERT INTO relationships" in sql]
    relation_types = [params[3] for params in relationship_params]
    assert "recruits_for_company" in relation_types
    assert "recruits_for_role" in relation_types
    assert "company_hiring_role" in relation_types
    metadata_payloads = [str(params[-1]) for params in relationship_params]
    assert any("RG_Maya" in payload and "Example AI" in payload for payload in metadata_payloads)
    assert any("AI PM role" in payload for payload in metadata_payloads)


def test_linkedin_job_search_rows_prefer_private_openable_urls():
    from app.worker import linkedin_job_rows_from_raw_data

    protected = {
        "capture_scope": "visible_job_search_results",
        "url": "https://www.linkedin.com/jobs/search/?currentJobId=REDACTED",
        "job_results": [
            {
                "job_id": "linkedin_search_backend",
                "source": "linkedin_browser_observation",
                "title": "Backend Engineer (Golang&PHP)",
                "company": "Xsolla",
                "location": "Beijing, Beijing, China (On-site)",
                "url": "https://www.linkedin.com/jobs/search/?currentJobId=REDACTED",
                "text": "Backend Engineer (Golang&PHP)\nXsolla\nBeijing, Beijing, China (On-site)",
            }
        ],
    }
    private = {
        **protected,
        "url": "https://www.linkedin.com/jobs/search/?currentJobId=4429828054&keywords=Backend",
        "job_results": [
            {
                **protected["job_results"][0],
                "url": "https://www.linkedin.com/jobs/view/4429828054/",
            }
        ],
    }

    rows = linkedin_job_rows_from_raw_data(
        "693979dd-c0cf-47be-9d4e-76547f368279",
        private,
        fallback_raw_data=protected,
        career_text="Java Go 后端 高并发 Redis MySQL",
    )

    assert len(rows) == 1
    assert rows[0]["id"] == "linkedin_search_backend"
    assert rows[0]["title"] == "Backend Engineer (Golang&PHP)"
    assert rows[0]["company"] == "Xsolla"
    assert rows[0]["url"] == "https://www.linkedin.com/jobs/view/4429828054/"
    assert rows[0]["payload"]["url_openable"] is True
    assert rows[0]["payload"]["search_query"] == "Backend"
    assert rows[0]["fit_score"] >= 0.65


def test_linkedin_job_rows_clean_pipe_title_and_company():
    from app.worker import linkedin_job_rows_from_raw_data

    rows = linkedin_job_rows_from_raw_data(
        "e1f9cc1b-e3b9-44d9-91e9-4bc30da10dbf",
        {
            "capture_scope": "visible_job_detail",
            "job_pages": [
                {
                    "job_id": "linkedin_job_4388714215",
                    "title": "Backend Engineer, AI (Agent Systems) | BJAK | LinkedIn",
                    "company": "BJAK",
                    "location": "Beijing, Beijing, China",
                    "url": "https://www.linkedin.com/jobs/view/4388714215/",
                    "text": "Backend Engineer, AI (Agent Systems)\nBJAK\nBeijing, Beijing, China\nFull-time",
                }
            ],
        },
        career_text="Java Go 后端 AI Agent 高并发 Redis MySQL",
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "Backend Engineer, AI (Agent Systems)"
    assert rows[0]["company"] == "BJAK"
    assert rows[0]["payload"]["title"] == "Backend Engineer, AI (Agent Systems)"
    assert rows[0]["payload"]["summary"].startswith("BJAK 的 Backend Engineer, AI (Agent Systems)")


def test_linkedin_job_search_rows_skip_action_request_query():
    from app.worker import linkedin_job_rows_from_raw_data

    raw_data = {
        "capture_scope": "visible_job_search_results",
        "title": "(16) 基于我刚刚真实 LinkedIn 搜索到的岗位，结合我的后端简历推荐适合我的工作机会，给出推荐理由和可以打开的链接 Jobs | LinkedIn",
        "url": "https://www.linkedin.com/jobs/search/?keywords=%E5%9F%BA%E4%BA%8E%E6%88%91%E5%88%9A%E5%88%9A%E7%9C%9F%E5%AE%9E%20LinkedIn%20%E6%90%9C%E7%B4%A2%E5%88%B0%E7%9A%84%E5%B2%97%E4%BD%8D%EF%BC%8C%E7%BB%93%E5%90%88%E6%88%91%E7%9A%84%E5%90%8E%E7%AB%AF%E7%AE%80%E5%8E%86%E6%8E%A8%E8%8D%90%E9%80%82%E5%90%88%E6%88%91%E7%9A%84%E5%B7%A5%E4%BD%9C%E6%9C%BA%E4%BC%9A%EF%BC%8C%E7%BB%99%E5%87%BA%E6%8E%A8%E8%8D%90%E7%90%86%E7%94%B1%E5%92%8C%E5%8F%AF%E4%BB%A5%E6%89%93%E5%BC%80%E7%9A%84%E9%93%BE%E6%8E%A5",
        "job_results": [
            {
                "title": "Business Development Manager",
                "company": "Rock-West",
                "location": "China",
                "url": "https://www.linkedin.com/jobs/search/?currentJobId=4413966477",
                "text": "Business Development Manager Rock-West China",
            }
        ],
    }

    rows = linkedin_job_rows_from_raw_data(
        "1516758c-7ae7-40d2-8c93-4e45b281cbfa",
        raw_data,
        career_text="Java Go 后端 高并发 Redis MySQL",
    )

    assert rows == []


def test_persist_linkedin_job_search_opportunities_upserts_job_rows(monkeypatch):
    import app.worker as worker

    executed = []

    class Cursor:
        def __init__(self, row=None):
            self._row = row

        def fetchone(self):
            return self._row

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            if "SELECT raw_data_private FROM events" in sql:
                return Cursor(None)
            if "FROM career_profiles" in sql:
                return Cursor(("Java 后端架构", ["Backend Engineer"], ["Beijing"], ["Java", "Go", "Redis"], {"skills": ["Java", "Go"]}))
            if "FROM career_resumes" in sql:
                return Cursor(("Java Go 后端 高并发 Redis MySQL", {"skills": ["Java", "Go", "Redis", "MySQL"]}))
            return Cursor(None)

    count = worker.persist_linkedin_job_search_opportunities(
        Conn(),
        "693979dd-c0cf-47be-9d4e-76547f368279",
        {
            "raw_data": {
                "capture_scope": "visible_job_search_results",
                "job_results": [
                    {
                        "job_id": "linkedin_search_backend",
                        "source": "linkedin_browser_observation",
                        "title": "Backend Engineer (Golang&PHP)",
                        "company": "Xsolla",
                        "location": "Beijing, Beijing, China (On-site)",
                        "url": "https://www.linkedin.com/jobs/search/?currentJobId=REDACTED",
                        "text": "Backend Engineer (Golang&PHP)\nXsolla\nBeijing, Beijing, China (On-site)",
                    }
                ],
            }
        },
    )

    assert count == 1
    upserts = [(sql, params) for sql, params in executed if "INSERT INTO job_opportunities" in sql]
    assert len(upserts) == 1
    _, params = upserts[0]
    assert params[0] == "linkedin_search_backend"
    assert params[1] == "linkedin_browser_observation"
    assert params[2] == "Backend Engineer (Golang&PHP)"
    assert params[3] == "Xsolla"
    assert params[7] >= 0.65
    assert params[9] == ["693979dd-c0cf-47be-9d4e-76547f368279"]


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


def test_suggestion_for_event_drops_low_value_gmail_or_linkedin_notifications():
    from app.worker import suggestion_for_event

    suggestion = suggestion_for_event(
        "11111111-1111-1111-1111-111111111112",
        {
            "intent": "generic_event",
            "entities": {
                "source": "gmail",
                "event_type": "gmail_message_snapshot",
                "labels": ["low_value"],
                "primary_label": "low_value",
            },
            "importance": 0.55,
            "summary": "You have 2 new messages on LinkedIn.",
        },
    )

    assert suggestion is None


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

    class Cursor:
        def fetchone(self):
            return None

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            return Cursor()

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

    assert any("INSERT INTO proactive_suggestions" in sql for sql, _ in executed)
    assert published[0][0] == "par:realtime"
    assert '"type": "proactive_message"' in published[0][1]
    assert "处理邮件待办" in published[0][1]


def test_persist_suggestion_suppresses_linkedin_profile_browser_observation_without_realtime_publish():
    from app.worker import persist_suggestion

    published = []
    executed = []

    class Cursor:
        def fetchone(self):
            return ("existing-suggestion-id",)

    class Conn:
        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            executed.append((normalized, params))
            raise AssertionError("LinkedIn browser observations must not create proactive suggestions")

    class Redis:
        def publish(self, channel, payload):
            published.append((channel, payload))

    persist_suggestion(
        Conn(),
        "22222222-2222-2222-2222-222222222222",
        {
            "intent": "information_extraction",
            "entities": {"source": "linkedin", "event_type": "linkedin_profile_snapshot"},
            "importance": 0.86,
            "summary": "张子长是北京三快科技有限公司的项目经理，位于北京。",
        },
        redis_client=Redis(),
    )

    assert executed == []
    assert published == []


def test_persist_suggestion_suppresses_same_visible_message_across_sources_without_realtime_publish():
    from app.worker import persist_suggestion

    published = []
    executed = []

    class Cursor:
        def __init__(self, row=None):
            self.row = row

        def fetchone(self):
            return self.row

    class Conn:
        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            executed.append((normalized, params))
            if "pg_advisory_xact_lock" in normalized:
                return Cursor()
            if "metadata->>'dedupe_key'" in normalized:
                return Cursor()
            if "metadata->>'display_dedupe_key'" in normalized:
                assert str(params[0]).startswith("display:")
                assert params[1] == "跟进近期安排"
                assert params[2] == "这条信息可能需要跟进：NOMI_REG_WA_0629 明天15:30人民广场见，带合同。"
                return Cursor(("existing-visible-suggestion",))
            raise AssertionError("visible duplicate suggestions must not be inserted or updated")

    class Redis:
        def publish(self, channel, payload):
            published.append((channel, payload))

    persist_suggestion(
        Conn(),
        "33333333-3333-3333-3333-333333333333",
        {
            "intent": "social_plan",
            "entities": {"source": "telegram", "event_type": "telegram_message_preview"},
            "importance": 0.82,
            "summary": "NOMI_REG_WA_0629 明天15:30人民广场见，带合同。",
        },
        redis_client=Redis(),
    )

    assert [item[0] for item in executed[:2]].count("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))") == 2
    assert any("metadata->>'display_dedupe_key'" in sql for sql, _ in executed)
    assert not any("INSERT INTO proactive_suggestions" in sql for sql, _ in executed)
    assert published == []


def test_persist_suggestion_locks_dedupe_key_before_duplicate_lookup():
    from app.worker import persist_suggestion

    executed = []

    class Cursor:
        def fetchone(self):
            return None

    class Conn:
        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            executed.append((normalized, params))
            return Cursor()

    persist_suggestion(
        Conn(),
        "33333333-3333-3333-3333-333333333333",
        {
            "intent": "social_plan",
            "entities": {"source": "telegram", "event_type": "telegram_message_preview"},
            "importance": 0.8,
            "summary": "NOMI_REG_TG_0629 周五10点静安寺地铁站见 Maya。",
        },
    )

    assert "pg_advisory_xact_lock" in executed[0][0]
    assert executed[0][1] == (
        "social_followup:telegram:social_plan:NOMI_REG_TG_0629 周五10点静安寺地铁站见 Maya。",
    )
    duplicate_lookup_index = next(index for index, item in enumerate(executed) if "FROM proactive_suggestions" in item[0])
    insert_index = next(index for index, item in enumerate(executed) if "INSERT INTO proactive_suggestions" in item[0])
    assert duplicate_lookup_index > 0
    assert insert_index > duplicate_lookup_index


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


def test_extract_semantics_keeps_browser_network_events_rules_only(monkeypatch):
    from app import worker

    def fail_model_call(messages):
        raise AssertionError("browser telemetry should not call the model")

    monkeypatch.setattr(worker, "call_model", fail_model_call)

    semantic = worker.extract_semantics(
        "telegram",
        "browser_network_event",
        {
            "kind": "xhr",
            "method": "GET",
            "url": "https://web.telegram.org/api/messages",
            "status": 200,
            "capture_scope": "runtime_network_hook",
        },
    )

    assert semantic["intent"] == "generic_event"
    assert semantic["importance"] < 0.55
    assert semantic["entities"]["primary_label"] == "low_value"
    assert semantic["entities"]["classification_trace"]["parser_mode"] == "rules_only_telemetry"


def test_worker_start_id_prefers_checkpoint_over_configured_default(monkeypatch):
    from app import worker

    class RedisClient:
        def get(self, key):
            assert key == "events:raw:worker:last_id"
            return "1780315110199-0"

    monkeypatch.setattr(worker, "REDIS_START_ID", "$")

    assert worker.resolve_start_id(RedisClient()) == "1780315110199-0"


def test_worker_start_id_replays_from_beginning_when_no_checkpoint_and_config_is_dollar(monkeypatch):
    from app import worker

    class RedisClient:
        def get(self, key):
            return None

    monkeypatch.setattr(worker, "REDIS_START_ID", "$")

    assert worker.resolve_start_id(RedisClient()) == "0-0"


def test_process_stream_entry_persists_semantics_and_checkpoint(monkeypatch):
    from app import worker

    calls = []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class PsycopgModule:
        def connect(self, url):
            assert url == "postgresql://test"
            calls.append(("connect", url))
            return Conn()

    class RedisClient:
        def set(self, key, value):
            calls.append(("set", key, value))

    monkeypatch.setattr(worker, "psycopg", PsycopgModule())
    monkeypatch.setattr(
        worker,
        "extract_semantics",
        lambda source, event_type, raw_data: {
            "intent": "social_plan",
            "entities": {"source": source, "event_type": event_type},
            "importance": 0.86,
            "summary": raw_data["message"],
            "model_version": "test",
        },
    )
    monkeypatch.setattr(
        worker,
        "persist_semantics",
        lambda conn, event_id, timestamp, semantic, redis_client=None: calls.append(
            ("persist", event_id, timestamp, semantic["summary"], redis_client is not None)
        ),
    )

    result = worker.process_stream_entry(
        RedisClient(),
        "1780316000000-0",
        {
            "event_id": "11111111-1111-1111-1111-111111111111",
            "timestamp": "2026-06-01T12:00:00+00:00",
            "source": "whatsapp",
            "event_type": "whatsapp_message",
            "raw_data": json.dumps({"message": "明天下午三点在武康路见"}, ensure_ascii=False),
        },
    )

    assert result is True
    assert ("persist", "11111111-1111-1111-1111-111111111111", "2026-06-01T12:00:00+00:00", "明天下午三点在武康路见", True) in calls
    assert ("set", "events:raw:worker:last_id", "1780316000000-0") in calls


def test_process_stream_entry_deadletters_bad_payload_and_advances_checkpoint():
    from app import worker

    calls = []

    class RedisClient:
        def xadd(self, stream, fields):
            calls.append(("xadd", stream, fields["message_id"], "raw_data" in fields))

        def set(self, key, value):
            calls.append(("set", key, value))

    result = worker.process_stream_entry(
        RedisClient(),
        "1780316000001-0",
        {
            "event_id": "22222222-2222-2222-2222-222222222222",
            "timestamp": "2026-06-01T12:00:00+00:00",
            "source": "gmail",
            "event_type": "gmail_thread_snapshot",
            "raw_data": "{not-json",
        },
    )

    assert result is False
    assert ("xadd", "events:deadletter", "1780316000001-0", True) in calls
    assert ("set", "events:raw:worker:last_id", "1780316000001-0") in calls


def test_process_stream_entry_result_does_not_checkpoint_retryable_db_failure(monkeypatch):
    from app import worker

    calls = []

    class PsycopgModule:
        OperationalError = worker.psycopg.OperationalError

        def connect(self, url):
            raise self.OperationalError("connection failed")

    class RedisClient:
        def xadd(self, stream, fields):
            calls.append(("xadd", stream, fields["message_id"]))

        def set(self, key, value):
            calls.append(("set", key, value))

    monkeypatch.setattr(worker, "psycopg", PsycopgModule())
    monkeypatch.setattr(
        worker,
        "extract_semantics",
        lambda source, event_type, raw_data: {
            "intent": "social_plan",
            "entities": {"source": source, "event_type": event_type},
            "importance": 0.86,
            "summary": raw_data["message"],
            "model_version": "test",
        },
    )

    result = worker.process_stream_entry_result(
        RedisClient(),
        "1780316000002-0",
        {
            "event_id": "33333333-3333-3333-3333-333333333333",
            "timestamp": "2026-06-01T12:00:00+00:00",
            "source": "gmail",
            "event_type": "gmail_message_snapshot",
            "raw_data": json.dumps({"message": "明天3点开会"}, ensure_ascii=False),
        },
    )

    assert result.success is False
    assert result.checkpoint is False
    assert ("xadd", "events:deadletter", "1780316000002-0") in calls
    assert [call for call in calls if call[0] == "set"] == []


def test_stream_entry_priority_processes_user_messages_before_focus_noise():
    from app.worker import stream_batch_checkpoint_id, stream_entry_priority

    entries = [
        ("1780316000001-0", {"source": "focus", "event_type": "deep_focus"}),
        ("1780316000002-0", {"source": "whatsapp", "event_type": "whatsapp_message"}),
        ("1780316000003-0", {"source": "browser", "event_type": "browser_network_event"}),
    ]

    sorted_entries = sorted(entries, key=stream_entry_priority)

    assert sorted_entries[0][1]["source"] == "whatsapp"
    assert sorted_entries[-1][1]["source"] == "browser"
    assert stream_batch_checkpoint_id(entries) == "1780316000003-0"


def test_persist_semantics_skips_heavy_outputs_for_low_value_telemetry():
    from app.worker import persist_semantics

    executed = []

    class Cursor:
        rowcount = 1

    class Conn:
        def execute(self, sql, params=()):
            executed.append(" ".join(sql.split()))
            return Cursor()

    persist_semantics(
        Conn(),
        "11111111-1111-1111-1111-111111111111",
        "2026-06-10T10:00:00+08:00",
        {
            "intent": "schedule",
            "summary": "Gmail: Secure, AI-Powered Email for Everyone | Google Workspace",
            "importance": 0.43,
            "model_version": "test",
            "entities": {
                "source": "focus",
                "event_type": "deep_focus",
                "labels": ["appointment"],
            },
            "raw_data": {
                "source": "focus",
                "event_type": "deep_focus",
                "title": "Gmail: Secure, AI-Powered Email for Everyone | Google Workspace",
            },
        },
    )

    combined = "\n".join(executed)
    assert "INSERT INTO semantic_events" in combined
    assert "SELECT source, event_type FROM events" not in combined
    assert "INSERT INTO timeline" not in combined


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


def test_mask_value_does_not_treat_codename_as_a_verification_code():
    from app.worker import mask_value

    message = "NOMI_REAL_WA_20260727_B project codename CedarFalcon deadline 2026-08-11"

    assert mask_value(message) == message


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


def test_mask_value_preserves_iso_dates_and_deadline_times_before_phone_redaction():
    from app.worker import mask_value

    masked = mask_value(
        {
            "body": "Please send your tailored resume before 2026-06-15 18:00. Call +1 415 555 2671 only if urgent.",
            "text": "available before 2026-06-15 18:00",
        }
    )

    rendered = str(masked)
    assert "2026-06-15 18:00" in rendered
    assert "+1 415 555 2671" not in rendered
    assert "PHONE_1" in rendered


def test_mask_value_preserves_iso_times_before_chinese_punctuation():
    from app.worker import mask_value

    masked = mask_value(
        {
            "text": "面试安排在2026-06-13 10:30，Zoom链接稍后发。联系电话 +86 138 0000 0000。",
        }
    )

    assert masked["text"] == "面试安排在2026-06-13 10:30，Zoom链接稍后发。联系电话 PHONE_1。"


def test_mask_value_preserves_linkedin_job_detail_urls_while_redacting_phone():
    from app.worker import mask_value

    masked = mask_value(
        {
            "url": "https://www.linkedin.com/jobs/view/4404787524/",
            "text": "岗位链接 https://www.linkedin.com/jobs/view/4378789245/，联系电话 +86 138 0000 0000。",
        }
    )

    assert masked["url"] == "https://www.linkedin.com/jobs/view/4404787524/"
    assert "https://www.linkedin.com/jobs/view/4378789245/" in masked["text"]
    assert "PHONE_1" in masked["text"]


def test_mask_value_preserves_task_identifiers_and_chinese_clock_times():
    from app.worker import mask_value

    masked = mask_value(
        {
            "message": "3点去武康路，周日上午10点再确认 INV-RG-1001 和 rg-20260529-001。",
            "subject": "处理 INV-RG-1001 报价单",
        }
    )

    rendered = str(masked)
    assert "3点" in rendered
    assert "10点" in rendered
    assert "INV-RG-1001" in rendered
    assert "rg-20260529-001" in rendered
    assert "AMOUNT_1" not in rendered
    assert "PHONE_1" not in rendered


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
