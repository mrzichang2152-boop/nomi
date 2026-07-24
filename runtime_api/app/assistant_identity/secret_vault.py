from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.assistant_identity.models import AssistantCredentialRef
from app.assistant_identity.repository import AssistantCredentialRepository


class SecretVaultError(RuntimeError):
    pass


class SecretVaultUnavailable(SecretVaultError):
    pass


class SecretVaultIntegrityError(SecretVaultError):
    pass


class SecretVaultNotFound(SecretVaultError):
    pass


@dataclass(frozen=True)
class SecretValue:
    _value: str = field(repr=False)

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "SecretValue([stored-locally])"

    def __str__(self) -> str:
        return "[stored-locally]"


def _decode_master_key(value: bytes | str | None) -> bytes:
    if value is None or value == b"" or value == "":
        raise SecretVaultUnavailable("secret_vault_unavailable")
    if isinstance(value, bytes):
        key = value
    else:
        try:
            key = base64.urlsafe_b64decode(value.encode("ascii"))
        except (ValueError, UnicodeError) as exc:
            raise SecretVaultUnavailable("secret_vault_invalid_master_key") from exc
    if len(key) != 32:
        raise SecretVaultUnavailable("secret_vault_invalid_master_key")
    return key


def master_key_from_environment() -> bytes:
    return _decode_master_key(os.getenv("NOMI_SECRET_MASTER_KEY", ""))


class AssistantIdentitySecretVault:
    _SCHEMA_VERSION = 1
    _ALGORITHM = "AES-256-GCM"

    def __init__(
        self,
        *,
        repository: AssistantCredentialRepository,
        master_key: bytes | str | None,
    ) -> None:
        self.repository = repository
        self._key = _decode_master_key(master_key)

    def public_status(self) -> dict[str, object]:
        return {"available": True, "error_code": ""}

    @classmethod
    def _aad(cls, identity_id: str, provider: str, credential_name: str) -> bytes:
        return (
            f"nomi-assistant-secret-v{cls._SCHEMA_VERSION}\0"
            f"{identity_id}\0{provider}\0{credential_name}"
        ).encode("utf-8")

    def put(
        self,
        *,
        identity_id: str,
        provider: str,
        credential_name: str,
        value: str,
    ) -> dict[str, object]:
        normalized_identity = identity_id.strip()
        normalized_provider = provider.strip()
        normalized_name = credential_name.strip()
        if not normalized_identity or not normalized_provider or not normalized_name:
            raise ValueError("secret_identity_provider_and_name_required")
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._key).encrypt(
            nonce,
            value.encode("utf-8"),
            self._aad(normalized_identity, normalized_provider, normalized_name),
        )
        envelope = json.dumps(
            {
                "algorithm": self._ALGORITHM,
                "schema_version": self._SCHEMA_VERSION,
                "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
                "ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self.repository.put(
            AssistantCredentialRef(
                identity_id=normalized_identity,
                provider=normalized_provider,
                encrypted_ref=envelope,
                status="active",
                metadata={
                    "credential_name": normalized_name,
                    "algorithm": self._ALGORITHM,
                    "schema_version": self._SCHEMA_VERSION,
                },
            )
        )
        return {"stored": True, "provider": normalized_provider}

    def replace(self, **kwargs: str) -> dict[str, object]:
        return self.put(**kwargs)

    def get(
        self,
        *,
        identity_id: str,
        provider: str,
        credential_name: str,
    ) -> SecretValue:
        record = self.repository.get(identity_id, provider)
        if record is None:
            raise SecretVaultNotFound("assistant_secret_not_found")
        try:
            envelope = json.loads(record.encrypted_ref)
            if (
                envelope.get("algorithm") != self._ALGORITHM
                or int(envelope.get("schema_version")) != self._SCHEMA_VERSION
            ):
                raise ValueError("unsupported_secret_envelope")
            nonce = base64.urlsafe_b64decode(str(envelope["nonce"]).encode("ascii"))
            ciphertext = base64.urlsafe_b64decode(
                str(envelope["ciphertext"]).encode("ascii")
            )
            plaintext = AESGCM(self._key).decrypt(
                nonce,
                ciphertext,
                self._aad(identity_id, provider, credential_name),
            )
            return SecretValue(plaintext.decode("utf-8"))
        except (InvalidTag, KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise SecretVaultIntegrityError("assistant_secret_integrity_check_failed") from exc

    def delete(self, *, identity_id: str, provider: str) -> bool:
        return self.repository.delete(identity_id, provider)


class UnavailableAssistantIdentitySecretVault:
    def __init__(self, *, repository: AssistantCredentialRepository) -> None:
        self.repository = repository

    def public_status(self) -> dict[str, object]:
        return {
            "available": False,
            "error_code": "secret_vault_unavailable",
        }

    @staticmethod
    def _raise() -> None:
        raise SecretVaultUnavailable("secret_vault_unavailable")

    def put(self, **_: str) -> dict[str, object]:
        self._raise()

    def replace(self, **_: str) -> dict[str, object]:
        self._raise()

    def get(self, **_: str) -> SecretValue:
        self._raise()

    def delete(self, **_: str) -> bool:
        self._raise()


def build_secret_vault(
    *,
    repository: AssistantCredentialRepository,
    master_key: bytes | str | None,
) -> AssistantIdentitySecretVault | UnavailableAssistantIdentitySecretVault:
    try:
        return AssistantIdentitySecretVault(
            repository=repository,
            master_key=master_key,
        )
    except SecretVaultUnavailable:
        return UnavailableAssistantIdentitySecretVault(repository=repository)
