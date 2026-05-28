import os
import sys
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
    assert message["actions"][1]["risk"] == "external_execution"


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


def test_normalize_retrieval_pattern_removes_punctuation():
    from app.main import normalize_retrieval_pattern

    assert normalize_retrieval_pattern("What degree did I graduate with?") == "%what degree did i graduate with%"


def test_query_tokens_ignore_punctuation_and_short_words():
    from app.main import query_tokens

    assert query_tokens("Caroline mentor transgender teen") == ["caroline", "mentor", "transgender", "teen"]
    assert query_tokens("What is Caroline's identity?") == ["what", "caroline", "identity"]


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
