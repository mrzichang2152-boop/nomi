from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AssistantIdentity:
    identity_id: str
    kind: str
    display_name: str
    address: str
    provider: str = ""
    capabilities: list[str] = field(default_factory=list)
    status: str = "unconfigured"
    metadata: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    last_verified_at: datetime | None = None
    last_error_code: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AssistantCredentialRef:
    identity_id: str
    provider: str
    encrypted_ref: str = field(repr=False)
    status: str = "active"
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        safe = asdict(self)
        safe["encrypted_ref"] = "[stored-locally]"
        safe["expires_at"] = self.expires_at.isoformat() if self.expires_at else None
        safe["updated_at"] = self.updated_at.isoformat()
        return safe


@dataclass(frozen=True)
class AssistantIdentityHealthCheck:
    check_id: str
    identity_id: str
    check_type: str
    status: str
    latency_ms: int | None = None
    error_code: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["checked_at"] = self.checked_at.isoformat()
        return payload
