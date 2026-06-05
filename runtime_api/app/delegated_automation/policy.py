from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.delegated_automation.models import (
    AutomationDecision,
    DelegationGrant,
    ExecutionTrace,
    TargetManifest,
)


PERSONAL_ACCOUNT_SURFACES = {
    "user_gmail",
    "user_whatsapp",
    "personal_gmail",
    "personal_whatsapp",
}

SUPPORTED_BATCH_LEVELS = {"L4", "L5"}
PLATFORM_CHALLENGE_KEYS = {
    "captcha",
    "two_factor",
    "2fa",
    "account_security",
    "suspicious_activity",
    "login_challenge",
    "security_check",
    "blocked",
}


def _same_day(left: datetime, right: datetime) -> bool:
    left_utc = left.astimezone(timezone.utc)
    right_utc = right.astimezone(timezone.utc)
    return left_utc.date() == right_utc.date()


def _completed_today(grant: DelegationGrant, traces: list[ExecutionTrace], now: datetime) -> list[ExecutionTrace]:
    return [
        trace
        for trace in traces
        if trace.grant_id == grant.grant_id
        and trace.action == grant.action
        and trace.status == "completed"
        and _same_day(trace.started_at, now)
    ]


def _platform_challenge(page_state: dict | None) -> bool:
    if not isinstance(page_state, dict):
        return False
    return any(bool(page_state.get(key)) for key in PLATFORM_CHALLENGE_KEYS)


def _base_decision(
    *,
    allowed: bool,
    reasons: list[str],
    stop_condition: str | None,
    grant: DelegationGrant | None,
    manifest: TargetManifest | None,
    target_id: str,
    traces: list[ExecutionTrace],
    now: datetime,
    target: dict | None = None,
    evidence_ids: list[str] | None = None,
) -> AutomationDecision:
    used_today = len(_completed_today(grant, traces, now)) if grant else 0
    daily_limit = grant.daily_limit if grant else 0
    remaining_today = max(daily_limit - used_today, 0)
    return AutomationDecision(
        allowed=allowed,
        reasons=reasons,
        stop_condition=stop_condition,
        grant_id=grant.grant_id if grant else "",
        manifest_id=manifest.manifest_id if manifest else "",
        target_id=target_id,
        action=grant.action if grant else "",
        scenario=grant.scenario if grant else "",
        platform=grant.platform if grant else "",
        surface=grant.surface if grant else "",
        automation_level=grant.automation_level if grant else "",
        budget={
            "daily_limit": daily_limit,
            "batch_limit": grant.batch_limit if grant else 0,
            "used_today": used_today,
            "remaining_today": remaining_today,
        },
        target=target,
        evidence_ids=list(evidence_ids or []),
    )


