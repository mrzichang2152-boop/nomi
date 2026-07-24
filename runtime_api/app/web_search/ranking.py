from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

from app.web_search.schema import WebSource
from app.web_search.urls import canonicalize_url


AUTHORITATIVE_SUFFIXES = (
    ".gov",
    ".gov.cn",
    ".gov.uk",
    ".gov.au",
    ".gov.sg",
    ".go.jp",
    ".go.kr",
    ".gc.ca",
    ".gouv.fr",
    ".bund.de",
    ".europa.eu",
    ".edu",
    ".edu.cn",
)
AUTHORITATIVE_DOMAINS = (
    "weather.com.cn",
    "nmc.cn",
)
NAMED_ENTITY_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.+-]{3,}")
NAMED_ENTITY_STOP_WORDS = {
    "about",
    "current",
    "documentation",
    "latest",
    "news",
    "notes",
    "official",
    "overview",
    "release",
    "releases",
    "version",
    "website",
}
SPAM_TITLE_RE = re.compile(
    r"(官网版.{0,8}(?:下载|安装)|免费最新版下载|已认证地址|开户注册|注册账号|娱乐.{0,6}下载|综合信息查询)",
    re.IGNORECASE,
)
PROVIDER_GENERATED_RESULT_PATHS = {
    "bocha.cn": ("/share/",),
    "www.bocha.cn": ("/share/",),
}
ENTITY_IDENTITY_GATE_RE = re.compile(
    r"(?:\breleases?\b|\bversions?\b|\bgithub\b|\bdownloads?\b|"
    r"\bdocs?\b|\bdocumentation\b|安装包|版本|下载|发布说明|发行说明|更新日志)",
    re.IGNORECASE,
)


def _domain_matches(host: str, domains: list[str] | None) -> bool:
    return any(host == item or host.endswith(f".{item}") for item in (domains or []))


def infer_trust_tier(source: WebSource, allowed_domains: list[str] | None = None) -> str:
    host = (urlsplit(source.url).hostname or "").lower()
    allowed = [item.lower().lstrip(".") for item in (allowed_domains or [])]
    if any(host == item or host.endswith(f".{item}") for item in allowed):
        return "primary"
    if (
        host.startswith(("docs.", "developer.", "support."))
        or host.endswith(AUTHORITATIVE_SUFFIXES)
        or _domain_matches(host, list(AUTHORITATIVE_DOMAINS))
    ):
        return "authoritative"
    if source.trust_tier != "unknown":
        return source.trust_tier
    return "secondary" if host else "unknown"


def _query_tokens(query: str) -> set[str]:
    normalized_query = query.lower()
    tokens = set(re.findall(r"[A-Za-z0-9_]+", normalized_query))
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", normalized_query):
        for size in (2, 3):
            tokens.update(chunk[index : index + size] for index in range(len(chunk) - size + 1))
    return tokens


def _text_overlap(query: str, text: str) -> float:
    tokens = _query_tokens(query)
    if not tokens:
        return 0.0
    haystack = text.lower()
    return sum(1 for token in tokens if token in haystack) / len(tokens)


def _query_overlap(query: str, source: WebSource) -> float:
    return _text_overlap(
        query,
        f"{source.title} {source.snippet} {' '.join(source.highlights)}",
    )


def _named_entity_anchors(query: str) -> set[str]:
    return {
        token.lower()
        for token in NAMED_ENTITY_TOKEN_RE.findall(str(query or ""))
        if token.lower() not in NAMED_ENTITY_STOP_WORDS
        and (token != token.lower() or any(char.isdigit() for char in token))
    }


def _passes_source_quality_gate(query: str, source: WebSource, host: str) -> bool:
    if SPAM_TITLE_RE.search(str(source.title or "")):
        return False
    path = (urlsplit(source.url).path or "/").lower()
    if any(path.startswith(prefix) for prefix in PROVIDER_GENERATED_RESULT_PATHS.get(host, ())):
        return False
    if not ENTITY_IDENTITY_GATE_RE.search(str(query or "")):
        return True
    anchors = _named_entity_anchors(query)
    if not anchors:
        return True
    identity_text = f"{source.title} {host}".lower()
    return any(anchor in identity_text for anchor in anchors)


def _source_score(query: str, source: WebSource) -> float:
    trust_bonus = {
        "primary": 0.22,
        "authoritative": 0.16,
        "secondary": 0.04,
        "unknown": 0.0,
    }[source.trust_tier]
    completeness = min(0.08, len(source.snippet) / 2000.0 + len(source.highlights) * 0.01)
    rank_bonus = max(0.0, 0.08 - max(0, source.provider_rank - 1) * 0.01)
    return (
        float(source.relevance_score or 0.0)
        + trust_bonus
        + completeness
        + rank_bonus
        + _query_overlap(query, source) * 0.18
        + _text_overlap(query, source.title) * 0.28
    )


def _content_richness(source: WebSource) -> int:
    return len(source.content) + len(source.snippet) + sum(len(item) for item in source.highlights)


def _title_fingerprint(title: str) -> str:
    normalized = str(title or "").strip().casefold()
    normalized = re.sub(r"\s*[_|｜]\s*[^_|｜]{1,24}\s*$", "", normalized)
    normalized = re.sub(
        r"\s*[-—]\s*[^-—]{1,24}(?:新闻|日报|时报|官网|网站|客户端|网)\s*$",
        "",
        normalized,
    )
    return re.sub(r"[\W_]+", "", normalized)


def _prefer_source(query: str, existing: WebSource, candidate: WebSource) -> WebSource:
    existing_key = (_source_score(query, existing), _content_richness(existing))
    candidate_key = (_source_score(query, candidate), _content_richness(candidate))
    return candidate if candidate_key > existing_key else existing


def rank_and_dedupe_sources(
    query: str,
    sources: list[WebSource],
    *,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
) -> list[WebSource]:
    allowed = [item.lower().lstrip(".") for item in (allowed_domains or [])]
    blocked = [item.lower().lstrip(".") for item in (blocked_domains or [])]
    by_url: dict[str, WebSource] = {}
    for source in sources:
        canonical = canonicalize_url(source.url)
        host = (urlsplit(canonical).hostname or "").lower()
        if allowed and not _domain_matches(host, allowed):
            continue
        if blocked and _domain_matches(host, blocked):
            continue
        if not _passes_source_quality_gate(query, source, host):
            continue
        enriched = source.model_copy(
            update={
                "canonical_url": canonical,
                "domain": source.domain or host,
                "trust_tier": infer_trust_tier(source, allowed_domains),
                "content_hash": source.content_hash
                or hashlib.sha256((source.content or source.snippet).encode("utf-8")).hexdigest(),
            }
        )
        existing = by_url.get(canonical)
        if existing is None:
            by_url[canonical] = enriched
            continue
        by_url[canonical] = _prefer_source(query, existing, enriched)

    by_title: dict[str, WebSource] = {}
    without_stable_title: list[WebSource] = []
    for source in by_url.values():
        fingerprint = _title_fingerprint(source.title)
        if len(fingerprint) < 8:
            without_stable_title.append(source)
            continue
        existing = by_title.get(fingerprint)
        if existing is None:
            by_title[fingerprint] = source
        else:
            by_title[fingerprint] = _prefer_source(query, existing, source)
    deduped = [*by_title.values(), *without_stable_title]
    return sorted(deduped, key=lambda item: (_source_score(query, item), _content_richness(item)), reverse=True)
