from __future__ import annotations

import time
from typing import Any

import httpx

from app.web_search.providers.base import WebSearchProviderError
from app.web_search.schema import ProviderSearchResult, SearchRequest, WebSource


class ExaSearchProvider:
    name = "exa"

    def __init__(self, api_key: str, *, base_url: str = "https://api.exa.ai", timeout_seconds: float = 5.0) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def search(self, request: SearchRequest) -> ProviderSearchResult:
        started = time.perf_counter()
        payload: dict[str, Any] = {
            "query": request.query,
            "type": "fast" if request.mode == "quick" else "auto",
            "numResults": request.max_results,
            "contents": {
                "highlights": {"query": request.query, "maxCharacters": 1200},
            },
        }
        if request.allowed_domains:
            payload["includeDomains"] = request.allowed_domains
        if request.blocked_domains:
            payload["excludeDomains"] = request.blocked_domains
        if request.start_date:
            payload["startPublishedDate"] = request.start_date
        try:
            response = httpx.post(
                f"{self.base_url}/search",
                headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise WebSearchProviderError(str(exc), error_type="exa_request_failed") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise WebSearchProviderError(
                "Exa returned an invalid response.",
                retryable=False,
                error_type="exa_invalid_response",
            ) from exc
        if not isinstance(data, dict):
            raise WebSearchProviderError(
                "Exa returned a non-object response.",
                retryable=False,
                error_type="exa_invalid_response",
            )
        results = data.get("results")
        if not isinstance(results, list):
            raise WebSearchProviderError(
                "Exa response is missing a results list.",
                retryable=False,
                error_type="exa_invalid_response",
            )
        sources: list[WebSource] = []
        for index, item in enumerate(results, start=1):
            if not isinstance(item, dict) or not item.get("url"):
                continue
            highlights = [str(value) for value in item.get("highlights") or [] if str(value).strip()]
            sources.append(
                WebSource(
                    provider=self.name,
                    title=str(item.get("title") or item.get("url")),
                    url=str(item.get("url")),
                    published_at=item.get("publishedDate"),
                    snippet=highlights[0] if highlights else str(item.get("text") or "")[:1200],
                    highlights=highlights,
                    content=str(item.get("text") or ""),
                    provider_rank=index,
                    relevance_score=float(item.get("score") or 0.0),
                    metadata={"author": item.get("author"), "image": item.get("image")},
                )
            )
        return ProviderSearchResult(
            provider=self.name,
            sources=sources,
            response_time_ms=int((time.perf_counter() - started) * 1000),
            request_id=str(data.get("requestId") or ""),
            usage=data.get("costDollars") if isinstance(data.get("costDollars"), dict) else {},
        )
