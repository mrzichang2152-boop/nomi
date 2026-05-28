#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime_api"))

os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")
os.environ.setdefault("APP_PASSWORD", "secret")

from app import main  # noqa: E402


EXPECTED_PIPELINES = {
    "event_ingestion_pipeline",
    "memory_write_pipeline",
    "context_pack_pipeline",
    "personal_search_pipeline",
    "chat_response_pipeline",
    "reply_pipeline",
    "email_pipeline",
    "agenda_pipeline",
    "task_todo_pipeline",
    "proactive_suggestion_pipeline",
    "route_pipeline",
    "ride_pipeline",
    "shopping_pipeline",
    "payment_bill_pipeline",
    "contact_relationship_pipeline",
    "document_file_pipeline",
    "account_login_pipeline",
    "governance_audit_pipeline",
}


def stage(name: str, output: dict[str, Any], checks: dict[str, bool]) -> dict[str, Any]:
    return {
        "stage": name,
        "reasonable": all(checks.values()),
        "checks": checks,
        "output": output,
    }


def compact_route(result: dict[str, Any]) -> dict[str, Any]:
    packet = result.get("openclaw_task_packet") or {}
    return {
        "route_type": result["route_type"],
        "legacy_route_type": result.get("legacy_route_type"),
        "capability": result["capability"]["id"],
        "pipeline": (result.get("pipeline") or {}).get("id"),
        "guard": result.get("execution_guard"),
        "reason": result.get("routing_reason"),
        "packet_allowed_actions": packet.get("allowed_actions"),
        "packet_forbidden_actions": packet.get("forbidden_actions"),
        "minimal_context": packet.get("minimal_context"),
        "clarification": result.get("clarification"),
    }


