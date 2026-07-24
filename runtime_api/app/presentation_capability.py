from __future__ import annotations

import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from .capability_packs import select_capability_pack
from .office_metadata import office_core_property


PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
SUPPORTED_ROLES = {
    "title",
    "section",
    "concept",
    "process",
    "comparison",
    "evidence",
    "closing",
}

CANVAS = RGBColor(246, 248, 250)
PAPER = RGBColor(255, 255, 255)
INK = RGBColor(18, 31, 49)
MUTED = RGBColor(89, 103, 119)
LINE = RGBColor(210, 218, 226)
TEAL = RGBColor(0, 139, 126)
TEAL_LIGHT = RGBColor(218, 244, 239)
BLUE = RGBColor(29, 102, 214)
BLUE_LIGHT = RGBColor(226, 236, 252)
CORAL = RGBColor(224, 95, 82)
FONT = "Noto Sans CJK SC"

OVERSTATED_TECHNICAL_CLAIMS = (
    re.compile(r"(?:模型|LLM|大语言模型)不会[“”\"「」]?(?:思考|推理).*?(?:或|和|、).*?[“”\"「」]?(?:理解)", re.IGNORECASE),
    re.compile(r"(?:模型|LLM|大语言模型)?[^。；]{0,8}不靠[“”\"「」]?思考", re.IGNORECASE),
    re.compile(r"(?:模型|LLM|大语言模型)[^。；]{0,50}并非真正的?[“”\"「」]?(?:理解|推理)", re.IGNORECASE),
    re.compile(r"(?:模型|LLM|大语言模型)没有真正的?[“”\"「」]?理解", re.IGNORECASE),
    re.compile(r"(?:模型|LLM|大语言模型)不知道[“”\"「」]?(?:意思|含义)", re.IGNORECASE),
    re.compile(r"(?:模型|LLM|大语言模型)[^。；]{0,24}没有[^。；]{0,24}(?:记忆|推理)能力", re.IGNORECASE),
    re.compile(r"(?:模型|LLM|大语言模型)[^。；]{0,50}没有真正的?(?:因果)?推理", re.IGNORECASE),
    re.compile(r"没有真正的?(?:因果)?推理", re.IGNORECASE),
    re.compile(r"(?:模型|LLM|大语言模型)?无法超越训练数据(?:覆盖)?(?:的)?(?:知识和能力)?范围", re.IGNORECASE),
    re.compile(r"训练数据之外[^。；]{0,30}无法(?:获取|知道|掌握)", re.IGNORECASE),
    re.compile(r"上下文越长[^。；]*?(?:回答|输出)[^。；]*?越(?:准确|可靠|贴合)"),
)

MISLEADING_TECHNICAL_EXPLANATIONS = (
    re.compile(r"(?:模型|LLM|大语言模型)不(?:读|处理)(?:完整)?句子", re.IGNORECASE),
    re.compile(r"(?:LLM|模型|大语言模型)[^。；]{0,24}逐字(?:生成|预测|输出)", re.IGNORECASE),
    re.compile(r"拆[^。；]{0,24}token[^。；]{0,24}(?:再)?逐个处理", re.IGNORECASE),
    re.compile(r"逐\s*token[^。；]{0,24}预测下一个词", re.IGNORECASE),
    re.compile(r"英文[^。；]{0,24}token[^。；]{0,24}(?:大约|约)[^。；]{0,12}半个词", re.IGNORECASE),
    re.compile(r"(?:token[^。；]{0,36}(?:半词|半个词)|(?:半词|半个词)[^。；]{0,36}token)", re.IGNORECASE),
    re.compile(r"(?:模型|LLM|大语言模型)[^。；]{0,30}预测(?:最可能的下一个|下一个最可能的)\s*token", re.IGNORECASE),
    re.compile(r"(?:模型|LLM|大语言模型)[^。；]{0,30}无法验证自身输出", re.IGNORECASE),
    re.compile(r"(?:模型|LLM|大语言模型)[^。；]{0,30}不具备跨会话记忆", re.IGNORECASE),
    re.compile(r"(?:大语言模型|LLM|(?<!基础)模型)[^。；]{0,30}(?:不具备|没有)持久(?:的)?记忆", re.IGNORECASE),
    re.compile(r"(?:输入|提问)[^。；]{0,50}构成(?:模型|LLM|大语言模型)处理的全部内容", re.IGNORECASE),
    re.compile(r"训练数据[^。；]{0,24}截止时间[^。；]{0,24}无法(?:获知|知道)(?:最新|实时)(?:事件|信息)", re.IGNORECASE),
    re.compile(r"每次(?:推理|对话|会话)[^。；]{0,24}独立于(?:之前|历史)(?:的)?(?:交互|对话|会话)", re.IGNORECASE),
    re.compile(r"上下文[^。；]{0,24}过长[^。；]{0,24}会被截断", re.IGNORECASE),
)

PRIVATE_EVIDENCE_INFERENCE_MARKERS = (
    "反映",
    "表明",
    "说明",
    "意味着",
    "证明",
    "因此",
    "由此可见",
    "可见",
    "体现",
)

PRIVATE_EVIDENCE_EVALUATIVE_MARKERS = (
    "效率良好",
    "表现良好",
    "表现优秀",
    "能力较强",
    "较为可控",
    "风险可控",
    "较为理想",
    "高效",
    "低效",
    "健康",
    "稳健",
    "当日内闭环",
    "效率的基本面",
)

PRIVATE_EVIDENCE_ABSENCE_ASSERTION_MARKERS = (
    "尚未分析",
    "尚未统计",
    "未分析",
    "未统计",
)

PRIVATE_EVIDENCE_ABSENCE_ASSERTION_PATTERNS = (
    re.compile(r"(?:未提供|缺少|暂无|尚无)[^。；]{0,24}(?:目标对比|目标值|基准对比)"),
)

PRIVATE_EVIDENCE_INFORMATION_GAP_FORBIDDANCE_PATTERNS = (
    re.compile(r"(?:不得|不要|禁止)(?:编造|添加|补充)[^。；]{0,48}信息缺口"),
)

PRIVATE_EVIDENCE_INFORMATION_GAP_PATTERNS = (
    re.compile(
        r"(?:现有|当前|以上)?(?:数据|证据|指标)?(?:不足以|无法)"
        r"[^。；]{0,40}(?:评价|判断|说明|支持|确认)"
    ),
    re.compile(
        r"(?:需|需要|尚需|还需)(?:进一步)?"
        r"(?:分析|补充|核对|明确|确定|收集|获取|验证)[^。；]{0,40}"
    ),
    re.compile(r"(?:尚未|未)(?:经过|完成)?(?:数据)?验证"),
    re.compile(r"(?:暂无|尚无)[^。；]{0,24}(?:进一步)?(?:解释|说明|分析)"),
    re.compile(r"(?:行动|事项|方案)?[^。；]{0,16}(?:尚未|未)(?:实施|执行|开始|落地)"),
)

PRIVATE_EVIDENCE_QUALIFIERS = (
    "可能",
    "或许",
    "待验证",
    "待评估",
    "假设",
    "推测",
    "初步判断",
    "需验证",
    "需要验证",
    "尚待验证",
    "不能据此",
    "无法据此",
)

PRIVATE_EVIDENCE_PROVENANCE_MARKERS = ("来自", "源自")
PRIVATE_EVIDENCE_GENERIC_PROVENANCE = (
    "用户提供",
    "当前请求",
    "已提供记录",
    "已提供资料",
    "证据包",
)


