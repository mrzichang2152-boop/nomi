from __future__ import annotations

import re
from typing import Any


OWNED_PIPELINES = {
    "route_pipeline",
    "ride_pipeline",
    "shopping_pipeline",
    "payment_bill_pipeline",
    "document_file_pipeline",
    "account_login_pipeline",
}


def run_action_pipeline(pipeline_id: str, request: str, context: dict) -> dict | None:
    context = context or {}
    if pipeline_id not in OWNED_PIPELINES:
        return None
    if pipeline_id == "route_pipeline":
        return _route_pipeline(request, context)
    if pipeline_id == "ride_pipeline":
        return _ride_pipeline(request, context)
    if pipeline_id == "shopping_pipeline":
        return _shopping_pipeline(request, context)
    if pipeline_id == "payment_bill_pipeline":
        return _payment_bill_pipeline(request, context)
    if pipeline_id == "document_file_pipeline":
        return _document_file_pipeline(request, context)
    if pipeline_id == "account_login_pipeline":
        return _account_login_pipeline(request, context)
    return None


def _base_result(
    *,
    pipeline_id: str,
    status: str,
    required_slots: list[str],
    resolved_slots: dict[str, Any],
    risk_permission: str,
    confirmation_required: bool,
    external_effects: list[str],
    steps: list[dict[str, str]],
    output: dict[str, Any],
    writeback_targets: list[str] | None = None,
    writeback_plan: list[dict[str, Any]] | None = None,
    provider_calls: list[dict[str, Any]] | None = None,
    provider_call_plan: dict[str, Any] | None = None,
    safety_checks: list[dict[str, str]] | None = None,
    blocked_effects: list[str] | None = None,
    confirmation_card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    missing_slots = _missing_slots(required_slots, resolved_slots)
    result = {
        "pipeline_id": pipeline_id,
        "status": status,
        "required_slots": required_slots,
        "resolved_slots": resolved_slots,
        "missing_slots": missing_slots,
        "risk": {
            "permission": risk_permission,
            "confirmation_required": confirmation_required,
            "final_user_confirmation": confirmation_required,
        },
        "execution_guard": {
            "permission": risk_permission,
            "policy": "requires_final_user_confirmation" if confirmation_required else "allowed_without_confirmation",
        },
        "external_effects": external_effects,
        "writeback_targets": writeback_targets or ["assistant_turns", "task_trace"],
        "steps": steps,
        "output": output,
        "provider_calls": provider_calls or [],
        "provider_call_plan": provider_call_plan or _provider_call_plan("proposed_only"),
        "safety_checks": safety_checks or _default_safety_checks(confirmation_required, external_effects),
        "blocked_effects": blocked_effects or [],
        "writeback_plan": writeback_plan or [],
    }
    if confirmation_card:
        result["confirmation_card"] = confirmation_card
    return result


def _provider_call_plan(
    mode: str,
    *,
    provider: str | None = None,
    action: str | None = None,
    params: dict[str, Any] | None = None,
    external_effect: bool = False,
    allowed_actions: list[str] | None = None,
    blocked_actions: list[str] | None = None,
) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "mode": mode,
        "external_effect": external_effect,
    }
    if provider:
        plan["provider"] = provider
    if action:
        plan["action"] = action
    if params:
        plan["params"] = params
    if allowed_actions:
        plan["allowed_actions"] = allowed_actions
    if blocked_actions:
        plan["blocked_actions"] = blocked_actions
    return plan


def _default_safety_checks(confirmation_required: bool, external_effects: list[str]) -> list[dict[str, str]]:
    checks = [
        {
            "name": "requires_final_user_confirmation" if confirmation_required else "no_confirmation_required",
            "status": "passed",
        }
    ]
    if external_effects:
        checks.append({"name": "external_effects_blocked_until_confirmation", "status": "passed"})
    else:
        checks.append({"name": "no_external_effects", "status": "passed"})
    return checks


