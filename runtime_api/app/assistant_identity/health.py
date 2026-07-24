from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.assistant_identity.lifecycle import redacted_error_code
from app.assistant_identity.models import AssistantIdentity, AssistantIdentityHealthCheck
from app.assistant_identity.repository import AssistantIdentityHealthRepository


_CHECK_TYPES = {"credentials", "profile", "inbound", "outbound", "webhook"}
_CHECK_STATUSES = {"passed", "degraded", "failed"}
_SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "client_secret",
    "secret",
}


def _redact_details(value: Any, key_hint: str = "") -> Any:
    if key_hint.lower() in _SENSITIVE_KEYS:
        return "[redacted]"
    if isinstance(value, dict):
        return {str(key): _redact_details(item, str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_details(item, key_hint) for item in value]
    return value


class AssistantIdentityHealthService:
    def __init__(self, repository: AssistantIdentityHealthRepository) -> None:
        self.repository = repository

    def record(
        self,
        identity_id: str,
        check_type: str,
        status: str,
        *,
        latency_ms: int | None = None,
        error_code: str = "",
        details: dict[str, Any] | None = None,
    ) -> AssistantIdentityHealthCheck:
        normalized_type = check_type.strip().lower()
        normalized_status = status.strip().lower()
        if normalized_type not in _CHECK_TYPES:
            raise ValueError("unsupported_assistant_identity_health_check")
        if normalized_status not in _CHECK_STATUSES:
            raise ValueError("unsupported_assistant_identity_health_status")
        normalized_error = ""
        if normalized_status != "passed":
            normalized_error = redacted_error_code(
                error_code,
                fallback="health_check_failed",
            )
        return self.repository.append(
            AssistantIdentityHealthCheck(
                check_id=str(uuid4()),
                identity_id=identity_id,
                check_type=normalized_type,
                status=normalized_status,
                latency_ms=latency_ms,
                error_code=normalized_error,
                details=_redact_details(details or {}),
            )
        )

    def history(self, identity_id: str) -> list[dict[str, Any]]:
        return [check.to_dict() for check in self.repository.list(identity_id)]

    def current(self, identity: AssistantIdentity) -> dict[str, Any]:
        history = self.repository.list(identity.identity_id)
        latest: dict[str, AssistantIdentityHealthCheck] = {}
        for check in history:
            latest.setdefault(check.check_type, check)
        checks = {key: check.status for key, check in latest.items()}
        missing_core = [key for key in ("credentials", "profile") if key not in latest]
        capability_requirements: list[str] = []
        if "receive" in identity.capabilities:
            capability_requirements.append("inbound")
        if "send" in identity.capabilities:
            capability_requirements.append("outbound")
        missing_capability_checks = [
            key for key in capability_requirements if key not in latest
        ]
        core_verified = not missing_core and all(
            latest[key].status == "passed" for key in ("credentials", "profile")
        )
        unhealthy_checks = [
            key for key, check in latest.items() if check.status != "passed"
        ]

        if identity.status not in {"connected", "degraded"}:
            derived_status = identity.status
            healthy = False
        elif missing_core or missing_capability_checks or unhealthy_checks:
            derived_status = "degraded"
            healthy = False
        else:
            derived_status = "connected"
            healthy = core_verified

        return {
            "identity_id": identity.identity_id,
            "kind": identity.kind,
            "status": derived_status,
            "stored_status": identity.status,
            "healthy": healthy,
            "core_identity_verified": core_verified,
            "checks": checks,
            "missing_checks": missing_core,
            "missing_capability_checks": missing_capability_checks,
            "unhealthy_checks": unhealthy_checks,
            "capabilities": list(identity.capabilities),
            "last_verified_at": (
                identity.last_verified_at.isoformat()
                if identity.last_verified_at
                else None
            ),
        }
