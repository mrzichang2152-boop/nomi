from __future__ import annotations

import json
import os
import time
from threading import Lock
from typing import Any

import httpx

from app.web_search.providers.base import WebSearchProviderError
from app.web_search.schema import ProviderSearchResult, SearchRequest, WebSource


FRESHNESS_MAP = {
    "none": "noLimit",
    "day": "oneDay",
    "week": "oneWeek",
    "month": "oneMonth",
    "year": "oneYear",
}


class BochaSearchProvider:
    name = "bocha"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.bochaai.com",
        timeout_seconds: float = 6.0,
        min_request_interval_seconds: float | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.min_request_interval_seconds = (
            float(os.getenv("BOCHA_MIN_REQUEST_INTERVAL_SECONDS", "0.55"))
            if min_request_interval_seconds is None
            else max(0.0, min_request_interval_seconds)
        )
        self.max_retries = max(0, int(os.getenv("BOCHA_MAX_RETRIES", "2")))
        self._request_lock = Lock()
        self._last_request_at = 0.0

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        with self._request_lock:
            response: httpx.Response | None = None
            for attempt in range(self.max_retries + 1):
                wait_seconds = self.min_request_interval_seconds - (time.monotonic() - self._last_request_at)
                if wait_seconds > 0:
                    time.sleep(wait_seconds)
                self._last_request_at = time.monotonic()
                response = httpx.post(
                    f"{self.base_url}/v1/web-search",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                if response.status_code != 429 or attempt >= self.max_retries:
                    return response
                retry_after = str(response.headers.get("Retry-After") or "").strip()
                try:
                    retry_delay = float(retry_after)
                except ValueError:
                    retry_delay = self.min_request_interval_seconds * (2 ** (attempt + 1))
                time.sleep(max(0.0, retry_delay))
            assert response is not None
            return response

    def search(self, request: SearchRequest) -> ProviderSearchResult:
        started = time.perf_counter()
        payload: dict[str, Any] = {
            "query": request.query,
            "freshness": FRESHNESS_MAP.get(request.freshness, "noLimit"),
            "summary": True,
            "count": request.max_results,
        }
        try:
            response = self._post(payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise WebSearchProviderError(str(exc), error_type="bocha_request_failed") from exc
        try:
            envelope = response.json()
        except ValueError as exc:
            raise WebSearchProviderError(
                "Bocha returned an invalid response.",
                retryable=False,
                error_type="bocha_invalid_response",
            ) from exc

        if not isinstance(envelope, dict):
            raise WebSearchProviderError(
                "Bocha returned a non-object response.",
                retryable=False,
                error_type="bocha_invalid_response",
            )
        code = envelope.get("code")
        if code not in (None, 0, 200):
            raise WebSearchProviderError(
                str(envelope.get("msg") or f"Bocha API error: {code}"),
                retryable=code in {429, 500, 502, 503, 504},
                error_type="bocha_api_error",
            )
        data = envelope.get("data", envelope)
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError as exc:
                raise WebSearchProviderError(
                    "Bocha returned invalid JSON in data.",
                    retryable=False,
                    error_type="bocha_invalid_response",
                ) from exc
        if not isinstance(data, dict):
            raise WebSearchProviderError(
                "Bocha response data is not an object.",
                retryable=False,
                error_type="bocha_invalid_response",
            )
        pages = data.get("webPages")
        if not isinstance(pages, dict):
            raise WebSearchProviderError(
                "Bocha response is missing webPages.",
                retryable=False,
                error_type="bocha_invalid_response",
            )
        values = pages.get("value")
        if not isinstance(values, list):
            raise WebSearchProviderError(
                "Bocha response is missing a result list.",
                retryable=False,
                error_type="bocha_invalid_response",
            )
        sources: list[WebSource] = []
        for index, item in enumerate(values or [], start=1):
            if not isinstance(item, dict) or not item.get("url"):
                continue
            summary = str(item.get("summary") or "").strip()
            snippet = str(item.get("snippet") or "").strip()
            sources.append(
                WebSource(
                    provider=self.name,
                    title=str(item.get("name") or item.get("url")),
                    url=str(item.get("url")),
                    published_at=item.get("datePublished"),
                    snippet=summary or snippet,
                    highlights=[summary] if summary else [],
                    provider_rank=index,
                    relevance_score=max(0.0, 1.0 - (index - 1) * 0.06),
                    metadata={
                        "site_name": item.get("siteName"),
                        "site_icon": item.get("siteIcon"),
                        "raw_snippet": snippet,
                    },
                )
            )
        return ProviderSearchResult(
            provider=self.name,
            sources=sources,
            response_time_ms=int((time.perf_counter() - started) * 1000),
            request_id=str(envelope.get("log_id") or data.get("log_id") or ""),
            usage=envelope.get("usage") if isinstance(envelope.get("usage"), dict) else {},
        )