def _route_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    destination = _first_text(context, "destination") or _extract_destination(request)
    origin = _first_text(context, "origin", "pickup", "current_location") or "current_location"
    mode = _first_text(context, "mode", "travel_mode") or "transit"
    resolved = _compact_slots({"destination": destination})
    missing = _missing_slots(["destination"], resolved)
    status = "needs_user_input" if missing else "completed_read_only"
    output: dict[str, Any]
    if missing:
        output = {"question": "What destination should I prepare a route for?"}
    else:
        route_request = {
            "origin": origin,
            "destination": destination,
            "mode": mode,
        }
        output = {
            "summary": f"Prepared a read-only route lookup to {destination}.",
            "route_request": route_request,
        }
        provider_result = context.get("provider_result") or context.get("route_result")
        if provider_result:
            output["route_options"] = _normalize_route_options(provider_result, mode)
            provider_call_plan = _provider_call_plan(
                "estimate_only",
                provider=output["route_options"][0]["provider"] if output["route_options"] else "google_maps",
                action="route_lookup",
                params=route_request,
                external_effect=False,
            )
        else:
            output["provider_needed"] = "google_maps"
            output["route_options"] = []
            provider_call_plan = _provider_call_plan(
                "proposed_only",
                provider="google_maps",
                action="route_lookup",
                params=route_request,
                external_effect=False,
            )
    return _base_result(
        pipeline_id="route_pipeline",
        status=status,
        required_slots=["destination"],
        resolved_slots=resolved,
        risk_permission="read_only",
        confirmation_required=False,
        external_effects=[],
        steps=[
            {"name": "resolve_destination", "status": "completed" if destination else "pending"},
            {"name": "prepare_route_request", "status": "completed" if not missing else "pending"},
        ],
        output=output,
        writeback_targets=["route_cache", "assistant_turns", "task_trace"],
        writeback_plan=[
            {"target": "task_trace", "action": "record_route_request"},
            {"target": "route_cache", "operation": "record_route_request", "payload": {**route_request, "route_options": output.get("route_options", [])}},
        ] if not missing else [],
        provider_call_plan=provider_call_plan if not missing else _provider_call_plan("proposed_only", action="route_lookup"),
        safety_checks=[
            {"name": "read_only_route_lookup", "status": "passed" if not missing else "pending"},
            {"name": "no_external_effects", "status": "passed"},
        ],
    )


def _ride_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    pickup = _first_text(context, "pickup", "origin", "current_location") or _extract_pickup(request)
    destination = _first_text(context, "destination") or _extract_destination(request)
    ride_type = _first_text(context, "ride_type") or "standard"
    resolved = _compact_slots({"pickup": pickup, "destination": destination})
    missing = _missing_slots(["pickup", "destination"], resolved)
    if missing:
        output = {
            "question": _missing_question(missing, "ride"),
            "booking_blocked": True,
        }
        status = "needs_user_input"
        writeback_plan: list[dict[str, Any]] = []
    else:
        output = {
            "summary": f"Prepared ride options from {pickup} to {destination}; booking is blocked until confirmation.",
            "ride_options": [
                {
                    "provider": "uber",
                    "ride_type": ride_type,
                    "pickup": pickup,
                    "destination": destination,
                    "status": "estimate_needed",
                }
            ],
            "proposed_provider_calls": [
                {
                    "provider": "uber",
                    "action": "estimate_ride",
                    "params": {"pickup": pickup, "destination": destination, "ride_type": ride_type},
                }
            ],
            "booking_blocked": True,
        }
        status = "confirmation_required"
        writeback_plan = [{"target": "assistant_turns", "action": "show_confirmation_card"}]
    confirmation_card = None if missing else {
        "type": "ride_confirmation",
        "pickup": pickup,
        "destination": destination,
        "options": [{"provider": "uber", "ride_type": ride_type}],
        "confirm_action": "book_ride",
    }
    return _base_result(
        pipeline_id="ride_pipeline",
        status=status,
        required_slots=["pickup", "destination"],
        resolved_slots=resolved,
        risk_permission="payment_or_purchase",
        confirmation_required=True,
        external_effects=["book_ride", "payment"],
        steps=[
            {"name": "resolve_pickup", "status": "completed" if pickup else "pending"},
            {"name": "resolve_destination", "status": "completed" if destination else "pending"},
            {"name": "prepare_ride_options", "status": "completed" if not missing else "pending"},
        ],
        output=output,
        writeback_plan=writeback_plan,
        provider_call_plan=_provider_call_plan(
            "blocked_until_confirmation",
            provider="uber",
            action="book_ride",
            params={"pickup": pickup, "destination": destination, "ride_type": ride_type},
            allowed_actions=["estimate_ride"],
            blocked_actions=["book_ride", "payment"],
        ),
        safety_checks=[
            {"name": "requires_final_user_confirmation", "status": "passed" if not missing else "pending"},
            {"name": "payment_not_sent", "status": "passed"},
            {"name": "ride_not_booked", "status": "passed"},
        ],
        blocked_effects=["book_ride", "payment"],
        confirmation_card=confirmation_card,
    )


