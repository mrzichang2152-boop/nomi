from __future__ import annotations

import re
from typing import Any


CITATION_RE = re.compile(
    r"\[((?:websrc_[A-Za-z0-9_-]+)(?:\s*[,，;；]\s*websrc_[A-Za-z0-9_-]+)*)\]"
)
SOURCE_ID_RE = re.compile(r"websrc_[A-Za-z0-9_-]+")
QUALITY_DISCLAIMERS = {
    "official_source_not_found": "未找到官方一手来源；下面内容仅是二手线索，不能视为已核验的官方结论。",
    "authoritative_source_not_found": "未找到足以核验该事实的权威来源；下面内容只能作为待核验线索。",
    "primary_source_not_found": "未找到品牌、机构或交易方的一手来源；下面的媒体转述、促销信息或聚合价格不能视为统一的当前值。",
}
LEGACY_QUALITY_DISCLAIMERS = (
    "尚未找到品牌、机构或交易方的一手来源，不得把媒体转述、促销文章或聚合价格表述为统一的当前价格。",
    "尚未找到足以核验该事实的权威来源。",
    "只找到了相关二手来源、尚未找到官方来源。",
)
MODEL_QUALITY_PREFACE_RE = re.compile(
    r"^(?:尚未找到|未找到|目前未找到)"
    r"(?=[^\n]{0,220}(?:来源|发布记录))"
    r"(?=[^\n]{0,220}(?:官方|权威|一手|二手|核验))"
    r"[^\n]{0,220}(?:\n+|$)"
)
MODEL_TRAILING_QUALITY_NOTE_RE = re.compile(
    r"^(?:\*{1,2})?(?:注意|说明|Note)(?:\*{1,2})?[：:]",
    re.IGNORECASE,
)


def apply_web_quality_disclaimer(
    answer: str,
    web_context: list[dict[str, Any]],
) -> str:
    warning = next(
        (
            str(item.get("error") or "").strip()
            for item in web_context
            if isinstance(item, dict)
            and item.get("layer") == "web_search_status"
            and str(item.get("error") or "").strip() in QUALITY_DISCLAIMERS
        ),
        "",
    )
    if not warning:
        return str(answer or "")
    desired = QUALITY_DISCLAIMERS[warning]
    cleaned = str(answer or "").lstrip()
    removable = (*QUALITY_DISCLAIMERS.values(), *LEGACY_QUALITY_DISCLAIMERS)
    for prefix in removable:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].lstrip(" \n")
            break
    else:
        model_preface = MODEL_QUALITY_PREFACE_RE.match(cleaned)
        if model_preface:
            cleaned = cleaned[model_preface.end() :].lstrip(" \n")
        else:
            first_paragraph, separator, remainder = cleaned.partition("\n\n")
            normalized_first = first_paragraph.replace("**", "")
            is_duplicate_quality_preface = (
                bool(separator)
                and len(normalized_first) <= 260
                and any(term in normalized_first for term in ("尚未找到", "未找到"))
                and any(term in normalized_first for term in ("来源", "发布记录"))
                and any(
                    term in normalized_first
                    for term in ("官方", "权威", "一手", "二手", "核验")
                )
            )
            if is_duplicate_quality_preface:
                cleaned = remainder.lstrip(" \n")
    paragraphs = cleaned.split("\n\n") if cleaned else []
    cleaned = "\n\n".join(
        paragraph
        for paragraph in paragraphs
        if not (
            MODEL_TRAILING_QUALITY_NOTE_RE.match(paragraph.strip())
            and (
                any(term in paragraph for term in ("尚未找到", "未找到"))
                or (
                    "search status" in paragraph.lower()
                    and any(
                        term in paragraph.lower()
                        for term in ("partial", "unverified", "not found")
                    )
                )
            )
            and (
                any(term in paragraph for term in ("来源", "核验", "发布记录"))
                or any(term in paragraph.lower() for term in ("source", "evidence"))
            )
            and (
                any(term in paragraph for term in ("官方", "权威", "一手", "二手"))
                or any(
                    term in paragraph.lower()
                    for term in ("official", "authoritative", "primary", "secondary")
                )
            )
        )
    ).strip()
    return desired if not cleaned else f"{desired}\n\n{cleaned}"


