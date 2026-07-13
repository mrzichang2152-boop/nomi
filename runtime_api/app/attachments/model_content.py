from __future__ import annotations

import base64
import copy
import mimetypes
import os
from pathlib import Path
from typing import Any, Optional, Union


MAX_MODEL_VISUALS = 6
MAX_MODEL_IMAGE_BYTES = 12 * 1024 * 1024
ALLOWED_IMAGE_MIME_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}

ChatContent = Union[str, list[dict[str, Any]]]
ChatMessage = dict[str, Any]


class AttachmentModelContentError(ValueError):
    pass


def build_chat_content(text: str, visual_evidence: list[dict[str, Any]]) -> ChatContent:
    """Keep private image references structured until the provider boundary."""

    selected = [item for item in visual_evidence if isinstance(item, dict)][:MAX_MODEL_VISUALS]
    if not selected:
        return str(text or "")
    parts: list[dict[str, Any]] = [{"type": "text", "text": str(text or "")}]
    for item in selected:
        image_ref: dict[str, Any] = {
            "mime_type": str(item.get("mime_type") or "image/png"),
            "evidence_id": str(item.get("evidence_id") or ""),
            "citation_label": str(item.get("citation_label") or ""),
            "locator": copy.deepcopy(item.get("locator") or {}),
        }
        if item.get("private_path") is not None:
            image_ref["private_path"] = Path(item["private_path"])
        elif item.get("storage_relative_path") is not None:
            image_ref["storage_relative_path"] = str(item["storage_relative_path"])
        else:
            raise AttachmentModelContentError("missing_private_image_reference")
        parts.append({"type": "image_url", "image_url": image_ref})
    return parts


def _attachment_root(value: Optional[str | Path]) -> Path:
    root = Path(value or os.getenv("ATTACHMENT_STORAGE_ROOT", "/data/attachments"))
    return root.expanduser().resolve()


def _private_image_path(image_ref: dict[str, Any], attachment_root: Optional[str | Path]) -> Path:
    root = _attachment_root(attachment_root)
    if image_ref.get("private_path") is not None:
        candidate = Path(image_ref["private_path"]).expanduser().resolve()
    else:
        relative = Path(str(image_ref.get("storage_relative_path") or ""))
        if not str(relative) or relative.is_absolute() or ".." in relative.parts:
            raise AttachmentModelContentError("outside_attachment_root")
        candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise AttachmentModelContentError("outside_attachment_root") from exc
    if not candidate.is_file():
        raise AttachmentModelContentError("private_image_missing")
    return candidate


def _mime_type(image_ref: dict[str, Any], path: Path) -> str:
    declared = str(image_ref.get("mime_type") or "").lower().strip()
    guessed = str(mimetypes.guess_type(path.name)[0] or "").lower()
    mime_type = declared or guessed
    if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise AttachmentModelContentError("unsupported_private_image_type")
    return mime_type


def qwen_provider_content(
    content: ChatContent,
    *,
    attachment_root: Optional[str | Path] = None,
) -> ChatContent:
    if isinstance(content, str):
        return content
    converted: list[dict[str, Any]] = []
    visual_count = 0
    for part in content:
        if not isinstance(part, dict):
            raise AttachmentModelContentError("invalid_chat_content_part")
        part_type = str(part.get("type") or "")
        if part_type == "text":
            converted.append({"type": "text", "text": str(part.get("text") or "")})
            continue
        if part_type != "image_url":
            raise AttachmentModelContentError("unsupported_chat_content_part")
        visual_count += 1
        if visual_count > MAX_MODEL_VISUALS:
            break
        image_ref = part.get("image_url") if isinstance(part.get("image_url"), dict) else {}
        path = _private_image_path(image_ref, attachment_root)
        byte_size = path.stat().st_size
        if byte_size <= 0 or byte_size > MAX_MODEL_IMAGE_BYTES:
            raise AttachmentModelContentError("private_image_size_invalid")
        mime_type = _mime_type(image_ref, path)
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        converted.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
            }
        )
    return converted


def qwen_provider_messages(
    messages: list[ChatMessage],
    *,
    attachment_root: Optional[str | Path] = None,
) -> list[ChatMessage]:
    converted: list[ChatMessage] = []
    for message in messages:
        content = message.get("content", "")
        converted.append(
            {
                **{key: copy.deepcopy(value) for key, value in message.items() if key != "content"},
                "content": qwen_provider_content(content, attachment_root=attachment_root),
            }
        )
    return converted


def attachment_trace(content: ChatContent) -> dict[str, Any]:
    if isinstance(content, str):
        return {"kind": "text", "text_chars": len(content), "visuals": []}
    visuals: list[dict[str, Any]] = []
    text_chars = 0
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            text_chars += len(str(part.get("text") or ""))
            continue
        if part.get("type") != "image_url":
            continue
        image_ref = part.get("image_url") if isinstance(part.get("image_url"), dict) else {}
        visuals.append(
            {
                "evidence_id": str(image_ref.get("evidence_id") or ""),
                "citation_label": str(image_ref.get("citation_label") or ""),
                "locator": copy.deepcopy(image_ref.get("locator") or {}),
                "mime_type": str(image_ref.get("mime_type") or ""),
            }
        )
    return {"kind": "multimodal", "text_chars": text_chars, "visuals": visuals}


def attachment_message_trace(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    return [
        {
            "role": str(message.get("role") or ""),
            "content": attachment_trace(message.get("content", "")),
        }
        for message in messages
    ]


__all__ = [
    "AttachmentModelContentError",
    "ChatContent",
    "ChatMessage",
    "MAX_MODEL_VISUALS",
    "attachment_message_trace",
    "attachment_trace",
    "build_chat_content",
    "qwen_provider_content",
    "qwen_provider_messages",
]
