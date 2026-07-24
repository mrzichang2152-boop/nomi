from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.web_search.cache import WebSearchCache
from app.web_search.privacy import prepare_public_query
from app.web_search.providers.base import WebSearchProvider, WebSearchProviderError
from app.web_search.ranking import rank_and_dedupe_sources
from app.web_search.router import WebSearchRoutePlan
from app.web_search.schema import (
    ProviderError,
    SearchPlan,
    SearchRequest,
    SearchResponse,
    WebSource,
)


class WebSearchBlockedError(ValueError):
    pass


SEARCH_POLICY_VERSION = "2026-07-21-v7"
OFFICIAL_SOURCE_RE = re.compile(r"(?:官方|official)", re.IGNORECASE)
CURRENT_IDENTITY_RE = re.compile(r"(?:是谁|谁是|现任|目前|现在|current|who\s+is)", re.IGNORECASE)
PUBLIC_ROLE_RE = re.compile(
    r"(?:总统|总理|首相|部长|市长|州长|议长|首席执行官|董事长|"
    r"president|prime\s+minister|minister|governor|mayor|speaker|chief\s+executive|\bceo\b)",
    re.IGNORECASE,
)
WEATHER_RE = re.compile(
    r"(?:天气|气温|降雨|下雨|雷雨|暴雨|空气质量|weather|temperature|forecast)",
    re.IGNORECASE,
)
PRICE_RE = re.compile(r"(?:价格|售价|多少钱|price|pricing|cost)", re.IGNORECASE)
CURRENT_SIGNAL_RE = re.compile(
    r"(?:今天|今日|当前|现在|最新|实时|本周|this\s+week|today|current|latest|now)",
    re.IGNORECASE,
)
FRESH_NEWS_RE = re.compile(r"(?:新闻|快讯|news|breaking)", re.IGNORECASE)
RELEASE_RE = re.compile(r"(?:release|releases|版本|发布)", re.IGNORECASE)
GITHUB_RE = re.compile(r"(?:github|代码仓库|开源仓库)", re.IGNORECASE)
WEATHER_SUBJECT_STOP_RE = re.compile(
    r"(?:今天|今日|现在|当前|实时|天气|气温|降雨|下雨|雷雨|暴雨|空气质量|"
    r"预报|怎么样|如何|什么|会不会|是否|请问|告诉我|的)",
    re.IGNORECASE,
)
WEATHER_ENGLISH_STOP_WORDS = {
    "what",
    "is",
    "the",
    "weather",
    "temperature",
    "forecast",
    "in",
    "at",
    "for",
    "today",
    "now",
    "current",
    "latest",
    "cite",
    "official",
    "source",
    "sources",
    "please",
    "tell",
    "me",
}


def quality_search_expansions(query: str) -> list[str]:
    """Build deterministic parallel subqueries for source-quality-critical intents."""
    normalized = re.sub(r"\s+", " ", str(query or "")).strip()
    expansions: list[str] = []
    if WEATHER_RE.search(normalized):
        expansions.append(f"{normalized} 气象台 官方预报")
    elif PRICE_RE.search(normalized) and CURRENT_SIGNAL_RE.search(normalized):
        expansions.append(f"{normalized} 品牌官网 官方售价")
    elif FRESH_NEWS_RE.search(normalized) and CURRENT_SIGNAL_RE.search(normalized):
        expansions.append(f"{normalized} 行业重要进展 产品发布 政策")
    elif CURRENT_IDENTITY_RE.search(normalized) and PUBLIC_ROLE_RE.search(normalized):
        expansions.append(f"{normalized} 政府官网")
    elif RELEASE_RE.search(normalized) and GITHUB_RE.search(normalized):
        expansions.append(f"{normalized} GitHub Releases 官方")
    return [item for item in expansions if item and item != normalized]


