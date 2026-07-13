from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))


from app.attachments.detection import AttachmentRejected, DetectionLimits, detect_attachment
from attachment_fixture_factory import (
    image_bytes,
    mark_zip_encrypted,
    office_bytes,
    pdf_bytes,
    write_fixture,
    zip_bytes,
)


@pytest.mark.parametrize(
    ("filename", "payload", "expected_mime", "expected_kind"),
    [
        ("photo.png", image_bytes("PNG"), "image/png", "image"),
        ("photo.jpg", image_bytes("JPEG"), "image/jpeg", "image"),
        ("photo.webp", image_bytes("WEBP"), "image/webp", "image"),
        ("photo.gif", image_bytes("GIF"), "image/gif", "image"),
        ("brief.pdf", pdf_bytes(), "application/pdf", "pdf"),
        ("brief.docx", office_bytes("docx"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "document"),
        ("slides.pptx", office_bytes("pptx"), "application/vnd.openxmlformats-officedocument.presentationml.presentation", "presentation"),
        ("budget.xlsx", office_bytes("xlsx"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "spreadsheet"),
        ("contacts.csv", "姓名,电话\n王超,13800000000\n".encode(), "text/csv", "text"),
        ("notes.txt", "普通 UTF-8 文本".encode(), "text/plain", "text"),
        ("readme.md", b"# Nomi\n\nAttachment notes.", "text/markdown", "text"),
    ],
)
def test_supported_types_are_detected_from_content_and_container_markers(
    tmp_path,
    filename,
    payload,
    expected_mime,
    expected_kind,
):
    detected = detect_attachment(write_fixture(tmp_path, filename, payload), filename)

    assert detected.mime_type == expected_mime
    assert detected.kind == expected_kind
    assert detected.extension == Path(filename).suffix.lower()


@pytest.mark.parametrize("filename", ["legacy.doc", "legacy.ppt", "legacy.xls"])
def test_legacy_office_formats_are_rejected_with_stable_safe_error(tmp_path, filename):
    path = write_fixture(tmp_path, filename, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy")

    with pytest.raises(AttachmentRejected) as error:
        detect_attachment(path, filename)

    assert error.value.code == "unsupported_type"
    assert error.value.safe_message == "暂不支持这种文件格式。"


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        ("invoice.png", b"MZ" + b"\x00" * 128),
        ("report.pdf", b"\x7fELF" + b"\x00" * 128),
        ("script.js", b"alert('x')"),
        ("page.html", b"<html><script>x()</script></html>"),
        ("run.sh", b"#!/bin/sh\nrm -rf /"),
    ],
)
def test_renamed_executables_and_active_scripts_are_rejected(tmp_path, filename, payload):
    with pytest.raises(AttachmentRejected) as error:
        detect_attachment(write_fixture(tmp_path, filename, payload), filename)

    assert error.value.code == "unsupported_type"
    assert str(tmp_path) not in error.value.safe_message


def test_zip_path_traversal_is_rejected_before_office_dispatch(tmp_path):
    payload = office_bytes("docx", extra_entries=[("../../escape.txt", b"private")])

    with pytest.raises(AttachmentRejected) as error:
        detect_attachment(write_fixture(tmp_path, "unsafe.docx", payload), "unsafe.docx")

    assert error.value.code == "complexity_limit"
    assert error.value.safe_message == "文件结构过于复杂，无法安全处理。"


def test_zip_bomb_ratio_is_rejected_before_decompression(tmp_path):
    payload = office_bytes("docx", extra_entries=[("word/media/zeros.bin", b"0" * 2_000_000)])

    with pytest.raises(AttachmentRejected) as error:
        detect_attachment(write_fixture(tmp_path, "bomb.docx", payload), "bomb.docx")

    assert error.value.code == "complexity_limit"


def test_zip_entry_count_and_total_uncompressed_limits_are_enforced(tmp_path):
    payload = zip_bytes((f"word/items/{index}.xml", b"x") for index in range(8))
    limits = DetectionLimits(max_zip_entries=5)

    with pytest.raises(AttachmentRejected) as error:
        detect_attachment(write_fixture(tmp_path, "many.docx", payload), "many.docx", limits=limits)

    assert error.value.code == "complexity_limit"


def test_encrypted_office_and_pdf_are_rejected_as_encrypted(tmp_path):
    encrypted_docx = mark_zip_encrypted(office_bytes("docx"))
    encrypted_pdf = pdf_bytes(encrypted=True)

    for filename, payload in [("secret.docx", encrypted_docx), ("secret.pdf", encrypted_pdf)]:
        with pytest.raises(AttachmentRejected) as error:
            detect_attachment(write_fixture(tmp_path, filename, payload), filename)
        assert error.value.code == "encrypted"
        assert error.value.safe_message == "文件已加密，暂时无法读取。"


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        ("broken.docx", b"PK\x03\x04not-a-zip"),
        ("broken.pdf", b"%PDF-1.7\ninvalid"),
        ("broken.png", b"\x89PNG\r\n\x1a\ninvalid"),
    ],
)
def test_corrupt_containers_have_stable_non_leaking_error(tmp_path, filename, payload):
    with pytest.raises(AttachmentRejected) as error:
        detect_attachment(write_fixture(tmp_path, filename, payload), filename)

    assert error.value.code == "corrupt"
    assert error.value.safe_message == "文件已损坏或内容不完整。"
    assert filename not in error.value.safe_message


def test_oversized_image_dimensions_are_rejected_without_pixel_decode(tmp_path):
    payload = image_bytes("PNG", size=(10_000, 10_000))

    with pytest.raises(AttachmentRejected) as error:
        detect_attachment(
            write_fixture(tmp_path, "huge.png", payload),
            "huge.png",
            limits=DetectionLimits(max_image_pixels=20_000_000),
        )

    assert error.value.code == "complexity_limit"


def test_plain_zip_without_supported_office_markers_is_not_accepted(tmp_path):
    payload = zip_bytes([("notes.txt", b"hello")], compression=zipfile.ZIP_STORED)

    with pytest.raises(AttachmentRejected) as error:
        detect_attachment(write_fixture(tmp_path, "archive.zip", payload), "archive.zip")

    assert error.value.code == "unsupported_type"
