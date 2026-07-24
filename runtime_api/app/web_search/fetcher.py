from __future__ import annotations

import hashlib
import html
import os
import re
import time
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

import httpx

from app.web_search.schema import FetchRequest, FetchResponse, WebSource
from app.web_search.urls import UnsafeUrlError, canonicalize_url, validate_public_url


ALLOWED_CONTENT_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "application/json",
    "application/xml",
    "text/xml",
}
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


class ReadableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._title_depth = 0
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg", "canvas", "template"}:
            self._skip_depth += 1
        if lowered == "title":
            self._title_depth += 1
        if lowered in {"p", "div", "main", "article", "section", "li", "br", "h1", "h2", "h3", "h4"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg", "canvas", "template"} and self._skip_depth:
            self._skip_depth -= 1
        if lowered == "title" and self._title_depth:
            self._title_depth -= 1
        if lowered in {"p", "div", "main", "article", "section", "li", "h1", "h2", "h3", "h4"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = str(data or "").strip()
        if not value:
            return
        if self._title_depth:
            self.title_parts.append(value)
        self.text_parts.append(value)


def _normalize_readable_text(value: str, max_chars: int) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"[\t\r\f\v ]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()[:max_chars]


def _decode_body(response: httpx.Response, body: bytes) -> str:
    encoding = response.encoding or "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _limited_get(client: Any, url: str, *, timeout: float, max_bytes: int) -> tuple[httpx.Response, bytes]:
    headers = {
        "Accept": "text/html,application/xhtml+xml,text/plain,application/json;q=0.8,*/*;q=0.1",
        "User-Agent": "NomiWebEvidence/1.0 (+read-only)",
    }
    if hasattr(client, "build_request") and hasattr(client, "send"):
        request = client.build_request("GET", url, headers=headers)
        response = client.send(request, stream=True)
        chunks: list[bytes] = []
        used = 0
        try:
            for chunk in response.iter_bytes():
                used += len(chunk)
                if used > max_bytes:
                    raise ValueError("response_body_too_large")
                chunks.append(chunk)
        finally:
            response.close()
        return response, b"".join(chunks)
    response = client.get(url, headers=headers, timeout=timeout, follow_redirects=False)
    body = response.content
    if len(body) > max_bytes:
        raise ValueError("response_body_too_large")
    return response, body


def _empty_source(url: str, *, status: str) -> WebSource:
    canonical = canonicalize_url(url)
    return WebSource(
        source_id=f"websrc_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:20]}" if canonical else "",
        run_id=f"webfetch_{uuid.uuid4().hex}",
        provider="direct_fetch",
        title=url,
        url=url,
        canonical_url=canonical,
        domain=(urlsplit(url).hostname or "").lower(),
        content_status=status,
    )


def fetch_public_page(
    request: FetchRequest,
    *,
    client: Any | None = None,
    resolver: Callable[[str], list[str]] | None = None,
) -> FetchResponse:
    started = time.perf_counter()
    current_url = request.url
    owns_client = client is None
    http_client = client or httpx.Client(timeout=float(os.getenv("WEB_FETCH_TIMEOUT_SECONDS", "8")))
    max_bytes = int(os.getenv("WEB_FETCH_MAX_BYTES", str(2 * 1024 * 1024)))
    max_redirects = int(os.getenv("WEB_FETCH_MAX_REDIRECTS", "3"))
    timeout = float(os.getenv("WEB_FETCH_TIMEOUT_SECONDS", "8"))
    try:
        for redirect_index in range(max_redirects + 1):
            try:
                validate_public_url(current_url, resolver=resolver)
            except UnsafeUrlError as exc:
                return FetchResponse(
                    source=_empty_source(current_url, status="blocked"),
                    status="blocked",
                    error=str(exc),
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            try:
                response, body = _limited_get(http_client, current_url, timeout=timeout, max_bytes=max_bytes)
            except (httpx.HTTPError, ValueError) as exc:
                return FetchResponse(
                    source=_empty_source(current_url, status="failed"),
                    status="failed",
                    error=str(exc)[:300],
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            if response.status_code in REDIRECT_STATUS_CODES:
                location = str(response.headers.get("location") or "").strip()
                if not location:
                    break
                if redirect_index >= max_redirects:
                    return FetchResponse(
                        source=_empty_source(current_url, status="failed"),
                        status="failed",
                        error="too_many_redirects",
                        latency_ms=int((time.perf_counter() - started) * 1000),
                    )
                current_url = urljoin(current_url, location)
                continue
            if response.status_code >= 400:
                return FetchResponse(
                    source=_empty_source(current_url, status="failed"),
                    status="failed",
                    error=f"http_status:{response.status_code}",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            content_type = str(response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
            if content_type not in ALLOWED_CONTENT_TYPES:
                return FetchResponse(
                    source=_empty_source(current_url, status="blocked"),
                    status="blocked",
                    error=f"unsupported_content_type:{content_type or 'unknown'}",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            raw_text = _decode_body(response, body)
            title = ""
            if content_type in {"text/html", "application/xhtml+xml"}:
                parser = ReadableHtmlParser()
                parser.feed(raw_text)
                title = _normalize_readable_text(" ".join(parser.title_parts), 300)
                content = _normalize_readable_text(" ".join(parser.text_parts), request.max_chars)
            else:
                content = _normalize_readable_text(raw_text, request.max_chars)
            canonical = canonicalize_url(current_url)
            source_id = f"websrc_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:20]}"
            source = WebSource(
                source_id=source_id,
                run_id=f"webfetch_{uuid.uuid4().hex}",
                provider="direct_fetch",
                title=title or (urlsplit(current_url).hostname or current_url),
                url=current_url,
                canonical_url=canonical,
                domain=(urlsplit(current_url).hostname or "").lower(),
                fetched_at=datetime.now(timezone.utc).isoformat(),
                snippet=content[:1200],
                content=content,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                content_status="fetched",
                metadata={"content_type": content_type, "focus": request.focus},
            )
            return FetchResponse(
                source=source,
                status="completed",
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        return FetchResponse(
            source=_empty_source(current_url, status="failed"),
            status="failed",
            error="redirect_without_usable_destination",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    finally:
        if owns_client:
            http_client.close()
