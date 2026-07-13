from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from app.attachments.models import AttachmentErrorCode, AttachmentRejected
from app.attachments.parsers.common import ParseResult
from app.attachments.parsers.docx import parse_docx
from app.attachments.parsers.image import parse_image
from app.attachments.parsers.pdf import parse_pdf
from app.attachments.parsers.pptx import parse_pptx
from app.attachments.parsers.spreadsheet import parse_csv, parse_xlsx
from app.attachments.parsers.text import parse_markdown, parse_text

if TYPE_CHECKING:
    from app.attachments.repository import AttachmentRecord


ParserFunction = Callable[[Path], ParseResult]


class DefaultAttachmentParser:
    def __init__(self) -> None:
        self.parsers: dict[str, ParserFunction] = {
            "image": parse_image,
            "pdf": parse_pdf,
            "docx": parse_docx,
            "pptx": parse_pptx,
            "xlsx": parse_xlsx,
            "csv": parse_csv,
            "txt": parse_text,
            "md": parse_markdown,
        }

    def parse(self, record: "AttachmentRecord", source_path: Path) -> ParseResult:
        kind = str(record.parser_kind or "").lower()
        parser = self.parsers.get(kind)
        if parser is None:
            raise AttachmentRejected(AttachmentErrorCode.UNSUPPORTED_TYPE)
        result = parser(source_path)
        manifest = {**result.manifest, "parser_kind": kind}
        return replace(result, manifest=manifest)


def build_default_attachment_parser() -> DefaultAttachmentParser:
    return DefaultAttachmentParser()


__all__ = [
    "DefaultAttachmentParser",
    "ParseResult",
    "build_default_attachment_parser",
]
