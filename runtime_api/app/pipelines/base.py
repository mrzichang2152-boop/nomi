from __future__ import annotations

from typing import Any


PERMISSION_POLICIES = {
    "read_only": {
        "permission": "read_only",
        "policy": "allowed_after_login",
        "requires_confirmation": False,
        "final_user_confirmation": False,
    },
    "draft": {
        "permission": "draft",
        "policy": "allowed_to_prepare_only",
        "requires_confirmation": False,
        "final_user_confirmation": False,
    },
    "write": {
        "permission": "write",
        "policy": "requires_explicit_confirmation",
        "requires_confirmation": True,
        "final_user_confirmation": False,
    },
    "external_message": {
        "permission": "external_message",
        "policy": "requires_explicit_confirmation",
        "requires_confirmation": True,
        "final_user_confirmation": False,
    },
    "external_execution": {
        "permission": "external_execution",
        "policy": "requires_explicit_confirmation",
        "requires_confirmation": True,
        "final_user_confirmation": False,
    },
    "payment_or_purchase": {
        "permission": "payment_or_purchase",
        "policy": "requires_final_user_confirmation",
        "requires_confirmation": True,
        "final_user_confirmation": True,
    },
}


def execution_guard(permission: str) -> dict[str, Any]:
    return dict(PERMISSION_POLICIES.get(permission, PERMISSION_POLICIES["read_only"]))


def risk_from_permission(permission: str) -> dict[str, Any]:
    guard = execution_guard(permission)
    return {
        "permission": guard["permission"],
        "confirmation_required": bool(guard["requires_confirmation"]),
        "final_user_confirmation": bool(guard["final_user_confirmation"]),
    }


def missing_slots(required_slots: list[str], slots: dict[str, Any]) -> list[str]:
    return [
        slot
        for slot in required_slots
        if slots.get(slot) is None or slots.get(slot) == "" or slots.get(slot) == []
    ]


def step_states(step_names: list[str], blocked: bool = False) -> list[dict[str, str]]:
    return [
        {"name": step, "status": "pending" if blocked else "completed"}
        for step in step_names
    ]


def pipeline_result(
    *,
    pipeline_id: str,
    status: str,
    required_slots: list[str],
    resolved_slots: dict[str, Any],
    permission: str,
    steps: list[str],
    output: dict[str, Any],
    writeback_targets: list[str],
    external_effects: list[str] | None = None,
    provider_calls: list[dict[str, Any]] | None = None,
    writeback_plan: list[dict[str, Any]] | None = None,
    validation_warnings: list[str] | None = None,
) -> dict[str, Any]:
    missing = missing_slots(required_slots, resolved_slots)
    blocked = status in {"needs_user_input", "blocked", "failed"}
    return {
        "pipeline_id": pipeline_id,
        "status": status,
        "required_slots": required_slots,
        "resolved_slots": resolved_slots,
        "missing_slots": missing,
        "risk": risk_from_permission(permission),
        "execution_guard": execution_guard(permission),
        "external_effects": external_effects or [],
        "writeback_targets": writeback_targets,
        "steps": step_states(steps, blocked=blocked),
        "output": output,
        "provider_calls": provider_calls or [],
        "writeback_plan": writeback_plan or [],
        "validation_warnings": validation_warnings or [],
    }


def first_value(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "" and value != []:
            return value
    return None
