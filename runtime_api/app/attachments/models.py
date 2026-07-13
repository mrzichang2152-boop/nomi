from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal, Optional, Sequence, Union
from uuid import UUID

from pydantic import BaseModel, Field


class AttachmentStatus(str, Enum):
    RECEIVING = "receiving"
    STORED = "stored"
    PROCESSING = "processing"
    READY = "ready"
    REJECTED = "rejected"
    FAILED = "failed"


class AttachmentLifecycle(str, Enum):
    DRAFT = "draft"
    ATTACHED = "attached"
    DELETED = "deleted"


class AttachmentErrorCode(str, Enum):
    UNSUPPORTED_TYPE = "unsupported_type"
    TOO_LARGE = "too_large"
    COMPLEXITY_LIMIT = "complexity_limit"
    ENCRYPTED = "encrypted"
    CORRUPT = "corrupt"
    STORAGE_FAILED = "storage_failed"
    PARSE_FAILED = "parse_failed"
    PARSE_TIMEOUT = "parse_timeout"
    VISION_UNAVAILABLE = "vision_unavailable"
    ATTACHMENT_NOT_READY = "attachment_not_ready"
    ATTACHMENT_EXPIRED = "attachment_expired"
    ATTACHMENT_ALREADY_ATTACHED = "attachment_already_attached"


SAFE_ATTACHMENT_ERROR_MESSAGES: dict[AttachmentErrorCode, str] = {
    AttachmentErrorCode.UNSUPPORTED_TYPE: "暂不支持这种文件格式。",
    AttachmentErrorCode.TOO_LARGE: "文件大小超过允许上限。",
    AttachmentErrorCode.COMPLEXITY_LIMIT: "文件结构过于复杂，无法安全处理。",
    AttachmentErrorCode.ENCRYPTED: "文件已加密，暂时无法读取。",
    AttachmentErrorCode.CORRUPT: "文件已损坏或内容不完整。",
    AttachmentErrorCode.STORAGE_FAILED: "文件存储失败，请重试。",
    AttachmentErrorCode.PARSE_FAILED: "文件内容解析失败。",
    AttachmentErrorCode.PARSE_TIMEOUT: "文件处理超时，请重试。",
    AttachmentErrorCode.VISION_UNAVAILABLE: "图片理解服务暂时不可用。",
    AttachmentErrorCode.ATTACHMENT_NOT_READY: "文件仍在处理中，请稍后重试。",
    AttachmentErrorCode.ATTACHMENT_EXPIRED: "文件草稿已过期，请重新上传。",
    AttachmentErrorCode.ATTACHMENT_ALREADY_ATTACHED: "文件已经发送，不能重复使用。",
}


class AttachmentRejected(ValueError):
    def __init__(
        self,
        code: Union[AttachmentErrorCode, str],
        *,
        safe_message: Optional[str] = None,
        internal_detail: Optional[str] = None,
    ) -> None:
        normalized_code = AttachmentErrorCode(code)
        self.code = normalized_code.value
        self.safe_message = safe_message or SAFE_ATTACHMENT_ERROR_MESSAGES[normalized_code]
        self.internal_detail = internal_detail
        super().__init__(self.safe_message)


ALLOWED_TRANSITIONS: dict[AttachmentStatus, frozenset[AttachmentStatus]] = {
    AttachmentStatus.RECEIVING: frozenset(
        {AttachmentStatus.STORED, AttachmentStatus.REJECTED, AttachmentStatus.FAILED}
    ),
    AttachmentStatus.STORED: frozenset(
        {AttachmentStatus.PROCESSING, AttachmentStatus.REJECTED, AttachmentStatus.FAILED}
    ),
    AttachmentStatus.PROCESSING: frozenset(
        {AttachmentStatus.READY, AttachmentStatus.REJECTED, AttachmentStatus.FAILED}
    ),
    AttachmentStatus.READY: frozenset({AttachmentStatus.PROCESSING}),
    AttachmentStatus.REJECTED: frozenset(),
    AttachmentStatus.FAILED: frozenset({AttachmentStatus.PROCESSING}),
}


DEFAULT_ATTACHMENT_ONLY_INSTRUCTION = (
    "请识别并概括这些附件的内容，并标明关键信息来自哪个文件和位置。"
)


@dataclass(frozen=True)
class AttachmentLimits:
    max_file_bytes: int = 25 * 1024 * 1024
    max_attachments_per_message: int = 8
    max_message_attachment_bytes: int = 64 * 1024 * 1024
    max_pdf_pages: int = 200
    max_pptx_slides: int = 150
    max_xlsx_nonempty_cells: int = 100_000
    max_visual_items_per_request: int = 6


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImageUrlValue(BaseModel):
    url: str


class ImageUrlPart(BaseModel):
    type: Literal["image_url"] = "image_url"
    image_url: ImageUrlValue

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        image_url: Optional[Union[ImageUrlValue, dict[str, str]]] = None,
    ):
        value = image_url if image_url is not None else {"url": str(url or "")}
        super().__init__(image_url=value)


ChatContent = Union[str, list[Union[TextPart, ImageUrlPart]]]


class AttachmentPublic(BaseModel):
    attachment_id: UUID
    filename: str
    mime_type: str
    byte_size: int = Field(ge=0)
    status: AttachmentStatus
    kind: str
    preview_url: Optional[str] = None
    content_url: str
    error_code: Optional[AttachmentErrorCode] = None
    error_message: Optional[str] = None


class AttachmentTraceSummary(BaseModel):
    attachment_id: UUID
    detected_mime_type: str
    byte_size: int = Field(ge=0)
    processing_version: str
    status: AttachmentStatus
    selected_locators: list[dict[str, object]] = Field(default_factory=list)
    excluded_locators: list[dict[str, object]] = Field(default_factory=list)
    visual_item_count: int = Field(default=0, ge=0)


def validate_chat_input(
    message: str,
    attachment_ids: Sequence[UUID],
    limits: Optional[AttachmentLimits] = None,
) -> str:
    active_limits = limits or AttachmentLimits()
    if not message.strip() and not attachment_ids:
        raise ValueError("message_or_attachment_required")
    if len(attachment_ids) > active_limits.max_attachments_per_message:
        raise ValueError("too_many_attachments")
    normalized_ids = [str(attachment_id) for attachment_id in attachment_ids]
    if len(normalized_ids) != len(set(normalized_ids)):
        raise ValueError("duplicate_attachment_id")
    return message
