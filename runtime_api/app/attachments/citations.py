from __future__ import annotations

import re
from typing import Iterable, TYPE_CHECKING


if TYPE_CHECKING:
    from app.attachments.retrieval import EvidencePlan


class CitationValidationError(ValueError):
    pass


def citation_label(filename: str, kind: str, locator: dict[str, object]) -> str:
    safe_filename = str(filename or "附件")
    normalized_kind = str(kind or "").lower()
    if normalized_kind == "pdf" and locator.get("page") is not None:
        return f"[{safe_filename}，第 {int(locator['page'])} 页]"
    if normalized_kind == "pptx" and locator.get("slide") is not None:
        return f"[{safe_filename}，第 {int(locator['slide'])} 张]"
    if normalized_kind == "docx" and locator.get("heading"):
        return f"[{safe_filename}，“{locator['heading']}”章节]"
    if normalized_kind in {"xlsx", "spreadsheet"} and locator.get("sheet"):
        cell_range = str(locator.get("range") or "").strip()
        suffix = f"!{cell_range}" if cell_range else ""
        return f"[{safe_filename}，{locator['sheet']}{suffix}]"
    if normalized_kind == "image":
        return f"[{safe_filename}]"
    if locator.get("line_start") is not None:
        line_start = int(locator["line_start"])
        line_end = int(locator.get("line_end") or line_start)
        line_text = f"第 {line_start} 行" if line_start == line_end else f"第 {line_start}-{line_end} 行"
        return f"[{safe_filename}，{line_text}]"
    return f"[{safe_filename}]"


def validate_cited_evidence_ids(
    cited_evidence_ids: Iterable[str],
    selected_evidence_ids: Iterable[str],
) -> None:
    cited = {str(value) for value in cited_evidence_ids}
    selected = {str(value) for value in selected_evidence_ids}
    unknown = sorted(cited - selected)
    if unknown:
        raise CitationValidationError(f"unselected_evidence_id: {', '.join(unknown)}")


ATTACHMENT_CITATION_RE = re.compile(
    r"\[[^\[\]\n]{0,180}\.(?:pdf|pptx|docx|xlsx|xls|csv|txt|md|png|jpe?g|webp)[^\[\]\n]{0,180}\]",
    re.IGNORECASE,
)


def validate_attachment_answer_citations(
    answer: str,
    selected_context: Iterable[dict[str, object]],
) -> dict[str, object]:
    selected_labels = sorted(
        {
            str(item.get("citation_label") or "").strip()
            for item in selected_context
            if isinstance(item, dict) and str(item.get("citation_label") or "").strip()
        }
    )
    attachment_labels = sorted(set(ATTACHMENT_CITATION_RE.findall(str(answer or ""))))
    cited_labels = sorted(label for label in attachment_labels if label in selected_labels)
    unknown_labels = sorted(label for label in attachment_labels if label not in selected_labels)
    return {
        "valid": not unknown_labels,
        "selected_labels": selected_labels,
        "cited_labels": cited_labels,
        "unknown_labels": unknown_labels,
    }


def coverage_statement(plan: "EvidencePlan") -> str:
    if plan.coverage.complete:
        return "已检查本次选定附件的全部可用内容。"
    selected_labels = [citation_label(item.filename, item.kind, item.locator) for item in plan.text_items]
    selected_text = "、".join(dict.fromkeys(selected_labels)) or "尚无可用位置"
    excluded_count = max(0, int(plan.coverage.total_count) - int(plan.coverage.selected_count))
    return f"仅检查：{selected_text}；未覆盖 {excluded_count} 个位置，结论仅基于上述证据。"


__all__ = [
    "CitationValidationError",
    "citation_label",
    "coverage_statement",
    "validate_attachment_answer_citations",
    "validate_cited_evidence_ids",
]
