from __future__ import annotations

import os
from dataclasses import replace
from typing import Callable, ContextManager

from app.assistant_identity.lifecycle import AssistantIdentityLifecycle
from app.assistant_identity.audit import AssistantIdentityAuditor
from app.assistant_identity.models import AssistantIdentity
from app.assistant_identity.repository import (
    AssistantIdentityRepository,
    InMemoryAssistantIdentityRepository,
    PostgresAssistantIdentityRepository,
)


ALLOWED_IDENTITY_KINDS = {"assistant_gmail", "assistant_whatsapp", "assistant_phone"}


def build_assistant_identity_registry(
    *,
    database_url: str,
    connection_factory: Callable[[], ContextManager[object]],
    auditor: AssistantIdentityAuditor | None = None,
) -> "AssistantIdentityRegistry":
    if database_url == "postgresql://test":
        return AssistantIdentityRegistry(auditor=auditor)
    return AssistantIdentityRegistry(
        repository=PostgresAssistantIdentityRepository(connection_factory),
        auditor=auditor,
    )


class AssistantIdentityRegistry:
    def __init__(
        self,
        repository: AssistantIdentityRepository | None = None,
        *,
        auditor: AssistantIdentityAuditor | None = None,
    ) -> None:
        self.repository = repository or InMemoryAssistantIdentityRepository()
        self.auditor = auditor or AssistantIdentityAuditor()
        self.lifecycle = AssistantIdentityLifecycle(self.repository, auditor=self.auditor)

    def bootstrap_defaults(self) -> list[AssistantIdentity]:
        defaults = [
                AssistantIdentity(
                    identity_id="nomi_gmail_primary",
                    kind="assistant_gmail",
                    display_name="Nomi",
                    address=os.getenv("ASSISTANT_GMAIL_ADDRESS", ""),
                    provider=os.getenv("ASSISTANT_GMAIL_PROVIDER", ""),
                    capabilities=[],
                    status=os.getenv("ASSISTANT_GMAIL_STATUS", "unconfigured"),
                    metadata={
                        "supported_capabilities": [
                            "receive",
                            "draft",
                            "send",
                            "thread_reply",
                        ]
                    },
                ),
                AssistantIdentity(
                    identity_id="nomi_whatsapp_primary",
                    kind="assistant_whatsapp",
                    display_name="Nomi",
                    address=os.getenv("ASSISTANT_WHATSAPP_NUMBER", ""),
                    capabilities=[],
                    status=os.getenv("ASSISTANT_WHATSAPP_STATUS", "unconfigured"),
                    metadata={
                        "supported_capabilities": [
                            "receive",
                            "send_text",
                            "delivery_receipt",
                        ]
                    },
                ),
                AssistantIdentity(
                    identity_id="nomi_phone_primary",
                    kind="assistant_phone",
                    display_name="Nomi",
                    address=os.getenv("ASSISTANT_PHONE_NUMBER", ""),
                    capabilities=[],
                    status=os.getenv("ASSISTANT_PHONE_STATUS", "unconfigured"),
                    metadata={
                        "supported_capabilities": [
                            "receive_sms",
                            "send_sms",
                            "outbound_call_playback",
                            "inbound_call_greeting",
                            "delivery_receipt",
                            "call_status",
                        ]
                    },
                ),
        ]
        for identity in defaults:
            self.add(identity)
        return self.list()

    def add(self, identity: AssistantIdentity) -> AssistantIdentity:
        if identity.kind not in ALLOWED_IDENTITY_KINDS:
            raise ValueError("Only Nomi-owned identity kinds are allowed.")
        display_name = identity.display_name.strip() or "Nomi"
        normalized = AssistantIdentity(
            identity_id=identity.identity_id.strip(),
            kind=identity.kind.strip(),
            display_name=display_name,
            address=identity.address.strip(),
            capabilities=list(identity.capabilities),
            provider=identity.provider.strip(),
            status=identity.status.strip() or "unconfigured",
            metadata=dict(identity.metadata),
            version=identity.version,
            last_verified_at=identity.last_verified_at,
            last_error_code=identity.last_error_code,
            created_at=identity.created_at,
            updated_at=identity.updated_at,
        )
        return self.repository.add_if_missing(normalized)

    def list(self) -> list[AssistantIdentity]:
        return self.repository.list()

    def get(self, identity_id: str) -> AssistantIdentity | None:
        identity = self.repository.get(identity_id)
        if identity is None:
            self.bootstrap_defaults()
            identity = self.repository.get(identity_id)
        return identity

    def connect_kind(self, kind: str) -> AssistantIdentity:
        if kind not in ALLOWED_IDENTITY_KINDS:
            raise ValueError("Only Nomi-owned identity kinds are allowed.")
        self.bootstrap_defaults()
        for identity in self.repository.list():
            if identity.kind == kind:
                return self.lifecycle.request_authorization(identity.identity_id)
        raise KeyError(kind)

    def update(self, identity_id: str, *, display_name: str | None = None, status: str | None = None) -> AssistantIdentity:
        self.bootstrap_defaults()
        if status is not None:
            raise ValueError("status_is_provider_managed")
        identity = self.repository.get(identity_id)
        if identity is None:
            raise KeyError(identity_id)
        stored = self.repository.save(
            replace(
                identity,
                display_name=display_name if display_name is not None else identity.display_name,
            ),
            expected_version=identity.version,
        )
        self.auditor.record(
            "identity.configuration_updated",
            actor="local_owner",
            identity_id=stored.identity_id,
            status=stored.status,
            policy_result="configuration_valid",
            payload={"display_name_changed": display_name is not None},
        )
        return stored

    def update_profile(
        self,
        identity_id: str,
        *,
        display_name: str | None = None,
        style: dict[str, object] | None = None,
    ) -> AssistantIdentity:
        self.bootstrap_defaults()
        identity = self.repository.get(identity_id)
        if identity is None:
            raise KeyError(identity_id)
        metadata = dict(identity.metadata)
        if style is not None:
            metadata["profile_style"] = dict(style)
        normalized_display_name = identity.display_name
        if display_name is not None:
            normalized_display_name = display_name.strip() or "Nomi"
        stored = self.repository.save(
            replace(
                identity,
                display_name=normalized_display_name,
                metadata=metadata,
            ),
            expected_version=identity.version,
        )
        self.auditor.record(
            "identity.profile_updated",
            actor="local_owner",
            identity_id=stored.identity_id,
            status=stored.status,
            policy_result="profile_valid",
            payload={
                "display_name_changed": display_name is not None,
                "style_keys": sorted(str(key) for key in (style or {}).keys()),
            },
        )
        return stored
