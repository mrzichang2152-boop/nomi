from __future__ import annotations

from typing import Any, Callable

from app.pipelines.base import pipeline_result


def run_contact_relationship_pipeline(pipeline_id: str, request: str, context: dict[str, Any]) -> dict[str, Any] | None:
    if pipeline_id != "contact_relationship_pipeline":
        return None
    contact = context.get("contact_or_actor") or context.get("actor") or context.get("contact")
    resolved_slots = {"contact_or_actor": str(contact)} if contact else {}
    status = "completed_read_only" if contact else "needs_user_input"
    source_event_ids = [str(item) for item in context.get("source_event_ids") or []]
    degree = int(context.get("relationship_degree") or context.get("graph_degree") or len(context.get("existing_edges") or []))
    degree_limit = int(context.get("supernode_degree_limit") or 80)
    is_supernode = degree >= degree_limit
    correction_text = str(context.get("user_correction") or "")
    is_correction = bool(correction_text) or any(marker in str(request) for marker in ["不是", "纠正", "改成", "别再", "删除这条"])
    scope = {
        "conversation_id": context.get("conversation_id"),
        "source_event_ids": source_event_ids,
        "visibility_scope": context.get("visibility_scope") or "contact_scoped",
        "supernode_mitigation": is_supernode,
    }
    relationship_fact = context.get("relationship_fact") or context.get("fact") or request
    relationship_update = {
        "contact_or_actor": str(contact) if contact else None,
        "fact": str(relationship_fact or "").strip(),
        "scope": scope,
        "sensitivity": context.get("sensitivity", "scoped_contact_memory"),
        "source_event_ids": source_event_ids,
        "write_mode": "scoped_edge_only" if is_supernode else "normal_scoped_edge",
    }
    supernode_metrics = {
        "degree": degree,
        "degree_limit": degree_limit,
        "is_supernode": is_supernode,
        "mitigation": "avoid_global_edge_promotion" if is_supernode else "not_needed",
    }
    correction_plan = {
        "is_correction": is_correction,
        "correction_text": correction_text or (request if is_correction else ""),
        "action": "write_memory_audit_and_keep_scope" if is_correction else "none",
    }
    writeback_plan = [
        {
            "target": "knowledge_entities",
            "operation": "upsert",
            "payload": {"name": str(contact) if contact else None, "scope": scope},
        },
        {
            "target": "knowledge_edges",
            "operation": "upsert_scoped_fact",
            "payload": relationship_update,
        },
        {
            "target": "memory_items",
            "operation": "upsert_scoped_memory",
            "payload": relationship_update,
        },
    ]
    if is_correction:
        writeback_plan.append(
            {
                "target": "memory_audit_log",
                "operation": "append_correction",
                "payload": {
                    "target_type": "contact_relationship",
                    "target_id": str(contact or ""),
                    "reason": correction_plan["correction_text"],
                    "supernode_metrics": supernode_metrics,
                    "source_event_ids": source_event_ids,
                },
            }
        )
    return pipeline_result(
        pipeline_id=pipeline_id,
        status=status,
        required_slots=["contact_or_actor"],
        resolved_slots=resolved_slots,
        permission="read_only",
        steps=["抽取联系人事实", "判断关系作用域", "更新图谱", "记录证据"],
        output={
            "summary": "联系人关系更新计划已生成，保持在来源会话作用域内。",
            "relationship_update": relationship_update,
            "supernode_metrics": supernode_metrics,
            "correction_plan": correction_plan,
            "leakage_policy": "do_not_recall_in_other_contact_context_without_explicit_global_search",
        },
        writeback_targets=["knowledge_entities", "knowledge_edges", "memory_items", "memory_audit_log", "task_trace"],
        writeback_plan=writeback_plan,
    )


