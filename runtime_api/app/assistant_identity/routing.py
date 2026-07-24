from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class TriggerDecision:
    trigger_id: str
    trigger_source: str
    route_type: str
    pipeline_id: str
    capability_id: str
    confirmation_required: bool
    agent_allowed: bool
    reason: str
    allowed_effects: list[str] = field(default_factory=list)
    forbidden_effects: list[str] = field(default_factory=list)
    agent_allowed_tools: list[str] = field(default_factory=list)
    forbidden_provider_tools: list[str] = field(default_factory=list)
    source_evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AssistantCommunicationTriggerRouter:
    LONG_TAIL_HINTS = (
        "分析",
        "策略",
        "规划",
        "协调",
        "找出",
        "比较",
        "先",
        "整理后",
        "复杂",
    )
    PROVIDER_SEND_TOOLS = (
        "gmail.messages.send",
        "gmail.drafts.send",
        "whatsapp.messages.send",
        "sms.messages.send",
        "phone.calls.create",
        "twilio.messages.create",
        "twilio.calls.create",
        "composio.gmail.send",
        "composio.whatsapp.send",
        "composio.sms.send",
        "composio.phone.call",
    )

    def route(self, trigger: dict[str, Any]) -> dict[str, Any]:
        source = str(trigger.get("trigger_source") or "unknown")
        text = str(trigger.get("text") or "")
        channel_hint = str(trigger.get("channel_hint") or "").lower()
        evidence = [str(item) for item in trigger.get("source_evidence_ids", [])]

        if source == "provider_status":
            return self._decision(
                source=source,
                route_type="none",
                pipeline_id="delivery_state_pipeline",
                capability_id="assistant.delivery.update",
                confirmation_required=False,
                agent_allowed=False,
                reason="Provider status events only update delivery or sync state.",
                allowed_effects=["update_state"],
                forbidden_effects=["draft", "send", "auto_reply"],
                evidence=evidence,
            )

        if source in {"external_contact_message", "unknown_sender", "noise_or_spam"}:
            return self._decision(
                source=source,
                route_type="none",
                pipeline_id="proactive_suggestion_pipeline",
                capability_id="assistant.inbox.read",
                confirmation_required=False,
                agent_allowed=False,
                reason="Inbound external or low-trust messages are stored and surfaced to the user before any reply.",
                allowed_effects=["store", "summarize", "notify_user_if_relevant"],
                forbidden_effects=["auto_reply", "send_without_confirmation"],
                evidence=evidence,
            )

        if source == "agent_outbound_request":
            return self._decision(
                source=source,
                route_type="core_pipeline",
                pipeline_id="outbound_message_pipeline",
                capability_id="assistant.email.create_draft",
                confirmation_required=True,
                agent_allowed=False,
                reason="Agent-produced outbound intent must return to the deterministic draft pipeline.",
                allowed_effects=["draft"],
                forbidden_effects=["send_without_confirmation"],
                evidence=evidence,
            )

        if source in {"user_explicit_send_request", "proactive_suggestion_action"}:
            capability_id = self._capability_for(channel_hint, text)
            return self._decision(
                source=source,
                route_type="core_pipeline",
                pipeline_id="reply_pipeline",
                capability_id=capability_id,
                confirmation_required=True,
                agent_allowed=False,
                reason=self._core_reason(source, capability_id),
                allowed_effects=["draft"],
                forbidden_effects=["send_without_confirmation", "delete", "archive", "block"],
                evidence=evidence,
            )

        if source == "user_direct_command" and self._looks_long_tail(text):
            return self._decision(
                source=source,
                route_type="agent",
                pipeline_id="long_tail_agent_pipeline",
                capability_id="assistant.email.create_draft",
                confirmation_required=True,
                agent_allowed=True,
                reason="The deterministic pipeline was insufficient because the request requires planning before drafting.",
                allowed_effects=["plan", "read_scoped_memory", "create_draft"],
                forbidden_effects=["send_without_confirmation", "direct_provider_send"],
                agent_allowed_tools=["assistant.email.create_draft"],
                forbidden_provider_tools=list(self.PROVIDER_SEND_TOOLS),
                evidence=evidence,
            )

        return self._decision(
            source=source,
            route_type="core_pipeline",
            pipeline_id="reply_pipeline",
            capability_id=self._capability_for(channel_hint, text),
            confirmation_required=True,
            agent_allowed=False,
            reason="Known communication request resolved by deterministic routing.",
            allowed_effects=["draft"],
            forbidden_effects=["send_without_confirmation"],
            evidence=evidence,
        )

    def _capability_for(self, channel_hint: str, text: str) -> str:
        lower = text.lower()
        if channel_hint == "whatsapp" or "whatsapp" in lower:
            return "assistant.whatsapp.send"
        if channel_hint in {"phone_call", "phone", "call"}:
            return "assistant.phone.call_playback"
        if channel_hint == "sms":
            return "assistant.sms.send"
        if any(hint in text for hint in ("打电话", "电话通知", "拨打", "语音电话")) or "call" in lower:
            return "assistant.phone.call_playback"
        if any(hint in text for hint in ("短信", "发 sms", "发sms")) or "sms" in lower:
            return "assistant.sms.send"
        return "assistant.email.send"

    def _looks_long_tail(self, text: str) -> bool:
        return any(hint in text for hint in self.LONG_TAIL_HINTS)

    def _core_reason(self, source: str, capability_id: str) -> str:
        if source == "proactive_suggestion_action":
            return f"User selected a proactive suggestion; route {capability_id} to draft confirmation."
        return f"Known Nomi-owned communication request; route {capability_id} to draft confirmation."

    def _decision(
        self,
        *,
        source: str,
        route_type: str,
        pipeline_id: str,
        capability_id: str,
        confirmation_required: bool,
        agent_allowed: bool,
        reason: str,
        allowed_effects: list[str],
        forbidden_effects: list[str],
        evidence: list[str],
        agent_allowed_tools: list[str] | None = None,
        forbidden_provider_tools: list[str] | None = None,
    ) -> dict[str, Any]:
        return TriggerDecision(
            trigger_id=str(uuid4()),
            trigger_source=source,
            route_type=route_type,
            pipeline_id=pipeline_id,
            capability_id=capability_id,
            confirmation_required=confirmation_required,
            agent_allowed=agent_allowed,
            reason=reason,
            allowed_effects=allowed_effects,
            forbidden_effects=forbidden_effects,
            agent_allowed_tools=agent_allowed_tools or [],
            forbidden_provider_tools=forbidden_provider_tools or [],
            source_evidence_ids=evidence,
        ).to_dict()
