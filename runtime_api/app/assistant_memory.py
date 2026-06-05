from __future__ import annotations

import json
import re
from typing import Any, Callable


SHORT_REPLY_MARKERS = {
    "需要",
    "可以",
    "好的",
    "好",
    "要",
    "是",
    "确认",
    "继续",
    "不用",
    "不要",
    "yes",
    "ok",
    "sure",
}


def estimate_tokens(value: Any) -> int:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    cjk_chars = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    non_cjk_chars = len(text) - cjk_chars
    return max(1, cjk_chars + (non_cjk_chars + 3) // 4)


def is_short_contextual_reply(message: str) -> bool:
    compact = re.sub(r"\s+", "", str(message or "").strip().lower())
    if not compact:
        return False
    return compact in SHORT_REPLY_MARKERS or (len(compact) <= 8 and not re.search(r"[\u4e00-\u9fffA-Za-z0-9]{3,}", compact))


def assistant_question_score(turn: dict[str, Any]) -> int:
    content = str(turn.get("content") or "")
    score = 0
    if str(turn.get("role") or "").lower() == "assistant":
        score += 10
    if any(marker in content for marker in ["需要", "是否", "要不要", "可以", "确认", "帮你"]):
        score += 8
    if any(marker in content for marker in ["？", "?", "吗"]):
        score += 6
    return score


def find_prior_assistant_question(turns: list[dict[str, Any]], conversation_id: str | None) -> dict[str, Any] | None:
    scoped = [
        turn
        for turn in turns
        if str(turn.get("conversation_id") or conversation_id or "") == str(conversation_id or turn.get("conversation_id") or "")
    ]
    for turn in reversed(scoped):
        if assistant_question_score(turn) >= 14:
            return turn
    return None


def normalize_turn(turn: dict[str, Any], index: int, token_estimator: Callable[[Any], int]) -> dict[str, Any]:
    content = str(turn.get("content") or "").strip()
    item = {
        "turn_id": str(turn.get("turn_id") or turn.get("id") or turn.get("event_id") or f"turn-{index}"),
        "event_id": str(turn.get("event_id") or turn.get("turn_id") or turn.get("id") or f"turn-{index}"),
        "conversation_id": str(turn.get("conversation_id") or ""),
        "role": str(turn.get("role") or "").lower(),
        "content": content,
    }
    item["token_count"] = token_estimator(item)
    return item


def pack_with_required(
    candidates: list[dict[str, Any]],
    required_ids: set[str],
    token_budget: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    used = 0

    required = [item for item in candidates if item["turn_id"] in required_ids]
    optional = [item for item in candidates if item["turn_id"] not in required_ids]
    ordered = required + optional
    for item in ordered:
        cost = int(item.get("token_count") or estimate_tokens(item))
        if included and used + cost > token_budget:
            excluded.append({"turn_id": item["turn_id"], "reason": "token_budget_exceeded"})
            continue
        if not included and cost > token_budget:
            compact = dict(item)
            compact["content"] = compact["content"][: max(20, token_budget * 2)] + "\n[truncated]"
            compact["token_count"] = min(token_budget, estimate_tokens(compact))
            included.append(compact)
            used += int(compact["token_count"])
            continue
        included.append(item)
        used += cost
    return included, excluded, used


def build_session_search_context(
    *,
    current_message: str,
    conversation_id: str | None,
    turns: list[dict[str, Any]],
    active_tasks: list[dict[str, Any]] | None = None,
    token_budget: int = 32000,
    token_estimator: Callable[[Any], int] = estimate_tokens,
) -> dict[str, Any]:
    active_tasks = active_tasks or []
    current_clean = str(current_message or "").strip()
    normalized_turns = [
        normalize_turn(turn, index, token_estimator)
        for index, turn in enumerate(turns or [])
        if str(turn.get("content") or "").strip()
    ]
    normalized_turns = [
        turn
        for turn in normalized_turns
        if not (turn["role"] == "user" and current_clean and turn["content"] == current_clean)
    ]
    short_reply = is_short_contextual_reply(current_message)
    prior_question = find_prior_assistant_question(normalized_turns, conversation_id) if short_reply else None
    required_ids = {prior_question["turn_id"]} if prior_question else set()
    same_conversation = [
        turn
        for turn in normalized_turns
        if not conversation_id or turn.get("conversation_id") in {"", str(conversation_id)}
    ]
    candidates = list(reversed(same_conversation[-64:]))
    included, excluded, used = pack_with_required(candidates, required_ids, max(1, token_budget))
    included = list(reversed(included))

    scoped_tasks = [
        task
        for task in active_tasks
        if not conversation_id or str(task.get("conversation_id") or conversation_id) == str(conversation_id)
    ]
    return {
        "conversation_id": conversation_id,
        "included_turns": included,
        "active_tasks": scoped_tasks,
        "excluded": excluded,
        "short_reply_resolution": {
            "is_short_reply": short_reply,
            "resolved": bool(short_reply and prior_question),
            "prior_question_turn_id": prior_question["turn_id"] if prior_question else None,
        },
        "token_budget": {"limit": token_budget, "used": used},
        "reason": (
            "short reply resolved with prior Nomi question and active task context"
            if short_reply and prior_question
            else "session search selected same-conversation turns by recency and token budget"
        ),
    }


def assistant_memory_schema_sql() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS assistant_profile_memories (
          id UUID PRIMARY KEY,
          user_id TEXT NOT NULL DEFAULT 'default',
          fact_type TEXT NOT NULL DEFAULT '',
          fact_text TEXT NOT NULL DEFAULT '',
          structured_value JSONB NOT NULL DEFAULT '{}'::jsonb,
          confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
          source_turn_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
          valid_until TIMESTAMPTZ,
          supersedes_memory_id TEXT,
          sensitivity_level TEXT NOT NULL DEFAULT 'medium',
          scope JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS conversation_summaries (
          id UUID PRIMARY KEY,
          conversation_id TEXT NOT NULL DEFAULT '',
          summary TEXT NOT NULL DEFAULT '',
          covered_turn_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          open_questions JSONB NOT NULL DEFAULT '[]'::jsonb,
          active_task_refs TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          token_count INTEGER NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS conversation_session_index (
          id UUID PRIMARY KEY,
          conversation_id TEXT NOT NULL DEFAULT '',
          turn_id TEXT NOT NULL DEFAULT '',
          role TEXT NOT NULL DEFAULT '',
          content TEXT NOT NULL DEFAULT '',
          tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          task_refs TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          token_count INTEGER NOT NULL DEFAULT 0,
          payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS assistant_profile_memories_user_idx
        ON assistant_profile_memories(user_id, fact_type, updated_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS conversation_summaries_conversation_idx
        ON conversation_summaries(conversation_id, updated_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS conversation_session_index_conversation_idx
        ON conversation_session_index(conversation_id, created_at DESC)
        """,
    ]