class PresentationSpecError(ValueError):
    pass


def _pack_and_profile() -> tuple[Any, dict[str, Any]]:
    pack = select_capability_pack("pptx")
    if pack is None:
        raise PresentationSpecError("presentation capability pack is not installed")
    return pack, dict(pack.quality_profile)


def validate_presentation_spec(spec: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise PresentationSpecError("presentation specification must be an object")

    for key in ("title", "audience", "purpose"):
        if not str(spec.get(key) or "").strip():
            raise PresentationSpecError(f"presentation {key} is required")

    slides = spec.get("slides")
    if isinstance(slides, str):
        try:
            decoded_slides = json.loads(slides)
        except json.JSONDecodeError:
            decoded_slides = _decode_tool_transport_list(slides)
        if isinstance(decoded_slides, list):
            slides = decoded_slides
    if not isinstance(slides, list) or not slides:
        raise PresentationSpecError("presentation slides must be a non-empty list")

    _, profile = _pack_and_profile()
    minimum_slide_count = int(profile.get("minimum_slide_count") or 1)
    maximum_chars = int(profile.get("maximum_text_chars_per_slide") or 700)
    require_visual_at = int(profile.get("require_visual_for_slide_count") or 4)
    if len(slides) < minimum_slide_count:
        raise PresentationSpecError(f"presentation requires at least {minimum_slide_count} slide(s)")

    seen_titles: set[str] = set()
    visual_slide_count = 0
    normalized_slides: list[dict[str, Any]] = []
    for index, raw_slide in enumerate(slides, start=1):
        if not isinstance(raw_slide, dict):
            raise PresentationSpecError(f"slide {index} must be an object")
        slide = _normalize_slide_schema(dict(raw_slide))
        role = str(slide.get("role") or "evidence").strip().lower()
        if role not in SUPPORTED_ROLES:
            raise PresentationSpecError(f"slide {index} has unsupported role: {role}")
        title = str(slide.get("title") or "").strip()
        if not title:
            raise PresentationSpecError(f"slide {index} title is required")
        normalized_title = re.sub(r"\s+", " ", title).casefold()
        if normalized_title in seen_titles:
            raise PresentationSpecError(f"duplicate slide title: {title}")
        seen_titles.add(normalized_title)

        overstated_claim = _find_overstated_technical_claim(slide)
        if overstated_claim:
            raise PresentationSpecError(
                f"slide {index} contains an overstated technical claim: {overstated_claim}"
            )
        misleading_explanation = _find_misleading_technical_explanation(slide)
        if misleading_explanation:
            raise PresentationSpecError(
                f"slide {index} contains a misleading technical explanation: "
                f"{misleading_explanation}"
            )
        _validate_slide_item_limits(slide, role=role, profile=profile, index=index)

        text_chars = _text_character_count(slide)
        if text_chars > maximum_chars:
            raise PresentationSpecError(
                f"slide {index} exceeds {maximum_chars} characters ({text_chars})"
            )
        if _has_visual_explanation(slide, role):
            visual_slide_count += 1

        slide["role"] = role
        slide["title"] = title
        slide["source_evidence_ids"] = _stable_strings(slide.get("source_evidence_ids") or [])
        normalized_slides.append(slide)

    if len(slides) >= require_visual_at and visual_slide_count == 0:
        raise PresentationSpecError(
            f"a deck with {len(slides)} slides requires at least one visual explanation"
        )

    normalized = dict(spec)
    normalized["title"] = str(spec["title"]).strip()
    normalized["audience"] = str(spec["audience"]).strip()
    normalized["purpose"] = str(spec["purpose"]).strip()
    normalized["slides"] = normalized_slides
    return normalized


def _decode_tool_transport_list(value: str) -> list[Any] | None:
    """Recover a valid array followed by the single object brace leaked by some tool transports."""
    try:
        decoded, end = json.JSONDecoder().raw_decode(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, list) or value[end:].strip() != "}":
        return None
    return decoded


def render_presentation(
    spec: dict[str, Any],
    output_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    task_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = validate_presentation_spec(spec)
    request_contract = validate_presentation_request_contract(
        normalized,
        task_packet or {},
    )
    _validate_private_evidence_grounding(normalized, task_packet or {})
    pack, profile = _pack_and_profile()
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    deck = Presentation()
    deck.slide_width = Inches(13.333)
    deck.slide_height = Inches(7.5)
    deck.core_properties.title = office_core_property(normalized["title"])
    deck.core_properties.subject = office_core_property(normalized["purpose"])
    deck.core_properties.author = office_core_property("Nomi Presentation Studio")
    deck.core_properties.comments = office_core_property(
        f"Capability pack {pack.pack_id}@{pack.version}"
    )

    for number, slide_spec in enumerate(normalized["slides"], start=1):
        _render_slide(deck, slide_spec, normalized, number=number)

    rendered_text = _normalize_match_text(
        "\n".join(
            shape.text
            for slide in deck.slides
            for shape in slide.shapes
            if hasattr(shape, "text")
        )
    )
    semantic_segments = [
        segment
        for slide in normalized["slides"]
        for segment in _semantic_segments(slide)
    ]
    rendered_segments = sum(
        1
        for segment in semantic_segments
        if _normalize_match_text(segment) in rendered_text
    )
    rendered_content_coverage = (
        rendered_segments / len(semantic_segments) if semantic_segments else 1.0
    )
    deck.save(str(output))

    source_evidence_ids = _stable_strings(
        evidence_id
        for slide in normalized["slides"]
        for evidence_id in slide.get("source_evidence_ids") or []
    )
    evidence_map: OrderedDict[str, list[str]] = OrderedDict()
    for number, slide in enumerate(normalized["slides"], start=1):
        for evidence_id in slide.get("source_evidence_ids") or []:
            evidence_map.setdefault(evidence_id, []).append(f"slide_{number}")

    roles = [slide["role"] for slide in normalized["slides"]]
    maximum_text = max(_text_character_count(slide) for slide in normalized["slides"])
    visual_slide_count = sum(
        1
        for slide in normalized["slides"]
        if _has_visual_explanation(slide, slide["role"])
    )
    checks = {
            "titles_unique": True,
            "text_density_within_limit": maximum_text
            <= int(profile.get("maximum_text_chars_per_slide") or 700),
            "visual_explanation_present": visual_slide_count > 0
            or len(roles) < int(profile.get("require_visual_for_slide_count") or 4),
            "editable_native_shapes": True,
            "evidence_map_complete": all(
                evidence_id in evidence_map for evidence_id in source_evidence_ids
            ),
            "semantic_content_rendered": rendered_content_coverage >= 0.9,
            "request_contract_matched": request_contract["status"] == "passed",
        }
    quality_report = {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "layout_kind_count": len(set(roles)),
        "visual_slide_count": visual_slide_count,
        "maximum_slide_text_chars": maximum_text,
        "rendered_content_coverage": round(rendered_content_coverage, 3),
        "semantic_segments_total": len(semantic_segments),
        "semantic_segments_rendered": rendered_segments,
        "request_contract": request_contract,
    }
    manifest = {
        "artifact_type": "pptx",
        "filename": output.name,
        "mime_type": PPTX_MIME,
        "file_path": str(output),
        "capability_pack_id": pack.pack_id,
        "capability_pack_version": pack.version,
        "source_evidence_ids": source_evidence_ids,
        "evidence_to_content_map": dict(evidence_map) or {"artifact": ["slide_1"]},
        "slide_count": len(normalized["slides"]),
        "slide_roles": roles,
        "quality_report": quality_report,
        "summary": f"Generated and verified {len(roles)} editable slides for {normalized['audience']}",
    }
    if manifest_path is not None:
        target = Path(manifest_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def validate_presentation_request_contract(
    spec: dict[str, Any],
    task_packet: dict[str, Any],
) -> dict[str, Any]:
    if not task_packet:
        return {
            "status": "passed",
            "checks": ["no_task_packet_supplied"],
            "expected_slide_count": None,
            "actual_slide_count": len(spec.get("slides") or []),
            "audience_matched": True,
            "goal_terms_missing": [],
            "required_topics_missing": [],
        }

    expected_slide_count = requested_slide_count_from_packet(task_packet)
    actual_slide_count = len(spec.get("slides") or [])
    if expected_slide_count is not None and actual_slide_count != expected_slide_count:
        raise PresentationSpecError(
            f"presentation task contract expected {expected_slide_count} slides, got {actual_slide_count}"
        )

    requirements = _requirements_contract_from_packet(task_packet)
    expected_audience = str(requirements.get("audience") or "").strip()
    actual_audience = str(spec.get("audience") or "").strip()
    audience_matched = _audience_matches(expected_audience, actual_audience)
    if not audience_matched:
        raise PresentationSpecError(
            "presentation audience does not match task contract: "
            f"expected {expected_audience!r}, got {actual_audience!r}"
        )

    presentation_text = _normalize_match_text(
        "\n".join(
            segment
            for slide in spec.get("slides") or []
            if isinstance(slide, dict)
            for segment in _semantic_segments(slide)
        )
    )
    goal_terms = _goal_subject_terms(task_packet)
    goal_terms_missing = [
        term for term in goal_terms if not _goal_term_is_covered(term, presentation_text)
    ]
    if goal_terms_missing:
        raise PresentationSpecError(
            "presentation does not cover task goal terms: " + ", ".join(goal_terms_missing)
        )

    required_topics = _required_topics_from_packet(task_packet)
    required_topics_missing = [
        topic
        for topic in required_topics
        if not _topic_is_covered(topic, presentation_text, spec=spec)
    ]
    if required_topics_missing:
        raise PresentationSpecError(
            "presentation does not cover required topics: " + ", ".join(required_topics_missing)
        )

    slide_outline_violations = _slide_outline_violations(spec, requirements=requirements)
    if slide_outline_violations:
        raise PresentationSpecError(
            "presentation slide outline mismatch: " + "; ".join(slide_outline_violations)
        )

    return {
        "status": "passed",
        "checks": [
            "explicit_slide_count_matched" if expected_slide_count is not None else "slide_count_not_explicit",
            "audience_matched" if expected_audience else "audience_not_explicit",
            "goal_terms_covered" if goal_terms else "goal_terms_not_extractable",
            "required_topics_covered" if required_topics else "required_topics_not_explicit",
            "slide_outline_matched" if requirements.get("slide_outline") else "slide_outline_not_explicit",
        ],
        "expected_slide_count": expected_slide_count,
        "actual_slide_count": actual_slide_count,
        "audience_matched": audience_matched,
        "goal_terms_missing": goal_terms_missing,
        "required_topics_missing": required_topics_missing,
        "slide_outline_violations": slide_outline_violations,
    }


def requested_slide_count_from_packet(packet: dict[str, Any]) -> int | None:
    requirements = _requirements_contract_from_packet(packet)
    raw_count = requirements.get("page_count") or requirements.get("slide_count") or requirements.get("pages")
    if raw_count is not None:
        try:
            return max(1, min(int(raw_count), 20))
        except (TypeError, ValueError):
            parsed = _requested_slide_count_from_text(str(raw_count))
            if parsed is not None:
                return parsed

    plan_input = packet.get("plan_input") if isinstance(packet.get("plan_input"), dict) else {}
    for candidate in (
        plan_input.get("user_request"),
        plan_input.get("original_goal"),
        packet.get("original_goal"),
        packet.get("original_goal_summary"),
        packet.get("user_request"),
        packet.get("goal"),
    ):
        parsed = _requested_slide_count_from_text(str(candidate or ""))
        if parsed is not None:
            return parsed
    return None


def _requested_slide_count_from_text(text: str) -> int | None:
    clean = unquote(str(text or "")).replace("_", " ")
    match = re.search(
        r"(?i)(?<!\d)(\d{1,2})\s*(?:页|張|张|p|pages?|slides?|slide|deck pages?)",
        clean,
    )
    if match:
        return max(1, min(int(match.group(1)), 20))
    chinese_digits = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    match = re.search(r"([一二两三四五六七八九十])\s*(?:页|張|张)", clean)
    return chinese_digits.get(match.group(1)) if match else None


def _requirements_contract_from_packet(packet: dict[str, Any]) -> dict[str, Any]:
    plan_input = packet.get("plan_input") if isinstance(packet.get("plan_input"), dict) else {}
    candidates = (
        packet.get("requirements_contract"),
        plan_input.get("requirements_contract"),
        (packet.get("context") or {}).get("requirements_contract") if isinstance(packet.get("context"), dict) else None,
        (packet.get("task_route") or {}).get("requirements_contract") if isinstance(packet.get("task_route"), dict) else None,
        (packet.get("route_decision") or {}).get("requirements_contract") if isinstance(packet.get("route_decision"), dict) else None,
    )
    for candidate in candidates:
        if isinstance(candidate, dict):
            return dict(candidate)
    return {}


def _validate_private_evidence_grounding(
    spec: dict[str, Any],
    task_packet: dict[str, Any],
) -> None:
    """Reject unsupported assertions in strict private-evidence presentations.

    The model may restate supplied facts. It may also propose a hypothesis when
    the wording explicitly says that the hypothesis still needs validation.
    What it may not do is turn a metric into a confident business conclusion
    that is absent from the evidence pack.
    """

    requirements = _requirements_contract_from_packet(task_packet)
    if str(requirements.get("source_policy") or "").strip() != "must_use_private_evidence":
        return

    evidence_text = _private_evidence_corpus(task_packet)
    normalized_evidence = _normalize_match_text(evidence_text)
    forbids_invented_information_gaps = any(
        pattern.search(evidence_text)
        for pattern in PRIVATE_EVIDENCE_INFORMATION_GAP_FORBIDDANCE_PATTERNS
    )
    for slide_index, slide in enumerate(spec.get("slides") or [], start=1):
        if not isinstance(slide, dict):
            continue
        for segment in _semantic_segments(slide):
            normalized_segment = _normalize_match_text(segment)
            if not normalized_segment or normalized_segment in normalized_evidence:
                continue
            has_qualifier = any(
                _normalize_match_text(marker) in normalized_segment
                for marker in PRIVATE_EVIDENCE_QUALIFIERS
            )
            has_unsupported_assertion = any(
                _normalize_match_text(marker) in normalized_segment
                for marker in (
                    *PRIVATE_EVIDENCE_INFERENCE_MARKERS,
                    *PRIVATE_EVIDENCE_EVALUATIVE_MARKERS,
                    *PRIVATE_EVIDENCE_ABSENCE_ASSERTION_MARKERS,
                )
            )
            has_unsupported_provenance = _has_unsupported_private_evidence_provenance(
                segment,
                normalized_evidence,
            )
            has_unsupported_absence_assertion = any(
                pattern.search(segment)
                for pattern in PRIVATE_EVIDENCE_ABSENCE_ASSERTION_PATTERNS
            )
            has_forbidden_information_gap = (
                forbids_invented_information_gaps
                and any(
                    pattern.search(segment)
                    for pattern in PRIVATE_EVIDENCE_INFORMATION_GAP_PATTERNS
                )
            )
            if (
                (has_unsupported_assertion and not has_qualifier)
                or has_unsupported_provenance
                or has_unsupported_absence_assertion
                or has_forbidden_information_gap
            ):
                raise PresentationSpecError(
                    "unsupported private-evidence claim on "
                    f"slide {slide_index}: {segment}"
                )


def _has_unsupported_private_evidence_provenance(
    segment: str,
    normalized_evidence: str,
) -> bool:
    normalized_segment = _normalize_match_text(segment)
    for marker in PRIVATE_EVIDENCE_PROVENANCE_MARKERS:
        normalized_marker = _normalize_match_text(marker)
        marker_index = normalized_segment.find(normalized_marker)
        if marker_index < 0:
            continue
        attribution = normalized_segment[marker_index + len(normalized_marker) :].strip(
            "：:，,。；;（）()【】[]"
        )
        if not attribution:
            return True
        if any(
            attribution.startswith(_normalize_match_text(generic))
            for generic in PRIVATE_EVIDENCE_GENERIC_PROVENANCE
        ):
            return False
        if attribution in normalized_evidence:
            return False
        return True
    return False


def _private_evidence_corpus(task_packet: dict[str, Any]) -> str:
    plan_input = (
        task_packet.get("plan_input")
        if isinstance(task_packet.get("plan_input"), dict)
        else {}
    )
    values: list[str] = []
    for value in (
        task_packet.get("original_goal"),
        task_packet.get("original_goal_summary"),
        task_packet.get("user_request"),
        task_packet.get("goal"),
        plan_input.get("user_request"),
        plan_input.get("original_goal"),
    ):
        if str(value or "").strip():
            values.append(str(value))
    for item in _packet_evidence_items(task_packet):
        for key in ("content", "excerpt", "text", "summary"):
            value = item.get(key)
            if str(value or "").strip():
                values.append(str(value))
    return "\n".join(values)


def _goal_subject_terms(packet: dict[str, Any]) -> list[str]:
    plan_input = packet.get("plan_input") if isinstance(packet.get("plan_input"), dict) else {}
    requirements = _requirements_contract_from_packet(packet)
    contract_topic = str(requirements.get("topic") or "").strip()
    goal = unquote(str(
        contract_topic
        or packet.get("original_goal")
        or packet.get("original_goal_summary")
        or plan_input.get("user_request")
        or packet.get("goal")
        or ""
    ))
    ignored = {
        "ppt",
        "pptx",
        "slide",
        "slides",
        "deck",
        "page",
        "pages",
        "make",
        "create",
        "about",
        "for",
        "titled",
        "include",
        "summary",
        "nomi",
        "real",
        "founders",
        "ordinary",
        "people",
        "explaining",
        "explain",
        "how",
        "works",
        "work",
        "understand",
        "with",
        "from",
        "into",
        "and",
        "the",
    }
    return _stable_strings(
        token
        for token in re.findall(r"[A-Za-z][A-Za-z0-9.+#-]{1,30}", goal)
        if token.casefold() not in ignored
    )


def _goal_term_is_covered(term: str, presentation_text: str) -> bool:
    normalized = _normalize_match_text(term)
    aliases = {
        "llm": ("llm", "大语言模型", "语言模型"),
        "ai": ("ai", "人工智能"),
        "asr": ("asr", "语音识别", "自动语音识别"),
        "rag": ("rag", "检索增强生成"),
    }
    return any(
        _normalize_match_text(candidate) in presentation_text
        for candidate in aliases.get(normalized, (normalized,))
    )


def _required_topics_from_packet(packet: dict[str, Any]) -> list[str]:
    requirements = _requirements_contract_from_packet(packet)
    topics: list[str] = []
    for explicit in (
        requirements.get("required_topics"),
        requirements.get("topics"),
        requirements.get("must_include"),
    ):
        if isinstance(explicit, str):
            topics.extend(_split_required_topics(explicit))
        elif isinstance(explicit, list):
            topics.extend(str(item).strip() for item in explicit if str(item).strip())

    for item in _packet_evidence_items(packet):
        content = str(item.get("content") or item.get("excerpt") or "")
        for match in re.finditer(
            r"(?:必须|需要|应当|务必)(?:解释|包含|覆盖|说明|讲清)([^。；\n]+)",
            content,
        ):
            topics.extend(_split_required_topics(match.group(1)))
    return _stable_strings(topic for topic in topics if len(_normalize_match_text(topic)) >= 2)


def _slide_outline_violations(
    spec: dict[str, Any],
    *,
    requirements: dict[str, Any],
) -> list[str]:
    slides = [slide for slide in spec.get("slides") or [] if isinstance(slide, dict)]
    violations: list[str] = []
    for item in requirements.get("slide_outline") or []:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("slide_number") or 0)
        except (TypeError, ValueError):
            continue
        if number <= 0:
            continue
        if number > len(slides):
            violations.append(f"slide {number} is missing")
            continue
        slide = slides[number - 1]
        expected_title = str(item.get("title") or "").strip()
        actual_title = str(slide.get("title") or "").strip()
        if expected_title and _normalize_match_text(expected_title) not in _normalize_match_text(actual_title):
            violations.append(f"slide {number} missing title {expected_title}")
        expected_subtitle = str(item.get("subtitle") or "").strip()
        actual_subtitle = str(slide.get("subtitle") or "").strip()
        if expected_subtitle and _normalize_match_text(expected_subtitle) not in _normalize_match_text(actual_subtitle):
            violations.append(f"slide {number} missing subtitle {expected_subtitle}")
        slide_text = _normalize_match_text("\n".join(_semantic_segments(slide)))
        for required in item.get("must_include") or []:
            required_text = str(required or "").strip()
            if required_text and not _topic_is_covered(
                required_text,
                slide_text,
                spec={"slides": [slide]},
            ):
                violations.append(f"slide {number} missing {required_text}")
    return violations


def _packet_evidence_items(packet: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for owner in (packet.get("context"), packet.get("plan_input")):
        if not isinstance(owner, dict):
            continue
        pack = owner.get("evidence_pack")
        if not isinstance(pack, dict):
            continue
        items.extend(item for item in pack.get("items") or [] if isinstance(item, dict))
    return items


def _split_required_topics(value: str) -> list[str]:
    clean = re.sub(r"(?:以及|并且|同时)", "、", str(value or ""))
    clean = re.sub(r"和(?=[\u4e00-\u9fffA-Za-z])", "、", clean)
    return [
        part.strip(" ，,、:：。；;\"'“”")
        for part in re.split(r"[、,，;/；]", clean)
        if part.strip(" ，,、:：。；;\"'“”")
    ]


def _audience_matches(expected: str, actual: str) -> bool:
    if not expected:
        return True
    expected_normalized = _normalize_match_text(expected)
    actual_normalized = _normalize_match_text(actual)
    if not expected_normalized or not actual_normalized:
        return False
    if expected_normalized in actual_normalized or actual_normalized in expected_normalized:
        return True
    expected_classes = _audience_classes(expected_normalized)
    actual_classes = _audience_classes(actual_normalized)
    return bool(expected_classes and expected_classes.intersection(actual_classes))


def _audience_classes(value: str) -> set[str]:
    classes: set[str] = set()
    if any(token in value for token in ("普通人", "普通大众", "大众", "非技术", "无ai技术背景", "无技术背景")):
        classes.add("general_public")
    if any(token in value for token in ("产品团队", "产品经理", "产品人员")):
        classes.add("product")
    if any(token in value for token in ("管理层", "管理者", "决策者", "高管")):
        classes.add("management")
    if any(token in value for token in ("开发者", "工程师", "技术团队", "技术人员")):
        classes.add("technical")
    if any(token in value for token in ("学生", "学习者", "课堂", "学员")):
        classes.add("learner")
    return classes


def _topic_is_covered(
    topic: str,
    presentation_text: str,
    *,
    spec: dict[str, Any] | None = None,
) -> bool:
    normalized = _normalize_match_text(topic)
    if normalized in presentation_text:
        return True
    if _structural_topic_is_covered(normalized, spec or {}):
        return True
    semantic_segments = [
        _normalize_match_text(segment)
        for slide in (spec or {}).get("slides") or []
        if isinstance(slide, dict)
        for segment in _semantic_segments(slide)
        if str(segment or "").strip()
    ]
    requirement_parts = _required_topic_match_parts(topic)
    if requirement_parts and all(
        _topic_part_is_covered(
            part,
            presentation_text,
            semantic_segments=semantic_segments,
        )
        for part in requirement_parts
    ):
        return True
    latin = re.findall(r"[a-z][a-z0-9.+#-]*", normalized)
    chinese = re.sub(r"[a-z0-9.+#-]+", "", normalized)
    chinese_tokens = [
        token
        for token in ("上下文", "模型", "能力", "边界", "预测", "输入", "输出", "训练", "数据")
        if token in chinese
    ]
    required_parts = _stable_strings([*latin, *chinese_tokens])
    return bool(required_parts) and all(part in presentation_text for part in required_parts)


def _structural_topic_is_covered(topic: str, spec: dict[str, Any]) -> bool:
    if "标题" not in topic or not any(token in topic for token in ("摘要", "结论")):
        return False
    slides = [slide for slide in spec.get("slides") or [] if isinstance(slide, dict)]
    if not slides:
        return False
    title_slide = slides[0]
    if str(title_slide.get("role") or "").strip().lower() != "title":
        return False
    has_title = bool(str(title_slide.get("title") or "").strip())
    has_summary = bool(
        str(title_slide.get("takeaway") or "").strip()
        or _list_text(title_slide.get("preview_points"))
    )
    return has_title and has_summary


def _topic_part_is_covered(
    part: str,
    presentation_text: str,
    *,
    semantic_segments: list[str] | None = None,
) -> bool:
    if part in presentation_text:
        return True
    compact_part = part.replace("为", "")
    compact_text = presentation_text.replace("为", "")
    if compact_part and compact_part in compact_text:
        return True

    if compact_part in {"标注未知", "明确标注未知"} and semantic_segments:
        return any("未知" in segment for segment in semantic_segments)

    unknown_obligation = re.fullmatch(r"(.{2,8})未知", compact_part)
    if unknown_obligation and semantic_segments:
        subject = unknown_obligation.group(1)
        pattern = re.compile(re.escape(subject) + r".{0,12}未知")
        return any(pattern.search(segment.replace("为", "")) for segment in semantic_segments)
    return False


def _required_topic_match_parts(topic: str) -> list[str]:
    """Extract the semantic obligations from a prose requirement.

    Requirements often combine an action and several checks, for example
    ``展示上述四项指标，其中原因未知必须明确标注未知``.  A deck should not
    have to repeat that instruction verbatim; it must contain each meaningful
    obligation (``四项指标``, ``原因未知`` and ``标注未知``).
    """

    positive_requirement = re.split(
        r"[，,；;。]?\s*(?:不添加|不要|不得|不应|禁止|避免|无需)",
        str(topic or ""),
        maxsplit=1,
    )[0]
    clauses = re.split(
        r"(?:其中|必须|需要|应当|务必|同时|以及|并且|[与及、，,：:；;])",
        positive_requirement,
    )
    parts: list[str] = []
    for clause in clauses:
        clause = re.sub(r"^(?:请|只)+", "", clause.strip())
        cleaned = re.sub(
            r"^(?:请|展示|说明|解释|总结|列出|包含|覆盖|讲清|呈现|介绍)+",
            "",
            clause,
        )
        cleaned = re.sub(r"(?:上述|以下|明确)", "", cleaned)
        cleaned = re.sub(r"^[一二两三四五六七八九十百\d]+项", "", cleaned)
        normalized = _normalize_match_text(cleaned)
        if len(normalized) >= 2:
            parts.append(normalized)
    return _stable_strings(parts)


def _render_slide(
    deck: Presentation,
    slide_spec: dict[str, Any],
    presentation_spec: dict[str, Any],
    *,
    number: int,
) -> None:
    role = slide_spec["role"]
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    if role == "title":
        _render_title_slide(slide, slide_spec, presentation_spec)
    elif role == "section" and _has_comparison_columns(slide_spec):
        _render_comparison_slide(slide, slide_spec, number)
    elif role == "section":
        _render_section_slide(slide, slide_spec, number)
    elif role == "concept":
        _render_concept_slide(slide, slide_spec, number)
    elif role == "process":
        _render_process_slide(slide, slide_spec, number)
    elif role == "comparison":
        _render_comparison_slide(slide, slide_spec, number)
    elif role == "closing":
        _render_closing_slide(slide, slide_spec, presentation_spec, number)
    else:
        _render_evidence_slide(slide, slide_spec, number)


def _render_title_slide(slide: Any, spec: dict[str, Any], deck_spec: dict[str, Any]) -> None:
    _set_background(slide, INK)
    _add_rect(slide, 0.62, 0.72, 0.12, 5.74, TEAL)
    _add_text(slide, 1.08, 0.9, 10.95, 1.75, spec["title"], 34, PAPER, bold=True)
    subtitle = str(spec.get("subtitle") or deck_spec.get("purpose") or "").strip()
    _add_text(slide, 1.12, 2.85, 9.65, 1.15, subtitle, 19, RGBColor(196, 207, 218))
    _add_text(
        slide,
        1.12,
        5.6,
        8.6,
        0.48,
        f"为 {deck_spec['audience']} 准备",
        12,
        RGBColor(157, 174, 191),
    )
    preview = _list_text(spec.get("preview_points"))
    if preview:
        _add_text(
            slide,
            1.12,
            4.12,
            9.9,
            0.72,
            "  ·  ".join(preview[:4]),
            12,
            RGBColor(157, 174, 191),
        )
    _add_pill(slide, 10.62, 5.45, 1.72, 0.56, "NOMI BRIEF", TEAL, PAPER)


def _render_section_slide(slide: Any, spec: dict[str, Any], number: int) -> None:
    _set_background(slide, CANVAS)
    _add_text(slide, 0.75, 0.7, 1.0, 0.45, f"{number:02d}", 14, TEAL, bold=True)
    _add_text(slide, 1.25, 2.0, 10.8, 1.5, spec["title"], 31, INK, bold=True, align=PP_ALIGN.CENTER)
    takeaway = str(spec.get("takeaway") or spec.get("subtitle") or "").strip()
    _add_text(slide, 2.05, 3.65, 9.2, 0.95, takeaway, 17, MUTED, align=PP_ALIGN.CENTER)
    _add_rect(slide, 5.64, 5.25, 2.05, 0.09, TEAL)
    _add_footer(slide, number, spec)


def _render_concept_slide(slide: Any, spec: dict[str, Any], number: int) -> None:
    _base_content_slide(slide, spec, number)
    takeaway = str(spec.get("takeaway") or "").strip()
    if takeaway:
        takeaway_font_size = 16 if _text_character_count(takeaway) > 34 else 18
        _add_text(
            slide,
            0.82,
            1.52,
            5.9,
            1.18,
            takeaway,
            takeaway_font_size,
            INK,
            bold=True,
        )
    _add_bullets(slide, 0.82, 2.82, 5.45, 2.72, _list_text(spec.get("points")), 15)
    visual = spec.get("visual") if isinstance(spec.get("visual"), dict) else {}
    nodes = _visual_nodes(visual.get("nodes")) or [
        {"label": "输入", "content": ""},
        {"label": "理解", "content": ""},
        {"label": "输出", "content": ""},
    ]
    nodes = nodes[:4]
    y = 1.55
    card_height = 1.08
    card_gap = 0.18
    for index, node in enumerate(nodes):
        color = TEAL if index == len(nodes) - 1 else BLUE
        light = TEAL_LIGHT if index == len(nodes) - 1 else BLUE_LIGHT
        label = node["label"]
        detail = node["content"]
        _add_round_rect(slide, 7.25, y, 4.72, card_height, light, LINE)
        _add_circle(slide, 7.49, y + 0.34, 0.4, color)
        if detail:
            label_font_size = 11 if _text_character_count(label) > 30 else 12
            _add_text(
                slide,
                8.08,
                y + 0.07,
                3.55,
                0.48,
                label,
                label_font_size,
                INK,
                bold=True,
            )
            detail_font_size = 9 if _text_character_count(detail) > 24 else 10
            _add_text(slide, 8.08, y + 0.53, 3.55, 0.42, detail, detail_font_size, MUTED)
        else:
            label_font_size = 11 if _text_character_count(label) > 30 else 12
            _add_text(
                slide,
                8.08,
                y + 0.1,
                3.55,
                0.82,
                label,
                label_font_size,
                INK,
                bold=True,
            )
        if index < len(nodes) - 1:
            _add_text(
                slide,
                9.24,
                y + card_height,
                0.65,
                card_gap,
                "↓",
                10,
                MUTED,
                align=PP_ALIGN.CENTER,
            )
        y += card_height + card_gap


def _render_process_slide(slide: Any, spec: dict[str, Any], number: int) -> None:
    _base_content_slide(slide, spec, number)
    takeaway = str(spec.get("takeaway") or "").strip()
    _add_text(slide, 0.82, 1.52, 11.55, 0.75, takeaway, 18, MUTED)
    steps = _list_text(spec.get("steps")) or _list_text(spec.get("points")) or ["开始", "处理", "完成"]
    steps = steps[:5]
    usable_width = 11.7
    card_width = min(2.55, (usable_width - (len(steps) - 1) * 0.25) / len(steps))
    total = card_width * len(steps) + 0.25 * (len(steps) - 1)
    x = (13.333 - total) / 2
    for index, step in enumerate(steps, start=1):
        _add_round_rect(slide, x, 2.66, card_width, 2.2, PAPER, LINE)
        _add_circle(slide, x + 0.18, 2.88, 0.5, TEAL if index == len(steps) else BLUE)
        _add_text(slide, x + 0.18, 2.98, 0.5, 0.25, str(index), 11, PAPER, bold=True, align=PP_ALIGN.CENTER)
        _add_text(slide, x + 0.22, 3.63, card_width - 0.44, 0.78, step, 15, INK, bold=True, align=PP_ALIGN.CENTER)
        if index < len(steps):
            _add_text(slide, x + card_width, 3.49, 0.25, 0.4, "→", 16, MUTED, align=PP_ALIGN.CENTER)
        x += card_width + 0.25


def _render_comparison_slide(slide: Any, spec: dict[str, Any], number: int) -> None:
    _base_content_slide(slide, spec, number)
    left = spec.get("left") if isinstance(spec.get("left"), dict) else {"label": "一侧", "items": []}
    right = spec.get("right") if isinstance(spec.get("right"), dict) else {"label": "另一侧", "items": []}
    _comparison_column(slide, 0.82, 1.62, 5.63, 4.35, left, BLUE, BLUE_LIGHT)
    _comparison_column(slide, 6.88, 1.62, 5.63, 4.35, right, TEAL, TEAL_LIGHT)
    _add_pill(slide, 6.13, 3.15, 1.05, 0.52, "VS", INK, PAPER)


def _render_evidence_slide(slide: Any, spec: dict[str, Any], number: int) -> None:
    _base_content_slide(slide, spec, number)
    takeaway = str(spec.get("takeaway") or "").strip()
    if takeaway:
        _add_text(slide, 0.82, 1.48, 11.65, 0.78, takeaway, 19, INK, bold=True)
    points = _list_text(spec.get("points")) or _list_text(spec.get("bullets"))
    _add_bullets(slide, 0.9, 2.58, 7.45, 3.25, points, 16)
    evidence_ids = _list_text(spec.get("source_evidence_ids"))
    _add_round_rect(slide, 9.15, 2.0, 3.18, 2.95, PAPER, LINE)
    _add_text(slide, 9.48, 2.32, 2.55, 0.45, "证据边界", 11, TEAL, bold=True)
    evidence_text = "\n".join(_audience_source_names(evidence_ids))
    _add_text(slide, 9.48, 2.98, 2.52, 1.5, evidence_text, 12, MUTED)


def _render_closing_slide(
    slide: Any,
    spec: dict[str, Any],
    deck_spec: dict[str, Any],
    number: int,
) -> None:
    _set_background(slide, INK)
    _add_text(slide, 0.82, 0.72, 1.1, 0.4, "NEXT", 11, TEAL, bold=True)
    _add_text(slide, 0.82, 1.42, 11.35, 1.25, spec["title"], 30, PAPER, bold=True)
    takeaway = str(spec.get("takeaway") or deck_spec.get("desired_action") or "").strip()
    _add_text(slide, 0.86, 2.86, 10.9, 0.95, takeaway, 18, RGBColor(202, 213, 223))
    strengths = _list_text(spec.get("strengths"))
    limits = _list_text(spec.get("limits"))
    if strengths or limits:
        _dark_list_panel(slide, 0.86, 4.03, 5.55, 2.0, "适合", strengths, BLUE)
        _dark_list_panel(slide, 6.7, 4.03, 5.55, 2.0, "注意", limits, TEAL)
        _add_text(
            slide,
            11.65,
            6.72,
            0.8,
            0.28,
            f"{number:02d}",
            10,
            RGBColor(133, 153, 174),
            align=PP_ALIGN.RIGHT,
        )
        return

    actions = _list_text(spec.get("actions")) or _list_text(spec.get("points"))
    x = 0.86
    for index, action in enumerate(actions[:4], start=1):
        width = min(2.82, max(2.15, 10.8 / max(1, len(actions[:4]))))
        _add_round_rect(slide, x, 4.45, width, 1.25, RGBColor(31, 48, 68), RGBColor(62, 82, 103))
        _add_text(slide, x + 0.2, 4.68, 0.4, 0.3, f"{index:02d}", 11, TEAL, bold=True)
        _add_text(slide, x + 0.2, 5.03, width - 0.4, 0.42, action, 13, PAPER, bold=True)
        x += width + 0.22
    _add_text(slide, 11.65, 6.72, 0.8, 0.28, f"{number:02d}", 10, RGBColor(133, 153, 174), align=PP_ALIGN.RIGHT)


def _dark_list_panel(
    slide: Any,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    items: list[str],
    accent: RGBColor,
) -> None:
    _add_round_rect(slide, x, y, width, height, RGBColor(31, 48, 68), RGBColor(62, 82, 103))
    _add_text(slide, x + 0.28, y + 0.2, width - 0.56, 0.34, label, 11, accent, bold=True)
    box = slide.shapes.add_textbox(
        Inches(x + 0.28),
        Inches(y + 0.67),
        Inches(width - 0.56),
        Inches(height - 0.84),
    )
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    for index, item in enumerate((items or ["待补充内容"])[:3]):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = f"•  {item}"
        paragraph.font.name = FONT
        paragraph.font.size = Pt(12)
        paragraph.font.color.rgb = PAPER
        paragraph.space_after = Pt(7)


def _comparison_column(
    slide: Any,
    x: float,
    y: float,
    width: float,
    height: float,
    content: dict[str, Any],
    accent: RGBColor,
    accent_light: RGBColor,
) -> None:
    _add_round_rect(slide, x, y, width, height, PAPER, LINE)
    _add_rect(slide, x, y, width, 0.13, accent)
    _add_pill(slide, x + 0.35, y + 0.38, 1.35, 0.5, str(content.get("label") or ""), accent_light, accent)
    _add_bullets(slide, x + 0.42, y + 1.25, width - 0.84, height - 1.55, _list_text(content.get("items")), 15)


def _base_content_slide(slide: Any, spec: dict[str, Any], number: int) -> None:
    _set_background(slide, CANVAS)
    _add_text(slide, 0.82, 0.55, 10.9, 0.72, spec["title"], 24, INK, bold=True)
    _add_rect(slide, 0.82, 1.31, 0.82, 0.07, TEAL)
    _add_footer(slide, number, spec)


def _add_footer(slide: Any, number: int, spec: dict[str, Any]) -> None:
    _add_text(slide, 0.82, 6.79, 8.7, 0.25, _source_label(spec), 9, MUTED)
    _add_text(slide, 11.72, 6.76, 0.62, 0.25, f"{number:02d}", 10, MUTED, align=PP_ALIGN.RIGHT)


def _source_label(spec: dict[str, Any]) -> str:
    evidence = _list_text(spec.get("source_evidence_ids"))
    return "来源  " + " · ".join(_audience_source_names(evidence))


def _audience_source_names(evidence_ids: list[str]) -> list[str]:
    has_general_knowledge = any(
        _is_general_knowledge_evidence(evidence_id)
        for evidence_id in evidence_ids
    )
    has_private_evidence = any(
        not _is_general_knowledge_evidence(evidence_id)
        for evidence_id in evidence_ids
    )
    labels: list[str] = []
    if has_private_evidence:
        labels.append("用户提供的证据")
    if has_general_knowledge or not labels:
        labels.append("通用知识")
    return labels


def _is_general_knowledge_evidence(evidence_id: str) -> bool:
    canonical = re.sub(r"[^a-z0-9]+", "", str(evidence_id).lower())
    return canonical.startswith("generalknowledge")


def _add_bullets(
    slide: Any,
    x: float,
    y: float,
    width: float,
    height: float,
    items: list[str],
    font_size: int,
) -> None:
    items = items or ["待补充内容"]
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(width), Inches(height))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = Inches(0.03)
    frame.margin_right = Inches(0.03)
    for index, item in enumerate(items[:6]):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = f"•  {item}"
        paragraph.font.name = FONT
        paragraph.font.size = Pt(font_size)
        paragraph.font.color.rgb = INK
        paragraph.space_after = Pt(12)
        paragraph.line_spacing = 1.12


def _add_text(
    slide: Any,
    x: float,
    y: float,
    width: float,
    height: float,
    text: str,
    font_size: int,
    color: RGBColor,
    *,
    bold: bool = False,
    align: PP_ALIGN = PP_ALIGN.LEFT,
) -> Any:
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(width), Inches(height))
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    frame.margin_left = Inches(0.02)
    frame.margin_right = Inches(0.02)
    paragraph = frame.paragraphs[0]
    paragraph.text = str(text or "")
    paragraph.alignment = align
    paragraph.font.name = FONT
    paragraph.font.size = Pt(font_size)
    paragraph.font.bold = bold
    paragraph.font.color.rgb = color
    paragraph.space_after = Pt(0)
    return shape


def _add_rect(slide: Any, x: float, y: float, width: float, height: float, color: RGBColor) -> Any:
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(width), Inches(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    return shape


def _add_round_rect(
    slide: Any,
    x: float,
    y: float,
    width: float,
    height: float,
    fill_color: RGBColor,
    line_color: RGBColor,
) -> Any:
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE,
        Inches(x),
        Inches(y),
        Inches(width),
        Inches(height),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_color
    shape.line.color.rgb = line_color
    shape.line.width = Pt(0.8)
    return shape


def _add_circle(slide: Any, x: float, y: float, size: float, color: RGBColor) -> Any:
    shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(size), Inches(size))
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    return shape


def _add_pill(
    slide: Any,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    fill_color: RGBColor,
    text_color: RGBColor,
) -> Any:
    shape = _add_round_rect(slide, x, y, width, height, fill_color, fill_color)
    frame = shape.text_frame
    frame.clear()
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    paragraph = frame.paragraphs[0]
    paragraph.text = label
    paragraph.alignment = PP_ALIGN.CENTER
    paragraph.font.name = FONT
    paragraph.font.size = Pt(10)
    paragraph.font.bold = True
    paragraph.font.color.rgb = text_color
    return shape


def _set_background(slide: Any, color: RGBColor) -> None:
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = color


def _text_character_count(value: Any) -> int:
    if isinstance(value, str):
        return len(re.sub(r"\s+", "", value))
    if isinstance(value, dict):
        return sum(_text_character_count(item) for key, item in value.items() if key != "source_evidence_ids")
    if isinstance(value, (list, tuple)):
        return sum(_text_character_count(item) for item in value)
    return 0


def _has_visual_explanation(slide: dict[str, Any], role: str) -> bool:
    if role in {"process", "comparison"}:
        return True
    visual = slide.get("visual")
    return isinstance(visual, dict) and bool(visual.get("type") or visual.get("nodes"))


def _validate_slide_item_limits(
    slide: dict[str, Any],
    *,
    role: str,
    profile: dict[str, Any],
    index: int,
) -> None:
    maximum_steps = int(profile.get("maximum_process_steps") or 4)
    maximum_items = int(profile.get("maximum_list_items") or 4)
    maximum_comparison_items = int(profile.get("maximum_comparison_items_per_side") or 3)
    if role == "process" and len(_list_text(slide.get("steps"))) > maximum_steps:
        raise PresentationSpecError(
            f"slide {index} supports at most {maximum_steps} steps"
        )
    for key in ("points", "actions"):
        if len(_list_text(slide.get(key))) > maximum_items:
            raise PresentationSpecError(
                f"slide {index} supports at most {maximum_items} {key}"
            )
    for key in ("left", "right"):
        column = slide.get(key)
        if isinstance(column, dict) and len(_list_text(column.get("items"))) > maximum_comparison_items:
            raise PresentationSpecError(
                f"slide {index} supports at most {maximum_comparison_items} comparison items per side"
            )
    for key in ("strengths", "limits"):
        if len(_list_text(slide.get(key))) > maximum_comparison_items:
            raise PresentationSpecError(
                f"slide {index} supports at most {maximum_comparison_items} {key}"
            )
    visual = slide.get("visual")
    if isinstance(visual, dict) and len(_visual_node_labels(visual.get("nodes"))) > maximum_items:
        raise PresentationSpecError(
            f"slide {index} supports at most {maximum_items} visual nodes"
        )


def _normalize_slide_schema(slide: dict[str, Any]) -> dict[str, Any]:
    content = slide.pop("content", None)
    content = content if isinstance(content, dict) else {}
    role = str(slide.get("role") or "evidence").strip().lower()

    source_ids = slide.get("source_evidence_ids") or slide.get("evidence_ids") or content.get("evidence_ids")
    slide["source_evidence_ids"] = _stable_strings(source_ids or [])
    slide.pop("evidence_ids", None)

    for key in (
        "subtitle",
        "takeaway",
        "points",
        "steps",
        "actions",
        "visual",
        "left",
        "right",
        "strengths",
        "limits",
    ):
        if key not in slide and key in content:
            slide[key] = content[key]

    explanation = str(content.get("explanation") or "").strip()
    analogy = str(content.get("analogy") or "").strip()
    analogy_limitation = str(content.get("analogy_limitation") or "").strip()

    if role == "title":
        slide.setdefault("subtitle", content.get("deck_tagline") or "")
        slide["preview_points"] = _list_text(
            slide.get("preview_points") or content.get("topics_preview")
        )
    elif role == "concept":
        slide.setdefault("takeaway", explanation)
        points = _list_text(slide.get("points") or content.get("key_points"))
        if analogy:
            points.append(f"类比：{analogy}")
        if analogy_limitation:
            points.append(f"类比边界：{analogy_limitation}")
        slide["points"] = points
        if not isinstance(slide.get("visual"), dict):
            nodes = [_short_visual_label(point) for point in points[:3]]
            slide["visual"] = {"type": "flow", "nodes": nodes or ["输入", "处理", "输出"]}
    elif role == "process":
        slide.setdefault("takeaway", explanation)
        raw_steps = slide.get("steps") or content.get("process_steps")
        slide["steps"] = _process_step_text(raw_steps)
    elif role == "comparison":
        slide.setdefault("takeaway", explanation)
    elif role == "closing":
        slide["takeaway"] = str(
            slide.get("takeaway") or content.get("takeaway") or explanation
        ).strip()
        slide["strengths"] = _list_text(slide.get("strengths") or content.get("strengths"))
        slide["limits"] = _list_text(slide.get("limits") or content.get("limits"))
        if not _list_text(slide.get("actions")):
            slide["actions"] = _visual_node_items(slide.get("visual"))
    else:
        slide.setdefault("takeaway", explanation)
        slide["points"] = _list_text(
            slide.get("points") or content.get("key_points") or content.get("bullets")
        )
        if not slide["points"]:
            slide["points"] = _visual_node_items(slide.get("visual"))
    return slide


def _has_comparison_columns(slide: dict[str, Any]) -> bool:
    return all(
        isinstance(slide.get(key), dict)
        and bool(_list_text(slide[key].get("items")))
        for key in ("left", "right")
    )


def _visual_node_items(visual: Any) -> list[str]:
    if not isinstance(visual, dict):
        return []
    return [
        "：".join(part for part in (node["label"], node["content"]) if part)
        for node in _visual_nodes(visual.get("nodes"))
    ]


def _process_step_text(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("step") or "").strip()
            description = str(item.get("description") or item.get("detail") or "").strip()
            text = "\n".join(part for part in (label, description) if part)
        else:
            text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def _visual_node_labels(value: Any) -> list[str]:
    return [node["label"] for node in _visual_nodes(value)]


def _visual_nodes(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, (list, tuple)):
        return []
    nodes: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("title") or item.get("name") or "").strip()
            content = str(
                item.get("content")
                or item.get("description")
                or item.get("detail")
                or ""
            ).strip()
        else:
            label = str(item or "").strip()
            content = ""
        if label:
            nodes.append({"label": label, "content": content})
    return nodes


