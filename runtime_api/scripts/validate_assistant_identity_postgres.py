from __future__ import annotations

import json
import os
from contextlib import nullcontext
from dataclasses import replace
from uuid import uuid4

import psycopg

from app.assistant_identity.models import AssistantIdentity
from app.assistant_identity.repository import (
    AssistantIdentityVersionConflict,
    PostgresAssistantCredentialRepository,
    PostgresAssistantIdentityRepository,
)
from app.assistant_identity.schema import assistant_identity_schema_sql
from app.assistant_identity.secret_vault import AssistantIdentitySecretVault


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    identity_id = f"nomi_gmail_validation_{uuid4().hex}"
    checks: dict[str, bool] = {}

    with psycopg.connect(database_url) as connection:
        try:
            for statement in assistant_identity_schema_sql():
                connection.execute(statement)
            repository = PostgresAssistantIdentityRepository(
                connection_factory=lambda: nullcontext(connection)
            )
            created = repository.add_if_missing(
                AssistantIdentity(
                    identity_id=identity_id,
                    kind="assistant_gmail",
                    display_name="Nomi",
                    address="",
                    status="unconfigured",
                    capabilities=["receive", "draft", "send", "thread_reply"],
                )
            )
            checks["starts_unconfigured"] = (
                created.status == "unconfigured" and created.address == ""
            )

            verified = repository.save(
                replace(
                    created,
                    provider="composio_gmail",
                    address="nomi.validation@example.com",
                    status="verifying",
                ),
                expected_version=created.version,
            )
            checks["version_increments"] = verified.version == created.version + 1

            restored = repository.get(identity_id)
            checks["state_round_trips"] = restored == verified

            duplicate = repository.add_if_missing(
                replace(created, address="placeholder@example.com")
            )
            checks["bootstrap_does_not_overwrite"] = (
                duplicate.address == "nomi.validation@example.com"
            )

            try:
                repository.save(
                    replace(created, display_name="stale"),
                    expected_version=created.version,
                )
            except AssistantIdentityVersionConflict as exc:
                checks["stale_write_rejected"] = exc.actual_version == verified.version
            else:
                checks["stale_write_rejected"] = False

            credential_repository = PostgresAssistantCredentialRepository(
                connection_factory=lambda: nullcontext(connection)
            )
            vault = AssistantIdentitySecretVault(
                repository=credential_repository,
                master_key=b"v" * 32,
            )
            plaintext = "postgres-validation-secret"
            vault.put(
                identity_id=identity_id,
                provider="gmail_api",
                credential_name="refresh_token",
                value=plaintext,
            )
            credential = credential_repository.get(identity_id, "gmail_api")
            checks["credential_is_encrypted"] = (
                credential is not None
                and plaintext not in credential.encrypted_ref
                and credential.to_dict()["encrypted_ref"] == "[stored-locally]"
            )
            checks["credential_round_trips"] = (
                vault.get(
                    identity_id=identity_id,
                    provider="gmail_api",
                    credential_name="refresh_token",
                ).reveal()
                == plaintext
            )
        finally:
            connection.rollback()

    payload = {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rolled_back": True,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if payload["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
