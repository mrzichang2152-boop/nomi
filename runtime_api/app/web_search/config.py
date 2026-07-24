from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.web_search.providers.base import WebSearchProviderError
from app.web_search.providers.bocha import BochaSearchProvider
from app.web_search.providers.exa import ExaSearchProvider
from app.web_search.providers.tavily import TavilySearchProvider
from app.web_search.schema import SearchRequest


SUPPORTED_PROVIDER_SLUGS = ("exa", "tavily", "bocha")
PROVIDER_ENV_KEYS = {
    "exa": "EXA_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "bocha": "BOCHA_API_KEY",
}
DEFAULT_PROVIDER_PRIORITIES = {"exa": 10, "tavily": 20, "bocha": 30}
INSECURE_DEFAULT_ENCRYPTION_SECRETS = {
    "par-dev",
    "par-dev-web-search-config",
}


class ProviderSecretError(ValueError):
    pass


SECRET_FRAGMENT_RE = re.compile(r"(?i)(?:bearer\s+)?(?:sk-|tvly-|exa-)?[a-z0-9_-]{16,}")


@dataclass(frozen=True)
class ProviderConfigRecord:
    provider: str
    enabled: bool
    priority: int
    encrypted_api_key: dict[str, Any]
    key_hint: str
    connection_status: str
    last_tested_at: datetime | str | None
    last_test_latency_ms: int | None
    last_error_type: str
    last_error_message: str
    settings: dict[str, Any]
    updated_at: datetime | str | None


@dataclass(frozen=True)
class ResolvedProviderConfig:
    provider: str
    enabled: bool
    priority: int
    api_key: str
    config_source: str
    connection_status: str
    last_tested_at: datetime | str | None = None
    last_test_latency_ms: int | None = None
    last_error_type: str = ""
    last_error_message: str = ""
    settings: dict[str, Any] | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class RoutingConfig:
    strategy: str
    fallback_order: list[str]
    config_version: int
    updated_at: datetime | str | None = None


