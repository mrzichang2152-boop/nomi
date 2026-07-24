from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from typing import Any

from app.web_search.cache import MemoryWebSearchCache, WebSearchCache
from app.web_search.config import ResolvedProviderConfig, RoutingConfig
from app.web_search.providers.bocha import BochaSearchProvider
from app.web_search.providers.base import WebSearchProvider
from app.web_search.providers.brave import BraveSearchProvider
from app.web_search.providers.exa import ExaSearchProvider
from app.web_search.providers.searxng import SearXNGSearchProvider
from app.web_search.providers.tavily import TavilySearchProvider
from app.web_search.schema import SearchResponse
from app.web_search.router import (
    build_web_search_route_plan,
    classify_web_search_category,
    eligible_provider_slugs,
)
from app.web_search.service import WebSearchService


DEFAULT_PROVIDER_ORDER = ("exa", "tavily", "bocha", "brave", "searxng")


class WebSearchRuntimeManager:
    def __init__(
        self,
        *,
        version_reader: Callable[[], int],
        fallback_version_reader: Callable[[], int],
        service_builder: Callable[[int], WebSearchService],
        fallback_check_ttl_seconds: float = 2.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._version_reader = version_reader
        self._fallback_version_reader = fallback_version_reader
        self._service_builder = service_builder
        self._lock = threading.RLock()
        self._service: WebSearchService | Any | None = None
        self._current_version = 0
        self._invalidated_version = 0
        self._fallback_check_ttl_seconds = max(0.0, float(fallback_check_ttl_seconds))
        self._monotonic = monotonic
        self._fallback_version: int | None = None
        self._fallback_version_expires_at = 0.0
        self._last_redis_version: int | None = None

    @property
    def current_version(self) -> int:
        with self._lock:
            return self._current_version

    def _read_version(self) -> int:
        redis_version: int | None = None
        try:
            redis_version = int(self._version_reader())
        except Exception:
            pass

        now = self._monotonic()
        with self._lock:
            redis_changed = (
                redis_version is not None
                and redis_version != self._last_redis_version
            )
            if redis_version is not None:
                self._last_redis_version = redis_version
            database_check_due = (
                self._fallback_version is None
                or now >= self._fallback_version_expires_at
                or redis_changed
                or self._invalidated_version > (self._fallback_version or 0)
            )
            if database_check_due:
                try:
                    database_version = int(self._fallback_version_reader())
                except Exception:
                    database_version = self._fallback_version
                else:
                    self._fallback_version = database_version
                    self._fallback_version_expires_at = (
                        now + self._fallback_check_ttl_seconds
                    )
                    if self._invalidated_version <= database_version:
                        self._invalidated_version = 0
            else:
                database_version = self._fallback_version

            if database_version is not None:
                return max(1, database_version)
            hints = [
                version
                for version in (redis_version, self._invalidated_version)
                if version is not None and version > 0
            ]
            if not hints:
                raise RuntimeError("web_search_config_version_unavailable")
            return max(1, *hints)

    def get_service(self) -> WebSearchService:
        version = self._read_version()
        with self._lock:
            if self._service is not None and self._current_version == version:
                return self._service
            service = self._service_builder(version)
            self._service = service
            self._current_version = version
            return service

    def invalidate(self, config_version: int) -> None:
        with self._lock:
            self._invalidated_version = max(self._invalidated_version, int(config_version))


def configured_provider_order() -> list[str]:
    raw = os.getenv("WEB_SEARCH_PROVIDER_ORDER", ",".join(DEFAULT_PROVIDER_ORDER))
    return list(dict.fromkeys(item.strip().lower() for item in raw.split(",") if item.strip()))


def build_web_search_providers() -> list[WebSearchProvider]:
    providers: dict[str, WebSearchProvider] = {}
    bocha_key = os.getenv("BOCHA_API_KEY", "").strip()
    exa_key = os.getenv("EXA_API_KEY", "").strip()
    tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
    brave_key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    searxng_url = os.getenv("SEARXNG_BASE_URL", "").strip()
    timeout = float(os.getenv("WEB_SEARCH_PROVIDER_TIMEOUT_SECONDS", "6"))
    if bocha_key:
        providers["bocha"] = BochaSearchProvider(bocha_key, timeout_seconds=timeout)
    if exa_key:
        providers["exa"] = ExaSearchProvider(exa_key, timeout_seconds=timeout)
    if tavily_key:
        providers["tavily"] = TavilySearchProvider(tavily_key, timeout_seconds=timeout)
    if brave_key:
        providers["brave"] = BraveSearchProvider(brave_key, timeout_seconds=timeout)
    if searxng_url:
        providers["searxng"] = SearXNGSearchProvider(searxng_url, timeout_seconds=timeout)
    return [providers[name] for name in configured_provider_order() if name in providers]


def build_web_search_service(*, cache: WebSearchCache | None = None) -> WebSearchService:
    return WebSearchService(
        build_web_search_providers(),
        cache=cache or MemoryWebSearchCache(),
    )


def build_web_search_service_from_configs(
    configs: dict[str, ResolvedProviderConfig],
    routing: RoutingConfig,
    *,
    cache: WebSearchCache | None = None,
) -> WebSearchService:
    timeout = float(os.getenv("WEB_SEARCH_PROVIDER_TIMEOUT_SECONDS", "6"))
    eligible = set(eligible_provider_slugs(configs))
    providers: dict[str, WebSearchProvider] = {}
    for provider in eligible:
        api_key = configs[provider].api_key
        if provider == "exa":
            providers[provider] = ExaSearchProvider(api_key, timeout_seconds=timeout)
        elif provider == "tavily":
            providers[provider] = TavilySearchProvider(api_key, timeout_seconds=timeout)
        elif provider == "bocha":
            providers[provider] = BochaSearchProvider(api_key, timeout_seconds=timeout)
    ordered = [
        providers[provider]
        for provider in routing.fallback_order
        if provider in providers
    ]

    def route_planner(request: Any):
        category = classify_web_search_category(
            request.query,
            freshness=request.freshness,
            trace_context=request.trace_context,
        )
        return build_web_search_route_plan(
            category,
            configs,
            strategy=routing.strategy,
            fallback_order=routing.fallback_order,
        )

    return WebSearchService(
        ordered,
        cache=cache or MemoryWebSearchCache(),
        route_planner=route_planner,
        config_version=routing.config_version,
    )


def search_response_to_context(response: SearchResponse) -> list[dict[str, Any]]:
    context = [
        {
            "source_id": source.source_id,
            "run_id": source.run_id,
            "layer": "web_evidence",
            "provider": source.provider,
            "title": source.title,
            "url": source.url,
            "canonical_url": source.canonical_url,
            "snippet": source.snippet,
            "published_at": source.published_at,
            "trust_tier": source.trust_tier,
            "content_status": source.content_status,
            "relevance_score": source.relevance_score,
        }
        for source in response.sources
    ]
    quality_warning = str(response.routing_trace.get("quality_warning") or "").strip()
    warning_reasons = {
        "official_source_not_found": "Search returned related pages but no authoritative official source.",
        "authoritative_source_not_found": "Search returned related pages but no authoritative source for this fact.",
        "primary_source_not_found": "Search returned related pages but no primary source for this current value.",
    }
    if quality_warning in warning_reasons:
        context.append(
            {
                "source_id": "web-search-quality",
                "layer": "web_search_status",
                "status": "partial",
                "error": quality_warning,
                "inclusion_reason": warning_reasons[quality_warning],
            }
        )
    return context


def web_search_provider_status() -> dict[str, Any]:
    configured = {provider.name for provider in build_web_search_providers()}
    return {
        "enabled": os.getenv("WEB_SEARCH_ENABLED", "true").lower() == "true",
        "provider_order": configured_provider_order(),
        "configured_providers": [name for name in configured_provider_order() if name in configured],
    }