def _shopping_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    product_intent = _first_text(context, "product_intent", "product", "query") or _extract_product_intent(request)
    shopping_intent = (_first_text(context, "shopping_intent", "intent") or _classify_shopping_intent(request)).lower()
    resolved = _compact_slots({"product_intent": product_intent})
    missing = _missing_slots(["product_intent"], resolved)
    is_compare = shopping_intent in {"compare", "comparison", "research", "search"}
    status = "needs_user_input" if missing else ("completed_read_only" if is_compare else "confirmation_required")
    confirmation_required = not is_compare or bool(missing)
    risk_permission = "read_only" if is_compare and not missing else "payment_or_purchase"
    if missing:
        output = {"question": "What product should I research or prepare?", "purchase_blocked": True}
        external_effects: list[str] = ["add_to_cart", "purchase"]
        writeback_plan: list[dict[str, Any]] = []
        blocked_effects = ["add_to_cart", "purchase"]
        provider_call_plan = _provider_call_plan("proposed_only", action="shopping_lookup")
        confirmation_card = None
    elif is_compare:
        comparison_criteria = ["price", "reviews", "availability"]
        output = {
            "summary": f"Prepared a read-only shopping comparison for {product_intent}.",
            "comparison_plan": {"product_intent": product_intent, "signals": comparison_criteria},
            "comparison_criteria": comparison_criteria,
            "ranked_products": _ranked_products(context.get("products")),
            "purchase_blocked": True,
        }
        external_effects = []
        blocked_effects = ["add_to_cart", "purchase"]
        provider_call_plan = _provider_call_plan(
            "proposed_only",
            action="compare_products",
            params={"product_intent": product_intent, "criteria": comparison_criteria},
            external_effect=False,
        )
        confirmation_card = None
        writeback_plan = [{"target": "assistant_turns", "action": "show_comparison_plan"}]
    else:
        action = "purchase" if shopping_intent in {"buy", "purchase", "order"} else "add_to_cart"
        output = {
            "summary": f"Prepared a {action} plan for {product_intent}; execution is blocked until confirmation.",
            "proposed_action": {
                "action": action,
                "product_intent": product_intent,
                "quantity": context.get("quantity", 1),
            },
            "purchase_blocked": True,
        }
        external_effects = ["add_to_cart", "purchase"]
        blocked_effects = [action]
        provider_call_plan = _provider_call_plan(
            "blocked_until_confirmation",
            action=action,
            params={"product_intent": product_intent, "quantity": context.get("quantity", 1)},
            blocked_actions=[action],
        )
        confirmation_card = {
            "type": "shopping_confirmation",
            "product_intent": product_intent,
            "quantity": context.get("quantity", 1),
            "confirm_action": action,
        }
        writeback_plan = [{"target": "assistant_turns", "action": "show_confirmation_card"}]
    return _base_result(
        pipeline_id="shopping_pipeline",
        status=status,
        required_slots=["product_intent"],
        resolved_slots=resolved,
        risk_permission=risk_permission,
        confirmation_required=confirmation_required,
        external_effects=external_effects,
        steps=[
            {"name": "resolve_product_intent", "status": "completed" if product_intent else "pending"},
            {"name": "classify_shopping_action", "status": "completed" if not missing else "pending"},
        ],
        output=output,
        writeback_plan=writeback_plan,
        provider_call_plan=provider_call_plan,
        safety_checks=_default_safety_checks(confirmation_required, external_effects),
        blocked_effects=blocked_effects,
        confirmation_card=confirmation_card,
    )


