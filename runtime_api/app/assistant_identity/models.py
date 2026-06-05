from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AssistantIdentity:
    identity_id: str
    kind: str
    display_name: str
    address: str
    capabilities: list[str] = field(default_factory=list)
    status: str = "configured"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AssistantCredentialRef:
    identity_id: str
    provider: str
    encrypted_ref: str
    status: str = "configured"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        safe = asdict(self)
        safe["encrypted_ref"] = "[stored-locally]"
        return safe
