from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from app.assistant_identity.outbound import OutboundMessagePipeline
from app.assistant_identity.registry import AssistantIdentityRegistry
from app.assistant_identity.audit import AssistantIdentityAuditor


ASSISTANT_TOOL_NAMES = (
    "assistant.identity.get_status",
    "assistant.contacts.resolve",
    "assistant.email.create_draft",
    "assistant.outbound.get_status",
    "assistant.outbound.cancel_draft",
)


def _stable_nonempty_strings(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values if isinstance(values, (list, tuple, set)) else []:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def build_assistant_task_scope(
    task_state: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Build a fail-closed assistant tool scope from server-owned task state."""

    task_id = str(task_state.get("task_id") or "").strip()
    current_step_id = str(task_state.get("current_step_id") or "").strip()
    route_decision = (
        dict(task_state.get("route_decision") or {})
        if isinstance(task_state.get("route_decision"), dict)
        else {}
    )
    current_step: dict[str, Any] = {}
    for raw_step in plan.get("steps") or []:
        step = dict(raw_step) if isinstance(raw_step, dict) else {}
        if current_step_id and str(step.get("step_id") or "").strip() == current_step_id:
            current_step = step
            break
    allowed_actions = set(_stable_nonempty_strings(current_step.get("allowed_actions")))
    return {
        "task_id": task_id,
        "step_id": current_step_id if current_step else "",
        "permitted_tool_names": [
            tool_name for tool_name in ASSISTANT_TOOL_NAMES if tool_name in allowed_actions
        ],
        "permitted_contact_ids": _stable_nonempty_strings(
            route_decision.get("permitted_contact_ids")
        ),
        "permitted_source_evidence_ids": _stable_nonempty_strings(
            route_decision.get("source_event_ids")
        ),
    }


class AssistantScopedToolExecutor:
    """Execute assistant tools against scope rebuilt from server-owned task state."""

    def __init__(
        self,
        *,
        gateway: "AssistantToolGateway",
        task_loader: Callable[[str], tuple[dict[str, Any], dict[str, Any]]],
        event_store: Any,
    ) -> None:
        self.gateway = gateway
        self.task_loader = task_loader
        self.event_store = event_store

    def execute(
        self,
        *,
        task_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        requested_task_id = str(task_id or "").strip()
        if not requested_task_id:
            raise PermissionError("assistant_task_scope_missing")
        task_state, plan = self.task_loader(requested_task_id)
        if str(task_state.get("task_id") or "").strip() != requested_task_id:
            raise PermissionError("assistant_task_scope_mismatch")
        task_scope = build_assistant_task_scope(task_state, plan)
        trusted_arguments = dict(arguments or {})
        trusted_arguments.pop("task_scope", None)
        result = self.gateway.execute(
            tool_name,
            trusted_arguments,
            task_scope=task_scope,
        )
        safe_payload = {
            "tool_name": tool_name,
            "status": str(result.get("status") or "completed"),
        }
        draft_id = str(result.get("draft_id") or "").strip()
        if draft_id:
            safe_payload["draft_id"] = draft_id
        request_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "tool_name": tool_name,
                    "arguments": trusted_arguments,
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        self.event_store.append_event(
            task_id=requested_task_id,
            event_type="assistant.tool.executed",
            step_id=str(task_scope.get("step_id") or "") or None,
            node_name="assistant_tool_gateway",
            payload=safe_payload,
            idempotency_key=(
                f"{requested_task_id}:assistant_tool:{tool_name}:{request_fingerprint}"
            ),
            redaction_summary={
                "arguments_persisted": False,
                "provider_credentials_persisted": False,
            },
        )
        return dict(result)


def assistant_tool_manifest() -> list[dict[str, Any]]:
    return [
        {
            "name": "assistant.identity.get_status",
            "description": "读取 Nomi 助理身份的脱敏可用状态。",
            "input_schema": {
                "type": "object",
                "properties": {"identity_id": {"type": "string"}},
                "required": ["identity_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "assistant.contacts.resolve",
            "description": "在当前任务授权范围内解析一个联系人。",
            "input_schema": {
                "type": "object",
                "properties": {"contact_id": {"type": "string"}},
                "required": ["contact_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "assistant.email.create_draft",
            "description": "创建一封等待用户确认的 Nomi 邮件草稿，不执行发送。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "identity_id": {"type": "string"},
                    "recipient": {
                        "type": "object",
                        "properties": {"contact_id": {"type": "string"}},
                        "required": ["contact_id"],
                        "additionalProperties": False,
                    },
                    "subject": {"type": "string"},
                    "body_text": {"type": "string"},
                    "source_evidence_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "task_id": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": [
                    "identity_id",
                    "recipient",
                    "subject",
                    "body_text",
                    "source_evidence_ids",
                    "task_id",
                    "idempotency_key",
                ],
                "additionalProperties": False,
            },
        },
        {
            "name": "assistant.outbound.get_status",
            "description": "读取当前任务创建的助理外发草稿状态。",
            "input_schema": {
                "type": "object",
                "properties": {"draft_id": {"type": "string"}},
                "required": ["draft_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "assistant.outbound.cancel_draft",
            "description": "取消当前任务创建且尚未发送的草稿。",
            "input_schema": {
                "type": "object",
                "properties": {"draft_id": {"type": "string"}},
                "required": ["draft_id"],
                "additionalProperties": False,
            },
        },
    ]


class AssistantToolGateway:
    def __init__(
        self,
        *,
        registry: AssistantIdentityRegistry,
        outbound: OutboundMessagePipeline,
        contacts: dict[str, dict[str, str]] | None = None,
        contact_lookup: Callable[[str], dict[str, str] | None] | None = None,
        auditor: AssistantIdentityAuditor | None = None,
    ) -> None:
        self.registry = registry
        self.outbound = outbound
        self.contacts = {
            str(contact_id): dict(contact)
            for contact_id, contact in (contacts or {}).items()
        }
        self._idempotent_results: dict[tuple[str, str], dict[str, Any]] = {}
        self._draft_owners: dict[str, str] = {}
        self.contact_lookup = contact_lookup
        self.auditor = auditor or AssistantIdentityAuditor()

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        task_scope: dict[str, Any],
    ) -> dict[str, Any]:
        if tool_name not in ASSISTANT_TOOL_NAMES:
            self._blocked_tool_audit(
                tool_name,
                arguments,
                task_scope,
                reason="assistant_tool_not_allowed",
            )
            raise PermissionError("assistant_tool_not_allowed")
        task_id = str(task_scope.get("task_id") or "").strip()
        if not task_id:
            self._blocked_tool_audit(
                tool_name,
                arguments,
                task_scope,
                reason="assistant_task_scope_missing",
            )
            raise PermissionError("assistant_task_scope_missing")
        permitted_tool_names = set(
            _stable_nonempty_strings(task_scope.get("permitted_tool_names"))
        )
        if tool_name not in permitted_tool_names:
            self._blocked_tool_audit(
                tool_name,
                arguments,
                task_scope,
                reason="assistant_tool_scope_denied",
            )
            raise PermissionError("assistant_tool_scope_denied")
        handlers = {
            "assistant.identity.get_status": self._identity_status,
            "assistant.contacts.resolve": self._resolve_contact,
            "assistant.email.create_draft": self._create_email_draft,
            "assistant.outbound.get_status": self._outbound_status,
            "assistant.outbound.cancel_draft": self._cancel_draft,
        }
        return handlers[tool_name](dict(arguments or {}), task_scope)

    def _blocked_tool_audit(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        task_scope: dict[str, Any],
        *,
        reason: str,
    ) -> None:
        self.auditor.record(
            "assistant_tool.blocked",
            actor="opencode",
            identity_id=str(arguments.get("identity_id") or ""),
            status="blocked",
            policy_result=reason,
            payload={
                "tool_name": tool_name,
                "task_id": str(task_scope.get("task_id") or ""),
                "arguments": dict(arguments or {}),
            },
        )

    def _identity_status(
        self,
        arguments: dict[str, Any],
        task_scope: dict[str, Any],
    ) -> dict[str, Any]:
        del task_scope
        identity_id = str(arguments.get("identity_id") or "").strip()
        identity = self.registry.get(identity_id)
        if identity is None:
            raise KeyError("assistant_identity_not_found")
        return {
            "identity_id": identity.identity_id,
            "display_name": identity.display_name,
            "address": identity.address,
            "status": identity.status,
            "capabilities": list(identity.capabilities),
            "available": identity.status == "connected",
        }

    def _resolve_contact(
        self,
        arguments: dict[str, Any],
        task_scope: dict[str, Any],
    ) -> dict[str, str]:
        contact_id = str(arguments.get("contact_id") or "").strip()
        permitted = {
            str(item)
            for item in task_scope.get("permitted_contact_ids") or []
            if str(item)
        }
        if not contact_id or contact_id not in permitted:
            raise PermissionError("contact_scope_denied")
        contact = self.contacts.get(contact_id)
        if contact is None and self.contact_lookup is not None:
            resolved = self.contact_lookup(contact_id)
            contact = dict(resolved) if resolved else None
        if not contact or not str(contact.get("gmail") or "").strip():
            raise KeyError("contact_gmail_not_resolved")
        return {
            "contact_id": contact_id,
            "display_name": str(contact.get("display_name") or contact_id),
            "address": str(contact["gmail"]),
        }

    def _create_email_draft(
        self,
        arguments: dict[str, Any],
        task_scope: dict[str, Any],
    ) -> dict[str, Any]:
        task_id = str(task_scope.get("task_id") or "").strip()
        if str(arguments.get("task_id") or "").strip() != task_id:
            raise PermissionError("task_scope_mismatch")
        idempotency_key = str(arguments.get("idempotency_key") or "").strip()
        if not idempotency_key:
            raise ValueError("idempotency_key_required")
        cached = self._idempotent_results.get((task_id, idempotency_key))
        if cached is not None:
            return dict(cached)

        identity_id = str(arguments.get("identity_id") or "").strip()
        identity = self.registry.get(identity_id)
        if (
            identity is None
            or identity.kind != "assistant_gmail"
            or identity.status != "connected"
            or "draft" not in identity.capabilities
        ):
            raise PermissionError("assistant_gmail_identity_unavailable")

        recipient_input = arguments.get("recipient")
        recipient = self._resolve_contact(
            dict(recipient_input) if isinstance(recipient_input, dict) else {},
            task_scope,
        )
        evidence_ids = [
            str(item)
            for item in arguments.get("source_evidence_ids") or []
            if str(item)
        ]
        permitted_evidence = {
            str(item)
            for item in task_scope.get("permitted_source_evidence_ids") or []
            if str(item)
        }
        if any(item not in permitted_evidence for item in evidence_ids):
            raise PermissionError("evidence_scope_denied")
        body_text = str(arguments.get("body_text") or "").strip()
        if not body_text:
            raise ValueError("email_body_required")

        draft = self.outbound.prepare_draft(
            identity_id=identity.identity_id,
            channel="gmail",
            recipient=recipient["address"],
            subject=str(arguments.get("subject") or "").strip(),
            body_text=body_text,
            source_evidence_ids=evidence_ids,
            risk_notes=["third_party_send_requires_confirmation"],
            idempotency_key=idempotency_key,
            task_id=task_id,
        )
        result = {
            "status": "confirmation_required",
            "draft_id": draft["draft_id"],
            "identity": f"{identity.display_name} <{identity.address}>",
            "recipient": f"{recipient['display_name']} <{recipient['address']}>",
            "policy_checks": [
                "identity_connected",
                "recipient_resolved",
                "evidence_scope_passed",
                "idempotency_passed",
            ],
            "confirmation_card_id": draft["draft_id"],
            "confirmation_card": dict(draft["confirmation_card"]),
            "audit": {
                "tool_name": "assistant.email.create_draft",
                "task_id": task_id,
                "status": "confirmation_required",
                "draft_id": draft["draft_id"],
                "sensitive_arguments_persisted": False,
            },
        }
        self._draft_owners[draft["draft_id"]] = task_id
        self._idempotent_results[(task_id, idempotency_key)] = dict(result)
        return result

    def _owned_draft(
        self,
        arguments: dict[str, Any],
        task_scope: dict[str, Any],
    ) -> dict[str, Any]:
        draft_id = str(arguments.get("draft_id") or "").strip()
        task_id = str(task_scope.get("task_id") or "").strip()
        draft = self.outbound.get_draft(draft_id)
        persisted_owner = str(draft.get("task_id") or "").strip()
        cached_owner = self._draft_owners.get(draft_id)
        if persisted_owner != task_id and cached_owner != task_id:
            raise PermissionError("draft_scope_denied")
        return draft

    def _outbound_status(
        self,
        arguments: dict[str, Any],
        task_scope: dict[str, Any],
    ) -> dict[str, Any]:
        draft = self._owned_draft(arguments, task_scope)
        return {
            "draft_id": draft["draft_id"],
            "status": draft["status"],
            "confirmation_required": bool(draft.get("confirmation_required")),
            "send_called": bool(draft.get("send_called")),
        }

    def _cancel_draft(
        self,
        arguments: dict[str, Any],
        task_scope: dict[str, Any],
    ) -> dict[str, Any]:
        draft = self._owned_draft(arguments, task_scope)
        cancelled = self.outbound.cancel_draft(draft["draft_id"])
        return {
            "draft_id": cancelled["draft_id"],
            "status": cancelled["status"],
            "confirmation_required": bool(cancelled.get("confirmation_required")),
            "send_called": bool(cancelled.get("send_called")),
        }
