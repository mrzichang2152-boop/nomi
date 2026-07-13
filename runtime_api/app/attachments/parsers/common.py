from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence


def content_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ParsedChunk:
    text: str
    locator: dict[str, Any]
    token_count: int = 0
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            object.__setattr__(self, "content_hash", content_hash(self.text.encode("utf-8")))
        if self.token_count <= 0 and self.text:
            object.__setattr__(self, "token_count", max(1, (len(self.text) + 3) // 4))


@dataclass(frozen=True)
class ParsedDerivative:
    kind: str
    mime_type: str
    extension: str
    locator: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    payload: bytes = field(default=b"", repr=False, compare=False)
    storage_relative_path: Optional[str] = None
    byte_size: int = 0
    content_hash: str = ""

    def __post_init__(self) -> None:
        if self.payload and self.byte_size <= 0:
            object.__setattr__(self, "byte_size", len(self.payload))
        if self.payload and not self.content_hash:
            object.__setattr__(self, "content_hash", content_hash(self.payload))


@dataclass(frozen=True)
class ParseResult:
    manifest: dict[str, Any] = field(default_factory=dict)
    derivatives: tuple[ParsedDerivative, ...] = field(default_factory=tuple)
    chunks: tuple[ParsedChunk, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    metrics: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    requires_default_visual_sweep: bool = False
    chunk_count: Optional[int] = None
    derivative_count: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "derivatives", tuple(self.derivatives))
        object.__setattr__(self, "chunks", tuple(self.chunks))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        if self.chunk_count is None:
            object.__setattr__(self, "chunk_count", len(self.chunks))
        if self.derivative_count is None:
            object.__setattr__(self, "derivative_count", len(self.derivatives))
        if not self.summary and self.chunks:
            object.__setattr__(self, "summary", self.chunks[0].text[:500])


def visual_cache_key(
    *,
    sha256: str,
    selected_locators: Sequence[dict[str, Any]],
    user_question: str,
    model_identity: str,
    processing_version: str,
) -> str:
    normalized_locators = sorted(
        (json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for item in selected_locators)
    )
    payload = json.dumps(
        {
            "sha256": sha256,
            "selected_locators": normalized_locators,
            "question_hash": content_hash(user_question.strip().encode("utf-8")),
            "model_identity": model_identity,
            "processing_version": processing_version,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return content_hash(payload.encode("utf-8"))


__all__ = [
    "ParseResult",
    "ParsedChunk",
    "ParsedDerivative",
    "content_hash",
    "visual_cache_key",
]