def run_governance_pipeline(pipeline_id: str, request: str, context: dict[str, Any]) -> dict[str, Any] | None:
    if pipeline_id != "governance_audit_pipeline":
        return None
    task_id = context.get("task_id")
    resolved_slots = {"task_id": task_id} if task_id else {}
    status = "completed_read_only" if task_id else "needs_user_input"
    trace_chain = {
        "task_id": task_id,
        "source_event_ids": [str(item) for item in context.get("source_event_ids") or []],
        "conversation_id": context.get("conversation_id"),
        "suggestion_id": context.get("suggestion_id"),
        "agenda_item_ids": [str(item) for item in context.get("agenda_item_ids") or []],
    }
    provider_call_plan = context.get("provider_call_plan") if isinstance(context.get("provider_call_plan"), dict) else {}
    confirmation_card = context.get("confirmation_card") if isinstance(context.get("confirmation_card"), dict) else {}
    provider_call_audit = {
        "status": "planned" if provider_call_plan else "not_applicable",
        "provider": provider_call_plan.get("provider"),
        "action": provider_call_plan.get("action"),
        "call_status": provider_call_plan.get("status"),
        "task_id": task_id,
    }
    confirmation_ledger = {
        "required": bool(confirmation_card),
        "kind": confirmation_card.get("kind"),
        "confirm_action": confirmation_card.get("confirm_action"),
        "final_user_confirmation": bool(confirmation_card.get("final_user_confirmation")),
        "task_id": task_id,
    }
    writeback_targets = ["task_route_traces", "pipeline_execution_results", "memory_audit_log"]
    writeback_plan = [
        {"target": "task_route_traces", "operation": "link_or_verify", "task_id": task_id},
        {"target": "pipeline_execution_results", "operation": "link_or_verify", "task_id": task_id},
    ]
    if provider_call_plan:
        writeback_targets.append("provider_call_traces")
        writeback_plan.append(
            {
                "target": "provider_call_traces",
                "operation": "append_planned_call",
                "task_id": task_id,
                "payload": provider_call_audit,
            }
        )
    if confirmation_card:
        writeback_targets.append("confirmation_ledger")
        writeback_plan.append(
            {
                "target": "confirmation_ledger",
                "operation": "append_required_confirmation",
                "task_id": task_id,
                "payload": confirmation_ledger,
            }
        )
    return pipeline_result(
        pipeline_id=pipeline_id,
        status=status,
        required_slots=["task_id"],
        resolved_slots=resolved_slots,
        permission="read_only",
        steps=["记录路由", "记录风险", "记录确认", "记录输出", "记录反馈"],
        output={
            "summary": "治理审计链路已准备记录。",
            "trace_chain": trace_chain,
            "provider_call_audit": provider_call_audit,
            "confirmation_ledger": confirmation_ledger,
            "audit_records": [
                {"table": "task_route_traces", "reference": task_id},
                {"table": "pipeline_execution_results", "reference": task_id},
            ],
        },
        writeback_targets=writeback_targets,
        writeback_plan=writeback_plan,
    )


def _optional_runner(module_name: str, function_name: str) -> Callable[[str, str, dict[str, Any]], dict[str, Any] | None] | None:
    try:
        module = __import__(module_name, fromlist=[function_name])
    except Exception:
        return None
    runner = getattr(module, function_name, None)
    return runner if callable(runner) else None


def run_registered_pipeline(pipeline_id: str, request: str, context: dict[str, Any]) -> dict[str, Any] | None:
    runners = [
        run_governance_pipeline,
        run_contact_relationship_pipeline,
        _optional_runner("app.pipelines.system", "run_system_pipeline"),
        _optional_runner("app.pipelines.communication", "run_communication_pipeline"),
        _optional_runner("app.pipelines.agenda", "run_agenda_pipeline"),
        _optional_runner("app.pipelines.actions", "run_action_pipeline"),
        _optional_runner("app.pipelines.career", "run_career_pipeline"),
    ]
    for runner in runners:
        if runner is None:
            continue
        result = runner(pipeline_id, request, context)
        if result is not None:
            return result
    return None
