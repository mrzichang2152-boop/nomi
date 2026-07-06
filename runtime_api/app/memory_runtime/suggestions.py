from __future__ import annotations

import hashlib
import re


def normalize_key_part(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower() or "unknown"


def build_suggestion_key(
    suggestion_type: str,
    primary_evidence_id: str,
    primary_evidence_version: str,
    target_user_id: str,
    channel: str,
) -> str:
    suggestion = normalize_key_part(suggestion_type)
    target = normalize_key_part(target_user_id)
    normalized_channel = normalize_key_part(channel)
    material = "|".join(
        [
            suggestion,
            normalize_key_part(primary_evidence_id),
            normalize_key_part(primary_evidence_version),
            target,
            normalized_channel,
        ]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    return f"{suggestion}:{target}:{normalized_channel}:{digest}"
