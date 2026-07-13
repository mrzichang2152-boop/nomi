from __future__ import annotations

import warnings
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional, Union

from charset_normalizer import from_bytes
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

from app.attachments.models import AttachmentErrorCode, AttachmentRejected


OFFICE_MIME_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
OFFICE_MARKERS = {
    "word/document.xml": ("docx", "document"),
    "ppt/presentation.xml": ("pptx", "presentation"),
    "xl/workbook.xml": ("xlsx", "spreadsheet"),
}
IMAGE_FORMATS = {
    "PNG": ("image/png", ".png"),
    "JPEG": ("image/jpeg", ".jpg"),
    "WEBP": ("image/webp", ".webp"),
    "GIF": ("image/gif", ".gif"),
}
TEXT_MIME_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
}
REJECTED_EXTENSIONS = {
    ".doc",
    ".ppt",
    ".xls",
    ".zip",
    ".rar",
    ".7z",
    ".exe",
    ".dll",
    ".elf",
    ".js",
    ".html",
    ".htm",
    ".py",
    ".sh",
    ".bat",
    ".cmd",
    ".ps1",
}


@dataclass(frozen=True)
class DetectionLimits:
    max_zip_entries: int = 10_000
    max_zip_entry_uncompressed_bytes: int = 64 * 1024 * 1024
    max_zip_total_uncompressed_bytes: int = 256 * 1024 * 1024
    max_zip_compression_ratio: float = 200.0
    max_image_pixels: int = 50_000_000
    max_image_dimension: int = 20_000
    max_text_probe_bytes: int = 2 * 1024 * 1024


@dataclass(frozen=True)
class DetectedAttachment:
    mime_type: str
    kind: str
    extension: str
    parser_kind: str
    width: Optional[int] = None
    height: Optional[int] = None


def _reject(code: AttachmentErrorCode, detail: str) -> AttachmentRejected:
    return AttachmentRejected(code, internal_detail=detail)


def _has_executable_magic(header: bytes) -> bool:
    return header.startswith(b"MZ") or header.startswith(b"\x7fELF") or header.startswith(b"#!")


def _safe_zip_name(name: str) -> bool:
    if "\\" in name:
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def _validate_zip(archive: zipfile.ZipFile, limits: DetectionLimits) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > limits.max_zip_entries:
        raise _reject(AttachmentErrorCode.COMPLEXITY_LIMIT, "zip entry count exceeded")
    total_uncompressed = 0
    for info in infos:
        if not _safe_zip_name(info.filename):
            raise _reject(AttachmentErrorCode.COMPLEXITY_LIMIT, "zip traversal entry")
        if info.flag_bits & 0x1:
            raise _reject(AttachmentErrorCode.ENCRYPTED, "encrypted zip entry")
        if info.file_size > limits.max_zip_entry_uncompressed_bytes:
            raise _reject(AttachmentErrorCode.COMPLEXITY_LIMIT, "zip entry size exceeded")
        total_uncompressed += info.file_size
        if total_uncompressed > limits.max_zip_total_uncompressed_bytes:
            raise _reject(AttachmentErrorCode.COMPLEXITY_LIMIT, "zip total size exceeded")
        if info.file_size:
            if info.compress_size <= 0:
                raise _reject(AttachmentErrorCode.COMPLEXITY_LIMIT, "invalid zip compression size")
            ratio = info.file_size / info.compress_size
            if ratio > limits.max_zip_compression_ratio:
                raise _reject(AttachmentErrorCode.COMPLEXITY_LIMIT, "zip compression ratio exceeded")
    return infos


def _detect_office(path: Path, extension: str, limits: DetectionLimits) -> DetectedAttachment:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = _validate_zip(archive, limits)
            names = {info.filename for info in infos}
    except AttachmentRejected:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise _reject(AttachmentErrorCode.CORRUPT, f"invalid office zip: {type(exc).__name__}") from exc

    detected = next((value for marker, value in OFFICE_MARKERS.items() if marker in names), None)
    if detected is None:
        raise _reject(AttachmentErrorCode.UNSUPPORTED_TYPE, "zip is not supported office container")
    detected_extension, kind = detected
    if extension and extension != f".{detected_extension}":
        raise _reject(AttachmentErrorCode.CORRUPT, "office extension does not match container")
    return DetectedAttachment(
        mime_type=OFFICE_MIME_TYPES[detected_extension],
        kind=kind,
        extension=f".{detected_extension}",
        parser_kind=detected_extension,
    )


