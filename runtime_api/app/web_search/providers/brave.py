from __future__ import annotations

import time

import httpx

from app.web_search.providers.base import WebSearchProviderError
from app.web_search.schema import ProviderSearchResult, SearchRequest, WebSource


class BraveSearchProvider:
    name = "brave"

    def __init__(self, api_key: str, *, base_url: str = "https://api.search.brave.com", timeout_seconds: float = 5.0) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def search(self, request: SearchRequest) -> ProviderSearchResult:
        started = time.perf_counter()
        params = {
            "q": request.query,
            "count": request.max_results,
            "search_lang": request.locale.split("-", 1)[0].lower(),
            "extra_snippets": "true",
        }
        if request.country:
            params["country"] = request.country.lower()
        if request.freshness != "none":
            params["freshness"] = request.freshness
        try:
            response = httpx.get(
                f"{self.base_url}/res/v1/web/search",
                headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
                params=params,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WebSearchProviderError(str(exc), error_type="brave_request_failed") from exc
        sources: list[WebSource] = []
        for index, item in enumerate((data.get("web") or {}).get("results") or [], start=1):
            if not isinstance(item, dict) or not item.get("url"):
                continue
            snippets = [str(value) for value in item.get("extra_snippets") or [] if str(value).strip()]
            sources.append(
                WebSource(
                    provider=self.name,
                    title=str(item.get("title") or item.get("url")),
                    url=str(item.get("url")),
                    published_at=item.get("page_age"),
                    snippet=str(item.get("description") or ""),
                    highlights=snippets,
                    provider_rank=index,
                    relevance_score=max(0.0, 1.0 - (index - 1) * 0.06),
                    metadata={"profile": item.get("profile") or {}},
                )
            )
        return ProviderSearchResult(
            provider=self.name,
            sources=sources,
            response_time_ms=int((time.perf_counter() - started) * 1000),
            request_id=str(data.get("query", {}).get("original") or ""),
        )