def required_source_quality_warning(query: str) -> str:
    if RELEASE_RE.search(query) and GITHUB_RE.search(query):
        return "official_source_not_found"
    if CURRENT_IDENTITY_RE.search(query) and PUBLIC_ROLE_RE.search(query):
        return "authoritative_source_not_found"
    if WEATHER_RE.search(query):
        return "authoritative_source_not_found"
    if PRICE_RE.search(query) and CURRENT_SIGNAL_RE.search(query):
        return "primary_source_not_found"
    if OFFICIAL_SOURCE_RE.search(query):
        return "official_source_not_found"
    return ""


def _weather_subject_anchors(query: str) -> set[str]:
    text = str(query or "").strip().casefold()
    anchors = {
        token
        for token in re.findall(r"[a-z][a-z0-9_-]{2,}", text)
        if token not in WEATHER_ENGLISH_STOP_WORDS
    }
    chinese_subject = WEATHER_SUBJECT_STOP_RE.sub("", text)
    anchors.update(re.findall(r"[\u4e00-\u9fff]{2,}", chinese_subject))
    return anchors


def _source_satisfies_required_quality(
    query: str,
    source: WebSource,
    quality_warning: str,
) -> bool:
    if quality_warning == "primary_source_not_found":
        if source.trust_tier != "primary":
            return False
    elif source.trust_tier not in {"primary", "authoritative"}:
        return False
    if WEATHER_RE.search(query):
        anchors = _weather_subject_anchors(query)
        if anchors:
            haystack = " ".join(
                [source.title, source.snippet, *source.highlights, source.domain, source.url]
            ).casefold()
            compact_haystack = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", haystack)
            if not any(
                re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", anchor) in compact_haystack
                for anchor in anchors
            ):
                return False
    return True


def default_search_plan(request: SearchRequest) -> SearchPlan:
    quality_expansions = quality_search_expansions(request.query)
    if request.mode == "quick":
        queries = [request.query, *quality_expansions[:1]]
    elif request.mode == "balanced":
        queries = [request.query, *quality_expansions[:1]]
        if not quality_expansions:
            queries.append(f"{request.query} 官方 资料")
    else:
        queries = [request.query, *quality_expansions[:1], f"{request.query} 官方 资料"]
        if not quality_expansions:
            queries.append(f"{request.query} 最新 进展")
    queries = list(dict.fromkeys(queries))
    return SearchPlan(
        mode=request.mode,
        queries=queries,
        max_sources=request.max_results,
        max_queries=len(queries),
        reason=f"default_{request.mode}_search_plan",
    )


