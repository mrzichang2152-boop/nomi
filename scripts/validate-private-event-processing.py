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


class Cursor:
    rowcount = 1

    def __init__(self, rows=None):
        self.rows = rows or []

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, handler, executed: list[tuple[str, Any]]):
        self.handler = handler
        self.executed = executed

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        self.executed.append((normalized, params))
        return self.handler(normalized, params)


def with_fake_db(runtime_main, handler, fn):
    executed: list[tuple[str, Any]] = []
    original_db = runtime_main.db
    runtime_main.db = lambda: FakeConn(handler, executed)
    try:
        return fn(), executed
    finally:
        runtime_main.db = original_db


EVENT_ID = "22222222-2222-2222-2222-222222222222"
AGENDA_ID = "11111111-1111-1111-1111-111111111111"
SUGGESTION_ID = "33333333-3333-3333-3333-333333333333"
CONVERSATION_ID = "44444444-4444-4444-4444-444444444444"


def runtime_agenda_row(title: str = "Alex 说周末见。"):
    return (
        AGENDA_ID,
        "appointment",
        title,
        "scheduled",
        "fuzzy",
        {"raw_text": "周末见", "has_exact_time": False, "has_fuzzy_time": True},
        "",
        ["Alex"],
        ["exact_time", "exact_place"],
        True,
        0.82,
        [EVENT_ID],
        {"dedupe_key": "agenda:appointment:whatsapp:alex"},
        "2026-05-28T09:00:00+00:00",
        "2026-05-28T09:30:00+00:00",
        "create",
        "create agenda from semantic event",
        "2026-05-28T09:00:01+00:00",
    )


