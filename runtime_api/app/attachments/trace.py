from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


TRACE_TIMING_KEYS = (
    "upload_ms",
    "hash_ms",
    "store_ms",
    "parse_ms",
    "chunk_ms",
    "embed_ms",
    "retrieve_ms",
    "render_ms",
    "upstream_first_chunk_ms",
    "formal_first_character_ms",
    "total_ms",
)

_LOCATOR_KEYS = {
    "page",
    "slide",
    "sheet",
    "cell",
    "cell_range",
    "row",
    "row_start",
    "row_end",
    "paragraph",
    "paragraph_start",
    "paragraph_end",
    "section",
    "item",
    "ordinal",
}
_SAFE_RECORD_KEYS = {
    "attachment_id",
    "turn_id",
    "evidence_id",
    "mime_type",
    "kind",
    "status",
    "processing_version",
    "content_hash",
    "chunk_ordinal",
    "reason",
}
_HTML_TAG_RE = re.compile(r"<[^>]*>")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SAFE_TOKEN_RE = re.compile(r"[^A-Za-z0-9_.:+@-]")
_SAFE_MIME_RE = re.compile(r"[^A-Za-z0-9_.+/-]")


def attachment_memory_policy(event_type: str) -> str:
    """Attachments become durable memory only through the dialogue batch lifecycle."""
    return "eligible" if str(event_type).strip() == "dialogue_batch" else "none"


def _plain_text(value: object, *, limit: int = 160) -> str:
    text = html.unescape(str(value or ""))
    text = _HTML_TAG_RE.sub("", text)
    text = _CONTROL_RE.sub("", text).strip()
    return text[:limit]


def _safe_token(value: object, *, limit: int = 200) -> str:
    text = _plain_text(value, limit=limit)
    if ".." in text or text.startswith(("/", "\\")) or "sk-" in text.lower():
        return ""
    return _SAFE_TOKEN_RE.sub("", text)[:limit]


def _safe_mime_type(value: object) -> str:
    text = _plain_text(value, limit=120).lower()
    if text.count("/") != 1 or ".." in text or text.startswith(("/", "\\")):
        return ""
    return _SAFE_MIME_RE.sub("", text)[:120]


def sanitize_locator(locator: object) -> dict[str, object]:
    if not isinstance(locator, Mapping):
        return {}
    result: dict[str, object] = {}
    for key in sorted(_LOCATOR_KEYS):
        if key not in locator:
            continue
        value = locator[key]
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            if value >= 0:
                result[key] = value
            continue
        if isinstance(value, float):
            if value >= 0:
                result[key] = value
            continue
        cleaned = _plain_text(value, limit=120)
        if cleaned and ".." not in cleaned and not cleaned.startswith(("/", "\\")):
            result[key] = cleaned
    return result


def sanitize_attachment_record(record: object) -> dict[str, object]:
    if not isinstance(record, Mapping):
        return {}
    result: dict[str, object] = {}
    for key in sorted(_SAFE_RECORD_KEYS):
        if key not in record:
            continue
        value = record[key]
        if key == "chunk_ordinal":
            if isinstance(value, int) and value >= 0:
                result[key] = value
            continue
        cleaned = _safe_mime_type(value) if key == "mime_type" else _safe_token(value)
        if cleaned:
            result[key] = cleaned
    locator = sanitize_locator(record.get("locator"))
    if locator:
        result["locator"] = locator
    return result


def safe_attachment_error(_error: object) -> dict[str, str]:
    return {
        "error_code": "attachment_processing_failed",
        "message": "附件处理失败，请重试或更换文件。",
    }


def sanitize_attachment_trace(trace: object) -> dict[str, object]:
    if not isinstance(trace, Mapping):
        return {}
    result = sanitize_attachment_record(trace)
    if "error" in trace or "exception" in trace:
        result.update(safe_attachment_error(trace.get("error") or trace.get("exception")))
    return result


