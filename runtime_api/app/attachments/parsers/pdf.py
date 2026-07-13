from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
from pypdf import PdfReader

from app.attachments.models import AttachmentErrorCode, AttachmentRejected
from app.attachments.parsers.common import ParseResult, ParsedChunk, ParsedDerivative


MAX_PDF_PAGES = 200
SCAN_TEXT_THRESHOLD = 20


def parse_pdf(path: Path) -> ParseResult:
    try:
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise AttachmentRejected(AttachmentErrorCode.ENCRYPTED)
        page_count = len(reader.pages)
        if page_count > MAX_PDF_PAGES:
            raise AttachmentRejected(AttachmentErrorCode.COMPLEXITY_LIMIT)
        chunks: list[ParsedChunk] = []
        page_metrics: list[dict[str, object]] = []
        suspected_scan_pages: list[int] = []
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            width = float(page.mediabox.width or 1)
            height = float(page.mediabox.height or 1)
            density = len(text) / max(1.0, width * height / 1000.0)
            suspected_scan = len(text) < SCAN_TEXT_THRESHOLD
            if suspected_scan:
                suspected_scan_pages.append(number)
            page_metrics.append(
                {
                    "page": number,
                    "text_char_count": len(text),
                    "text_density": round(density, 6),
                    "suspected_scan": suspected_scan,
                }
            )
            if text:
                chunks.append(ParsedChunk(text=text[:64_000], locator={"page": number}))
    except AttachmentRejected:
        raise
    except Exception as exc:
        raise AttachmentRejected(AttachmentErrorCode.CORRUPT, internal_detail=type(exc).__name__) from exc

    return ParseResult(
        manifest={
            "parser_kind": "pdf",
            "page_count": page_count,
            "suspected_scan_pages": suspected_scan_pages,
        },
        chunks=tuple(chunks),
        metrics={"pages": page_metrics},
        requires_default_visual_sweep=False,
        warnings=("包含疑似扫描页，需要视觉检查。",) if suspected_scan_pages else (),
    )


def render_pdf_page(path: Path, *, page_number: int, max_edge: int = 2048) -> ParsedDerivative:
    if page_number < 1 or max_edge < 1:
        raise ValueError("invalid_pdf_render_request")
    document = None
    page = None
    bitmap = None
    try:
        document = pdfium.PdfDocument(str(path))
        if page_number > len(document):
            raise ValueError("pdf_page_out_of_range")
        page = document[page_number - 1]
        width, height = page.get_size()
        scale = min(2.0, max_edge / max(width, height))
        bitmap = page.render(scale=max(0.1, scale))
        image = bitmap.to_pil().convert("RGB")
        image.thumbnail((max_edge, max_edge))
        from io import BytesIO

        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
        payload = output.getvalue()
        return ParsedDerivative(
            kind="pdf_page",
            mime_type="image/png",
            extension=".png",
            payload=payload,
            locator={"page": page_number},
            metadata={"width": image.width, "height": image.height},
        )
    except ValueError:
        raise
    except Exception as exc:
        raise AttachmentRejected(AttachmentErrorCode.CORRUPT, internal_detail=type(exc).__name__) from exc
    finally:
        if bitmap is not None:
            bitmap.close()
        if page is not None:
            page.close()
        if document is not None:
            document.close()


__all__ = ["parse_pdf", "render_pdf_page"]
