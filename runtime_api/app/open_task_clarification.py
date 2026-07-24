from __future__ import annotations

import re
from typing import Any

from app.artifact_tasks import artifact_label, detect_artifact_type, extract_entity_hint, normalize_text


DEFAULT_PPT_AUDIENCE = "普通人"
DEFAULT_PPT_PAGE_COUNT = 10
DEFAULT_PPT_DEPTH = "科普"
DEFAULT_PPT_STYLE = "清晰、有类比、适合讲解"
DEFAULT_DOCUMENT_AUDIENCE = "相关项目成员"
DEFAULT_DOCUMENT_PURPOSE = "形成可阅读、可执行的说明文档"
DEFAULT_IMAGE_AUDIENCE = "普通读者"
DEFAULT_IMAGE_PURPOSE = "清晰解释主题"
DEFAULT_IMAGE_CANVAS = {"width": 1600, "height": 1000, "orientation": "landscape"}
ENGLISH_COUNT_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}


def analyze_open_task_clarity(
    message: str,
    *,
    artifact_payload: dict[str, Any],
    conversation_context: list[dict[str, Any]] | None = None,
    pending_task_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    route = artifact_payload.get("route") if isinstance(artifact_payload.get("route"), dict) else {}
    artifact_type = str(route.get("artifact_type") or detect_artifact_type(normalize_text(message)) or "none")
    if route.get("requires_task_run") is False or artifact_type == "none":
        return {
            "status": "not_open_task",
            "task_type": "none",
            "artifact_type": "none",
            "slots": {},
            "missing_required": [],
            "defaultable": [],
            "question": "",
            "requirements_contract": None,
        }

    previous_slots = _previous_slots(pending_task_state)
    slots = {
        **previous_slots,
        **_extract_slots(message, artifact_type=artifact_type, previous_slots=previous_slots),
    }
    if not slots.get("source_policy"):
        slots["source_policy"] = _source_policy(message, previous_slots=previous_slots)
    if slots["source_policy"] == "may_use_general_knowledge" and _chooses_defaults(message):
        _apply_safe_defaults(slots, artifact_type=artifact_type)

    missing_required = _missing_required_slots(
        slots,
        artifact_payload=artifact_payload,
        artifact_type=artifact_type,
    )
    defaultable = _defaultable_slots(slots, artifact_type=artifact_type)
    if missing_required:
        return {
            "status": "needs_clarification",
            "task_type": "artifact_creation",
            "artifact_type": artifact_type,
            "slots": slots,
            "missing_required": missing_required,
            "defaultable": defaultable,
            "question": _clarification_question(slots, missing_required, artifact_type=artifact_type),
            "requirements_contract": None,
        }

    contract = _requirements_contract(slots, artifact_type=artifact_type)
    return {
        "status": "executable",
        "task_type": "artifact_creation",
        "artifact_type": artifact_type,
        "slots": slots,
        "missing_required": [],
        "defaultable": defaultable,
        "question": "",
        "requirements_contract": contract,
    }


def _previous_slots(pending_task_state: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(pending_task_state, dict):
        return {}
    slots = pending_task_state.get("slots")
    if isinstance(slots, dict):
        return {str(key): value for key, value in slots.items()}
    contract = pending_task_state.get("requirements_contract")
    if isinstance(contract, dict):
        return {
            "topic": contract.get("topic") or _topic_from_final_goal(str(contract.get("final_goal") or "")),
            "artifact_type": contract.get("deliverable"),
            "purpose": contract.get("purpose"),
            "audience": contract.get("audience"),
            "page_count": contract.get("page_count"),
            "depth": contract.get("depth"),
            "style": contract.get("style"),
            "must_include": contract.get("must_include"),
            "slide_outline": contract.get("slide_outline"),
            "inline_source_facts": contract.get("inline_source_facts"),
            "source_policy": contract.get("source_policy"),
            "columns": contract.get("columns"),
            "calculations": contract.get("calculations"),
            "sections": contract.get("sections"),
            "canvas": contract.get("canvas"),
            "visual_kind": contract.get("visual_kind"),
        }
    return {}


def _extract_slots(message: str, *, artifact_type: str, previous_slots: dict[str, Any]) -> dict[str, Any]:
    slots: dict[str, Any] = {
        "artifact_type": artifact_type,
        "topic": previous_slots.get("topic") or _extract_topic(message, artifact_type=artifact_type),
        "purpose": previous_slots.get("purpose") or _extract_purpose(message),
        "audience": previous_slots.get("audience") or _extract_audience(message),
        "page_count": previous_slots.get("page_count") or _extract_page_count(message),
        "depth": previous_slots.get("depth") or _extract_depth(message),
        "style": previous_slots.get("style") or _extract_style(message),
        "must_include": previous_slots.get("must_include") or _extract_must_include(message),
        "slide_outline": previous_slots.get("slide_outline") or _extract_slide_outline(message),
        "inline_source_facts": previous_slots.get("inline_source_facts") or _extract_inline_source_facts(message),
        "columns": previous_slots.get("columns") or _extract_columns(message),
        "calculations": previous_slots.get("calculations") or _extract_calculations(message),
        "sections": previous_slots.get("sections") or _extract_sections(message),
        "canvas": previous_slots.get("canvas") or _extract_canvas(message),
        "visual_kind": previous_slots.get("visual_kind") or _extract_visual_kind(message),
        "source_policy": previous_slots.get("source_policy") or _source_policy(message, previous_slots=previous_slots),
    }
    if _chooses_defaults(message) and slots.get("source_policy") == "may_use_general_knowledge":
        _apply_safe_defaults(slots, artifact_type=artifact_type)
    return {key: value for key, value in slots.items() if value not in ("", None)}


def _source_policy(message: str, *, previous_slots: dict[str, Any]) -> str:
    if previous_slots.get("source_policy"):
        return str(previous_slots["source_policy"])
    text = message or ""
    if re.search(
        r"(?i)\b(?:do\s+not|don't|must\s+not|never)\s+(?:invent|fabricate|make\s+up)\b",
        text,
    ):
        return "must_use_private_evidence"
    if any(
        marker in text
        for marker in [
            "数据来源仅限",
            "资料来源仅限",
            "内容仅限以下",
            "仅限以下明确事实",
            "不得编造",
            "不要编造",
        ]
    ):
        return "must_use_private_evidence"
    private_markers = [
        "依据刚刚",
        "根据刚刚",
        "刚刚",
        "刚才",
        "这封邮件",
        "这份资料",
        "附件",
        "我的简历",
        "简历",
        "王总",
        "资料",
    ]
    if any(marker in text for marker in private_markers) and not any(marker in text for marker in ["原理", "科普", "教程"]):
        return "must_use_private_evidence"
    if any(marker in text for marker in ["按这个", "用这个"]):
        return "must_use_private_evidence"
    if re.search(
        r"(?<!有)(?:依据|根据)\s*(?:这|该|以下|上述|前述|附件|资料|数据|内容|文档|文件|邮件|消息|现有|刚)",
        text,
    ):
        return "must_use_private_evidence"
    return "may_use_general_knowledge"


def _extract_topic(message: str, *, artifact_type: str) -> str:
    text = (message or "").strip()
    if not text:
        return ""
    bracketed_title = re.search(r"《([^》]+)》", text)
    if bracketed_title:
        return bracketed_title.group(1).strip()
    chinese_title = re.search(
        r"(?:标题|题目|主题)(?:为|是|叫|用)[:：]?\s*[“\"']([^”\"']+)[”\"']",
        text,
        flags=re.IGNORECASE,
    )
    if chinese_title:
        return chinese_title.group(1).strip()
    if artifact_type == "pptx":
        slide_outline = _extract_slide_outline(text)
        if slide_outline and str(slide_outline[0].get("title") or "").strip():
            return str(slide_outline[0]["title"]).strip()
        titled = re.search(
            r"\btitled\s+(.+?)(?=\s+(?:for|include|including|with|use|using|generate)\b|[,.;]|$)",
            text,
            flags=re.IGNORECASE,
        )
        if titled:
            return titled.group(1).strip().strip("\"'")
        match = re.search(r"(?:做一个|做一份|做个|生成|制作|写一份)?\s*(.+?)\s*(?:的)?\s*(?:PPT|ppt|pptx|幻灯片|演示文稿)", text)
        if match:
            topic = match.group(1)
        else:
            topic = text
        previous = None
        while previous != topic:
            previous = topic
            topic = re.sub(r"^(帮我|请|麻烦你|那你|做一个|做一份|做个|生成|制作|写一份)", "", topic).strip()
        if not topic:
            topic = _extract_topic_after_artifact_word(text)
        topic = re.sub(r"(可以)?用来.*$", "", topic).strip()
        compact_topic = re.sub(r"\s+", "", topic)
        if re.fullmatch(r"(?:一份|一个|一张)?(?:\d+页)?(?:中文|英文)?", compact_topic):
            report_topic = re.search(r"(?:做|进行)\s*([^，。；;]+?)(?:汇报|报告)", text)
            if report_topic:
                topic = report_topic.group(1).strip()
        return topic
    return text


def _extract_topic_after_artifact_word(text: str) -> str:
    match = re.search(r"(?:PPT|ppt|pptx|幻灯片|演示文稿)\s*(?:，|,|。|：|:)?\s*(.+)$", text)
    if not match:
        return ""
    tail = match.group(1).strip()
    tail = re.sub(r"^(让|给|为|面向)", "", tail).strip()
    tail = re.sub(r"^(普通人|学生|客户|技术团队|团队|老板|投资人)(?:可以|能|能够)?(?:理解|看懂|听懂)?", "", tail).strip()
    tail = re.sub(r"^(可以|能|能够)?(?:理解|看懂|听懂)", "", tail).strip()
    return tail


def _topic_from_final_goal(value: str) -> str:
    match = re.search(r"关于(.+?)的", value)
    return match.group(1).strip() if match else ""


def _extract_purpose(message: str) -> str:
    text = message or ""
    english_explicit = re.search(
        r"\bpurpose\s*(?:is|:|=)\s*(.+?)(?=\.(?:\s|$)|;|$)",
        text,
        flags=re.IGNORECASE,
    )
    if english_explicit:
        purpose = re.sub(r"^(?:a|an)\s+", "", english_explicit.group(1).strip(), flags=re.IGNORECASE)
        if purpose:
            return purpose
    explicit = re.search(r"(?:用于|用来)([^，。；;]+)", text, flags=re.IGNORECASE)
    if explicit:
        purpose = explicit.group(1).strip()
        purpose = re.sub(
            r"的?\s*(?:excel|xlsx|word|docx|pptx?|表格|文档|报告|图片|信息图|海报).*$",
            "",
            purpose,
            flags=re.IGNORECASE,
        ).strip()
        if purpose:
            return purpose
    if "讲解" in text:
        return "讲解"
    if "汇报" in text:
        return "汇报"
    if "培训" in text:
        return "培训"
    if "销售" in text or "客户" in text:
        return "销售/客户沟通"
    return ""


def _extract_audience(message: str) -> str:
    text = message or ""
    english_declared = re.search(
        r"\b(?:target\s+)?audience\s*(?:is|:|=)\s*(.+?)(?=\.(?:\s|$)|;|$)",
        text,
        flags=re.IGNORECASE,
    )
    if english_declared:
        audience = english_declared.group(1).strip()
        normalized_audience = audience.lower()
        if normalized_audience in {"manager", "managers", "management", "executives", "leadership"}:
            return "管理层"
        if normalized_audience in {"ordinary people", "general audience", "laypeople", "non-technical audience"}:
            return "普通人"
        if normalized_audience in {"student", "students"}:
            return "学生"
        if normalized_audience in {"customer", "customers", "client", "clients"}:
            return "客户"
        if normalized_audience in {"technical team", "engineers", "developers"}:
            return "技术团队"
        return audience
    declared = re.search(
        r"(?:目标)?受众\s*(?:为|是|：|:)\s*([^，。；;]+)",
        text,
    )
    if declared:
        return declared.group(1).strip()
    recipient = re.search(
        r"(?:用于)?给\s*(?:公司|项目|业务)?\s*(管理层|团队|客户|老板|投资人|学生|普通人|技术团队)(?:看|讲解|汇报|演示|使用)?",
        text,
    )
    if recipient:
        return recipient.group(1).strip()
    known_audience = re.search(
        r"面向\s*(?:公司)?\s*((?:没有|无)技术背景的普通人|非技术(?:背景)?(?:的)?(?:普通人|人群)|普通人|学生|客户|技术团队|管理层|团队|老板|投资人)",
        text,
    )
    if known_audience:
        return known_audience.group(1).strip()
    explicit = re.search(
        r"面向\s*(.+?)(?=的(?:项目|报告|文档|表格|PPT|演示|流程|信息图|海报|图片)|[，。；;]|必须|需要|需讲|使用|生成|不要|$)",
        text,
    )
    if explicit:
        return explicit.group(1).strip()
    for keyword in ["普通人", "学生", "客户", "技术团队", "管理层", "团队", "老板", "投资人"]:
        if keyword in text:
            return keyword
    lowered = text.lower()
    if any(keyword in lowered for keyword in ["ordinary people", "general audience", "non technical", "non-technical", "laypeople"]):
        return "普通人"
    if "student" in lowered:
        return "学生"
    if "customer" in lowered or "client" in lowered:
        return "客户"
    if "technical team" in lowered or "engineer" in lowered or "developer" in lowered:
        return "技术团队"
    return ""


def _extract_depth(message: str) -> str:
    text = message or ""
    if "科普" in text:
        return "科普"
    if any(marker in text for marker in ["技术复盘", "技术评审", "架构评审"]):
        return "技术原理"
    if any(marker in text for marker in ["业务复盘", "经营复盘", "客户复盘", "项目复盘", "经营分析"]):
        return "业务复盘"
    if "复盘" in text or ("管理层" in text and "汇报" in text):
        return "业务复盘"
    if any(marker in text for marker in ["没有技术背景", "无技术背景", "非技术", "普通人", "看懂", "听懂", "理解"]):
        return "科普"
    if "技术" in text:
        return "技术原理"
    lowered = text.lower()
    if any(
        keyword in lowered
        for keyword in [
            "business summary",
            "executive summary",
            "management summary",
            "system verification",
            "status review",
        ]
    ):
        return "业务总结"
    if any(
        keyword in lowered
        for keyword in [
            "popular science",
            "introductory",
            "beginner",
            "non technical",
            "non-technical",
            "simple explanation",
            "middle school",
            "for students",
        ]
    ):
        return "科普"
    if any(keyword in lowered for keyword in ["technical", "deep dive", "architecture", "algorithm"]):
        return "技术原理"
    return ""


def _extract_style(message: str) -> str:
    text = message or ""
    lowered = text.lower()
    styles: list[str] = []
    if "简约工业风" in text:
        styles.append("简约工业风")
    elif "工业风" in text:
        styles.append("工业风")
    if "类比" in text or "analogy" in lowered or "analogies" in lowered:
        styles.append("多用类比")
    if "简洁" in text or "concise" in lowered:
        styles.append("简洁")
    if "好看" in text:
        styles.append("视觉清晰")
    return "、".join(styles)


def _extract_must_include(message: str) -> list[str]:
    match = re.search(
        r"(?:必须讲清|必须包含|必须覆盖|需要讲清|需包含)[:：]?\s*(.+?)(?=[。；;]|使用|生成|不要|$)",
        message or "",
        flags=re.IGNORECASE,
    )
    if match:
        return _split_contract_items(match.group(1))
    slide_outline = _extract_slide_outline(message)
    if slide_outline:
        required: list[str] = []
        for slide in slide_outline:
            title = str(slide.get("title") or "").strip()
            if title and title.casefold() not in {"title", "title slide", "cover", "cover slide"}:
                required.append(title)
            subtitle = str(slide.get("subtitle") or "").strip()
            if subtitle:
                required.append(subtitle)
            required.extend(
                str(value).strip()
                for value in slide.get("must_include") or []
                if str(value or "").strip()
            )
        return list(dict.fromkeys(required))
    english_slide_outline = re.findall(
        r"(?is)\bslide\s+\d+\s*:\s*(.+?)(?=(?:\.\s*)?\bslide\s+\d+\s*:|(?:\.\s*)?(?:do\s+not|don't|audience|purpose|exactly)\b|$)",
        message or "",
    )
    if english_slide_outline:
        return [
            item.strip().rstrip(".")
            for item in english_slide_outline
            if item.strip().rstrip(".").casefold() not in {"title", "title slide", "cover", "cover slide"}
        ]
    page_outline = re.findall(
        r"第\s*\d+\s*页\s*(?:为|是|：|:)?\s*([^；;。]+)",
        message or "",
        flags=re.IGNORECASE,
    )
    return [item.strip() for item in page_outline if item.strip()]


def _extract_inline_source_facts(message: str) -> list[str]:
    english_slide_outline = re.findall(
        r"(?is)\bslide\s+\d+\s*:\s*(.+?)(?=(?:\.\s*)?\bslide\s+\d+\s*:|(?:\.\s*)?(?:do\s+not|don't|audience|purpose|exactly)\b|$)",
        message or "",
    )
    return [
        item.strip().rstrip(".")
        for item in english_slide_outline
        if item.strip().rstrip(".").casefold() not in {"title", "title slide", "cover", "cover slide"}
    ]


def _extract_slide_outline(message: str) -> list[dict[str, Any]]:
    text = str(message or "").strip()
    matches = list(re.finditer(r"(?i)\bslide\s+(\d{1,2})\s*(?::|[-‐-―])?\s*", text))
    outline: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        segment_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        segment = text[match.end() : segment_end].strip()
        segment = re.split(
            r"(?i)\.\s+(?=(?:use|using|do\s+not|don't|audience|purpose|generate|create)\b)",
            segment,
            maxsplit=1,
        )[0].strip(" .;,")
        title_match = re.search(
            r"(?is)^title(?:\s+is|\s*[:=])?\s+(.+?)(?=\s+(?:subtitle|and\s+body|body\s+must|must\s+include)\b|[.;]|$)",
            segment,
        )
        implicit_body: list[str] = []
        if not title_match:
            colon_title = re.match(r"(?is)^(.+?)(?=[.;]|$)", segment)
            colon_value = str(colon_title.group(1) if colon_title else "").strip()
            if colon_value.casefold() in {"title", "title slide", "cover", "cover slide"}:
                title = colon_value
            else:
                title = ""
                implicit_body = [colon_value] if colon_value else []
        else:
            title = title_match.group(1).strip()
        subtitle_match = re.search(
            r"(?is)\bsubtitle(?:\s+is|\s*[:=])?\s+(.+?)(?=\s+(?:and\s+body|body\s+must|must\s+include)\b|[.;]|$)",
            segment,
        )
        body_match = re.search(
            r"(?is)\b(?:and\s+)?body\s+must\s+include\s+(.+?)(?=[.;]|$)",
            segment,
        )
        body_items = _split_english_contract_items(body_match.group(1)) if body_match else implicit_body
        if not title and not subtitle_match and not body_items:
            continue
        outline.append(
            {
                "slide_number": int(match.group(1)),
                "title": title,
                "subtitle": subtitle_match.group(1).strip() if subtitle_match else "",
                "must_include": body_items,
            }
        )
    return outline


def _split_english_contract_items(value: str) -> list[str]:
    normalized = re.sub(
        r"(?i)^\s*(?:the\s+)?exact\s+phrases?\s*[:：]?\s*",
        "",
        str(value or ""),
    )
    parts = [
        item.strip(" .;,\"'")
        for item in re.split(r"(?i)\s+and\s+|[,;]", normalized)
        if item.strip(" .;,\"'")
    ]
    return list(dict.fromkeys(parts))


def _extract_page_count(message: str) -> int | None:
    match = re.search(
        r"(\d{1,2})\s*(?:[-‐‑–—]\s*)?(?:页|p|P|pages?|slides?)",
        message or "",
        flags=re.IGNORECASE,
    )
    if match:
        return int(match.group(1))
    word_match = re.search(
        rf"\b({'|'.join(ENGLISH_COUNT_WORDS)})\s*(?:pages?|slides?)\b",
        message or "",
        flags=re.IGNORECASE,
    )
    if word_match:
        return ENGLISH_COUNT_WORDS[word_match.group(1).lower()]
    return None


def _extract_columns(message: str) -> list[str]:
    match = re.search(r"(?:字段|列)(?:包括|包含|为|是)[:：]?(.+?)(?=，(?:计算|用于|用来)|。|；|;|$)", message or "", flags=re.IGNORECASE)
    return _split_contract_items(match.group(1)) if match else []


def _extract_calculations(message: str) -> list[str]:
    formula_rules = re.findall(
        r"(?:^|[，,；;。])\s*([^，,；;。]*?必须用[^，,；;。]*?公式)",
        message or "",
        flags=re.IGNORECASE,
    )
    if formula_rules:
        return list(dict.fromkeys(rule.strip() for rule in formula_rules if rule.strip()))
    matches = re.findall(
        r"(?:^|[，,；;])\s*(?:计算|核算|统计)[:：]?\s*(.+?)(?=。|；|;|$)",
        message or "",
        flags=re.IGNORECASE,
    )
    if not matches:
        return []
    value = re.sub(r"^(?:项目|字段|列)", "", matches[-1]).strip()
    return _split_contract_items(value)


def _extract_sections(message: str) -> list[str]:
    match = re.search(r"(?:章节|目录)(?:包括|包含|为|是)[:：]?(.+?)(?=。|；|;|$)", message or "", flags=re.IGNORECASE)
    return _split_contract_items(match.group(1)) if match else []


def _split_contract_items(value: str) -> list[str]:
    cleaned = re.sub(r"^(?:包括|包含)[:：]?", "", str(value or "")).strip()
    parts = [item.strip() for item in re.split(r"[、,，/]|(?:和|以及)", cleaned) if item.strip()]
    return list(dict.fromkeys(parts))


def _extract_canvas(message: str) -> dict[str, Any] | None:
    text = message or ""
    match = re.search(r"(\d{3,4})\s*[x×*]\s*(\d{3,4})", text, flags=re.IGNORECASE)
    if not match:
        return None
    width, height = int(match.group(1)), int(match.group(2))
    orientation = "landscape" if width >= height else "portrait"
    if "横版" in text:
        orientation = "landscape"
    elif "竖版" in text:
        orientation = "portrait"
    return {"width": width, "height": height, "orientation": orientation}


def _extract_visual_kind(message: str) -> str:
    text = (message or "").lower()
    if "流程图" in text or "diagram" in text:
        return "diagram"
    if "海报" in text or "poster" in text:
        return "poster"
    if "社交" in text or "social card" in text:
        return "social_card"
    if "信息图" in text or "infographic" in text:
        return "infographic"
    return ""


def _chooses_defaults(message: str) -> bool:
    text = normalize_text(message)
    lowered = text.lower()
    return any(keyword in text for keyword in ["按默认", "默认做", "你决定", "你看着办", "直接开始", "现在开始"]) or any(
        keyword in lowered
        for keyword in ["proceed now", "go ahead", "start now", "use defaults", "use the defaults"]
    )


def _apply_safe_ppt_defaults(slots: dict[str, Any]) -> None:
    slots.setdefault("audience", DEFAULT_PPT_AUDIENCE)
    slots.setdefault("page_count", DEFAULT_PPT_PAGE_COUNT)
    slots.setdefault("depth", DEFAULT_PPT_DEPTH)
    slots.setdefault("style", DEFAULT_PPT_STYLE)


def _apply_safe_defaults(slots: dict[str, Any], *, artifact_type: str) -> None:
    if artifact_type == "pptx":
        _apply_safe_ppt_defaults(slots)
    elif artifact_type == "xlsx":
        slots.setdefault("purpose", "整理并分析结构化数据")
        slots.setdefault("columns", ["项目", "值", "备注"])
    elif artifact_type == "docx":
        slots.setdefault("purpose", DEFAULT_DOCUMENT_PURPOSE)
        slots.setdefault("audience", DEFAULT_DOCUMENT_AUDIENCE)
        slots.setdefault("sections", ["执行摘要", "事实与分析", "下一步行动"])
    elif artifact_type in {"image", "png", "jpg", "jpeg"}:
        slots.setdefault("purpose", DEFAULT_IMAGE_PURPOSE)
        slots.setdefault("audience", DEFAULT_IMAGE_AUDIENCE)
        slots.setdefault("canvas", dict(DEFAULT_IMAGE_CANVAS))
        slots.setdefault("visual_kind", "infographic")


def _missing_required_slots(
    slots: dict[str, Any],
    *,
    artifact_payload: dict[str, Any],
    artifact_type: str,
) -> list[str]:
    missing: list[str] = []
    if not slots.get("topic"):
        missing.append("topic")
    if (
        slots.get("source_policy") == "must_use_private_evidence"
        and not _has_evidence_items(artifact_payload)
        and not slots.get("inline_source_facts")
    ):
        missing.append("source_material")
    if artifact_type == "pptx" and (
        slots.get("source_policy") == "may_use_general_knowledge"
        or slots.get("inline_source_facts")
    ):
        if not slots.get("audience"):
            missing.append("audience")
        if not slots.get("depth"):
            missing.append("depth")
    elif artifact_type == "xlsx":
        if not slots.get("purpose"):
            missing.append("purpose")
        if not slots.get("columns"):
            missing.append("columns")
    elif artifact_type == "docx":
        if not slots.get("purpose"):
            missing.append("purpose")
        if not slots.get("audience"):
            missing.append("audience")
    elif artifact_type in {"image", "png", "jpg", "jpeg"}:
        if not slots.get("purpose"):
            missing.append("purpose")
        if not slots.get("audience"):
            missing.append("audience")
    return missing


def _defaultable_slots(slots: dict[str, Any], *, artifact_type: str) -> list[str]:
    if artifact_type == "docx":
        return ["sections"] if not slots.get("sections") else []
    if artifact_type in {"image", "png", "jpg", "jpeg"}:
        return ["canvas"] if not slots.get("canvas") else []
    if artifact_type != "pptx":
        return []
    defaultable: list[str] = []
    if not slots.get("page_count"):
        defaultable.append("page_count")
    if not slots.get("style"):
        defaultable.append("style")
    return defaultable


def _has_evidence_items(artifact_payload: dict[str, Any]) -> bool:
    evidence_pack = artifact_payload.get("evidence_pack") if isinstance(artifact_payload.get("evidence_pack"), dict) else {}
    return bool(evidence_pack.get("items"))


def _clarification_question(slots: dict[str, Any], missing_required: list[str], *, artifact_type: str) -> str:
    label = artifact_label(artifact_type)
    if "source_material" in missing_required:
        entity = extract_entity_hint(str(slots.get("topic") or "")) or "相关人"
        if entity == "相关人":
            entity = "王总" if "王总" in str(slots.get("topic") or "") else entity
        return (
            f"我还没找到{entity if entity != '相关人' else '你提到的'}资料。"
            "你可以把资料发给我，或者告诉我是在哪个渠道、哪个文件里吗？"
        )
    missing = set(missing_required)
    if artifact_type == "pptx" and {"audience", "depth"}.issubset(missing):
        page_count = slots.get("page_count")
        default_note = (
            f"如果你不指定其余项，我会保留已给出的 {page_count} 页，并仅对缺失字段采用默认值。"
            if page_count
            else "如果你不指定，我可以按普通人听众、10 页、科普风来做。"
        )
        return (
            f"可以。我先确认两点：这个 {label} 是讲给普通人、学生、客户，还是技术团队？"
            "你希望偏业务总结、科普讲解，还是技术原理？\n\n"
            f"{default_note}"
        )
    if artifact_type == "pptx" and "audience" in missing:
        depth = str(slots.get("depth") or "已指定深度")
        return f"内容深度已按“{depth}”记录。这份 {label} 主要讲给哪类受众看？"
    if artifact_type == "pptx" and "depth" in missing:
        audience = str(slots.get("audience") or "目标受众")
        page_count = slots.get("page_count")
        known = f"受众已记录为“{audience}”"
        if page_count:
            known += f"，页数为 {page_count} 页"
        return f"{known}。你希望内容偏业务总结、科普讲解，还是技术原理？"
    if artifact_type == "xlsx" and {"purpose", "columns"}.intersection(missing_required):
        return "这份表格要解决什么问题？请告诉我需要哪些字段，以及是否有汇总、计算或对比目标。"
    if artifact_type == "docx" and {"purpose", "audience"}.intersection(missing_required):
        return "这份文档用于什么场景、主要给哪类读者看？章节结构可以由你指定，也可以让我按默认结构整理。"
    if artifact_type in {"image", "png", "jpg", "jpeg"} and {"purpose", "audience"}.intersection(missing_required):
        return "这张图用于什么场景、目标受众是谁？画布尺寸可以指定，也可以按横版 1600x1000 生成。"
    return "我还需要补充一点信息，才能把这个任务交给 OpenCode 执行。"


def _requirements_contract(slots: dict[str, Any], *, artifact_type: str) -> dict[str, Any]:
    if artifact_type == "pptx":
        page_count = int(slots.get("page_count") or DEFAULT_PPT_PAGE_COUNT)
        audience = str(slots.get("audience") or DEFAULT_PPT_AUDIENCE)
        depth = str(slots.get("depth") or DEFAULT_PPT_DEPTH)
        style = str(slots.get("style") or DEFAULT_PPT_STYLE)
        topic = str(slots.get("topic") or "待生成主题")
        assumptions = []
        if slots.get("source_policy") == "may_use_general_knowledge":
            assumptions.append("用户未提供私有资料，允许使用通用知识讲解原理。")
        if audience == DEFAULT_PPT_AUDIENCE and page_count == DEFAULT_PPT_PAGE_COUNT and depth == DEFAULT_PPT_DEPTH:
            assumptions.append("用户选择默认方案：普通人听众、10 页、科普风。")
        return {
            "final_goal": f"生成一份用于给{audience}讲解{topic}的 PPT",
            "deliverable": "pptx",
            "topic": topic,
            "purpose": str(slots.get("purpose") or "讲解"),
            "audience": audience,
            "page_count": page_count,
            "depth": depth,
            "style": style,
            "source_policy": str(slots.get("source_policy") or "may_use_general_knowledge"),
            "must_include": list(slots.get("must_include") or _ppt_must_include(topic)),
            "slide_outline": [dict(item) for item in slots.get("slide_outline") or []],
            "inline_source_facts": list(slots.get("inline_source_facts") or []),
            "assumptions": assumptions,
        }
    if artifact_type == "xlsx":
        return {
            "final_goal": str(slots.get("topic") or "生成结构化工作簿"),
            "deliverable": "xlsx",
            "topic": str(slots.get("topic") or ""),
            "purpose": str(slots.get("purpose") or ""),
            "columns": list(slots.get("columns") or []),
            "calculations": list(slots.get("calculations") or []),
            "source_policy": str(slots.get("source_policy") or "may_use_general_knowledge"),
            "must_not_invent_missing_values": True,
            "assumptions": [],
        }
    if artifact_type == "docx":
        return {
            "final_goal": str(slots.get("topic") or "生成结构化文档"),
            "deliverable": "docx",
            "topic": str(slots.get("topic") or ""),
            "purpose": str(slots.get("purpose") or DEFAULT_DOCUMENT_PURPOSE),
            "audience": str(slots.get("audience") or DEFAULT_DOCUMENT_AUDIENCE),
            "sections": list(slots.get("sections") or ["执行摘要", "事实与分析", "下一步行动"]),
            "source_policy": str(slots.get("source_policy") or "may_use_general_knowledge"),
            "native_editable_content": True,
            "assumptions": [],
        }
    if artifact_type in {"image", "png", "jpg", "jpeg"}:
        return {
            "final_goal": str(slots.get("topic") or "生成信息图"),
            "deliverable": "image",
            "topic": str(slots.get("topic") or ""),
            "purpose": str(slots.get("purpose") or DEFAULT_IMAGE_PURPOSE),
            "audience": str(slots.get("audience") or DEFAULT_IMAGE_AUDIENCE),
            "visual_kind": str(slots.get("visual_kind") or "infographic"),
            "canvas": dict(slots.get("canvas") or DEFAULT_IMAGE_CANVAS),
            "output_format": "png",
            "source_policy": str(slots.get("source_policy") or "may_use_general_knowledge"),
            "assumptions": [],
        }
    return {
        "final_goal": str(slots.get("topic") or ""),
        "deliverable": artifact_type,
        "source_policy": str(slots.get("source_policy") or "may_use_general_knowledge"),
        "assumptions": [],
    }


def _ppt_must_include(topic: str) -> list[str]:
    if "AI" in topic and "视频" in topic:
        return [
            "AI 视频生成的输入与输出",
            "文本到视频的基本流程",
            "扩散模型或 Transformer 的直观解释",
            "为什么视频比图片更难",
            "应用场景与局限",
        ]
    return [
        f"{topic}的核心概念",
        f"{topic}的关键流程",
        "适合目标听众的例子",
        "常见误区与限制",
    ]