def main_script() -> int:
    stages: list[dict[str, Any]] = []

    pipelines = {pipeline["id"]: pipeline for pipeline in main.core_pipeline_registry()}
    stages.append(
        stage(
            "core_pipeline_registry_matches_design",
            {
                "pipeline_count": len(pipelines),
                "missing": sorted(EXPECTED_PIPELINES - pipelines.keys()),
                "sample_permissions": {
                    "reply_pipeline": pipelines.get("reply_pipeline", {}).get("permission"),
                    "ride_pipeline": pipelines.get("ride_pipeline", {}).get("permission"),
                    "personal_search_pipeline": pipelines.get("personal_search_pipeline", {}).get("permission"),
                },
            },
            {
                "all_expected_pipelines_present": EXPECTED_PIPELINES.issubset(pipelines.keys()),
                "reply_sends_external_message": "send_message" in pipelines.get("reply_pipeline", {}).get("external_effects", []),
                "ride_requires_payment_or_purchase": pipelines.get("ride_pipeline", {}).get("permission") == "payment_or_purchase",
                "search_is_read_only": pipelines.get("personal_search_pipeline", {}).get("permission") == "read_only",
            },
        )
    )

    reply = main.route_tool_request("帮我回复 Alice，说明周五八点可以")
    stages.append(
        stage(
            "reply_routes_to_core_pipeline",
            compact_route(reply),
            {
                "route_type_core": reply["route_type"] == "core_pipeline",
                "pipeline_reply": (reply.get("pipeline") or {}).get("id") == "reply_pipeline",
                "external_message_confirmation": reply["execution_guard"]["permission"] == "external_message"
                and reply["execution_guard"]["requires_confirmation"],
                "reason_mentions_pipeline": "Pipeline" in reply["routing_reason"],
            },
        )
    )

    route = main.route_tool_request("查路线去武康路")
    stages.append(
        stage(
            "route_lookup_uses_read_only_core_pipeline",
            compact_route(route),
            {
                "route_type_core": route["route_type"] == "core_pipeline",
                "pipeline_route": (route.get("pipeline") or {}).get("id") == "route_pipeline",
                "read_only": route["execution_guard"]["permission"] == "read_only",
                "no_final_confirmation": route["execution_guard"]["final_user_confirmation"] is False,
            },
        )
    )

    ride = main.route_tool_request("帮我打车去武康路")
    stages.append(
        stage(
            "ride_uses_core_pipeline_with_final_confirmation",
            compact_route(ride),
            {
                "route_type_core": ride["route_type"] == "core_pipeline",
                "pipeline_ride": (ride.get("pipeline") or {}).get("id") == "ride_pipeline",
                "final_confirmation": ride["execution_guard"]["final_user_confirmation"] is True,
                "payment_guard": ride["execution_guard"]["permission"] == "payment_or_purchase",
            },
        )
    )

    reply_execution = main.run_core_pipeline(
        "帮我回复 Alice，说我周五八点可以",
        {"active_source_scope": {"source": "whatsapp", "conversation_id": "chat-alice"}},
    )
    route_execution = main.run_core_pipeline("查一下去武康路要多久")
    ride_execution = main.run_core_pipeline("帮我打车去武康路")
    payment_execution = main.run_core_pipeline("帮我付款")
    stages.append(
        stage(
            "core_pipeline_engine_status_contract",
            {
                "reply": reply_execution,
                "route": route_execution,
                "ride": ride_execution,
                "payment": payment_execution,
            },
            {
                "reply_draft_ready": reply_execution["pipeline_id"] == "reply_pipeline"
                and reply_execution["status"] == "draft_ready"
                and reply_execution["resolved_slots"].get("recipient") == "Alice"
                and reply_execution["risk"]["confirmation_required"] is True,
                "route_completed_read_only": route_execution["pipeline_id"] == "route_pipeline"
                and route_execution["status"] == "completed_read_only"
                and route_execution["resolved_slots"].get("destination") == "武康路",
                "ride_waits_for_pickup": ride_execution["pipeline_id"] == "ride_pipeline"
                and ride_execution["status"] == "needs_user_input"
                and "pickup" in ride_execution["missing_slots"]
                and ride_execution["risk"]["final_user_confirmation"] is True,
                "payment_asks_missing_fields": payment_execution["route_type"] == "ask_user"
                and payment_execution["status"] == "needs_user_input"
                and {"amount_or_bill", "counterparty"}.issubset(set(payment_execution["missing_slots"])),
            },
        )
    )

    direct_pipeline_contexts = {
        "event_ingestion_pipeline": {
            "pipeline_id": "event_ingestion_pipeline",
            "source": "whatsapp",
            "event_type": "message",
            "timestamp": "2026-05-28T09:00:00+08:00",
            "raw_event": {"text": "周日去武康路见"},
        },
        "memory_write_pipeline": {
            "pipeline_id": "memory_write_pipeline",
            "event_id": "evt_memory_1",
            "source_scope": {"source": "whatsapp", "conversation_id": "chat_alex"},
            "event_text": "Alex 约周日去武康路。",
            "embedding_available": False,
        },
        "context_pack_pipeline": {
            "pipeline_id": "context_pack_pipeline",
            "request_or_event_id": "evt_context_1",
            "current_scope": "chat_alex",
            "evidence_items": [
                {"id": "mem_alex", "scope": "chat_alex", "content": "Alex 约周日去武康路。"},
                {"id": "mem_bob", "scope": "chat_bob", "content": "Bob 的私密吐槽。"},
            ],
            "active_agenda": [{"id": "agenda_alex", "source_event_ids": ["evt_context_1"]}],
        },
        "personal_search_pipeline": {
            "pipeline_id": "personal_search_pipeline",
            "query": "Alex 约在哪里见",
            "current_scope": "chat_alex",
            "memory_hits": [
                {"id": "mem_alex", "scope": "chat_alex", "content": "地点是武康路。", "score": 0.92},
                {"id": "mem_bob", "scope": "chat_bob", "content": "不应泄露。", "score": 0.99},
            ],
        },
        "chat_response_pipeline": {
            "pipeline_id": "chat_response_pipeline",
            "conversation_id": "conv_alex",
            "message": "帮我盯一下周末见面的事",
            "memory_hits": [{"id": "mem_alex", "scope": "chat_alex", "content": "周日见"}],
        },
        "reply_pipeline": {
            "pipeline_id": "reply_pipeline",
            "recipient": "Alice",
            "channel": "whatsapp",
            "message_intent": "周五八点可以",
        },
        "email_pipeline": {
            "pipeline_id": "email_pipeline",
            "mailbox": "gmail",
            "email_intent": "summarize",
            "email_body": "Invoice due tomorrow.",
        },
        "agenda_pipeline": {
            "pipeline_id": "agenda_pipeline",
            "title": "周日和 Alex 见面",
            "time_window": {"raw_text": "周日", "type": "fuzzy"},
            "source_event_ids": ["evt_agenda_1"],
        },
        "task_todo_pipeline": {
            "pipeline_id": "task_todo_pipeline",
            "task_title": "跟进合同",
            "owner": "me",
            "due_window": {"raw_text": "明天", "type": "fuzzy"},
        },
        "proactive_suggestion_pipeline": {
            "pipeline_id": "proactive_suggestion_pipeline",
            "candidate_type": "route_need",
            "source_event_ids": ["evt_suggestion_1"],
            "destination": "武康路",
        },
        "route_pipeline": {
            "pipeline_id": "route_pipeline",
            "destination": "武康路",
            "current_location": "上海图书馆",
        },
        "ride_pipeline": {
            "pipeline_id": "ride_pipeline",
            "pickup": "上海图书馆",
            "destination": "武康路",
        },
        "shopping_pipeline": {
            "pipeline_id": "shopping_pipeline",
            "product_intent": "iPhone 充电线",
            "shopping_intent": "compare",
        },
        "payment_bill_pipeline": {
            "pipeline_id": "payment_bill_pipeline",
            "counterparty": "云服务商",
            "amount_or_bill": "100元账单",
        },
        "contact_relationship_pipeline": {
            "pipeline_id": "contact_relationship_pipeline",
            "contact_or_actor": "Alex",
            "relationship_fact": "喜欢安静的餐厅",
            "source_event_ids": ["evt_contact_1"],
            "conversation_id": "conv_alex",
        },
        "document_file_pipeline": {
            "pipeline_id": "document_file_pipeline",
            "file_or_query": "子长版.pptx",
            "document_intent": "summarize",
        },
        "account_login_pipeline": {
            "pipeline_id": "account_login_pipeline",
            "account_provider": "gmail",
        },
        "governance_audit_pipeline": {
            "pipeline_id": "governance_audit_pipeline",
            "task_id": "task_audit_1",
            "source_event_ids": ["evt_audit_1"],
        },
    }
    direct_results = {
        pipeline_id: main.run_core_pipeline("验证 pipeline 输出", context)
        for pipeline_id, context in direct_pipeline_contexts.items()
    }
    direct_summary = {
        pipeline_id: {
            "status": result.get("status"),
            "missing_slots": result.get("missing_slots"),
            "has_output": bool(result.get("output")),
            "risk": result.get("risk"),
            "external_effects": result.get("external_effects"),
            "output": result.get("output"),
        }
        for pipeline_id, result in direct_results.items()
    }
    stages.append(
        stage(
            "all_core_pipeline_modules_return_contentful_results",
            direct_summary,
            {
                "all_expected_pipeline_results_present": set(direct_results.keys()) == EXPECTED_PIPELINES,
                "all_have_content_output": all(bool(result.get("output")) for result in direct_results.values()),
                "memory_vector_retry_is_reasonable": direct_results["memory_write_pipeline"]["output"]["memory_layers"]["vector"]["status"]
                == "queued_for_retry",
                "context_scope_filter_excludes_unrelated": direct_results["context_pack_pipeline"]["output"]["excluded_evidence"][0]["id"]
                == "mem_bob",
                "personal_search_does_not_leak_other_contact": "不应泄露"
                not in direct_results["personal_search_pipeline"]["output"].get("answer_summary", ""),
                "reply_is_draft_not_sent": direct_results["reply_pipeline"]["status"] == "draft_ready"
                and direct_results["reply_pipeline"]["provider_calls"] == [],
                "proactive_has_clickable_route_ride_snooze": {
                    action["label"]
                    for action in direct_results["proactive_suggestion_pipeline"]["output"]["suggestion_card"]["actions"]
                }
                == {"查路线", "帮我打车", "稍后提醒"},
                "ride_requires_confirmation_without_booking": direct_results["ride_pipeline"]["status"] == "confirmation_required"
                and direct_results["ride_pipeline"]["output"]["booking_blocked"] is True,
                "shopping_compare_is_read_only": direct_results["shopping_pipeline"]["status"] == "completed_read_only"
                and direct_results["shopping_pipeline"]["risk"]["permission"] == "read_only",
                "payment_never_transfers_without_confirmation": direct_results["payment_bill_pipeline"]["status"] == "confirmation_required"
                and direct_results["payment_bill_pipeline"]["output"]["transfer_blocked"] is True,
                "contact_relationship_is_scoped": direct_results["contact_relationship_pipeline"]["output"]["relationship_update"]["scope"]["conversation_id"]
                == "conv_alex",
                "document_summary_is_read_only": direct_results["document_file_pipeline"]["status"] == "completed_read_only"
                and direct_results["document_file_pipeline"]["output"]["document_plan"]["action"] in {"summarize", "summary"},
                "account_login_keeps_credentials_with_user": direct_results["account_login_pipeline"]["output"]["credential_handling"]
                == "user_enters_credentials_directly",
                "governance_writes_execution_trace": "pipeline_execution_results"
                in direct_results["governance_audit_pipeline"]["writeback_targets"],
            },
        )
    )

    wave2_results = {
        "event_duplicate": main.run_core_pipeline(
            "重复事件",
            {
                "pipeline_id": "event_ingestion_pipeline",
                "source": "whatsapp",
                "event_type": "message",
                "timestamp": "2026-05-28T09:00:00+08:00",
                "raw_event": {"text": "周日去武康路见"},
                "event_exists": True,
            },
        ),
        "event_quarantine": main.run_core_pipeline(
            "坏事件",
            {
                "pipeline_id": "event_ingestion_pipeline",
                "source": "whatsapp",
                "event_type": "message",
                "timestamp": "2026-05-28T09:00:00+08:00",
                "raw_event": {"text": "缺少消息 id"},
                "schema_errors": ["missing_message_id"],
            },
        ),
        "ambiguous_private_search": main.run_core_pipeline(
            "Alex 在哪里见面",
            {
                "pipeline_id": "personal_search_pipeline",
                "query": "见面地点",
                "memory_hits": [
                    {"id": "mem_alex", "scope": "chat_alex", "content": "Alex 说武康路。", "score": 0.91},
                    {"id": "mem_bob", "scope": "chat_bob", "content": "Bob 的私密信息。", "score": 0.95},
                ],
            },
        ),
        "reply_leakage": main.run_core_pipeline(
            "回复 Alice",
            {
                "pipeline_id": "reply_pipeline",
                "recipient": "Alice",
                "channel": "whatsapp",
                "message_intent": "Bob said Alice is careless",
                "leakage_terms": ["Bob said Alice is careless"],
            },
        ),
        "email_action_plan": main.run_core_pipeline(
            "处理邮件",
            {
                "pipeline_id": "email_pipeline",
                "mailbox": "gmail",
                "email_intent": "reply",
                "email_body": "Please send agenda for Friday and pay invoice 100 RMB.",
            },
        ),
        "chat_action_handoff": main.run_core_pipeline(
            "帮我打车",
            {
                "pipeline_id": "chat_response_pipeline",
                "conversation_id": "conv_ride",
                "message": "帮我打车",
                "action_cards": [{"label": "帮我打车", "target_pipeline": "ride_pipeline"}],
            },
        ),
        "agenda_duplicate_merge": main.run_core_pipeline(
            "记录周五和 Alex 见面",
            {
                "pipeline_id": "agenda_pipeline",
                "title": "和 Alex 见面",
                "time_window": {"text": "周五 20:00", "type": "exact", "start": "2026-05-29T20:00:00+08:00"},
                "participants": ["Alex"],
                "source_event_ids": ["evt_new"],
                "existing_agenda_candidates": [
                    {
                        "agenda_item_id": "agenda_old",
                        "title": "和 Alex 见面",
                        "time_window": {
                            "text": "周五 20:00",
                            "type": "exact",
                            "start": "2026-05-29T20:00:00+08:00",
                        },
                        "participants": ["Alex"],
                        "source_event_ids": ["evt_old"],
                    }
                ],
            },
        ),
        "todo_reschedule": main.run_core_pipeline(
            "把跟进合同改到明天",
            {
                "pipeline_id": "task_todo_pipeline",
                "task_title": "跟进合同",
                "operation": "reschedule",
                "previous_status": "open",
                "due_window": {"text": "明天", "type": "fuzzy"},
                "source_event_ids": ["evt_todo"],
            },
        ),
        "proactive_duplicate_suppressed": main.run_core_pipeline(
            "路线建议",
            {
                "pipeline_id": "proactive_suggestion_pipeline",
                "candidate_type": "route_need",
                "source_event_ids": ["evt_route"],
                "destination": "武康路",
                "recent_suggestions": [{"dedupe_key": "route_need:evt_route"}],
            },
        ),
        "ride_confirmation_plan": main.run_core_pipeline(
            "帮我打车",
            {
                "pipeline_id": "ride_pipeline",
                "pickup": "上海图书馆",
                "destination": "武康路",
            },
        ),
        "payment_confirmation_plan": main.run_core_pipeline(
            "付款",
            {
                "pipeline_id": "payment_bill_pipeline",
                "counterparty": "云服务商",
                "amount_or_bill": "100元",
            },
        ),
        "document_write_plan": main.run_core_pipeline(
            "改文档",
            {
                "pipeline_id": "document_file_pipeline",
                "file_or_query": "demo.docx",
                "document_intent": "write",
            },
        ),
        "account_login_plan": main.run_core_pipeline(
            "登录 Gmail",
            {
                "pipeline_id": "account_login_pipeline",
                "account_provider": "gmail",
                "login_url": "https://accounts.google.com/",
            },
        ),
        "governance_provider_audit": main.run_core_pipeline(
            "审计外部调用",
            {
                "pipeline_id": "governance_audit_pipeline",
                "task_id": "task_ride_1",
                "provider_call_plan": {
                    "provider": "uber",
                    "action": "estimate_ride",
                    "status": "proposed_only",
                },
                "confirmation_card": {
                    "kind": "ride_booking",
                    "confirm_action": "book_ride",
                    "final_user_confirmation": True,
                },
            },
        ),
    }
    stages.append(
        stage(
            "wave2_internal_pipeline_outputs_are_reasonable",
            {
                name: {
                    "status": result.get("status"),
                    "missing_slots": result.get("missing_slots"),
                    "output": result.get("output"),
                    "provider_call_plan": result.get("provider_call_plan"),
                    "confirmation_card": result.get("confirmation_card"),
                    "blocked_effects": result.get("blocked_effects"),
                }
                for name, result in wave2_results.items()
            },
            {
                "duplicate_event_skips_downstream": wave2_results["event_duplicate"]["status"] == "completed_read_only"
                and wave2_results["event_duplicate"]["output"]["downstream_jobs"] == []
                and wave2_results["event_duplicate"]["writeback_plan"][0]["target"] == "duplicate_skip",
                "schema_error_quarantines_event": wave2_results["event_quarantine"]["status"] == "blocked"
                and wave2_results["event_quarantine"]["output"]["quarantine_record"]["schema_errors"] == ["missing_message_id"]
                and wave2_results["event_quarantine"]["output"]["downstream_jobs"] == [],
                "ambiguous_private_search_asks_scope": wave2_results["ambiguous_private_search"]["status"] == "needs_user_input"
                and "search_scope" in wave2_results["ambiguous_private_search"]["missing_slots"]
                and wave2_results["ambiguous_private_search"]["output"]["scope_filter_report"]["excluded_count"] == 2,
                "reply_leakage_blocks_send": wave2_results["reply_leakage"]["status"] == "blocked"
                and wave2_results["reply_leakage"]["output"]["leakage_review"]["status"] == "blocked"
                and wave2_results["reply_leakage"]["output"]["confirmation_card"]["actions"] == ["blocked"],
                "email_action_plan_is_proposed_only": wave2_results["email_action_plan"]["output"]["provider_call_plan"]["status"]
                == "proposed_only"
                and {
                    item["type"]
                    for item in wave2_results["email_action_plan"]["output"]["internal_candidates"]
                }.issuperset({"agenda", "todo", "payment"}),
                "chat_action_handoff_targets_ride": wave2_results["chat_action_handoff"]["output"]["action_handoff"]["target_pipeline"]
                == "ride_pipeline",
                "agenda_duplicate_merge_is_explicit": wave2_results["agenda_duplicate_merge"]["output"]["merge_plan"]["decision"]
                == "duplicate"
                and wave2_results["agenda_duplicate_merge"]["output"]["merge_plan"]["source_event_ids"]
                == ["evt_new", "evt_old"],
                "todo_reschedule_has_lifecycle": wave2_results["todo_reschedule"]["output"]["todo_lifecycle"]["new_status"]
                == "open"
                and wave2_results["todo_reschedule"]["output"]["reminder_adjustment"]["action"] == "rescheduled",
                "duplicate_proactive_suggestion_is_suppressed": wave2_results["proactive_duplicate_suppressed"]["status"]
                == "suppressed"
                and wave2_results["proactive_duplicate_suppressed"]["output"]["delivery_decision"]["deliver"] is False,
                "ride_books_only_after_confirmation": wave2_results["ride_confirmation_plan"]["provider_call_plan"]["mode"]
                == "blocked_until_confirmation"
                and "book_ride" in wave2_results["ride_confirmation_plan"]["blocked_effects"],
                "payment_transfer_only_after_confirmation": wave2_results["payment_confirmation_plan"]["provider_call_plan"]["mode"]
                == "blocked_until_confirmation"
                and wave2_results["payment_confirmation_plan"]["output"]["risk_summary"]["level"] == "high",
                "document_write_only_after_confirmation": wave2_results["document_write_plan"]["provider_call_plan"]["mode"]
                == "blocked_until_confirmation"
                and "write_document" in wave2_results["document_write_plan"]["blocked_effects"],
                "account_login_keeps_credential_entry_user_side": wave2_results["account_login_plan"]["output"]["credential_handling"]
                == "user_enters_credentials_directly"
                and wave2_results["account_login_plan"]["output"]["controlled_browser_plan"]["credential_entry"] == "user_only"
                and wave2_results["account_login_plan"]["output"]["connection_health"]["status"] == "not_connected",
                "governance_records_provider_and_confirmation": wave2_results["governance_provider_audit"]["output"]["provider_call_audit"]["status"]
                == "planned"
                and wave2_results["governance_provider_audit"]["output"]["confirmation_ledger"]["required"] is True,
            },
        )
    )

    original_slot_model_enabled = os.environ.get("PIPELINE_SLOT_MODEL_ENABLED")
    original_slot_model = main.call_pipeline_slot_model
    os.environ["PIPELINE_SLOT_MODEL_ENABLED"] = "1"
    try:
        main.call_pipeline_slot_model = lambda request, pipeline, context, rule_slots: {
            "slots": {"recipient": "Alice", "message_intent": "周五八点可以", "destination": "外滩"},
            "confidence": 0.91,
            "reason": "验证模型补槽和冲突拒绝。",
        }
        hybrid_reply = main.run_core_pipeline(
            "帮我回复她，就说周五八点可以",
            {"active_source_scope": {"source": "whatsapp", "conversation_id": "chat-alice"}},
        )
        hybrid_route = main.run_core_pipeline("查路线去武康路")
    finally:
        main.call_pipeline_slot_model = original_slot_model
        if original_slot_model_enabled is None:
            os.environ.pop("PIPELINE_SLOT_MODEL_ENABLED", None)
        else:
            os.environ["PIPELINE_SLOT_MODEL_ENABLED"] = original_slot_model_enabled
    stages.append(
        stage(
            "hybrid_pipeline_slot_extraction_is_conservative",
            {"hybrid_reply": hybrid_reply, "hybrid_route": hybrid_route},
            {
                "model_fills_missing_recipient": hybrid_reply["resolved_slots"].get("recipient") == "Alice"
                and hybrid_reply["slot_extraction"]["parser_mode"] == "hybrid_model_rules"
                and hybrid_reply["slot_extraction"]["model_used"] is True,
                "rule_destination_not_overwritten": hybrid_route["resolved_slots"].get("destination") == "武康路"
                and "model_conflict:destination" in hybrid_route["slot_extraction"]["validation_warnings"],
            },
        )
    )

    persistence_exec: list[tuple[str, tuple[Any, ...]]] = []

    class PipelinePersistConn:
        def execute(self, sql: str, params: tuple[Any, ...] = ()):
            persistence_exec.append((" ".join(sql.split()), params))
            return None

    route_with_refs = main.route_tool_request(
        "查路线去武康路",
        {
            "source_event_ids": ["evt_1"],
            "conversation_id": "conv_1",
            "suggestion_id": "sug_1",
            "agenda_item_ids": ["agenda_1"],
        },
    )
    main.persist_task_route_trace(PipelinePersistConn(), route_with_refs)
    execution_with_refs = main.run_core_pipeline(
        "查路线去武康路",
        {
            "source_event_ids": ["evt_1"],
            "conversation_id": "conv_1",
            "suggestion_id": "sug_1",
            "agenda_item_ids": ["agenda_1"],
        },
    )
    main.persist_pipeline_execution_result(PipelinePersistConn(), execution_with_refs)
    route_insert = next(item for item in persistence_exec if "INSERT INTO task_route_traces" in item[0])
    execution_insert = next(item for item in persistence_exec if "INSERT INTO pipeline_execution_results" in item[0])
    stages.append(
        stage(
            "pipeline_execution_and_trace_refs_are_persisted",
            {
                "route_insert_sql": route_insert[0],
                "route_insert_refs": {
                    "source_event_ids": route_insert[1][11],
                    "conversation_id": route_insert[1][12],
                    "suggestion_id": route_insert[1][13],
                    "agenda_item_ids": route_insert[1][14],
                },
                "execution_insert_sql": execution_insert[0],
                "execution_insert_refs": {
                    "source_event_ids": execution_insert[1][12],
                    "conversation_id": execution_insert[1][13],
                    "suggestion_id": execution_insert[1][14],
                    "agenda_item_ids": execution_insert[1][15],
                },
            },
            {
                "route_insert_has_explicit_refs": "source_event_ids" in route_insert[0]
                and route_insert[1][11] == ["evt_1"]
                and route_insert[1][12] == "conv_1"
                and route_insert[1][13] == "sug_1"
                and route_insert[1][14] == ["agenda_1"],
                "execution_insert_has_explicit_refs": "pipeline_execution_results" in execution_insert[0]
                and execution_insert[1][12] == ["evt_1"]
                and execution_insert[1][13] == "conv_1"
                and execution_insert[1][14] == "sug_1"
                and execution_insert[1][15] == ["agenda_1"],
            },
        )
    )

    backfill_exec: list[tuple[str, tuple[Any, ...]]] = []

    class BackfillConn:
        def execute(self, sql: str, params: tuple[Any, ...] = ()):
            backfill_exec.append((" ".join(sql.split()), params))
            return None

    main.backfill_explicit_trace_references(BackfillConn())
    backfill_sql = [sql for sql, _ in backfill_exec]
    stages.append(
        stage(
            "historical_trace_refs_are_backfilled_to_explicit_columns",
            {
                "updates": [
                    "task_route_source_events"
                    if any("UPDATE task_route_traces t SET source_event_ids" in sql for sql in backfill_sql)
                    else None,
                    "task_route_conversation"
                    if any("UPDATE task_route_traces SET conversation_id" in sql for sql in backfill_sql)
                    else None,
                    "pipeline_execution_source_events"
                    if any("UPDATE pipeline_execution_results p SET source_event_ids" in sql for sql in backfill_sql)
                    else None,
                    "pipeline_execution_conversation"
                    if any("UPDATE pipeline_execution_results SET conversation_id" in sql for sql in backfill_sql)
                    else None,
                ],
            },
            {
                "route_refs_backfilled": any("UPDATE task_route_traces t SET source_event_ids" in sql for sql in backfill_sql)
                and any("UPDATE task_route_traces SET conversation_id" in sql for sql in backfill_sql)
                and any("UPDATE task_route_traces SET suggestion_id" in sql for sql in backfill_sql)
                and any("UPDATE task_route_traces t SET agenda_item_ids" in sql for sql in backfill_sql),
                "execution_refs_backfilled": any(
                    "UPDATE pipeline_execution_results p SET source_event_ids" in sql for sql in backfill_sql
                )
                and any("UPDATE pipeline_execution_results SET conversation_id" in sql for sql in backfill_sql)
                and any("UPDATE pipeline_execution_results SET suggestion_id" in sql for sql in backfill_sql)
                and any("UPDATE pipeline_execution_results p SET agenda_item_ids" in sql for sql in backfill_sql),
            },
        )
    )

    writeback_exec: list[tuple[str, tuple[Any, ...]]] = []

    class WritebackConn:
        def execute(self, sql: str, params: tuple[Any, ...] = ()):
            writeback_exec.append((" ".join(sql.split()), params))
            return None

    writeback_summary = main.apply_pipeline_writeback_plan(
        WritebackConn(),
        {
            "pipeline_execution_id": "exec_validate_writeback",
            "task_trace_id": "trace_validate_writeback",
            "pipeline_id": "validation_pipeline",
            "status": "completed_read_only",
            "writeback_plan": [
                {
                    "target": "events",
                    "operation": "upsert",
                    "payload": {
                        "event_id": "evt_validate_writeback",
                        "source": "whatsapp",
                        "event_type": "message",
                        "timestamp": "2026-05-28T10:00:00+08:00",
                        "raw_event": {"text": "周末见"},
                    },
                },
                {
                    "target": "agenda_items",
                    "operation": "create",
                    "item": {
                        "agenda_item_id": "agenda_validate_writeback",
                        "title": "Alex 周末见面",
                        "operation": "create",
                        "certainty": "fuzzy",
                        "time_window": {"start": "2026-05-30", "end": "2026-05-31"},
                        "missing_fields": ["exact_time", "exact_place"],
                        "source_event_ids": ["evt_validate_writeback"],
                    },
                },
                {
                    "target": "search_audit",
                    "operation": "record_personal_search",
                    "payload": {"query": "Alex 见面地点", "scope": "chat_alex", "result_count": 1},
                },
                {
                    "target": "route_cache",
                    "operation": "record_route_request",
                    "payload": {"origin": "当前位置", "destination": "武康路", "mode": "transit"},
                },
            ],
        },
    )
    writeback_sql = [sql for sql, _ in writeback_exec]
    stages.append(
        stage(
            "local_writeback_materializes_internal_targets",
            {
                "summary": writeback_summary,
                "insert_targets": [
                    "events" if any("INSERT INTO events" in sql for sql in writeback_sql) else None,
                    "agenda_items" if any("INSERT INTO agenda_items" in sql for sql in writeback_sql) else None,
                    "agenda_item_versions" if any("INSERT INTO agenda_item_versions" in sql for sql in writeback_sql) else None,
                    "search_audit" if any("INSERT INTO search_audit" in sql for sql in writeback_sql) else None,
                    "route_cache" if any("INSERT INTO route_cache" in sql for sql in writeback_sql) else None,
                    "pipeline_health_metrics" if any("INSERT INTO pipeline_health_metrics" in sql for sql in writeback_sql) else None,
                ],
            },
            {
                "applied_without_external_tools": writeback_summary.get("applied") is True
                and writeback_summary.get("applied_count") == 4,
                "event_row_written": any("INSERT INTO events" in sql for sql in writeback_sql),
                "agenda_and_version_written": any("INSERT INTO agenda_items" in sql for sql in writeback_sql)
                and any("INSERT INTO agenda_item_versions" in sql for sql in writeback_sql),
                "search_and_route_audited": any("INSERT INTO search_audit" in sql for sql in writeback_sql)
                and any("INSERT INTO route_cache" in sql for sql in writeback_sql),
                "health_metric_written": any("INSERT INTO pipeline_health_metrics" in sql for sql in writeback_sql),
            },
        )
    )

    original_db = main.db

    class LocalCursor:
        def __init__(self, rows: list[Any] | None = None):
            self.rows = rows or []

        def fetchall(self):
            return self.rows

    class LocalRetrievalConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql: str, params: tuple[Any, ...] = ()):
            normalized = " ".join(sql.split())
            if "FROM facts" in normalized:
                return LocalCursor(
                    [
                        (
                            "fact_validate_context",
                            "Alex",
                            "meeting_place",
                            "武康路",
                            0.93,
                            ["evt_validate_context"],
                            {"scope": {"kind": "contact", "id": "alex"}},
                            "2026-05-28T10:00:00+08:00",
                        )
                    ]
                )
            if "FROM memory_items" in normalized:
                return LocalCursor([])
            if "FROM agenda_items" in normalized:
                return LocalCursor(
                    [
                        (
                            "33333333-3333-3333-3333-333333333333",
                            "appointment",
                            "Alex 周末见面",
                            "scheduled",
                            "fuzzy",
                            {"start": "2026-05-30", "end": "2026-05-31"},
                            "",
                            ["Alex"],
                            ["exact_time", "exact_place"],
                            True,
                            0.84,
                            ["evt_validate_context"],
                            {"scope": {"kind": "contact", "id": "alex"}},
                            "2026-05-28T09:00:00+08:00",
                            "2026-05-28T09:00:00+08:00",
                            None,
                            None,
                            None,
                        )
                    ]
                )
            if "FROM assistant_turns" in normalized:
                return LocalCursor(
                    [
                        (
                            "44444444-4444-4444-4444-444444444444",
                            "conv-alex",
                            "user",
                            "帮我盯一下和 Alex 周末见面的事",
                            "2026-05-28T09:30:00+08:00",
                            {},
                        )
                    ]
                )
            return LocalCursor([])

    try:
        main.db = lambda: LocalRetrievalConn()
        local_context_pack = main.run_core_pipeline(
            "那就周日吧",
            {
                "pipeline_id": "context_pack_pipeline",
                "request_or_event_id": "req_validate_context",
                "current_scope": {"kind": "contact", "id": "alex"},
                "conversation_id": "conv-alex",
            },
        )
    finally:
        main.db = original_db

    stages.append(
        stage(
            "context_pack_pipeline_uses_local_retrieval_fallback",
            local_context_pack.get("output", {}),
            {
                "local_fact_included": local_context_pack["output"]["included_memory_ids"] == ["fact_validate_context"],
                "matching_agenda_included": local_context_pack["output"]["included_agenda_ids"]
                == ["33333333-3333-3333-3333-333333333333"],
                "recent_turn_included": local_context_pack["output"]["recent_turn_ids"]
                == ["44444444-4444-4444-4444-444444444444"],
                "scope_boundary_preserved": local_context_pack["output"]["scope_boundary"]["current_scope"]
                == {"kind": "contact", "id": "alex"},
            },
        )
    )

    openclaw = main.route_tool_request(
        "帮我去一个不支持 MCP 的网站填写报名表，但不要提交",
        {
            "current_url": "https://forms.example/apply?token=abc123&email=alice@example.com",
            "page_title": "报名表",
            "selected_text": "申请岗位：产品经理",
            "source_event_ids": ["evt_1"],
            "active_source_scope": {"source": "whatsapp", "conversation_id": "chat_a"},
            "raw_memory_dump": "另一个联系人 B 的隐私不应进入 OpenClaw。",
        },
    )
    minimal_context_text = json.dumps(
        (openclaw.get("openclaw_task_packet") or {}).get("minimal_context", {}),
        ensure_ascii=False,
    )
    stages.append(
        stage(
            "openclaw_packet_is_constrained",
            compact_route(openclaw),
            {
                "route_type_openclaw": openclaw["route_type"] == "openclaw_tool",
                "legacy_compat": openclaw["legacy_route_type"] == "long_tail_tool",
                "has_packet": bool(openclaw.get("openclaw_task_packet")),
                "can_fill_but_not_submit": "fill_form" in openclaw["openclaw_task_packet"]["allowed_actions"]
                and "submit" in openclaw["openclaw_task_packet"]["forbidden_actions"],
                "context_redacted": "token=REDACTED" in minimal_context_text and "alice@example.com" not in minimal_context_text,
                "unrelated_memory_excluded": "联系人 B" not in minimal_context_text,
            },
        )
    )

    context_necessity = openclaw["openclaw_task_packet"].get("context_necessity") or {}
    stages.append(
        stage(
            "openclaw_context_necessity_is_explained",
            {
                "mode": context_necessity.get("mode"),
                "sensitive": context_necessity.get("sensitive"),
                "decisions": context_necessity.get("decisions"),
            },
            {
                "has_mode": context_necessity.get("mode") in {"rules", "rules+model"},
                "current_url_included": context_necessity.get("decisions", {}).get("current_url", {}).get("include") is True,
                "raw_memory_excluded": context_necessity.get("decisions", {}).get("raw_memory_dump", {}).get("include") is False,
                "exclusion_reason_present": bool(
                    context_necessity.get("decisions", {}).get("raw_memory_dump", {}).get("reason")
                ),
            },
        )
    )

    dry_run = main.execute_openclaw_task_packet(openclaw["openclaw_task_packet"], openclaw["execution_guard"])
    stages.append(
        stage(
            "openclaw_execution_defaults_to_safe_dry_run",
            dry_run,
            {
                "dry_run_mode": dry_run.get("mode") == "dry_run",
                "blocked_without_enable": dry_run.get("status") == "blocked",
                "requires_confirmation": dry_run.get("needs_confirmation") is True,
                "reason_mentions_flag": "OPENCLAW_ENABLED" in dry_run.get("reason", ""),
            },
        )
    )

    gateway_events = main.normalize_openclaw_gateway_events(
        {
            "events": [
                {
                    "type": "tool_call",
                    "name": "browser.open",
                    "status": "completed",
                    "message": "打开报名页面",
                    "url": "https://forms.example/apply?token=abc123",
                }
            ]
        }
    )
    retry_transition = main.classify_openclaw_job_result(
        {"status": "failed", "error": "timeout while opening page"},
        attempt_count=1,
        max_attempts=3,
    )
    stages.append(
        stage(
            "openclaw_gateway_events_and_retry_policy_are_reasonable",
            {"gateway_events": gateway_events, "retry_transition": retry_transition},
            {
                "tool_event_normalized": gateway_events[0]["event_type"] == "tool_call"
                and gateway_events[0]["tool_name"] == "browser.open",
                "event_payload_redacted": gateway_events[0]["payload"]["url"] == "https://forms.example/apply?token=REDACTED",
                "transient_failure_retries": retry_transition["status"] == "retry_scheduled",
                "retry_delay_bounded": retry_transition["next_attempt_delay_seconds"] == 30,
            },
        )
    )

    job_id = "11111111-1111-1111-1111-111111111111"
    job_exec: list[tuple[str, tuple[Any, ...]]] = []

    class JobCursor:
        def fetchone(self):
            return (
                job_id,
                "openclaw_task_1",
                None,
                "queued",
                0,
                2,
                {"task_id": "openclaw_task_1", "goal": "打开页面"},
                {"permission": "external_execution", "requires_confirmation": True},
                None,
                None,
                "2026-05-28T08:00:00+00:00",
                "2026-05-28T08:00:00+00:00",
                "2026-05-28T08:00:00+00:00",
                None,
            )

    class JobConn:
        def execute(self, sql: str, params: tuple[Any, ...] = ()):
            job_exec.append((sql, params))
            if "SELECT id, task_id" in sql:
                return JobCursor()

    def fake_executor(packet: dict[str, Any], guard: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "failed",
            "error": "timeout while opening page",
            "events": [
                {
                    "event_type": "tool_call",
                    "tool_name": "browser.open",
                    "message": "打开页面超时",
                    "payload": {"url": "https://forms.example/apply?token=REDACTED"},
                }
            ],
        }

    job_run = main.run_openclaw_execution_job_once(JobConn(), job_id, executor=fake_executor)
    job_events = [params for sql, params in job_exec if "INSERT INTO openclaw_execution_events" in sql]
    stages.append(
        stage(
            "openclaw_job_run_once_records_attempt_tool_event_and_retry",
            {"job_run": job_run, "event_types": [event[2] for event in job_events]},
            {
                "job_retry_scheduled": job_run["status"] == "retry_scheduled",
                "attempt_incremented": job_run["attempt_count"] == 1,
                "attempt_event_recorded": any(event[2] == "attempt_started" for event in job_events),
                "tool_event_recorded": any(event[2] == "tool_call" and event[3] == "打开页面超时" for event in job_events),
                "retry_event_recorded": any(event[2] == "retry_scheduled" for event in job_events),
            },
        )
    )

    class DueCursor:
        def fetchall(self) -> list[tuple[str]]:
            return [
                ("11111111-1111-1111-1111-111111111111",),
                ("22222222-2222-2222-2222-222222222222",),
            ]

    due_queries: list[tuple[str, tuple[Any, ...]]] = []

    class DueConn:
        def execute(self, sql: str, params: tuple[Any, ...] = ()):
            due_queries.append((sql, params))
            return DueCursor()

    due_ids = main.fetch_due_openclaw_execution_job_ids(DueConn(), limit=2)
    stages.append(
        stage(
            "openclaw_background_runner_fetches_due_jobs_safely",
            {"due_ids": due_ids, "sql": due_queries[0][0] if due_queries else "", "params": due_queries[0][1] if due_queries else ()},
            {
                "returns_due_ids": due_ids
                == ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"],
                "only_due_statuses": bool(due_queries) and "status IN ('queued', 'retry_scheduled')" in " ".join(due_queries[0][0].split()),
                "respects_due_time": bool(due_queries) and "next_attempt_at <= now()" in " ".join(due_queries[0][0].split()),
                "uses_skip_locked": bool(due_queries) and "FOR UPDATE SKIP LOCKED" in " ".join(due_queries[0][0].split()),
            },
        )
    )

    realtime_exec: list[tuple[str, tuple[Any, ...]]] = []
    realtime_published: list[tuple[str, dict[str, Any]]] = []

    class RealtimeConn:
        def execute(self, sql: str, params: tuple[Any, ...] = ()):
            realtime_exec.append((sql, params))

    class RealtimeRedis:
        def publish(self, channel: str, payload: str) -> None:
            realtime_published.append((channel, json.loads(payload)))

    main.record_openclaw_execution_event(
        RealtimeConn(),
        job_id=job_id,
        event_type="tool_call",
        message="打开报名页面",
        payload={"url": "https://forms.example/apply?token=abc123"},
        redis_obj=RealtimeRedis(),
    )
    realtime_message = realtime_published[0][1] if realtime_published else {}
    stages.append(
        stage(
            "openclaw_job_events_publish_realtime_updates",
            {"published": realtime_published[0] if realtime_published else None},
            {
                "event_row_written": bool(realtime_exec)
                and "INSERT INTO openclaw_execution_events" in realtime_exec[0][0],
                "published_to_realtime_channel": bool(realtime_published)
                and realtime_published[0][0] == main.REALTIME_CHANNEL,
                "message_type_is_job_event": realtime_message.get("type") == "openclaw_job_event",
                "job_id_preserved": realtime_message.get("job_id") == job_id,
                "payload_redacted": realtime_message.get("payload", {}).get("url")
                == "https://forms.example/apply?token=REDACTED",
            },
        )
    )

    executed: list[tuple[str, tuple[Any, ...]]] = []

    class TraceConn:
        def execute(self, sql: str, params: tuple[Any, ...] = ()):
            executed.append((sql, params))

    trace_id = main.persist_task_route_trace(TraceConn(), openclaw)
    stages.append(
        stage(
            "task_route_trace_persistence_payload_is_reasonable",
            {
                "trace_id": trace_id,
                "sql": executed[0][0] if executed else "",
                "route_type": executed[0][1][2] if executed else None,
                "capability_id": executed[0][1][3] if executed else None,
                "packet_goal": (executed[0][1][8] or {}).get("goal") if executed else None,
            },
            {
                "inserted_trace": bool(executed) and "INSERT INTO task_route_traces" in executed[0][0],
                "trace_id_matches": trace_id == openclaw["task_trace_id"],
                "route_type_openclaw": bool(executed) and executed[0][1][2] == "openclaw_tool",
                "capability_matches": bool(executed) and executed[0][1][3] == "automation.browser.operate",
                "packet_goal_preserved": bool(executed)
                and (executed[0][1][8] or {}).get("goal") == "帮我去一个不支持 MCP 的网站填写报名表，但不要提交",
            },
        )
    )

    class TraceCursor:
        def __init__(self, rows: list[tuple[Any, ...]]):
            self.rows = rows

        def fetchall(self) -> list[tuple[Any, ...]]:
            return self.rows

    queried: list[tuple[str, tuple[Any, ...]]] = []

    class QueryTraceConn:
        def execute(self, sql: str, params: tuple[Any, ...] = ()):
            queried.append((sql, params))
            return TraceCursor(
                [
                    (
                        openclaw["task_trace_id"],
                        openclaw["request"],
                        openclaw["route_type"],
                        openclaw["capability"]["id"],
                        None,
                        openclaw["execution_guard"]["permission"],
                        True,
                        openclaw["task_route_decision"],
                        openclaw["openclaw_task_packet"],
                        None,
                        openclaw["openclaw_task_packet"]["minimal_context"],
                        "2026-05-28T08:00:00+00:00",
                    )
                ]
            )

    traces = main.fetch_task_route_traces(
        QueryTraceConn(),
        route_type="openclaw_tool",
        capability="automation.browser.operate",
        q="报名",
        limit=5,
    )
    stages.append(
        stage(
            "task_route_trace_query_is_filterable_and_auditable",
            {
                "sql": queried[0][0] if queried else "",
                "params": queried[0][1] if queried else (),
                "trace": traces[0] if traces else {},
            },
            {
                "has_query": bool(queried) and "FROM task_route_traces" in queried[0][0],
                "uses_all_filters": bool(queried) and queried[0][1] == ("openclaw_tool", "automation.browser.operate", "%报名%", 5),
                "returns_packet_goal": bool(traces)
                and traces[0]["openclaw_task_packet"]["goal"] == "帮我去一个不支持 MCP 的网站填写报名表，但不要提交",
                "returns_context_summary": bool(traces) and "current_url" in traces[0]["context_summary"],
            },
        )
    )

    release = main.build_sensitive_field_release(
        field="phone",
        value="+86 138 0000 0000",
        purpose="填写报名表联系电话",
        task_id="openclaw_apply_form",
    )
    released = main.route_tool_request(
        "帮我去一个不支持 MCP 的网站填写报名表，但不要提交",
        {
            "current_url": "https://forms.example/apply?token=abc123",
            "user_approved_fields": {"phone": "+86 138 0000 0000"},
            "approved_sensitive_fields": release["approved_sensitive_fields"],
        },
    )
    released_packet = released["openclaw_task_packet"]
    released_context_text = json.dumps(released_packet["minimal_context"], ensure_ascii=False)
    stages.append(
        stage(
            "approved_sensitive_field_release_is_explicit_and_narrow",
            {
                "minimal_context": released_packet["minimal_context"],
                "context_necessity": released_packet["context_necessity"],
            },
            {
                "ordinary_approved_field_redacted": released_packet["minimal_context"]["user_approved_fields"]["phone"]
                == "PHONE_1",
                "formal_release_carries_raw_value": released_packet["minimal_context"]["approved_sensitive_fields"]["phone"]["value"]
                == "+86 138 0000 0000",
                "release_auditable": released_packet["minimal_context"]["approved_sensitive_fields"]["phone"]["approval_id"].startswith("sfr_"),
                "only_released_copy_is_raw": released_context_text.count("+86 138 0000 0000") == 1,
                "necessity_records_release": released_packet["context_necessity"]["approved_sensitive_releases"][0]["field"]
                == "phone",
            },
        )
    )

    ambiguous = main.route_tool_request("帮我付款")
    stages.append(
        stage(
            "ambiguous_payment_asks_user",
            compact_route(ambiguous),
            {
                "route_type_ask_user": ambiguous["route_type"] == "ask_user",
                "no_packet": "openclaw_task_packet" not in ambiguous,
                "missing_amount": "amount_or_bill" in ambiguous.get("clarification", {}).get("missing_fields", []),
                "missing_counterparty": "counterparty" in ambiguous.get("clarification", {}).get("missing_fields", []),
                "reason_requires_confirmation": "需要先确认" in ambiguous["routing_reason"],
            },
        )
    )

    print(json.dumps({"stages": stages}, ensure_ascii=False, indent=2))
    return 0 if all(item["reasonable"] for item in stages) else 1


if __name__ == "__main__":
    raise SystemExit(main_script())