def web_search_provider_config_schema_sql() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS web_search_provider_configs (
          provider TEXT PRIMARY KEY,
          enabled BOOLEAN NOT NULL DEFAULT TRUE,
          priority INTEGER NOT NULL DEFAULT 100,
          encrypted_api_key JSONB NOT NULL DEFAULT '{}'::jsonb,
          key_hint TEXT NOT NULL DEFAULT '',
          connection_status TEXT NOT NULL DEFAULT 'not_configured',
          last_tested_at TIMESTAMPTZ,
          last_test_latency_ms INTEGER,
          last_error_type TEXT NOT NULL DEFAULT '',
          last_error_message TEXT NOT NULL DEFAULT '',
          settings JSONB NOT NULL DEFAULT '{}'::jsonb,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          CHECK (provider IN ('exa', 'tavily', 'bocha')),
          CHECK (connection_status IN ('not_configured', 'untested', 'healthy', 'invalid_key', 'rate_limited', 'timeout', 'provider_error'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS web_search_routing_config (
          id TEXT PRIMARY KEY CHECK (id = 'instance'),
          fallback_order TEXT[] NOT NULL DEFAULT ARRAY['exa', 'tavily', 'bocha']::TEXT[],
          strategy TEXT NOT NULL DEFAULT 'smart',
          config_version BIGINT NOT NULL DEFAULT 1,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          CHECK (strategy IN ('smart', 'fixed'))
        )
        """,
        """
        INSERT INTO web_search_routing_config (id)
        VALUES ('instance')
        ON CONFLICT (id) DO NOTHING
        """,
    ]


def web_search_config_fernet() -> Fernet:
    secret = (
        os.getenv("WEB_SEARCH_CONFIG_ENCRYPTION_SECRET")
        or os.getenv("RAW_DATA_ENCRYPTION_KEY")
        or os.getenv("APP_PASSWORD")
    )
    secret = str(secret or "").strip()
    if not secret or secret in INSECURE_DEFAULT_ENCRYPTION_SECRETS:
        raise ProviderSecretError("provider_encryption_secret_required")
    digest = hashlib.sha256(
        f"nomi:web-search-provider-key:v1:{secret}".encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_provider_api_key(api_key: str) -> dict[str, Any]:
    value = str(api_key or "").strip()
    if not value:
        raise ProviderSecretError("api_key_required")
    ciphertext = web_search_config_fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    return {"version": 1, "algorithm": "fernet", "ciphertext": ciphertext}


def decrypt_provider_api_key(envelope: dict[str, Any] | None) -> str:
    payload = envelope if isinstance(envelope, dict) else {}
    if payload.get("version") != 1 or payload.get("algorithm") != "fernet":
        raise ProviderSecretError("unsupported_provider_secret_envelope")
    ciphertext = str(payload.get("ciphertext") or "").strip()
    if not ciphertext:
        raise ProviderSecretError("provider_secret_ciphertext_missing")
    try:
        return web_search_config_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
        raise ProviderSecretError("provider_secret_decryption_failed") from exc


def provider_key_hint(api_key: str) -> str:
    value = str(api_key or "").strip()
    return value[-4:] if len(value) >= 4 else ""


def public_provider_setting(
    provider: str,
    *,
    api_key: str,
    source: str,
    enabled: bool,
    connection_status: str,
    **fields: Any,
) -> dict[str, Any]:
    if provider not in SUPPORTED_PROVIDER_SLUGS:
        raise ValueError("unsupported_web_search_provider")
    safe_source = source if source in {"database", "environment", "none"} else "none"
    result = {
        "provider": provider,
        "enabled": bool(enabled),
        "configured": bool(str(api_key or "").strip()),
        "config_source": safe_source,
        "key_hint": provider_key_hint(api_key),
        "connection_status": str(connection_status or "not_configured"),
    }
    result.update(fields)
    return result


def load_provider_config_records(conn: Any) -> dict[str, ProviderConfigRecord]:
    rows = conn.execute(
        """
        SELECT provider, enabled, priority, encrypted_api_key, key_hint,
               connection_status, last_tested_at, last_test_latency_ms,
               last_error_type, last_error_message, settings, updated_at
        FROM web_search_provider_configs
        ORDER BY priority, provider
        """
    ).fetchall()
    records: dict[str, ProviderConfigRecord] = {}
    for row in rows:
        provider = str(row[0] or "").strip().lower()
        if provider not in SUPPORTED_PROVIDER_SLUGS:
            continue
        records[provider] = ProviderConfigRecord(
            provider=provider,
            enabled=bool(row[1]),
            priority=int(row[2] or DEFAULT_PROVIDER_PRIORITIES[provider]),
            encrypted_api_key=row[3] if isinstance(row[3], dict) else {},
            key_hint=str(row[4] or ""),
            connection_status=str(row[5] or "not_configured"),
            last_tested_at=row[6],
            last_test_latency_ms=int(row[7]) if row[7] is not None else None,
            last_error_type=str(row[8] or ""),
            last_error_message=str(row[9] or ""),
            settings=row[10] if isinstance(row[10], dict) else {},
            updated_at=row[11],
        )
    return records


def migrate_legacy_provider_secrets(conn: Any) -> int:
    try:
        current_fernet = web_search_config_fernet()
    except ProviderSecretError:
        return 0
    legacy_fernets = []
    for secret in INSECURE_DEFAULT_ENCRYPTION_SECRETS:
        digest = hashlib.sha256(
            f"nomi:web-search-provider-key:v1:{secret}".encode("utf-8")
        ).digest()
        legacy_fernets.append(Fernet(base64.urlsafe_b64encode(digest)))

    migrated = 0
    for record in load_provider_config_records(conn).values():
        envelope = record.encrypted_api_key
        ciphertext = str(envelope.get("ciphertext") or "") if envelope else ""
        if (
            not ciphertext
            or envelope.get("version") != 1
            or envelope.get("algorithm") != "fernet"
        ):
            continue
        try:
            current_fernet.decrypt(ciphertext.encode("utf-8"))
            continue
        except InvalidToken:
            pass
        plaintext = ""
        for legacy_fernet in legacy_fernets:
            try:
                plaintext = legacy_fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
                break
            except (InvalidToken, UnicodeDecodeError):
                continue
        if not plaintext:
            continue
        new_envelope = encrypt_provider_api_key(plaintext)
        conn.execute(
            """
            UPDATE web_search_provider_configs
            SET encrypted_api_key = %s::jsonb, key_hint = %s, updated_at = NOW()
            WHERE provider = %s
            """,
            (json.dumps(new_envelope), provider_key_hint(plaintext), record.provider),
        )
        migrated += 1
    return migrated


def resolve_provider_configs(
    conn: Any,
    *,
    environ: dict[str, str] | None = None,
) -> dict[str, ResolvedProviderConfig]:
    env = os.environ if environ is None else environ
    records = load_provider_config_records(conn)
    resolved: dict[str, ResolvedProviderConfig] = {}
    for provider in SUPPORTED_PROVIDER_SLUGS:
        record = records.get(provider)
        api_key = ""
        source = "none"
        if record and record.encrypted_api_key:
            api_key = decrypt_provider_api_key(record.encrypted_api_key).strip()
            source = "database" if api_key else "none"
        if not api_key:
            api_key = str(env.get(PROVIDER_ENV_KEYS[provider]) or "").strip()
            source = "environment" if api_key else "none"
        if source == "database" and record:
            connection_status = record.connection_status
        elif api_key:
            connection_status = (
                record.connection_status
                if record
                and not record.encrypted_api_key
                and record.connection_status not in {"", "not_configured"}
                else "untested"
            )
        else:
            connection_status = "not_configured"
        resolved[provider] = ResolvedProviderConfig(
            provider=provider,
            enabled=record.enabled if record else True,
            priority=record.priority if record else DEFAULT_PROVIDER_PRIORITIES[provider],
            api_key=api_key,
            config_source=source,
            connection_status=connection_status,
            last_tested_at=record.last_tested_at if record else None,
            last_test_latency_ms=record.last_test_latency_ms if record else None,
            last_error_type=record.last_error_type if record else "",
            last_error_message=record.last_error_message if record else "",
            settings=record.settings if record else {},
        )
    return resolved


def load_routing_config(conn: Any) -> RoutingConfig:
    row = conn.execute(
        """
        SELECT strategy, fallback_order, config_version, updated_at
        FROM web_search_routing_config
        WHERE id = 'instance'
        """
    ).fetchone()
    if not row:
        return RoutingConfig(
            strategy="smart",
            fallback_order=list(SUPPORTED_PROVIDER_SLUGS),
            config_version=1,
        )
    strategy = str(row[0] or "smart")
    order = [str(item).strip().lower() for item in (row[1] or [])]
    if sorted(order) != sorted(SUPPORTED_PROVIDER_SLUGS) or len(order) != len(SUPPORTED_PROVIDER_SLUGS):
        order = list(SUPPORTED_PROVIDER_SLUGS)
    return RoutingConfig(
        strategy=strategy if strategy in {"smart", "fixed"} else "smart",
        fallback_order=order,
        config_version=max(1, int(row[2] or 1)),
        updated_at=row[3],
    )


def build_provider_from_key(provider: str, api_key: str) -> Any:
    slug = str(provider or "").strip().lower()
    value = str(api_key or "").strip()
    if slug not in SUPPORTED_PROVIDER_SLUGS:
        raise ValueError("unsupported_web_search_provider")
    if not value:
        raise ProviderSecretError("api_key_required")
    timeout = float(os.getenv("WEB_SEARCH_PROVIDER_TEST_TIMEOUT_SECONDS", "8"))
    if slug == "exa":
        return ExaSearchProvider(value, timeout_seconds=timeout)
    if slug == "tavily":
        return TavilySearchProvider(value, timeout_seconds=timeout)
    return BochaSearchProvider(value, timeout_seconds=timeout)


def sanitize_provider_error(value: Any, *secret_fragments: str) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    for secret in secret_fragments:
        fragment = str(secret or "")
        if fragment:
            text = text.replace(fragment, "[redacted]")
    return SECRET_FRAGMENT_RE.sub("[redacted]", text)[:300]


def test_provider_connection(provider: str, api_key: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        adapter = build_provider_from_key(provider, api_key)
        result = adapter.search(
            SearchRequest(
                query="Nomi web search provider connectivity test official documentation",
                mode="quick",
                freshness="none",
                max_results=1,
            )
        )
        return {
            "status": "healthy",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "result_count": len(result.sources),
            "error_type": "",
            "error_message": "",
        }
    except WebSearchProviderError as exc:
        message = sanitize_provider_error(exc, api_key)
        lowered = f"{exc.error_type} {message}".lower()
        if "invalid_response" in lowered:
            status, error_type = "provider_error", "provider_invalid_response"
        elif any(marker in lowered for marker in ("401", "403", "auth", "unauthorized", "forbidden")):
            status, error_type = "invalid_key", "provider_auth_failed"
        elif "429" in lowered or "rate" in lowered:
            status, error_type = "rate_limited", "provider_rate_limited"
        elif "timeout" in lowered or "timed out" in lowered:
            status, error_type = "timeout", "provider_test_timeout"
        else:
            status, error_type = "provider_error", "provider_test_failed"
        return {
            "status": status,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "result_count": 0,
            "error_type": error_type,
            "error_message": "Provider connection test failed.",
        }
    except Exception as exc:
        return {
            "status": "provider_error",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "result_count": 0,
            "error_type": "provider_invalid_response",
            "error_message": "Provider connection test failed.",
        }
