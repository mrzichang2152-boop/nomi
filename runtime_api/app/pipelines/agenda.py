from __future__ import annotations

import re
from typing import Any


OWNED_PIPELINES = {"agenda_pipeline", "task_todo_pipeline", "proactive_suggestion_pipeline"}


def _list_refs(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)]


def _missing(required_slots: list[str], resolved_slots: dict[str, Any]) -> list[str]:
    return [
        slot
        for slot in required_slots
        if resolved_slots.get(slot) is None or resolved_slots.get(slot) == "" or resolved_slots.get(slot) == []
    ]


def _step_list(names: list[str], status: str) -> list[dict[str, str]]:
    blocked = status in {"needs_user_input", "blocked", "failed"}
    return [{"name": name, "status": "pending" if blocked else "completed"} for name in names]


def _base_result(
    *,
    pipeline_id: str,
    status: str,
    required_slots: list[str],
    resolved_slots: dict[str, Any],
    risk: dict[str, Any],
    execution_guard: dict[str, Any],
    external_effects: list[str],
    writeback_targets: list[str],
    steps: list[str],
    output: dict[str, Any],
    writeback_plan: list[dict[str, Any]],
    slot_extraction: dict[str, Any],
) -> dict[str, Any]:
    return {
        "pipeline_id": pipeline_id,
        "status": status,
        "required_slots": required_slots,
        "resolved_slots": resolved_slots,
        "missing_slots": _missing(required_slots, resolved_slots),
        "risk": risk,
        "execution_guard": execution_guard,
        "external_effects": external_effects,
        "writeback_targets": writeback_targets,
        "steps": _step_list(steps, status),
        "output": output,
        "provider_calls": [],
        "writeback_plan": writeback_plan,
        "slot_extraction": slot_extraction,
    }


def _context_candidate(context: dict[str, Any]) -> dict[str, Any]:
    rule_candidate = context.get("rule_candidate") if isinstance(context.get("rule_candidate"), dict) else {}
    candidate = dict(rule_candidate)
    for key in ["title", "time_window", "task_title", "owner", "due_window", "candidate_type", "destination"]:
        if context.get(key) not in (None, "", []):
            candidate[key] = context[key]
    return candidate


def _is_exact_time(value: Any) -> bool:
    if isinstance(value, dict):
        value_type = str(value.get("type") or "").lower()
        return value_type == "exact" or bool(value.get("start") or value.get("at"))
    if isinstance(value, str):
        return bool(re.search(r"\d{1,2}[:：]\d{2}|\d{4}-\d{2}-\d{2}T", value))
    return False


