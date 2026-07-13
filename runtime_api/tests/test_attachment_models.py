from __future__ import annotations

import uuid
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from app.attachments.models import (
    DEFAULT_ATTACHMENT_ONLY_INSTRUCTION,
    AttachmentErrorCode,
    AttachmentLifecycle,
    AttachmentLimits,
    AttachmentStatus,
    ImageUrlPart,
    TextPart,
    validate_chat_input,
)


def test_attachment_limits_match_approved_spec():
    limits = AttachmentLimits()

    assert limits.max_file_bytes == 25 * 1024 * 1024
    assert limits.max_attachments_per_message == 8
    assert limits.max_message_attachment_bytes == 64 * 1024 * 1024
    assert limits.max_pdf_pages == 200
    assert limits.max_pptx_slides == 150
    assert limits.max_xlsx_nonempty_cells == 100_000
    assert limits.max_visual_items_per_request == 6


def test_message_or_attachment_is_required_but_either_may_be_empty():
    attachment_id = uuid.UUID("a64ccead-38f5-4cb0-bbe7-e3f9177cd6d2")

    assert validate_chat_input("", [attachment_id]) == ""
    assert validate_chat_input("请总结", []) == "请总结"

    with pytest.raises(ValueError, match="message_or_attachment_required"):
        validate_chat_input("  ", [])


def test_chat_input_rejects_duplicate_and_excess_attachment_ids():
    attachment_id = uuid.UUID("a64ccead-38f5-4cb0-bbe7-e3f9177cd6d2")

    with pytest.raises(ValueError, match="duplicate_attachment_id"):
        validate_chat_input("分析", [attachment_id, attachment_id])

    too_many = [uuid.UUID(int=value + 1) for value in range(9)]
    with pytest.raises(ValueError, match="too_many_attachments"):
        validate_chat_input("分析", too_many)


def test_status_lifecycle_and_error_codes_are_stable():
    assert {item.value for item in AttachmentStatus} == {
        "receiving",
        "stored",
        "processing",
        "ready",
        "rejected",
        "failed",
    }
    assert {item.value for item in AttachmentLifecycle} == {"draft", "attached", "deleted"}
    assert {item.value for item in AttachmentErrorCode} == {
        "unsupported_type",
        "too_large",
        "complexity_limit",
        "encrypted",
        "corrupt",
        "storage_failed",
        "parse_failed",
        "parse_timeout",
        "vision_unavailable",
        "attachment_not_ready",
        "attachment_expired",
        "attachment_already_attached",
    }


def test_default_attachment_only_instruction_is_explicit_and_localized():
    assert "识别并概括" in DEFAULT_ATTACHMENT_ONLY_INSTRUCTION
    assert "文件和位置" in DEFAULT_ATTACHMENT_ONLY_INSTRUCTION


def test_structured_content_parts_do_not_stringify_images():
    text = TextPart(text="请分析图片")
    image = ImageUrlPart(url="data:image/png;base64,AA==")

    assert text.model_dump() == {"type": "text", "text": "请分析图片"}
    assert image.model_dump() == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,AA=="},
    }