def _payment_bill_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    counterparty = _first_text(context, "counterparty", "recipient", "payee") or _extract_counterparty(request)
    amount_or_bill = _first_text(context, "amount_or_bill", "amount", "bill") or _extract_amount_or_bill(request)
    resolved = _compact_slots({"counterparty": counterparty, "amount_or_bill": amount_or_bill})
    missing = _missing_slots(["counterparty", "amount_or_bill"], resolved)
    if missing:
        status = "needs_user_input"
        output = {
            "question": "Who should be paid, and what amount or bill should I prepare?",
            "risk_summary": _payment_risk_summary(),
            "transfer_blocked": True,
        }
        writeback_plan: list[dict[str, Any]] = []
        confirmation_card = None
    else:
        status = "confirmation_required"
        payment_method = _first_text(context, "payment_method") or "user_selects_method"
        confirmation_card = {
            "type": "payment_confirmation",
            "counterparty": counterparty,
            "amount_or_bill": amount_or_bill,
            "payment_method": payment_method,
            "confirm_action": "transfer_funds",
        }
        output = {
            "summary": f"Prepared payment details for {counterparty}; transfer is blocked until confirmation.",
            "payment_plan": {
                "counterparty": counterparty,
                "amount_or_bill": amount_or_bill,
                "payment_method": payment_method,
            },
            "risk_summary": _payment_risk_summary(),
            "payment_confirmation_card": confirmation_card,
            "transfer_blocked": True,
        }
        writeback_plan = [{"target": "assistant_turns", "action": "show_confirmation_card"}]
    return _base_result(
        pipeline_id="payment_bill_pipeline",
        status=status,
        required_slots=["counterparty", "amount_or_bill"],
        resolved_slots=resolved,
        risk_permission="payment_or_purchase",
        confirmation_required=True,
        external_effects=["payment", "transfer"],
        steps=[
            {"name": "resolve_counterparty", "status": "completed" if counterparty else "pending"},
            {"name": "resolve_amount_or_bill", "status": "completed" if amount_or_bill else "pending"},
            {"name": "prepare_payment_confirmation", "status": "completed" if not missing else "pending"},
        ],
        output=output,
        writeback_plan=writeback_plan,
        provider_call_plan=_provider_call_plan(
            "blocked_until_confirmation",
            action="transfer_funds",
            params={"counterparty": counterparty, "amount_or_bill": amount_or_bill},
            blocked_actions=["payment", "transfer"],
        ),
        safety_checks=[
            {"name": "requires_final_user_confirmation", "status": "passed" if not missing else "pending"},
            {"name": "transfer_not_sent", "status": "passed"},
        ],
        blocked_effects=["payment", "transfer"],
        confirmation_card=confirmation_card,
    )


