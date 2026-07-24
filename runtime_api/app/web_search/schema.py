from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


SearchMode = Literal["quick", "balanced", "research"]
Freshness = Literal["none", "day", "week", "month", "year", "custom"]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mode: SearchMode = "quick"
    freshness: Freshness = "none"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
    max_results: int = Field(default=8, ge=1, le=20)
    locale: str = "zh-CN"
    country: Optional[str] = None
    query_sensitivity: Literal["public", "derived_private", "blocked"] = "public"
    trace_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("allowed_domains", "blocked_domains")
    @classmethod
    def normalize_domains(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            domain = str(item or "").strip().lower().lstrip(".")
            if domain and domain not in normalized:
                normalized.append(domain)
        return normalized


class FetchRequest(BaseModel):
    url: str
    focus: str = ""
    max_chars: int = Field(default=12000, ge=500, le=100000)


class WebSource(BaseModel):
    source_id: str = ""
    run_id: str = ""
    query_id: str = ""
    provider: str
    title: str
    url: str
    canonical_url: str = ""
    domain: str = ""
    published_at: Optional[str] = None
    fetched_at: Optional[str] = None
    snippet: str = ""
    highlights: list[str] = Field(default_factory=list)
    content: str = ""
    content_hash: str = ""
    provider_rank: int = 0
    relevance_score: float = 0.0
    trust_tier: Literal["primary", "authoritative", "secondary", "unknown"] = "unknown"
    content_status: Literal["snippet_only", "fetched", "blocked", "failed"] = "snippet_only"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderError(BaseModel):
    provider: str
    query: str = ""
    error_type: str = "provider_error"
    message: str
    retryable: bool = True


class ProviderSearchResult(BaseModel):
    provider: str
    sources: list[WebSource] = Field(default_factory=list)
    response_time_ms: int = 0
    request_id: str = ""
    usage: dict[str, Any] = Field(default_factory=dict)


class SearchPlan(BaseModel):
    mode: SearchMode
    queries: list[str] = Field(min_length=1, max_length=8)
    max_sources: int = Field(default=8, ge=1, le=30)
    max_queries: int = Field(default=3, ge=1, le=8)
    reason: str = ""


class SearchResponse(BaseModel):
    run_id: str
    status: Literal["completed", "partial", "failed", "blocked"]
    query: str
    query_hash: str
    mode: SearchMode
    sources: list[WebSource] = Field(default_factory=list)
    providers_attempted: list[str] = Field(default_factory=list)
    errors: list[ProviderError] = Field(default_factory=list)
    latency_ms: int = 0
    cache_hit: bool = False
    redaction_summary: dict[str, Any] = Field(default_factory=dict)
    routing_trace: dict[str, Any] = Field(default_factory=dict)


class FetchResponse(BaseModel):
    source: WebSource
    status: Literal["completed", "failed", "blocked"]
    error: str = ""
    latency_ms: int = 0
