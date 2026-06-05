from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    raise TypeError(f"unsupported datetime value: {value!r}")


def iso_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


@dataclass
class DelegationGrant:
    grant_id: str
    user_id: str
    scenario: str
    platform: str
    surface: str
    action: str
    automation_level: str
    status: str = "active"
    daily_limit: int = 0
    batch_limit: int = 0
    cooldown_minutes: int = 0
    valid_until: datetime | None = None
    requires_target_manifest: bool = True
    requires_grounded_content: bool = True
    requires_audit_log: bool = True
    stop_on_challenge: bool = True
    stop_on_user_pause: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DelegationGrant":
        return cls(
            grant_id=str(payload["grant_id"]),
            user_id=str(payload.get("user_id") or "local_user"),
            scenario=str(payload["scenario"]),
            platform=str(payload["platform"]),
            surface=str(payload["surface"]),
            action=str(payload["action"]),
            automation_level=str(payload["automation_level"]),
            status=str(payload.get("status") or "active"),
            daily_limit=int(payload.get("daily_limit") or 0),
            batch_limit=int(payload.get("batch_limit") or 0),
            cooldown_minutes=int(payload.get("cooldown_minutes") or 0),
            valid_until=parse_datetime(payload.get("valid_until")),
            requires_target_manifest=bool(payload.get("requires_target_manifest", True)),
            requires_grounded_content=bool(payload.get("requires_grounded_content", True)),
            requires_audit_log=bool(payload.get("requires_audit_log", True)),
            stop_on_challenge=bool(payload.get("stop_on_challenge", True)),
            stop_on_user_pause=bool(payload.get("stop_on_user_pause", True)),
            created_at=parse_datetime(payload.get("created_at")) or datetime.now(timezone.utc),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "user_id": self.user_id,
            "scenario": self.scenario,
            "platform": self.platform,
            "surface": self.surface,
            "action": self.action,
            "automation_level": self.automation_level,
            "status": self.status,
            "daily_limit": self.daily_limit,
            "batch_limit": self.batch_limit,
            "cooldown_minutes": self.cooldown_minutes,
            "valid_until": iso_datetime(self.valid_until),
            "requires_target_manifest": self.requires_target_manifest,
            "requires_grounded_content": self.requires_grounded_content,
            "requires_audit_log": self.requires_audit_log,
            "stop_on_challenge": self.stop_on_challenge,
            "stop_on_user_pause": self.stop_on_user_pause,
            "created_at": iso_datetime(self.created_at),
            "metadata": dict(self.metadata),
        }

    def is_active_at(self, now: datetime) -> bool:
        if self.status != "active":
            return False
        if self.valid_until and now > self.valid_until:
            return False
        return True


@dataclass
class ManifestTarget:
    target_id: str
    target_type: str
    name: str = ""
    role: str = ""
    company: str = ""
    profile_url: str = ""
    reason: str = ""
    related_job_id: str = ""
    draft_id: str = ""
    risk: str = "medium"
    status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ManifestTarget":
        return cls(
            target_id=str(payload["target_id"]),
            target_type=str(payload.get("target_type") or "unknown"),
            name=str(payload.get("name") or ""),
            role=str(payload.get("role") or ""),
            company=str(payload.get("company") or ""),
            profile_url=str(payload.get("profile_url") or ""),
            reason=str(payload.get("reason") or ""),
            related_job_id=str(payload.get("related_job_id") or ""),
            draft_id=str(payload.get("draft_id") or ""),
            risk=str(payload.get("risk") or "medium"),
            status=str(payload.get("status") or "pending"),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "target_type": self.target_type,
            "name": self.name,
            "role": self.role,
            "company": self.company,
            "profile_url": self.profile_url,
            "reason": self.reason,
            "related_job_id": self.related_job_id,
            "draft_id": self.draft_id,
            "risk": self.risk,
            "status": self.status,
            "metadata": dict(self.metadata),
        }