def _document_file_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    file_or_query = _first_text(context, "file_or_query", "file", "query", "document") or _extract_file_or_query(request)
    document_intent = (_first_text(context, "document_intent", "intent") or _classify_document_intent(request)).lower()
    resolved = _compact_slots({"file_or_query": file_or_query, "document_intent": document_intent})
    missing = _missing_slots(["file_or_query", "document_intent"], resolved)
    is_read_only = document_intent in {"read", "summarize", "summary", "find", "search"}
    status = "needs_user_input" if missing else ("completed_read_only" if is_read_only else "confirmation_required")
    confirmation_required = not is_read_only or bool(missing)
    risk_permission = "read_only" if is_read_only and not missing else "external_write"
    external_effects = [] if is_read_only and not missing else ["write_document", "share_file"]
    if missing:
        output = {
            "question": _missing_question(missing, "document"),
            "write_blocked": True,
        }
        writeback_plan: list[dict[str, Any]] = []
        blocked_effects = ["write_document", "share_file"]
        provider_call_plan = _provider_call_plan("blocked_until_confirmation", action="document_write_or_share")
        confirmation_card = None
    else:
        action = "summarize" if document_intent == "summary" else document_intent
        effect = "share_file" if action == "share" else "write_document"
        confirmation_card = None if is_read_only else {
            "type": "document_confirmation",
            "action": action,
            "file_or_query": file_or_query,
            "recipient": _first_text(context, "recipient"),
            "confirm_action": effect,
        }
        output = {
            "summary": f"Prepared document action {action} for {file_or_query}.",
            "document_plan": {
                "action": action,
                "file_or_query": file_or_query,
                "recipient": _first_text(context, "recipient"),
            },
            "document_result": {
                "action": action,
                "file_or_query": file_or_query,
                "read_only": True,
            } if is_read_only else None,
            "edit_or_share_confirmation_card": confirmation_card,
            "write_blocked": not is_read_only,
        }
        if output["document_result"] is None:
            output.pop("document_result")
        if output["edit_or_share_confirmation_card"] is None:
            output.pop("edit_or_share_confirmation_card")
        blocked_effects = [] if is_read_only else [effect]
        provider_call_plan = _provider_call_plan(
            "proposed_only" if is_read_only else "blocked_until_confirmation",
            action=action,
            params={"file_or_query": file_or_query, "recipient": _first_text(context, "recipient")},
            external_effect=not is_read_only,
            blocked_actions=blocked_effects,
        )
        writeback_plan = [
            {
                "target": "assistant_turns",
                "action": "show_confirmation_card" if not is_read_only else "show_read_only_result",
            }
        ]
    return _base_result(
        pipeline_id="document_file_pipeline",
        status=status,
        required_slots=["file_or_query", "document_intent"],
        resolved_slots=resolved,
        risk_permission=risk_permission,
        confirmation_required=confirmation_required,
        external_effects=external_effects,
        steps=[
            {"name": "resolve_file_or_query", "status": "completed" if file_or_query else "pending"},
            {"name": "resolve_document_intent", "status": "completed" if document_intent else "pending"},
            {"name": "prepare_document_action", "status": "completed" if not missing else "pending"},
        ],
        output=output,
        writeback_plan=writeback_plan,
        provider_call_plan=provider_call_plan,
        safety_checks=[
            {"name": "read_only_document_access", "status": "passed" if is_read_only and not missing else "pending"},
            {"name": "external_write_blocked", "status": "passed" if not is_read_only or missing else "not_applicable"},
        ],
        blocked_effects=blocked_effects,
        confirmation_card=confirmation_card,
    )


def _account_login_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    account_provider = _first_text(context, "account_provider", "provider", "account") or _extract_account_provider(request)
    resolved = _compact_slots({"account_provider": account_provider})
    missing = _missing_slots(["account_provider"], resolved)
    login_url = _first_text(context, "login_url") or _default_login_url(account_provider)
    connection_status = _first_text(context, "connection_status", "collector_health_status", "health_status") or "not_connected"
    connection_reason = _first_text(context, "connection_reason", "health_reason") or "no_external_login_attempted"
    status = "needs_user_input" if missing else "draft_ready"
    output: dict[str, Any]
    if missing:
        output = {
            "question": "Which account provider should I prepare a login page for?",
            "credential_handling": "user_enters_credentials_directly",
            "connection_health": {
                "status": connection_status,
                "reason": connection_reason,
            },
        }
        writeback_plan: list[dict[str, Any]] = []
    else:
        controlled_browser_plan = {
            "action": "open_browser",
            "account_provider": account_provider,
            "login_url": login_url,
            "credential_entry": "user_only",
        }
        output = {
            "summary": f"Prepared browser login for {account_provider}; credentials stay with the user.",
            "login_plan": {
                "action": "open_browser",
                "account_provider": account_provider,
                "login_url": login_url,
            },
            "controlled_browser_plan": controlled_browser_plan,
            "connection_health": {
                "status": connection_status,
                "reason": connection_reason,
            },
            "connection_readiness": {
                "collector_ready": connection_status in {"healthy", "connected", "ready"},
                "status_source": "context_or_default",
            },
            "credential_handling": "user_enters_credentials_directly",
        }
        writeback_plan = [
            {"target": "assistant_turns", "action": "show_login_open_plan"},
            {
                "target": "account_connections",
                "operation": "upsert_connection_plan",
                "payload": {
                    "account_provider": account_provider,
                    "status": connection_status,
                    "login_url": login_url,
                    "credential_handling": "user_enters_credentials_directly",
                    "reason": connection_reason,
                },
            },
        ]
    return _base_result(
        pipeline_id="account_login_pipeline",
        status=status,
        required_slots=["account_provider"],
        resolved_slots=resolved,
        risk_permission="account_access",
        confirmation_required=False,
        external_effects=["open_browser"] if not missing else [],
        steps=[
            {"name": "resolve_account_provider", "status": "completed" if account_provider else "pending"},
            {"name": "prepare_login_url", "status": "completed" if not missing else "pending"},
        ],
        output=output,
        writeback_targets=["assistant_turns", "account_connections", "task_trace"],
        writeback_plan=writeback_plan,
        provider_call_plan=_provider_call_plan(
            "proposed_only",
            action="open_controlled_browser",
            params={"account_provider": account_provider, "login_url": login_url},
            external_effect=False,
        ),
        safety_checks=[
            {"name": "credentials_user_entered_only", "status": "passed"},
            {"name": "credentials_not_read_or_sent_by_system", "status": "passed"},
        ],
        blocked_effects=["submit_credentials", "read_credentials"],
    )


