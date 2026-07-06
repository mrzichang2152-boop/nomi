from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any


def normalize_source_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_source_part(value: str | None) -> str:
    cleaned = normalize_source_text(value)
    return cleaned or "unknown"


def minute_bucket(value: str | None) -> str:
    raw = normalize_source_text(value)
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(second=0, microsecond=0).isoformat()
    except ValueError:
        return raw[:16]


def short_hash(value: Any, length: int = 16) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def build_source_fingerprint(
    *,
    source: str,
    account_id: str,
    conversation_id: str,
    speaker_id: str,
    text: str,
    source_created_at: str | None,
) -> str:
    parts = [
        normalize_source_part(source).lower(),
        normalize_source_part(account_id),
        normalize_source_part(conversation_id),
        normalize_source_part(speaker_id),
        normalize_source_text(text),
        minute_bucket(source_created_at),
    ]
    return short_hash("|".join(parts))


def build_source_event_uid(
    *,
    source: str,
    account_id: str,
    conversation_id: str,
    message_id: str | None,
    speaker_id: str,
    text: str,
    source_created_at: str | None,
) -> str:
    prefix = ":".join(
        [
            normalize_source_part(source).lower(),
            normalize_source_part(account_id),
            normalize_source_part(conversation_id),
        ]
    )
    normalized_message_id = normalize_source_text(message_id)
    if normalized_message_id:
        return f"{prefix}:{normalize_source_part(normalized_message_id)}"
    fingerprint = build_source_fingerprint(
        source=source,
        account_id=account_id,
        conversation_id=conversation_id,
        speaker_id=speaker_id,
        text=text,
        source_created_at=source_created_at,
    )
    return f"{prefix}:fp:{fingerprint}"


def normalize_ingest_payload(
    *,
    source: str,
    account_id: str,
    conversation_id: str,
    contact_id: str,
    speaker_id: str,
    message_id: str | None,
    text: str,
    source_created_at: str | None,
    observed_at: str | None,
    raw_event_id: str,
) -> dict[str, Any]:
    source_fingerprint = build_source_fingerprint(
        source=source,
        account_id=account_id,
        conversation_id=conversation_id,
        speaker_id=speaker_id,
        text=text,
        source_created_at=source_created_at,
    )
    return {
        "source_event_uid": build_source_event_uid(
            source=source,
            account_id=account_id,
            conversation_id=conversation_id,
            message_id=message_id,
            speaker_id=speaker_id,
            text=text,
            source_created_at=source_created_at,
        ),
        "source_fingerprint": source_fingerprint,
        "source": normalize_source_part(source).lower(),
        "account_id": normalize_source_text(account_id),
        "conversation_id": normalize_source_text(conversation_id),
        "contact_id": normalize_source_text(contact_id),
        "speaker_id": normalize_source_text(speaker_id),
        "message_id": normalize_source_text(message_id),
        "source_created_at": normalize_source_text(source_created_at),
        "observed_at": normalize_source_text(observed_at),
        "payload_hash": short_hash(
            {
                "text": normalize_source_text(text),
                "source_created_at": normalize_source_text(source_created_at),
                "speaker_id": normalize_source_text(speaker_id),
            }
        ),
        "raw_event_id": normalize_source_text(raw_event_id),
        "status": "raw_written",
        "attempts": 0,
        "last_error": "",
    }
