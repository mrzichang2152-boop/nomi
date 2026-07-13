import os
import sys
import asyncio
from pathlib import Path
from types import ModuleType


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_text_embedding_is_normalized_and_stable():
    from app.vector import VECTOR_DIMENSIONS, text_embedding, vector_literal

    first = text_embedding("Caroline likes pottery and camping")
    second = text_embedding("Caroline likes pottery and camping")

    assert first == second
    assert len(first) == VECTOR_DIMENSIONS
    assert abs(sum(value * value for value in first) - 1.0) < 0.00001
    assert vector_literal(first).startswith("[")


def test_embedding_status_reports_hash_fallback(monkeypatch):
    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    from app.vector import embedding_status

    assert embedding_status()["provider"] == "hash_fallback"


def test_embedding_status_reports_fastembed_when_configured(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    from app.vector import embedding_status

    status = embedding_status()

    assert status["provider"] == "fastembed"
    assert status["model"]


def test_fastembed_uses_configured_cache_dir(monkeypatch):
    from app import vector

    captured = {}

    class FakeTextEmbedding:
        def __init__(self, model_name, cache_dir=None):
            captured["model_name"] = model_name
            captured["cache_dir"] = cache_dir

        def embed(self, texts):
            yield [1.0] + [0.0] * (vector.VECTOR_DIMENSIONS - 1)

    fake_module = ModuleType("fastembed")
    fake_module.TextEmbedding = FakeTextEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", fake_module)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    monkeypatch.setenv("FASTEMBED_CACHE_DIR", "/models/fastembed")
    monkeypatch.setattr(vector, "_FASTEMBED_MODEL_CACHE", None)

    embedded = vector.fastembed_embedding("hello")

    assert embedded
    assert captured["cache_dir"] == "/models/fastembed"


def test_embedding_probe_reports_actual_provider(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    def fake_embedding(text):
        return [1.0] + [0.0] * 383, "test_provider"

    monkeypatch.setattr(main, "text_embedding_with_provider", fake_embedding)
    client = TestClient(main.app)

    response = client.get("/api/memory/embedding/probe", headers={"x-par-password": "secret"})

    assert response.status_code == 200
    assert response.json()["actual_provider"] == "test_provider"
    assert response.json()["dimensions"] == 384


def test_lifespan_does_not_block_or_fail_on_embedding_warmup(monkeypatch):
    from app import main

    for name in [
        "ensure_collector_settings_schema",
        "ensure_event_private_storage_schema",
        "ensure_private_event_gateway_schema",
        "ensure_assistant_identity_schema",
        "ensure_memory_governance_schema",
        "ensure_assistant_context_schema",
        "ensure_attachment_schema",
        "ensure_curated_assistant_memory_schema",
        "ensure_proactive_feedback_schema",
        "ensure_task_routing_schema",
        "ensure_task_orchestrator_schema",
        "ensure_long_tail_agent_schema",
        "ensure_tool_registry_schema",
        "ensure_workflow_distillation_schema",
        "ensure_openclaw_execution_schema",
        "ensure_delegated_automation_schema",
        "ensure_model_gateway_schema",
        "ensure_ios_live_activity_schema",
    ]:
        monkeypatch.setattr(main, name, lambda: None)
    monkeypatch.setattr(main, "ENABLE_DAILY_MAINTENANCE", False)
    monkeypatch.setattr(main, "ENABLE_OPENCLAW_JOB_RUNNER", False)
    monkeypatch.setattr(main, "ENABLE_LONG_TAIL_RECOVERY_RUNNER", False)

    def failing_embedding(text):
        raise RuntimeError("warmup backend unavailable")

    monkeypatch.setattr(main, "text_embedding_with_provider", failing_embedding)

    async def enter_lifespan():
        async with main.lifespan(main.app):
            return "entered"

    assert asyncio.run(enter_lifespan()) == "entered"


def test_heuristic_rerank_prefers_exact_fact_match():
    from app.main import rerank_context

    ranked = rerank_context(
        "What did Caroline research?",
        [
            {"layer": "vector_recall", "summary": "Melanie likes pottery"},
            {"layer": "entity_graph", "subject": "Caroline", "predicate": "researched", "object": "Adoption agencies"},
        ],
    )

    assert ranked[0]["layer"] == "entity_graph"


def test_heuristic_rerank_normalizes_apostrophes_for_graph():
    from app.main import rerank_context

    ranked = rerank_context(
        "What is Caroline's identity?",
        [
            {"layer": "semantic_memory", "content": {"summary": "What is Caroline's identity? Transgender woman"}, "confidence": 0.78},
            {"layer": "entity_graph", "subject": "what is caroline s identity", "predicate": "benchmark_answer", "object": "transgender woman", "confidence": 0.84},
        ],
    )

    assert ranked[0]["layer"] == "entity_graph"


def test_suggestions_endpoint_requires_password(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    client = TestClient(main.app)
    response = client.get("/api/suggestions")

    assert response.status_code == 401


def test_suggestions_endpoint_prefetches_past_filtered_noise(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from datetime import datetime, timezone

    from app import main

    created_at = datetime(2026, 6, 29, 8, 0, tzinfo=timezone.utc)
    rows = []
    for index in range(8):
        rows.append(
            (
                f"noise-{index}",
                f"event-noise-{index}",
                "跟进近期安排",
                "这条信息可能需要跟进：Gmail: Secure, AI-Powered Email for Everyone | Google Workspace。",
                0.95 - index * 0.01,
                "open",
                {
                    "source": "focus",
                    "event_type": "deep_focus",
                    "dedupe_key": f"noise:{index}",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                },
                created_at,
                created_at,
            )
        )
    rows.append(
        (
            "real-whatsapp",
            "event-whatsapp",
            "跟进近期安排",
            "这条信息可能需要跟进：NOMI_REG_WA_0629 明天15:30人民广场见，带合同。",
            0.2,
            "open",
            {
                "source": "whatsapp",
                "event_type": "whatsapp_message",
                "dedupe_key": "social_followup:whatsapp:NOMI_REG_WA_0629",
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
            created_at,
            created_at,
        )
    )

    class Cursor:
        def __init__(self, result_rows):
            self.result_rows = result_rows

        def fetchall(self):
            return self.result_rows

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=()):
            limit = int(params[0])
            return Cursor(rows[:limit])

    monkeypatch.setattr(main, "db", lambda: Conn())

    suggestions = main.suggestions(x_par_password="secret", limit=1)

    assert [item["id"] for item in suggestions] == ["real-whatsapp"]


def test_filter_open_suggestions_removes_expired_and_deduplicates_by_metadata_key():
    from app.main import filter_open_suggestions

    rows = [
        {
            "id": "1",
            "priority": 0.8,
            "metadata": {"dedupe_key": "email_todo:gmail:a", "expires_at": "2099-01-01T00:00:00+00:00"},
        },
        {
            "id": "2",
            "priority": 0.7,
            "metadata": {"dedupe_key": "email_todo:gmail:a", "expires_at": "2099-01-01T00:00:00+00:00"},
        },
        {
            "id": "3",
            "priority": 0.9,
            "metadata": {"dedupe_key": "calendar:schedule:b", "expires_at": "2000-01-01T00:00:00+00:00"},
        },
    ]

    filtered = filter_open_suggestions(rows)

    assert [item["id"] for item in filtered] == ["1"]


def test_filter_open_suggestions_suppresses_low_value_focus_page_titles():
    from app.main import filter_open_suggestions

    rows = [
        {
            "id": "focus-page-title",
            "title": "跟进近期安排",
            "body": "这条信息可能需要跟进：Gmail: Secure, AI-Powered Email for Everyone | Google Workspace。",
            "priority": 0.9,
            "metadata": {
                "source": "focus",
                "event_type": "deep_focus",
                "dedupe_key": "social_followup:focus:gmail",
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        },
        {
            "id": "low-value-email",
            "title": "处理邮件待办",
            "body": "这封邮件可能需要处理：Example AI follow-up。",
            "priority": 0.85,
            "metadata": {
                "source": "gmail",
                "event_type": "gmail_message",
                "dedupe_key": "email_todo:gmail:low",
                "expires_at": "2099-01-01T00:00:00+00:00",
                "entities": {"primary_label": "low_value", "labels": ["low_value"]},
            },
        },
        {
            "id": "real-whatsapp",
            "title": "跟进见面安排",
            "body": "RG_Alice 约了 2026-06-14 10:00 在武康路见。",
            "priority": 0.8,
            "metadata": {
                "source": "whatsapp",
                "event_type": "whatsapp_message",
                "dedupe_key": "social_followup:whatsapp:alice",
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        },
    ]

    filtered = filter_open_suggestions(rows)

    assert [item["id"] for item in filtered] == ["real-whatsapp"]


def test_filter_open_suggestions_suppresses_gmail_notification_count_noise():
    from app.main import filter_open_suggestions

    rows = [
        {
            "id": "gmail-notification-count-noise",
            "title": "处理邮件待办",
            "body": "这封邮件可能需要处理：0 notifications total",
            "priority": 0.9,
            "metadata": {
                "source": "gmail",
                "event_type": "gmail_message",
                "dedupe_key": "email_todo:gmail:notification-count",
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        },
        {
            "id": "real-email-todo",
            "title": "处理邮件待办",
            "body": "HR 发来后端架构师面试确认，需要今晚前回复。",
            "priority": 0.8,
            "metadata": {
                "source": "gmail",
                "event_type": "gmail_message",
                "dedupe_key": "email_todo:gmail:real",
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        },
    ]

    filtered = filter_open_suggestions(rows)

    assert [item["id"] for item in filtered] == ["real-email-todo"]


def test_filter_open_suggestions_suppresses_gmail_receipts_marketing_and_policy_noise():
    from app.main import filter_open_suggestions

    rows = [
        {
            "id": "gmail-receipt",
            "title": "处理邮件待办",
            "body": "Apple 收据：Your receipt from Apple, total $0.99, billed to your card.",
            "priority": 0.95,
            "metadata": {
                "source": "gmail",
                "event_type": "gmail_message_snapshot",
                "dedupe_key": "email_todo:gmail:receipt",
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        },
        {
            "id": "gmail-marketing",
            "title": "可能值得关注",
            "body": "Limited time offer: upgrade today and save 30%. Unsubscribe at any time.",
            "priority": 0.92,
            "metadata": {
                "source": "gmail",
                "event_type": "gmail_message_snapshot",
                "dedupe_key": "email_todo:gmail:marketing",
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        },
        {
            "id": "gmail-privacy-policy",
            "title": "隐私政策更新",
            "body": "We updated our Privacy Policy and Terms of Service. No action is required.",
            "priority": 0.91,
            "metadata": {
                "source": "gmail",
                "event_type": "gmail_message_snapshot",
                "dedupe_key": "email_todo:gmail:privacy",
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        },
        {
            "id": "gmail-real-meeting",
            "title": "会议需要确认",
            "body": "Lin 约你 2026-07-02 14:00 进行后端岗位技术面，需要今天回复是否确认。",
            "priority": 0.85,
            "metadata": {
                "source": "gmail",
                "event_type": "gmail_message_snapshot",
                "dedupe_key": "email_todo:gmail:real-meeting",
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        },
    ]

    filtered = filter_open_suggestions(rows)

    assert [item["id"] for item in filtered] == ["gmail-real-meeting"]


def test_filter_open_suggestions_suppresses_real_world_gmail_and_telegram_noise():
    from app.main import filter_open_suggestions

    rows = [
        {
            "id": "gmail-openai-marketing-cn",
            "title": "确认取消安排",
            "body": "让您提供的服务更清晰。OpenAI 1455 3rd Street San Francisco。取消订阅 隐私 · 条款",
            "priority": 0.9,
            "metadata": {"source": "gmail", "event_type": "gmail_message_snapshot", "expires_at": "2099-01-01T00:00:00+00:00"},
        },
        {
            "id": "gmail-linkedin-notification",
            "title": "处理邮件待办",
            "body": "You have 2 new messages View messages:https://www.linkedin.com/comm/messaging/",
            "priority": 0.9,
            "metadata": {"source": "gmail", "event_type": "gmail_message_snapshot", "expires_at": "2099-01-01T00:00:00+00:00"},
        },
        {
            "id": "gmail-payment-receipt",
            "title": "处理邮件待办",
            "body": "订单支付成功：https://www.henghost.com/ 客户名称：请更新姓名",
            "priority": 0.9,
            "metadata": {"source": "gmail", "event_type": "gmail_message_snapshot", "expires_at": "2099-01-01T00:00:00+00:00"},
        },
        {
            "id": "telegram-security-spam",
            "title": "处理消息待办",
            "body": "官方安全中心提醒您！请尽快前往安全中心进行账号验证：https://www.tregsafety.com Telegram Web",
            "priority": 0.9,
            "metadata": {"source": "telegram", "event_type": "telegram_visible_snapshot", "expires_at": "2099-01-01T00:00:00+00:00"},
        },
        {
            "id": "real-whatsapp-meeting",
            "title": "会议安排",
            "body": "NOMI_REG_WA_0629 2026-07-03 15:30 人民广场见，带合同。",
            "priority": 0.8,
            "metadata": {"source": "whatsapp", "event_type": "whatsapp_message_snapshot", "expires_at": "2099-01-01T00:00:00+00:00"},
        },
    ]

    filtered = filter_open_suggestions(rows)

    assert [item["id"] for item in filtered] == ["real-whatsapp-meeting"]


def test_filter_open_suggestions_suppresses_nomi_chat_question_noise():
    from app.main import filter_open_suggestions

    rows = [
        {
            "id": "chat-question",
            "title": "跟进近期安排",
            "body": "这条信息可能需要跟进：user said to Nomi: NOMI_REG_WA_0629 这条 WhatsApp 里约的人民广场会面具体是什么时候？",
            "priority": 0.6,
            "metadata": {
                "source": "nomi_chat",
                "event_type": "user_message",
                "dedupe_key": "social_followup:nomi_chat:question",
                "expires_at": "2099-01-01T00:00:00+00:00",
                "entities": {"client_type": "regression", "primary_label": "appointment"},
            },
        },
        {
            "id": "chat-question-model-summary",
            "title": "可能值得关注",
            "body": "用户询问关于保利广场的安排缺失了哪些信息并要求提供来源。",
            "priority": 0.7,
            "metadata": {
                "source": "nomi_chat",
                "event_type": "user_message",
                "dedupe_key": "attention:nomi_chat:model-summary",
                "expires_at": "2099-01-01T00:00:00+00:00",
                "entities": {"client_type": "regression", "primary_label": "todo"},
            },
        },
        {
            "id": "chat-dialogue-batch",
            "title": "跟进近期安排",
            "body": "这条信息可能需要跟进：Nomi 对话批次摘要：用户关注人民广场会面。",
            "priority": 0.8,
            "metadata": {
                "source": "nomi_chat",
                "event_type": "dialogue_batch",
                "dedupe_key": "social_followup:nomi_chat:dialogue-batch",
                "expires_at": "2099-01-01T00:00:00+00:00",
                "entities": {"client_type": "regression", "primary_label": "todo"},
            },
        },
        {
            "id": "whatsapp-title-badge",
            "title": "跟进近期安排",
            "body": "这条信息可能需要跟进：(2) WhatsApp。",
            "priority": 0.8,
            "metadata": {
                "source": "whatsapp",
                "event_type": "whatsapp_snapshot",
                "dedupe_key": "social_followup:whatsapp:title-badge",
                "expires_at": "2099-01-01T00:00:00+00:00",
                "entities": {"primary_label": "appointment", "labels": ["appointment"]},
            },
        },
        {
            "id": "real-whatsapp-meeting",
            "title": "跟进近期安排",
            "body": "这条信息可能需要跟进：NOMI_REG_WA_0629 明天15:30人民广场见，带合同。",
            "priority": 0.2,
            "metadata": {
                "source": "whatsapp",
                "event_type": "whatsapp_message",
                "dedupe_key": "social_followup:whatsapp:meeting",
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        },
    ]

    filtered = filter_open_suggestions(rows)

    assert [item["id"] for item in filtered] == ["real-whatsapp-meeting"]


def test_suggestion_to_realtime_message_preserves_source_and_body():
    from app.main import suggestion_to_realtime_message

    message = suggestion_to_realtime_message(
        {
            "id": "s1",
            "source_event_id": "e1",
            "title": "处理邮件待办",
            "body": "新订单需要尽快完成付款。",
            "priority": 0.88,
            "metadata": {"suggestion_type": "email_todo", "source": "gmail"},
            "created_at": "2026-05-27T09:00:00+00:00",
        }
    )

    assert message["type"] == "proactive_message"
    assert message["id"] == "s1"
    assert message["title"] == "处理邮件待办"
    assert message["body"] == "新订单需要尽快完成付款。"
    assert message["source"] == "gmail"
    assert message["open_view"] == "chat"


def test_suggestion_to_realtime_message_exposes_action_cards_top_level():
    from app.main import suggestion_to_realtime_message

    message = suggestion_to_realtime_message(
        {
            "id": "s1",
            "source_event_id": "e1",
            "title": "跟进近期安排",
            "body": "Alex 约你周日去武康路见面。",
            "priority": 0.88,
            "metadata": {
                "suggestion_type": "social_followup",
                "source": "whatsapp",
                "actions": [
                    {"id": "route_lookup", "label": "查路线", "risk": "read_only"},
                    {"id": "ride_prepare", "label": "帮我打车", "risk": "external_execution"},
                    {"id": "snooze", "label": "稍后提醒", "risk": "local_only"},
                ],
            },
            "created_at": "2026-05-27T09:00:00+00:00",
        }
    )

    assert [item["label"] for item in message["actions"]] == ["查路线", "帮我打车", "稍后提醒"]


def test_suggestion_to_realtime_message_filters_placeholder_job_links():
    from app.main import suggestion_to_realtime_message

    message = suggestion_to_realtime_message(
        {
            "id": "s-job-placeholder",
            "source_event_id": "e-job-placeholder",
            "title": "发现高匹配岗位",
            "body": (
                "推荐岗位：Senior AI Workflow Product Manager @ Example AI\n"
                "链接：https://boards.greenhouse.io/exampleai/jobs/ai-workflow-pm"
            ),
            "priority": 0.82,
            "metadata": {
                "suggestion_type": "career_job_recommendation",
                "source": "career_job_recommendation_pipeline",
                "actions": [
                    {
                        "id": "open_job_url",
                        "label": "打开岗位链接",
                        "risk": "read_only",
                        "url": "https://boards.greenhouse.io/exampleai/jobs/ai-workflow-pm",
                    },
                    {
                        "id": "add_to_career_board",
                        "label": "加入求职看板",
                        "risk": "write",
                        "job_id": "job-placeholder",
                    },
                ],
                "recommended_jobs": [
                    {
                        "job_id": "job-placeholder",
                        "url": "https://boards.greenhouse.io/exampleai/jobs/ai-workflow-pm",
                    }
                ],
            },
            "created_at": "2026-06-24T09:00:00+08:00",
        }
    )

    assert "https://boards.greenhouse.io/exampleai/jobs/ai-workflow-pm" not in message["body"]
    assert "链接待验证" in message["body"]
    assert [item["label"] for item in message["actions"]] == ["加入求职看板"]
    assert message["metadata"]["recommended_jobs"][0]["url"] == ""
    assert message["metadata"]["recommended_jobs"][0]["url_validation_status"] == "placeholder_or_test_url"


def test_build_reasoning_context_layers_sources():
    from app.main import build_reasoning_context

    context = build_reasoning_context(
        state_rows=[("active_topic", {"summary": "Tokyo trip"}, None)],
        timeline_rows=[("2026-05-26", "Planned Tokyo hotels", [])],
        semantic_rows=[("interest", {"summary": "Likes quiet hotels"}, 0.9, [])],
        fact_rows=[("user", "research_interest", "Tokyo hotels", 0.8, [])],
        bm25_rows=[],
        vector_rows=[("2026-05-26T00:00:00+00:00", "search", "search", {"query": "Tokyo hotel"}, "Tokyo hotel search", "research_interest", 0.6)],
    )

    assert [item["layer"] for item in context] == [
        "working_memory",
        "timeline",
        "semantic_memory",
        "entity_graph",
        "vector_recall",
    ]


def test_retrieval_plan_weights_relationship_questions_toward_graph():
    from app.main import plan_retrieval

    plan = plan_retrieval("Alex 和我是什么关系？")

    assert plan.graph_limit > plan.vector_limit
    assert plan.state_limit >= 1


def test_retrieval_plan_weights_vague_recall_toward_rag():
    from app.main import plan_retrieval

    plan = plan_retrieval("我之前看过的那个东京酒店")

    assert plan.vector_limit > plan.graph_limit
    assert plan.timeline_limit >= 1


def test_explain_retrieval_plan_reports_layer_reasons():
    from app.main import explain_retrieval_plan, plan_retrieval

    explanation = explain_retrieval_plan("Alex 和我是什么关系？", plan_retrieval("Alex 和我是什么关系？"))

    assert explanation["query"] == "Alex 和我是什么关系？"
    assert "entity_graph" in explanation["priority_layers"]
    assert any("关系" in reason for reason in explanation["reasons"])
    assert explanation["limits"]["graph_limit"] > 0


def test_graph_query_filters_supernodes():
    from app.main import graph_fact_sql

    sql = graph_fact_sql()

    assert "entity_degree" in sql
    assert "<=" in sql


def test_consolidation_query_excludes_synthetic_sources():
    from app.main import consolidation_fact_sql

    sql = consolidation_fact_sql()

    assert "longmemeval_conversation" in sql
    assert "locomo_conversation" in sql
    assert "locomo_seed" in sql


def test_consolidation_query_excludes_linkedin_browser_snapshots():
    from app.main import consolidation_fact_sql

    sql = consolidation_fact_sql()

    assert "metadata#>>'{entities,source}'" in sql
    assert "= 'linkedin'" in sql
    assert "linkedin_visible_snapshot" in sql
    assert "linkedin_contact_search_results" in sql
    assert "linkedin_job_search_results" in sql
    assert "linkedin_career_prompt" in sql
    assert "primary_label" in sql
    assert "low_value" in sql
    assert "COALESCE(metadata#>>'{entities,primary_label}', '') NOT IN ('low_value', 'ordinary_chat')" in sql
    assert "metadata#>'{entities,labels}'" in sql
    assert "? 'ordinary_chat'" in sql
    assert "visible_snapshot|login_snapshot" in sql
    assert "predicate NOT IN ('generic_event', 'notification', 'browse_feed', 'information_consumption')" in sql
    assert "your receipt from" in sql
    assert "newsletter" in sql
    assert "linkedin\\.com/comm/messaging" in sql
    assert "消息和通话已进行端到端加密" in sql


def test_normalize_retrieval_pattern_removes_punctuation():
    from app.main import normalize_retrieval_pattern

    assert normalize_retrieval_pattern("What degree did I graduate with?") == "%what degree did i graduate with%"


def test_query_tokens_ignore_punctuation_and_short_words():
    from app.main import query_tokens

    assert query_tokens("Caroline mentor transgender teen") == ["caroline", "mentor", "transgender", "teen"]
    assert query_tokens("What is Caroline's identity?") == ["what", "caroline", "identity"]


def test_chinese_query_tokens_extract_retrieval_keywords():
    from app.main import normalize_retrieval_pattern, query_tokens, token_patterns

    secret_tokens = query_tokens("我的测试暗号是什么？")
    quote_tokens = query_tokens("报价单需要什么时候前发？要注意什么？")

    assert "测试暗号" in secret_tokens
    assert "报价单" in quote_tokens
    assert "%测试暗号%" in token_patterns("我的测试暗号是什么？")
    assert "%报价单%" in token_patterns("报价单需要什么时候前发？要注意什么？")
    assert normalize_retrieval_pattern("我的测试暗号是什么？") == "%测试暗号%"
    assert normalize_retrieval_pattern("报价单需要什么时候前发？要注意什么？") == "%报价单%"


def test_bm25_layer_is_in_reasoning_context():
    from app.main import build_reasoning_context

    context = build_reasoning_context(
        state_rows=[],
        timeline_rows=[],
        semantic_rows=[],
        fact_rows=[],
        bm25_rows=[("2026-05-26T00:00:00+00:00", "gmail", "email", {"subject": "Visa appointment"}, "Visa appointment tomorrow", "task", 0.8, 0.42)],
        vector_rows=[],
    )

    assert context[0]["layer"] == "bm25_recall"
    assert context[0]["rank"] == 0.42


def test_build_personal_search_response_groups_layers_and_explains_sources():
    from app.main import build_personal_search_response

    response = build_personal_search_response(
        "东京酒店",
        [
            {
                "layer": "vector_recall",
                "summary": "用户搜索过东京酒店",
                "source": "search",
                "event_type": "search",
                "time": "2026-05-26T00:00:00+00:00",
            },
            {
                "layer": "entity_graph",
                "subject": "user",
                "predicate": "research_interest",
                "object": "Tokyo hotels",
                "confidence": 0.8,
            },
        ],
    )

    assert response["answer"] == "找到 2 条相关个人记忆。"
    assert response["confidence"] >= 0.7
    assert response["layers"] == ["vector_recall", "entity_graph"]
    assert response["sources"][0]["explanation"] == "向量召回：语义相近的历史内容"
    assert response["sources"][1]["explanation"] == "知识图谱：实体、关系或事实匹配"


def test_decorate_context_sources_adds_explanations_without_mutating_content():
    from app.main import decorate_context_sources

    decorated = decorate_context_sources(
        [{"layer": "entity_graph", "subject": "user", "predicate": "preference", "object": "quiet hotels"}]
    )

    assert decorated[0]["layer"] == "entity_graph"
    assert decorated[0]["explanation"] == "知识图谱：实体、关系或事实匹配"
    assert decorated[0]["subject"] == "user"


def test_infer_memory_access_policy_detects_reply_target():
    from app.main import infer_memory_access_policy

    policy = infer_memory_access_policy("帮我回复 Alice，语气自然一点")

    assert policy["output_context"] == "reply_to_contact"
    assert "alice" in policy["target_entities"]


def test_memory_access_policy_blocks_third_party_private_negative_opinion_in_reply():
    from app.main import filter_context_by_memory_access_policy, infer_memory_access_policy

    policy = infer_memory_access_policy("帮我回复 Alice")
    context = [
        {
            "layer": "vector_recall",
            "source": "whatsapp",
            "raw_data": {"chat_name": "Bob", "sender": "Bob", "message": "Alice is unreliable and annoying."},
            "summary": "Bob 私下吐槽 Alice 不靠谱。",
            "metadata": {
                "memory_scope": {
                    "conversation_label": "Bob",
                    "speaker": "Bob",
                    "related_entities": ["Bob", "Alice"],
                    "sensitivity": "third_party_private_negative",
                    "not_usable_contexts": ["reply_to_contact"],
                }
            },
        },
        {
            "layer": "vector_recall",
            "source": "whatsapp",
            "raw_data": {"chat_name": "Alice", "sender": "Alice", "message": "Friday 8 works for dinner."},
            "summary": "Alice 说周五八点可以吃饭。",
            "metadata": {
                "memory_scope": {
                    "conversation_label": "Alice",
                    "speaker": "Alice",
                    "related_entities": ["Alice"],
                    "sensitivity": "normal",
                }
            },
        },
    ]

    filtered = filter_context_by_memory_access_policy(context, policy)

    assert len(filtered) == 1
    assert filtered[0]["raw_data"]["chat_name"] == "Alice"


def test_memory_access_policy_allows_private_analysis_when_user_explicitly_asks():
    from app.main import filter_context_by_memory_access_policy, infer_memory_access_policy

    policy = infer_memory_access_policy("帮我分析 Alice 和 Bob 的关系")
    context = [
        {
            "layer": "entity_graph",
            "subject": "bob",
            "predicate": "negative_opinion_about",
            "object": "alice",
            "metadata": {
                "memory_scope": {
                    "conversation_label": "Bob",
                    "speaker": "Bob",
                    "related_entities": ["Bob", "Alice"],
                    "sensitivity": "third_party_private_negative",
                    "usable_contexts": ["private_analysis"],
                }
            },
        }
    ]

    filtered = filter_context_by_memory_access_policy(context, policy)

    assert filtered == context


def test_consolidate_day_summarizes_fact_rows():
    from app.main import summarize_daily_facts

    summary = summarize_daily_facts(
        [
            ("Alex", "invited_user_to", "Friday dinner", 0.8, []),
            ("User", "research_interest", "Tokyo hotels", 0.6, []),
        ]
    )

    assert "Alex: invited_user_to Friday dinner" in summary
    assert "User: research_interest Tokyo hotels" in summary


def test_consolidate_summary_deduplicates_and_groups_by_subject():
    from app.main import summarize_daily_facts

    summary = summarize_daily_facts(
        [
            ("Caroline", "benchmark_answer", "Transgender woman", 0.9, []),
            ("Caroline", "benchmark_answer", "Transgender woman", 0.8, []),
            ("Caroline", "conversation_memory", "Caroline mentors a transgender teen", 0.68, []),
            ("Melanie", "conversation_memory", "Melanie plans camping in June", 0.7, []),
        ]
    )

    assert summary.count("Transgender woman") == 1
    assert "Caroline:" in summary
    assert "Melanie:" in summary
    assert "mentors a transgender teen" in summary


def test_consolidate_summary_uses_readable_phrases():
    from app.main import summarize_daily_facts

    summary = summarize_daily_facts(
        [
            ("Caroline", "conversation_memory", "Caroline said: I mentor a transgender teen just like me.", 0.68, []),
            ("what is caroline s identity", "benchmark_answer", "transgender woman", 0.84, []),
        ]
    )

    assert "Caroline: said: I mentor a transgender teen" in summary
    assert "benchmark_answer" not in summary
    assert "answer: transgender woman" in summary


def test_consolidate_summary_is_structured_daily_digest():
    from app.main import summarize_daily_facts

    summary = summarize_daily_facts(
        [
            ("user", "preference", "quiet hotels", 0.82, []),
            ("gmail", "payment_reminder", "new order needs payment", 0.8, []),
            ("calendar", "schedule", "09:30 product review", 0.9, []),
        ]
    )

    assert "今日重点：" in summary
    assert "待跟进：" in summary
    assert "稳定记忆：" in summary
    assert "product review" in summary
    assert "quiet hotels" in summary


def test_consolidate_day_writes_stable_semantic_memory_from_daily_summary():
    from app.main import consolidate_day

    executed = []

    class Cursor:
        def __init__(self, rows=None):
            self.rows = rows or []
            self.rowcount = 1

        def fetchall(self):
            return self.rows

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            if "FROM facts" in sql:
                return Cursor(
                    [
                        (
                            "user",
                            "preference",
                            "quiet hotels",
                            0.82,
                            ["11111111-1111-1111-1111-111111111111"],
                        )
                    ]
                )
            return Cursor()

    result = consolidate_day(Conn(), "2026-05-26")

    semantic_sql, semantic_params = next(item for item in executed if "INSERT INTO semantic_memory" in item[0])
    assert result["fact_count"] == 1
    assert "daily_consolidation" in semantic_params
    assert "quiet hotels" in semantic_params[2]
    assert "consolidated_daily" in semantic_params[2]


def test_pruned_raw_data_keeps_summary_and_removes_original_private_payload():
    from app.main import build_pruned_raw_data

    pruned = build_pruned_raw_data(
        source="gmail",
        event_type="gmail_message_preview",
        summary="支付宝订单已经完成付款。",
        reason="older_than_raw_retention",
    )

    assert pruned == {
        "pruned": True,
        "source": "gmail",
        "event_type": "gmail_message_preview",
        "reason": "older_than_raw_retention",
        "semantic_summary": "支付宝订单已经完成付款。",
    }
    assert "订单号" not in str(pruned)


def test_prune_raw_events_updates_low_value_and_expired_payloads():
    from app.main import prune_raw_events

    executed = []

    class Cursor:
        def __init__(self, rowcount):
            self.rowcount = rowcount

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            if "importance <" in sql:
                return Cursor(3)
            if "older_than_raw_retention" in sql:
                return Cursor(5)
            return Cursor(0)

    result = prune_raw_events(Conn(), raw_retention_days=30, low_value_retention_days=7)

    assert result == {
        "low_value_pruned": 3,
        "expired_pruned": 5,
        "raw_retention_days": 30,
        "low_value_retention_days": 7,
    }
    assert len(executed) == 2


def test_run_daily_memory_maintenance_combines_consolidation_and_pruning(monkeypatch):
    from app import main

    calls = []

    def fake_consolidate(conn, date_text):
        calls.append(("consolidate", date_text))
        return {"date": date_text, "fact_count": 2, "summary": "User: paid cloud server invoice"}

    def fake_prune(conn, raw_retention_days, low_value_retention_days):
        calls.append(("prune", raw_retention_days, low_value_retention_days))
        return {
            "low_value_pruned": 1,
            "expired_pruned": 2,
            "raw_retention_days": raw_retention_days,
            "low_value_retention_days": low_value_retention_days,
        }

    monkeypatch.setattr(main, "consolidate_day", fake_consolidate)
    monkeypatch.setattr(main, "prune_raw_events", fake_prune)

    class Conn:
        pass

    result = main.run_daily_memory_maintenance(
        Conn(),
        date_text="2026-05-25",
        raw_retention_days=30,
        low_value_retention_days=7,
    )

    assert result["date"] == "2026-05-25"
    assert result["consolidation"]["summary"] == "User: paid cloud server invoice"
    assert result["raw_cleanup"]["expired_pruned"] == 2
    assert calls == [("consolidate", "2026-05-25"), ("prune", 30, 7)]
