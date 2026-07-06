import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_simple_chat_only_needs_dialogue_context():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("你好，简单介绍一下你能做什么", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "simple_chat"
    assert route.needs_dialogue is True
    assert limits["dialogue"] == 30
    assert limits["input_target_tokens"] == 16000
    assert route.needs_memory is False
    assert route.needs_agenda is False
    assert route.needs_tasks is False
    assert route.needs_source is False


def test_answer_format_instruction_uses_small_dialogue_window_for_low_latency():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("请只回复：pong", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "simple_chat"
    assert route.needs_dialogue is True
    assert route.reason == "answer_format"
    assert limits["dialogue"] == 10
    assert limits["input_target_tokens"] == 4000
    assert limits["memory"] == 0
    assert limits["tasks"] == 0


def test_short_reply_keeps_dialogue_for_reference_resolution():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("需要", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "simple_chat"
    assert route.needs_dialogue is True
    assert route.reason == "short_reply"
    assert limits["dialogue"] == 30
    assert limits["memory"] == 0


def test_agenda_question_needs_agenda_and_dialogue():
    from app.chat_router import route_chat_context

    route = route_chat_context("我今天下午有哪些安排？", ui_state=None)

    assert route.intent == "agenda_query"
    assert route.needs_dialogue is True
    assert route.needs_agenda is True
    assert route.needs_memory is False


def test_weekday_deadline_question_routes_to_agenda_with_wider_window():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("周五18点前我要做什么？", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "agenda_query"
    assert route.needs_agenda is True
    assert route.needs_source is True
    assert route.needs_memory is True
    assert route.needs_memory_rag is True
    assert limits["agenda"] >= 8
    assert limits["source"] > 0
    assert limits["memory_rag"] > 0


def test_linkedin_job_apply_request_routes_to_job_query_with_confirmation_risk():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("帮我申请 linkedin_search_9ed794c2eb50，提交前必须让我确认", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "job_query"
    assert route.reason == "job_context"
    assert route.needs_source is True
    assert route.needs_memory is True
    assert route.needs_tasks is True
    assert route.risk["requires_user_confirmation"] is True
    assert limits["input_target_tokens"] == 96000


def test_cancelled_arrangements_question_routes_to_agenda():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("我最近有什么被取消的安排？", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "agenda_query"
    assert route.needs_agenda is True
    assert limits["agenda"] >= 8


def test_insurance_preference_question_routes_to_memory():
    from app.chat_router import route_chat_context

    route = route_chat_context("我买保险最关心什么？", ui_state=None)

    assert route.intent == "memory_query"
    assert route.needs_memory is True
    assert route.needs_memory_rag is True


def test_chinese_open_meeting_question_routes_to_agenda():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("最近有要开的会吗", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "agenda_query"
    assert route.needs_agenda is True
    assert limits["agenda"] > 0
    assert limits["memory"] == 0


def test_specific_place_agenda_question_fetches_source_and_memory_fallbacks():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("保利广场的安排缺什么信息？请给出来源。", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "agenda_query"
    assert route.needs_agenda is True
    assert route.needs_source is True
    assert route.needs_memory is True
    assert route.needs_memory_rag is True
    assert limits["agenda"] >= 8
    assert limits["source"] > 0
    assert limits["memory_rag"] > 0


def test_memory_question_needs_scoped_memory_and_source():
    from app.chat_router import route_chat_context

    route = route_chat_context("Alice 之前说 PHONE_1 报价什么时候截止？", ui_state=None)

    assert route.intent == "memory_query"
    assert route.needs_memory is True
    assert route.needs_source is True


def test_family_relationship_question_needs_memory_graph_and_rag():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("谁儿子叫王刚", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "relationship_query"
    assert route.needs_memory is True
    assert route.needs_memory_graph is True
    assert route.needs_memory_rag is True
    assert limits["memory_graph"] > 0
    assert limits["memory_rag"] > 0


def test_family_relationship_question_extracts_object_name_for_retrieval():
    from app.main import normalize_retrieval_pattern, query_tokens, token_patterns

    assert query_tokens("谁儿子叫王刚")[0] == "王刚"
    assert "%王刚%" in token_patterns("谁儿子叫王刚")
    assert normalize_retrieval_pattern("谁儿子叫王刚") == "%王刚%"
    assert query_tokens("张红是谁")[0] == "张红"
    assert "%张红%" in token_patterns("张红是谁")
    assert normalize_retrieval_pattern("张红是谁") == "%张红%"
    assert (
        normalize_retrieval_pattern("张红是谁？请只基于我的真实 WhatsApp/Telegram/Gmail/LinkedIn 记录回答。")
        == "%张红%"
    )
    assert query_tokens("张红和王超是什么关系")[:2] == ["张红", "王超"]
    assert query_tokens("王超他儿子是谁")[0] == "王超"
    assert normalize_retrieval_pattern("王超他儿子是谁") == "%王超%"


def test_chinese_person_identity_question_needs_memory_graph_and_rag():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("张红是谁", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "relationship_query"
    assert route.needs_memory is True
    assert route.needs_memory_graph is True
    assert route.needs_memory_rag is True
    assert limits["memory_graph"] > 0
    assert limits["memory_rag"] > 0


def test_chinese_person_identity_with_channel_scope_is_not_misrouted_to_job_query():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context(
        "张红是谁？请只基于我的真实 WhatsApp/Telegram/Gmail/LinkedIn 记录回答。",
        ui_state=None,
    )
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "relationship_query"
    assert route.needs_source is True
    assert route.needs_memory_graph is True
    assert route.needs_memory_rag is True
    assert limits["source"] > 0
    assert limits["memory_graph"] > 0
    assert limits["memory_rag"] > 0


def test_chinese_relation_between_two_people_needs_memory_graph_and_rag():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("张红和王超是什么关系", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "relationship_query"
    assert route.needs_memory is True
    assert route.needs_memory_graph is True
    assert route.needs_memory_rag is True
    assert limits["memory_graph"] > 0
    assert limits["memory_rag"] > 0


def test_secret_phrase_question_needs_memory_layers():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("我的测试暗号是什么？", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "memory_query"
    assert route.needs_memory is True
    assert route.needs_memory_kv is True
    assert route.needs_memory_graph is True
    assert route.needs_memory_rag is True
    assert limits["memory"] > 0


def test_task_request_needs_tasks_and_memory():
    from app.chat_router import route_chat_context

    route = route_chat_context("帮我跟进这个客户报价并起草回复", ui_state=None)

    assert route.intent == "task_request"
    assert route.needs_tasks is True
    assert route.needs_memory is True


def test_narrow_agenda_question_uses_stable_fetch_window():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("根据刚才 WhatsApp 里 Alice 的安排，我什么时候去哪里见她？", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert limits["agenda"] >= 8
    assert limits["dialogue"] <= 24
    assert limits["memory"] == 0
    assert limits["tasks"] == 0


def test_answer_format_does_not_hide_agenda_or_memory_intent():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("根据刚才 WhatsApp 里 Alice 的安排，我什么时候去哪里见她？请一句话回答。", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent in {"agenda_query", "memory_query"}
    assert limits["agenda"] > 0
    assert limits["input_target_tokens"] <= 48000


def test_english_meeting_question_routes_to_agenda_even_when_url_encoded():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("When%20and%20where%20do%20I%20meet%20TestAlice%20from%20WhatsApp?", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "agenda_query"
    assert limits["agenda"] > 0
    assert limits["memory"] == 0


def test_task_request_keeps_broader_context_limits():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("帮我根据邮件和聊天记录跟进客户报价，起草回复并列出待办", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert limits["memory"] >= 12
    assert limits["tasks"] >= 6
    assert limits["dialogue"] >= 32


def test_implicit_reference_routes_to_memory_without_keyword():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("她后来回了吗？", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "memory_query"
    assert route.needs_dialogue is True
    assert route.needs_memory is True
    assert route.needs_memory_graph is True
    assert route.needs_memory_rag is True
    assert route.needs_timeline is True
    assert route.reason == "implicit_reference"
    assert limits["memory_graph"] > 0
    assert limits["memory_rag"] > 0
    assert limits["timeline"] > 0


def test_short_confirmation_with_pending_action_routes_to_action_confirmation():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context(
        "需要",
        ui_state={
            "pending_action": {
                "type": "quote_margin_check",
                "entities": ["RG_Alice", "PHONE_1"],
            }
        },
    )
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "action_confirmation"
    assert route.needs_dialogue is True
    assert route.needs_source is True
    assert route.needs_tasks is True
    assert route.needs_memory is True
    assert route.needs_memory_kv is True
    assert route.needs_memory_graph is True
    assert route.needs_memory_rag is True
    assert route.needs_timeline is True
    assert route.reason == "pending_action_confirmation"
    assert limits["tasks"] > 0
    assert limits["memory"] > 0


def test_informational_help_question_does_not_become_task_request():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("帮我解释一下 BM25 是什么", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "simple_chat"
    assert route.needs_memory is False
    assert route.needs_tasks is False
    assert limits["memory"] == 0
    assert limits["tasks"] == 0


def test_job_question_routes_to_job_query_with_resume_and_source_context():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context(
        "帮我根据这个 LinkedIn 后端岗位 JD 和我的简历写一段给 HR 的自我介绍",
        ui_state={"source_type": "linkedin_job", "current_source": "job_123"},
    )
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "job_query"
    assert route.needs_source is True
    assert route.needs_tasks is True
    assert route.needs_memory is True
    assert route.needs_memory_kv is True
    assert route.needs_memory_graph is True
    assert route.needs_memory_rag is True
    assert route.needs_timeline is False
    assert limits["source"] >= 4
    assert limits["memory_kv"] > 0
    assert limits["memory_graph"] > 0
    assert limits["memory_rag"] > 0
    assert {"type": "channel", "text": "LinkedIn", "confidence": 0.72} in route.entities
    assert {"type": "job", "text": "JD", "confidence": 0.72} in route.entities
    assert {"type": "person", "text": "HR", "confidence": 0.72} in route.entities


def test_english_linkedin_resume_job_request_routes_to_job_query():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context(
        "Recommend suitable jobs from LinkedIn based on my resume",
        ui_state=None,
    )
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "job_query"
    assert route.reason == "job_context"
    assert route.needs_source is True
    assert route.needs_memory is True
    assert route.needs_memory_kv is True
    assert route.needs_memory_graph is True
    assert route.needs_memory_rag is True
    assert limits["source"] >= 4
    assert limits["memory_kv"] > 0
    assert {"type": "channel", "text": "LinkedIn", "confidence": 0.72} in route.entities


def test_job_opportunity_request_routes_to_job_query_before_generic_task():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context("帮我找找看有没有适合我的工作机会", ui_state=None)
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "job_query"
    assert route.reason == "job_context"
    assert route.needs_source is True
    assert route.needs_tasks is True
    assert route.needs_memory is True
    assert limits["source"] >= 4
    assert limits["memory_kv"] > 0
    assert limits["memory_graph"] > 0
    assert limits["memory_rag"] > 0


def test_agenda_question_with_linkedin_as_source_name_stays_agenda_query():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context(
        "保利广场的安排缺什么信息？请只基于我的真实 WhatsApp/Telegram/Gmail/LinkedIn 记录回答，日期必须写绝对日期。",
        ui_state=None,
    )
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "agenda_query"
    assert route.needs_agenda is True
    assert route.needs_source is True
    assert route.needs_memory is True
    assert limits["agenda"] > 0
    assert limits["source"] > 0
    assert limits["memory_rag"] > 0


def test_route_decision_is_serializable_and_explains_memory_layers():
    from app.chat_router import route_chat_context

    route = route_chat_context("Alice 最近有回复吗？", ui_state=None)
    decision = route.to_decision()

    assert decision["intent"] == "relationship_query"
    assert decision["needs"]["dialogue"] is True
    assert decision["needs"]["memory_graph"] is True
    assert decision["needs"]["memory_rag"] is True
    assert decision["needs"]["timeline"] is True
    assert 0 < decision["confidence"] <= 1
    assert decision["reason"] == "relationship_reference"


def test_action_confirmation_fetch_limits_include_external_tool_state():
    from app.chat_router import context_fetch_limits, route_chat_context

    route = route_chat_context(
        "确认",
        ui_state={"pending_confirmation": {"tool": "gmail_send_email", "draft_id": "draft_1"}},
    )
    limits = context_fetch_limits(route, requested_limit=12)

    assert route.intent == "action_confirmation"
    assert route.needs_external_tool_state is True
    assert limits["external_tool_state"] > 0


def test_semantic_router_can_upgrade_default_route_to_memory_query():
    from app.chat_router import route_chat_context

    def fake_semantic_router(message, ui_state, deterministic_route):
        assert deterministic_route.intent == "simple_chat"
        return {
            "intent": "memory_query",
            "confidence": 0.81,
            "needs": {
                "dialogue": True,
                "source": True,
                "memory_kv": False,
                "memory_graph": True,
                "memory_rag": True,
                "timeline": True,
                "agenda": False,
                "tasks": False,
                "external_tool_state": False,
            },
            "entities": [{"type": "person", "text": "她", "confidence": 0.61}],
            "reason": "semantic_router_reference",
        }

    route = route_chat_context("有消息了吗", semantic_router=fake_semantic_router)

    assert route.intent == "memory_query"
    assert route.needs_memory is True
    assert route.needs_memory_graph is True
    assert route.needs_memory_rag is True
    assert route.needs_timeline is True
    assert route.confidence == 0.81
    assert route.reason == "semantic_router_reference"


def test_semantic_router_invalid_output_falls_back_to_deterministic_route():
    from app.chat_router import route_chat_context

    route = route_chat_context("有消息了吗", semantic_router=lambda *_args: {"intent": "nonsense"})

    assert route.intent == "simple_chat"
    assert route.reason == "default_simple"