def _missing_slots(required_slots: list[str], resolved_slots: dict[str, Any]) -> list[str]:
    return [slot for slot in required_slots if not _has_value(resolved_slots.get(slot))]


def _normalize_route_options(provider_result: Any, mode: str) -> list[dict[str, Any]]:
    routes = provider_result
    if isinstance(provider_result, dict):
        routes = provider_result.get("routes") or provider_result.get("route_options") or [provider_result]
    if not isinstance(routes, list):
        routes = [routes]

    options: list[dict[str, Any]] = []
    for route in routes:
        if not isinstance(route, dict):
            continue
        provider = route.get("provider")
        if provider is None and isinstance(provider_result, dict):
            provider = provider_result.get("provider")
        eta_minutes = _extract_eta_minutes(route)
        options.append(
            {
                "eta_minutes": eta_minutes,
                "distance_text": _extract_distance_text(route),
                "provider": str(provider or "google_maps"),
                "mode": str(route.get("mode") or mode),
            }
        )
    return options


def _extract_eta_minutes(route: dict[str, Any]) -> int | None:
    for key in ("eta_minutes", "duration_minutes", "minutes"):
        if route.get(key) is not None:
            return int(float(route[key]))
    duration = route.get("duration")
    if isinstance(duration, dict):
        if duration.get("value") is not None:
            return max(1, round(float(duration["value"]) / 60))
        if duration.get("text"):
            return _minutes_from_text(str(duration["text"]))
    if isinstance(duration, str):
        return _minutes_from_text(duration)
    return None


def _extract_distance_text(route: dict[str, Any]) -> str | None:
    distance = route.get("distance") or route.get("distance_text")
    if isinstance(distance, dict):
        return str(distance.get("text")) if distance.get("text") is not None else None
    return str(distance) if distance is not None else None


def _minutes_from_text(value: str) -> int | None:
    match = re.search(r"(\d+(?:\.\d+)?)", value)
    return int(round(float(match.group(1)))) if match else None


def _ranked_products(products: Any) -> list[dict[str, Any]]:
    if not isinstance(products, list):
        return []
    ranked = []
    for index, product in enumerate(products, start=1):
        if isinstance(product, dict):
            ranked.append({"rank": index, **product})
        else:
            ranked.append({"rank": index, "name": str(product)})
    return ranked


def _payment_risk_summary() -> dict[str, Any]:
    return {
        "level": "high",
        "reasons": ["moves_money", "irreversible_or_sensitive_external_effect"],
    }


def _compact_slots(slots: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in slots.items() if _has_value(value)}


def _has_value(value: Any) -> bool:
    return value is not None and value != "" and value != []


