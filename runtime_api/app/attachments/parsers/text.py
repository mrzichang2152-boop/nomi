from __future__ import annotations

import re
from pathlib import Path

from charset_normalizer import from_bytes

from app.attachments.models import AttachmentErrorCode, AttachmentRejected
from app.attachments.parsers.common import ParseResult, ParsedChunk


MAX_TEXT_CHUNK_CHARS = 32_000


def _decode(path: Path) -> tuple[str, str]:
    payload = path.read_bytes()
    try:
        return payload.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        try:
            return payload.decode("gb18030"), "gb18030"
        except UnicodeDecodeError:
            match = from_bytes(payload).best()
            if match is None:
                raise AttachmentRejected(AttachmentErrorCode.CORRUPT)
            return str(match), str(match.encoding or "unknown")


def _line_chunks(text: str, *, extra_locator: dict[str, object] | None = None) -> tuple[ParsedChunk, ...]:
    lines = text.splitlines()
    chunks: list[ParsedChunk] = []
    start = 0
    while start < max(1, len(lines)):
        end = start
        selected: list[str] = []
        current_size = 0
        while end < len(lines):
            candidate = lines[end]
            if selected and current_size + len(candidate) + 1 > MAX_TEXT_CHUNK_CHARS:
                break
            selected.append(candidate)
            current_size += len(candidate) + 1
            end += 1
        if not selected and not lines:
            break
        locator = {"line_start": start + 1, "line_end": max(start + 1, end)}
        locator.update(extra_locator or {})
        chunks.append(ParsedChunk(text="\n".join(selected), locator=locator))
        start = end
    return tuple(chunks)


def parse_text(path: Path) -> ParseResult:
    try:
        text, encoding = _decode(path)
    except AttachmentRejected:
        raise
    except (OSError, UnicodeError) as exc:
        raise AttachmentRejected(AttachmentErrorCode.CORRUPT, internal_detail=type(exc).__name__) from exc
    return ParseResult(
        manifest={"parser_kind": "txt", "encoding": encoding, "line_count": len(text.splitlines())},
        chunks=_line_chunks(text),
    )


def parse_markdown(path: Path) -> ParseResult:
    try:
        text, encoding = _decode(path)
    except AttachmentRejected:
        raise
    except (OSError, UnicodeError) as exc:
        raise AttachmentRejected(AttachmentErrorCode.CORRUPT, internal_detail=type(exc).__name__) from exc

    chunks: list[ParsedChunk] = []
    current_heading = ""
    code_fence = False
    code_start = 0
    code_lines: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        heading = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if not code_fence and heading:
            current_heading = heading.group(1)
            chunks.append(
                ParsedChunk(
                    text=line,
                    locator={"line_start": line_number, "line_end": line_number, "heading": current_heading, "code_block": False, "trusted_html": False},
                )
            )
            continue
        if line.lstrip().startswith("```"):
            if code_fence:
                chunks.append(
                    ParsedChunk(
                        text="\n".join(code_lines),
                        locator={"line_start": code_start, "line_end": line_number, "heading": current_heading, "code_block": True, "trusted_html": False},
                    )
                )
                code_lines = []
                code_fence = False
            else:
                code_fence = True
                code_start = line_number
            continue
        if code_fence:
            code_lines.append(line)
            continue
        if line.strip():
            chunks.append(
                ParsedChunk(
                    text=line,
                    locator={"line_start": line_number, "line_end": line_number, "heading": current_heading, "code_block": False, "trusted_html": False},
                )
            )
    if code_fence and code_lines:
        chunks.append(
            ParsedChunk(
                text="\n".join(code_lines),
                locator={"line_start": code_start, "line_end": len(text.splitlines()), "heading": current_heading, "code_block": True, "trusted_html": False},
            )
        )

    return ParseResult(
        manifest={"parser_kind": "md", "encoding": encoding, "line_count": len(text.splitlines()), "trusted_html": False},
        chunks=tuple(chunks),
    )


__all__ = ["parse_markdown", "parse_text"]