@dataclass
class TargetManifest:
    manifest_id: str
    scenario: str
    platform: str
    action: str
    targets: list[ManifestTarget]
    max_actions: int
    created_from_evidence_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TargetManifest":
        return cls(
            manifest_id=str(payload["manifest_id"]),
            scenario=str(payload["scenario"]),
            platform=str(payload["platform"]),
            action=str(payload["action"]),
            targets=[ManifestTarget.from_dict(item) for item in payload.get("targets", [])],
            max_actions=int(payload.get("max_actions") or len(payload.get("targets", []))),
            created_from_evidence_ids=[str(item) for item in payload.get("created_from_evidence_ids", [])],
            metadata=dict(payload.get("metadata") or {}),
        )

    def target_by_id(self, target_id: str) -> ManifestTarget | None:
        for target in self.targets:
            if target.target_id == target_id:
                return target
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "scenario": self.scenario,
            "platform": self.platform,
            "action": self.action,
            "targets": [target.to_dict() for target in self.targets],
            "max_actions": self.max_actions,
            "created_from_evidence_ids": list(self.created_from_evidence_ids),
            "metadata": dict(self.metadata),
        }


@dataclass
class ExecutionTrace:
    trace_id: str
    grant_id: str
    manifest_id: str
    target_id: str
    action: str
    status: str
    started_at: datetime
    finished_at: datetime
    result_summary: str
    evidence_ids: list[str]
    budget_after: dict[str, int]
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExecutionTrace":
        started = parse_datetime(payload.get("started_at")) or datetime.now(timezone.utc)
        finished = parse_datetime(payload.get("finished_at")) or started
        return cls(
            trace_id=str(payload["trace_id"]),
            grant_id=str(payload["grant_id"]),
            manifest_id=str(payload.get("manifest_id") or ""),
            target_id=str(payload.get("target_id") or ""),
            action=str(payload["action"]),
            status=str(payload.get("status") or "completed"),
            started_at=started,
            finished_at=finished,
            result_summary=str(payload.get("result_summary") or ""),
            evidence_ids=[str(item) for item in payload.get("evidence_ids", [])],
            budget_after=dict(payload.get("budget_after") or {}),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "grant_id": self.grant_id,
            "manifest_id": self.manifest_id,
            "target_id": self.target_id,
            "action": self.action,
            "status": self.status,
            "started_at": iso_datetime(self.started_at),
            "finished_at": iso_datetime(self.finished_at),
            "result_summary": self.result_summary,
            "evidence_ids": list(self.evidence_ids),
            "budget_after": dict(self.budget_after),
            "metadata": dict(self.metadata),
        }


@dataclass
class AutomationDecision:
    allowed: bool
    reasons: list[str]
    stop_condition: str | None
    grant_id: str
    manifest_id: str
    target_id: str
    action: str
    scenario: str
    platform: str
    surface: str
    automation_level: str
    budget: dict[str, int]
    target: dict[str, Any] | None = None
    evidence_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AutomationDecision":
        return cls(
            allowed=bool(payload.get("allowed")),
            reasons=[str(item) for item in payload.get("reasons", [])],
            stop_condition=payload.get("stop_condition"),
            grant_id=str(payload.get("grant_id") or ""),
            manifest_id=str(payload.get("manifest_id") or ""),
            target_id=str(payload.get("target_id") or ""),
            action=str(payload.get("action") or ""),
            scenario=str(payload.get("scenario") or ""),
            platform=str(payload.get("platform") or ""),
            surface=str(payload.get("surface") or ""),
            automation_level=str(payload.get("automation_level") or ""),
            budget=dict(payload.get("budget") or {}),
            target=dict(payload["target"]) if isinstance(payload.get("target"), dict) else None,
            evidence_ids=[str(item) for item in payload.get("evidence_ids", [])],
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "stop_condition": self.stop_condition,
            "grant_id": self.grant_id,
            "manifest_id": self.manifest_id,
            "target_id": self.target_id,
            "action": self.action,
            "scenario": self.scenario,
            "platform": self.platform,
            "surface": self.surface,
            "automation_level": self.automation_level,
            "budget": dict(self.budget),
            "target": dict(self.target) if self.target else None,
            "evidence_ids": list(self.evidence_ids),
            "metadata": dict(self.metadata),
        }
