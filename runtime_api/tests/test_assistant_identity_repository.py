import sys
from dataclasses import replace
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_gmail_identity_survives_registry_reinstantiation_without_placeholder_overwrite():
    from app.assistant_identity.registry import AssistantIdentityRegistry
    from app.assistant_identity.repository import InMemoryAssistantIdentityRepository

    records = {}
    first_repository = InMemoryAssistantIdentityRepository(records=records)
    first_registry = AssistantIdentityRegistry(repository=first_repository)
    gmail = first_registry.bootstrap_defaults()[0]

    assert gmail.identity_id == "nomi_gmail_primary"
    assert gmail.status == "unconfigured"
    assert gmail.address == ""

    verified = first_repository.save(
        replace(
            gmail,
            provider="composio_gmail",
            address="nomi.real@example.com",
            status="verifying",
        ),
        expected_version=gmail.version,
    )

    second_registry = AssistantIdentityRegistry(
        repository=InMemoryAssistantIdentityRepository(records=records)
    )
    restored = second_registry.bootstrap_defaults()[0]

    assert restored.identity_id == verified.identity_id
    assert restored.provider == "composio_gmail"
    assert restored.address == "nomi.real@example.com"
    assert restored.status == "verifying"
    assert restored.version == 2


def test_repository_rejects_stale_identity_version():
    from app.assistant_identity.repository import (
        AssistantIdentityVersionConflict,
        InMemoryAssistantIdentityRepository,
    )
    from app.assistant_identity.registry import AssistantIdentityRegistry

    repository = InMemoryAssistantIdentityRepository()
    gmail = AssistantIdentityRegistry(repository=repository).bootstrap_defaults()[0]
    repository.save(replace(gmail, display_name="Nomi One"), expected_version=1)

    try:
        repository.save(replace(gmail, display_name="Nomi Stale"), expected_version=1)
    except AssistantIdentityVersionConflict as exc:
        assert exc.identity_id == "nomi_gmail_primary"
        assert exc.expected_version == 1
    else:
        raise AssertionError("repository accepted a stale identity version")


def test_bootstrap_preserves_unrelated_legacy_assistant_identities():
    from app.assistant_identity.models import AssistantIdentity
    from app.assistant_identity.registry import AssistantIdentityRegistry
    from app.assistant_identity.repository import InMemoryAssistantIdentityRepository

    repository = InMemoryAssistantIdentityRepository(
        records={
            "legacy_assistant": AssistantIdentity(
                identity_id="legacy_assistant",
                kind="assistant_phone",
                display_name="Legacy",
                address="+15550000000",
                status="disabled",
                version=7,
            )
        }
    )

    identities = AssistantIdentityRegistry(repository=repository).bootstrap_defaults()

    legacy = next(item for item in identities if item.identity_id == "legacy_assistant")
    assert legacy.display_name == "Legacy"
    assert legacy.status == "disabled"
    assert legacy.version == 7
    assert sum(item.identity_id == "nomi_gmail_primary" for item in identities) == 1


def test_registry_factory_uses_postgres_outside_unit_test_database():
    from app.assistant_identity.registry import build_assistant_identity_registry
    from app.assistant_identity.repository import PostgresAssistantIdentityRepository

    connection_factory = lambda: None
    registry = build_assistant_identity_registry(
        database_url="postgresql://nomi-production",
        connection_factory=connection_factory,
    )

    assert isinstance(registry.repository, PostgresAssistantIdentityRepository)
    assert registry.repository.connection_factory is connection_factory


def test_registry_factory_keeps_unit_tests_database_free():
    from app.assistant_identity.registry import build_assistant_identity_registry
    from app.assistant_identity.repository import InMemoryAssistantIdentityRepository

    registry = build_assistant_identity_registry(
        database_url="postgresql://test",
        connection_factory=lambda: None,
    )

    assert isinstance(registry.repository, InMemoryAssistantIdentityRepository)
