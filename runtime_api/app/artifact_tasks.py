from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any


ARTIFACT_TASK_STEPS = [
    "interpret_request",
    "gather_evidence",
    "outline",
    "draft",
    "generate_artifact",
    "verify",
    "deliver",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def route_artifact_task(message: str) -> dict[str, Any]:
    text = normalize_text(message)
    artifact_type = detect_artifact_type(text)
    if artifact_type == "none":
        return {
            "message_kind": "chat_answer",
            "task_type": "none",
            "artifact_type": "none",
            "confidence": 0.0,
            "reason": "用户是在询问信息，不是在请求生成文件产物。",
            "requires_task_run": False,
            "requires_user_confirmation_before_external_effect": False,
            "risk_level": "low",
        }

    confidence = 0.92 if has_artifact_creation_verb(text) else 0.78
    if confidence < 0.8:
        return {
            "message_kind": "chat_answer",
            "task_type": "none",
            "artifact_type": "none",
            "confidence": confidence,
            "reason": "只检测到产物名，但没有明确生成或整理成文件的动作。",
            "requires_task_run": False,
            "requires_user_confirmation_before_external_effect": False,
            "risk_level": "low",
        }

    return {
        "message_kind": "task_request",
        "task_type": "artifact_creation",
        "artifact_type": artifact_type,
        "confidence": confidence,
        "reason": f"用户请求生成 {artifact_label(artifact_type)} 产物。",
        "requires_task_run": True,
        "requires_user_confirmation_before_external_effect": False,
        "risk_level": "medium",
    }


def build_context_requirement_plan(message: str) -> dict[str, Any]:
    text = normalize_text(message)
    entity_hint = extract_entity_hint(text)
    needed_context = [
        {
            "type": "recent_messages",
            "source": ["whatsapp", "telegram", "gmail"],
            "entity_hint": entity_hint,
            "time_window": "recent",
            "purpose": f"找到{entity_hint}刚刚给的资料" if entity_hint else "找到用户刚刚提到的资料",
        },
        {
            "type": "attachments",
            "source": ["gmail", "whatsapp", "telegram"],
            "entity_hint": entity_hint,
            "purpose": "查找可用于产物的附件、链接或文件",
        },
        {
            "type": "memory",
            "layers": ["kv", "graph", "rag"],
            "entity_hint": entity_hint,
            "purpose": f"补充{entity_hint}身份和项目背景" if entity_hint else "补充相关背景",
        },
    ]
    return {
        "needed_context": needed_context,
        "missing_user_inputs": artifact_missing_inputs(text),
        "can_start_without_missing_inputs": True,
    }


def build_evidence_pack(
    message: str,
    *,
    context_plan: dict[str, Any],
    source_context: list[dict[str, Any]] | None = None,
    memory_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    entity_hint = extract_entity_hint(message)
    source_items = source_context or []
    memory_items = memory_context or []
    evidence_items: list[dict[str, Any]] = []
    for item in source_items:
        evidence = evidence_from_item(item, entity_hint=entity_hint, default_type="event")
        if evidence:
            evidence_items.append(evidence)
    for item in memory_items:
        evidence = evidence_from_item(item, entity_hint=entity_hint, default_type="memory")
        if evidence:
            evidence_items.append(evidence)

    has_topic = bool(evidence_items)
    has_data_points = any(len(item.get("excerpt", "")) >= 8 for item in evidence_items)
    missing_evidence: list[str] = []
    if not evidence_items:
        missing_evidence.append(f"未找到{entity_hint}最近资料" if entity_hint else "未找到最近资料")
    missing_evidence.extend(str(value) for value in context_plan.get("missing_user_inputs") or [])

    return {
        "evidence_pack_id": f"evidence_pack_{uuid.uuid4().hex}",
        "items": evidence_items,
        "coverage": {
            "has_topic": has_topic,
            "has_audience": "目标听众" not in missing_evidence,
            "has_data_points": has_data_points,
            "has_file_attachments": any(item.get("source_type") == "file" for item in evidence_items),
        },
        "missing_evidence": missing_evidence,
    }


def build_artifact_task_payload(
    message: str,
    *,
    source_context: list[dict[str, Any]] | None = None,
    memory_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    route = route_artifact_task(message)
    context_plan = build_context_requirement_plan(message)
    evidence_pack = build_evidence_pack(
        message,
        context_plan=context_plan,
        source_context=source_context,
        memory_context=memory_context,
    )
    return {
        "route": route,
        "context_plan": context_plan,
        "evidence_pack": evidence_pack,
        "steps": ARTIFACT_TASK_STEPS,
        "created_at": utc_now_iso(),
    }


def artifact_task_answer(task: dict[str, Any], payload: dict[str, Any]) -> str:
    artifact_type = payload.get("route", {}).get("artifact_type") or task.get("artifact_type") or "artifact"
    evidence_items = payload.get("evidence_pack", {}).get("items") or []
    missing = payload.get("evidence_pack", {}).get("missing_evidence") or []
    title = task.get("title") or f"生成{artifact_label(str(artifact_type))}"
    if evidence_items:
        return (
            f"我已经创建任务：{title}。"
            f"目前找到 {len(evidence_items)} 条可追溯资料，先进入大纲整理；"
            "生成产物前会继续校验每页内容是否有依据。"
        )
    missing_text = "、".join(str(item) for item in missing[:3]) or "资料来源"
    return (
        f"我已经创建任务：{title}。"
        f"但当前资料还不够完整，缺口是：{missing_text}。"
        "我会先保留任务并等待你补充，避免编造内容。"
    )


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def has_artifact_creation_verb(text: str) -> bool:
    return any(keyword in text for keyword in ["帮我", "生成", "写一份", "做一份", "制作", "整理成", "导出", "改"])


def detect_artifact_type(text: str) -> str:
    if any(keyword in text for keyword in ["ppt", "pptx", "幻灯片", "演示文稿"]):
        return "pptx"
    if any(keyword in text for keyword in ["docx", "word", "文档", "报告", "方案"]):
        return "docx"
    if any(keyword in text for keyword in ["xlsx", "excel", "表格"]):
        return "xlsx"
    if any(keyword in text for keyword in ["markdown", "md"]):
        return "markdown"
    return "none"


def artifact_label(artifact_type: str) -> str:
    return {
        "pptx": "PPT",
        "docx": "文档",
        "xlsx": "表格",
        "markdown": "Markdown",
    }.get(artifact_type, "文件")


def extract_entity_hint(message: str) -> str:
    text = message or ""
    for pattern in [
        r"([\u4e00-\u9fa5]{1,3}总)",
        r"([\u4e00-\u9fa5]{1,4})(?:刚刚|给的|发的|资料)",
    ]:
        match = re.search(pattern, text)
        if match:
            return clean_entity_hint(match.group(1))
    return ""


def clean_entity_hint(value: str) -> str:
    cleaned = value.strip()
    for prefix in ["刚刚", "刚才", "之前", "最近"]:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    return cleaned


def artifact_missing_inputs(text: str) -> list[str]:
    missing: list[str] = []
    if not any(keyword in text for keyword in ["汇报", "复盘", "路演", "客户", "内部", "投资人", "老板"]):
        missing.append("PPT用途")
    if not any(keyword in text for keyword in ["给客户", "客户", "老板", "投资人", "团队", "内部"]):
        missing.append("目标听众")
    if not re.search(r"\d+\s*(页|p)", text):
        missing.append("期望页数")
    return missing


def evidence_from_item(item: dict[str, Any], *, entity_hint: str, default_type: str) -> dict[str, Any] | None:
    content = str(item.get("content") or item.get("text") or item.get("summary") or "").strip()
    if not content:
        return None
    actor = str(item.get("actor") or item.get("contact") or item.get("sender") or "").strip()
    combined = f"{actor} {content}"
    if entity_hint and entity_hint not in combined:
        return None
    evidence_id = str(item.get("event_id") or item.get("memory_id") or item.get("source_id") or f"evidence_{uuid.uuid4().hex}")
    return {
        "evidence_id": evidence_id,
        "source": str(item.get("source") or item.get("layer") or default_type),
        "source_type": str(item.get("source_type") or default_type),
        "actor": actor or entity_hint,
        "timestamp": str(item.get("timestamp") or item.get("created_at") or ""),
        "excerpt": excerpt(content),
        "confidence": 0.9 if entity_hint and entity_hint in combined else 0.76,
        "reason": f"包含{entity_hint}且与用户请求的资料相关" if entity_hint else "与用户请求的资料相关",
    }


def excerpt(content: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", content).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"