def _agenda_slots(request: str, context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    rule_candidate = _context_candidate(context)
    model_candidate = context.get("model_candidate") if isinstance(context.get("model_candidate"), dict) else {}
    warnings: list[str] = []
    resolved: dict[str, Any] = {}

    if rule_candidate.get("title"):
        resolved["title"] = rule_candidate["title"]
    elif model_candidate.get("title"):
        resolved["title"] = model_candidate["title"]
    else:
        title = re.sub(r"^(帮我|请|记一下|安排|创建|新增)", "", request).strip(" ，,。.!！?？")
        if title:
            resolved["title"] = title

    rule_time = rule_candidate.get("time_window")
    model_time = model_candidate.get("time_window")
    rule_rejects_exact = rule_candidate.get("exact_time_supported") is False
    if rule_time not in (None, "", []):
        resolved["time_window"] = rule_time
        if model_time not in (None, "", []) and _is_exact_time(model_time) and not _is_exact_time(rule_time) and rule_rejects_exact:
            warnings.append("unsupported_model_exact_time:time_window")
    elif model_time not in (None, "", []):
        resolved["time_window"] = model_time
    elif context.get("time_phrase"):
        resolved["time_window"] = {"text": str(context["time_phrase"]), "type": "fuzzy"}

    operation = str(context.get("operation") or rule_candidate.get("operation") or model_candidate.get("operation") or "create")
    if operation not in {"create", "reschedule", "cancel", "update", "complete"}:
        warnings.append(f"unsupported_operation:{operation}")
        operation = "update"
    resolved["operation"] = operation
    agenda_item_id = context.get("agenda_item_id")
    if agenda_item_id:
        resolved["agenda_item_id"] = str(agenda_item_id)
    source_event_ids = _list_refs(context.get("source_event_ids"))
    if source_event_ids:
        resolved["source_event_ids"] = source_event_ids
    participants = _list_refs(context.get("participants") or rule_candidate.get("participants") or model_candidate.get("participants"))
    if participants:
        resolved["participants"] = participants

    trace = {
        "parser_mode": "module_rules_with_candidate_validation",
        "model_used": bool(model_candidate),
        "rule_slots": rule_candidate,
        "model_slots": model_candidate,
        "validation_warnings": warnings,
    }
    return resolved, trace


def _normalized_set(value: Any) -> set[str]:
    return {item.lower() for item in _list_refs(value)}


def _same_time(left: Any, right: Any) -> bool:
    return left not in (None, "", []) and right not in (None, "", []) and left == right


def _agenda_item_id(item: dict[str, Any]) -> str | None:
    value = item.get("agenda_item_id") or item.get("id")
    return str(value) if value not in (None, "", []) else None


def _build_merge_plan(resolved_slots: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    candidates = context.get("existing_agenda_candidates")
    if not isinstance(candidates, list):
        candidates = []
    candidates = [item for item in candidates if isinstance(item, dict)]
    operation = str(resolved_slots.get("operation") or "create")
    agenda_item_id = resolved_slots.get("agenda_item_id")
    title = str(resolved_slots.get("title") or "").strip().lower()
    time_window = resolved_slots.get("time_window")
    participants = _normalized_set(resolved_slots.get("participants"))
    source_event_ids = set(resolved_slots.get("source_event_ids", []))

    def candidate_score(candidate: dict[str, Any]) -> tuple[int, list[str]]:
        score = 0
        reasons: list[str] = []
        candidate_id = _agenda_item_id(candidate)
        if agenda_item_id and candidate_id == agenda_item_id:
            score += 8
            reasons.append("explicit_item_id_match")
        candidate_sources = set(_list_refs(candidate.get("source_event_ids")))
        if source_event_ids and source_event_ids & candidate_sources:
            score += 6
            reasons.append("source_event_overlap")
        candidate_title = str(candidate.get("title") or "").strip().lower()
        title_matches = bool(title and candidate_title == title)
        time_matches = _same_time(time_window, candidate.get("time_window"))
        participant_overlap = bool(participants and participants & _normalized_set(candidate.get("participants")))
        if title_matches:
            score += 2
        if time_matches:
            score += 2
        if participant_overlap:
            score += 1
        if title_matches and time_matches and (participant_overlap or not participants):
            reasons.append("title_time_participants_overlap")
        elif title_matches and participant_overlap:
            reasons.append("title_participants_overlap")
        elif title_matches:
            reasons.append("title_overlap")
        return score, reasons

    ranked: list[tuple[dict[str, Any], int, list[str]]] = []
    for candidate in candidates:
        score, reasons = candidate_score(candidate)
        if score:
            ranked.append((candidate, score, reasons))
    ranked.sort(key=lambda item: item[1], reverse=True)

    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return {
            "decision": "ambiguous",
            "matched_item_id": None,
            "candidate_item_ids": [_agenda_item_id(item[0]) for item in ranked],
            "reason": ["multiple_existing_candidates_match"],
            "source_event_ids": sorted(source_event_ids),
        }

    if not ranked:
        return {
            "decision": "create",
            "matched_item_id": None,
            "candidate_item_ids": [],
            "reason": ["no_existing_candidate"],
            "source_event_ids": sorted(source_event_ids),
        }

    match, _, reasons = ranked[0]
    matched_id = _agenda_item_id(match)
    matched_sources = set(_list_refs(match.get("source_event_ids")))
    if operation in {"reschedule", "cancel"}:
        decision = operation
    elif operation in {"update", "complete"}:
        decision = "update"
    elif _same_time(time_window, match.get("time_window")):
        decision = "duplicate"
    else:
        decision = "update"
    return {
        "decision": decision,
        "matched_item_id": matched_id,
        "candidate_item_ids": [matched_id] if matched_id else [],
        "reason": reasons or [f"{decision}_requested"],
        "source_event_ids": sorted(source_event_ids | matched_sources),
    }


def _build_conflict_plan(context: dict[str, Any]) -> dict[str, Any]:
    same_time_items = context.get("same_time_agenda_items") or context.get("conflicting_agenda_items")
    if not isinstance(same_time_items, list):
        same_time_items = []
    conflicting_ids = [
        str(item.get("agenda_item_id") or item.get("id"))
        for item in same_time_items
        if isinstance(item, dict) and (item.get("agenda_item_id") or item.get("id"))
    ]
    if len(conflicting_ids) < 2:
        return {"conflict_type": "none", "conflicting_item_ids": [], "resolution_options": []}
    return {
        "conflict_type": "same_time_multiple_items",
        "conflicting_item_ids": conflicting_ids,
        "resolution_options": [
            {"action": "keep_both", "confirmation_required": False},
            {"action": "merge_items", "confirmation_required": False},
            {"action": "reschedule_one", "confirmation_required": False},
        ],
    }


def _build_notification_plan(time_window: Any, source_event_ids: list[str]) -> dict[str, Any]:
    if _is_exact_time(time_window):
        return {
            "time_precision": "exact",
            "concrete_reminder": {"time_window": time_window, "source_event_ids": source_event_ids},
            "items": [{"type": "reminder", "status": "planned_internal", "time_window": time_window}],
        }
    return {
        "time_precision": "fuzzy",
        "concrete_reminder": None,
        "items": [
            {"type": "clarification", "status": "available", "reason": "time_window_is_fuzzy"},
            {"type": "monitor", "status": "planned_internal", "source_event_ids": source_event_ids},
        ],
    }


def _run_single_agenda_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    required_slots = ["time_window", "title"]
    resolved_slots, slot_trace = _agenda_slots(request, context)
    missing_slots = _missing(required_slots, resolved_slots)
    status = "needs_user_input" if missing_slots else "confirmation_required"
    operation = str(resolved_slots.get("operation") or "create")
    item_status = "completed" if operation == "complete" else operation
    agenda_item = {
        "agenda_item_id": resolved_slots.get("agenda_item_id"),
        "title": resolved_slots.get("title"),
        "time_window": resolved_slots.get("time_window"),
        "operation": operation,
        "status": item_status,
        "source_event_ids": resolved_slots.get("source_event_ids", []),
    }
    if resolved_slots.get("participants"):
        agenda_item["participants"] = resolved_slots["participants"]
    merge_plan = _build_merge_plan(resolved_slots, context)
    conflict_plan = _build_conflict_plan(context)
    notification_plan = _build_notification_plan(resolved_slots.get("time_window"), resolved_slots.get("source_event_ids", []))
    writeback_plan = [
        {
            "target": "agenda_items",
            "operation": operation,
            "item": agenda_item,
            "confirmation_required": False,
        },
        {
            "target": "external_calendar",
            "operation": "propose_write",
            "item": agenda_item,
            "confirmation_required": True,
            "reason": "external calendar writes require explicit user confirmation",
        },
    ]
    return _base_result(
        pipeline_id="agenda_pipeline",
        status=status,
        required_slots=required_slots,
        resolved_slots=resolved_slots,
        risk={"permission": "write", "confirmation_required": True, "final_user_confirmation": False},
        execution_guard={
            "permission": "write",
            "policy": "internal_agenda_write_allowed_external_calendar_requires_confirmation",
            "requires_confirmation": True,
            "final_user_confirmation": False,
        },
        external_effects=["write_calendar"],
        writeback_targets=["agenda_items", "agenda_item_versions", "proactive_candidates", "task_trace"],
        steps=["解析日程候选", "校验时间精度", "生成内部日程写入计划", "准备外部日历确认"],
        output={
            "summary": "已准备内部日程写入计划，外部日历写入需确认。",
            "agenda_item": agenda_item,
            "merge_plan": merge_plan,
            "conflict_plan": conflict_plan,
            "notification_plan": notification_plan,
        },
        writeback_plan=writeback_plan,
        slot_extraction=slot_trace,
    )


def _extract_due_window(request: str, context: dict[str, Any]) -> Any:
    if context.get("due_window") not in (None, "", []):
        return context["due_window"]
    for phrase in ["今天", "今晚", "明天上午", "明天下午", "明天", "周末", "周日", "周六"]:
        if phrase in request:
            return {"text": phrase, "type": "fuzzy"}
    return None


def _extract_task_title(request: str, context: dict[str, Any], due_window: Any) -> str | None:
    explicit = context.get("task_title") or context.get("title")
    if explicit:
        return str(explicit)
    text = request.strip(" ，,。.!！?？")
    text = re.sub(r"^(提醒我|记得|帮我记一下|帮我|请)", "", text).strip()
    if isinstance(due_window, dict) and due_window.get("text"):
        text = text.replace(str(due_window["text"]), "", 1).strip()
    text = re.sub(r"^(要|去|得)", "", text).strip()
    return text or None


def _run_task_todo_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    required_slots = ["task_title"]
    due_window = _extract_due_window(request, context)
    task_title = _extract_task_title(request, context, due_window)
    source_event_ids = _list_refs(context.get("source_event_ids"))
    owner = str(context.get("owner") or ("me" if "我" in request else "unknown"))
    operation = str(context.get("operation") or "create")
    if operation not in {"create", "complete", "cancel", "reschedule", "update"}:
        operation = "update"
    todo_item_id = context.get("todo_item_id")
    previous_status = context.get("previous_status")
    new_status_by_operation = {
        "create": "open",
        "update": str(previous_status or "open"),
        "complete": "completed",
        "cancel": "cancelled",
        "reschedule": str(previous_status or "open"),
    }
    new_status = new_status_by_operation[operation]
    resolved_slots: dict[str, Any] = {
        "task_title": task_title,
        "owner": owner,
        "due_window": due_window,
        "source_event_ids": source_event_ids,
        "operation": operation,
    }
    if todo_item_id:
        resolved_slots["todo_item_id"] = str(todo_item_id)
    missing_slots = _missing(required_slots, resolved_slots)
    status = "needs_user_input" if missing_slots else "completed_read_only"
    todo_item = {
        "todo_item_id": str(todo_item_id) if todo_item_id else None,
        "task_title": task_title,
        "owner": owner,
        "due_window": due_window,
        "source_event_ids": source_event_ids,
        "status": new_status,
        "operation": operation,
    }
    todo_lifecycle = {
        "previous_status": previous_status,
        "new_status": new_status,
        "reason": f"{operation}_requested",
        "source_event_ids": source_event_ids,
    }
    reminder_adjustment = (
        {
            "action": "rescheduled",
            "due_window": due_window,
            "source_event_ids": source_event_ids,
            "confirmation_required": False,
        }
        if operation == "reschedule"
        else None
    )
    reminder_plan = {
        "status": "planned_internal",
        "due_window": due_window,
        "source_event_ids": source_event_ids,
    }
    writeback_plan = [
        {"target": "internal_todos", "operation": operation, "item": todo_item, "confirmation_required": False},
        {"target": "internal_reminders", "operation": "plan", "item": reminder_plan, "confirmation_required": False},
        {
            "target": "external_task_tool",
            "operation": "propose_write",
            "item": todo_item,
            "confirmation_required": True,
        },
    ]
    return _base_result(
        pipeline_id="task_todo_pipeline",
        status=status,
        required_slots=required_slots,
        resolved_slots=resolved_slots,
        risk={"permission": "write", "confirmation_required": False, "final_user_confirmation": False},
        execution_guard={
            "permission": "write",
            "policy": "internal_todo_write_allowed_external_task_tool_requires_confirmation",
            "requires_confirmation": False,
            "final_user_confirmation": False,
        },
        external_effects=["write_task"],
        writeback_targets=["agenda_items", "agenda_item_versions", "proactive_suggestions", "task_trace"],
        steps=["识别待办", "解析负责人和截止窗口", "生成内部待办", "计划提醒", "准备外部任务确认"],
        output={
            "summary": "已准备内部待办和提醒计划。",
            "todo_item": todo_item,
            "reminder_plan": reminder_plan,
            "todo_lifecycle": todo_lifecycle,
            "reminder_adjustment": reminder_adjustment,
        },
        writeback_plan=writeback_plan,
        slot_extraction={
            "parser_mode": "module_rules",
            "model_used": False,
            "rule_slots": resolved_slots,
            "model_slots": {},
            "validation_warnings": [],
        },
    )


def _action(label: str, target_pipeline: str, permission: str, confirmation_required: bool, final: bool = False) -> dict[str, Any]:
    return {
        "label": label,
        "target_pipeline": target_pipeline,
        "risk": {
            "permission": permission,
            "confirmation_required": confirmation_required,
            "final_user_confirmation": final,
        },
    }


def _is_route_candidate(candidate_type: str, context: dict[str, Any], request: str) -> bool:
    lowered = candidate_type.lower()
    return any(term in lowered for term in ["route", "travel", "ride"]) or bool(context.get("destination")) or "路线" in request


def _run_proactive_suggestion_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    required_slots = ["candidate_type", "source_event_ids"]
    inferred_candidate_type = "route_need" if _is_route_candidate("", context, request) else None
    candidate_type = context.get("candidate_type") or inferred_candidate_type
    source_event_ids = _list_refs(context.get("source_event_ids"))
    destination = context.get("destination")
    resolved_slots = {"candidate_type": candidate_type, "source_event_ids": source_event_ids}
    missing_slots = _missing(required_slots, resolved_slots)
    status = "needs_user_input" if missing_slots else "draft_ready"

    if _is_route_candidate(str(candidate_type or ""), context, request):
        title = f"去{destination}前要不要看一下路线？" if destination else "要不要先看一下路线？"
        body = "我可以先查路线，也可以准备打车方案；真正叫车前还会再确认。"
        actions = [
            _action("查路线", "route_pipeline", "read_only", False),
            _action("帮我打车", "ride_pipeline", "payment_or_purchase", True, True),
            _action("稍后提醒", "task_todo_pipeline", "write", False),
        ]
    else:
        title = "有一条新的主动建议"
        body = "我整理成了建议卡片，可以稍后提醒或打开相关任务。"
        actions = [_action("稍后提醒", "task_todo_pipeline", "write", False)]

    cooldown = context.get("cooldown") if isinstance(context.get("cooldown"), dict) else {}
    dedupe = context.get("dedupe") if isinstance(context.get("dedupe"), dict) else {}
    cooldown_key_type = str(candidate_type or "unknown")
    cooldown = {
        "key": cooldown.get("key") or f"{cooldown_key_type}:{','.join(source_event_ids)}",
        "seconds_remaining": int(
            context.get("cooldown_seconds_remaining")
            if context.get("cooldown_seconds_remaining") not in (None, "")
            else cooldown.get("seconds_remaining") or 0
        ),
    }
    recent_suggestions = context.get("recent_suggestions") if isinstance(context.get("recent_suggestions"), list) else []
    recent_duplicate = any(
        isinstance(item, dict)
        and (item.get("dedupe_key") == cooldown["key"] or item.get("key") == cooldown["key"])
        for item in recent_suggestions
    )
    dedupe = {
        "key": dedupe.get("key") or cooldown["key"],
        "matched_existing": bool(dedupe.get("matched_existing", False) or recent_duplicate),
    }
    suggestion_card = {"title": title, "body": body, "actions": actions}
    explicit_cooldown_active = (
        context.get("cooldown_seconds_remaining") not in (None, "")
        and int(context.get("cooldown_seconds_remaining") or 0) > 0
    )
    if dedupe["matched_existing"]:
        delivery_decision = {"deliver": False, "suppress_reason": "duplicate"}
        if not missing_slots:
            status = "suppressed"
    elif explicit_cooldown_active:
        delivery_decision = {"deliver": False, "suppress_reason": "cooldown_active"}
        if not missing_slots:
            status = "suppressed"
    else:
        delivery_decision = {"deliver": True, "suppress_reason": None}
    notification_payload = {
        "bubble_text": title,
        "deep_link_tab": "proactive",
        "actions": actions,
    }
    feedback_history = context.get("feedback_history") if isinstance(context.get("feedback_history"), list) else []
    negative_feedback_count = sum(
        1
        for item in feedback_history
        if isinstance(item, dict)
        and str(item.get("feedback") or "").lower() in {"dismissed", "negative", "not_useful", "reject", "rejected"}
    )
    learning_signal = {
        "feedback_history_count": len(feedback_history),
        "negative_feedback_count": negative_feedback_count,
        "cooldown_seconds_remaining": cooldown["seconds_remaining"],
    }
    score_breakdown = context.get("score_breakdown") if isinstance(context.get("score_breakdown"), dict) else {
        "urgency": 0.7 if _is_route_candidate(str(candidate_type or ""), context, request) else 0.45,
        "importance": 0.7 if source_event_ids else 0.4,
        "actionability": 0.8 if actions else 0.3,
        "cooldown_penalty": 1.0 if explicit_cooldown_active else 0.0,
        "negative_feedback_penalty": min(1.0, negative_feedback_count * 0.25),
    }
    candidate_record = {
        "candidate_type": candidate_type,
        "source_event_ids": source_event_ids,
        "scores": score_breakdown,
        "decision": "suppressed" if not delivery_decision["deliver"] else "visible",
        "cooldown_key": cooldown["key"],
        "dedupe_key": dedupe["key"],
        "suggestion_card": suggestion_card,
        "learning_signal": learning_signal,
    }
    writeback_plan = [
        {
            "target": "proactive_candidates",
            "operation": "upsert_candidate",
            "item": candidate_record,
            "confirmation_required": False,
        },
        {
            "target": "proactive_suggestions",
            "operation": "upsert_card",
            "item": suggestion_card,
            "confirmation_required": False,
        },
        {
            "target": "task_trace",
            "operation": "record_cooldown_dedupe",
            "item": {"cooldown": cooldown, "dedupe": dedupe},
            "confirmation_required": False,
        },
    ]
    return _base_result(
        pipeline_id="proactive_suggestion_pipeline",
        status=status,
        required_slots=required_slots,
        resolved_slots=resolved_slots,
        risk={"permission": "draft", "confirmation_required": False, "final_user_confirmation": False},
        execution_guard={
            "permission": "draft",
            "policy": "suggestion_display_allowed_actions_follow_target_pipeline_policy",
            "requires_confirmation": False,
            "final_user_confirmation": False,
        },
        external_effects=[],
        writeback_targets=["proactive_candidates", "proactive_suggestions", "user_feedback", "task_trace"],
        steps=["评分重要性", "检查冷却和去重", "生成建议卡片", "准备实时投递"],
        output={
            "suggestion_card": suggestion_card,
            "cooldown": cooldown,
            "dedupe": dedupe,
            "delivery_decision": delivery_decision,
            "notification_payload": notification_payload,
            "learning_signal": learning_signal,
        },
        writeback_plan=writeback_plan,
        slot_extraction={
            "parser_mode": "module_rules",
            "model_used": False,
            "rule_slots": resolved_slots,
            "model_slots": {},
            "validation_warnings": [],
        },
    )


def run_agenda_pipeline(pipeline_id: str, request: str, context: dict[str, Any]) -> dict[str, Any] | None:
    context = context or {}
    if pipeline_id not in OWNED_PIPELINES:
        return None
    if pipeline_id == "agenda_pipeline":
        return _run_single_agenda_pipeline(request, context)
    if pipeline_id == "task_todo_pipeline":
        return _run_task_todo_pipeline(request, context)
    return _run_proactive_suggestion_pipeline(request, context)
