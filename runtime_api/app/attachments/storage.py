from __future__ import annotations

import hashlib
import os
import re
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional, Union
from uuid import UUID

from app.attachments.models import AttachmentErrorCode, AttachmentRejected


DEFAULT_CHUNK_SIZE = 256 * 1024
MAX_DISPLAY_FILENAME_CHARS = 180
_SAFE_EXTENSION = re.compile(r"^\.[a-z0-9]{1,10}$")


@dataclass(frozen=True)
class StoredOriginal:
    relative_path: str
    sha256: str
    byte_size: int
    safe_display_filename: str


def _safe_extension(filename: str) -> str:
    extension = Path(filename).suffix.lower()
    return extension if _SAFE_EXTENSION.fullmatch(extension) else ""


def sanitize_display_filename(filename: str, *, max_chars: int = MAX_DISPLAY_FILENAME_CHARS) -> str:
    normalized = unicodedata.normalize("NFC", str(filename or ""))
    normalized = normalized.replace("\\", "/").split("/")[-1]
    normalized = "".join(
        character
        for character in normalized
        if unicodedata.category(character) not in {"Cc", "Cf", "Cs", "Co", "Cn"}
    )
    normalized = normalized.replace("/", "").replace("\\", "").strip(" .")
    extension = _safe_extension(normalized)
    stem = normalized[: -len(extension)] if extension else normalized
    stem = re.sub(r"\s+", " ", stem).strip(" .") or "attachment"
    allowed_stem_chars = max(1, max_chars - len(extension))
    stem = stem[:allowed_stem_chars].rstrip(" .") or "attachment"
    return f"{stem}{extension}"


def resolve_storage_path(root: Union[str, Path], relative_path: Union[str, Path]) -> Path:
    root_path = Path(root).expanduser().resolve()
    candidate_relative = Path(relative_path)
    if candidate_relative.is_absolute():
        raise AttachmentRejected(AttachmentErrorCode.STORAGE_FAILED)
    candidate = (root_path / candidate_relative).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise AttachmentRejected(
            AttachmentErrorCode.STORAGE_FAILED,
            internal_detail="attachment path escaped storage root",
        ) from exc
    return candidate


def write_streamed_original(
    source: BinaryIO,
    root: Union[str, Path],
    attachment_id: UUID,
    *,
    original_filename: str,
    max_bytes: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> StoredOriginal:
    if max_bytes < 0 or chunk_size <= 0:
        raise ValueError("invalid_stream_limits")

    root_path = Path(root).expanduser().resolve()
    temporary_dir = resolve_storage_path(root_path, "temporary")
    temporary_dir.mkdir(parents=True, exist_ok=True)
    safe_display_filename = sanitize_display_filename(original_filename)
    extension = _safe_extension(safe_display_filename)
    generated_name = f"{uuid.uuid4().hex}{extension}"
    relative_path = Path("originals") / attachment_id.hex[:2] / str(attachment_id) / generated_name
    target_path = resolve_storage_path(root_path, relative_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = resolve_storage_path(root_path, Path("temporary") / f"{uuid.uuid4().hex}.part")

    digest = hashlib.sha256()
    byte_size = 0
    moved = False
    try:
        with part_path.open("xb") as output:
            while True:
                chunk = source.read(chunk_size)
                if not chunk:
                    break
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise TypeError("attachment stream must return bytes")
                chunk_bytes = bytes(chunk)
                byte_size += len(chunk_bytes)
                if byte_size > max_bytes:
                    raise AttachmentRejected(AttachmentErrorCode.TOO_LARGE)
                output.write(chunk_bytes)
                digest.update(chunk_bytes)
            output.flush()
            os.fsync(output.fileno())
        os.replace(part_path, target_path)
        moved = True
        directory_fd: Optional[int] = None
        try:
            directory_fd = os.open(str(target_path.parent), os.O_RDONLY)
            os.fsync(directory_fd)
        finally:
            if directory_fd is not None:
                os.close(directory_fd)
    except Exception:
        if part_path.exists():
            part_path.unlink()
        if moved and target_path.exists():
            target_path.unlink()
        raise

    return StoredOriginal(
        relative_path=relative_path.as_posix(),
        sha256=digest.hexdigest(),
        byte_size=byte_size,
        safe_display_filename=safe_display_filename,
    )


__all__ = [
    "AttachmentRejected",
    "DEFAULT_CHUNK_SIZE",
    "StoredOriginal",
    "resolve_storage_path",
    "sanitize_display_filename",
    "write_streamed_original",
]
