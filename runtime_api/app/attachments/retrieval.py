from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable, Optional, Sequence
from uuid import UUID, uuid4

from app.attachments.citations import citation_label


FULL_TEXT_TOKEN_THRESHOLD = 24_000
DEFAULT_ATTACHMENT_TOKEN_BUDGET = 64_000
DEFAULT_TOTAL_CONTEXT_BUDGET = 256_000
DEFAULT_VISUAL_LIMIT = 6


class EvidenceMode(str, Enum):
    FULL_TEXT = "full_text"
    HYBRID = "hybrid"
    FULL_INSPECTION = "full_inspection"


@dataclass(frozen=True)
class AttachmentChunk:
    attachment_id: UUID
    ordinal: int
    text: str
    token_count: int
    locator: dict[str, object]
    content_hash: str
    vector_score: float = 0.0
    low_text_density: bool = False
    contains_visual: bool = False
    text_insufficient: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "attachment_id", UUID(str(self.attachment_id)))
        object.__setattr__(self, "ordinal", max(0, int(self.ordinal)))
        object.__setattr__(self, "token_count", max(0, int(self.token_count)))
        object.__setattr__(self, "locator", dict(self.locator))
        if not self.content_hash:
            digest = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
            object.__setattr__(self, "content_hash", digest)


@dataclass(frozen=True)
class AttachmentEvidence:
    attachment_id: UUID
    filename: str
    kind: str
    chunks: tuple[AttachmentChunk, ...] = field(default_factory=tuple)
    page_count: Optional[int] = None
    slide_count: Optional[int] = None

    def __post_init__(self) -> None:
        normalized_id = UUID(str(self.attachment_id))
        object.__setattr__(self, "attachment_id", normalized_id)
        ordered = tuple(sorted(self.chunks, key=lambda item: item.ordinal))
        if any(item.attachment_id != normalized_id for item in ordered):
            raise ValueError("attachment_chunk_owner_mismatch")
        object.__setattr__(self, "chunks", ordered)


@dataclass(frozen=True)
class SelectedTextEvidence:
    evidence_id: str
    attachment_id: UUID
    filename: str
    kind: str
    ordinal: int
    text: str
    token_count: int
    locator: dict[str, object]
    content_hash: str
    score: float


@dataclass(frozen=True)
class SelectedVisualEvidence:
    evidence_id: str
    attachment_id: UUID
    filename: str
    kind: str
    locator: dict[str, object]
    reason: str
    score: float


@dataclass(frozen=True)
class EvidenceExclusion:
    attachment_id: UUID
    filename: str
    locator: dict[str, object]
    reason: str
    evidence_id: Optional[str] = None


@dataclass(frozen=True)
class EvidenceCoverage:
    complete: bool
    selected_count: int
    total_count: int
    selected_locators: tuple[dict[str, object], ...]
    excluded_locators: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class InspectionLocator:
    attachment_id: UUID
    filename: str
    kind: str
    locator: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "attachment_id": str(self.attachment_id),
            "filename": self.filename,
            "kind": self.kind,
            "locator": dict(self.locator),
        }


@dataclass(frozen=True)
class EvidencePlan:
    mode: EvidenceMode
    text_items: tuple[SelectedTextEvidence, ...]
    visual_items: tuple[SelectedVisualEvidence, ...]
    exclusions: tuple[EvidenceExclusion, ...]
    coverage: EvidenceCoverage
    total_tokens: int
    effective_attachment_budget: int
    tokens_by_attachment: dict[str, int]
    requires_async_full_inspection: bool = False
    inspection_locators: tuple[InspectionLocator, ...] = field(default_factory=tuple)


