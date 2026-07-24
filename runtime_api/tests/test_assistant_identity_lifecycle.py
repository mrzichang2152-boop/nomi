import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _service():
    from app.assistant_identity.lifecycle import AssistantIdentityLifecycle
    from app.assistant_identity.registry import AssistantIdentityRegistry
    from app.assistant_identity.repository import InMemoryAssistantIdentityRepository

    repository = InMemoryAssistantIdentityRepository()
    registry = AssistantIdentityRegistry(repository=repository)
    identity = registry.bootstrap_defaults()[0]
    return AssistantIdentityLifecycle(repository), identity


def test_gmail_connection_requires_authorization_and_verification():
    service, identity = _service()

    pending = service.request_authorization(identity.identity_id)
    assert pending.status == "authorization_pending"
    assert pending.address == ""

    verifying = service.begin_verification(identity.identity_id)
    assert verifying.status == "verifying"

    connected = service.provider_verified(
        identity.identity_id,
        provider="composio_gmail",
        address="nomi.real@example.com",
        capabilities=["receive", "draft", "send", "thread_reply"],
    )
    assert connected.status == "connected"
    assert connected.address == "nomi.real@example.com"
    assert connected.provider == "composio_gmail"
    assert connected.last_verified_at is not None
    assert connected.last_error_code == ""


def test_client_cannot_jump_unconfigured_identity_to_connected():
    service, identity = _service()

    with pytest.raises(ValueError, match="invalid_assistant_identity_transition"):
        service.provider_verified(
            identity.identity_id,
            provider="composio_gmail",
            address="nomi.real@example.com",
            capabilities=["send"],
        )


def test_connected_identity_can_degrade_expire_and_disable():
    service, identity = _service()
    service.request_authorization(identity.identity_id)
    service.begin_verification(identity.identity_id)
    service.provider_verified(
        identity.identity_id,
        provider="composio_gmail",
        address="nomi.real@example.com",
        capabilities=["send"],
    )

    degraded = service.mark_degraded(identity.identity_id, "gmail_inbound_stale")
    assert degraded.status == "degraded"
    assert degraded.last_error_code == "gmail_inbound_stale"

    expired = service.mark_expired(identity.identity_id, "gmail_credentials_expired")
    assert expired.status == "expired"
    assert expired.last_error_code == "gmail_credentials_expired"

    disabled = service.disable(identity.identity_id)
    assert disabled.status == "disabled"


def test_disabled_identity_must_reenter_verification_before_connected():
    service, identity = _service()
    disabled = service.disable(identity.identity_id)
    assert disabled.status == "disabled"

    with pytest.raises(ValueError, match="invalid_assistant_identity_transition"):
        service.provider_verified(
            identity.identity_id,
            provider="composio_gmail",
            address="nomi.real@example.com",
            capabilities=["send"],
        )

    verifying = service.enable_for_verification(identity.identity_id)
    assert verifying.status == "verifying"
    connected = service.provider_verified(
        identity.identity_id,
        provider="composio_gmail",
        address="nomi.real@example.com",
        capabilities=["send"],
    )
    assert connected.status == "connected"


def test_failed_verification_stores_only_stable_redacted_error_code():
    service, identity = _service()
    service.request_authorization(identity.identity_id)
    service.begin_verification(identity.identity_id)

    failed = service.verification_failed(
        identity.identity_id,
        "OAuth failed for nomi.real@example.com token=super-secret",
    )

    assert failed.status == "failed"
    assert failed.last_error_code == "provider_verification_failed"
    serialized = str(failed.to_dict())
    assert "nomi.real@example.com" not in serialized
    assert "super-secret" not in serialized


def test_registry_connect_begins_authorization_and_rejects_status_patch():
    from app.assistant_identity.registry import AssistantIdentityRegistry

    registry = AssistantIdentityRegistry()
    pending = registry.connect_kind("assistant_gmail")
    assert pending.status == "authorization_pending"

    with pytest.raises(ValueError, match="status_is_provider_managed"):
        registry.update("nomi_gmail_primary", status="connected")
