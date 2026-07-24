from __future__ import annotations

import base64
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _vault(master_key: bytes = b"k" * 32):
    from app.assistant_identity.repository import InMemoryAssistantCredentialRepository
    from app.assistant_identity.secret_vault import AssistantIdentitySecretVault

    repository = InMemoryAssistantCredentialRepository()
    return AssistantIdentitySecretVault(repository=repository, master_key=master_key), repository


def test_secret_vault_round_trip_uses_fresh_nonce_and_safe_public_status():
    vault, repository = _vault()

    first = vault.put(
        identity_id="nomi_gmail_primary",
        provider="gmail_api",
        credential_name="refresh_token",
        value="secret-value-one",
    )
    first_envelope = repository.get("nomi_gmail_primary", "gmail_api").encrypted_ref
    second = vault.replace(
        identity_id="nomi_gmail_primary",
        provider="gmail_api",
        credential_name="refresh_token",
        value="secret-value-one",
    )
    second_envelope = repository.get("nomi_gmail_primary", "gmail_api").encrypted_ref

    assert first == {"stored": True, "provider": "gmail_api"}
    assert second == {"stored": True, "provider": "gmail_api"}
    assert first_envelope != second_envelope
    assert vault.get(
        identity_id="nomi_gmail_primary",
        provider="gmail_api",
        credential_name="refresh_token",
    ).reveal() == "secret-value-one"


def test_secret_vault_binds_ciphertext_to_identity_provider_and_credential_name():
    from app.assistant_identity.secret_vault import SecretVaultIntegrityError

    vault, repository = _vault()
    vault.put(
        identity_id="nomi_gmail_primary",
        provider="gmail_api",
        credential_name="refresh_token",
        value="bound-secret",
    )
    record = repository.get("nomi_gmail_primary", "gmail_api")
    repository.put(replace(record, identity_id="another_identity"))

    with pytest.raises(SecretVaultIntegrityError):
        vault.get(
            identity_id="another_identity",
            provider="gmail_api",
            credential_name="refresh_token",
        )
    with pytest.raises(SecretVaultIntegrityError):
        vault.get(
            identity_id="nomi_gmail_primary",
            provider="gmail_api",
            credential_name="access_token",
        )


def test_secret_vault_tampering_and_wrong_master_key_fail_closed():
    from app.assistant_identity.secret_vault import (
        AssistantIdentitySecretVault,
        SecretVaultIntegrityError,
    )

    vault, repository = _vault()
    vault.put(
        identity_id="nomi_gmail_primary",
        provider="gmail_api",
        credential_name="refresh_token",
        value="do-not-leak",
    )
    record = repository.get("nomi_gmail_primary", "gmail_api")
    envelope = json.loads(record.encrypted_ref)
    ciphertext = bytearray(base64.urlsafe_b64decode(envelope["ciphertext"]))
    ciphertext[-1] ^= 1
    envelope["ciphertext"] = base64.urlsafe_b64encode(bytes(ciphertext)).decode("ascii")
    repository.put(replace(record, encrypted_ref=json.dumps(envelope, sort_keys=True)))

    with pytest.raises(SecretVaultIntegrityError):
        vault.get(
            identity_id="nomi_gmail_primary",
            provider="gmail_api",
            credential_name="refresh_token",
        )

    clean_vault, clean_repository = _vault()
    clean_vault.put(
        identity_id="nomi_gmail_primary",
        provider="gmail_api",
        credential_name="refresh_token",
        value="do-not-leak",
    )
    wrong_key = AssistantIdentitySecretVault(
        repository=clean_repository,
        master_key=b"w" * 32,
    )
    with pytest.raises(SecretVaultIntegrityError):
        wrong_key.get(
            identity_id="nomi_gmail_primary",
            provider="gmail_api",
            credential_name="refresh_token",
        )


def test_secret_values_and_records_do_not_leak_plaintext_in_repr_or_api_dict():
    vault, repository = _vault()
    secret = "known-test-secret-123"
    vault.put(
        identity_id="nomi_gmail_primary",
        provider="gmail_api",
        credential_name="refresh_token",
        value=secret,
    )
    revealed = vault.get(
        identity_id="nomi_gmail_primary",
        provider="gmail_api",
        credential_name="refresh_token",
    )
    record = repository.get("nomi_gmail_primary", "gmail_api")

    assert secret not in repr(revealed)
    assert secret not in str(revealed)
    assert secret not in repr(record)
    assert secret not in json.dumps(record.to_dict(), ensure_ascii=False)
    assert record.to_dict()["encrypted_ref"] == "[stored-locally]"


def test_secret_vault_delete_removes_stored_value():
    vault, repository = _vault()
    vault.put(
        identity_id="nomi_gmail_primary",
        provider="gmail_api",
        credential_name="refresh_token",
        value="temporary-secret",
    )

    assert vault.delete(identity_id="nomi_gmail_primary", provider="gmail_api") is True
    assert repository.get("nomi_gmail_primary", "gmail_api") is None


def test_missing_master_key_blocks_secret_operations_without_erasing_ciphertext():
    from app.assistant_identity.secret_vault import (
        SecretVaultUnavailable,
        build_secret_vault,
    )

    configured_vault, repository = _vault()
    configured_vault.put(
        identity_id="nomi_gmail_primary",
        provider="gmail_api",
        credential_name="refresh_token",
        value="preserve-me",
    )
    before = repository.get("nomi_gmail_primary", "gmail_api")

    unavailable = build_secret_vault(repository=repository, master_key=None)
    assert unavailable.public_status() == {
        "available": False,
        "error_code": "secret_vault_unavailable",
    }
    with pytest.raises(SecretVaultUnavailable, match="secret_vault_unavailable"):
        unavailable.put(
            identity_id="nomi_gmail_primary",
            provider="gmail_api",
            credential_name="refresh_token",
            value="replacement",
        )

    assert repository.get("nomi_gmail_primary", "gmail_api") == before


def test_missing_master_key_does_not_break_identity_read_api(monkeypatch):
    monkeypatch.delenv("NOMI_SECRET_MASTER_KEY", raising=False)
    monkeypatch.setenv("APP_PASSWORD", "test-password")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")

    from fastapi.testclient import TestClient
    from app.main import app

    response = TestClient(app).get(
        "/api/assistant-identities",
        headers={"x-par-password": "test-password"},
    )

    assert response.status_code == 200
    assert any(
        item["identity_id"] == "nomi_gmail_primary"
        for item in response.json()["identities"]
    )


def test_deployment_contract_exposes_one_stable_assistant_secret_master_key():
    root = Path(__file__).resolve().parents[2]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    env_example = (root / ".env.example").read_text(encoding="utf-8")

    assert "NOMI_SECRET_MASTER_KEY: ${NOMI_SECRET_MASTER_KEY:-}" in compose
    assert "NOMI_SECRET_MASTER_KEY=" in env_example
    assert "openssl rand -base64 32" in env_example