def main() -> int:
    runtime_main = import_project_module("runtime_api", "app.main")
    worker = import_project_module("worker", "app.worker")
    os.environ.setdefault("APP_PASSWORD", "secret")

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

    active_agenda_pack = runtime_main.build_context_pack(
        "那就周日吧",
        base_context=[],
        assistant_context=[],
        conversation_id="conv-active",
        agenda_context=[
            {
                "id": AGENDA_ID,
                "title": "周末和 Alex 见面",
                "participants": ["Alex"],
                "certainty": "fuzzy",
                "missing_fields": ["exact_time", "exact_place"],
                "source_event_ids": [EVENT_ID],
            },
            {
                "id": "55555555-5555-5555-5555-555555555555",
                "title": "缴纳服务器账单",
                "participants": [],
                "certainty": "exact",
                "missing_fields": [],
                "source_event_ids": ["66666666-6666-6666-6666-666666666666"],
            },
        ],
    )
    active_agenda_text = json.dumps(active_agenda_pack, ensure_ascii=False)
    reports.append(
        stage(
            "active_agenda_context_pack",
            active_agenda_pack["included_agenda_ids"] == [AGENDA_ID]
            and "周末和 Alex 见面" in active_agenda_text
            and "缴纳服务器账单" not in active_agenda_text
            and EVENT_ID in active_agenda_pack["included_event_ids"],
            {
                "included_agenda_ids": active_agenda_pack["included_agenda_ids"],
                "included_event_ids": active_agenda_pack["included_event_ids"],
                "agenda_context": active_agenda_pack["agenda_context"],
            },
        )
    )

    def agenda_api_handler(sql, params):
        if "FROM agenda_items" in sql and "certainty = %s" in sql:
            return Cursor([runtime_agenda_row()])
        if "SELECT id, type, title, status, certainty" in sql and "FROM agenda_items" in sql:
            return Cursor([runtime_agenda_row()])
        return Cursor()

    agenda_output, agenda_executed = with_fake_db(
        runtime_main,
        agenda_api_handler,
        lambda: runtime_main.agenda_items(x_par_password="secret", certainty="fuzzy"),
    )
    agenda_patch_output, agenda_patch_executed = with_fake_db(
        runtime_main,
        agenda_api_handler,
        lambda: runtime_main.patch_agenda_item(
            AGENDA_ID,
            runtime_main.AgendaPatchIn(
                title="周日和 Alex 见面",
                place="武康路",
                status="scheduled",
                reason="用户修正地点",
            ),
            x_par_password="secret",
        ),
    )
    reports.append(
        stage(
            "agenda_api_list_and_correction",
            len(agenda_output["items"]) == 1
            and agenda_output["items"][0]["certainty"] == "fuzzy"
            and agenda_output["items"][0]["latest_version"]["operation"] == "create"
            and agenda_patch_output["version"]["operation"] == "user_correction"
            and agenda_patch_output["version"]["previous_value"]["title"] == "Alex 说周末见。"
            and agenda_patch_output["version"]["new_value"]["place"] == "武康路"
            and any("UPDATE agenda_items" in sql for sql, _ in agenda_patch_executed),
            {
                "list_item": agenda_output["items"][0] if agenda_output["items"] else {},
                "patch_version": agenda_patch_output["version"],
                "update_sql_seen": any("UPDATE agenda_items" in sql for sql, _ in agenda_patch_executed),
                "list_filter_sql_seen": any("certainty = %s" in sql for sql, _ in agenda_executed),
            },
        )
    )

    original_semantic_call_model = worker.call_model
    try:
        worker.call_model = lambda messages: """
        {
          "intent": "generic_event",
          "entities": {"source": "gmail", "labels": ["ordinary_chat"], "primary_label": "ordinary_chat"},
          "importance": 0.4,
          "summary": "一封普通邮件。"
        }
        """
        hybrid_semantic = worker.extract_semantics(
            "gmail",
            "gmail_thread_snapshot",
            {"subject": "Invoice due", "body": "云服务器账单需要在明天前付款"},
        )
        trace = hybrid_semantic["entities"]["classification_trace"]
        reports.append(
            stage(
                "hybrid_semantic_rule_overrides_model_label",
                hybrid_semantic["entities"]["primary_label"] == "payment"
                and "payment" in hybrid_semantic["entities"]["labels"]
                and "rule_overrode_low_value_model_label" in trace["validation_warnings"],
                {
                    "intent": hybrid_semantic["intent"],
                    "labels": hybrid_semantic["entities"]["labels"],
                    "primary_label": hybrid_semantic["entities"]["primary_label"],
                    "classification_trace": trace,
                    "summary": hybrid_semantic["summary"],
                },
            )
        )
    finally:
        worker.call_model = original_semantic_call_model

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

    exact_agenda = worker.agenda_candidate_from_semantic(
        "12121212-1212-1212-1212-121212121212",
        "2026-05-28T09:30:00+00:00",
        {
            "intent": "social_plan",
            "summary": "Alex 约我今晚 7点在武康路见面。",
            "importance": 0.9,
            "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
            "raw_data": {"chat_name": "Alex", "sender": "Alex", "message": "今晚 7点在武康路见面吧"},
        },
    )
    reports.append(
        stage(
            "exact_agenda_candidate",
            exact_agenda is not None
            and exact_agenda["certainty"] == "exact"
            and exact_agenda["place"] == "武康路"
            and exact_agenda["missing_fields"] == []
            and exact_agenda["needs_clarification"] is False,
            exact_agenda or {},
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

    executed_agenda_updates: list[tuple[str, Any]] = []

    class ExistingAgendaCursor:
        rowcount = 1

        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchone(self):
            return self.rows[0] if self.rows else None

    class ExistingAgendaConn:
        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            executed_agenda_updates.append((normalized, params))
            if "FROM agenda_items WHERE metadata->>'dedupe_key'" in normalized:
                return ExistingAgendaCursor(
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
            return ExistingAgendaCursor()

    agenda_model_enabled_for_version = os.environ.get("AGENDA_MODEL_ENABLED")
    os.environ["AGENDA_MODEL_ENABLED"] = "0"
    try:
        worker.persist_agenda(
            ExistingAgendaConn(),
            "13131313-1313-1313-1313-131313131313",
            "2026-05-28T10:45:00+00:00",
            {
                "intent": "social_plan",
                "summary": "Alex 把见面改到周六。",
                "importance": 0.86,
                "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
                "raw_data": {"chat_name": "Alex", "chat_id": "wa-alex", "sender": "Alex", "message": "改到周六吧"},
            },
        )
    finally:
        if agenda_model_enabled_for_version is None:
            os.environ.pop("AGENDA_MODEL_ENABLED", None)
        else:
            os.environ["AGENDA_MODEL_ENABLED"] = agenda_model_enabled_for_version
    version_params = next(params for sql, params in executed_agenda_updates if "INSERT INTO agenda_item_versions" in sql)
    version_previous = json.loads(version_params[3])
    version_new = json.loads(version_params[4])
    reports.append(
        stage(
            "agenda_version_previous_value",
            version_params[2] == "reschedule"
            and version_previous.get("title") == "Alex 说那就周日见。"
            and version_previous.get("missing_fields") == ["exact_time", "exact_place"]
            and version_new.get("title") == "Alex 把见面改到周六。",
            {
                "operation": version_params[2],
                "previous_value": version_previous,
                "new_value": version_new,
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

    original_model_enabled = os.environ.get("AGENDA_MODEL_ENABLED")
    original_call_model = worker.call_model
    os.environ["AGENDA_MODEL_ENABLED"] = "1"
    try:
        worker.call_model = lambda messages: """
        {
          "is_agenda": true,
          "type": "appointment",
          "operation": "create",
          "title": "周日和 Alex 去武康路见面",
          "status": "scheduled",
          "certainty": "fuzzy",
          "time_window": {"raw_text": "周日"},
          "place": "武康路",
          "participants": ["Alex"],
          "missing_fields": ["exact_time"],
          "needs_clarification": true,
          "confidence": 0.91,
          "reason": "消息明确包含周日、Alex、武康路，但没有精确时间。"
        }
        """
        hybrid_supported = worker.hybrid_agenda_candidate_from_semantic(
            "88888888-8888-8888-8888-888888888888",
            "2026-05-28T12:00:00+00:00",
            {
                "intent": "social_plan",
                "summary": "Alex 说周日去武康路见。",
                "importance": 0.82,
                "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
                "raw_data": {"chat_name": "Alex", "chat_id": "wa-alex", "sender": "Alex", "message": "周日去武康路见吧"},
            },
        )
        reports.append(
            stage(
                "hybrid_agenda_model_supported_candidate",
                hybrid_supported is not None
                and hybrid_supported["metadata"]["parser_mode"] == "hybrid_model_rules"
                and hybrid_supported["title"] == "周日和 Alex 去武康路见面"
                and hybrid_supported["place"] == "武康路"
                and hybrid_supported["missing_fields"] == ["exact_time"],
                hybrid_supported or {},
            )
        )

        worker.call_model = lambda messages: """
        {
          "is_agenda": true,
          "type": "appointment",
          "operation": "create",
          "title": "周末和 Alex 晚上八点见面",
          "status": "scheduled",
          "certainty": "exact",
          "time_window": {"raw_text": "周六晚上八点", "start": "2026-05-30T20:00:00+08:00"},
          "place": "武康路",
          "participants": ["Alex"],
          "missing_fields": [],
          "needs_clarification": false,
          "confidence": 0.94,
          "reason": "模型猜了一个具体时间。"
        }
        """
        hybrid_downgraded = worker.hybrid_agenda_candidate_from_semantic(
            "99999999-9999-9999-9999-999999999999",
            "2026-05-28T12:10:00+00:00",
            {
                "intent": "social_plan",
                "summary": "Alex 说周末去武康路见。",
                "importance": 0.82,
                "entities": {"source": "whatsapp", "event_type": "whatsapp_message"},
                "raw_data": {"chat_name": "Alex", "sender": "Alex", "message": "周末去武康路见吧"},
            },
        )
        reports.append(
            stage(
                "hybrid_agenda_rejects_unsupported_exact_time",
                hybrid_downgraded is not None
                and hybrid_downgraded["certainty"] == "fuzzy"
                and "exact_time" in hybrid_downgraded["missing_fields"]
                and "unsupported_exact_time" in hybrid_downgraded["metadata"]["validation_warnings"],
                hybrid_downgraded or {},
            )
        )
    finally:
        worker.call_model = original_call_model
        if original_model_enabled is None:
            os.environ.pop("AGENDA_MODEL_ENABLED", None)
        else:
            os.environ["AGENDA_MODEL_ENABLED"] = original_model_enabled

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

    def suggestion_action_handler(sql, params):
        if "FROM proactive_suggestions" in sql and "SELECT id" in sql:
            return Cursor(
                [
                    (
                        SUGGESTION_ID,
                        EVENT_ID,
                        "跟进近期安排",
                        "Alex 约你周日去武康路见面。",
                        0.88,
                        "open",
                        {
                            "suggestion_type": "social_followup",
                            "source": "whatsapp",
                            "actions": [
                                {"id": "route_lookup", "label": "查路线", "next_step": "route_lookup"},
                                {"id": "ride_prepare", "label": "帮我打车", "next_step": "prepare_ride_request"},
                            ],
                        },
                        "2026-05-28T09:00:00+00:00",
                        "2026-05-28T09:00:00+00:00",
                    )
                ]
            )
        return Cursor()

    suggestion_action_output, suggestion_action_executed = with_fake_db(
        runtime_main,
        suggestion_action_handler,
        lambda: runtime_main.proactive_suggestion_action(
            SUGGESTION_ID,
            runtime_main.SuggestionActionIn(action_id="route_lookup", reason="用户想先看路线"),
            x_par_password="secret",
        ),
    )
    ride_action_output, _ = with_fake_db(
        runtime_main,
        suggestion_action_handler,
        lambda: runtime_main.proactive_suggestion_action(
            SUGGESTION_ID,
            runtime_main.SuggestionActionIn(action_id="ride_prepare", reason="用户想准备叫车"),
            x_par_password="secret",
        ),
    )
    snooze_action_output, _ = with_fake_db(
        runtime_main,
        suggestion_action_handler,
        lambda: runtime_main.proactive_suggestion_action(
            SUGGESTION_ID,
            runtime_main.SuggestionActionIn(
                action_id="snooze",
                reason="晚点提醒",
                snoozed_until="2026-05-29T09:00:00+08:00",
            ),
            x_par_password="secret",
        ),
    )
    reports.append(
        stage(
            "proactive_suggestion_action_feedback_and_route",
            suggestion_action_output["feedback_recorded"] is True
            and suggestion_action_output["route_result"]["route_type"] == "core_pipeline"
            and suggestion_action_output["route_result"]["pipeline"]["id"] == "route_pipeline"
            and ride_action_output["route_result"]["pipeline"]["id"] == "ride_pipeline"
            and ride_action_output["route_result"]["execution_guard"]["final_user_confirmation"] is True
            and snooze_action_output["local_result"]["metadata"]["snoozed_until"] == "2026-05-29T09:00:00+08:00"
            and any("INSERT INTO user_feedback" in sql for sql, _ in suggestion_action_executed)
            and any("INSERT INTO task_route_traces" in sql for sql, _ in suggestion_action_executed),
            {
                "feedback_recorded": suggestion_action_output["feedback_recorded"],
                "route_type": suggestion_action_output["route_result"]["route_type"],
                "pipeline": suggestion_action_output["route_result"]["pipeline"],
                "execution_guard": suggestion_action_output["route_result"]["execution_guard"],
                "ride_pipeline": ride_action_output["route_result"]["pipeline"],
                "ride_execution_guard": ride_action_output["route_result"]["execution_guard"],
                "snooze_local_result": snooze_action_output["local_result"],
                "feedback_sql_seen": any("INSERT INTO user_feedback" in sql for sql, _ in suggestion_action_executed),
                "route_trace_sql_seen": any("INSERT INTO task_route_traces" in sql for sql, _ in suggestion_action_executed),
            },
        )
    )

    def trace_handler(sql, params):
        if "FROM events" in sql and "WHERE event_id = %s" in sql:
            return Cursor([(EVENT_ID, "whatsapp", "whatsapp_message", {"message": "周日去武康路见"}, "2026-05-28T09:00:00+00:00")])
        if "FROM semantic_events" in sql:
            return Cursor([("sem-1", "social_plan", {"primary_label": "appointment"}, 0.88, "Alex 约你周日去武康路见面。", "qwen3.6")])
        if "FROM memory_vectors" in sql:
            return Cursor([("vec-1", "Alex 约你周日去武康路见面。", {"memory_scope": {"conversation_label": "Alex"}})])
        if "FROM facts" in sql:
            return Cursor([("fact-1", "alex", "social_plan", "wukang road", 0.88, [EVENT_ID], {"summary": "见面安排"})])
        if "FROM agenda_items" in sql:
            return Cursor([runtime_agenda_row()])
        if "FROM agenda_item_versions" in sql:
            return Cursor([("ver-1", AGENDA_ID, "create", {}, {"title": "Alex 说周末见。"}, "created", [EVENT_ID], 0.82, "2026-05-28T09:00:01+00:00")])
        if "FROM assistant_conversations" in sql:
            return Cursor([(CONVERSATION_ID, "android", "2026-05-28T09:00:00+00:00", "2026-05-28T09:10:00+00:00", None, {"source": "nomi_chat"}, "active")])
        if "FROM assistant_turns" in sql:
            return Cursor([("turn-1", CONVERSATION_ID, "user", "帮我盯一下周末和 Alex 见面", EVENT_ID, None, None, "2026-05-28T09:00:00+00:00", None)])
        if "FROM context_snapshots" in sql:
            return Cursor([("ctx-1", EVENT_ID, "chat_response", [EVENT_ID], [], [AGENDA_ID], "bounded context pack", {"agenda_context": [{"id": AGENDA_ID}]}, "2026-05-28T09:00:01+00:00")])
        if "FROM proactive_suggestions" in sql:
            return Cursor([(SUGGESTION_ID, EVENT_ID, "跟进近期安排", "Alex 约你周日去武康路见面。", 0.88, "open", {}, "2026-05-28T09:01:00+00:00", "2026-05-28T09:01:00+00:00")])
        if "FROM task_route_traces" in sql:
            return Cursor([(
                "trace-1",
                "查路线",
                "core_pipeline",
                "local_service.route.lookup",
                "route_pipeline",
                "read_only",
                False,
                {},
                None,
                None,
                {"source_event_ids": [EVENT_ID], "conversation_id": CONVERSATION_ID},
                "2026-05-28T09:02:00+00:00",
                [EVENT_ID],
                CONVERSATION_ID,
                SUGGESTION_ID,
                [AGENDA_ID],
            )])
        if "FROM pipeline_execution_results" in sql:
            return Cursor([(
                "exec-1",
                "trace-1",
                "查路线",
                "core_pipeline",
                "local_service.route.lookup",
                "route_pipeline",
                "completed_read_only",
                ["destination"],
                {"destination": "武康路"},
                [],
                {"permission": "read_only", "confirmation_required": False},
                {"permission": "read_only", "requires_confirmation": False},
                [EVENT_ID],
                CONVERSATION_ID,
                SUGGESTION_ID,
                [AGENDA_ID],
                {
                    "status": "completed_read_only",
                    "resolved_slots": {"destination": "武康路"},
                    "input": {
                        "source_event_ids": [EVENT_ID],
                        "conversation_id": CONVERSATION_ID,
                        "suggestion_id": SUGGESTION_ID,
                        "agenda_item_ids": [AGENDA_ID],
                    },
                },
                "2026-05-28T09:02:02+00:00",
            )])
        return Cursor()

    event_trace_output, _ = with_fake_db(
        runtime_main,
        trace_handler,
        lambda: runtime_main.event_trace(EVENT_ID, x_par_password="secret"),
    )
    conversation_trace_output, _ = with_fake_db(
        runtime_main,
        trace_handler,
        lambda: runtime_main.conversation_trace(CONVERSATION_ID, x_par_password="secret"),
    )
    reports.append(
        stage(
            "event_and_conversation_trace_api",
            event_trace_output["event"]["event_id"] == EVENT_ID
            and event_trace_output["semantic_event"]["intent"] == "social_plan"
            and event_trace_output["agenda_items"][0]["latest_version"]["operation"] == "create"
            and event_trace_output["route_traces"][0]["pipeline_id"] == "route_pipeline"
            and event_trace_output["route_traces"][0]["source_event_ids"] == [EVENT_ID]
            and event_trace_output["route_traces"][0]["conversation_id"] == CONVERSATION_ID
            and event_trace_output["pipeline_executions"][0]["resolved_slots"]["destination"] == "武康路"
            and event_trace_output["pipeline_executions"][0]["source_event_ids"] == [EVENT_ID]
            and conversation_trace_output["conversation"]["id"] == CONVERSATION_ID
            and conversation_trace_output["context_snapshots"][0]["included_agenda_ids"] == [AGENDA_ID]
            and conversation_trace_output["suggestions"][0]["source_event_id"] == EVENT_ID
            and conversation_trace_output["pipeline_executions"][0]["conversation_id"] == CONVERSATION_ID,
            {
                "event_trace": {
                    "event": event_trace_output["event"],
                    "semantic_event": event_trace_output["semantic_event"],
                    "agenda_items": event_trace_output["agenda_items"],
                    "suggestions": event_trace_output["suggestions"],
                    "route_traces": event_trace_output["route_traces"],
                    "pipeline_executions": event_trace_output["pipeline_executions"],
                },
                "conversation_trace": {
                    "conversation": conversation_trace_output["conversation"],
                    "turns": conversation_trace_output["turns"],
                    "context_snapshots": conversation_trace_output["context_snapshots"],
                    "suggestions": conversation_trace_output["suggestions"],
                    "route_traces": conversation_trace_output["route_traces"],
                    "pipeline_executions": conversation_trace_output["pipeline_executions"],
                },
            },
        )
    )

    print(json.dumps({"reports": reports}, ensure_ascii=False, indent=2, default=str))
    return 0 if all(item["reasonable"] for item in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
