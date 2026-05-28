from __future__ import annotations

import re
from typing import Any


OWNED_PIPELINES = {
    "personal_search_pipeline",
    "chat_response_pipeline",
    "reply_pipeline",
    "email_pipeline",
}

PIPELINE_STEPS = {
    "personal_search_pipeline": ["retrieve_memory_hits", "filter_scope", "rank_evidence", "compose_answer"],
    "chat_response_pipeline": ["store_user_turn", "build_context_snapshot", "prepare_stream", "plan_writeback"],
    "reply_pipeline": ["resolve_target", "resolve_intent", "draft_reply", "await_confirmation"],
    "email_pipeline": ["resolve_mailbox", "resolve_intent", "prepare_email_output", "await_confirmation"],
}


def run_communication_pipeline(pipeline_id: str, request: str, context: dict[str, Any]) -> dict[str, Any] | None:
    if pipeline_id not in OWNED_PIPELINES:
        return None
    context = context or {}
    if pipeline_id == "personal_search_pipeline":
        return _personal_search(request, context)
    if pipeline_id == "chat_response_pipeline":
        return _chat_response(request, context)
    if pipeline_id == "reply_pipeline":
        return _reply(request, context)
    if pipeline_id == "email_pipeline":
        return _email(request, context)
    return None


def _base_result(
    *,
    pipeline_id: str,
    status: str,
    required_slots: list[str],
    resolved_slots: dict[str, Any],
    missing_slots: list[str],
    permission: str,
    confirmation_required: bool,
    final_user_confirmation: bool,
    external_effects: list[str],
    writeback_targets: list[str],
    output: dict[str, Any],
    writeback_plan: list[dict[str, Any]] | None = None,
    provider_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    blocked = status in {"needs_user_input", "blocked", "failed"}
    guard_policy = "requires_final_user_confirmation" if confirmation_required else "allowed_read_only"
    return {
        "pipeline_id": pipeline_id,
        "status": status,
        "required_slots": required_slots,
        "resolved_slots": resolved_slots,
        "missing_slots": missing_slots,
        "risk": {
            "permission": permission,
            "confirmation_required": confirmation_required,
            "final_user_confirmation": final_user_confirmation,
        },
        "execution_guard": {"permission": permission, "policy": guard_policy},
        "external_effects": external_effects,
        "writeback_targets": writeback_targets,
        "steps": [
            {"name": step, "status": "pending" if blocked else "completed"}
            for step in PIPELINE_STEPS[pipeline_id]
        ],
        "output": output,
        "provider_calls": provider_calls or [],
        "writeback_plan": writeback_plan or [],
    }


def _missing(required_slots: list[str], resolved_slots: dict[str, Any]) -> list[str]:
    return [
        slot
        for slot in required_slots
        if resolved_slots.get(slot) is None or resolved_slots.get(slot) == "" or resolved_slots.get(slot) == []
    ]


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _personal_search(request: str, context: dict[str, Any]) -> dict[str, Any]:
    required_slots = ["query"]
    query = _text(context.get("query")) or request.strip()
    resolved_slots = {"query": query} if query else {}
    missing_slots = _missing(required_slots, resolved_slots)
    current_scope = _text(context.get("current_scope") or context.get("scope"))
    allowed_scopes = {"global", "user", "contact", "conversation"}
    if current_scope:
        allowed_scopes.add(current_scope)

    scoped_hits = []
    excluded_hits = []
    private_scopes = set()
    for hit in context.get("memory_hits") or []:
        if not isinstance(hit, dict):
            continue
        scope = _text(hit.get("scope"))
        if scope in allowed_scopes:
            scoped_hits.append(hit)
        else:
            private_scopes.add(scope)
            excluded_hits.append({**hit, "_exclude_reason": "outside_allowed_scope"})

    ambiguous_private_scopes = not current_scope and len(private_scopes) > 1
    if ambiguous_private_scopes and "search_scope" not in missing_slots:
        missing_slots.append("search_scope")
        excluded_hits = [
            {**hit, "_exclude_reason": "requires_explicit_search_scope"}
            for hit in context.get("memory_hits") or []
            if isinstance(hit, dict) and _text(hit.get("scope")) not in allowed_scopes
        ]
        scoped_hits = [
            hit
            for hit in scoped_hits
            if _text(hit.get("scope")) in {"global", "user", "contact", "conversation"}
        ]

    evidence_ranking = [] if ambiguous_private_scopes else _rank_evidence(scoped_hits)
    rank_by_id = {item["id"]: item for item in evidence_ranking}
    scoped_hits.sort(
        key=lambda hit: rank_by_id.get(_text(hit.get("id")), {}).get("final_rank", 999999)
        if evidence_ranking
        else -float(hit.get("score") or 0)
    )

    citations = [
        {
            "id": _text(hit.get("id")),
            "scope": _text(hit.get("scope")),
            "score": hit.get("score", 0),
            "content": _text(hit.get("content")),
        }
        for hit in scoped_hits
    ]
    scope_filter_report = {
        "allowed_count": len(scoped_hits),
        "excluded_count": len(excluded_hits),
        "allowed": [
            {"id": _text(hit.get("id")), "scope": _text(hit.get("scope")), "reason": "allowed_scope"}
            for hit in scoped_hits
        ],
        "excluded": [
            {
                "id": _text(hit.get("id")),
                "scope": _text(hit.get("scope")),
                "reason": _text(hit.get("_exclude_reason")) or "outside_allowed_scope",
            }
            for hit in excluded_hits
        ],
    }
    if missing_slots:
        status = "needs_user_input"
        if "search_scope" in missing_slots:
            answer_summary = "Which scope should I search before using private memory hits?"
        else:
            answer_summary = "What should I search your memory for?"
    elif citations:
        status = "completed_read_only"
        answer_summary = (
            f"Found {len(citations)} scoped memory citation(s): "
            + " ".join(citation["content"] for citation in citations[:3] if citation["content"])
        )
    else:
        status = "completed_read_only"
        answer_summary = "No reliable evidence was found in the allowed memory scope."

    output = {
        "answer_summary": answer_summary,
        "citations": citations,
        "query": query,
        "evidence_ranking": evidence_ranking,
        "scope_filter_report": scope_filter_report,
    }
    if missing_slots:
        output["question"] = answer_summary
    if not citations and not missing_slots:
        output["no_evidence_reason"] = "no_hits_in_allowed_scope"

    return _base_result(
        pipeline_id="personal_search_pipeline",
        status=status,
        required_slots=required_slots,
        resolved_slots=resolved_slots,
        missing_slots=missing_slots,
        permission="read_only",
        confirmation_required=False,
        final_user_confirmation=False,
        external_effects=[],
        writeback_targets=["assistant_turns", "search_audit", "task_trace"],
        output=output,
        writeback_plan=[
            {
                "target": "search_audit",
                "operation": "record_personal_search",
                "payload": {
                    "pipeline_id": "personal_search_pipeline",
                    "query": query,
                    "scope": current_scope or "default_allowed_scope",
                    "result_count": len(citations),
                    "citation_ids": [citation["id"] for citation in citations],
                    "excluded_count": len(excluded_hits),
                    "missing_slots": missing_slots,
                },
            }
        ],
    )


def _chat_response(request: str, context: dict[str, Any]) -> dict[str, Any]:
    required_slots = ["conversation_id", "message"]
    conversation_id = _text(context.get("conversation_id"))
    message = _text(context.get("message")) or request.strip()
    resolved_slots = {}
    if conversation_id:
        resolved_slots["conversation_id"] = conversation_id
    if message:
        resolved_slots["message"] = message
    missing_slots = _missing(required_slots, resolved_slots)
    status = "needs_user_input" if missing_slots else "completed_read_only"
    memory_hits = [hit for hit in context.get("memory_hits") or [] if isinstance(hit, dict)]
    evidence_ids = [_text(hit.get("id")) for hit in memory_hits if _text(hit.get("id"))]
    snapshot_payload = {
        "conversation_id": conversation_id,
        "message": message,
        "context_pack_id": context.get("context_pack_id"),
        "evidence_ids": evidence_ids,
    }
    output = {
        "stream_plan": {
            "mode": "assistant_response",
            "chunk_mode": _text(context.get("chunk_mode")) or "token",
            "conversation_id": conversation_id,
            "message": message,
            "context_pack_id": context.get("context_pack_id"),
            "trace_id": _text(context.get("trace_id")) or f"trace:{conversation_id or 'pending'}",
            "writeback_after_stream": True,
            "provider_call": "proposed_model_stream",
        },
        "context_snapshot": snapshot_payload,
    }
    if context.get("action_cards"):
        output["action_cards"] = context.get("action_cards")
    if context.get("action_cards") or context.get("action_intent"):
        action_intent = context.get("action_intent") if isinstance(context.get("action_intent"), dict) else {}
        output["action_handoff"] = {
            "target_pipeline": _text(action_intent.get("target_pipeline")) or _infer_action_pipeline(context),
            "requires_user_click": True,
        }

    return _base_result(
        pipeline_id="chat_response_pipeline",
        status=status,
        required_slots=required_slots,
        resolved_slots=resolved_slots,
        missing_slots=missing_slots,
        permission="read_only",
        confirmation_required=False,
        final_user_confirmation=False,
        external_effects=[],
        writeback_targets=["assistant_turns", "context_snapshots", "task_trace"],
        output=output,
        writeback_plan=[{"target": "context_snapshots", "operation": "upsert", "payload": snapshot_payload}],
    )


def _reply(request: str, context: dict[str, Any]) -> dict[str, Any]:
    required_slots = ["recipient", "channel", "message_intent"]
    active_scope = context.get("active_source_scope") if isinstance(context.get("active_source_scope"), dict) else {}
    recipient = _text(context.get("recipient")) or _infer_recipient(request)
    channel = _text(context.get("channel")) or _text(active_scope.get("source")) or _infer_channel(request)
    message_intent = _text(context.get("message_intent")) or _infer_reply_intent(request)
    resolved_slots = {}
    if recipient:
        resolved_slots["recipient"] = recipient
    if channel:
        resolved_slots["channel"] = channel
    if message_intent:
        resolved_slots["message_intent"] = message_intent
    missing_slots = _missing(required_slots, resolved_slots)
    target = {"recipient": recipient, "channel": channel}
    draft = _compose_reply_draft(message_intent, context)
    leakage_review = _review_leakage(draft, message_intent, context)
    status = "needs_user_input" if missing_slots else ("blocked" if leakage_review["status"] == "blocked" else "draft_ready")
    question = "Please provide " + ", ".join(missing_slots) + " before I prepare the reply."
    confirmation_card = {
        "recipient": recipient,
        "channel": channel,
        "draft": draft if message_intent else "",
        "risk_summary": "Blocked because the draft includes disallowed context."
        if status == "blocked"
        else "Final sending requires explicit confirmation.",
        "actions": ["blocked"] if status == "blocked" else ["confirm_send", "edit_draft", "cancel"],
    }

    return _base_result(
        pipeline_id="reply_pipeline",
        status=status,
        required_slots=required_slots,
        resolved_slots=resolved_slots,
        missing_slots=missing_slots,
        permission="external_message",
        confirmation_required=True,
        final_user_confirmation=True,
        external_effects=[] if status == "blocked" else ["send_message"],
        writeback_targets=["assistant_turns", "task_trace", "memory_items"],
        output={
            "draft": draft if message_intent else "",
            "target": target,
            "question": question if missing_slots else "",
            "note": "Draft only. No message was sent.",
            "leakage_review": leakage_review,
            "confirmation_card": confirmation_card,
            "send_message": {
                "status": "blocked" if status == "blocked" else "proposed_only",
                "requires_user_confirmation": status != "blocked",
            },
        },
    )


def _email(request: str, context: dict[str, Any]) -> dict[str, Any]:
    required_slots = ["mailbox", "email_intent"]
    mailbox = _text(context.get("mailbox")) or _infer_mailbox(request)
    email_intent = (_text(context.get("email_intent")) or _infer_email_intent(request)).lower()
    resolved_slots = {}
    if mailbox:
        resolved_slots["mailbox"] = mailbox
    if email_intent:
        resolved_slots["email_intent"] = email_intent
    missing_slots = _missing(required_slots, resolved_slots)

    is_summary = email_intent in {"summarize", "read"}
    status = "needs_user_input" if missing_slots else ("completed_read_only" if is_summary else "draft_ready")
    permission = "read_only" if is_summary else "external_message"
    external_effects = [] if is_summary else _email_external_effects(email_intent)
    output = _email_output(request, context, mailbox, email_intent, missing_slots)

    return _base_result(
        pipeline_id="email_pipeline",
        status=status,
        required_slots=required_slots,
        resolved_slots=resolved_slots,
        missing_slots=missing_slots,
        permission=permission,
        confirmation_required=not is_summary,
        final_user_confirmation=not is_summary,
        external_effects=external_effects,
        writeback_targets=["assistant_turns", "agenda_items", "task_trace", "memory_items"],
        output=output,
    )


def _infer_recipient(request: str) -> str:
    patterns = [
        r"\b(?:to|for)\s+([A-Z][\w.-]*)",
        r"\b回复\s*([\w.-]+)",
        r"\b给\s*([\w.-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, request)
        if match:
            return match.group(1).strip(" ,.:;")
    return ""


def _infer_channel(request: str) -> str:
    lower = request.lower()
    channels = ["whatsapp", "slack", "gmail", "email", "sms", "wechat"]
    for channel in channels:
        if channel in lower:
            return "email" if channel == "gmail" else channel
    return ""


def _infer_reply_intent(request: str) -> str:
    patterns = [
        r"\bthat\s+(.+)$",
        r"\bsaying\s+(.+)$",
        r"\bsay\s+(.+)$",
        r"说\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, request, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _compose_reply_draft(message_intent: str, context: dict[str, Any]) -> str:
    if not message_intent:
        return ""
    tone = _text(context.get("tone")).lower()
    if tone == "warm":
        return f"Hi, {message_intent}."
    return message_intent


def _infer_mailbox(request: str) -> str:
    lower = request.lower()
    if "gmail" in lower:
        return "gmail"
    if "outlook" in lower:
        return "outlook"
    if "inbox" in lower:
        return "inbox"
    return ""


def _infer_email_intent(request: str) -> str:
    lower = request.lower()
    if "summarize" in lower or "summary" in lower:
        return "summarize"
    if "read" in lower:
        return "read"
    if "archive" in lower:
        return "archive"
    if "label" in lower or "tag" in lower:
        return "label"
    if "send" in lower:
        return "send"
    if "draft" in lower or "reply" in lower:
        return "draft"
    return ""


def _email_external_effects(email_intent: str) -> list[str]:
    if email_intent in {"draft", "send"}:
        return ["send_email"]
    if email_intent == "archive":
        return ["archive_email"]
    if email_intent == "label":
        return ["label_email"]
    return ["send_email", "archive_email", "label_email"]


def _email_output(
    request: str,
    context: dict[str, Any],
    mailbox: str,
    email_intent: str,
    missing_slots: list[str],
) -> dict[str, Any]:
    if missing_slots:
        return {"question": "Please provide " + ", ".join(missing_slots) + " for the email task."}

    emails = [email for email in context.get("emails") or [] if isinstance(email, dict)]
    internal_candidates = _email_internal_candidates(context)
    if email_intent in {"summarize", "read"}:
        task_candidates = [
            {
                "source_email_id": _text(email.get("id")),
                "title": _text(email.get("subject")) or "Email follow-up",
                "reason": _text(email.get("snippet")),
            }
            for email in emails
            if "please" in _text(email.get("snippet")).lower() or "by " in _text(email.get("snippet")).lower()
        ]
        subjects = ", ".join(_text(email.get("subject")) for email in emails if _text(email.get("subject")))
        return {
            "summary": f"Summarized {len(emails)} email(s) from {mailbox}." + (f" Subjects: {subjects}." if subjects else ""),
            "task_candidates": task_candidates,
            "internal_candidates": internal_candidates,
            "read_model": {
                "mailbox": mailbox,
                "intent": email_intent,
                "email_count": len(emails),
                "subjects": [_text(email.get("subject")) for email in emails if _text(email.get("subject"))],
            },
        }

    if email_intent in {"draft", "send"}:
        draft = _text(context.get("draft")) or f"Draft prepared for {mailbox}: {request.strip()}"
        return {
            "draft": draft,
            "internal_candidates": internal_candidates,
            "confirmation_required": True,
            "confirmation_card": _email_confirmation_card(mailbox, email_intent, draft=draft),
            "provider_call_plan": _email_provider_call_plan(mailbox, email_intent, context),
            "note": "Draft only. No email was sent.",
        }

    action_plan = {
        "mailbox": mailbox,
        "intent": email_intent,
        "email_ids": context.get("email_ids") or [_text(email.get("id")) for email in emails if _text(email.get("id"))],
        "label": context.get("label"),
        "confirmation_required": True,
        "note": "Plan only. No archive or label action was performed.",
    }
    return {
        "action_plan": action_plan,
        "internal_candidates": internal_candidates,
        "confirmation_card": _email_confirmation_card(mailbox, email_intent, action_plan=action_plan),
        "provider_call_plan": _email_provider_call_plan(mailbox, email_intent, context),
    }


def _rank_evidence(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored_hits = [hit for hit in hits if _text(hit.get("id"))]
    recency_sorted = sorted(
        scored_hits,
        key=lambda hit: (_recency_value(hit), -float(hit.get("score") or 0), _text(hit.get("id"))),
    )
    recency_rank_by_id = {_text(hit.get("id")): index + 1 for index, hit in enumerate(recency_sorted)}
    final_sorted = sorted(
        scored_hits,
        key=lambda hit: (recency_rank_by_id[_text(hit.get("id"))], -float(hit.get("score") or 0)),
    )
    return [
        {
            "id": _text(hit.get("id")),
            "scope": _text(hit.get("scope")),
            "score": hit.get("score", 0),
            "recency_rank": recency_rank_by_id[_text(hit.get("id"))],
            "final_rank": index + 1,
        }
        for index, hit in enumerate(final_sorted)
    ]


def _recency_value(hit: dict[str, Any]) -> float:
    value = hit.get("recency", hit.get("recency_rank", hit.get("age")))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 999999.0


def _infer_action_pipeline(context: dict[str, Any]) -> str:
    action_intent = context.get("action_intent")
    if isinstance(action_intent, str) and _text(action_intent):
        action_intent_lower = action_intent.lower()
        if any(token in action_intent_lower for token in ("ride", "uber", "打车", "叫车")):
            return "ride_pipeline"
        if any(token in action_intent_lower for token in ("route", "map", "路线", "导航")):
            return "route_pipeline"
    cards = context.get("action_cards") if isinstance(context.get("action_cards"), list) else []
    first_card = cards[0] if cards and isinstance(cards[0], dict) else {}
    if _text(first_card.get("target_pipeline")):
        return _text(first_card.get("target_pipeline"))
    card_type = _text(first_card.get("type"))
    if card_type in {"reply", "send_message"}:
        return "reply_pipeline"
    if card_type in {"email", "mail"}:
        return "email_pipeline"
    return "reply_pipeline"


def _review_leakage(draft: str, message_intent: str, context: dict[str, Any]) -> dict[str, Any]:
    terms = []
    for key in ("leakage_terms", "disallowed_context"):
        value = context.get(key)
        if isinstance(value, list):
            terms.extend(_text(item) for item in value if _text(item))
        elif _text(value):
            terms.append(_text(value))
    haystack = f"{draft}\n{message_intent}".lower()
    matched_terms = [term for term in terms if term.lower() in haystack]
    return {
        "status": "blocked" if matched_terms else "passed",
        "matched_terms": matched_terms,
        "reviewed_terms_count": len(terms),
    }


def _email_internal_candidates(context: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    for candidate in context.get("candidates") or []:
        if isinstance(candidate, dict):
            candidates.append({**candidate, "source": candidate.get("source", "context.candidates")})

    body = _text(context.get("email_body"))
    lower = body.lower()
    rules = [
        ("agenda", ("agenda",)),
        ("todo", ("todo", "to-do", "please", "by ")),
        ("payment", ("payment", "invoice", "pay ", "due")),
        ("reply", ("reply", "respond", "get back")),
    ]
    for candidate_type, keywords in rules:
        if any(keyword in lower for keyword in keywords):
            candidates.append(
                {
                    "type": candidate_type,
                    "title": _candidate_title(candidate_type),
                    "source": "email_body",
                    "evidence": body[:160],
                }
            )
    return candidates


def _candidate_title(candidate_type: str) -> str:
    titles = {
        "agenda": "Agenda item candidate",
        "todo": "Todo candidate",
        "payment": "Payment candidate",
        "reply": "Reply candidate",
    }
    return titles.get(candidate_type, "Internal candidate")


def _email_confirmation_card(
    mailbox: str,
    email_intent: str,
    *,
    draft: str = "",
    action_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "mailbox": mailbox,
        "intent": email_intent,
        "draft": draft,
        "action_plan": action_plan or {},
        "risk_summary": "External email action is proposed only and requires final confirmation.",
        "actions": ["confirm", "edit", "cancel"],
    }


def _email_provider_call_plan(mailbox: str, email_intent: str, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "proposed_only",
        "provider": mailbox.split(":", 1)[0] if mailbox else "",
        "intent": email_intent,
        "email_ids": context.get("email_ids") or [],
    }