def _short_visual_label(value: str) -> str:
    label = re.split(r"[：:，,。；;]", str(value or ""), maxsplit=1)[0].strip()
    if len(label) <= 40:
        return label
    shortened = label[:40].rsplit(" ", 1)[0].strip()
    return f"{shortened or label[:40]}…"


def _semantic_segments(slide: dict[str, Any]) -> list[str]:
    """Return only content selected by the role's renderer.

    Agent-produced slide schemas can contain alternative fields such as both
    ``actions`` and ``points``. Renderers intentionally apply precedence to
    those alternatives; quality and task-contract checks must use the same
    precedence or they either reject a correct deck or approve hidden content.
    """

    segments = [str(slide.get("title") or "").strip()]
    role = str(slide.get("role") or "evidence").strip().lower()

    def add_text(key: str) -> None:
        value = str(slide.get(key) or "").strip()
        if value:
            segments.append(value)

    def add_list(key: str) -> None:
        segments.extend(_list_text(slide.get(key)))

    def add_comparison_columns() -> None:
        for key in ("left", "right"):
            column = slide.get(key)
            if not isinstance(column, dict):
                continue
            label = str(column.get("label") or "").strip()
            if label:
                segments.append(label)
            segments.extend(_list_text(column.get("items")))

    def add_visual_nodes() -> None:
        visual = slide.get("visual")
        if not isinstance(visual, dict):
            return
        for node in _visual_nodes(visual.get("nodes")):
            segments.append(node["label"])
            if node["content"]:
                segments.append(node["content"])

    if role == "title":
        add_text("subtitle")
        add_list("preview_points")
    elif role in {"section", "comparison"} and _has_comparison_columns(slide):
        add_comparison_columns()
    elif role == "section":
        takeaway = str(slide.get("takeaway") or slide.get("subtitle") or "").strip()
        if takeaway:
            segments.append(takeaway)
    elif role == "concept":
        add_text("takeaway")
        add_list("points")
        add_visual_nodes()
    elif role == "process":
        add_text("takeaway")
        active_steps = _list_text(slide.get("steps")) or _list_text(slide.get("points"))
        segments.extend(active_steps)
    elif role == "closing":
        add_text("takeaway")
        strengths = _list_text(slide.get("strengths"))
        limits = _list_text(slide.get("limits"))
        if strengths or limits:
            segments.extend(strengths)
            segments.extend(limits)
        else:
            segments.extend(
                _list_text(slide.get("actions")) or _list_text(slide.get("points"))
            )
    else:
        add_text("takeaway")
        segments.extend(
            _list_text(slide.get("points")) or _list_text(slide.get("bullets"))
        )
    return [segment for segment in segments if segment]


def _normalize_match_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _find_overstated_technical_claim(slide: dict[str, Any]) -> str | None:
    text = json.dumps(slide, ensure_ascii=False)
    for pattern in OVERSTATED_TECHNICAL_CLAIMS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def _find_misleading_technical_explanation(slide: dict[str, Any]) -> str | None:
    text = json.dumps(slide, ensure_ascii=False)
    for pattern in MISLEADING_TECHNICAL_EXPLANATIONS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def _list_text(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _stable_strings(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
