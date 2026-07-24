import json
import os
import sys
import base64
import hashlib
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_provider_key_envelope_round_trip_without_plaintext(monkeypatch):
    from app.web_search.config import decrypt_provider_api_key, encrypt_provider_api_key

    monkeypatch.setenv("WEB_SEARCH_CONFIG_ENCRYPTION_SECRET", "unit-test-secret")
    envelope = encrypt_provider_api_key("sk-private-1234")

    assert "sk-private-1234" not in json.dumps(envelope)
    assert envelope["version"] == 1
    assert envelope["algorithm"] == "fernet"
    assert decrypt_provider_api_key(envelope) == "sk-private-1234"


def test_web_search_config_rejects_insecure_default_secret(monkeypatch):
    from app.web_search.config import ProviderSecretError, web_search_config_fernet

    monkeypatch.delenv("WEB_SEARCH_CONFIG_ENCRYPTION_SECRET", raising=False)
    monkeypatch.delenv("RAW_DATA_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("APP_PASSWORD", "par-dev")

    with pytest.raises(ProviderSecretError, match="provider_encryption_secret_required"):
        web_search_config_fernet()


def test_legacy_default_envelope_is_rekeyed_when_secure_secret_is_available(monkeypatch):
    from app.web_search.config import (
        decrypt_provider_api_key,
        migrate_legacy_provider_secrets,
    )

    monkeypatch.setenv("WEB_SEARCH_CONFIG_ENCRYPTION_SECRET", "new-secure-secret")
    legacy_digest = hashlib.sha256(
        "nomi:web-search-provider-key:v1:par-dev".encode("utf-8")
    ).digest()
    legacy_fernet = Fernet(base64.urlsafe_b64encode(legacy_digest))
    legacy_envelope = {
        "version": 1,
        "algorithm": "fernet",
        "ciphertext": legacy_fernet.encrypt(b"legacy-provider-key").decode("utf-8"),
    }
    conn = ConfigConn(
        provider_rows=[provider_row("bocha", legacy_envelope)]
    )

    migrated = migrate_legacy_provider_secrets(conn)

    update = next(
        (item for item in conn.executed if "UPDATE web_search_provider_configs" in item[0]),
        None,
    )
    assert migrated == 1
    assert update is not None
    new_envelope = json.loads(update[1][0])
    assert new_envelope != legacy_envelope
    assert decrypt_provider_api_key(new_envelope) == "legacy-provider-key"


def test_provider_key_envelope_rejects_wrong_secret(monkeypatch):
    from app.web_search.config import ProviderSecretError, decrypt_provider_api_key, encrypt_provider_api_key

    monkeypatch.setenv("WEB_SEARCH_CONFIG_ENCRYPTION_SECRET", "first-secret")
    envelope = encrypt_provider_api_key("sk-private-1234")
    monkeypatch.setenv("WEB_SEARCH_CONFIG_ENCRYPTION_SECRET", "different-secret")

    with pytest.raises(ProviderSecretError):
        decrypt_provider_api_key(envelope)


def test_public_provider_setting_only_exposes_hint():
    from app.web_search.config import public_provider_setting

    public = public_provider_setting(
        provider="exa",
        api_key="sk-private-1234",
        source="database",
        enabled=True,
        connection_status="healthy",
    )

    assert public["configured"] is True
    assert public["key_hint"] == "1234"
    assert public["config_source"] == "database"
    assert "api_key" not in public
    assert "encrypted_api_key" not in public
    assert "sk-private-1234" not in json.dumps(public)


def test_short_provider_key_is_fully_hidden():
    from app.web_search.config import provider_key_hint

    assert provider_key_hint("abc") == ""
    assert provider_key_hint("abcd") == "abcd"


class ConfigCursor:
    def __init__(self, rows=None, row=None):
        self.rows = rows or []
        self.row = row

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


class ConfigConn:
    def __init__(self, provider_rows=None, routing_row=None):
        self.provider_rows = provider_rows or []
        self.routing_row = routing_row
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((" ".join(sql.split()), params))
        if "FROM web_search_provider_configs" in sql:
            return ConfigCursor(rows=self.provider_rows)
        if "FROM web_search_routing_config" in sql:
            return ConfigCursor(row=self.routing_row)
        return ConfigCursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


def provider_row(provider, envelope, *, enabled=True, status="healthy"):
    return (
        provider,
        enabled,
        10,
        envelope,
        "ignored-hint",
        status,
        "2026-07-12T08:00:00Z",
        321,
        "",
        "",
        {},
        "2026-07-12T08:00:00Z",
    )


def test_web_search_config_schema_contains_provider_and_routing_tables():
    from app.web_search.config import web_search_provider_config_schema_sql

    sql = "\n".join(web_search_provider_config_schema_sql())

    assert "CREATE TABLE IF NOT EXISTS web_search_provider_configs" in sql
    assert "CREATE TABLE IF NOT EXISTS web_search_routing_config" in sql
    assert "encrypted_api_key JSONB" in sql
    assert "config_version BIGINT" in sql


def test_database_key_overrides_environment_key(monkeypatch):
    from app.web_search.config import encrypt_provider_api_key, resolve_provider_configs

    monkeypatch.setenv("WEB_SEARCH_CONFIG_ENCRYPTION_SECRET", "unit-test-secret")
    monkeypatch.setenv("EXA_API_KEY", "env-exa-key")
    conn = ConfigConn(provider_rows=[provider_row("exa", encrypt_provider_api_key("db-exa-key"))])

    configs = resolve_provider_configs(conn)

    assert configs["exa"].api_key == "db-exa-key"
    assert configs["exa"].config_source == "database"
    assert configs["exa"].connection_status == "healthy"


def test_environment_key_is_used_when_database_key_is_absent(monkeypatch):
    from app.web_search.config import resolve_provider_configs

    monkeypatch.setenv("TAVILY_API_KEY", "env-tavily-key")
    conn = ConfigConn()

    configs = resolve_provider_configs(conn)

    assert configs["tavily"].api_key == "env-tavily-key"
    assert configs["tavily"].config_source == "environment"
    assert configs["tavily"].connection_status == "untested"


def test_environment_key_preserves_persisted_invalid_status(monkeypatch):
    from app.web_search.config import resolve_provider_configs
    from app.web_search.router import eligible_provider_slugs

    monkeypatch.setenv("TAVILY_API_KEY", "env-tavily-key")
    conn = ConfigConn(
        provider_rows=[provider_row("tavily", {}, status="invalid_key")]
    )

    configs = resolve_provider_configs(conn)

    assert configs["tavily"].config_source == "environment"
    assert configs["tavily"].connection_status == "invalid_key"
    assert "tavily" not in eligible_provider_slugs(configs)


def test_deleted_database_key_reveals_environment_fallback(monkeypatch):
    from app.web_search.config import resolve_provider_configs

    monkeypatch.setenv("BOCHA_API_KEY", "env-bocha-key")
    conn = ConfigConn(provider_rows=[provider_row("bocha", {}, status="not_configured")])

    configs = resolve_provider_configs(conn)

    assert configs["bocha"].api_key == "env-bocha-key"
    assert configs["bocha"].config_source == "environment"
    assert configs["bocha"].configured is True


def test_routing_config_defaults_when_row_is_absent():
    from app.web_search.config import load_routing_config

    routing = load_routing_config(ConfigConn())

    assert routing.strategy == "smart"
    assert routing.fallback_order == ["exa", "tavily", "bocha"]
    assert routing.config_version == 1


class ApiConfigConn(ConfigConn):
    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        self.executed.append((normalized, params))
        if "FROM web_search_provider_configs" in normalized:
            return ConfigCursor(rows=self.provider_rows)
        if "FROM web_search_routing_config" in normalized:
            return ConfigCursor(row=self.routing_row)
        if "RETURNING config_version" in normalized:
            return ConfigCursor(row=(7,))
        return ConfigCursor()


class MutableApiConfigConn(ApiConfigConn):
    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        if (
            "INSERT INTO web_search_provider_configs" in normalized
            and "encrypted_api_key = '{}'::jsonb" in normalized
        ):
            provider = str(params[0])
            remaining = [row for row in self.provider_rows if row[0] != provider]
            remaining.append(provider_row(provider, {}, status="not_configured"))
            self.provider_rows = remaining
        return super().execute(sql, params)


def test_settings_list_never_returns_plaintext_or_ciphertext(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("WEB_SEARCH_CONFIG_ENCRYPTION_SECRET", "unit-test-secret")
    monkeypatch.setenv("TAVILY_API_KEY", "env-tavily-secret")
    from app import main
    from app.web_search.config import encrypt_provider_api_key

    envelope = encrypt_provider_api_key("db-exa-secret")
    conn = ApiConfigConn(
        provider_rows=[provider_row("exa", envelope)],
        routing_row=("smart", ["exa", "tavily", "bocha"], 6, "2026-07-12T08:00:00Z"),
    )
    monkeypatch.setattr(main, "db", lambda: conn)

    response = TestClient(main.app).get(
        "/api/web-search/settings",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["strategy"] == "smart"
    assert payload["config_version"] == 6
    assert {item["provider"] for item in payload["providers"]} == {"exa", "tavily", "bocha"}
    exa = next(item for item in payload["providers"] if item["provider"] == "exa")
    tavily = next(item for item in payload["providers"] if item["provider"] == "tavily")
    assert exa["key_hint"] == "cret"
    assert exa["config_source"] == "database"
    assert tavily["config_source"] == "environment"
    assert "db-exa-secret" not in response.text
    assert "env-tavily-secret" not in response.text
    assert envelope["ciphertext"] not in response.text
    assert all("last_error_message" not in item for item in payload["providers"])


def test_save_tests_candidate_before_persisting(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("WEB_SEARCH_CONFIG_ENCRYPTION_SECRET", "unit-test-secret")
    from app import main

    conn = ApiConfigConn(routing_row=("smart", ["exa", "tavily", "bocha"], 6, None))
    monkeypatch.setattr(main, "db", lambda: conn)
    monkeypatch.setattr(
        main,
        "test_provider_connection",
        lambda provider, api_key: {
            "status": "healthy",
            "latency_ms": 245,
            "result_count": 1,
            "error_type": "",
            "error_message": "",
        },
        raising=False,
    )
    invalidations = []
    monkeypatch.setattr(main, "invalidate_web_search_runtime", lambda version: invalidations.append(version), raising=False)

    response = TestClient(main.app).put(
        "/api/web-search/settings/exa",
        headers={"x-par-password": "secret"},
        json={"api_key": "candidate-exa-key", "enabled": True},
    )

    assert response.status_code == 200
    assert response.json()["key_hint"] == "-key"
    assert response.json()["connection_status"] == "healthy"
    assert "candidate-exa-key" not in response.text
    insert = next((item for item in conn.executed if "INSERT INTO web_search_provider_configs" in item[0]), None)
    assert insert is not None
    assert "candidate-exa-key" not in json.dumps(insert[1], default=str)
    assert invalidations == [7]


def test_invalid_candidate_does_not_replace_old_key(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    conn = ApiConfigConn(routing_row=("smart", ["exa", "tavily", "bocha"], 6, None))
    monkeypatch.setattr(main, "db", lambda: conn)
    monkeypatch.setattr(
        main,
        "test_provider_connection",
        lambda provider, api_key: {
            "status": "invalid_key",
            "latency_ms": 91,
            "result_count": 0,
            "error_type": "provider_auth_failed",
            "error_message": "Authentication failed.",
        },
        raising=False,
    )

    response = TestClient(main.app).put(
        "/api/web-search/settings/exa",
        headers={"x-par-password": "secret"},
        json={"api_key": "wrong-key", "enabled": True},
    )

    assert response.status_code == 422
    assert "wrong-key" not in response.text
    assert not any("INSERT INTO web_search_provider_configs" in sql for sql, _ in conn.executed)


def test_overlong_candidate_key_is_not_echoed_by_validation_response(monkeypatch):
    from app import main

    monkeypatch.setenv("APP_PASSWORD", "secret")
    candidate = "sk-" + "x" * 2100

    response = TestClient(main.app).put(
        "/api/web-search/settings/exa",
        headers={"x-par-password": "secret"},
        json={"api_key": candidate, "enabled": True},
    )

    assert response.status_code == 422
    assert candidate not in response.text


def test_non_object_candidate_body_is_not_echoed_by_validation_response(monkeypatch):
    from app import main

    monkeypatch.setenv("APP_PASSWORD", "secret")
    candidate = "sk-array-body-must-not-be-echoed-1234567890"

    response = TestClient(main.app).put(
        "/api/web-search/settings/exa",
        headers={"x-par-password": "secret"},
        json=[candidate],
    )

    assert response.status_code == 422
    assert candidate not in response.text


def test_routing_order_requires_all_three_unique_slugs(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    response = TestClient(main.app).patch(
        "/api/web-search/settings/routing",
        headers={"x-par-password": "secret"},
        json={"strategy": "smart", "fallback_order": ["exa", "exa", "bocha"]},
    )

    assert response.status_code == 422


def test_test_saved_provider_updates_health_without_changing_key(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("WEB_SEARCH_CONFIG_ENCRYPTION_SECRET", "unit-test-secret")
    from app import main
    from app.web_search.config import encrypt_provider_api_key

    envelope = encrypt_provider_api_key("stored-bocha-key")
    conn = ApiConfigConn(
        provider_rows=[provider_row("bocha", envelope, status="untested")],
        routing_row=("smart", ["exa", "tavily", "bocha"], 6, None),
    )
    monkeypatch.setattr(main, "db", lambda: conn)
    tested = []
    monkeypatch.setattr(
        main,
        "test_provider_connection",
        lambda provider, api_key: tested.append((provider, api_key))
        or {
            "status": "healthy",
            "latency_ms": 188,
            "result_count": 1,
            "error_type": "",
            "error_message": "",
        },
    )
    monkeypatch.setattr(main, "invalidate_web_search_runtime", lambda version: None)

    response = TestClient(main.app).post(
        "/api/web-search/settings/bocha/test",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    assert tested == [("bocha", "stored-bocha-key")]
    assert response.json()["status"] == "healthy"
    health_write = next(
        item for item in conn.executed if "INSERT INTO web_search_provider_configs" in item[0]
    )
    assert "encrypted_api_key" not in health_write[0]
    assert envelope["ciphertext"] not in json.dumps(health_write[1], default=str)


def test_enable_requires_effective_key(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    from app import main

    conn = ApiConfigConn(routing_row=("smart", ["exa", "tavily", "bocha"], 6, None))
    monkeypatch.setattr(main, "db", lambda: conn)

    response = TestClient(main.app).patch(
        "/api/web-search/settings/exa",
        headers={"x-par-password": "secret"},
        json={"enabled": True},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "provider_not_configured"
    assert not any("INSERT INTO web_search_provider_configs" in sql for sql, _ in conn.executed)


def test_delete_database_key_falls_back_to_environment(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("WEB_SEARCH_CONFIG_ENCRYPTION_SECRET", "unit-test-secret")
    monkeypatch.setenv("TAVILY_API_KEY", "environment-tavily-key")
    from app import main
    from app.web_search.config import encrypt_provider_api_key

    conn = MutableApiConfigConn(
        provider_rows=[provider_row("tavily", encrypt_provider_api_key("database-tavily-key"))],
        routing_row=("smart", ["exa", "tavily", "bocha"], 6, None),
    )
    monkeypatch.setattr(main, "db", lambda: conn)
    monkeypatch.setattr(main, "invalidate_web_search_runtime", lambda version: None)

    response = TestClient(main.app).delete(
        "/api/web-search/settings/tavily/key",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is True
    assert payload["config_source"] == "environment"
    assert payload["key_hint"] == "-key"
    assert "database-tavily-key" not in response.text
    assert "environment-tavily-key" not in response.text


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("get", "/api/web-search/settings", None),
        ("put", "/api/web-search/settings/exa", {"api_key": "candidate-key"}),
        ("post", "/api/web-search/settings/exa/test", None),
        ("patch", "/api/web-search/settings/exa", {"enabled": False}),
        ("delete", "/api/web-search/settings/exa/key", None),
    ],
)
def test_web_search_settings_endpoints_require_authentication(monkeypatch, method, path, json_body):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    response = TestClient(main.app).request(method, path, json=json_body)

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("message", "error_type", "expected_status", "expected_error_type"),
    [
        ("HTTP 401 unauthorized", "exa_request_failed", "invalid_key", "provider_auth_failed"),
        ("HTTP 429 rate limit", "tavily_request_failed", "rate_limited", "provider_rate_limited"),
        ("request timed out", "bocha_request_failed", "timeout", "provider_test_timeout"),
        ("malformed payload", "exa_invalid_response", "provider_error", "provider_invalid_response"),
    ],
)
def test_provider_connection_normalizes_provider_failures(
    monkeypatch,
    message,
    error_type,
    expected_status,
    expected_error_type,
):
    from app.web_search import config
    from app.web_search.providers.base import WebSearchProviderError

    class FailingProvider:
        def search(self, request):
            raise WebSearchProviderError(message, error_type=error_type)

    monkeypatch.setattr(config, "build_provider_from_key", lambda provider, api_key: FailingProvider())

    result = config.test_provider_connection("exa", "candidate-secret")

    assert result["status"] == expected_status
    assert result["error_type"] == expected_error_type
    assert result["result_count"] == 0


def test_provider_connection_redacts_secret_fragments(monkeypatch):
    from app.web_search import config
    from app.web_search.providers.base import WebSearchProviderError

    leaked_secret = "sk-super-private-provider-key-1234567890"

    class LeakingProvider:
        def search(self, request):
            raise WebSearchProviderError(
                f"Authorization Bearer {leaked_secret} failed",
                error_type="exa_request_failed",
            )

    monkeypatch.setattr(config, "build_provider_from_key", lambda provider, api_key: LeakingProvider())

    result = config.test_provider_connection("exa", leaked_secret)

    assert leaked_secret not in json.dumps(result)
    assert result["error_message"] == "Provider connection test failed."


def test_provider_connection_never_exposes_upstream_account_details(monkeypatch):
    from app.web_search import config
    from app.web_search.providers.base import WebSearchProviderError

    upstream_detail = "account tenant-42 has quota 17 and internal region alpha"

    class FailingProvider:
        def search(self, request):
            raise WebSearchProviderError(
                upstream_detail,
                error_type="provider_request_failed",
            )

    monkeypatch.setattr(
        config,
        "build_provider_from_key",
        lambda provider, api_key: FailingProvider(),
    )

    result = config.test_provider_connection("exa", "candidate-secret")

    assert upstream_detail not in json.dumps(result)
    assert result["error_message"] == "Provider connection test failed."


def test_provider_connection_normalizes_invalid_response_without_leaking_candidate(monkeypatch):
    from app.web_search import config

    candidate = "sk-candidate-must-not-leak-1234567890"

    class MalformedProvider:
        def search(self, request):
            raise TypeError(f"invalid response while using {candidate}")

    monkeypatch.setattr(
        config,
        "build_provider_from_key",
        lambda provider, api_key: MalformedProvider(),
    )

    result = config.test_provider_connection("exa", candidate)

    assert result["status"] == "provider_error"
    assert result["error_type"] == "provider_invalid_response"
    assert result["result_count"] == 0
    assert candidate not in json.dumps(result)


def test_runtime_manager_reuses_service_for_same_version():
    from app.web_search.runtime import WebSearchRuntimeManager

    builds = []
    manager = WebSearchRuntimeManager(
        version_reader=lambda: 3,
        fallback_version_reader=lambda: 3,
        service_builder=lambda version: builds.append(version) or object(),
    )

    first = manager.get_service()
    second = manager.get_service()

    assert first is second
    assert builds == [3]
    assert manager.current_version == 3


def test_runtime_manager_rebuilds_after_version_changes():
    from app.web_search.runtime import WebSearchRuntimeManager

    state = {"version": 4}
    builds = []
    manager = WebSearchRuntimeManager(
        version_reader=lambda: state["version"],
        fallback_version_reader=lambda: state["version"],
        service_builder=lambda version: builds.append(version) or object(),
    )
    first = manager.get_service()
    state["version"] = 5

    second = manager.get_service()
    third = manager.get_service()

    assert first is not second
    assert second is third
    assert builds == [4, 5]
    assert manager.current_version == 5


def test_runtime_manager_checks_database_when_redis_is_unavailable():
    from app.web_search.runtime import WebSearchRuntimeManager

    builds = []

    def redis_failure():
        raise ConnectionError("redis unavailable")

    manager = WebSearchRuntimeManager(
        version_reader=redis_failure,
        fallback_version_reader=lambda: 8,
        service_builder=lambda version: builds.append(version) or object(),
    )

    manager.get_service()

    assert builds == [8]
    assert manager.current_version == 8


def test_runtime_manager_uses_short_ttl_for_database_version_fallback():
    from app.web_search.runtime import WebSearchRuntimeManager

    now = {"value": 100.0}
    database_versions = iter([8, 9])
    database_reads = []

    def redis_failure():
        raise ConnectionError("redis unavailable")

    def read_database_version():
        version = next(database_versions)
        database_reads.append(version)
        return version

    builds = []
    manager = WebSearchRuntimeManager(
        version_reader=redis_failure,
        fallback_version_reader=read_database_version,
        service_builder=lambda version: builds.append(version) or object(),
        fallback_check_ttl_seconds=2.0,
        monotonic=lambda: now["value"],
    )

    first = manager.get_service()
    now["value"] += 1.0
    second = manager.get_service()
    now["value"] += 2.0
    third = manager.get_service()

    assert first is second
    assert third is not second
    assert database_reads == [8, 9]
    assert builds == [8, 9]


def test_runtime_manager_detects_database_version_newer_than_stale_redis():
    from app.web_search.runtime import WebSearchRuntimeManager

    now = {"value": 100.0}
    database = {"version": 5}
    database_reads = []
    builds = []

    def read_database_version():
        database_reads.append(database["version"])
        return database["version"]

    manager = WebSearchRuntimeManager(
        version_reader=lambda: 4,
        fallback_version_reader=read_database_version,
        service_builder=lambda version: builds.append(version) or object(),
        fallback_check_ttl_seconds=2.0,
        monotonic=lambda: now["value"],
    )

    first = manager.get_service()
    now["value"] += 1.0
    second = manager.get_service()
    database["version"] = 6
    now["value"] += 2.0
    third = manager.get_service()

    assert first is second
    assert third is not second
    assert database_reads == [5, 6]
    assert builds == [5, 6]


def test_runtime_manager_uses_database_as_authority_when_redis_version_is_ahead():
    from app.web_search.runtime import WebSearchRuntimeManager

    now = {"value": 100.0}
    database = {"version": 5}
    builds = []
    manager = WebSearchRuntimeManager(
        version_reader=lambda: 100,
        fallback_version_reader=lambda: database["version"],
        service_builder=lambda version: builds.append(version) or object(),
        fallback_check_ttl_seconds=2.0,
        monotonic=lambda: now["value"],
    )

    first = manager.get_service()
    now["value"] += 1.0
    second = manager.get_service()
    database["version"] = 6
    now["value"] += 2.0
    third = manager.get_service()

    assert first is second
    assert third is not second
    assert builds == [5, 6]


def test_runtime_manager_invalidation_forces_new_service_without_waiting_for_version_reader():
    from app.web_search.runtime import WebSearchRuntimeManager

    builds = []
    database = {"version": 2}
    manager = WebSearchRuntimeManager(
        version_reader=lambda: 2,
        fallback_version_reader=lambda: database["version"],
        service_builder=lambda version: builds.append(version) or object(),
    )
    first = manager.get_service()

    database["version"] = 3
    manager.invalidate(3)
    second = manager.get_service()

    assert first is not second
    assert builds == [2, 3]


def test_runtime_manager_swap_does_not_break_in_flight_service_reference():
    from app.web_search.runtime import WebSearchRuntimeManager

    state = {"version": 1}

    class Service:
        def __init__(self, version):
            self.version = version

        def finish_existing_request(self):
            return self.version

    manager = WebSearchRuntimeManager(
        version_reader=lambda: state["version"],
        fallback_version_reader=lambda: state["version"],
        service_builder=Service,
    )
    in_flight_service = manager.get_service()

    state["version"] = 2
    replacement_service = manager.get_service()

    assert replacement_service is not in_flight_service
    assert replacement_service.version == 2
    assert in_flight_service.finish_existing_request() == 1


def test_main_runtime_invalidation_notifies_manager_and_redis(monkeypatch):
    from app import main

    invalidated = []
    redis_writes = []

    class Manager:
        def invalidate(self, version):
            invalidated.append(version)

    class Redis:
        def set(self, key, value):
            redis_writes.append((key, value))

    monkeypatch.setattr(main, "_WEB_SEARCH_RUNTIME_MANAGER", Manager(), raising=False)
    monkeypatch.setattr(main, "redis_client", lambda: Redis())

    main.invalidate_web_search_runtime(12)

    assert invalidated == [12]
    assert redis_writes == [("nomi:web-search:config-version", 12)]


def test_runtime_provider_status_uses_database_built_service_not_environment(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "true")
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("BOCHA_API_KEY", raising=False)
    from app import main

    class Provider:
        def __init__(self, name):
            self.name = name

    class Service:
        providers = [Provider("tavily"), Provider("exa")]
        config_version = 14

    monkeypatch.setattr(main, "web_search_service", lambda: Service())

    status = main.current_web_search_provider_status()

    assert status["enabled"] is True
    assert status["configured_providers"] == ["tavily", "exa"]
    assert status["config_version"] == 14


def test_runtime_provider_status_degrades_without_breaking_chat(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "true")
    from app import main

    monkeypatch.setattr(
        main,
        "web_search_service",
        lambda: (_ for _ in ()).throw(ConnectionError("configuration database unavailable")),
    )

    status = main.current_web_search_provider_status()

    assert status == {
        "enabled": False,
        "provider_order": [],
        "configured_providers": [],
        "config_version": 0,
        "error": "web_search_configuration_unavailable",
    }
