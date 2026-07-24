from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _connected_identity():
    from app.assistant_identity.registry import AssistantIdentityRegistry
    from app.assistant_identity.repository import InMemoryAssistantIdentityRepository

    identity_repository = InMemoryAssistantIdentityRepository()
    registry = AssistantIdentityRegistry(repository=identity_repository)
    identity = registry.bootstrap_defaults()[0]
    registry.lifecycle.request_authorization(identity.identity_id)
    registry.lifecycle.begin_verification(identity.identity_id)
    connected = registry.lifecycle.provider_verified(
        identity.identity_id,
        provider="composio_gmail",
        address="nomi.real@example.com",
        capabilities=["receive", "draft", "send", "thread_reply"],
    )
    return connected


def test_health_checks_are_independent_and_connected_requires_core_checks():
    from app.assistant_identity.health import AssistantIdentityHealthService
    from app.assistant_identity.repository import InMemoryAssistantIdentityHealthRepository

    identity = _connected_identity()
    repository = InMemoryAssistantIdentityHealthRepository()
    service = AssistantIdentityHealthService(repository)
    service.record(identity.identity_id, "credentials", "passed", latency_ms=11)
    service.record(identity.identity_id, "profile", "passed", latency_ms=13)
    service.record(identity.identity_id, "inbound", "passed", latency_ms=17)
    service.record(identity.identity_id, "outbound", "passed", latency_ms=19)

    current = service.current(identity)

    assert current["status"] == "connected"
    assert current["healthy"] is True
    assert current["checks"] == {
        "credentials": "passed",
        "profile": "passed",
        "inbound": "passed",
        "outbound": "passed",
    }


def test_stale_inbound_degrades_connected_gmail_without_claiming_total_failure():
    from app.assistant_identity.health import AssistantIdentityHealthService
    from app.assistant_identity.repository import InMemoryAssistantIdentityHealthRepository

    identity = _connected_identity()
    repository = InMemoryAssistantIdentityHealthRepository()
    service = AssistantIdentityHealthService(repository)
    service.record(identity.identity_id, "credentials", "passed")
    service.record(identity.identity_id, "profile", "passed")
    service.record(
        identity.identity_id,
        "inbound",
        "degraded",
        error_code="gmail_inbound_stale",
    )
    service.record(identity.identity_id, "outbound", "passed")

    current = service.current(identity)

    assert current["status"] == "degraded"
    assert current["healthy"] is False
    assert current["core_identity_verified"] is True
    assert current["checks"]["outbound"] == "passed"
    assert current["checks"]["inbound"] == "degraded"


def test_stored_connected_text_is_not_healthy_without_verification_evidence():
    from app.assistant_identity.health import AssistantIdentityHealthService
    from app.assistant_identity.repository import InMemoryAssistantIdentityHealthRepository

    identity = _connected_identity()
    current = AssistantIdentityHealthService(
        InMemoryAssistantIdentityHealthRepository()
    ).current(identity)

    assert identity.status == "connected"
    assert current["status"] == "degraded"
    assert current["healthy"] is False
    assert current["missing_checks"] == ["credentials", "profile"]


def test_health_history_is_append_only_and_redacts_sensitive_details():
    from app.assistant_identity.health import AssistantIdentityHealthService
    from app.assistant_identity.repository import InMemoryAssistantIdentityHealthRepository

    repository = InMemoryAssistantIdentityHealthRepository()
    service = AssistantIdentityHealthService(repository)
    service.record(
        "nomi_gmail_primary",
        "credentials",
        "failed",
        error_code="OAuth token=secret for nomi.real@example.com",
        details={"access_token": "secret", "provider": "gmail"},
    )
    service.record("nomi_gmail_primary", "credentials", "passed")

    history = service.history("nomi_gmail_primary")

    assert len(history) == 2
    assert history[0]["status"] == "passed"
    assert history[1]["status"] == "failed"
    assert history[1]["error_code"] == "health_check_failed"
    assert history[1]["details"] == {
        "access_token": "[redacted]",
        "provider": "gmail",
    }
    assert "secret" not in str(history)