def _dedupe_records(records: Iterable[object]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in records:
        record = sanitize_attachment_record(raw)
        if not record:
            continue
        fingerprint = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        result.append(record)
    return result


def merge_attachment_provenance(
    existing: Iterable[object],
    incoming: Iterable[object],
) -> list[dict[str, object]]:
    """Append immutable evidence versions while deduplicating exact records."""
    return _dedupe_records([*existing, *incoming])


def load_attachment_provenance_for_turns(
    conn: object,
    turn_ids: Sequence[object],
) -> list[dict[str, object]]:
    normalized_turn_ids = list(turn_ids)
    if not normalized_turn_ids:
        return []
    rows = conn.execute(
        """
        SELECT relation.turn_id, attachment.id,
               COALESCE(attachment.detected_mime_type, attachment.declared_mime_type),
               attachment.status, attachment.processing_version,
               chunk.locator, COALESCE(chunk.content_hash, attachment.sha256), chunk.ordinal
        FROM assistant_turn_attachments relation
        JOIN chat_attachments attachment ON attachment.id = relation.attachment_id
        LEFT JOIN chat_attachment_chunks chunk
          ON chunk.attachment_id = attachment.id
         AND chunk.processing_version = attachment.processing_version
        WHERE relation.turn_id = ANY(%s::UUID[])
        ORDER BY relation.turn_id, relation.ordinal, chunk.ordinal
        LIMIT 512
        """,
        (normalized_turn_ids,),
    ).fetchall()
    provenance = []
    for row in rows:
        provenance.append(
            {
                "turn_id": str(row[0]),
                "attachment_id": str(row[1]),
                "mime_type": str(row[2] or "application/octet-stream"),
                "status": str(row[3] or ""),
                "processing_version": str(row[4] or ""),
                "locator": row[5] if isinstance(row[5], Mapping) and row[5] else {"ordinal": 0},
                "content_hash": str(row[6] or ""),
                "chunk_ordinal": int(row[7]) if row[7] is not None else 0,
            }
        )
    return _dedupe_records(provenance)


def _safe_timing(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0, value)


def build_attachment_trace(
    *,
    request_id: object,
    client_request_id: object,
    turn_id: object,
    attachment_records: Iterable[object],
    selected: Iterable[object],
    excluded: Iterable[object],
    timings: Mapping[str, object],
    visual_count: int = 0,
    retry_count: int = 0,
) -> dict[str, object]:
    attachments = _dedupe_records(attachment_records)
    selected_locators = _dedupe_records(selected)
    excluded_locators = _dedupe_records(excluded)
    return {
        "request_id": _safe_token(request_id),
        "client_request_id": _safe_token(client_request_id),
        "turn_id": _safe_token(turn_id),
        "retry_count": max(0, int(retry_count)),
        "attachment_count": len(attachments),
        "attachments": attachments,
        "selected_locators": selected_locators,
        "excluded_locators": excluded_locators,
        "visual_count": max(0, int(visual_count)),
        "timings": {key: _safe_timing(timings.get(key)) for key in TRACE_TIMING_KEYS},
    }


def enrich_attachment_traces(
    context_pack: object,
    timings: Mapping[str, object],
) -> int:
    if not isinstance(context_pack, dict):
        return 0
    attachment_context = context_pack.get("attachment_context")
    if not isinstance(attachment_context, list):
        return 0
    safe_updates = {
        key: timing
        for key in TRACE_TIMING_KEYS
        if (timing := _safe_timing(timings.get(key))) is not None
    }
    updated = 0
    for item in attachment_context:
        if not isinstance(item, dict):
            continue
        trace = item.get("trace")
        if not isinstance(trace, dict):
            continue
        current = trace.get("timings") if isinstance(trace.get("timings"), dict) else {}
        trace["timings"] = {**current, **safe_updates}
        updated += 1
    return updated


__all__ = [
    "TRACE_TIMING_KEYS",
    "attachment_memory_policy",
    "build_attachment_trace",
    "enrich_attachment_traces",
    "load_attachment_provenance_for_turns",
    "merge_attachment_provenance",
    "safe_attachment_error",
    "sanitize_attachment_record",
    "sanitize_attachment_trace",
    "sanitize_locator",
]
