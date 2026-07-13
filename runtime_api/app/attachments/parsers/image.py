from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

from app.attachments.models import AttachmentErrorCode, AttachmentRejected
from app.attachments.parsers.common import ParseResult, ParsedDerivative, content_hash


MAX_PREVIEW_EDGE = 2048
MAX_GIF_FRAMES = 4


def _png_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _normalized_frame(image: Image.Image) -> Image.Image:
    normalized = ImageOps.exif_transpose(image).convert("RGB")
    normalized.thumbnail((MAX_PREVIEW_EDGE, MAX_PREVIEW_EDGE), Image.Resampling.LANCZOS)
    return normalized


def parse_image(path: Path) -> ParseResult:
    try:
        with Image.open(path) as source:
            source.verify()
        with Image.open(path) as source:
            frame_count = int(getattr(source, "n_frames", 1))
            source_format = str(source.format or path.suffix.lstrip(".")).lower()
            original_width = source.width
            original_height = source.height
            source.seek(0)
            preview_image = _normalized_frame(source.copy())
            preview_payload = _png_bytes(preview_image)
            derivatives = [
                ParsedDerivative(
                    kind="preview",
                    mime_type="image/png",
                    extension=".png",
                    payload=preview_payload,
                    locator={"frame": 1},
                    metadata={"width": preview_image.width, "height": preview_image.height},
                )
            ]
            if frame_count > 1:
                seen: set[str] = set()
                for index, frame in enumerate(ImageSequence.Iterator(source), start=1):
                    normalized = _normalized_frame(frame.copy())
                    fingerprint_image = normalized.copy()
                    fingerprint_image.thumbnail((32, 32), Image.Resampling.BILINEAR)
                    fingerprint = content_hash(fingerprint_image.tobytes())
                    if fingerprint in seen:
                        continue
                    seen.add(fingerprint)
                    payload = _png_bytes(normalized)
                    derivatives.append(
                        ParsedDerivative(
                            kind="gif_frame",
                            mime_type="image/png",
                            extension=".png",
                            payload=payload,
                            locator={"frame": index},
                            metadata={"width": normalized.width, "height": normalized.height},
                        )
                    )
                    if len([item for item in derivatives if item.kind == "gif_frame"]) >= MAX_GIF_FRAMES:
                        break
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AttachmentRejected(AttachmentErrorCode.CORRUPT, internal_detail=type(exc).__name__) from exc

    return ParseResult(
        manifest={
            "parser_kind": "image",
            "format": source_format,
            "original_width": original_width,
            "original_height": original_height,
            "normalized_width": preview_image.width,
            "normalized_height": preview_image.height,
            "frame_count": frame_count,
        },
        derivatives=tuple(derivatives),
        metrics={"selected_frame_count": len(derivatives) - 1 if frame_count > 1 else 1},
        summary=f"图片 {preview_image.width}x{preview_image.height}",
    )


__all__ = ["parse_image"]
