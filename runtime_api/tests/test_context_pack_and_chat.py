import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_schema_bootstrap_creates_assistant_context_tables(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed = []

    class Cursor:
        pass

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            executed.append(" ".join(sql.split()))
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())

    main.ensure_assistant_context_schema()

    combined = "\n".join(executed)
    assert "CREATE TABLE IF NOT EXISTS assistant_conversations" in combined
    assert "CREATE TABLE IF NOT EXISTS assistant_turns" in combined
    assert "CREATE TABLE IF NOT EXISTS context_snapshots" in combined
    assert "CREATE TABLE IF NOT EXISTS context_route_traces" in combined
    assert "assistant_turns_conversation_idx" in combined
    assert "context_snapshots_event_idx" in combined
    assert "context_route_traces_conversation_idx" in combined


def test_schema_bootstrap_creates_model_gateway_tables(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed = []

    class Cursor:
        pass

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            executed.append(" ".join(sql.split()))
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())

    main.ensure_model_gateway_schema()

    combined = "\n".join(executed)
    assert "CREATE TABLE IF NOT EXISTS model_providers" in combined
    assert "CREATE TABLE IF NOT EXISTS model_health_checks" in combined
    assert "CREATE TABLE IF NOT EXISTS model_request_traces" in combined
    assert "model_request_traces_provider_idx" in combined


def test_schema_bootstrap_creates_curated_assistant_memory_tables(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed = []

    class Cursor:
        pass

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            executed.append(" ".join(sql.split()))
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())

    main.ensure_curated_assistant_memory_schema()

    combined = "\n".join(executed)
    assert "CREATE TABLE IF NOT EXISTS assistant_profile_memories" in combined
    assert "CREATE TABLE IF NOT EXISTS conversation_summaries" in combined
    assert "CREATE TABLE IF NOT EXISTS conversation_session_index" in combined


def test_schema_bootstrap_creates_private_event_gateway_tables(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed = []

    class Cursor:
        pass

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            executed.append(" ".join(sql.split()))
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())

    main.ensure_private_event_gateway_schema()

    combined = "\n".join(executed)
    assert "CREATE TABLE IF NOT EXISTS source_events" in combined
    assert "CREATE TABLE IF NOT EXISTS source_cursors" in combined
    assert "source_events_dedupe_idx" in combined


