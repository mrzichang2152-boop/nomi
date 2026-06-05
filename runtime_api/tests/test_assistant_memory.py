import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_session_search_boosts_prior_nomi_question_for_short_reply():
    from app.assistant_memory import build_session_search_context

    context = build_session_search_context(
        current_message="需要",
        conversation_id="conv-margin",
        turns=[
            {
                "turn_id": "turn-user-1",
                "role": "user",
                "content": "PHONE_1 客户报价什么时候截止？",
                "conversation_id": "conv-margin",
            },
            {
                "turn_id": "turn-assistant-1",
                "role": "assistant",
                "content": "根据现有记录，截止时间是周五 18:00。需要我帮你核对成本与利润率吗？",
                "conversation_id": "conv-margin",
            },
            {
                "turn_id": "turn-user-current",
                "role": "user",
                "content": "需要",
                "conversation_id": "conv-margin",
            },
        ],
        active_tasks=[
            {
                "task_id": "task-margin",
                "title": "PHONE_1 报价利润率核对",
                "status": "waiting_for_user",
                "conversation_id": "conv-margin",
            }
        ],
        token_budget=2000,
    )

    included_text = "\n".join(item["content"] for item in context["included_turns"])
    assert "核对成本与利润率" in included_text
    assert "turn-user-current" not in [item["turn_id"] for item in context["included_turns"]]
    assert context["short_reply_resolution"]["resolved"] is True
    assert context["short_reply_resolution"]["prior_question_turn_id"] == "turn-assistant-1"
    assert context["active_tasks"][0]["task_id"] == "task-margin"
    assert context["token_budget"]["used"] > 0
    assert "short reply" in context["reason"]


def test_session_search_respects_token_budget_and_keeps_prior_question():
    from app.assistant_memory import build_session_search_context

    long_turns = [
        {
            "turn_id": f"old-{index}",
            "role": "user",
            "content": "无关旧对话 " * 80,
            "conversation_id": "conv-margin",
        }
        for index in range(8)
    ]
    long_turns.append(
        {
            "turn_id": "turn-assistant-question",
            "role": "assistant",
            "content": "需要我帮你核对成本与利润率数据吗？",
            "conversation_id": "conv-margin",
        }
    )

    context = build_session_search_context(
        current_message="需要",
        conversation_id="conv-margin",
        turns=long_turns,
        active_tasks=[],
        token_budget=120,
    )

    ids = [item["turn_id"] for item in context["included_turns"]]
    assert "turn-assistant-question" in ids
    assert context["token_budget"]["used"] <= context["token_budget"]["limit"]
    assert context["excluded"]


def test_assistant_memory_schema_sql_creates_curated_tables():
    from app.assistant_memory import assistant_memory_schema_sql

    combined = "\n".join(" ".join(sql.split()) for sql in assistant_memory_schema_sql())

    assert "CREATE TABLE IF NOT EXISTS assistant_profile_memories" in combined
    assert "CREATE TABLE IF NOT EXISTS conversation_summaries" in combined
    assert "CREATE TABLE IF NOT EXISTS conversation_session_index" in combined