def _canonical_locator(locator: dict[str, object]) -> str:
    return json.dumps(locator, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_evidence_id(attachment_id: UUID, content_hash: str, locator: dict[str, object]) -> str:
    payload = f"{attachment_id}|{content_hash}|{_canonical_locator(locator)}".encode("utf-8")
    return "att-evidence-" + hashlib.sha256(payload).hexdigest()[:24]


def _is_explicit_full_inspection(question: str) -> bool:
    normalized = re.sub(r"\s+", "", str(question or "").lower())
    patterns = (
        "逐页",
        "每一页",
        "所有页面",
        "全部页面",
        "逐张",
        "每一张",
        "全部幻灯片",
        "所有幻灯片",
    )
    return any(pattern in normalized for pattern in patterns)


def _visual_question(question: str) -> bool:
    normalized = str(question or "").lower()
    return any(
        term in normalized
        for term in ("布局", "颜色", "视觉", "图像", "图片", "图表", "流程图", "截图", "节点关系")
    )


def _query_terms(question: str) -> tuple[str, ...]:
    normalized = re.sub(r"\s+", "", str(question or "").lower())
    segments = re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", normalized)
    terms: set[str] = set(segments)
    for segment in segments:
        if re.fullmatch(r"[\u4e00-\u9fff]+", segment):
            for size in range(2, min(6, len(segment)) + 1):
                terms.update(segment[index : index + size] for index in range(len(segment) - size + 1))
    return tuple(sorted(terms, key=lambda value: (-len(value), value)))


def _hybrid_score(question: str, candidate: AttachmentChunk) -> float:
    text = candidate.text.lower()
    terms = _query_terms(question)
    lexical_hits = sum(1 for term in terms if term in text)
    lexical = min(1.0, lexical_hits / max(1, min(5, len(terms))))
    vector = max(0.0, min(1.0, float(candidate.vector_score)))
    return round((0.55 * lexical) + (0.45 * vector), 8)


def _all_chunks(attachments: Sequence[AttachmentEvidence]) -> list[tuple[AttachmentEvidence, AttachmentChunk]]:
    return [(source, candidate) for source in attachments for candidate in source.chunks]


def _selected_item(
    source: AttachmentEvidence,
    candidate: AttachmentChunk,
    score: float,
) -> SelectedTextEvidence:
    return SelectedTextEvidence(
        evidence_id=stable_evidence_id(source.attachment_id, candidate.content_hash, candidate.locator),
        attachment_id=source.attachment_id,
        filename=source.filename,
        kind=source.kind,
        ordinal=candidate.ordinal,
        text=candidate.text,
        token_count=candidate.token_count,
        locator=dict(candidate.locator),
        content_hash=candidate.content_hash,
        score=score,
    )


def _visual_reason(candidate: AttachmentChunk, *, kind: str, visual_question: bool) -> Optional[str]:
    if candidate.low_text_density:
        return "low_text_density"
    if candidate.contains_visual or kind == "image":
        return "contains_visual"
    if visual_question:
        return "visual_question"
    if candidate.text_insufficient:
        return "text_insufficient"
    return None


def _effective_budget(
    attachment_budget: int,
    total_context_budget: int,
    already_reserved_context_tokens: int,
    reserved_output_tokens: int,
) -> int:
    remaining = max(
        0,
        int(total_context_budget) - int(already_reserved_context_tokens) - int(reserved_output_tokens),
    )
    return max(0, min(int(attachment_budget), remaining))


def plan_attachment_evidence(
    question: str,
    attachments: Sequence[AttachmentEvidence],
    *,
    total_attachment_budget: int = DEFAULT_ATTACHMENT_TOKEN_BUDGET,
    total_context_budget: int = DEFAULT_TOTAL_CONTEXT_BUDGET,
    already_reserved_context_tokens: int = 0,
    reserved_output_tokens: int = 0,
    full_text_threshold: int = FULL_TEXT_TOKEN_THRESHOLD,
    max_visual_items: int = DEFAULT_VISUAL_LIMIT,
) -> EvidencePlan:
    ordered_attachments = tuple(attachments)
    effective_budget = _effective_budget(
        total_attachment_budget,
        total_context_budget,
        already_reserved_context_tokens,
        reserved_output_tokens,
    )
    all_candidates = _all_chunks(ordered_attachments)
    inspection_locators = tuple(
        InspectionLocator(source.attachment_id, source.filename, source.kind, dict(candidate.locator))
        for source, candidate in all_candidates
    )
    if _is_explicit_full_inspection(question):
        coverage = EvidenceCoverage(
            complete=False,
            selected_count=0,
            total_count=len(all_candidates),
            selected_locators=(),
            excluded_locators=tuple(dict(candidate.locator) for _, candidate in all_candidates),
        )
        return EvidencePlan(
            mode=EvidenceMode.FULL_INSPECTION,
            text_items=(),
            visual_items=(),
            exclusions=tuple(
                EvidenceExclusion(source.attachment_id, source.filename, dict(candidate.locator), "async_full_inspection")
                for source, candidate in all_candidates
            ),
            coverage=coverage,
            total_tokens=0,
            effective_attachment_budget=effective_budget,
            tokens_by_attachment={},
            requires_async_full_inspection=True,
            inspection_locators=inspection_locators,
        )

    total_tokens = sum(candidate.token_count for _, candidate in all_candidates)
    large_document = any(
        (source.kind == "pdf" and int(source.page_count or 0) > 20)
        or (source.kind == "pptx" and int(source.slide_count or 0) > 30)
        for source in ordered_attachments
    )
    mode = (
        EvidenceMode.FULL_TEXT
        if total_tokens <= int(full_text_threshold) and total_tokens <= effective_budget and not large_document
        else EvidenceMode.HYBRID
    )
    scored = [
        (source, candidate, 1.0 if mode == EvidenceMode.FULL_TEXT else _hybrid_score(question, candidate))
        for source, candidate in all_candidates
    ]
    if mode == EvidenceMode.FULL_TEXT:
        ranked = scored
    else:
        ranked = sorted(
            scored,
            key=lambda item: (-item[2], str(item[0].attachment_id), item[1].ordinal),
        )

    selected: list[SelectedTextEvidence] = []
    exclusions: list[EvidenceExclusion] = []
    selected_hashes: set[str] = set()
    selected_locator_keys: set[tuple[UUID, str]] = set()
    selected_candidate_keys: set[tuple[UUID, int]] = set()
    used_tokens = 0

    def try_select(source: AttachmentEvidence, candidate: AttachmentChunk, score: float) -> bool:
        nonlocal used_tokens
        candidate_key = (source.attachment_id, candidate.ordinal)
        if candidate_key in selected_candidate_keys:
            return False
        evidence_id = stable_evidence_id(source.attachment_id, candidate.content_hash, candidate.locator)
        if candidate.content_hash in selected_hashes:
            exclusions.append(
                EvidenceExclusion(source.attachment_id, source.filename, dict(candidate.locator), "duplicate_content", evidence_id)
            )
            selected_candidate_keys.add(candidate_key)
            return False
        locator_key = (source.attachment_id, _canonical_locator(candidate.locator))
        if locator_key in selected_locator_keys:
            exclusions.append(
                EvidenceExclusion(source.attachment_id, source.filename, dict(candidate.locator), "duplicate_locator", evidence_id)
            )
            selected_candidate_keys.add(candidate_key)
            return False
        if used_tokens + candidate.token_count > effective_budget:
            exclusions.append(
                EvidenceExclusion(source.attachment_id, source.filename, dict(candidate.locator), "budget_exceeded", evidence_id)
            )
            selected_candidate_keys.add(candidate_key)
            return False
        selected.append(_selected_item(source, candidate, score))
        selected_hashes.add(candidate.content_hash)
        selected_locator_keys.add(locator_key)
        selected_candidate_keys.add(candidate_key)
        used_tokens += candidate.token_count
        return True

    if mode == EvidenceMode.HYBRID:
        for source in ordered_attachments:
            per_attachment = [item for item in ranked if item[0].attachment_id == source.attachment_id]
            for candidate_source, candidate, score in per_attachment:
                if try_select(candidate_source, candidate, score):
                    break
    for source, candidate, score in ranked:
        try_select(source, candidate, score)

    selected_keys = {(item.attachment_id, item.ordinal) for item in selected}
    excluded_keys = {
        (item.attachment_id, _canonical_locator(item.locator), item.reason)
        for item in exclusions
    }
    for source, candidate, score in scored:
        if (source.attachment_id, candidate.ordinal) in selected_keys:
            continue
        locator_key = _canonical_locator(candidate.locator)
        if any(key[0] == source.attachment_id and key[1] == locator_key for key in excluded_keys):
            continue
        reason = "not_relevant" if mode == EvidenceMode.HYBRID and score <= 0 else "budget_exceeded"
        exclusions.append(
            EvidenceExclusion(
                source.attachment_id,
                source.filename,
                dict(candidate.locator),
                reason,
                stable_evidence_id(source.attachment_id, candidate.content_hash, candidate.locator),
            )
        )

    visual_question = _visual_question(question)
    visual_candidates: list[tuple[SelectedTextEvidence, str]] = []
    chunk_by_key = {
        (source.attachment_id, candidate.ordinal): candidate for source, candidate in all_candidates
    }
    for item in selected:
        source_chunk = chunk_by_key[(item.attachment_id, item.ordinal)]
        reason = _visual_reason(source_chunk, kind=item.kind, visual_question=visual_question)
        if reason is not None:
            visual_candidates.append((item, reason))
    visual_candidates.sort(key=lambda item: (-item[0].score, str(item[0].attachment_id), item[0].ordinal))
    visual_items = tuple(
        SelectedVisualEvidence(
            evidence_id=item.evidence_id,
            attachment_id=item.attachment_id,
            filename=item.filename,
            kind=item.kind,
            locator=dict(item.locator),
            reason=reason,
            score=item.score,
        )
        for item, reason in visual_candidates[: max(0, int(max_visual_items))]
    )
    for item, _ in visual_candidates[max(0, int(max_visual_items)) :]:
        exclusions.append(
            EvidenceExclusion(
                item.attachment_id,
                item.filename,
                dict(item.locator),
                "visual_limit",
                item.evidence_id,
            )
        )

    tokens_by_attachment: dict[str, int] = {}
    for item in selected:
        key = str(item.attachment_id)
        tokens_by_attachment[key] = tokens_by_attachment.get(key, 0) + item.token_count
    text_exclusion_count = len(all_candidates) - len(selected)
    coverage = EvidenceCoverage(
        complete=text_exclusion_count == 0,
        selected_count=len(selected),
        total_count=len(all_candidates),
        selected_locators=tuple(dict(item.locator) for item in selected),
        excluded_locators=tuple(
            dict(item.locator)
            for item in exclusions
            if item.reason != "visual_limit"
        ),
    )
    return EvidencePlan(
        mode=mode,
        text_items=tuple(selected),
        visual_items=visual_items,
        exclusions=tuple(exclusions),
        coverage=coverage,
        total_tokens=used_tokens,
        effective_attachment_budget=effective_budget,
        tokens_by_attachment=tokens_by_attachment,
        requires_async_full_inspection=False,
        inspection_locators=inspection_locators,
    )


def build_full_inspection_task(
    plan: EvidencePlan,
    *,
    user_turn_id: UUID,
    batch_size: int = 6,
) -> dict[str, object]:
    if not plan.requires_async_full_inspection:
        raise ValueError("full_inspection_not_requested")
    normalized_batch_size = max(1, int(batch_size))
    locators = [item.as_dict() for item in plan.inspection_locators]
    return {
        "task_type": "attachment_full_inspection",
        "status": "pending",
        "user_turn_id": str(UUID(str(user_turn_id))),
        "total_locators": len(locators),
        "batches": [locators[index : index + normalized_batch_size] for index in range(0, len(locators), normalized_batch_size)],
        "completed_locators": [],
        "failed_locators": [],
        "coverage_status": "pending",
    }


def _inspection_locator_key(item: dict[str, object]) -> str:
    return json.dumps(
        {
            "attachment_id": str(item.get("attachment_id") or ""),
            "locator": item.get("locator") if isinstance(item.get("locator"), dict) else {},
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _all_inspection_locators(contract: dict[str, object]) -> list[dict[str, object]]:
    return [
        dict(item)
        for batch in (contract.get("batches") or [])
        if isinstance(batch, list)
        for item in batch
        if isinstance(item, dict)
    ]


def process_full_inspection_batch(
    contract: dict[str, object],
    inspector: Callable[[dict[str, object]], dict[str, object]],
    *,
    batch_index: Optional[int] = None,
    force_terminal: bool = False,
) -> dict[str, object]:
    """Advance one bounded batch without reprocessing durable locator results."""

    if str(contract.get("task_type") or "") != "attachment_full_inspection":
        raise ValueError("invalid_full_inspection_task_type")
    updated = deepcopy(contract)
    batches = [list(batch) for batch in (updated.get("batches") or []) if isinstance(batch, list)]
    completed = [dict(item) for item in (updated.get("completed_locators") or []) if isinstance(item, dict)]
    failed = [dict(item) for item in (updated.get("failed_locators") or []) if isinstance(item, dict)]
    processed_keys = {_inspection_locator_key(item) for item in completed + failed}

    selected_batch: list[dict[str, object]] = []
    selected_index: Optional[int] = None
    if not force_terminal:
        candidate_indexes = [batch_index] if batch_index is not None else list(range(len(batches)))
        for index in candidate_indexes:
            if index is None or index < 0 or index >= len(batches):
                continue
            pending = [
                dict(item)
                for item in batches[index]
                if isinstance(item, dict) and _inspection_locator_key(item) not in processed_keys
            ]
            if pending:
                selected_batch = pending
                selected_index = index
                break

    for locator in selected_batch:
        durable_locator = dict(locator)
        try:
            output = inspector(dict(locator))
            if not isinstance(output, dict):
                raise TypeError("inspection_output_must_be_mapping")
            completed.append({**durable_locator, "output": dict(output)})
        except Exception as exc:
            failed.append({**durable_locator, "error": str(exc)[:240] or exc.__class__.__name__})
        processed_keys.add(_inspection_locator_key(locator))

    all_locators = _all_inspection_locators(updated)
    unprocessed = [item for item in all_locators if _inspection_locator_key(item) not in processed_keys]
    terminal = force_terminal or not unprocessed
    coverage_status = "complete" if terminal and not failed and not unprocessed else "partial" if terminal else "running"
    updated.update(
        {
            "status": "completed" if terminal else "running",
            "coverage_status": coverage_status,
            "completed_locators": completed,
            "failed_locators": failed,
            "unprocessed_locators": unprocessed,
            "last_batch_index": selected_index,
            "progress": {
                "processed": len(completed) + len(failed),
                "total": len(all_locators),
                "succeeded": len(completed),
                "failed": len(failed),
            },
        }
    )
    if terminal:
        updated["final_summary"] = terminal_full_inspection_summary(updated)
    return updated


def _locator_display(item: dict[str, object]) -> str:
    filename = str(item.get("filename") or "附件")
    kind = str(item.get("kind") or "file")
    locator = item.get("locator") if isinstance(item.get("locator"), dict) else {}
    return citation_label(filename, kind, locator)


def terminal_full_inspection_summary(contract: dict[str, object]) -> str:
    completed = [item for item in (contract.get("completed_locators") or []) if isinstance(item, dict)]
    failed = [item for item in (contract.get("failed_locators") or []) if isinstance(item, dict)]
    unprocessed = [item for item in (contract.get("unprocessed_locators") or []) if isinstance(item, dict)]
    total = int(contract.get("total_locators") or len(_all_inspection_locators(contract)))
    if not failed and not unprocessed and len(completed) == total:
        return f"逐页附件检查已完成：共检查 {total} 个位置，覆盖完整。"
    failed_text = "、".join(_locator_display(item) for item in failed) or "无"
    unprocessed_text = "、".join(_locator_display(item) for item in unprocessed) or "无"
    return (
        f"逐页附件检查部分完成：已成功检查 {len(completed)}/{total} 个位置；"
        f"失败位置：{failed_text}；未处理位置：{unprocessed_text}。"
    )


def should_retrieve_attachment_evidence(
    *,
    message: str = "",
    current_attachment_ids: Sequence[UUID] = (),
    prior_attachment_ids: Sequence[UUID] = (),
    route_requires_file_evidence: bool = False,
) -> bool:
    if current_attachment_ids or route_requires_file_evidence:
        return True
    if not prior_attachment_ids:
        return False
    normalized = str(message or "").lower()
    return any(
        term in normalized
        for term in ("附件", "文件", "刚才", "上传", "pdf", "ppt", "word", "表格", "图片", "文档")
    )


def _manifest_count(metadata: dict[str, object], key: str) -> Optional[int]:
    manifest = metadata.get("manifest") if isinstance(metadata.get("manifest"), dict) else {}
    value = manifest.get(key) if isinstance(manifest, dict) else None
    try:
        return max(0, int(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def load_attachment_evidence(
    conn: object,
    attachment_ids: Sequence[UUID],
    *,
    query_embedding: Optional[Sequence[float]] = None,
) -> list[AttachmentEvidence]:
    """Load all requested attachment chunks in one scoped query."""

    normalized_ids = list(dict.fromkeys(UUID(str(value)) for value in attachment_ids))
    if not normalized_ids:
        return []
    vector_expression = "0.0"
    params: list[object] = []
    if query_embedding:
        vector_expression = (
            "COALESCE(GREATEST(0.0, LEAST(1.0, "
            "1.0 - (chunk.embedding <=> %s::vector))), 0.0)"
        )
        params.append(list(query_embedding))
    rows = conn.execute(
        f"""
        SELECT attachment.id, attachment.safe_filename, attachment.parser_kind,
               chunk.ordinal, chunk.text, chunk.token_count, chunk.locator,
               chunk.content_hash, {vector_expression} AS vector_score,
               COALESCE(manifest.metadata, '{{}}'::jsonb) AS manifest_metadata,
               (length(trim(chunk.text)) < 80) AS low_text_density,
               EXISTS (
                 SELECT 1
                 FROM chat_attachment_derivatives visual
                 WHERE visual.attachment_id = attachment.id
                   AND visual.processing_version = attachment.processing_version
                   AND visual.kind <> 'manifest'
                   AND visual.locator = chunk.locator
               ) AS contains_visual
        FROM chat_attachments attachment
        JOIN chat_attachment_chunks chunk
          ON chunk.attachment_id = attachment.id
         AND chunk.processing_version = attachment.processing_version
        LEFT JOIN LATERAL (
          SELECT derivative.metadata
          FROM chat_attachment_derivatives derivative
          WHERE derivative.attachment_id = attachment.id
            AND derivative.processing_version = attachment.processing_version
            AND derivative.kind = 'manifest'
          ORDER BY derivative.created_at DESC
          LIMIT 1
        ) manifest ON TRUE
        WHERE attachment.id = ANY(%s)
          AND attachment.status = 'ready'
          AND attachment.lifecycle = 'attached'
        ORDER BY array_position(%s::uuid[], attachment.id), chunk.ordinal
        """,
        tuple(params + [normalized_ids, normalized_ids]),
    ).fetchall()
    grouped: dict[UUID, dict[str, object]] = {}
    for row in rows:
        attachment_id = UUID(str(row[0]))
        metadata = row[9] if isinstance(row[9], dict) else {}
        group = grouped.setdefault(
            attachment_id,
            {
                "filename": str(row[1] or "附件"),
                "kind": str(row[2] or "file").lower(),
                "page_count": _manifest_count(metadata, "page_count"),
                "slide_count": _manifest_count(metadata, "slide_count"),
                "chunks": [],
            },
        )
        text = str(row[4] or "")
        group["chunks"].append(
            AttachmentChunk(
                attachment_id=attachment_id,
                ordinal=int(row[3] or 0),
                text=text,
                token_count=int(row[5] or 0),
                locator=row[6] if isinstance(row[6], dict) else {},
                content_hash=str(row[7] or ""),
                vector_score=float(row[8] or 0.0),
                low_text_density=bool(row[10]),
                contains_visual=bool(row[11]),
                text_insufficient=len(text.strip()) < 24,
            )
        )
    return [
        AttachmentEvidence(
            attachment_id=attachment_id,
            filename=str(value["filename"]),
            kind=str(value["kind"]),
            chunks=tuple(value["chunks"]),
            page_count=value["page_count"],
            slide_count=value["slide_count"],
        )
        for attachment_id in normalized_ids
        if (value := grouped.get(attachment_id)) is not None
    ]


def load_recent_attachment_ids(
    conn: object,
    conversation_id: UUID,
    *,
    exclude_turn_id: Optional[UUID] = None,
    round_limit: int = 15,
) -> list[UUID]:
    """Return attachment ids from the recent bounded conversation window."""

    normalized_conversation = UUID(str(conversation_id))
    normalized_excluded = UUID(str(exclude_turn_id)) if exclude_turn_id else None
    row_limit = max(2, min(int(round_limit), 50) * 2)
    rows = conn.execute(
        """
        WITH recent_turns AS (
          SELECT id, created_at
          FROM assistant_turns
          WHERE conversation_id = %s
            AND (%s::uuid IS NULL OR id <> %s::uuid)
          ORDER BY created_at DESC
          LIMIT %s
        )
        SELECT relation.attachment_id
        FROM recent_turns turn_row
        JOIN assistant_turn_attachments relation ON relation.turn_id = turn_row.id
        JOIN chat_attachments attachment ON attachment.id = relation.attachment_id
        WHERE attachment.status = 'ready' AND attachment.lifecycle = 'attached'
        ORDER BY turn_row.created_at DESC, relation.ordinal ASC
        """,
        (normalized_conversation, normalized_excluded, normalized_excluded, row_limit),
    ).fetchall()
    return list(dict.fromkeys(UUID(str(row[0])) for row in rows))


def persist_full_inspection_task(conn: object, task_contract: dict[str, object]) -> dict[str, object]:
    if str(task_contract.get("task_type") or "") != "attachment_full_inspection":
        raise ValueError("invalid_full_inspection_task_type")
    user_turn_id = str(task_contract.get("user_turn_id") or "")
    locators = [
        item
        for batch in (task_contract.get("batches") or [])
        if isinstance(batch, list)
        for item in batch
        if isinstance(item, dict)
    ]
    locator_fingerprint = hashlib.sha256(
        json.dumps(locators, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:24]
    idempotency_key = f"attachment_full_inspection:{user_turn_id}:{locator_fingerprint}"
    task_run_id = f"task_{uuid4().hex}"
    inserted_cursor = conn.execute(
        """
        INSERT INTO task_runs (
          task_run_id, task_type, source_event_ids, pipeline_id, route_type, status,
          idempotency_key, risk_permission, requires_user_confirmation,
          final_user_visible_summary, payload
        )
        VALUES (%s, 'attachment_full_inspection', ARRAY[]::TEXT[],
                'attachment_full_inspection_pipeline', 'attachment_worker', 'queued',
                %s, 'local_read_only', FALSE, %s, %s)
        ON CONFLICT (idempotency_key) DO NOTHING
        """,
        (
            task_run_id,
            idempotency_key,
            "正在逐页检查附件；完成后会汇总覆盖范围和失败位置。",
            json.dumps(task_contract, ensure_ascii=False, default=str),
        ),
    )
    row = conn.execute(
        """
        SELECT task_run_id, task_type, status, payload
        FROM task_runs
        WHERE idempotency_key = %s
        LIMIT 1
        """,
        (idempotency_key,),
    ).fetchone()
    if row is None:
        raise RuntimeError("attachment_full_inspection_task_not_persisted")
    stored_task_id = str(row[0])
    if int(getattr(inserted_cursor, "rowcount", 0) or 0) != 0:
        for step_order, batch in enumerate(task_contract.get("batches") or []):
            conn.execute(
                """
                INSERT INTO task_steps (
                  task_step_id, task_run_id, step_name, step_order, status, input_json
                )
                VALUES (%s, %s, %s, %s, 'queued', %s::jsonb)
                """,
                (
                    f"step_{uuid4().hex}",
                    stored_task_id,
                    "inspect_locator_batch",
                    step_order,
                    json.dumps({"locators": batch}, ensure_ascii=False),
                ),
            )
        for locator in locators:
            evidence_id = "att-locator-" + hashlib.sha256(
                json.dumps(locator, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:24]
            conn.execute(
                """
                INSERT INTO task_evidence_links (
                  evidence_link_id, task_run_id, evidence_id, evidence_type, source,
                  contact_or_actor, used_for, confidence
                )
                VALUES (%s, %s, %s, 'attachment_locator', 'attachment', '', 'full_inspection', 1.0)
                """,
                (f"evidence_link_{uuid4().hex}", stored_task_id, evidence_id),
            )
    stored_payload = row[3] if isinstance(row[3], dict) else dict(task_contract)
    return {
        "task_run_id": stored_task_id,
        "task_type": str(row[1] or ""),
        "status": str(row[2] or ""),
        "payload": stored_payload,
    }


__all__ = [
    "AttachmentChunk",
    "AttachmentEvidence",
    "EvidenceCoverage",
    "EvidenceExclusion",
    "EvidenceMode",
    "EvidencePlan",
    "InspectionLocator",
    "SelectedTextEvidence",
    "SelectedVisualEvidence",
    "build_full_inspection_task",
    "load_attachment_evidence",
    "load_recent_attachment_ids",
    "plan_attachment_evidence",
    "process_full_inspection_batch",
    "persist_full_inspection_task",
    "should_retrieve_attachment_evidence",
    "stable_evidence_id",
    "terminal_full_inspection_summary",
]
