from __future__ import annotations

import re
from typing import Any


OWNER_SOURCES = {"android_chat", "web_chat", "nomi_chat", "assistant_chat"}
FIRST_PERSON_RE = re.compile(r"(^|[，,。.\s])我(?:的)?(?:儿子|女儿|孩子|朋友|同事|老婆|老公|妻子|丈夫)")
RELATION_SUBJECT_RE = re.compile(r"(?P<subject>[\u4e00-\u9fffA-Za-z0-9_]{1,32})(?:他|她|的)?(?:儿子|女儿|孩子|朋友|同事|老婆|老公|妻子|丈夫)")


def resolve_fact_subject(
    *,
    text: str,
    source: str,
    owner_user_id: str,
    speaker_id: str,
    speaker_display_name: str,
    known_entities: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    content = str(text or "").strip()
    source_name = str(source or "").strip().lower()
    owner = str(owner_user_id or "default").strip()
    speaker = str(speaker_id or "").strip() or "unknown_speaker"
    speaker_label = str(speaker_display_name or "").strip() or speaker
    entities = [str(entity).strip() for entity in (known_entities or []) if str(entity).strip()]

    relation_match = RELATION_SUBJECT_RE.search(content)
    if relation_match:
        subject = relation_match.group("subject").strip()
        if subject and subject != "我":
            for entity in entities:
                if entity == subject or subject in entity or entity in subject:
                    subject = entity
                    break
            return {
                "subject_id": subject,
                "subject_label": subject,
                "ownership": "named_entity",
                "confidence": 0.9,
                "reason": "third-person relationship subject was explicit in message text",
            }

    if FIRST_PERSON_RE.search(content):
        if source_name in OWNER_SOURCES or speaker == owner:
            return {
                "subject_id": owner,
                "subject_label": speaker_label or owner,
                "ownership": "owner",
                "confidence": 0.95,
                "reason": "first-person fact came from direct Nomi conversation",
            }
        return {
            "subject_id": speaker,
            "subject_label": speaker_label,
            "ownership": "speaker",
            "confidence": 0.9,
            "reason": "first-person fact came from an external contact message",
        }

    return {
        "subject_id": speaker if source_name not in OWNER_SOURCES else owner,
        "subject_label": speaker_label if source_name not in OWNER_SOURCES else owner,
        "ownership": "speaker" if source_name not in OWNER_SOURCES else "owner",
        "confidence": 0.45,
        "reason": "no explicit relationship subject found; using conservative source owner fallback",
    }
