#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def import_project_module(package_root: str, module_name: str):
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    sys.path.insert(0, str(ROOT / package_root))
    try:
        return importlib.import_module(module_name)
    finally:
        sys.path.pop(0)


def stage(name: str, reasonable: bool, output: dict[str, Any]) -> dict[str, Any]:
    return {"stage": name, "reasonable": bool(reasonable), "output": output}


def main() -> int:
    runtime_main = import_project_module("runtime_api", "app.main")
    worker = import_project_module("worker", "app.worker")

    reports: list[dict[str, Any]] = []

    nomi_semantic = worker.rule_extract_semantics(
        "nomi_chat",
        "user_message",
        {
            "role": "user",
            "content": "帮我盯一下周末和 Alex 见面的事",
            "conversation_id": "conv-active",
            "client_type": "android",
        },
    )
    reports.append(
        stage(
            "nomi_dialogue_semantic",
            nomi_semantic["intent"] == "user_instruction"
            and "周末和 Alex" in nomi_semantic["summary"]
            and nomi_semantic["importance"] >= 0.7,
            {
                "intent": nomi_semantic["intent"],
                "importance": nomi_semantic["importance"],
                "summary": nomi_semantic["summary"],
                "entities": nomi_semantic["entities"],
            },
        )
    )

    context_pack = runtime_main.build_context_pack(
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
    context_text = json.dumps(context_pack, ensure_ascii=False)
    reports.append(
        stage(
            "bounded_context_pack",
            "周末和 Alex" in context_text and "健身房 Alex" in context_text and "猫粮优惠券" not in context_text,
            {
                "included_event_ids": context_pack["included_event_ids"],
                "assistant_dialogue": context_pack["assistant_dialogue"],
                "reason": context_pack["reason"],
            },
        )
    )

    fuzzy_agenda = worker.agenda_candidate_from_semantic(
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
    reports.append(
        stage(
            "fuzzy_agenda_candidate",
            fuzzy_agenda is not None
            and fuzzy_agenda["certainty"] == "fuzzy"
            and fuzzy_agenda["needs_clarification"]
            and {"exact_time", "exact_place"}.issubset(set(fuzzy_agenda["missing_fields"])),
            fuzzy_agenda or {},
        )
    )

    cancel_agenda = worker.agenda_candidate_from_semantic(
        "33333333-3333-3333-3333-333333333333",
        "2026-05-28T10:00:00+00:00",
        {
            "intent": "social_plan",
            "summary": "Alex 说周日见面取消了。",
            "importance": 0.86,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
            "raw_data": {"chat_name": "Alex", "sender": "Alex", "message": "周日先取消吧"},
        },
    )
    reports.append(
        stage(
            "cancel_agenda_candidate",
            cancel_agenda is not None
            and cancel_agenda["operation"] == "cancel"
            and cancel_agenda["status"] == "canceled"
            and cancel_agenda["missing_fields"] == [],
            cancel_agenda or {},
        )
    )

    reschedule_agenda = worker.agenda_candidate_from_semantic(
        "66666666-6666-6666-6666-666666666666",
        "2026-05-28T10:30:00+00:00",
        {
            "intent": "social_plan",
            "summary": "Alex 把见面改到周六。",
            "importance": 0.86,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
            "raw_data": {"chat_name": "Alex", "chat_id": "wa-alex", "sender": "Alex", "message": "改到周六吧"},
        },
    )
    original_with_chat_id = worker.agenda_candidate_from_semantic(
        "77777777-7777-7777-7777-777777777777",
        "2026-05-28T09:00:00+00:00",
        {
            "intent": "social_plan",
            "summary": "Alex 说那就周日见。",
            "importance": 0.82,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
            "raw_data": {"chat_name": "Alex", "chat_id": "wa-alex", "sender": "Alex", "message": "那就周日吧"},
        },
    )
    reports.append(
        stage(
            "reschedule_agenda_candidate",
            reschedule_agenda is not None
            and original_with_chat_id is not None
            and reschedule_agenda["operation"] == "reschedule"
            and reschedule_agenda["metadata"]["dedupe_key"] == original_with_chat_id["metadata"]["dedupe_key"],
            {
                "reschedule": reschedule_agenda or {},
                "original_dedupe_key": (original_with_chat_id or {}).get("metadata", {}).get("dedupe_key"),
            },
        )
    )

    payment_agenda = worker.agenda_candidate_from_semantic(
        "44444444-4444-4444-4444-444444444444",
        "2026-05-28T11:00:00+00:00",
        {
            "intent": "payment_reminder",
            "summary": "云服务器账单需要在明天前付款。",
            "importance": 0.88,
            "entities": {"source": "gmail", "event_type": "gmail_thread_snapshot"},
            "raw_data": {"subject": "Invoice due", "body": "云服务器账单需要在明天前付款"},
        },
    )
    reports.append(
        stage(
            "payment_agenda_candidate",
            payment_agenda is not None
            and payment_agenda["type"] == "payment"
            and payment_agenda["confidence"] >= 0.8
            and "exact_place" not in payment_agenda["missing_fields"],
            payment_agenda or {},
        )
    )

    social_suggestion = worker.suggestion_for_event(
        "55555555-5555-5555-5555-555555555555",
        {
            "intent": "social_plan",
            "summary": "Alex 约你周日去武康路见面。",
            "importance": 0.86,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
        },
    )
    action_labels = [item["label"] for item in social_suggestion["metadata"]["actions"]] if social_suggestion else []
    reports.append(
        stage(
            "proactive_action_cards",
            action_labels == ["查路线", "帮我打车", "稍后提醒"],
            {
                "title": social_suggestion["title"] if social_suggestion else "",
                "body": social_suggestion["body"] if social_suggestion else "",
                "actions": social_suggestion["metadata"]["actions"] if social_suggestion else [],
            },
        )
    )

    print(json.dumps({"reports": reports}, ensure_ascii=False, indent=2, default=str))
    return 0 if all(item["reasonable"] for item in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