def _first_text(context: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = context.get(key)
        if _has_value(value):
            return str(value).strip()
    return None


def _extract_destination(request: str) -> str | None:
    for pattern in (r"(?:去|到|前往)([^，。,.!?？]+?)(?:要多久|怎么走|路线|打车|$)", r"route to ([^,.!?]+)"):
        match = re.search(pattern, request, flags=re.IGNORECASE)
        if match:
            return _clean_phrase(match.group(1))
    return None


def _extract_pickup(request: str) -> str | None:
    match = re.search(r"(?:从|自)([^，。,.!?？]+?)(?:去|到|前往)", request)
    return _clean_phrase(match.group(1)) if match else None


def _extract_product_intent(request: str) -> str | None:
    cleaned = re.sub(r"(比较一下|比较|买|购买|下单|加到购物车|加入购物车|帮我|please|buy|purchase|order|add to cart)", "", request, flags=re.IGNORECASE)
    return _clean_phrase(cleaned)


def _classify_shopping_intent(request: str) -> str:
    lowered = request.lower()
    if any(token in lowered for token in ("比较", "compare", "对比", "research", "搜索", "search")):
        return "compare"
    if any(token in lowered for token in ("买", "购买", "下单", "buy", "purchase", "order")):
        return "purchase"
    if any(token in lowered for token in ("购物车", "cart")):
        return "add_to_cart"
    return "compare"


def _extract_counterparty(request: str) -> str | None:
    match = re.search(r"(?:付给|转给|给)([^\d，。,.!?？]+?)(?:\s*\d|$)", request)
    return _clean_phrase(match.group(1)) if match else None


def _extract_amount_or_bill(request: str) -> str | None:
    match = re.search(r"(\d+(?:\.\d+)?\s*(?:元|块|rmb|usd|dollars?)(?:[^，。,.!?？]*)?)", request, flags=re.IGNORECASE)
    return _clean_phrase(match.group(1)) if match else None


def _extract_file_or_query(request: str) -> str | None:
    match = re.search(r"([^，。,.!?？\s]+\.(?:docx?|xlsx?|pdf|txt|md|csv))", request, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    cleaned = re.sub(r"(总结一下|总结|读取|打开|查找|写|分享|共享|帮我|please|summarize|read|find|write|share)", "", request, flags=re.IGNORECASE)
    return _clean_phrase(cleaned)


def _classify_document_intent(request: str) -> str:
    lowered = request.lower()
    if any(token in lowered for token in ("分享", "共享", "share")):
        return "share"
    if any(token in lowered for token in ("写", "编辑", "修改", "write", "edit", "update")):
        return "write"
    if any(token in lowered for token in ("总结", "summarize", "summary")):
        return "summarize"
    if any(token in lowered for token in ("找", "查找", "find", "search")):
        return "find"
    return "read"


def _extract_account_provider(request: str) -> str | None:
    known = {
        "google": "Google",
        "gmail": "Google",
        "github": "GitHub",
        "notion": "Notion",
        "slack": "Slack",
        "microsoft": "Microsoft",
        "outlook": "Microsoft",
        "apple": "Apple",
    }
    lowered = request.lower()
    for token, provider in known.items():
        if token in lowered:
            return provider
    match = re.search(r"(?:打开|登录|login to|log in to)\s*([A-Za-z][A-Za-z0-9_-]+)", request, flags=re.IGNORECASE)
    return _clean_phrase(match.group(1)) if match else None


def _default_login_url(account_provider: str | None) -> str | None:
    if not account_provider:
        return None
    mapping = {
        "google": "https://accounts.google.com/",
        "github": "https://github.com/login",
        "notion": "https://www.notion.so/login",
        "slack": "https://slack.com/signin",
        "microsoft": "https://login.microsoftonline.com/",
        "apple": "https://appleid.apple.com/",
    }
    return mapping.get(account_provider.lower(), f"https://www.google.com/search?q={account_provider}+login")


def _missing_question(missing: list[str], subject: str) -> str:
    fields = " and ".join(missing)
    return f"Please provide {fields} for this {subject} request."


def _clean_phrase(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip(" \t\n\r，。,.!?？")
    return cleaned or None
