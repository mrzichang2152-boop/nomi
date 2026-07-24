from __future__ import annotations

import time

import httpx

from app.web_search.providers.base import WebSearchProviderError
from app.web_search.schema import ProviderSearchResult, SearchRequest, WebSource


class SearXNGSearchProvider:
    name = "searxng"

    def __init__(self, base_url: str, *, timeout_seconds: float = 6.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def search(self, request: SearchRequest) -> ProviderSearchResult:
        started = time.perf_counter()
        params = {
            "q": request.query,
            "format": "json",
            "language": request.locale,
            "safesearch": 1,
        }
        if request.freshness in {"day", "week", "month", "year"}:
            params["time_range"] = request.freshness
        try:
            response = httpx.get(
                f"{self.base_url}/search",
                params=params,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WebSearchProviderError(str(exc), error_type="searxng_request_failed") from exc
        sources = [
            WebSource(
                provider=self.name,
                title=str(item.get("title") or item.get("url") or ""),
                url=str(item.get("url") or ""),
                published_at=item.get("publishedDate") or item.get("published_date"),
                snippet=str(item.get("content") or ""),
                provider_rank=index,
                relevance_score=float(item.get("score") or max(0.0, 1.0 - (index - 1) * 0.06)),
                metadata={"engine": item.get("engine"), "engines": item.get("engines") or []},
            )
            for index, item in enumerate((data.get("results") or [])[: request.max_results], start=1)
            if isinstance(item, dict) and item.get("url")
        ]
        return ProviderSearchResult(
            provider=self.name,
            sources=sources,
            response_time_ms=int((time.perf_counter() - started) * 1000),
            usage={"number_of_results": data.get("number_of_results")},
        )