def _claim_before_marker(prefix: str) -> str:
    """Return the complete sentence immediately preceding a citation marker."""
    trimmed = prefix.rstrip()
    if not trimmed:
        return ""

    terminal = trimmed[-1] if trimmed[-1] in "。！？.!?" else ""
    search_text = trimmed[:-1].rstrip() if terminal else trimmed
    boundaries = [
        search_text.rfind("\n"),
        search_text.rfind("。"),
        search_text.rfind("！"),
        search_text.rfind("？"),
        search_text.rfind(". "),
        search_text.rfind("! "),
        search_text.rfind("? "),
    ]
    boundary = max(boundaries)
    claim = search_text[boundary + 1 :].strip()
    return f"{claim}{terminal}" if claim else ""


def _markdown_link(source: dict[str, Any]) -> str:
    title = str(source.get("title") or source.get("domain") or "来源").replace("[", "").replace("]", "")
    url = str(source.get("url") or "").strip()
    return f"[{title}]({url})" if url else title


def finalize_web_answer(
    answer: str,
    web_context: list[dict[str, Any]],
    *,
    append_fallback_sources: bool = True,
) -> tuple[str, dict[str, Any]]:
    sources = {
        str(item.get("source_id")): item
        for item in web_context
        if isinstance(item, dict)
        and item.get("source_id")
        and item.get("url")
        and item.get("layer") == "web_evidence"
    }
    raw_answer = str(answer or "")
    raw_ids = list(
        dict.fromkeys(
            source_id
            for match in CITATION_RE.finditer(raw_answer)
            for source_id in SOURCE_ID_RE.findall(match.group(1))
        )
    )
    marker_cited = [source_id for source_id in raw_ids if source_id in sources]
    unknown = [source_id for source_id in raw_ids if source_id not in sources]
    bindings: list[dict[str, str]] = []
    for match in CITATION_RE.finditer(raw_answer):
        claim = _claim_before_marker(raw_answer[: match.start()])
        if not claim:
            continue
        for source_id in SOURCE_ID_RE.findall(match.group(1)):
            if source_id in sources:
                bindings.append(
                    {
                        "claim": claim,
                        "source_id": source_id,
                        "validation_status": "marker_bound",
                    }
                )

    def render_citation_group(match: re.Match[str]) -> str:
        links = [
            _markdown_link(sources[source_id])
            for source_id in SOURCE_ID_RE.findall(match.group(1))
            if source_id in sources
        ]
        return "；".join(links)

    rendered = CITATION_RE.sub(render_citation_group, raw_answer)
    direct_url_source_ids = [
        source_id
        for source_id, source in sources.items()
        if any(
            candidate and candidate in raw_answer
            for candidate in {
                str(source.get("url") or "").strip(),
                str(source.get("canonical_url") or "").strip(),
            }
        )
    ]
    cited = list(dict.fromkeys([*marker_cited, *direct_url_source_ids]))
    if cited:
        status = "cited"
    elif sources and append_fallback_sources:
        fallback_sources = list(sources.values())[:3]
        rendered = rendered.rstrip() + "\n\n参考来源：\n" + "\n".join(
            f"- {_markdown_link(source)}" for source in fallback_sources
        )
        status = "fallback_sources_appended"
    elif sources:
        status = "uncited_sources_not_appended"
    else:
        status = "no_web_evidence"
    return rendered, {
        "status": status,
        "cited_source_ids": cited,
        "unknown_source_ids": unknown,
        "direct_url_source_ids": direct_url_source_ids,
        "available_source_ids": list(sources),
        "claim_level_binding": bool(bindings),
        "bindings": bindings,
    }
