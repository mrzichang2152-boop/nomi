from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path
from typing import Iterable, Optional

from PIL import Image
from pypdf import PdfWriter


OFFICE_MARKERS = {
    "docx": ("word/document.xml", b"<w:document xmlns:w='urn:test'/>") ,
    "pptx": ("ppt/presentation.xml", b"<p:presentation xmlns:p='urn:test'/>") ,
    "xlsx": ("xl/workbook.xml", b"<workbook xmlns='urn:test'/>") ,
}


def image_bytes(image_format: str, size: tuple[int, int] = (16, 12)) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", size, color=(22, 140, 121))
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def pdf_bytes(*, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    if encrypted:
        writer.encrypt("nomi-test")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def zip_bytes(
    entries: Iterable[tuple[str, bytes]],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    return buffer.getvalue()


def office_bytes(kind: str, *, extra_entries: Optional[Iterable[tuple[str, bytes]]] = None) -> bytes:
    marker_name, marker_payload = OFFICE_MARKERS[kind]
    entries = [
        ("[Content_Types].xml", b"<Types xmlns='urn:test'/>") ,
        (marker_name, marker_payload),
    ]
    entries.extend(list(extra_entries or []))
    return zip_bytes(entries)


def mark_zip_encrypted(payload: bytes) -> bytes:
    data = bytearray(payload)
    offset = 0
    while True:
        offset = data.find(b"PK\x03\x04", offset)
        if offset < 0:
            break
        flags = struct.unpack_from("<H", data, offset + 6)[0] | 0x1
        struct.pack_into("<H", data, offset + 6, flags)
        offset += 4
    offset = 0
    while True:
        offset = data.find(b"PK\x01\x02", offset)
        if offset < 0:
            break
        flags = struct.unpack_from("<H", data, offset + 8)[0] | 0x1
        struct.pack_into("<H", data, offset + 8, flags)
        offset += 4
    return bytes(data)


def write_fixture(tmp_path: Path, filename: str, payload: bytes) -> Path:
    path = tmp_path / filename
    path.write_bytes(payload)
    return path