def test_literal_identifiers_extract_invoice_and_masked_phone_tokens(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    identifiers = main.extract_literal_identifiers(
        "帮我处理 INV-RG-1001 和 PHONE_1 报价，但不要付款，只告诉我找到了什么。"
    )

    assert identifiers == ["INV-RG-1001", "PHONE_1"]


def test_cjk_retrieval_tokens_keep_business_entities_and_places(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    assert "保险" in main.query_tokens("我买保险最关心什么")
    assert main.normalize_retrieval_pattern("我买保险最关心什么") == "%保险%"
    assert "保单" in main.query_tokens("明天3点半提醒我看一下保单")
    assert "保利广场" in main.query_tokens("保利广场的安排缺什么信息")
    assert main.normalize_retrieval_pattern("保利广场的安排缺什么信息") == "%保利广场%"


def test_retrieve_context_prioritizes_literal_identifier_matches(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed: list[tuple[str, tuple]] = []

    class Cursor:
        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchall(self):
            return self.rows

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            compact = " ".join(sql.split())
            executed.append((compact, params))
            if "literal_identifier_recall" in compact:
                return Cursor(
                    [
                        (
                            "2026-06-16T08:00:00+00:00",
                            "gmail",
                            "email",
                            {
                                "subject": "Invoice INV-RG-1001 due",
                                "body": "Invoice INV-RG-1001 for AMOUNT_1 is due next Tuesday.",
                            },
                            "Invoice INV-RG-1001 for AMOUNT_1 is due next Tuesday.",
                            "task_request",
                            0.8,
                            {"memory_scope": {"usable_contexts": ["personal_search"], "sensitivity": "normal"}},
                            "INV-RG-1001",
                        )
                    ]
                )
            return Cursor([])

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "text_embedding", lambda query: [0.0] * 384)

    context = main.retrieve_context("帮我处理 INV-RG-1001，但不要付款，只告诉我你找到了什么。", 4)

    assert context[0]["layer"] == "literal_identifier_recall"
    assert context[0]["matched_identifier"] == "INV-RG-1001"
    assert "INV-RG-1001" in str(context[0]["raw_data"])
    assert any("literal_identifier_recall" in sql for sql, _ in executed)


def test_retrieve_context_releases_minimal_private_invoice_fields_for_read_only_literal_query(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    encrypted_private = main.encrypt_private_raw_data(
        {
            "subject": "Invoice INV-LIVE-1601 due",
            "body": "Invoice INV-LIVE-1601 for 1200 USD is due next Tuesday. Do not pay without confirmation.",
            "from": "billing@example.com",
        }
    )

    class Cursor:
        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchall(self):
            return self.rows

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            compact = " ".join(sql.split())
            if "literal_identifier_recall" in compact:
                return Cursor(
                    [
                        (
                            "2026-06-16T08:00:00+00:00",
                            "gmail",
                            "email",
                            {
                                "subject": "Invoice INV-LIVE-1601 due",
                                "body": "Invoice INV-LIVE-1601 for AMOUNT_1 is due next Tuesday.",
                                "sensitive": True,
                                "sensitive_reasons": ["amount", "email"],
                            },
                            "Invoice INV-LIVE-1601 for AMOUNT_1 is due next Tuesday.",
                            "task_request",
                            0.8,
                            {"memory_scope": {"usable_contexts": ["personal_search"], "sensitivity": "normal"}},
                            "INV-LIVE-1601",
                            encrypted_private,
                        )
                    ]
                )
            return Cursor([])

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "text_embedding", lambda query: [0.0] * 384)

    context = main.retrieve_context("帮我处理 INV-LIVE-1601，但不要付款，只告诉我你找到了什么。", 4)

    assert context[0]["layer"] == "literal_identifier_recall"
    release = context[0]["released_private_evidence"]
    assert release["release_policy"] == "first_party_literal_identifier_read_minimal_fields"
    assert "1200 USD" in release["fields"]["amounts"]
    assert any("next Tuesday" in item for item in release["fields"]["time_clues"])
    assert any("2026-06-23 周二" in item for item in release["fields"]["resolved_time_clues"])
    assert "billing@example.com" not in str(release)


def test_retrieve_context_prioritizes_external_literal_evidence_over_old_nomi_answers(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    encrypted_private = main.encrypt_private_raw_data(
        {
            "subject": "Invoice INV-LIVE-1601 due",
            "body": "Invoice INV-LIVE-1601 for 1200 USD is due next Tuesday. Do not pay without confirmation.",
            "from": "billing@example.com",
        }
    )

    class Cursor:
        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchall(self):
            return self.rows

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            compact = " ".join(sql.split())
            if "literal_identifier_recall" in compact:
                return Cursor(
                    [
                        (
                            "2026-06-16T09:00:00+00:00",
                            "nomi_chat",
                            "assistant_message",
                            {
                                "role": "assistant",
                                "content": "INV-LIVE-1601 状态：已到期（Due），金额 AMOUNT_1。",
                            },
                            None,
                            None,
                            None,
                            {},
                            "INV-LIVE-1601",
                            None,
                        ),
                        (
                            "2026-06-16T09:01:00+00:00",
                            "nomi_chat",
                            "user_message",
                            {
                                "role": "user",
                                "content": "帮我处理 INV-LIVE-1601，但不要付款，只告诉我你找到了什么。",
                            },
                            None,
                            None,
                            None,
                            {},
                            "INV-LIVE-1601",
                            None,
                        ),
                        (
                            "2026-06-16T08:00:00+00:00",
                            "gmail",
                            "gmail_message",
                            {
                                "subject": "Invoice INV-LIVE-1601 due",
                                "body": "Invoice INV-LIVE-1601 for AMOUNT_1 is due next Tuesday.",
                                "sensitive": True,
                                "sensitive_reasons": ["amount", "email"],
                            },
                            "Invoice INV-LIVE-1601 for AMOUNT_1 is due next Tuesday.",
                            "task_request",
                            0.8,
                            {"memory_scope": {"usable_contexts": ["personal_search"], "sensitivity": "normal"}},
                            "INV-LIVE-1601",
                            encrypted_private,
                        ),
                    ]
                )
            return Cursor([])

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "text_embedding", lambda query: [0.0] * 384)

    context = main.retrieve_context("帮我处理 INV-LIVE-1601，但不要付款，只告诉我你找到了什么。", 4)

    assert context[0]["source"] == "gmail"
    assert "1200 USD" in str(context[0].get("released_private_evidence"))
    assert all(item.get("event_type") != "assistant_message" for item in context)


def test_merge_parallel_memory_context_keeps_explicit_layers_and_dedupes(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    merged = main.merge_parallel_memory_context(
        {
            "memory_kv": [{"source_id": "profile:name", "layer": "working_memory", "content": "用户叫 Nomi Tester"}],
            "memory_graph": [{"source_id": "person:alice", "layer": "entity_graph", "content": "Alice 是朋友"}],
            "memory_rag": [{"source_id": "event:1", "layer": "vector_recall", "content": "Alice 约周五见"}],
            "timeline": [{"source_id": "event:1", "layer": "timeline", "content": "重复的 timeline 证据"}],
            "memory": [{"source_id": "legacy:1", "layer": "semantic_memory", "content": "兼容旧 memory fetcher"}],
        }
    )

    assert [item["source_id"] for item in merged] == ["profile:name", "person:alice", "event:1", "legacy:1"]
    assert {item["layer"] for item in merged} == {"working_memory", "entity_graph", "vector_recall", "semantic_memory"}


def test_schema_bootstrap_creates_task_orchestrator_tables(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed = []

    class Cursor:
        pass

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            executed.append(" ".join(sql.split()))
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())

    main.ensure_task_orchestrator_schema()

    combined = "\n".join(executed)
    assert "CREATE TABLE IF NOT EXISTS task_runs" in combined
    assert "CREATE TABLE IF NOT EXISTS task_steps" in combined
    assert "CREATE TABLE IF NOT EXISTS notification_outbox" in combined


def test_schema_bootstrap_creates_tool_registry_tables(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed = []

    class Cursor:
        pass

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            executed.append(" ".join(sql.split()))
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())

    main.ensure_tool_registry_schema()

    combined = "\n".join(executed)
    assert "CREATE TABLE IF NOT EXISTS capability_catalog" in combined
    assert "CREATE TABLE IF NOT EXISTS tool_registry_entries" in combined
    assert "CREATE TABLE IF NOT EXISTS tool_invocation_traces" in combined


def test_schema_bootstrap_creates_workflow_distillation_tables(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed = []

    class Cursor:
        pass

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            executed.append(" ".join(sql.split()))
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())

    main.ensure_workflow_distillation_schema()

    combined = "\n".join(executed)
    assert "CREATE TABLE IF NOT EXISTS workflow_patterns" in combined
    assert "CREATE TABLE IF NOT EXISTS pipeline_candidates" in combined
    assert "CREATE TABLE IF NOT EXISTS skill_evaluation_runs" in combined


def test_persist_model_request_trace_records_provider_and_fallbacks(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed = []

    class Cursor:
        pass

    class Conn:
        def execute(self, sql, params=()):
            executed.append((" ".join(sql.split()), params))
            return Cursor()

    trace_id = main.persist_model_request_trace(
        Conn(),
        task_class="chat",
        selected_provider_id="fallback",
        status="succeeded",
        fallback_provider_ids=["primary"],
        payload={"reason": "primary unreachable"},
    )

    assert trace_id
    sql, params = executed[0]
    assert "INSERT INTO model_request_traces" in sql
    assert params[1] == "chat"
    assert params[2] == "fallback"
    assert params[3] == ["primary"]
    assert params[4] == "succeeded"


def test_context_pack_honors_max_agenda_items_for_narrow_queries(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    agenda_items = [
        {
            "id": f"agenda-{index}",
            "type": "appointment",
            "title": f"明天和 Alice 见面 {index}",
            "status": "scheduled",
            "certainty": "exact",
            "time_window": {"display": "2099-06-16 周二 10:00"},
            "place": "静安寺地铁站",
            "participants": ["Alice"],
            "missing_fields": [],
            "needs_clarification": False,
            "confidence": 0.8,
            "source_event_ids": [f"event-{index}"],
            "metadata": {"source": "whatsapp"},
        }
        for index in range(6)
    ]

    pack = main.build_context_pack(
        "我什么时候去哪里见 Alice？",
        [],
        conversation_id="conv-1",
        agenda_context=agenda_items,
        max_agenda_items=2,
        context_budget={"input_target": 12000, "hard_input_ceiling": 16000},
    )

    assert len(pack["agenda_context"]) == 2
    assert pack["included_agenda_ids"] == ["agenda-0", "agenda-1"]


def test_chat_messages_use_compact_model_context_without_raw_debug_payloads():
    from app.main import build_chat_messages

    context_pack = {
        "current_request": {"content": "Alice 明天几点见面？", "raw_data": {"debug": "x" * 5000}},
        "assistant_dialogue": [
            {"role": "assistant", "content": "你要我帮你确认 Alice 的见面时间吗？", "raw_data": {"debug": "y" * 5000}},
        ],
        "agenda_context": [
            {
                "title": "Alice 见面",
                "starts_at": "2026-06-16T16:00:00+08:00",
                "location": "人民广场",
                "raw_data": {"html": "z" * 5000},
            }
        ],
        "sections": [{"name": "debug", "items": [{"raw_data": "should-not-leak"}]}],
        "excluded": [{"reason": "debug-only", "raw": "should-not-leak"}],
        "chat_route": {"intent": "agenda_query"},
        "token_budget": {"input_used": 1234, "input_target": 24000},
    }

    messages = build_chat_messages("Alice 明天几点见面？", context_pack)
    model_context = messages[1]["content"]

    assert "Alice 见面" in model_context
    assert "2026-06-16T16:00:00+08:00" in model_context
    assert "人民广场" in model_context
    assert "should-not-leak" not in model_context
    assert "debug-only" not in model_context
    assert len(model_context) < 3000


def test_chat_messages_include_career_context_for_job_queries():
    from app.main import build_chat_messages

    messages = build_chat_messages(
        "帮我找找看有没有适合我的工作机会",
        {
            "chat_route": {"intent": "job_query"},
            "career_context": {
                "profiles": [
                    {
                        "headline": "后端工程师，熟悉 Java、Spring Boot、MySQL",
                        "target_roles": ["Backend Engineer"],
                    }
                ],
                "career_resumes": [
                    {
                        "filename": "后端-范小刚.pdf",
                        "parsed_text_summary": "5 年后端开发经验，Java / Spring Boot / Redis / MySQL。",
                    }
                ],
                "opportunities": [
                    {
                        "title": "Backend Engineer",
                        "company": "Example AI",
                        "url": "https://www.linkedin.com/jobs/view/4431606283",
                        "fit_score": 0.82,
                    }
                ],
                "linkedin": {"collection_status": "healthy"},
                "missing": ["career_resume"],
            },
        },
    )

    model_context = messages[1]["content"]
    assert "career_context" in model_context
    assert "后端-范小刚.pdf" in model_context
    assert "Spring Boot" in model_context
    assert "https://www.linkedin.com/jobs/view/4431606283" in model_context
    assert "career_resume" in model_context
    assert "没有导入完整简历" in messages[0]["content"]
    assert "不要声称已经完成实时 LinkedIn 搜索" in messages[0]["content"]


def test_chat_messages_instruct_agenda_answers_to_use_absolute_dates():
    from app.main import build_chat_messages

    messages = build_chat_messages("我什么时候见 Alice？", {"agenda_context": []})

    assert "日程" in messages[0]["content"]
    assert "绝对日期" in messages[0]["content"]


def test_chat_messages_include_agenda_time_status_for_model():
    from app.main import build_chat_messages

    messages = build_chat_messages(
        "最近有要开的会吗",
        {
            "agenda_context": [
                {
                    "id": "gmail-past-meeting",
                    "title": "腾讯会议线上会议",
                    "time_window": {"start": "2026-06-25T03:00:00+08:00", "display": "2026-06-25 周四 03:00"},
                    "time_status": "past",
                }
            ]
        },
    )

    assert "time_status" in messages[1]["content"]
    assert "past" in messages[1]["content"]
    assert "已发生" in messages[0]["content"]
    assert "不要建议用户准备" in messages[0]["content"]


def test_relevant_agenda_items_prioritizes_named_contact_and_source_over_recent_generic_match():
    from app.main import relevant_agenda_items

    items = [
        {
            "id": "hr",
            "title": "明天上午10点产品经理面试安排",
            "participants": ["Alpha HR"],
            "metadata": {"source": "gmail"},
            "time_window": {"display": "2026-06-16 周二 10:00"},
            "updated_at": "2026-06-15T19:30:00+08:00",
        },
        {
            "id": "maya",
            "title": "周五上午10点静安寺地铁站见面",
            "participants": ["Maya"],
            "metadata": {"source": "telegram"},
            "time_window": {"display": "2026-06-19 周五 10:00"},
            "updated_at": "2026-06-15T19:00:00+08:00",
        },
        {
            "id": "alice",
            "title": "明天下午4点在人民广场见面，记得带合同。",
            "participants": ["Alice"],
            "metadata": {"source": "whatsapp"},
            "time_window": {"display": "2026-06-16 周二 16:00"},
            "updated_at": "2026-06-15T18:47:45+08:00",
        },
    ]

    selected = relevant_agenda_items("根据刚才 WhatsApp 里 Alice 的安排，我什么时候去哪里见她？", items, limit=1)

    assert [item["id"] for item in selected] == ["alice"]


def test_relevant_agenda_items_filters_to_explicit_source_and_contact_when_available():
    from app.main import relevant_agenda_items

    items = [
        {
            "id": "echo-question-1",
            "title": "user said to Nomi: 根据刚才 WhatsApp 里 Alice 的安排，我什么时候去哪里见她？请一句话回答。",
            "participants": [],
            "metadata": {"source": "nomi_chat"},
            "time_window": {"raw_text": "根据刚才 WhatsApp 里 Alice 的安排，我什么时候去哪里见她？请一句话回答。"},
            "missing_fields": ["exact_time"],
            "needs_clarification": True,
            "updated_at": "2026-06-15T19:35:00+08:00",
        },
        {
            "id": "echo-question-2",
            "title": "user said to Nomi: 根据刚才 WhatsApp 里 Alice 的安排，我什么时候去哪里见她？请一句话回答。",
            "participants": [],
            "metadata": {"source": "nomi_chat"},
            "time_window": {"raw_text": "根据刚才 WhatsApp 里 Alice 的安排，我什么时候去哪里见她？请一句话回答。"},
            "missing_fields": ["exact_time"],
            "needs_clarification": True,
            "updated_at": "2026-06-15T19:34:00+08:00",
        },
        {
            "id": "hr",
            "title": "明天上午10点产品经理面试安排",
            "participants": ["Alpha HR"],
            "metadata": {"source": "gmail"},
            "time_window": {"display": "2026-06-16 周二 10:00"},
            "updated_at": "2026-06-15T19:30:00+08:00",
        },
        {
            "id": "maya",
            "title": "周五上午10点静安寺地铁站见面",
            "participants": ["Maya"],
            "metadata": {"source": "telegram"},
            "time_window": {"display": "2026-06-19 周五 10:00"},
            "updated_at": "2026-06-15T19:00:00+08:00",
        },
        {
            "id": "alice",
            "title": "明天下午4点在人民广场见面，记得带合同。",
            "participants": ["Alice"],
            "metadata": {"source": "whatsapp"},
            "time_window": {"display": "2026-06-16 周二 16:00"},
            "updated_at": "2026-06-15T18:47:45+08:00",
        },
    ]

    selected = relevant_agenda_items(
        "根据刚才 WhatsApp 里 Alice 的安排，我什么时候去哪里见她？请一句话回答。",
        items,
        limit=2,
    )

    assert [item["id"] for item in selected] == ["alice"]


def test_retrieve_active_agenda_context_uses_wide_candidate_window_before_rerank(monkeypatch):
    from app import main

    captured_limits = []

    class Cursor:
        def fetchall(self):
            return []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            captured_limits.append(params[-1])
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())

    result = main.retrieve_active_agenda_context("WhatsApp Alice 明天见面", limit=2)

    assert result == []
    assert captured_limits == [80]


def test_agenda_item_from_row_canonicalizes_relative_time_window_to_absolute_display():
    from app import main

    row = (
        "agenda-people-square",
        "appointment",
        "人民广场会面",
        "scheduled",
        "exact",
        {
            "type": "exact",
            "raw_text": "明天下午4点",
            "text": "明天下午4点",
            "start": "2026-06-25T16:00:00+08:00",
        },
        "人民广场",
        ["张三"],
        [],
        False,
        0.92,
        ["event-1"],
        {"source": "whatsapp"},
        "2026-06-24T10:00:00+08:00",
        "2026-06-24T10:01:00+08:00",
    )

    item = main.agenda_item_from_row(row)

    assert item["time_window"]["display"] == "2026-06-25 周四 16:00"
    assert item["time_window"]["text"] == "2026-06-25 周四 16:00"
    assert item["time_window"]["raw_text"] == "明天下午4点"
    assert "明天" not in item["time_window"]["text"]


def test_agenda_item_matches_query_by_place_and_source_reference():
    from app import main

    item = {
        "id": "agenda-gmail-people-square",
        "title": "明天下午4点人民广场见：请明天下午4点在人民广场见面，带合同。",
        "status": "scheduled",
        "certainty": "exact",
        "place": "人民广场",
        "participants": ["张子长"],
        "metadata": {"source": "gmail"},
        "time_window": {"display": "2026-06-21 周日 16:00"},
    }

    assert main.agenda_item_matches_query("刚才 Gmail 里的人民广场日程是什么？", item) is True
    assert main.agenda_item_matches_query("刚才 Gmail 里那条日程是什么？", item) is True


def test_generic_meeting_query_returns_recent_valid_agenda_and_filters_ui_noise():
    from app import main

    items = [
        {
            "id": "noise-linkedin",
            "title": "0 notifications total\nKeyboard shortcuts\nClose jump menu",
            "status": "scheduled",
            "certainty": "fuzzy",
            "time_window": {"raw_text": "0 notifications total\nKeyboard shortcuts"},
            "metadata": {"source": "linkedin"},
        },
        {
            "id": "payment-reminder",
            "title": "订单支付提醒",
            "status": "scheduled",
            "certainty": "fuzzy",
            "time_window": {"raw_text": "订单支付提醒"},
            "metadata": {"source": "gmail"},
        },
        {
            "id": "agenda-meeting",
            "title": "2026-06-25 周四 16:00 人民广场会面",
            "status": "scheduled",
            "certainty": "exact",
            "time_window": {"display": "2026-06-25 周四 16:00"},
            "place": "人民广场",
            "metadata": {"source": "gmail"},
        },
    ]

    selected = main.relevant_agenda_items("最近有要开的会吗", items, limit=3)

    assert [item["id"] for item in selected] == ["agenda-meeting"]


def test_upcoming_meeting_query_excludes_dated_past_agenda_items():
    from app import main

    items = [
        {
            "id": "past-meeting",
            "title": "2020-01-01 周三 09:00 旧会议",
            "status": "scheduled",
            "certainty": "exact",
            "time_window": {"start": "2020-01-01T09:00:00+08:00", "display": "2020-01-01 周三 09:00"},
            "metadata": {"source": "gmail"},
        },
        {
            "id": "future-meeting",
            "title": "2099-01-01 周四 10:00 新会议",
            "status": "scheduled",
            "certainty": "exact",
            "time_window": {"start": "2099-01-01T10:00:00+08:00", "display": "2099-01-01 周四 10:00"},
            "metadata": {"source": "gmail"},
        },
    ]

    selected = main.relevant_agenda_items("接下来有要开的会吗", items, limit=5)

    assert [item["id"] for item in selected] == ["future-meeting"]


def test_recent_meeting_query_falls_back_to_recent_past_and_ignores_stale_relative_items():
    from datetime import datetime

    from app import main

    now = datetime(2026, 6, 25, 15, 0, tzinfo=main.USER_TIMEZONE)
    items = [
        {
            "id": "stale-relative-meeting",
            "title": "上海博物馆见面",
            "status": "create",
            "certainty": "exact",
            "time_window": {
                "raw_text": "明天下午5点",
                "anchor_time": "2026-06-18T10:00:00+08:00",
            },
            "metadata": {"source": "nomi_chat"},
            "updated_at": "2026-06-18T05:35:51+00:00",
        },
        {
            "id": "non-meeting-payment",
            "title": "云服务器产品即将到期，请及时续费",
            "status": "scheduled",
            "certainty": "fuzzy",
            "time_window": {"raw_text": "7 天后到期"},
            "metadata": {"source": "gmail"},
            "updated_at": "2026-06-25T07:30:00+00:00",
        },
        {
            "id": "older-exact-past-meeting",
            "title": "2026-06-23 周二 16:00 人民广场会面",
            "status": "scheduled",
            "certainty": "exact",
            "time_window": {
                "start": "2026-06-23T16:00:00+08:00",
                "display": "2026-06-23 周二 16:00",
            },
            "place": "人民广场",
            "metadata": {"source": "gmail"},
            "updated_at": "2026-06-23T08:00:00+00:00",
        },
        {
            "id": "gmail-past-meeting",
            "title": "明天3点记得在腾讯会议上开线上会议",
            "status": "scheduled",
            "certainty": "fuzzy",
            "time_window": {
                "start": "2026-06-25T03:00:00+08:00",
                "display": "2026-06-25 周四 03:00",
                "source_event_timestamp": "2026-06-24T20:17:41+08:00",
            },
            "metadata": {"source": "gmail"},
            "updated_at": "2026-06-25T07:14:22+00:00",
        },
    ]

    selected = main.relevant_agenda_items("最近有要开的会吗", items, limit=3, now=now)

    assert selected[0]["id"] == "gmail-past-meeting"
    assert selected[0]["time_status"] == "past"


def test_next_meeting_query_does_not_fall_back_to_past_items():
    from datetime import datetime

    from app import main

    now = datetime(2026, 6, 25, 15, 0, tzinfo=main.USER_TIMEZONE)
    items = [
        {
            "id": "gmail-past-meeting",
            "title": "2026-06-25 周四 03:00 腾讯会议",
            "status": "scheduled",
            "certainty": "exact",
            "time_window": {"start": "2026-06-25T03:00:00+08:00", "display": "2026-06-25 周四 03:00"},
            "metadata": {"source": "gmail"},
        },
    ]

    selected = main.relevant_agenda_items("接下来有要开的会吗", items, limit=3, now=now)

    assert selected == []


def test_people_square_time_query_prefers_upcoming_exact_match_over_old_past_items():
    from datetime import datetime

    from app import main

    now = datetime(2026, 7, 1, 20, 40, tzinfo=main.USER_TIMEZONE)
    items = [
        {
            "id": "old-people-square",
            "title": "明天下午4点人民广场见",
            "type": "appointment",
            "status": "scheduled",
            "certainty": "exact",
            "time_window": {
                "start": "2026-06-23T16:00:00+08:00",
                "display": "2026-06-23 周二 16:00",
            },
            "place": "人民广场",
            "participants": ["历史联系人"],
            "metadata": {"source": "gmail"},
            "updated_at": "2026-06-22T19:13:11+08:00",
        },
        {
            "id": "new-people-square",
            "title": "明天下午3点半在人民广场见，带合同。 测试码M1",
            "type": "appointment",
            "status": "scheduled",
            "certainty": "exact",
            "time_window": {
                "start": "2026-07-02T15:30:00+08:00",
                "display": "2026-07-02 周四 15:30",
                "raw_text": "明天下午3点半在人民广场见，带合同。 测试码M1",
            },
            "place": "人民广场",
            "participants": ["大刚"],
            "metadata": {"source": "whatsapp"},
            "updated_at": "2026-07-01T20:27:36+08:00",
        },
    ]

    selected = main.relevant_agenda_items("人民广场见面的具体时间是哪天几点？", items, limit=1, now=now)

    assert [item["id"] for item in selected] == ["new-people-square"]


def test_people_square_time_query_can_answer_recent_past_exact_match():
    from datetime import datetime

    from app import main

    now = datetime(2026, 7, 2, 16, 40, tzinfo=main.USER_TIMEZONE)
    items = [
        {
            "id": "people-square-recent-past",
            "title": "明天下午3点半在人民广场见，带合同。 测试码M1",
            "type": "appointment",
            "status": "scheduled",
            "certainty": "exact",
            "time_window": {
                "start": "2026-07-02T15:30:00+08:00",
                "display": "2026-07-02 周四 15:30",
                "raw_text": "明天下午3点半在人民广场见，带合同。 测试码M1",
            },
            "place": "人民广场",
            "participants": ["大刚"],
            "metadata": {"source": "whatsapp"},
            "updated_at": "2026-07-01T20:27:36+08:00",
        }
    ]

    selected = main.relevant_agenda_items("人民广场会面是几月几号几点？", items, limit=1, now=now)

    assert [item["id"] for item in selected] == ["people-square-recent-past"]
    assert selected[0]["time_status"] == "past"


def test_specific_place_missing_info_query_can_answer_recent_past_fuzzy_match():
    from datetime import datetime

    from app import main

    now = datetime(2026, 7, 4, 16, 0, tzinfo=main.USER_TIMEZONE)
    items = [
        {
            "id": "poly-missing-time",
            "title": "明天下午在保利广场详细聊一下呗",
            "type": "appointment",
            "status": "scheduled",
            "certainty": "fuzzy",
            "time_window": {
                "date": "2026-07-03",
                "display": "2026-07-03 周五",
                "raw_text": "明天下午在保利广场详细聊一下呗",
                "source_event_timestamp": "2026-07-02T14:48:23+08:00",
            },
            "place": "保利广场",
            "participants": ["大刚"],
            "missing_fields": ["exact_time"],
            "metadata": {"source": "whatsapp"},
            "updated_at": "2026-07-02T14:48:23+08:00",
        }
    ]

    selected = main.relevant_agenda_items("保利广场的安排缺什么信息？请给出来源。", items, limit=3, now=now)

    assert [item["id"] for item in selected] == ["poly-missing-time"]
    assert selected[0]["time_status"] == "past"
    assert selected[0]["missing_fields"] == ["exact_time"]


def test_deadline_action_query_can_answer_recent_past_exact_match():
    from datetime import datetime

    from app import main

    now = datetime(2026, 7, 4, 16, 0, tzinfo=main.USER_TIMEZONE)
    items = [
        {
            "id": "quote-deadline",
            "title": "周五18点前把报价单发我，记得核对成本和利润率。",
            "type": "deadline",
            "status": "scheduled",
            "certainty": "exact",
            "time_window": {
                "start": "2026-07-03T18:00:00+08:00",
                "display": "2026-07-03 周五 18:00",
                "raw_text": "周五18点前把报价单发我，记得核对成本和利润率。",
            },
            "participants": ["大刚"],
            "metadata": {"source": "whatsapp"},
            "updated_at": "2026-07-02T16:30:07+08:00",
        }
    ]

    selected = main.relevant_agenda_items("周五18点前我要做什么？请给出来源。", items, limit=3, now=now)

    assert [item["id"] for item in selected] == ["quote-deadline"]
    assert selected[0]["time_status"] == "past"


def test_people_square_time_query_excludes_expired_past_matches_by_default():
    from datetime import datetime

    from app import main

    now = datetime(2026, 7, 1, 20, 40, tzinfo=main.USER_TIMEZONE)
    items = [
        {
            "id": "same-day-expired-people-square",
            "title": "NOMI_REG_WA_0629 明天15:30人民广场见，带合同",
            "type": "appointment",
            "status": "scheduled",
            "certainty": "exact",
            "time_window": {
                "start": "2026-07-01T15:30:00+08:00",
                "display": "2026-07-01 周三 15:30",
            },
            "place": "人民广场",
            "participants": ["Ask"],
            "metadata": {"source": "whatsapp"},
            "updated_at": "2026-06-30T17:52:07+08:00",
        },
        {
            "id": "upcoming-people-square",
            "title": "明天下午3点半在人民广场见，带合同。 测试码M1",
            "type": "appointment",
            "status": "scheduled",
            "certainty": "exact",
            "time_window": {
                "start": "2026-07-02T15:30:00+08:00",
                "display": "2026-07-02 周四 15:30",
                "raw_text": "明天下午3点半在人民广场见，带合同。 测试码M1",
            },
            "place": "人民广场",
            "participants": ["大刚"],
            "metadata": {"source": "whatsapp"},
            "updated_at": "2026-07-01T20:27:36+08:00",
        },
    ]

    selected = main.relevant_agenda_items("人民广场见面的具体时间是哪天几点？", items, limit=3, now=now)

    assert [item["id"] for item in selected] == ["upcoming-people-square"]


def test_cancelled_arrangements_query_returns_only_canceled_items():
    from datetime import datetime

    from app import main

    now = datetime(2026, 7, 2, 16, 40, tzinfo=main.USER_TIMEZONE)
    items = [
        {
            "id": "active-call",
            "title": "明天电话聊保险",
            "type": "appointment",
            "status": "scheduled",
            "certainty": "fuzzy",
            "time_window": {"date": "2026-07-03", "display": "2026-07-03 周五"},
            "metadata": {"source": "whatsapp"},
            "updated_at": "2026-07-02T16:32:51+08:00",
        },
        {
            "id": "cancelled-meeting",
            "title": "我们明天不见面了，改电话聊",
            "type": "appointment",
            "status": "canceled",
            "certainty": "fuzzy",
            "time_window": {"date": "2026-07-03", "display": "2026-07-03 周五"},
            "metadata": {"source": "whatsapp"},
            "updated_at": "2026-07-02T16:32:51+08:00",
        },
    ]

    selected = main.relevant_agenda_items("我最近有什么被取消的安排？", items, limit=3, now=now)

    assert [item["id"] for item in selected] == ["cancelled-meeting"]
    assert selected[0]["time_status"] == "canceled"


def test_upcoming_agenda_query_excludes_uncommitted_create_items():
    from datetime import datetime

    from app import main

    now = datetime(2026, 7, 2, 18, 0, tzinfo=main.USER_TIMEZONE)
    items = [
        {
            "id": "uncommitted-create",
            "title": "上海博物馆见面",
            "type": "appointment",
            "status": "create",
            "certainty": "fuzzy",
            "time_window": {"raw_text": "明天下午5点"},
            "metadata": {"source": "nomi_chat"},
            "updated_at": "2026-07-02T17:50:00+08:00",
        },
        {
            "id": "policy-reminder",
            "title": "明天3点半别忘了，不是开会，是提醒你看一下保单",
            "type": "todo",
            "status": "scheduled",
            "certainty": "exact",
            "time_window": {
                "start": "2026-07-03T03:30:00+08:00",
                "display": "2026-07-03 周五 03:30",
                "raw_text": "明天3点半别忘了，不是开会，是提醒你看一下保单",
            },
            "metadata": {"source": "whatsapp"},
            "updated_at": "2026-07-02T16:32:00+08:00",
        },
        {
            "id": "poly-meeting",
            "title": "明天下午在保利广场详细聊一下呗",
            "type": "appointment",
            "status": "scheduled",
            "certainty": "fuzzy",
            "time_window": {"date": "2026-07-03", "display": "2026-07-03 周五"},
            "place": "保利广场",
            "missing_fields": ["exact_time"],
            "metadata": {"source": "whatsapp"},
            "updated_at": "2026-07-02T14:48:00+08:00",
        },
    ]

    selected = main.relevant_agenda_items("明天我有哪些安排？", items, limit=5, now=now)

    assert [item["id"] for item in selected] == ["policy-reminder", "poly-meeting"]


def test_upcoming_relative_day_query_excludes_unrelated_undated_items():
    from datetime import datetime

    from app import main

    now = datetime(2026, 7, 2, 18, 0, tzinfo=main.USER_TIMEZONE)
    items = [
        {
            "id": "undated-renewal",
            "title": "云服务器产品即将到期，请及时续费。为避免服务暂停，请您及时安排续费。",
            "type": "todo",
            "status": "scheduled",
            "certainty": "fuzzy",
            "time_window": {"raw_text": "7 天后到期"},
            "missing_fields": ["exact_time"],
            "metadata": {"source": "gmail"},
            "updated_at": "2026-07-02T12:00:00+08:00",
        },
        {
            "id": "policy-reminder",
            "title": "明天3点半别忘了，不是开会，是提醒你看一下保单",
            "type": "todo",
            "status": "scheduled",
            "certainty": "exact",
            "time_window": {
                "start": "2026-07-03T03:30:00+08:00",
                "display": "2026-07-03 周五 03:30",
            },
            "metadata": {"source": "whatsapp"},
            "updated_at": "2026-07-02T16:32:00+08:00",
        },
    ]

    selected = main.relevant_agenda_items("明天我有哪些安排？", items, limit=5, now=now)

    assert [item["id"] for item in selected] == ["policy-reminder"]


def test_agenda_query_with_explicit_place_filters_other_places():
    from datetime import datetime

    from app import main

    now = datetime(2026, 7, 1, 20, 40, tzinfo=main.USER_TIMEZONE)
    items = [
        {
            "id": "other-place-meeting",
            "title": "上海博物馆见面",
            "type": "appointment",
            "status": "scheduled",
            "certainty": "fuzzy",
            "time_window": {"raw_text": "找时间见面"},
            "place": "上海博物馆",
            "participants": ["RG_Alice"],
            "metadata": {"source": "whatsapp"},
            "updated_at": "2026-07-01T20:30:00+08:00",
        },
        {
            "id": "people-square-meeting",
            "title": "明天下午3点半在人民广场见，带合同。 测试码M1",
            "type": "appointment",
            "status": "scheduled",
            "certainty": "exact",
            "time_window": {
                "start": "2026-07-02T15:30:00+08:00",
                "display": "2026-07-02 周四 15:30",
                "raw_text": "明天下午3点半在人民广场见，带合同。 测试码M1",
            },
            "place": "人民广场",
            "participants": ["大刚"],
            "metadata": {"source": "whatsapp"},
            "updated_at": "2026-07-01T20:27:36+08:00",
        },
    ]

    selected = main.relevant_agenda_items("人民广场见面的具体时间是哪天几点？", items, limit=3, now=now)

    assert [item["id"] for item in selected] == ["people-square-meeting"]


def test_agenda_query_prefers_open_chat_evidence_over_chat_list_preview_duplicate():
    from datetime import datetime

    from app import main

    now = datetime(2026, 7, 1, 20, 40, tzinfo=main.USER_TIMEZONE)
    items = [
        {
            "id": "preview-wrong-half-past",
            "title": "明天下午3点半在人民广场见，带合同。 测试码M1",
            "type": "appointment",
            "status": "scheduled",
            "certainty": "exact",
            "time_window": {
                "start": "2026-07-02T15:00:00+08:00",
                "display": "2026-07-02 周四 15:00",
                "raw_text": "明天下午3点半在人民广场见，带合同。 测试码M1",
            },
            "place": "人民广场",
            "participants": ["请记住：我的测试暗号是海盐拿铁。 测试码P1"],
            "metadata": {
                "source": "whatsapp",
                "source_event_evidence": [
                    {
                        "event_type": "whatsapp_message",
                        "capture_scope": "chat_list_preview",
                        "message": "明天下午3点半在人民广场见，带合同。 测试码M1",
                    }
                ],
            },
            "updated_at": "2026-07-01T20:38:21+08:00",
        },
        {
            "id": "open-chat-correct-half-past",
            "title": "明天下午3点半在人民广场见，带合同。 测试码M1",
            "type": "appointment",
            "status": "scheduled",
            "certainty": "exact",
            "time_window": {
                "start": "2026-07-02T15:30:00+08:00",
                "display": "2026-07-02 周四 15:30",
                "raw_text": "明天下午3点半在人民广场见，带合同。 测试码M1",
            },
            "place": "人民广场",
            "participants": ["大刚"],
            "metadata": {
                "source": "whatsapp",
                "source_event_evidence": [
                    {
                        "event_type": "whatsapp_message",
                        "capture_scope": "history_scroll_sync",
                        "message": "明天下午3点半在人民广场见，带合同。 测试码M1",
                    }
                ],
            },
            "updated_at": "2026-07-01T20:27:36+08:00",
        },
    ]

    selected = main.relevant_agenda_items("人民广场见面的具体时间是哪天几点？", items, limit=1, now=now)

    assert [item["id"] for item in selected] == ["open-chat-correct-half-past"]


def test_compact_agenda_context_item_drops_large_low_value_source_evidence():
    from app import main

    noisy_transcript = (
        "消息和通话已进行端到端加密。只有此聊天中的成员可以查看、收听或分享。点击了解更多\n"
        + "输入消息\n" * 600
        + "明天下午3点半在人民广场见，带合同。 测试码M1"
    )
    item = {
        "id": "people-square",
        "title": "明天下午3点半在人民广场见，带合同。 测试码M1",
        "metadata": {
            "source": "whatsapp",
            "source_event_evidence": [
                {
                    "event_type": "whatsapp_message",
                    "capture_scope": "history_scroll_sync",
                    "message": "明天下午3点半在人民广场见，带合同。 测试码M1",
                },
                {
                    "event_type": "whatsapp_message",
                    "capture_scope": "history_scroll_sync",
                    "message": noisy_transcript,
                },
            ],
        },
    }

    compacted = main.compact_agenda_context_item(item)
    evidence = compacted["metadata"]["source_event_evidence"]

    assert len(evidence) == 1
    assert evidence[0]["message"] == "明天下午3点半在人民广场见，带合同。 测试码M1"
    assert main.estimate_context_tokens(compacted) < 800


def test_low_value_agenda_item_filters_whatsapp_full_ui_transcript_noise():
    from app import main

    item = {
        "title": (
            "消息和通话已进行端到端加密。只有此聊天中的成员可以查看、收听或分享。点击了解更多\n"
            "你好呀\n07:53\n明天下午3点半在人民广场见，带合同。 测试码M1\n输入消息"
        ),
        "metadata": {"source": "whatsapp"},
        "time_window": {
            "raw_text": (
                "消息和通话已进行端到端加密。只有此聊天中的成员可以查看、收听或分享。点击了解更多\n"
                "明天下午3点半在人民广场见，带合同。 测试码M1\n输入消息"
            )
        },
    }

    assert main.is_low_value_agenda_item(item) is True


def test_build_context_pack_includes_relevant_dialogue_and_excludes_unrelated():
    from app.main import build_context_pack

    pack = build_context_pack(
        "那就周日吧",
        base_context=[
            {
                "layer": "entity_graph",
                "subject": "alex",
                "predicate": "identity",
                "object": "健身房 Alex",
                "confidence": 0.82,
                "source_event_ids": ["fact-1"],
            }
        ],
        assistant_context=[
            {
                "layer": "assistant_dialogue",
                "event_id": "turn-1",
                "conversation_id": "conv-active",
                "role": "user",
                "content": "帮我盯一下周末和 Alex 见面的事",
            },
            {
                "layer": "assistant_dialogue",
                "event_id": "turn-2",
                "conversation_id": "conv-active",
                "role": "user",
                "content": "不是公司 Alex，是健身房 Alex",
            },
            {
                "layer": "assistant_dialogue",
                "event_id": "turn-3",
                "conversation_id": "conv-other",
                "role": "user",
                "content": "猫粮优惠券下次再说",
            },
        ],
        conversation_id="conv-active",
    )

    dialogue_text = "\n".join(item["content"] for item in pack["assistant_dialogue"])
    assert "周末和 Alex 见面" in dialogue_text
    assert "健身房 Alex" in dialogue_text
    assert "猫粮优惠券" not in dialogue_text
    assert pack["included_event_ids"] == ["turn-1", "turn-2", "fact-1"]
    assert "bounded" in pack["reason"]


def test_retrieve_assistant_dialogue_context_keeps_valid_conversation_id_isolated(monkeypatch):
    import uuid

    from app import main

    captured: list[tuple[str, tuple]] = []

    class Cursor:
        def fetchall(self):
            return []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            captured.append((" ".join(sql.split()), params))
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())
    conversation_id = uuid.uuid4()

    result = main.retrieve_assistant_dialogue_context(
        "明天我有哪些安排？",
        conversation_id=str(conversation_id),
        limit=12,
    )

    assert result == []
    sql, params = captured[0]
    assert "WHERE t.conversation_id = %s" in sql
    assert "ILIKE" not in sql
    assert params == (conversation_id, 12)


def test_build_context_pack_excludes_cross_conversation_assistant_answers_for_identifier_tasks():
    from app.main import build_context_pack

    pack = build_context_pack(
        "帮我处理 INV-LIVE-1601，但不要付款，只告诉我你找到了什么。",
        base_context=[],
        assistant_context=[
            {
                "layer": "assistant_dialogue",
                "event_id": "old-assistant-wrong",
                "conversation_id": "conv-old",
                "role": "assistant",
                "content": "INV-LIVE-1601 状态：已到期（Due）。金额：AMOUNT_1。",
            },
            {
                "layer": "assistant_dialogue",
                "event_id": "old-user-correction",
                "conversation_id": "conv-old",
                "role": "user",
                "content": "不是已逾期，due next Tuesday 应该理解成到期日。",
            },
            {
                "layer": "assistant_dialogue",
                "event_id": "same-assistant",
                "conversation_id": "conv-active",
                "role": "assistant",
                "content": "需要我继续核对 INV-LIVE-1601 吗？",
            },
        ],
        conversation_id="conv-active",
    )

    dialogue_ids = [item["event_id"] for item in pack["assistant_dialogue"]]
    assert "old-assistant-wrong" not in dialogue_ids
    assert "old-user-correction" in dialogue_ids
    assert "same-assistant" in dialogue_ids


def test_build_context_pack_uses_token_budget_not_fixed_turn_count():
    from app.main import build_context_pack

    assistant_context = [
        {
            "layer": "assistant_dialogue",
            "event_id": f"turn-{index}",
            "conversation_id": "conv-budget",
            "role": "assistant" if index % 2 else "user",
            "content": f"PHONE_1 报价上下文第 {index} 条，包含成本、利润率和客户反馈。",
        }
        for index in range(12)
    ]

    pack = build_context_pack(
        "继续核对 PHONE_1 的成本与利润率",
        base_context=[],
        assistant_context=assistant_context,
        conversation_id="conv-budget",
        context_budget={"input_target": 12000, "hard_input_ceiling": 16000},
    )

    dialogue_ids = [item["event_id"] for item in pack["assistant_dialogue"]]
    assert dialogue_ids == [f"turn-{index}" for index in range(12)]
    assert pack["token_budget"]["model_window"] == 256000
    assert pack["token_budget"]["input_used"] > 0
    same_conversation = next(section for section in pack["sections"] if section["name"] == "same_conversation")
    assert same_conversation["tokens_used"] > 0


def test_build_context_pack_exposes_session_search_for_short_reply():
    from app.main import build_context_pack

    pack = build_context_pack(
        "需要",
        base_context=[],
        assistant_context=[
            {
                "layer": "assistant_dialogue",
                "turn_id": "assistant-question",
                "event_id": "assistant-question",
                "conversation_id": "conv-margin",
                "role": "assistant",
                "content": "需要我帮你核对成本与利润率数据吗？",
            }
        ],
        conversation_id="conv-margin",
        task_context=[
            {
                "layer": "task_trace",
                "task_id": "task-margin",
                "title": "PHONE_1 利润率核对",
                "status": "waiting_for_user",
                "conversation_id": "conv-margin",
            }
        ],
    )

    assert pack["session_search"]["short_reply_resolution"]["resolved"] is True
    assert pack["session_search"]["short_reply_resolution"]["prior_question_turn_id"] == "assistant-question"
    assert pack["session_search"]["active_tasks"][0]["task_id"] == "task-margin"


def test_short_reply_resolution_is_visible_in_model_context():
    from app.main import build_chat_messages, build_context_pack

    pack = build_context_pack(
        "需要",
        base_context=[],
        assistant_context=[
            {
                "layer": "assistant_dialogue",
                "turn_id": "assistant-question",
                "event_id": "assistant-question",
                "conversation_id": "conv-margin",
                "role": "assistant",
                "content": "根据现有记录，PHONE_1 报价截止时间是周五 18:00。需要我帮你核对成本与利润率吗？",
            }
        ],
        conversation_id="conv-margin",
        task_context=[
            {
                "layer": "task_trace",
                "task_id": "task-margin",
                "title": "PHONE_1 报价利润率核对",
                "status": "waiting_for_user",
                "conversation_id": "conv-margin",
            }
        ],
    )

    messages = build_chat_messages("需要", pack)
    model_payload = messages[1]["content"]
    assert "short_reply_resolution" in model_payload
    assert "用户短回复“需要”是在回应上一轮 Nomi 提问" in model_payload
    assert "核对成本与利润率" in model_payload
    assert "PHONE_1 报价利润率核对" in model_payload


def test_build_context_pack_filters_cross_contact_context_before_ranking():
    from app.main import build_context_pack

    pack = build_context_pack(
        "帮我回复 Alice",
        base_context=[
            {
                "layer": "semantic_memory",
                "event_id": "alice-event",
                "content": "Alice 说这周五可以确认报价。",
                "counterparty_ids": ["alice"],
                "visibility_scope": "contact_scoped",
                "sensitivity_level": "medium",
            },
            {
                "layer": "semantic_memory",
                "event_id": "bob-private",
                "content": "Bob 私下抱怨 Alice 不靠谱。",
                "counterparty_ids": ["bob"],
                "visibility_scope": "contact_scoped",
                "sensitivity_level": "high",
            },
        ],
        assistant_context=[],
        conversation_id="conv-alice",
        request_scope={"counterparty_ids": ["alice"], "primary_scope": "contact_scoped"},
    )

    memory_text = json_text(pack["memory_context"])
    assert "Alice 说这周五可以确认报价" in memory_text
    assert "Bob 私下抱怨" not in memory_text
    assert pack["excluded"][0]["source_id"] == "bob-private"
    assert "Different contact scope" in pack["excluded"][0]["reason"]


def test_build_context_pack_truncates_oversized_items_with_source_trace():
    from app.main import build_context_pack

    long_content = "这是一封很长的邮件。" * 400
    pack = build_context_pack(
        "总结这封邮件",
        base_context=[
            {
                "layer": "vector_recall",
                "event_id": "long-email-1",
                "content": long_content,
                "source_event_ids": ["long-email-source"],
            }
        ],
        assistant_context=[],
        context_budget={
            "input_target": 900,
            "hard_input_ceiling": 1200,
            "single_item_token_limit": 80,
        },
    )

    packed_item = pack["memory_context"][0]
    assert packed_item["event_id"] == "long-email-1"
    assert packed_item["truncated"] is True
    assert len(packed_item["content"]) < len(long_content)
    assert pack["warnings"][0]["source_id"] == "long-email-1"
    assert pack["warnings"][0]["type"] == "summarized"


def test_context_tokenizer_uses_loaded_qwen_tokenizer_when_available(monkeypatch):
    from app import main

    class FakeTokenizer:
        def encode(self, text, add_special_tokens=False):
            assert add_special_tokens is False
            if text == "a":
                return [10, 11, 12, 13, 14, 15, 16]
            return list(range(max(1, len(str(text)) // 2)))

    monkeypatch.setattr(main, "_CONTEXT_TOKENIZER", FakeTokenizer(), raising=False)
    monkeypatch.setattr(main, "_CONTEXT_TOKENIZER_BACKEND", "hf:qwen-test", raising=False)

    pack = main.build_context_pack("a", base_context=[])

    assert main.estimate_context_tokens("a") == 7
    assert pack["token_budget"]["tokenizer_backend"] == "hf:qwen-test"
    assert pack["fallback_modes"]["tokenizer"] is None


def test_build_context_pack_summarizes_oversized_items_with_provenance():
    from app.main import build_context_pack

    long_content = (
        "客户 Alice 明确要求先核对 PHONE_1 的成本和利润率。"
        + "中间是冗长的邮件正文。" * 260
        + "最后结论：如果利润率低于 18%，不要直接承诺发货。"
    )
    pack = build_context_pack(
        "总结 Alice 的 PHONE_1 邮件",
        base_context=[
            {
                "layer": "vector_recall",
                "event_id": "long-email-summary",
                "content": long_content,
                "source_event_ids": ["email-source-1"],
            }
        ],
        assistant_context=[],
        context_budget={
            "input_target": 900,
            "hard_input_ceiling": 1200,
            "single_item_token_limit": 90,
        },
    )

    packed_item = pack["memory_context"][0]
    assert packed_item["event_id"] == "long-email-summary"
    assert packed_item["truncated"] is True
    assert packed_item["summary_method"] == "extractive_provenance_summary"
    assert packed_item["omitted_token_estimate"] > 0
    assert "Alice" in packed_item["content"]
    assert "不要直接承诺发货" in packed_item["content"]
    assert "[summary]" in packed_item["content"]
    assert pack["warnings"][0]["type"] == "summarized"


def test_context_pack_scores_and_ranks_memory_candidates():
    from app.main import build_context_pack

    pack = build_context_pack(
        "继续核对 PHONE_1 的利润率",
        base_context=[
            {
                "layer": "semantic_memory",
                "event_id": "generic-memory",
                "content": "Alice 喜欢简短回复。",
                "importance": 0.2,
            },
            {
                "layer": "semantic_memory",
                "event_id": "phone-margin-memory",
                "content": "PHONE_1 的成本是 AMOUNT_1，目标利润率至少 18%。",
                "importance": 0.7,
                "topic_ids": ["phone_1"],
            },
        ],
        assistant_context=[],
    )

    ranked_ids = [item["event_id"] for item in pack["memory_context"]]
    assert ranked_ids[0] == "phone-margin-memory"
    score = pack["memory_context"][0]["score"]
    assert set(score) >= {
        "scope_score",
        "semantic_score",
        "recency_score",
        "importance_score",
        "active_task_score",
        "user_correction_score",
        "risk_penalty",
        "final_score",
        "reason",
    }
    assert score["semantic_score"] > 0
    assert score["final_score"] > pack["memory_context"][1]["score"]["final_score"]


def test_retrieve_current_source_context_reads_durable_thread_from_events(monkeypatch):
    from app import main

    class Cursor:
        def fetchall(self):
            return [
                (
                    "source-event-1",
                    "whatsapp",
                    "message",
                    {"chat_name": "Alice", "sender": "Alice", "text": "Friday works for me."},
                    "2026-05-29T10:00:00Z",
                    "Alice 要求周五确认 PHONE_1 报价利润率。",
                    "quote",
                    0.91,
                )
            ]

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            assert "FROM events e" in sql
            assert params[0] == "whatsapp"
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())

    result = main.retrieve_current_source_context(
        "帮我回复 Alice",
        {
            "source_type": "whatsapp",
            "conversation_id": "wa-alice",
            "counterparty_ids": ["Alice"],
        },
        limit=3,
    )

    assert result[0]["layer"] == "current_source_thread"
    assert result[0]["source_type"] == "whatsapp"
    assert result[0]["counterparty_ids"] == ["alice"]
    assert "PHONE_1 报价利润率" in result[0]["content"]
    assert result[0]["source_id"] == "source-event-1"
    assert "durable" in result[0]["inclusion_reason"].lower()


def test_chat_endpoint_infers_gmail_source_context_from_user_question(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.model_gateway import ModelAnswer

    source_scopes: list[dict[str, object]] = []
    packed_source_context: list[dict[str, object]] = []

    def fake_persist_turn(conn, redis_client, role, content, conversation_id=None, client_type="web", **kwargs):
        return {
            "conversation_id": conversation_id or "conv-gmail-source",
            "turn_id": f"turn-{role}",
            "event_id": f"event-{role}",
        }

    def fake_retrieve_current_source_context(query, request_scope, limit=6):
        source_scopes.append(dict(request_scope))
        assert limit > 0
        if request_scope.get("source_type") == "gmail":
            return [
                {
                    "layer": "current_source_thread",
                    "source": "durable_events",
                    "event_id": "gmail-event-real-1",
                    "source_id": "gmail-event-real-1",
                    "source_type": "gmail",
                    "event_type": "gmail_message_snapshot",
                    "content": "Subject: 真实会议安排\nBody: 下周二 14:00 和 Lin 进行后端面试沟通。",
                    "counterparty_ids": ["lin"],
                    "inclusion_reason": "recent Gmail source context",
                }
            ]
        return []

    def fake_context_pack(
        message,
        base_context,
        assistant_context=None,
        conversation_id=None,
        request_scope=None,
        source_context=None,
        task_context=None,
        **kwargs,
    ):
        packed_source_context.extend(source_context or [])
        return {
            "context_pack_id": "ctx-gmail-source",
            "query": message,
            "memory_context": base_context,
            "assistant_dialogue": assistant_context or [],
            "agenda_context": kwargs.get("agenda_context") or [],
            "source_context": source_context or [],
            "task_context": task_context or [],
            "included_event_ids": ["event-user", "gmail-event-real-1"],
            "included_memory_ids": [],
            "included_agenda_ids": [],
            "token_budget": {"input_used": 100},
            "sections": [{"name": "source_context", "tokens_used": 20, "items": source_context or []}],
            "excluded": [],
            "warnings": [],
            "reason": "gmail source question",
        }

    class FakeGateway:
        async def chat(self, messages, temperature=0.4):
            assert "ctx-gmail-source" in messages[1]["content"]
            assert "真实会议安排" in messages[1]["content"]
            return ModelAnswer(
                text="我看到了 Gmail 里的真实会议安排：下周二 14:00 和 Lin 沟通。",
                provider_id="test-provider",
                trace={"fallback_from": []},
            )

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: object())
    monkeypatch.setattr(main, "persist_assistant_turn", fake_persist_turn, raising=False)
    monkeypatch.setattr(main, "find_cached_assistant_response", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "retrieve_context", lambda *args, **kwargs: [], raising=False)
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_current_source_context", fake_retrieve_current_source_context, raising=False)
    monkeypatch.setattr(main, "retrieve_active_agenda_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_task_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "safe_persist_context_route_trace", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "safe_persist_model_request_trace", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "build_context_pack", fake_context_pack, raising=False)
    monkeypatch.setattr(main, "model_gateway", lambda: FakeGateway())

    response = TestClient(main.app).post(
        "/api/chat",
        headers={"x-par-password": "secret"},
        json={
            "message": "最近 Gmail 里有什么需要我关注的吗？",
            "conversation_id": "conv-gmail-source",
        },
    )

    assert response.status_code == 200
    assert source_scopes[0]["source_type"] == "gmail"
    assert packed_source_context[0]["source_type"] == "gmail"
    assert "真实会议安排" in response.json()["answer"]


def test_build_context_pack_includes_source_task_layers_and_trace_fields():
    from app.main import build_context_pack

    pack = build_context_pack(
        "可以",
        base_context=[
            {"layer": "working_memory", "key": "reply_style", "value": "简洁"},
            {
                "layer": "entity_graph",
                "event_id": "graph-1",
                "subject": "Alice",
                "predicate": "works_on",
                "object": "PHONE_1",
            },
            {
                "layer": "vector_recall",
                "event_id": "rag-1",
                "summary": "Alice 周五会确认 PHONE_1 报价。",
            },
        ],
        assistant_context=[
            {
                "layer": "assistant_dialogue",
                "event_id": "turn-confirm",
                "conversation_id": "conv-layered",
                "role": "assistant",
                "content": "我可以先帮你整理回复草稿，要发给 Alice 吗？",
            }
        ],
        conversation_id="conv-layered",
        source_context=[
            {
                "layer": "current_source_thread",
                "event_id": "visible-wa",
                "source_type": "whatsapp",
                "content": "Alice: Friday works for me.",
            }
        ],
        task_context=[
            {
                "layer": "task_trace",
                "event_id": "trace-1",
                "pipeline_id": "reply_pipeline",
                "status": "needs_confirmation",
            }
        ],
        request_scope={"counterparty_ids": ["alice"], "source_type": "whatsapp"},
    )

    section_names = [section["name"] for section in pack["sections"]]
    assert pack["context_pack_id"].startswith("ctx_")
    assert "current_request" in section_names
    assert "source_context" in section_names
    assert "task_context" in section_names
    assert "kv_profile" in section_names
    assert "knowledge_graph_context" in section_names
    assert "rag_event_memory" in section_names
    assert pack["retrieval_modes"]["source_context"] == 1
    assert pack["scope_filters_applied"]["counterparty_ids"] == ["alice"]
    assert pack["assistant_dialogue"][0]["inclusion_reason"]
    assert pack["source_context"][0]["content"] == "Alice: Friday works for me."
    assert pack["task_context"][0]["pipeline_id"] == "reply_pipeline"


def test_normalize_client_delta_dedupes_current_message_and_keeps_prior_question():
    from app.main import normalize_client_dialogue_context

    normalized = normalize_client_dialogue_context(
        [
            {"role": "assistant", "content": "需要我帮你核对成本与利润率数据吗？"},
            {"role": "user", "content": "需要"},
        ],
        "conv-1",
        current_message="需要",
        token_budget=1000,
    )

    assert [item["role"] for item in normalized] == ["assistant"]
    assert normalized[0]["content"] == "需要我帮你核对成本与利润率数据吗？"


def test_chat_endpoint_builds_request_scope_caps_context_candidates_and_persists_answer_trace(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.model_gateway import ModelAnswer

    retrieve_limits = []
    snapshots = []

    def fake_persist_turn(conn, redis_client, role, content, conversation_id=None, client_type="web", **kwargs):
        return {
            "conversation_id": conversation_id or "conv-scope",
            "turn_id": f"turn-{role}",
            "event_id": f"event-{role}",
        }

    def fake_retrieve_context(message, limit, request_scope=None):
        retrieve_limits.append((limit, request_scope))
        return [{"layer": "semantic_memory", "event_id": "alice-memory", "content": "Alice 等报价。"}]

    def fake_task_context(query, conversation_id=None, limit=8):
        return [{"layer": "task_trace", "event_id": "trace-1", "pipeline_id": "reply_pipeline"}]

    def fake_snapshot(conn, event_id, context_type, context_pack):
        snapshots.append(context_pack)

    def fake_context_pack(
        message,
        base_context,
        assistant_context=None,
        conversation_id=None,
        request_scope=None,
        source_context=None,
        task_context=None,
        **kwargs,
    ):
        assert request_scope["counterparty_ids"] == ["alice"]
        assert request_scope["source_type"] == "whatsapp"
        assert source_context[0]["source_type"] == "whatsapp"
        assert task_context[0]["pipeline_id"] == "reply_pipeline"
        return {
            "context_pack_id": "ctx-test",
            "query": message,
            "memory_context": base_context,
            "assistant_dialogue": assistant_context or [],
            "agenda_context": [],
            "source_context": source_context,
            "task_context": task_context,
            "included_event_ids": ["event-user", "alice-memory", "trace-1"],
            "included_memory_ids": ["alice-memory"],
            "included_agenda_ids": [],
            "token_budget": {"input_used": 123},
            "sections": [{"name": "source_context", "tokens_used": 12, "items": source_context}],
            "excluded": [],
            "warnings": [],
            "reason": "scoped context pack",
        }

    class FakeGateway:
        async def chat(self, messages, temperature=0.4):
            assert "ctx-test" in messages[1]["content"]
            return ModelAnswer(
                text="可以，我会基于 Alice 的当前 WhatsApp 上下文处理。",
                provider_id="test-provider",
                trace={"fallback_from": []},
            )

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: object())
    monkeypatch.setattr(main, "persist_assistant_turn", fake_persist_turn, raising=False)
    monkeypatch.setattr(main, "retrieve_context", fake_retrieve_context, raising=False)
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_agenda_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_task_context", fake_task_context, raising=False)
    monkeypatch.setattr(main, "persist_context_snapshot", fake_snapshot, raising=False)
    monkeypatch.setattr(main, "build_context_pack", fake_context_pack, raising=False)
    monkeypatch.setattr(main, "model_gateway", lambda: FakeGateway())

    response = TestClient(main.app).post(
        "/api/chat",
        headers={"x-par-password": "secret"},
        json={
            "message": "帮我回复 Alice 可以",
            "conversation_id": "conv-scope",
            "ui_state": {
                "source_type": "whatsapp",
                "counterparty_ids": ["Alice"],
                "current_source": {
                    "source_type": "whatsapp",
                    "conversation_id": "wa-alice",
                    "content": "Alice: Friday works for me.",
                },
            },
        },
    )

    assert response.status_code == 200
    assert retrieve_limits[0][0] == 12
    assert retrieve_limits[0][1]["counterparty_ids"] == ["alice"]
    assert snapshots[0]["final_model_answer_event_id"] == "event-assistant"


def test_chat_endpoint_passes_literal_identifier_invoice_context_to_model(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.model_gateway import ModelAnswer

    model_user_messages: list[str] = []

    def fake_persist_turn(conn, redis_client, role, content, conversation_id=None, client_type="web", **kwargs):
        return {
            "conversation_id": conversation_id or "conv-invoice",
            "turn_id": f"turn-{role}",
            "event_id": f"event-{role}",
        }

    invoice_context = [
        {
            "layer": "literal_identifier_recall",
            "matched_identifier": "INV-RG-1001",
            "source": "gmail",
            "event_type": "email",
            "raw_data": {
                "subject": "Invoice INV-RG-1001 due",
                "body": "Invoice INV-RG-1001 for AMOUNT_1 is due next Tuesday.",
            },
            "summary": "Invoice INV-RG-1001 for AMOUNT_1 is due next Tuesday.",
            "released_private_evidence": {
                "release_policy": "first_party_literal_identifier_read_minimal_fields",
                "release_reason": "The user asked a read-only or confirmation-gated question about an exact private identifier.",
                "fields": {
                    "matched_identifier": "INV-RG-1001",
                    "amounts": ["1200 USD"],
                    "time_clues": ["Invoice INV-RG-1001 for 1200 USD is due next Tuesday."],
                    "resolved_time_clues": ["2026-06-23 周二 for 'next Tuesday'; source_event_timestamp=2026-06-16T16:00:00+08:00"],
                    "matching_lines": ["Invoice INV-RG-1001 for 1200 USD is due next Tuesday."],
                },
            },
            "source_event_ids": ["invoice-event"],
        }
    ]

    class FakeGateway:
        async def chat(self, messages, temperature=0.4):
            assert "due" in messages[0]["content"]
            assert "已逾期" in messages[0]["content"]
            model_user_messages.append(messages[1]["content"])
            return ModelAnswer(
                text="找到 INV-RG-1001：AMOUNT_1，下周二到期。我不会付款，只列出信息。",
                provider_id="test-provider",
                trace={"fallback_from": []},
            )

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: object())
    monkeypatch.setattr(main, "persist_assistant_turn", fake_persist_turn, raising=False)
    monkeypatch.setattr(main, "find_cached_assistant_response", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "retrieve_context", lambda *args, **kwargs: invoice_context, raising=False)
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_current_source_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_agenda_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_task_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "safe_persist_model_request_trace", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "model_gateway", lambda: FakeGateway())

    response = TestClient(main.app).post(
        "/api/chat",
        headers={"x-par-password": "secret"},
        json={
            "message": "帮我处理 INV-RG-1001，但不要付款，只告诉我你找到了什么。",
            "conversation_id": "conv-invoice",
        },
    )

    assert response.status_code == 200
    assert "INV-RG-1001" in model_user_messages[0]
    assert "1200 USD" in model_user_messages[0]
    assert "2026-06-23 周二" in model_user_messages[0]
    assert "AMOUNT_1" in model_user_messages[0]
    assert "不要付款" in model_user_messages[0]
    assert response.json()["context_pack"]["memory_context_count"] == 1


def test_chat_endpoint_does_not_treat_past_gmail_meeting_as_upcoming(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    persisted_answers: list[str] = []

    def fake_persist_turn(conn, redis_client, role, content, conversation_id=None, client_type="web", **kwargs):
        if role == "assistant":
            persisted_answers.append(content)
        return {
            "conversation_id": conversation_id or "conv-agenda",
            "turn_id": f"turn-{role}",
            "event_id": f"event-{role}",
        }

    past_agenda = [
        {
            "id": "gmail-past-meeting",
            "title": "明天3点记得在腾讯会议上开线上会议",
            "status": "scheduled",
            "certainty": "fuzzy",
            "time_window": {
                "start": "2026-06-25T03:00:00+08:00",
                "display": "2026-06-25 周四 03:00",
                "source_event_timestamp": "2026-06-24T20:17:41+08:00",
            },
            "metadata": {"source": "gmail"},
            "time_status": "past",
        }
    ]

    class GatewayShouldNotRun:
        async def chat(self, messages, temperature=0.4):
            raise AssertionError("past-only agenda answer should be deterministic")

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: object())
    monkeypatch.setattr(main, "persist_assistant_turn", fake_persist_turn, raising=False)
    monkeypatch.setattr(main, "find_cached_assistant_response", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "retrieve_context", lambda *args, **kwargs: [], raising=False)
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_current_source_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_agenda_context", lambda *args, **kwargs: past_agenda)
    monkeypatch.setattr(main, "retrieve_active_task_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "safe_persist_model_request_trace", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "model_gateway", lambda: GatewayShouldNotRun())

    response = TestClient(main.app).post(
        "/api/chat",
        headers={"x-par-password": "secret"},
        json={"message": "最近有要开的会吗", "conversation_id": "conv-agenda"},
    )

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert "没有找到未开始的会议" in answer
    assert "2026-06-25 周四 03:00" in answer
    assert "已过去" in answer
    assert "建议准备" not in answer
    assert persisted_answers == [answer]


def test_chat_endpoint_returns_503_when_model_times_out(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.model_gateway import ModelGatewayError

    def fake_persist_turn(conn, redis_client, role, content, conversation_id=None, client_type="web", **kwargs):
        return {
            "conversation_id": conversation_id or "conv-timeout",
            "turn_id": f"turn-{role}",
            "event_id": f"event-{role}",
        }

    class FailingGateway:
        async def chat(self, messages, temperature=0.4):
            raise ModelGatewayError(
                "primary timeout",
                [{"provider_id": "primary", "error_type": "timeout", "error": "model timed out"}],
            )

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: object())
    monkeypatch.setattr(main, "persist_assistant_turn", fake_persist_turn, raising=False)
    monkeypatch.setattr(main, "retrieve_context", lambda message, limit, request_scope=None: [])
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_agenda_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_task_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "model_gateway", lambda: FailingGateway())

    response = TestClient(main.app, raise_server_exceptions=False).post(
        "/api/chat",
        headers={"x-par-password": "secret"},
        json={"message": "hello", "conversation_id": "conv-timeout"},
    )

    assert response.status_code == 503
    assert "model_unavailable" in response.text
    assert "模型服务暂时不可用" in response.text


def json_text(value):
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


def test_persist_assistant_turn_creates_private_event_turn_and_queue(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed = []
    queued = []

    class Cursor:
        rowcount = 1

        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchone(self):
            return self.rows[0] if self.rows else None

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            return Cursor()

    class Redis:
        def xadd(self, stream, fields):
            queued.append((stream, fields))

    result = main.persist_assistant_turn(
        Conn(),
        Redis(),
        role="user",
        content="帮我盯一下周末和 Alex 见面的事",
        conversation_id=None,
        client_type="android",
    )

    combined_sql = "\n".join(sql for sql, _ in executed)
    assert "INSERT INTO assistant_conversations" in combined_sql
    assert "INSERT INTO events" in combined_sql
    assert "INSERT INTO assistant_turns" in combined_sql
    assert result["conversation_id"]
    assert result["event_id"]
    assert queued[0][0] == "events:raw"
    queued_payload = queued[0][1]
    assert queued_payload["source"] == "nomi_chat"
    assert queued_payload["event_type"] == "user_message"
    assert "周末和 Alex" in queued_payload["raw_data"]


def test_persist_assistant_turn_reuses_existing_client_request_turn(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed = []

    class Cursor:
        def __init__(self, row=None):
            self.row = row

        def fetchone(self):
            return self.row

    class Conn:
        def execute(self, sql, params=()):
            executed.append((" ".join(sql.split()), params))
            if "FROM assistant_turns" in sql:
                return Cursor(
                    (
                        "turn-existing",
                        "11111111-1111-1111-1111-111111111111",
                        "event-existing",
                        "assistant",
                    )
                )
            raise AssertionError("existing idempotent turn should skip inserts")

    class Redis:
        def xadd(self, stream, fields):
            raise AssertionError("existing idempotent turn should not enqueue a duplicate event")

    result = main.persist_assistant_turn(
        Conn(),
        Redis(),
        role="assistant",
        content="pong",
        conversation_id="11111111-1111-1111-1111-111111111111",
        client_type="android",
        tool_call_id=main.assistant_turn_idempotency_key("android-req-1", "assistant"),
    )

    assert result == {
        "conversation_id": "11111111-1111-1111-1111-111111111111",
        "turn_id": "turn-existing",
        "event_id": "event-existing",
        "role": "assistant",
        "dialogue_memory_enqueue": {
            "policy": "skipped_duplicate",
            "reason": "client_request_id_reused",
            "pending_turn_count": 0,
            "pending_round_count": 0,
            "batch_created": False,
            "batch_id": None,
            "batch_event_id": None,
        },
    }
    assert len(executed) == 1
    assert executed[0][1] == ("client_request:android-req-1:assistant", "assistant")


def test_chat_endpoint_persists_turns_uses_context_pack_and_returns_trace(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.model_gateway import ModelAnswer

    persisted_turns = []
    snapshots = []

    def fake_persist_turn(conn, redis_client, role, content, conversation_id=None, client_type="web", **kwargs):
        persisted_turns.append({"role": role, "content": content, "conversation_id": conversation_id})
        return {
            "conversation_id": conversation_id or "conv-1",
            "turn_id": f"turn-{role}",
            "event_id": f"event-{role}",
        }

    def fake_context_pack(message, base_context, assistant_context=None, conversation_id=None, **kwargs):
        assistant_text = "\n".join(item.get("content", "") for item in assistant_context or [])
        assert [item.get("role") for item in assistant_context or []] == ["assistant"]
        assert "核对成本与利润率" in assistant_text
        assert assistant_text.count("需要") == 1
        return {
            "query": message,
            "memory_context": base_context,
            "assistant_dialogue": [{"layer": "assistant_dialogue", "content": assistant_text}],
            "included_event_ids": ["event-user"],
            "reason": "bounded context pack: active conversation and scoped memory",
        }

    def fake_snapshot(conn, event_id, context_type, context_pack):
        snapshots.append((event_id, context_type, context_pack["included_event_ids"]))

    class FakeGateway:
        async def chat(self, messages, temperature=0.4):
            assert "bounded context pack" in messages[1]["content"]
            assert "核对成本与利润率" in messages[1]["content"]
            return ModelAnswer(
                text="好的，我会继续按“核对成本与利润率”这个方向处理。",
                provider_id="test-provider",
                trace={"fallback_from": []},
            )

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class Redis:
        pass

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: Redis())
    monkeypatch.setattr(main, "retrieve_context", lambda message, limit, request_scope=None: [{"layer": "entity_graph", "subject": "alex"}])
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "persist_assistant_turn", fake_persist_turn, raising=False)
    monkeypatch.setattr(main, "build_context_pack", fake_context_pack, raising=False)
    monkeypatch.setattr(main, "persist_context_snapshot", fake_snapshot, raising=False)
    monkeypatch.setattr(main, "model_gateway", lambda: FakeGateway())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        headers={"x-par-password": "secret"},
        json={
            "message": "需要",
            "limit": 8,
            "conversation_id": "conv-1",
            "client_context_delta": [
                {"role": "assistant", "content": "需要我帮你核对成本与利润率数据吗？"},
                {"role": "user", "content": "需要"},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "conv-1"
    assert body["answer"] == "好的，我会继续按“核对成本与利润率”这个方向处理。"
    assert body["context_pack"]["included_event_ids"] == ["event-user"]
    assert [item["role"] for item in persisted_turns] == ["user", "assistant"]
    assert persisted_turns[0]["content"] == "需要"
    assert snapshots == [("event-user", "chat_response", ["event-user"])]


def test_chat_endpoint_adds_career_context_for_job_queries(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.model_gateway import ModelAnswer

    career_context = {
        "profiles": [{"headline": "后端工程师", "skills": ["Java", "Spring Boot"]}],
        "career_resumes": [{"filename": "后端-范小刚.pdf", "parsed_text_summary": "Java 后端开发经验"}],
        "opportunities": [{"title": "Backend Engineer", "company": "Example AI"}],
        "linkedin": {"collection_status": "healthy"},
    }

    def fake_persist_turn(conn, redis_client, role, content, conversation_id=None, client_type="web", **kwargs):
        return {
            "conversation_id": conversation_id or "conv-job",
            "turn_id": f"turn-{role}",
            "event_id": f"event-{role}",
        }

    def fake_context_pack(message, base_context, assistant_context=None, conversation_id=None, **kwargs):
        assert kwargs.get("career_context") == career_context
        return {
            "query": message,
            "memory_context": base_context,
            "assistant_dialogue": assistant_context or [],
            "career_context": kwargs.get("career_context"),
            "included_event_ids": ["event-user"],
            "reason": "bounded context pack with career context",
        }

    class FakeGateway:
        async def chat(self, messages, temperature=0.4):
            assert "career_context" in messages[1]["content"]
            assert "后端-范小刚.pdf" in messages[1]["content"]
            assert "Backend Engineer" in messages[1]["content"]
            return ModelAnswer(
                text="我会基于你的后端简历筛选 Backend Engineer 机会，并优先检查 LinkedIn。",
                provider_id="test-provider",
                trace={"fallback_from": []},
            )

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: object())
    monkeypatch.setattr(main, "persist_assistant_turn", fake_persist_turn, raising=False)
    monkeypatch.setattr(main, "retrieve_current_source_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_agenda_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_task_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_memory_layer_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_career_chat_context", lambda *args, **kwargs: career_context, raising=False)
    monkeypatch.setattr(main, "build_context_pack", fake_context_pack, raising=False)
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "model_gateway", lambda: FakeGateway())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        headers={"x-par-password": "secret"},
        json={"message": "帮我找找看有没有适合我的工作机会", "conversation_id": "conv-job"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "后端简历" in body["answer"]


def test_job_query_blocks_linkedin_job_search_when_linkedin_is_not_connected(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    queued = []
    stored = {}

    class Redis:
        def get(self, key):
            return None

        def setex(self, key, ttl, value):
            stored[key] = (ttl, value)

        def rpush(self, key, value):
            queued.append((key, value))
            return 1

    monkeypatch.setattr(main, "redis_client", lambda: Redis())

    result = main.maybe_queue_linkedin_job_search_for_chat(
        "帮我找找看有没有适合我的工作机会",
        {
            "profiles": [
                {
                    "career_profile_id": "career_profile_backend",
                    "headline": "后端工程师",
                    "target_roles": ["Backend Engineer"],
                    "target_locations": ["Singapore"],
                    "skills": ["Python", "PostgreSQL"],
                }
            ],
            "career_resumes": [],
            "opportunities": [],
            "linkedin": {"collection_status": "degraded", "browser_login_status": "logged_out"},
        },
    )

    assert result["status"] == "blocked"
    assert result["source"] == "linkedin"
    assert result["reason"] == "linkedin_login_required"
    assert result["collection_status"] == "degraded"
    assert result["browser_login_status"] == "logged_out"
    assert result["external_side_effect"] is False
    assert queued == []
    assert stored == {}


def test_job_query_uses_existing_linkedin_opportunities_without_fresh_search(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    queued = []
    stored = {}

    class Redis:
        def get(self, key):
            return None

        def setex(self, key, ttl, value):
            stored[key] = (ttl, value)

        def rpush(self, key, value):
            queued.append((key, value))
            return 1

    monkeypatch.setattr(main, "redis_client", lambda: Redis())

    result = main.maybe_queue_linkedin_job_search_for_chat(
        "Recommend suitable jobs from LinkedIn based on my resume",
        {
            "profiles": [{"career_profile_id": "career_profile_backend", "headline": "Java 后端架构"}],
            "career_resumes": [{"resume_id": "resume-1", "filename": "后端-范小刚.pdf"}],
            "opportunities": [
                {
                    "id": "linkedin_search_quantgroup",
                    "source": "linkedin_browser_observation",
                    "title": "AI Native 全栈工程师",
                    "company": "QuantGroup",
                    "url": "https://www.linkedin.com/jobs/search/?currentJobId=4387208771",
                    "fit_score": 0.92,
                }
            ],
            "linkedin": {"collection_status": "healthy", "browser_login_status": "logged_in"},
        },
    )

    assert result == {}
    assert queued == []
    assert stored == {}


def test_deterministic_career_answer_recommends_existing_linkedin_opportunities_with_links(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    answer = main.deterministic_career_answer(
        "基于最新 LinkedIn 真实搜索结果，给我推荐最适合的3个工作机会。每个都要有岗位总结、推荐理由和可以打开的链接。",
        {
            "chat_route": {"intent": "job_query"},
            "career_context": {
                "profiles": [{"headline": "Java/Go 后端架构师", "skills": ["Java", "Go", "AI Agent"]}],
                "career_resumes": [{"resume_id": "resume-1", "filename": "后端-范小刚.pdf"}],
                "opportunities": [
                    {
                        "id": "linkedin_job_noise",
                        "title": "0 notifications",
                        "company": "2",
                        "location": "China",
                        "url": "https://www.linkedin.com/jobs/view/4378789245/",
                        "fit_score": 0.99,
                        "payload": {"summary": "2 的 0 notifications，地点 China。"},
                    },
                    {
                        "id": "linkedin_search_a1",
                        "title": "后端开发工程师（AI Agent系统） | Backend Engineer, AI Systems",
                        "company": "A1",
                        "location": "China (Remote)",
                        "url": "https://www.linkedin.com/jobs/view/4378789245/",
                        "fit_score": 0.95,
                        "payload": {
                            "summary": "A1 的 AI Agent 后端岗位，地点 China (Remote)。匹配项：AI Agent、后端、Go。缺口：暂未发现明显缺口。",
                            "matched_requirements": ["AI Agent", "后端", "Go"],
                            "gap_requirements": [],
                        },
                    },
                    {
                        "id": "linkedin_search_bybit",
                        "title": "Backend Development Engineer（GO)",
                        "company": "Bybit",
                        "location": "China (Remote)",
                        "url": "https://www.linkedin.com/jobs/view/4404787524/",
                        "fit_score": 0.92,
                        "payload": {
                            "matched_requirements": ["Go", "高并发"],
                            "gap_requirements": ["金融交易领域"],
                        },
                    },
                ],
                "linkedin": {"collection_status": "healthy", "browser_login_status": "logged_in"},
            },
        },
    )

    assert answer is not None
    assert "正在采集" not in answer
    assert "A1" in answer
    assert "Bybit" in answer
    assert "0 notifications" not in answer
    assert "https://www.linkedin.com/jobs/view/4378789245/" in answer
    assert "https://www.linkedin.com/jobs/view/4404787524/" in answer
    assert "推荐理由" in answer


def test_deterministic_career_application_answer_blocks_submit_and_resolves_target(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    context_pack = {
        "chat_route": {"intent": "job_query"},
        "career_context": {
            "profiles": [{"headline": "Java/Go 后端架构师", "skills": ["Java", "Go", "AI Agent"]}],
            "career_resumes": [{"resume_id": "resume-1", "filename": "后端-范小刚.pdf"}],
            "opportunities": [
                {
                    "id": "linkedin_search_a1",
                    "title": "后端开发工程师（AI Agent系统） | Backend Engineer, AI Systems",
                    "company": "A1",
                    "location": "China (Remote)",
                    "url": "https://www.linkedin.com/jobs/view/4378789245/",
                    "fit_score": 0.95,
                    "payload": {
                        "summary": "A1 的 AI Agent 后端岗位，地点 China (Remote)。匹配项：AI Agent、后端、Go。",
                        "matched_requirements": ["AI Agent", "后端", "Go"],
                    },
                },
                {
                    "id": "linkedin_search_bybit",
                    "title": "Backend Development Engineer（GO)",
                    "company": "Bybit",
                    "location": "China (Remote)",
                    "url": "https://www.linkedin.com/jobs/view/4404787524/",
                    "fit_score": 0.92,
                    "payload": {"matched_requirements": ["Go", "高并发"]},
                },
            ],
            "linkedin": {"collection_status": "healthy", "browser_login_status": "logged_in"},
        },
    }

    answer = main.deterministic_career_application_answer("Help me apply to the A1 LinkedIn job", context_pack)

    assert answer is not None
    assert "A1" in answer
    assert "https://www.linkedin.com/jobs/view/4378789245/" in answer
    assert "Bybit" not in answer
    assert "未执行" in answer or "不会直接" in answer
    assert "Apply/Submit" in answer
    assert "确认" in answer
    assert "优先推荐" not in answer
    assert main.deterministic_career_answer("Help me apply to the A1 LinkedIn job", context_pack) is None


def test_career_application_answer_uses_recent_dialogue_linkedin_job_when_board_omits_target(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    context_pack = {
        "chat_route": {"intent": "job_query"},
        "assistant_dialogue": [
            {
                "role": "assistant",
                "content": (
                    "我基于已采集到的 LinkedIn 岗位推荐：\n"
                    "1. [后端开发工程师（AI Agent系统） | Backend Engineer, AI Systems](https://www.linkedin.com/jobs/view/4378789245/)\n"
                    "公司/地点：A1 · China (Remote)\n"
                    "匹配度：95%\n"
                    "推荐理由：匹配你的 AI Agent、后端、Go。"
                ),
            }
        ],
        "career_context": {
            "profiles": [{"headline": "Java/Go 后端架构师", "skills": ["Java", "Go", "AI Agent"]}],
            "career_resumes": [{"resume_id": "resume-1", "filename": "后端-范小刚.pdf"}],
            "opportunities": [
                {
                    "id": "linkedin_search_bybit",
                    "title": "Backend Development Engineer（GO)",
                    "company": "Bybit",
                    "location": "China (Remote)",
                    "url": "https://www.linkedin.com/jobs/view/4404787524/",
                    "fit_score": 0.92,
                    "payload": {"matched_requirements": ["Go", "高并发"]},
                }
            ],
            "linkedin": {"collection_status": "healthy", "browser_login_status": "logged_in"},
        },
    }

    answer = main.deterministic_career_application_answer("帮我申请 A1 这个 LinkedIn 岗位", context_pack)

    assert answer is not None
    assert "A1" in answer
    assert "https://www.linkedin.com/jobs/view/4378789245/" in answer
    assert "Bybit" not in answer
    assert "匹配依据：匹配你的 AI Agent、后端、Go。" in answer
    assert "我基于已采集到的 LinkedIn 岗位推荐" not in answer
    assert "未执行" in answer
    assert "确认" in answer


def test_career_context_excludes_stale_opportunities_after_new_resume(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    old = datetime(2026, 6, 20, tzinfo=timezone.utc)
    fresh = datetime(2026, 7, 2, tzinfo=timezone.utc)
    stale_job = (
        "job-old",
        "linkedin",
        "AI Product Manager",
        "Old Company",
        "Remote",
        "https://www.linkedin.com/jobs/view/old",
        "active",
        0.91,
        ["LLM product"],
        [],
        {},
        old,
        old,
    )
    fresh_job = (
        "job-fresh",
        "linkedin",
        "Backend Engineer",
        "Fresh Company",
        "Remote",
        "https://www.linkedin.com/jobs/view/fresh",
        "active",
        0.88,
        ["Java", "distributed systems"],
        [],
        {},
        fresh,
        fresh,
    )

    assert main.filter_stale_career_opportunity_rows([stale_job, fresh_job], fresh) == [fresh_job]


def test_chat_endpoint_exposes_linkedin_reconnect_status_for_job_queries(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.model_gateway import ModelAnswer

    career_context = {
        "profiles": [{"target_roles": ["Backend Engineer"], "target_locations": ["Singapore"]}],
        "career_resumes": [],
        "opportunities": [],
        "linkedin": {"collection_status": "degraded", "browser_login_status": "logged_out"},
    }
    captured_search_status = {}

    def fake_persist_turn(conn, redis_client, role, content, conversation_id=None, client_type="web", **kwargs):
        return {
            "conversation_id": conversation_id or "conv-job",
            "turn_id": f"turn-{role}",
            "event_id": f"event-{role}",
        }

    def fake_context_pack(message, base_context, assistant_context=None, conversation_id=None, **kwargs):
        career = kwargs.get("career_context")
        captured_search_status.update(career.get("linkedin_job_search") or {})
        return {
            "query": message,
            "memory_context": base_context,
            "assistant_dialogue": assistant_context or [],
            "career_context": career,
            "included_event_ids": ["event-user"],
            "reason": "bounded context pack with linkedin search status",
        }

    class FakeGateway:
        async def chat(self, messages, temperature=0.4):
            assert "linkedin_job_search" in messages[1]["content"]
            assert "linkedin_login_required" in messages[1]["content"]
            return ModelAnswer(
                text="我可以基于你的画像准备搜索条件，但 LinkedIn 现在需要重新连接，连接恢复后才能采集真实岗位。",
                provider_id="test-provider",
                trace={"fallback_from": []},
            )

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: object())
    monkeypatch.setattr(main, "persist_assistant_turn", fake_persist_turn, raising=False)
    monkeypatch.setattr(main, "retrieve_current_source_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_agenda_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_task_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_memory_layer_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_career_chat_context", lambda *args, **kwargs: career_context, raising=False)
    monkeypatch.setattr(main, "build_context_pack", fake_context_pack, raising=False)
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "model_gateway", lambda: FakeGateway())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        headers={"x-par-password": "secret"},
        json={"message": "帮我找找看有没有适合我的工作机会", "conversation_id": "conv-job"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "重新连接" in body["answer"]
    assert captured_search_status["status"] == "blocked"
    assert captured_search_status["reason"] == "linkedin_login_required"
    assert captured_search_status["external_side_effect"] is False


def test_chat_endpoint_reuses_cached_assistant_answer_for_duplicate_client_request(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    persisted_turns = []

    def fake_persist_turn(conn, redis_client, role, content, conversation_id=None, client_type="web", **kwargs):
        persisted_turns.append({"role": role, "content": content, "tool_call_id": kwargs.get("tool_call_id")})
        return {
            "conversation_id": conversation_id or "conv-duplicate",
            "turn_id": f"turn-{role}",
            "event_id": f"event-{role}",
        }

    def fake_cached_response(conn, client_request_id):
        assert client_request_id == "android-duplicate-1"
        return {
            "answer": "去重正常。",
            "conversation_id": "conv-duplicate",
            "turn_id": "turn-assistant-existing",
            "event_id": "event-assistant-existing",
        }

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FailingGateway:
        async def chat(self, *args, **kwargs):
            raise AssertionError("duplicate request must not call model gateway")

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: object())
    monkeypatch.setattr(main, "persist_assistant_turn", fake_persist_turn, raising=False)
    monkeypatch.setattr(main, "find_cached_assistant_response", fake_cached_response, raising=False)
    monkeypatch.setattr(main, "model_gateway", lambda: FailingGateway())

    response = TestClient(main.app).post(
        "/api/chat",
        headers={"x-par-password": "secret"},
        json={
            "message": "ping",
            "conversation_id": "conv-duplicate",
            "client_request_id": "android-duplicate-1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "去重正常。"
    assert body["duplicate"] is True
    assert body["conversation_id"] == "conv-duplicate"
    assert [item["role"] for item in persisted_turns] == ["user"]


def test_chat_messages_alias_uses_same_chat_pipeline(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.model_gateway import ModelAnswer

    def fake_persist_turn(conn, redis_client, role, content, conversation_id=None, client_type="web", **kwargs):
        return {
            "conversation_id": conversation_id or "conv-alias",
            "turn_id": f"turn-{role}",
            "event_id": f"event-{role}",
        }

    def fake_context_pack(message, base_context, assistant_context=None, conversation_id=None, **kwargs):
        return {
            "query": message,
            "memory_context": base_context,
            "assistant_dialogue": [],
            "agenda_context": [],
            "included_event_ids": ["event-user"],
            "included_agenda_ids": [],
            "reason": "bounded context pack: alias route",
        }

    class FakeGateway:
        async def chat(self, messages, temperature=0.4):
            assert "alias route" in messages[1]["content"]
            return ModelAnswer(
                text="别名路由也走同一个对话管线。",
                provider_id="test-provider",
                trace={"fallback_from": []},
            )

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: object())
    monkeypatch.setattr(main, "retrieve_context", lambda message, limit, request_scope=None: [])
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_agenda_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "persist_assistant_turn", fake_persist_turn, raising=False)
    monkeypatch.setattr(main, "build_context_pack", fake_context_pack, raising=False)
    monkeypatch.setattr(main, "persist_context_snapshot", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "model_gateway", lambda: FakeGateway())

    response = TestClient(main.app).post(
        "/api/chat/messages",
        headers={"x-par-password": "secret"},
        json={"message": "走兼容消息接口", "conversation_id": "conv-alias"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "conv-alias"
    assert body["answer"] == "别名路由也走同一个对话管线。"
    assert body["context_pack"]["included_event_ids"] == ["event-user"]


def test_chat_endpoint_routes_ppt_artifact_request_to_task_without_model(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    persisted_turns = []
    persisted_tasks = []
    snapshots = []

    def fake_persist_turn(conn, redis_client, role, content, conversation_id=None, client_type="web", **kwargs):
        persisted_turns.append(
            {
                "role": role,
                "content": content,
                "conversation_id": conversation_id,
                "client_request_id": kwargs.get("client_request_id"),
            }
        )
        return {
            "conversation_id": conversation_id or "conv-artifact-1",
            "turn_id": f"turn-{role}",
            "event_id": f"event-{role}",
        }

    def fake_current_source_context(*args, **kwargs):
        return [
            {
                "event_id": "evt_whatsapp_wang_1",
                "source": "whatsapp",
                "actor": "王总",
                "timestamp": "2026-07-06T10:30:00+08:00",
                "content": "王总：本次客户汇报重点是上线计划、预算和风险。",
            }
        ]

    def fake_persist_artifact_task_run(
        conn,
        *,
        conversation_id,
        source_message_event_id,
        message,
        client_request_id,
        payload,
    ):
        assert conversation_id == "conv-artifact-1"
        assert source_message_event_id == "event-user"
        assert client_request_id == "artifact-req-1"
        assert payload["route"]["task_type"] == "artifact_creation"
        task = {
            "task_run_id": "task_artifact_1",
            "task_type": "artifact_creation",
            "artifact_type": payload["route"]["artifact_type"],
            "pipeline_id": "ppt_creation_pipeline",
            "route_type": "artifact_task",
            "status": "waiting_user",
            "title": "依据王总资料生成 PPT",
            "source_event_ids": [item["evidence_id"] for item in payload["evidence_pack"]["items"]],
            "payload": payload,
        }
        persisted_tasks.append(task)
        return task

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class GatewayShouldNotRun:
        async def chat(self, *args, **kwargs):
            raise AssertionError("artifact task requests must not use normal chat generation")

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: object())
    monkeypatch.setattr(main, "find_cached_assistant_response", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "persist_assistant_turn", fake_persist_turn, raising=False)
    monkeypatch.setattr(main, "retrieve_current_source_context", fake_current_source_context, raising=False)
    monkeypatch.setattr(main, "retrieve_context", lambda *args, **kwargs: [], raising=False)
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda *args, **kwargs: [], raising=False)
    monkeypatch.setattr(main, "retrieve_active_agenda_context", lambda *args, **kwargs: [], raising=False)
    monkeypatch.setattr(main, "persist_artifact_task_run", fake_persist_artifact_task_run, raising=False)
    monkeypatch.setattr(
        main,
        "persist_context_snapshot",
        lambda conn, event_id, route_type, context_pack: snapshots.append(
            (event_id, route_type, context_pack)
        ),
        raising=False,
    )
    monkeypatch.setattr(main, "safe_persist_context_route_trace", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(main, "model_gateway", lambda: GatewayShouldNotRun())

    response = TestClient(main.app).post(
        "/api/chat",
        headers={"x-par-password": "secret"},
        json={
            "message": "帮我依据刚刚王总给的资料，写一份 PPT",
            "conversation_id": "conv-artifact-1",
            "client_request_id": "artifact-req-1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["task"]["task_run_id"] == "task_artifact_1"
    assert body["task"]["task_type"] == "artifact_creation"
    assert body["task"]["artifact_type"] == "pptx"
    assert body["task"]["status"] == "waiting_user"
    assert body["context_pack"]["task_route"]["message_kind"] == "task_request"
    assert body["context_pack"]["task_route"]["task_type"] == "artifact_creation"
    assert body["context_pack"]["artifact_evidence_count"] == 1
    assert "PPT" in body["answer"]
    assert "编造" not in body["answer"]
    assert persisted_turns[-1]["role"] == "assistant"
    assert persisted_tasks[0]["source_event_ids"] == ["evt_whatsapp_wang_1"]
    assert snapshots[-1][1] == "artifact_task"


def test_chat_history_endpoint_restores_latest_conversation_when_client_has_no_id(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from datetime import datetime, timezone
    import uuid

    from app import main

    conversation_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    executed = []

    class Cursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            compact_sql = " ".join(sql.split())
            executed.append((compact_sql, params))
            if "SELECT conversation_id FROM assistant_turns" in compact_sql:
                assert params == (1,)
                return Cursor([(conversation_id,)])
            if "FROM assistant_turns" in compact_sql and "WHERE conversation_id = %s" in compact_sql:
                assert params == (conversation_id, 20)
                return Cursor(
                    [
                        (
                            uuid.UUID("22222222-2222-2222-2222-222222222222"),
                            conversation_id,
                            "user",
                            "需要",
                            uuid.UUID("33333333-3333-3333-3333-333333333333"),
                            None,
                            None,
                            datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
                            None,
                        ),
                        (
                            uuid.UUID("44444444-4444-4444-4444-444444444444"),
                            conversation_id,
                            "assistant",
                            "好的，我会继续核对成本与利润率。",
                            uuid.UUID("55555555-5555-5555-5555-555555555555"),
                            None,
                            None,
                            datetime(2026, 5, 29, 8, 0, 5, tzinfo=timezone.utc),
                            datetime(2026, 5, 29, 8, 0, 5, tzinfo=timezone.utc),
                        ),
                    ]
                )
            if "FROM assistant_turn_attachments" in compact_sql:
                assert params == ([uuid.UUID("22222222-2222-2222-2222-222222222222")],)
                return Cursor([])
            raise AssertionError(f"unexpected SQL: {compact_sql}")

    monkeypatch.setattr(main, "db", lambda: Conn())

    response = TestClient(main.app).get(
        "/api/chat/history?limit=20",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["messages"][0]["id"] == "22222222-2222-2222-2222-222222222222"
    assert body["messages"][0]["created_at"] == "2026-05-29T08:00:00+00:00"
    assert body["messages"][1]["id"] == "44444444-4444-4444-4444-444444444444"
    assert body["messages"][1]["created_at"] == "2026-05-29T08:00:05+00:00"
    assert body["conversation_id"] == str(conversation_id)
    assert [message["role"] for message in body["messages"]] == ["user", "assistant"]
    assert body["messages"][0]["content"] == "需要"
    assert body["messages"][1]["content"] == "好的，我会继续核对成本与利润率。"
    assert sum("FROM assistant_turn_attachments" in sql for sql, _ in executed) == 1
    assert any("SELECT conversation_id FROM assistant_turns" in sql for sql, _ in executed)
