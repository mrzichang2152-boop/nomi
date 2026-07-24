from __future__ import annotations

import time
from typing import Any

import httpx

from app.web_search.providers.base import WebSearchProviderError
from app.web_search.schema import ProviderSearchResult, SearchRequest, WebSource


class TavilySearchProvider:
    name = "tavily"

    def __init__(self, api_key: str, *, base_url: str = "https://api.tavily.com", timeout_seconds: float = 6.0) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def search(self, request: SearchRequest) -> ProviderSearchResult:
        started = time.perf_counter()
        depth = {"quick": "fast", "balanced": "basic", "research": "advanced"}[request.mode]
        payload: dict[str, Any] = {
            "query": request.query,
            "search_depth": depth,
            "max_results": request.max_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_domains": request.allowed_domains,
            "exclude_domains": request.blocked_domains,
        }
        if request.freshness != "none":
            payload["time_range"] = request.freshness
        if request.start_date:
            payload["start_date"] = request.start_date
        if request.end_date:
            payload["end_date"] = request.end_date
        if request.country:
            payload["country"] = request.country
        try:
            response = httpx.post(
                f"{self.base_url}/search",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise WebSearchProviderError(str(exc), error_type="tavily_request_failed") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise WebSearchProviderError(
                "Tavily returned an invalid response.",
                retryable=False,
                error_type="tavily_invalid_response",
            ) from exc
        if not isinstance(data, dict):
            raise WebSearchProviderError(
                "Tavily returned a non-object response.",
                retryable=False,
                error_type="tavily_invalid_response",
            )
        results = data.get("results")
        if not isinstance(results, list):
            raise WebSearchProviderError(
                "Tavily response is missing a results list.",
                retryable=False,
                error_type="tavily_invalid_response",
            )
        sources = [
            WebSource(
                provider=self.name,
                title=str(item.get("title") or item.get("url") or ""),
                url=str(item.get("url") or ""),
                snippet=str(item.get("content") or ""),
                provider_rank=index,
                relevance_score=float(item.get("score") or 0.0),
                metadata={"favicon": item.get("favicon")},
            )
            for index, item in enumerate(results, start=1)
            if isinstance(item, dict) and item.get("url")
        ]
        return ProviderSearchResult(
            provider=self.name,
            sources=sources,
            response_time_ms=int((time.perf_counter() - started) * 1000),
            request_id=str(data.get("request_id") or ""),
            usage=data.get("usage") if isinstance(data.get("usage"), dict) else {},
        )
