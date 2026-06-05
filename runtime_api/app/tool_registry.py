from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


CONFIRMATION_PERMISSIONS = {
    "external_message",
    "external_execution",
    "purchase_or_payment",
    "payment_or_purchase",
    "write",
    "destructive",
}


@dataclass(frozen=True)
class CapabilityDefinition:
    capability_id: str
    route_type: str
    pipeline_id: str | None
    keywords: tuple[str, ...]
    preferred_adapter: str
    required_toolkit: str | None
    permission: str
    confirmation_required: bool
    reason: str
    forbidden_actions: tuple[str, ...] = ()
    alternative_adapters: tuple[str, ...] = ()


@dataclass
class ToolRegistry:
    capabilities: list[CapabilityDefinition]
    connected_adapters: dict[str, set[str]] = field(default_factory=dict)
    enabled_adapters: set[str] = field(default_factory=lambda: {"composio", "openclaw", "browser", "local"})

    def route_request(self, request: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = context or {}
        capability = self._match_capability(request)
        selected_adapter = self._select_adapter(capability, context)
        route_type = capability.route_type
        status = "ready"
        connect_action = None

        if capability.required_toolkit and not self._is_connected(selected_adapter, capability.required_toolkit):
            route_type = "connect_required"
            status = "needs_connection"
            connect_action = {
                "adapter": selected_adapter,
                "toolkit": capability.required_toolkit,
                "action": "connect_account",
                "reason": f"{capability.required_toolkit} is required before this capability can run.",
            }

        confirmation_required = capability.confirmation_required or capability.permission in CONFIRMATION_PERMISSIONS
        decision = {
            "route_type": route_type,
            "status": status,
            "capability_id": capability.capability_id,
            "pipeline_id": capability.pipeline_id,
            "selected_adapter": selected_adapter,
            "adapter_candidates": self._adapter_candidates(capability),
            "required_toolkit": capability.required_toolkit,
            "permission": capability.permission,
            "confirmation_required": confirmation_required,
            "execution_guard": {
                "permission": capability.permission,
                "policy": "requires_final_user_confirmation" if confirmation_required else "allowed_without_confirmation",
                "final_user_confirmation": confirmation_required,
            },
            "forbidden_actions": list(capability.forbidden_actions),
            "context_policy": self._context_policy(capability, context),
            "reason": capability.reason,
        }
        if connect_action:
            decision["connect_action"] = connect_action
        return decision

    def _match_capability(self, request: str) -> CapabilityDefinition:
        lowered = request.lower()
        scored: list[tuple[int, int, int, CapabilityDefinition]] = []
        for index, capability in enumerate(self.capabilities):
            matched_keywords = [keyword for keyword in capability.keywords if keyword.lower() in lowered]
            score = len(matched_keywords)
            if score:
                specificity = sum(len(keyword) for keyword in matched_keywords)
                scored.append((score, specificity, -index, capability))
        if scored:
            return sorted(scored, key=lambda item: (item[0], item[1], item[2]), reverse=True)[0][3]
        return self._fallback_capability()

    def _fallback_capability(self) -> CapabilityDefinition:
        for capability in self.capabilities:
            if capability.capability_id == "long_tail.browser_task":
                return capability
        raise ValueError("long_tail.browser_task capability is required")

    def _select_adapter(self, capability: CapabilityDefinition, context: dict[str, Any]) -> str:
        preferred = str(context.get("adapter") or capability.preferred_adapter)
        if preferred in self.enabled_adapters:
            return preferred
        for adapter in capability.alternative_adapters:
            if adapter in self.enabled_adapters:
                return adapter
        return capability.preferred_adapter

    def _adapter_candidates(self, capability: CapabilityDefinition) -> list[str]:
        candidates = [capability.preferred_adapter, *capability.alternative_adapters]
        seen = set()
        return [adapter for adapter in candidates if not (adapter in seen or seen.add(adapter))]

    def _is_connected(self, adapter: str, toolkit: str) -> bool:
        connected_toolkits = self.connected_adapters.get(adapter, set())
        return toolkit in connected_toolkits

    def _context_policy(self, capability: CapabilityDefinition, context: dict[str, Any]) -> dict[str, Any]:
        include_keys = [
            key
            for key in [
                "source_event_ids",
                "conversation_id",
                "agenda_item_ids",
                "current_url",
                "selected_text",
            ]
            if key in context
        ]
        return {
            "mode": "minimal_relevant_context",
            "included_keys": include_keys,
            "raw_private_payload_allowed": False,
            "reason": "Only explicit task references and UI state are passed to external adapters.",
        }


def default_tool_registry(
    *,
    connected_adapters: dict[str, set[str]] | None = None,
    enabled_adapters: set[str] | None = None,
) -> ToolRegistry:
    return ToolRegistry(
        capabilities=[
            CapabilityDefinition(
                capability_id="assistant.sms.send",
                route_type="core_pipeline",
                pipeline_id="reply_pipeline",
                keywords=(
                    "nomi 自己的手机号",
                    "自己的手机号给",
                    "用 nomi 发短信",
                    "nomi 发短信",
                    "助理手机号",
                    "发短信",
                    "短信",
                    "sms",
                ),
                preferred_adapter="local",
                alternative_adapters=("composio",),
                required_toolkit="assistant_phone",
                permission="external_message",
                confirmation_required=True,
                reason="Use Nomi-owned phone identity for SMS; final send requires user confirmation.",
                forbidden_actions=("send_without_confirmation", "delete", "block"),
            ),
            CapabilityDefinition(
                capability_id="assistant.phone.call_playback",
                route_type="core_pipeline",
                pipeline_id="reply_pipeline",
                keywords=(
                    "nomi 自己的手机号",
                    "自己的手机号给",
                    "用 nomi 打电话",
                    "nomi 打电话",
                    "电话播放",
                    "播放语音",
                    "打电话",
                    "拨打",
                    "phone call",
                ),
                preferred_adapter="local",
                alternative_adapters=("composio",),
                required_toolkit="assistant_phone",
                permission="external_message",
                confirmation_required=True,
                reason=(
                    "Use Nomi-owned phone identity for one-way playback calls. "
                    "V1 cannot do duplex voice; final call requires user confirmation."
                ),
                forbidden_actions=("send_without_confirmation", "duplex_call", "record_call_without_notice"),
            ),
            CapabilityDefinition(
                capability_id="assistant.email.send",
                route_type="core_pipeline",
                pipeline_id="reply_pipeline",
                keywords=("用 nomi 自己的邮箱", "nomi 自己的邮箱", "nomi gmail", "助理邮箱", "用 nomi 发邮件", "nomi", "自己的邮箱"),
                preferred_adapter="local",
                alternative_adapters=("composio",),
                required_toolkit="assistant_gmail",
                permission="external_message",
                confirmation_required=True,
                reason="Use Nomi-owned Gmail identity; final send requires user confirmation.",
                forbidden_actions=("send_without_confirmation", "delete", "archive"),
            ),
            CapabilityDefinition(
                capability_id="assistant.whatsapp.send",
                route_type="core_pipeline",
                pipeline_id="reply_pipeline",
                keywords=("nomi whatsapp", "助理 whatsapp", "用 nomi 发 whatsapp", "用 whatsapp 告诉"),
                preferred_adapter="local",
                alternative_adapters=("openclaw",),
                required_toolkit="assistant_whatsapp",
                permission="external_message",
                confirmation_required=True,
                reason="Use Nomi-owned WhatsApp identity; final send requires user confirmation.",
                forbidden_actions=("send_without_confirmation", "delete", "block"),
            ),
            CapabilityDefinition(
                capability_id="ride.prepare_booking",
                route_type="core_pipeline",
                pipeline_id="ride_pipeline",
                keywords=("打车", "叫车", "uber", "ride", "taxi", "网约车"),
                preferred_adapter="composio",
                alternative_adapters=("openclaw",),
                required_toolkit="google_maps",
                permission="purchase_or_payment",
                confirmation_required=True,
                reason=(
                    "Matched ride capability first, then selected Composio as adapter. "
                    "Ride booking or payment remains blocked until final confirmation."
                ),
                forbidden_actions=("book", "pay", "purchase", "transfer"),
            ),
            CapabilityDefinition(
                capability_id="email.send_draft",
                route_type="core_pipeline",
                pipeline_id="email_pipeline",
                keywords=("发邮件", "写邮件", "email", "gmail", "邮件"),
                preferred_adapter="composio",
                alternative_adapters=("openclaw",),
                required_toolkit="gmail",
                permission="external_message",
                confirmation_required=True,
                reason=(
                    "Matched email capability first, then selected Composio Gmail tools. "
                    "Sending is blocked until the user confirms the final draft."
                ),
                forbidden_actions=("send", "send_email", "delete"),
            ),
            CapabilityDefinition(
                capability_id="long_tail.browser_task",
                route_type="openclaw_tool",
                pipeline_id=None,
                keywords=("网站", "网页", "报名", "表格", "browser", "website", "openclaw"),
                preferred_adapter="openclaw",
                alternative_adapters=("browser",),
                required_toolkit=None,
                permission="external_execution",
                confirmation_required=True,
                reason=(
                    "No deterministic core capability is specific enough; route through OpenClaw with "
                    "minimal context and explicit external-effect guards."
                ),
                forbidden_actions=("submit", "send", "delete", "pay", "purchase", "book", "transfer"),
            ),
        ],
        connected_adapters=connected_adapters or {},
        enabled_adapters=enabled_adapters or {"composio", "openclaw", "browser", "local"},
    )


def tool_registry_schema_sql() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS capability_catalog (
          capability_id TEXT PRIMARY KEY,
          route_type TEXT NOT NULL,
          pipeline_id TEXT,
          preferred_adapter TEXT NOT NULL,
          required_toolkit TEXT,
          permission TEXT NOT NULL,
          confirmation_required BOOLEAN NOT NULL DEFAULT FALSE,
          keywords TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS tool_registry_entries (
          id UUID PRIMARY KEY,
          adapter_id TEXT NOT NULL,
          toolkit_slug TEXT,
          tool_slug TEXT,
          capability_id TEXT NOT NULL,
          connection_status TEXT NOT NULL DEFAULT 'unknown',
          permission TEXT NOT NULL DEFAULT '',
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS tool_invocation_traces (
          id UUID PRIMARY KEY,
          task_trace_id TEXT,
          capability_id TEXT NOT NULL,
          adapter_id TEXT NOT NULL,
          toolkit_slug TEXT,
          tool_slug TEXT,
          status TEXT NOT NULL,
          confirmation_required BOOLEAN NOT NULL DEFAULT FALSE,
          input_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
          output_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
          error TEXT NOT NULL DEFAULT '',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS tool_registry_entries_capability_idx
        ON tool_registry_entries(capability_id, adapter_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS tool_invocation_traces_capability_idx
        ON tool_invocation_traces(capability_id, created_at DESC)
        """,
    ]