class WebSearchService:
    def __init__(
        self,
        providers: list[WebSearchProvider],
        *,
        cache: WebSearchCache | None = None,
        route_planner: Callable[[SearchRequest], WebSearchRoutePlan] | None = None,
        config_version: int = 0,
    ) -> None:
        self.providers = list(providers)
        self.providers_by_name = {provider.name: provider for provider in self.providers}
        self.cache = cache
        self.route_planner = route_planner
        self.config_version = max(0, int(config_version))

    def search(self, request: SearchRequest) -> SearchResponse:
        prepared = prepare_public_query(request.query)
        if prepared.blocked:
            raise WebSearchBlockedError(prepared.reason)
        safe_request = request.model_copy(
            update={"query": prepared.query, "query_sensitivity": prepared.sensitivity}
        )
        cache_key = self._cache_key(safe_request)
        cached = self.cache.get(cache_key) if self.cache else None
        if cached:
            return cached.model_copy(update={"cache_hit": True})
        route_plan = self.route_planner(safe_request) if self.route_planner else None
        response = self.execute_plan(
            safe_request,
            default_search_plan(safe_request),
            route_plan=route_plan,
        )
        response = response.model_copy(
            update={
                "query_hash": prepared.query_hash,
                "redaction_summary": {
                    "sensitivity": prepared.sensitivity,
                    "redacted_types": list(prepared.redacted_types),
                },
            }
        )
        if self.cache and response.status in {"completed", "partial"}:
            self.cache.set(cache_key, response, self._cache_ttl(safe_request))
        return response

    def execute_plan(
        self,
        request: SearchRequest,
        plan: SearchPlan,
        *,
        route_plan: WebSearchRoutePlan | None = None,
    ) -> SearchResponse:
        started = time.perf_counter()
        queries = plan.queries[: plan.max_queries]
        providers = self._providers_for_route(route_plan)
        results: list[
            tuple[int, list[WebSource], list[str], list[ProviderError], list[dict[str, object]]]
        ] = []
        max_workers = max(1, min(4, len(queries)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(
                    self._search_one_query,
                    request.model_copy(update={"query": query}),
                    providers,
                    bool(route_plan and route_plan.parallel),
                ): index
                for index, query in enumerate(queries)
            }
            for future in as_completed(future_map):
                index = future_map[future]
                sources, attempted, errors, provider_outcomes = future.result()
                results.append((index, sources, attempted, errors, provider_outcomes))
        results.sort(key=lambda item: item[0])
        all_sources: list[WebSource] = []
        attempted: list[str] = []
        errors: list[ProviderError] = []
        provider_outcomes: list[dict[str, object]] = []
        for _index, sources, provider_names, query_errors, query_outcomes in results:
            all_sources.extend(sources)
            attempted.extend(provider_names)
            errors.extend(query_errors)
            provider_outcomes.extend(query_outcomes)
        ranked = rank_and_dedupe_sources(
            request.query,
            all_sources,
            allowed_domains=request.allowed_domains,
            blocked_domains=request.blocked_domains,
        )[: plan.max_sources]
        run_id = f"webrun_{uuid.uuid4().hex}"
        normalized_sources = []
        for item in ranked:
            source_key = f"{run_id}\0{item.canonical_url}"
            source_id = f"websrc_{hashlib.sha256(source_key.encode('utf-8')).hexdigest()[:20]}"
            normalized_sources.append(item.model_copy(update={"source_id": source_id, "run_id": run_id}))
        successful_queries = sum(
            1 for _index, sources, _provider_names, _errors, _outcomes in results if sources
        )
        if normalized_sources and successful_queries == len(queries):
            status = "completed"
        elif normalized_sources:
            status = "partial"
        else:
            status = "failed"
        successful_providers = {
            str(outcome.get("provider") or "")
            for outcome in provider_outcomes
            if int(outcome.get("result_count") or 0) > 0
            and not str(outcome.get("error_type") or "")
        }
        if (
            status == "completed"
            and route_plan
            and route_plan.cross_provider_verification
            and len(successful_providers) < 2
        ):
            status = "partial"
        routing_trace = self._routing_trace(route_plan, errors, provider_outcomes)
        quality_warning = required_source_quality_warning(request.query)
        qualifying_source_count = sum(
            1
            for source in normalized_sources
            if quality_warning
            and _source_satisfies_required_quality(
                request.query,
                source,
                quality_warning,
            )
        )
        if normalized_sources and quality_warning and qualifying_source_count == 0:
            if status == "completed":
                status = "partial"
            routing_trace = {
                **routing_trace,
                "quality_warning": quality_warning,
                "authoritative_source_count": 0,
            }
        elif quality_warning:
            routing_trace = {
                **routing_trace,
                "authoritative_source_count": qualifying_source_count,
            }
        return SearchResponse(
            run_id=run_id,
            status=status,
            query=request.query,
            query_hash=hashlib.sha256(request.query.encode("utf-8")).hexdigest(),
            mode=request.mode,
            sources=normalized_sources,
            providers_attempted=list(dict.fromkeys(attempted)),
            errors=errors,
            latency_ms=int((time.perf_counter() - started) * 1000),
            routing_trace=routing_trace,
        )

    def _providers_for_route(
        self,
        route_plan: WebSearchRoutePlan | None,
    ) -> list[WebSearchProvider]:
        if route_plan is None:
            return list(self.providers)
        return [
            self.providers_by_name[name]
            for name in route_plan.provider_order
            if name in self.providers_by_name
        ]

    @staticmethod
    def _routing_trace(
        route_plan: WebSearchRoutePlan | None,
        errors: list[ProviderError] | None = None,
        provider_outcomes: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        if route_plan is None:
            return {}
        fallback_events = [
            {
                "provider": error.provider,
                "error_type": error.error_type,
                "retryable": error.retryable,
            }
            for error in (errors or [])
        ]
        successful_providers = {
            str(outcome.get("provider") or "")
            for outcome in (provider_outcomes or [])
            if int(outcome.get("result_count") or 0) > 0
            and not str(outcome.get("error_type") or "")
        }
        cross_provider_required = bool(route_plan.cross_provider_verification)
        cross_provider_completed = (
            cross_provider_required and len(successful_providers) >= 2
        )
        verification_warning = route_plan.verification_warning
        if cross_provider_required and not cross_provider_completed:
            verification_warning = "cross_provider_verification_incomplete"
        return {
            "category": route_plan.category,
            "provider_order": list(route_plan.provider_order),
            "eligible_providers": list(route_plan.eligible_providers),
            "parallel": route_plan.parallel,
            "cross_provider_verification": cross_provider_completed,
            "cross_provider_verification_required": cross_provider_required,
            "cross_provider_verification_completed": cross_provider_completed,
            "reason": route_plan.reason,
            "route_category": route_plan.category,
            "configured_providers": list(route_plan.configured_providers or route_plan.eligible_providers),
            "selected_providers": list(route_plan.provider_order),
            "selection_reason": route_plan.reason,
            "fallback_events": fallback_events,
            "verification_warning": verification_warning,
            "provider_outcomes": list(provider_outcomes or []),
        }

    def _search_one_query(
        self,
        request: SearchRequest,
        providers: list[WebSearchProvider] | None = None,
        parallel: bool = False,
    ) -> tuple[list[WebSource], list[str], list[ProviderError], list[dict[str, object]]]:
        selected = list(providers if providers is not None else self.providers)
        if parallel:
            return self._search_one_query_parallel(request, selected)
        attempted: list[str] = []
        errors: list[ProviderError] = []
        provider_outcomes: list[dict[str, object]] = []
        for provider in selected:
            attempted.append(provider.name)
            provider_started = time.perf_counter()
            try:
                result = provider.search(request)
            except WebSearchProviderError as exc:
                latency_ms = int((time.perf_counter() - provider_started) * 1000)
                provider_outcomes.append(
                    self._provider_outcome(provider.name, latency_ms, 0, exc.error_type)
                )
                errors.append(
                    ProviderError(
                        provider=provider.name,
                        query=request.query,
                        error_type=exc.error_type,
                        message="Provider request failed.",
                        retryable=exc.retryable,
                    )
                )
                continue
            except Exception as exc:
                latency_ms = int((time.perf_counter() - provider_started) * 1000)
                provider_outcomes.append(
                    self._provider_outcome(
                        provider.name,
                        latency_ms,
                        0,
                        "unexpected_provider_error",
                    )
                )
                errors.append(
                    ProviderError(
                        provider=provider.name,
                        query=request.query,
                        error_type="unexpected_provider_error",
                        message="Provider request failed.",
                    )
                )
                continue
            usable_sources = self._usable_provider_sources(request, result.sources)
            empty_error_type = (
                "all_results_filtered" if result.sources else "empty_results"
            )
            provider_outcomes.append(
                self._provider_outcome(
                    provider.name,
                    result.response_time_ms,
                    len(usable_sources),
                    "" if usable_sources else empty_error_type,
                )
            )
            if usable_sources:
                return usable_sources, attempted, errors, provider_outcomes
            errors.append(
                ProviderError(
                    provider=provider.name,
                    query=request.query,
                    error_type=empty_error_type,
                    message="Provider returned no sources allowed by the search policy.",
                )
            )
        return [], attempted, errors, provider_outcomes

    def _search_one_query_parallel(
        self,
        request: SearchRequest,
        providers: list[WebSearchProvider],
    ) -> tuple[list[WebSource], list[str], list[ProviderError], list[dict[str, object]]]:
        indexed_results: list[
            tuple[int, list[WebSource], ProviderError | None, dict[str, object]]
        ] = []

        def call_provider(
            provider: WebSearchProvider,
        ) -> tuple[list[WebSource], ProviderError | None, dict[str, object]]:
            provider_started = time.perf_counter()
            try:
                result = provider.search(request)
            except WebSearchProviderError as exc:
                latency_ms = int((time.perf_counter() - provider_started) * 1000)
                return (
                    [],
                    ProviderError(
                        provider=provider.name,
                        query=request.query,
                        error_type=exc.error_type,
                        message="Provider request failed.",
                        retryable=exc.retryable,
                    ),
                    self._provider_outcome(provider.name, latency_ms, 0, exc.error_type),
                )
            except Exception as exc:
                latency_ms = int((time.perf_counter() - provider_started) * 1000)
                return (
                    [],
                    ProviderError(
                        provider=provider.name,
                        query=request.query,
                        error_type="unexpected_provider_error",
                        message="Provider request failed.",
                    ),
                    self._provider_outcome(
                        provider.name,
                        latency_ms,
                        0,
                        "unexpected_provider_error",
                    ),
                )
            usable_sources = self._usable_provider_sources(request, result.sources)
            if usable_sources:
                return (
                    usable_sources,
                    None,
                    self._provider_outcome(
                        provider.name,
                        result.response_time_ms,
                        len(usable_sources),
                        "",
                    ),
                )
            empty_error_type = (
                "all_results_filtered" if result.sources else "empty_results"
            )
            return (
                [],
                ProviderError(
                    provider=provider.name,
                    query=request.query,
                    error_type=empty_error_type,
                    message="Provider returned no sources allowed by the search policy.",
                ),
                self._provider_outcome(
                    provider.name,
                    result.response_time_ms,
                    0,
                    empty_error_type,
                ),
            )

        with ThreadPoolExecutor(max_workers=max(1, min(4, len(providers)))) as executor:
            future_map = {
                executor.submit(call_provider, provider): index
                for index, provider in enumerate(providers)
            }
            for future in as_completed(future_map):
                sources, error, outcome = future.result()
                indexed_results.append((future_map[future], sources, error, outcome))
        indexed_results.sort(key=lambda item: item[0])
        sources = [
            source for _index, items, _error, _outcome in indexed_results for source in items
        ]
        errors = [
            error
            for _index, _items, error, _outcome in indexed_results
            if error is not None
        ]
        outcomes = [outcome for _index, _items, _error, outcome in indexed_results]
        return sources, [provider.name for provider in providers], errors, outcomes

    @staticmethod
    def _provider_outcome(
        provider: str,
        latency_ms: int,
        result_count: int,
        error_type: str,
    ) -> dict[str, object]:
        return {
            "provider": provider,
            "latency_ms": max(0, int(latency_ms)),
            "result_count": max(0, int(result_count)),
            "error_type": str(error_type or ""),
        }

    @staticmethod
    def _usable_provider_sources(
        request: SearchRequest,
        sources: list[WebSource],
    ) -> list[WebSource]:
        return rank_and_dedupe_sources(
            request.query,
            sources,
            allowed_domains=request.allowed_domains,
            blocked_domains=request.blocked_domains,
        )

    def _cache_key(self, request: SearchRequest) -> str:
        payload = {
            "search_policy_version": SEARCH_POLICY_VERSION,
            "query": request.query,
            "mode": request.mode,
            "freshness": request.freshness,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "allowed_domains": request.allowed_domains,
            "blocked_domains": request.blocked_domains,
            "locale": request.locale,
            "country": request.country,
            "max_results": request.max_results,
            "route_category": str(request.trace_context.get("route_category") or ""),
            "config_version": self.config_version,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    @staticmethod
    def _cache_ttl(request: SearchRequest) -> int:
        if request.freshness == "day":
            return 180
        if request.freshness in {"week", "month"}:
            return 900
        return 21600
