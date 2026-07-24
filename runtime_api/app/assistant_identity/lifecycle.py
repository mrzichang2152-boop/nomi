from __future__ import annotations

import re
from dataclasses import replace
from typing import Iterable

from app.assistant_identity.models import AssistantIdentity, _utcnow
from app.assistant_identity.audit import AssistantIdentityAuditor
from app.assistant_identity.repository import AssistantIdentityRepository


_STABLE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{2,79}$")


def redacted_error_code(value: str, *, fallback: str) -> str:
    normalized = str(value or "").strip().lower()
    if _STABLE_ERROR_CODE.fullmatch(normalized):
        return normalized
    return fallback


class AssistantIdentityLifecycle:
    def __init__(
        self,
        repository: AssistantIdentityRepository,
        *,
        auditor: AssistantIdentityAuditor | None = None,
    ) -> None:
        self.repository = repository
        self.auditor = auditor or AssistantIdentityAuditor()

    def _identity(self, identity_id: str) -> AssistantIdentity:
        identity = self.repository.get(identity_id)
        if identity is None:
            raise KeyError(identity_id)
        return identity

    def _transition(
        self,
        identity_id: str,
        *,
        allowed_from: Iterable[str],
        target: str,
        error_code: str = "",
        provider: str | None = None,
        address: str | None = None,
        capabilities: list[str] | None = None,
        verified: bool = False,
        action: str = "identity.transitioned",
        actor: str = "system",
    ) -> AssistantIdentity:
        identity = self._identity(identity_id)
        allowed = set(allowed_from)
        if identity.status not in allowed:
            raise ValueError(
                f"invalid_assistant_identity_transition:{identity.status}->{target}"
            )
        updated = replace(
            identity,
            status=target,
            provider=identity.provider if provider is None else provider,
            address=identity.address if address is None else address,
            capabilities=(
                list(identity.capabilities)
                if capabilities is None
                else list(capabilities)
            ),
            last_verified_at=_utcnow() if verified else identity.last_verified_at,
            last_error_code=error_code,
        )
        stored = self.repository.save(updated, expected_version=identity.version)
        self.auditor.record(
            action,
            actor=actor,
            identity_id=stored.identity_id,
            status=stored.status,
            policy_result="transition_allowed",
            payload={
                "from_status": identity.status,
                "to_status": stored.status,
                "provider": stored.provider,
                "capability_count": len(stored.capabilities),
                "error_code": stored.last_error_code,
            },
        )
        return stored

    def request_authorization(self, identity_id: str) -> AssistantIdentity:
        return self._transition(
            identity_id,
            allowed_from={
                "unconfigured",
                "authorization_pending",
                "expired",
                "failed",
                "degraded",
                "connected",
            },
            target="authorization_pending",
            action="identity.authorization_requested",
            actor="local_owner",
        )

    def begin_verification(self, identity_id: str) -> AssistantIdentity:
        return self._transition(
            identity_id,
            allowed_from={"authorization_pending", "expired", "failed", "degraded", "connected"},
            target="verifying",
            action="identity.verification_started",
        )

    def enable_for_verification(self, identity_id: str) -> AssistantIdentity:
        return self._transition(
            identity_id,
            allowed_from={"disabled"},
            target="verifying",
            action="identity.verification_started",
            actor="local_owner",
        )

    def provider_verified(
        self,
        identity_id: str,
        *,
        provider: str,
        address: str,
        capabilities: list[str],
    ) -> AssistantIdentity:
        normalized_provider = provider.strip()
        normalized_address = address.strip()
        if not normalized_provider or not normalized_address:
            raise ValueError("verified_provider_and_address_required")
        return self._transition(
            identity_id,
            allowed_from={"verifying"},
            target="connected",
            provider=normalized_provider,
            address=normalized_address,
            capabilities=capabilities,
            verified=True,
            action="identity.provider_verified",
            actor="provider",
        )

    def verification_failed(self, identity_id: str, error_code: str) -> AssistantIdentity:
        return self._transition(
            identity_id,
            allowed_from={"authorization_pending", "verifying", "degraded"},
            target="failed",
            error_code=redacted_error_code(
                error_code,
                fallback="provider_verification_failed",
            ),
            action="identity.verification_failed",
            actor="provider",
        )

    def mark_degraded(self, identity_id: str, error_code: str) -> AssistantIdentity:
        return self._transition(
            identity_id,
            allowed_from={"connected", "verifying"},
            target="degraded",
            error_code=redacted_error_code(error_code, fallback="provider_degraded"),
            action="identity.degraded",
        )

    def mark_expired(self, identity_id: str, error_code: str) -> AssistantIdentity:
        return self._transition(
            identity_id,
            allowed_from={
                "authorization_pending",
                "verifying",
                "connected",
                "degraded",
                "failed",
            },
            target="expired",
            error_code=redacted_error_code(error_code, fallback="provider_credentials_expired"),
            action="identity.expired",
        )

    def disable(self, identity_id: str) -> AssistantIdentity:
        return self._transition(
            identity_id,
            allowed_from={
                "unconfigured",
                "authorization_pending",
                "verifying",
                "connected",
                "degraded",
                "expired",
                "failed",
            },
            target="disabled",
            action="identity.disabled",
            actor="local_owner",
        )

    def disconnect(self, identity_id: str) -> AssistantIdentity:
        identity = self._identity(identity_id)
        if identity.status not in {
            "unconfigured",
            "authorization_pending",
            "verifying",
            "connected",
            "degraded",
            "expired",
            "failed",
            "disabled",
        }:
            raise ValueError(
                f"invalid_assistant_identity_transition:{identity.status}->unconfigured"
            )
        disconnected = replace(
            identity,
            provider="",
            address="",
            status="unconfigured",
            capabilities=[],
            last_verified_at=None,
            last_error_code="",
        )
        stored = self.repository.save(disconnected, expected_version=identity.version)
        self.auditor.record(
            "identity.disconnected",
            actor="local_owner",
            identity_id=stored.identity_id,
            status=stored.status,
            policy_result="transition_allowed",
            payload={"from_status": identity.status, "to_status": stored.status},
        )
        return stored
