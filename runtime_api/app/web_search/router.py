from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import re
from typing import Mapping

from app.web_search.config import ResolvedProviderConfig, SUPPORTED_PROVIDER_SLUGS


SMART_PROVIDER_ORDER = {
    "technical_docs": ["exa", "tavily", "bocha"],
    "research": ["exa", "tavily", "bocha"],
    "open_source": ["exa", "tavily", "bocha"],
    "fresh_news": ["tavily", "bocha", "exa"],
    "current_general": ["tavily", "bocha", "exa"],
    "china_general": ["bocha", "tavily", "exa"],
    "jobs_company": ["exa", "tavily", "bocha"],
    "high_stakes_facts": ["exa", "tavily", "bocha"],
    "unknown": ["exa", "tavily", "bocha"],
}

HIGH_STAKES_TERMS = (
    "医疗", "药", "处方", "诊断", "法律", "诉讼", "合同风险", "投资", "证券", "税务",
    "medical", "medicine", "prescription", "legal", "lawsuit", "investment", "tax",
)
JOB_TERMS = (
    "岗位", "招聘", "求职", "职位", "简历", "面试", "猎头", "公司", "career", "job",
    "hiring", "recruiter", "resume", "interview", "company",
)
TECHNICAL_TERMS = (
    "api", "sdk", "官方文档", "技术文档", "documentation",
)
RESEARCH_TERMS = (
    "研究论文", "论文", "学术研究", "arxiv", "research paper", "academic study",
)
OPEN_SOURCE_TERMS = (
    "github", "开源", "代码仓库", "源码", "open source", "source code", "repository",
)
NEWS_TERMS = (
    "新闻", "快讯", "breaking", "news",
)
CURRENT_TERMS = (
    "今天", "最新", "刚刚", "动态", "进展", "发布", "本周", "today", "latest", "recent",
    "this week",
)


@dataclass(frozen=True)
class WebSearchRoutePlan:
    category: str
    provider_order: list[str]
    eligible_providers: list[str]
    parallel: bool
    cross_provider_verification: bool
    reason: str
    configured_providers: list[str] = field(default_factory=list)
    verification_warning: str = ""


def classify_web_search_category(
    query: str,
    *,
    freshness: str = "none",
    trace_context: Mapping[str, object] | None = None,
) -> str:
    explicit = str((trace_context or {}).get("route_category") or "").strip().lower()
    if explicit in SMART_PROVIDER_ORDER:
        return explicit
    normalized = str(query or "").strip().lower()
    if any(term in normalized for term in HIGH_STAKES_TERMS):
        return "high_stakes_facts"
    if any(term in normalized for term in JOB_TERMS):
        return "jobs_company"
    if any(term in normalized for term in RESEARCH_TERMS):
        return "research"
    if any(term in normalized for term in TECHNICAL_TERMS):
        return "technical_docs"
    if any(term in normalized for term in OPEN_SOURCE_TERMS):
        return "open_source"
    if any(term in normalized for term in NEWS_TERMS):
        return "fresh_news"
    if freshness != "none" or any(term in normalized for term in CURRENT_TERMS):
        return "current_general"
    if re.search(r"[\u4e00-\u9fff]", normalized):
        return "china_general"
    return "unknown"


def eligible_provider_slugs(
    configs: Mapping[str, ResolvedProviderConfig],
) -> list[str]:
    eligible: list[str] = []
    for provider in SUPPORTED_PROVIDER_SLUGS:
        config = configs.get(provider)
        if not config or not config.enabled or not config.configured:
            continue
        if config.connection_status == "invalid_key":
            continue
        eligible.append(provider)
    return eligible


def build_web_search_route_plan(
    category: str,
    configs: Mapping[str, ResolvedProviderConfig],
    *,
    strategy: str = "smart",
    fallback_order: list[str] | None = None,
) -> WebSearchRoutePlan:
    normalized_category = str(category or "china_general").strip().lower()
    eligible = eligible_provider_slugs(configs)
    configured = [
        provider
        for provider in SUPPORTED_PROVIDER_SLUGS
        if configs.get(provider) and configs[provider].configured
    ]
    if not eligible:
        return WebSearchRoutePlan(
            category=normalized_category,
            provider_order=[],
            eligible_providers=[],
            parallel=False,
            cross_provider_verification=False,
            reason="no_eligible_provider",
            configured_providers=configured,
        )
    if len(eligible) == 1:
        return WebSearchRoutePlan(
            category=normalized_category,
            provider_order=list(eligible),
            eligible_providers=list(eligible),
            parallel=False,
            cross_provider_verification=False,
            reason="single_configured_provider",
            configured_providers=configured,
            verification_warning=(
                "single_provider_cross_verification_unavailable"
                if normalized_category == "high_stakes_facts"
                else ""
            ),
        )

    if strategy == "fixed":
        configured_order = fallback_order or list(SUPPORTED_PROVIDER_SLUGS)
        ordered = [provider for provider in configured_order if provider in eligible]
        return WebSearchRoutePlan(
            category=normalized_category,
            provider_order=ordered,
            eligible_providers=list(eligible),
            parallel=False,
            cross_provider_verification=False,
            reason="fixed_provider_order",
            configured_providers=configured,
        )

    preferred = (
        fallback_order or list(SUPPORTED_PROVIDER_SLUGS)
        if normalized_category == "unknown"
        else SMART_PROVIDER_ORDER.get(normalized_category, fallback_order or list(SUPPORTED_PROVIDER_SLUGS))
    )
    ordered = [provider for provider in preferred if provider in eligible]
    high_stakes = normalized_category == "high_stakes_facts" and len(ordered) >= 2
    return WebSearchRoutePlan(
        category=normalized_category,
        provider_order=ordered,
        eligible_providers=list(eligible),
        parallel=high_stakes,
        cross_provider_verification=high_stakes,
        reason=f"smart_route:{normalized_category}",
        configured_providers=configured,
    )