def _detect_image(path: Path, extension: str, limits: DetectionLimits) -> DetectedAttachment:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                image_format = str(image.format or "").upper()
                width, height = image.size
                if (
                    width <= 0
                    or height <= 0
                    or width > limits.max_image_dimension
                    or height > limits.max_image_dimension
                    or width * height > limits.max_image_pixels
                ):
                    raise _reject(AttachmentErrorCode.COMPLEXITY_LIMIT, "image dimensions exceeded")
                image.verify()
    except AttachmentRejected:
        raise
    except (OSError, UnidentifiedImageError, ValueError, SyntaxError) as exc:
        raise _reject(AttachmentErrorCode.CORRUPT, f"invalid image: {type(exc).__name__}") from exc
    if image_format not in IMAGE_FORMATS:
        raise _reject(AttachmentErrorCode.UNSUPPORTED_TYPE, f"unsupported image format {image_format}")
    mime_type, canonical_extension = IMAGE_FORMATS[image_format]
    allowed_extensions = {canonical_extension}
    if canonical_extension == ".jpg":
        allowed_extensions.add(".jpeg")
    if extension and extension not in allowed_extensions:
        raise _reject(AttachmentErrorCode.CORRUPT, "image extension does not match content")
    return DetectedAttachment(
        mime_type=mime_type,
        kind="image",
        extension=extension or canonical_extension,
        parser_kind="image",
        width=width,
        height=height,
    )


def _detect_pdf(path: Path, extension: str) -> DetectedAttachment:
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            raise _reject(AttachmentErrorCode.ENCRYPTED, "encrypted pdf")
        len(reader.pages)
    except AttachmentRejected:
        raise
    except Exception as exc:
        raise _reject(AttachmentErrorCode.CORRUPT, f"invalid pdf: {type(exc).__name__}") from exc
    if extension and extension != ".pdf":
        raise _reject(AttachmentErrorCode.CORRUPT, "pdf extension does not match content")
    return DetectedAttachment(
        mime_type="application/pdf",
        kind="pdf",
        extension=".pdf",
        parser_kind="pdf",
    )


def _detect_text(path: Path, extension: str, limits: DetectionLimits) -> DetectedAttachment:
    payload = path.read_bytes()[: limits.max_text_probe_bytes]
    if b"\x00" in payload:
        raise _reject(AttachmentErrorCode.CORRUPT, "text contains null bytes")
    best = from_bytes(payload).best()
    if best is None:
        raise _reject(AttachmentErrorCode.CORRUPT, "text encoding not recognized")
    text = str(best)
    if not text and payload:
        raise _reject(AttachmentErrorCode.CORRUPT, "text decoding returned empty content")
    return DetectedAttachment(
        mime_type=TEXT_MIME_TYPES[extension],
        kind="text",
        extension=extension,
        parser_kind=extension[1:],
    )


def detect_attachment(
    path: Union[str, Path],
    original_filename: str,
    *,
    declared_mime_type: Optional[str] = None,
    limits: Optional[DetectionLimits] = None,
) -> DetectedAttachment:
    del declared_mime_type
    active_limits = limits or DetectionLimits()
    file_path = Path(path)
    extension = Path(original_filename).suffix.lower()
    try:
        with file_path.open("rb") as source:
            header = source.read(16)
    except OSError as exc:
        raise _reject(AttachmentErrorCode.CORRUPT, f"cannot read attachment: {type(exc).__name__}") from exc

    if extension in REJECTED_EXTENSIONS or _has_executable_magic(header):
        raise _reject(AttachmentErrorCode.UNSUPPORTED_TYPE, "rejected extension or executable magic")
    if header.startswith(b"%PDF-") or extension == ".pdf":
        if not header.startswith(b"%PDF-"):
            raise _reject(AttachmentErrorCode.CORRUPT, "pdf signature missing")
        return _detect_pdf(file_path, extension)
    if header.startswith(b"PK\x03\x04") or extension in {".docx", ".pptx", ".xlsx"}:
        return _detect_office(file_path, extension, active_limits)
    if extension in {".png", ".jpg", ".jpeg", ".webp", ".gif"} or header.startswith(
        (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"RIFF")
    ):
        return _detect_image(file_path, extension, active_limits)
    if extension in TEXT_MIME_TYPES:
        return _detect_text(file_path, extension, active_limits)
    raise _reject(AttachmentErrorCode.UNSUPPORTED_TYPE, "unsupported attachment type")


__all__ = [
    "AttachmentRejected",
    "DetectedAttachment",
    "DetectionLimits",
    "detect_attachment",
]
