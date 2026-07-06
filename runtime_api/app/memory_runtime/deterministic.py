from __future__ import annotations

from datetime import datetime
from typing import Any


RELATION_LABELS = {
    "has_son": "儿子",
    "has_daughter": "女儿",
    "has_child": "孩子",
    "works_at": "任职单位",
}

CANCELED_STATUSES = {"canceled", "cancelled", "deleted", "ignored"}


def answer_relationship_question(question: str, edges: list[dict[str, Any]]) -> dict[str, Any]:
    question_text = str(question or "")
    for edge in edges:
        if str(edge.get("status") or "active") != "active":
            continue
        object_label = str(edge.get("object_label") or edge.get("object") or "").strip()
        subject_label = str(edge.get("subject_label") or edge.get("subject") or "").strip()
        relation = str(edge.get("relation_type") or "").strip()
        relation_label = RELATION_LABELS.get(relation)
        if not object_label or not subject_label or not relation_label:
            continue
        if object_label and object_label in question_text:
            return {
                "answered": True,
                "answer": f"{object_label}是{subject_label}的{relation_label}。",
                "evidence": [edge],
                "confidence": float(edge.get("confidence") or 0.8),
            }
    return {"answered": False, "answer": "", "evidence": [], "confidence": 0.0}


def format_absolute_time(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return raw


def answer_agenda_time_question(question: str, agenda_items: list[dict[str, Any]]) -> dict[str, Any]:
    question_text = str(question or "")
    for item in agenda_items:
        if str(item.get("status") or "").lower() in CANCELED_STATUSES:
            continue
        place = str(item.get("place") or "").strip()
        title = str(item.get("title") or "").strip()
        if place and place not in question_text and title and title not in question_text:
            continue
        start_at = format_absolute_time(str(item.get("start_at") or item.get("start_time") or ""))
        if not start_at:
            continue
        subject = place or title or "这个安排"
        return {
            "answered": True,
            "answer": f"{subject}的时间是 {start_at}。",
            "evidence": [item],
            "confidence": float(item.get("confidence") or 0.8),
        }
    return {"answered": False, "answer": "", "evidence": [], "confidence": 0.0}