def evaluate_delegated_action(
    *,
    grant: DelegationGrant | None,
    manifest: TargetManifest | None,
    target_id: str,
    traces: list[ExecutionTrace],
    now: datetime | None = None,
    page_state: dict | None = None,
    content_evidence_ids: list[str] | None = None,
    user_paused: bool = False,
) -> AutomationDecision:
    now = now or datetime.now(timezone.utc)
    evidence_ids = [str(item) for item in content_evidence_ids or []]
    if grant is None:
        return _base_decision(
            allowed=False,
            reasons=["missing_grant"],
            stop_condition="missing_grant",
            grant=None,
            manifest=manifest,
            target_id=target_id,
            traces=traces,
            now=now,
            evidence_ids=evidence_ids,
        )

    if grant.surface in PERSONAL_ACCOUNT_SURFACES:
        return _base_decision(
            allowed=False,
            reasons=["personal_account_surface_out_of_scope"],
            stop_condition="personal_account_surface_out_of_scope",
            grant=grant,
            manifest=manifest,
            target_id=target_id,
            traces=traces,
            now=now,
            evidence_ids=evidence_ids,
        )

    if not grant.is_active_at(now):
        return _base_decision(
            allowed=False,
            reasons=["grant_inactive_or_expired"],
            stop_condition="grant_inactive_or_expired",
            grant=grant,
            manifest=manifest,
            target_id=target_id,
            traces=traces,
            now=now,
            evidence_ids=evidence_ids,
        )

    if user_paused and grant.stop_on_user_pause:
        return _base_decision(
            allowed=False,
            reasons=["user_paused"],
            stop_condition="user_paused",
            grant=grant,
            manifest=manifest,
            target_id=target_id,
            traces=traces,
            now=now,
            evidence_ids=evidence_ids,
        )

    if _platform_challenge(page_state) and grant.stop_on_challenge:
        return _base_decision(
            allowed=False,
            reasons=["platform_challenge"],
            stop_condition="platform_challenge",
            grant=grant,
            manifest=manifest,
            target_id=target_id,
            traces=traces,
            now=now,
            evidence_ids=evidence_ids,
        )

    if grant.automation_level in SUPPORTED_BATCH_LEVELS and grant.requires_target_manifest and manifest is None:
        return _base_decision(
            allowed=False,
            reasons=["missing_target_manifest"],
            stop_condition="missing_target_manifest",
            grant=grant,
            manifest=manifest,
            target_id=target_id,
            traces=traces,
            now=now,
            evidence_ids=evidence_ids,
        )

    target = manifest.target_by_id(target_id) if manifest else None
    if manifest and (manifest.scenario != grant.scenario or manifest.platform != grant.platform or manifest.action != grant.action):
        return _base_decision(
            allowed=False,
            reasons=["manifest_scope_mismatch"],
            stop_condition="manifest_scope_mismatch",
            grant=grant,
            manifest=manifest,
            target_id=target_id,
            traces=traces,
            now=now,
            evidence_ids=evidence_ids,
        )

    if manifest and target is None:
        return _base_decision(
            allowed=False,
            reasons=["target_not_in_manifest"],
            stop_condition="target_not_in_manifest",
            grant=grant,
            manifest=manifest,
            target_id=target_id,
            traces=traces,
            now=now,
            evidence_ids=evidence_ids,
        )

    if grant.requires_grounded_content and not evidence_ids:
        return _base_decision(
            allowed=False,
            reasons=["missing_grounded_content"],
            stop_condition="missing_grounded_content",
            grant=grant,
            manifest=manifest,
            target_id=target_id,
            traces=traces,
            now=now,
            target=target.to_dict() if target else None,
            evidence_ids=evidence_ids,
        )

    completed_today = _completed_today(grant, traces, now)
    if any(trace.target_id == target_id for trace in completed_today):
        return _base_decision(
            allowed=False,
            reasons=["duplicate_target"],
            stop_condition="duplicate_target",
            grant=grant,
            manifest=manifest,
            target_id=target_id,
            traces=traces,
            now=now,
            target=target.to_dict() if target else None,
            evidence_ids=evidence_ids,
        )

    if grant.daily_limit and len(completed_today) >= grant.daily_limit:
        return _base_decision(
            allowed=False,
            reasons=["daily_limit_reached"],
            stop_condition="quota_exhausted",
            grant=grant,
            manifest=manifest,
            target_id=target_id,
            traces=traces,
            now=now,
            target=target.to_dict() if target else None,
            evidence_ids=evidence_ids,
        )

    if manifest:
        completed_in_manifest = [trace for trace in completed_today if trace.manifest_id == manifest.manifest_id]
        if manifest.max_actions and len(completed_in_manifest) >= manifest.max_actions:
            return _base_decision(
                allowed=False,
                reasons=["manifest_limit_reached"],
                stop_condition="quota_exhausted",
                grant=grant,
                manifest=manifest,
                target_id=target_id,
                traces=traces,
                now=now,
                target=target.to_dict() if target else None,
                evidence_ids=evidence_ids,
            )
        if grant.batch_limit and len(completed_in_manifest) >= grant.batch_limit:
            return _base_decision(
                allowed=False,
                reasons=["batch_limit_reached"],
                stop_condition="quota_exhausted",
                grant=grant,
                manifest=manifest,
                target_id=target_id,
                traces=traces,
                now=now,
                target=target.to_dict() if target else None,
                evidence_ids=evidence_ids,
            )

    if grant.cooldown_minutes and completed_today:
        last_action = max(trace.finished_at for trace in completed_today)
        if now < last_action + timedelta(minutes=grant.cooldown_minutes):
            return _base_decision(
                allowed=False,
                reasons=["cooldown_active"],
                stop_condition="cooldown_active",
                grant=grant,
                manifest=manifest,
                target_id=target_id,
                traces=traces,
                now=now,
                target=target.to_dict() if target else None,
                evidence_ids=evidence_ids,
            )

    return _base_decision(
        allowed=True,
        reasons=["allowed_by_active_delegation"],
        stop_condition=None,
        grant=grant,
        manifest=manifest,
        target_id=target_id,
        traces=traces,
        now=now,
        target=target.to_dict() if target else None,
        evidence_ids=evidence_ids,
    )


def build_execution_trace(
    *,
    decision: AutomationDecision,
    trace_id: str,
    status: str,
    result_summary: str,
    evidence_ids: list[str],
    now: datetime | None = None,
) -> ExecutionTrace:
    now = now or datetime.now(timezone.utc)
    used_today = int(decision.budget.get("used_today") or 0)
    daily_limit = int(decision.budget.get("daily_limit") or 0)
    if status == "completed":
        used_today += 1
    budget_after = {
        "used_today": used_today,
        "remaining_today": max(daily_limit - used_today, 0),
    }
    return ExecutionTrace(
        trace_id=trace_id,
        grant_id=decision.grant_id,
        manifest_id=decision.manifest_id,
        target_id=decision.target_id,
        action=decision.action,
        status=status,
        started_at=now,
        finished_at=now,
        result_summary=result_summary,
        evidence_ids=[str(item) for item in evidence_ids],
        budget_after=budget_after,
        metadata={
            "decision_reasons": list(decision.reasons),
            "scenario": decision.scenario,
            "platform": decision.platform,
            "surface": decision.surface,
        },
    )
