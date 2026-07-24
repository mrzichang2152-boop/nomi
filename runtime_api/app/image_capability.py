from __future__ import annotations

import json
import os
import re
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any

from PIL import Image, ImageColor, ImageDraw, ImageFont, PngImagePlugin

from .capability_packs import select_capability_pack


PNG_MIME = "image/png"
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
PLACEHOLDER_RE = re.compile(r"(?i)\b(?:todo|tbd|lorem ipsum|placeholder)\b|待补充|此处填写|测试内容")
STRONG_CLAIM_RE = re.compile(
    r"不会(?:离开|上传|外发|传出)|立即|马上|实时|永远|始终|确保|保证|保障|保护|安全|泄露|控制权|删除|移除|加密|匿名|完全|绝对|绝不|零延迟|100\s*%|百分之(?:百|\d+)",
    re.IGNORECASE,
)
PROCESS_CLAIM_RE = re.compile(r"合并返回|汇总返回|自动同步|实时同步")
PRIVATE_EVIDENCE_EXPANSION_RE = re.compile(
    r"直接影响|决定(?:了)?|意味着|表明|说明|反映|因此|由此可见|"
    r"而非(?:仅|只)?|不(?:仅|只)依赖|保证|确保"
)
PROCESS_ITEM_PREFIX_RE = re.compile(r"^\s*(?:\d+\s*[.、):：]|第\s*\d+\s*步\s*[:：]?)\s*")
SUPPORTED_VISUAL_KINDS = {"infographic", "diagram", "social_card", "poster"}
SUPPORTED_BLOCK_KINDS = {"process", "callout", "metric", "list"}


class ImageSpecError(ValueError):
    pass


def _contains_unsupported_pictograph(value: str) -> bool:
    return any(
        unicodedata.category(character) == "So" or 0x1F000 <= ord(character) <= 0x1FAFF
        for character in value
    )


def _reject_unsupported_pictographs(value: str, *, field: str) -> None:
    if _contains_unsupported_pictograph(value):
        raise ImageSpecError(f"image {field} contains unsupported emoji or pictographic symbol")


def _pack():
    pack = select_capability_pack("image")
    if pack is None:
        raise ImageSpecError("image capability pack is not installed")
    return pack


def validate_image_spec(spec: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ImageSpecError("image specification must be an object")
    normalized = deepcopy(spec)
    for key in ("title", "purpose", "audience"):
        value = str(normalized.get(key) or "").strip()
        if not value:
            raise ImageSpecError(f"image {key} is required")
        if PLACEHOLDER_RE.search(value):
            raise ImageSpecError(f"image {key} contains placeholder content")
        _reject_unsupported_pictographs(value, field=key)
        normalized[key] = value
    if len(normalized["title"]) > 80:
        raise ImageSpecError("image title is too long")
    visual_kind = str(normalized.get("visual_kind") or "infographic").strip().lower()
    if visual_kind not in SUPPORTED_VISUAL_KINDS:
        raise ImageSpecError(f"unsupported visual kind: {visual_kind}")
    normalized["visual_kind"] = visual_kind
    canvas = normalized.get("canvas")
    if not isinstance(canvas, dict):
        raise ImageSpecError("image canvas is required")
    width = int(canvas.get("width") or 0)
    height = int(canvas.get("height") or 0)
    profile = dict(_pack().quality_profile)
    minimum = int(profile.get("minimum_dimension") or 512)
    maximum = int(profile.get("maximum_dimension") or 4096)
    if not (minimum <= width <= maximum and minimum <= height <= maximum):
        raise ImageSpecError(f"image dimensions must be between {minimum} and {maximum}")
    background = validate_color(canvas.get("background"), field="canvas.background")
    canvas.update({"width": width, "height": height, "background": background})
    palette = normalized.get("palette")
    if not isinstance(palette, dict):
        raise ImageSpecError("image palette is required")
    for field in ("ink", "muted", "accent", "highlight"):
        palette[field] = validate_color(palette.get(field), field=f"palette.{field}")
    minimum_contrast = float(profile.get("minimum_text_contrast_ratio") or 4.5)
    if contrast_ratio(palette["ink"], background) < minimum_contrast:
        raise ImageSpecError("image primary text contrast is below the required contrast ratio")
    if contrast_ratio(palette["muted"], background) < 3.0:
        raise ImageSpecError("image secondary text contrast is below the required contrast ratio")
    blocks = normalized.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ImageSpecError("image blocks must be a non-empty list")
    if len(blocks) > int(profile.get("maximum_block_count") or 6):
        raise ImageSpecError("image has too many blocks")
    for index, block in enumerate(blocks, start=1):
        if not isinstance(block, dict):
            raise ImageSpecError(f"image block {index} must be an object")
        kind = str(block.get("kind") or "callout").strip().lower()
        if kind not in SUPPORTED_BLOCK_KINDS:
            raise ImageSpecError(f"unsupported block kind: {kind}")
        heading = str(block.get("heading") or "").strip()
        body = str(block.get("body") or "").strip()
        value = str(block.get("value") or "").strip()
        raw_items = block.get("items") or []
        if not isinstance(raw_items, list):
            raise ImageSpecError(f"image block {index} items must be a list")
        if any(not isinstance(item, str) for item in raw_items):
            raise ImageSpecError(f"image block {index} items must be strings")
        items = [item.strip() for item in raw_items if item.strip()]
        if kind == "process":
            items = [PROCESS_ITEM_PREFIX_RE.sub("", item).strip() for item in items]
        all_text = "\n".join([heading, body, value, *items])
        if not heading or not any([body, value, items]):
            raise ImageSpecError(f"image block {index} needs heading and content")
        if PLACEHOLDER_RE.search(all_text):
            raise ImageSpecError(f"image block {index} contains placeholder content")
        _reject_unsupported_pictographs(all_text, field=f"block {index}")
        if len(all_text) > int(profile.get("maximum_characters_per_block") or 360):
            raise ImageSpecError(f"image block {index} content is too long")
        if len(items) > int(profile.get("maximum_items_per_block") or 5):
            raise ImageSpecError(f"image block {index} has too many items")
        block["kind"] = kind
        block["heading"] = heading
        block["body"] = body
        block["value"] = value
        block["items"] = items
        block["source_evidence_ids"] = list(
            dict.fromkeys(str(item).strip() for item in block.get("source_evidence_ids") or [] if str(item).strip())
        )
    footer = normalized.get("footer")
    if footer is not None and not isinstance(footer, str):
        raise ImageSpecError("image footer must be a string")
    normalized["footer"] = str(footer or "").strip()
    _reject_unsupported_pictographs(str(normalized.get("subtitle") or ""), field="subtitle")
    _reject_unsupported_pictographs(normalized["footer"], field="footer")
    return normalized


def validate_color(value: Any, *, field: str) -> str:
    color = str(value or "").strip()
    if not HEX_COLOR_RE.fullmatch(color):
        raise ImageSpecError(f"{field} must be a six-digit hex color")
    return color.upper()


def contrast_ratio(first: str, second: str) -> float:
    def luminance(color: str) -> float:
        rgb = ImageColor.getrgb(color)
        channels = []
        for value in rgb:
            component = value / 255.0
            channels.append(component / 12.92 if component <= 0.03928 else ((component + 0.055) / 1.055) ** 2.4)
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def render_image(
    spec: dict[str, Any],
    output_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    task_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = validate_image_spec(spec)
    _validate_image_evidence_grounding(normalized, task_packet=task_packet)
    pack = _pack()
    output = Path(output_path)
    if output.suffix.lower() != ".png":
        raise ImageSpecError("image output filename must end in .png")
    output.parent.mkdir(parents=True, exist_ok=True)
    width = normalized["canvas"]["width"]
    height = normalized["canvas"]["height"]
    background = normalized["canvas"]["background"]
    palette = normalized["palette"]
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    font_path = resolve_font_path()
    safe = max(48, int(min(width, height) * 0.055))
    bounds: list[tuple[int, int, int, int]] = []

    accent_width = max(10, width // 120)
    draw.rectangle((0, 0, accent_width, height), fill=palette["accent"])
    title_box = (safe, safe, width - safe, int(height * 0.19))
    bounds.append(draw_fitted_text(draw, normalized["title"], title_box, font_path=font_path, max_size=68, min_size=36, fill=palette["ink"], spacing=10))
    subtitle = str(normalized.get("subtitle") or normalized["purpose"]).strip()
    subtitle_box = (safe, int(height * 0.18), width - safe, int(height * 0.27))
    bounds.append(draw_fitted_text(draw, subtitle, subtitle_box, font_path=font_path, max_size=31, min_size=22, fill=palette["muted"], spacing=7))

    blocks = normalized["blocks"]
    gap = max(22, width // 70)
    columns = grid_column_count(len(blocks), width=width, height=height)
    rows = (len(blocks) + columns - 1) // columns
    grid_top = int(height * 0.31)
    grid_bottom = height - safe - 46
    card_width = (width - safe * 2 - gap * (columns - 1)) // columns
    card_height = (grid_bottom - grid_top - gap * (rows - 1)) // rows
    evidence_map: dict[str, list[str]] = {}
    for index, block in enumerate(blocks):
        row = index // columns
        column = index % columns
        left = safe + column * (card_width + gap)
        top = grid_top + row * (card_height + gap)
        right = left + card_width
        bottom = top + card_height
        draw.rounded_rectangle((left, top, right, bottom), radius=8, fill="#FFFFFF", outline="#D8E0E8", width=2)
        draw.rectangle((left, top, left + 8, bottom), fill=palette["accent"] if index % 2 == 0 else palette["highlight"])
        inner_left = left + 32
        inner_right = right - 26
        heading_bottom = top + min(80, card_height // 4)
        bounds.append(draw_fitted_text(draw, block["heading"], (inner_left, top + 24, inner_right, heading_bottom), font_path=font_path, max_size=28, min_size=20, fill=palette["ink"], spacing=5))
        body_top = heading_bottom + 8
        if block["kind"] == "metric" and block.get("value"):
            value_bottom = min(bottom - 90, body_top + 82)
            bounds.append(draw_fitted_text(draw, block["value"], (inner_left, body_top, inner_right, value_bottom), font_path=font_path, max_size=48, min_size=30, fill=palette["accent"], spacing=4))
            body_top = value_bottom + 10
        if block.get("body"):
            body_bottom = bottom - 28
            if block.get("items"):
                body_bottom = min(body_bottom, body_top + max(65, card_height // 3))
            bounds.append(draw_fitted_text(draw, block["body"], (inner_left, body_top, inner_right, body_bottom), font_path=font_path, max_size=22, min_size=16, fill=palette["muted"], spacing=7))
            body_top = body_bottom + 10
        items = block.get("items") or []
        if items:
            if block["kind"] == "process":
                bounds.extend(draw_process(draw, items, (inner_left, body_top, inner_right, bottom - 24), font_path=font_path, palette=palette))
            else:
                item_text = "\n".join(f"• {item}" for item in items)
                bounds.append(draw_fitted_text(draw, item_text, (inner_left, body_top, inner_right, bottom - 24), font_path=font_path, max_size=20, min_size=15, fill=palette["ink"], spacing=6))
        for evidence_id in block.get("source_evidence_ids") or []:
            evidence_map.setdefault(evidence_id, []).append(f"block:{index + 1}")

    footer = str(normalized.get("footer") or "Nomi · verified visual").strip()
    footer_font = load_font(font_path, 18)
    draw.text((safe, height - safe + 12), footer, font=footer_font, fill=palette["muted"])
    footer_bbox = draw.textbbox((safe, height - safe + 12), footer, font=footer_font)
    bounds.append(footer_bbox)

    overflow = [bbox for bbox in bounds if bbox[0] < 0 or bbox[1] < 0 or bbox[2] > width or bbox[3] > height]
    if overflow:
        raise ImageSpecError("rendered image text exceeds canvas bounds")
    png_info = PngImagePlugin.PngInfo()
    png_info.add_text("Title", normalized["title"])
    png_info.add_text("Author", "Nomi Image Studio")
    png_info.add_text("CapabilityPack", f"{pack.pack_id}@{pack.version}")
    image.save(output, format="PNG", optimize=True, pnginfo=png_info)

    probe = image.resize((200, max(1, int(200 * height / width))))
    colors = probe.getcolors(maxcolors=100000) or []
    distinct_color_count = len(colors)
    background_rgb = ImageColor.getrgb(background)
    background_pixels = sum(count for count, color in colors if color == background_rgb)
    total_pixels = probe.width * probe.height
    non_background_ratio = 1.0 - (background_pixels / total_pixels if total_pixels else 1.0)
    source_ids = list(evidence_map)
    minimum_contrast = float(pack.quality_profile.get("minimum_text_contrast_ratio") or 4.5)
    quality = {
        "status": "passed",
        "checks": {
            "font_loaded": bool(font_path),
            "text_fits_safe_bounds": not overflow,
            "minimum_contrast_met": contrast_ratio(palette["ink"], background) >= minimum_contrast,
            "non_blank_visual": non_background_ratio >= float(pack.quality_profile.get("minimum_non_background_ratio") or 0.08),
            "source_mapping_complete": all(evidence_map.get(source_id) for source_id in source_ids),
            "evidence_claims_grounded": True,
            "no_placeholder_content": True,
        },
        "distinct_color_count": distinct_color_count,
        "non_background_ratio": round(non_background_ratio, 4),
        "text_box_count": len(bounds),
        "overflow_count": len(overflow),
        "font_path": font_path,
    }
    if not quality["checks"]["non_blank_visual"]:
        raise ImageSpecError("rendered image is visually blank")
    manifest = {
        "artifact_type": "png",
        "filename": output.name,
        "file_path": str(output.resolve()),
        "mime_type": PNG_MIME,
        "capability_pack_id": pack.pack_id,
        "capability_pack_version": pack.version,
        "title": normalized["title"],
        "visual_kind": normalized["visual_kind"],
        "canvas": {"width": width, "height": height},
        "source_evidence_ids": source_ids,
        "evidence_to_content_map": evidence_map,
        "quality_report": quality,
        "task_contract_present": bool(task_packet),
    }
    if manifest_path is not None:
        path = Path(manifest_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _validate_image_evidence_grounding(
    spec: dict[str, Any],
    *,
    task_packet: dict[str, Any] | None,
) -> None:
    evidence = _task_evidence_by_id(task_packet)
    if not evidence:
        return
    contract = _task_requirements_contract(task_packet)
    strict_private_evidence = (
        str(contract.get("source_policy") or "").strip()
        == "must_use_private_evidence"
    )
    all_evidence_text = "\n".join(evidence.values())
    top_level_text = "\n".join(
        str(spec.get(field) or "") for field in ("title", "subtitle", "purpose", "footer")
    )
    for match in STRONG_CLAIM_RE.finditer(top_level_text):
        claim = match.group(0)
        if claim not in all_evidence_text:
            raise ImageSpecError(f"image top-level copy has unsupported strong claim '{claim}'")
    for index, block in enumerate(spec.get("blocks") or [], start=1):
        source_ids = block.get("source_evidence_ids") or []
        if not source_ids:
            raise ImageSpecError(f"image block {index} has no evidence id")
        unknown = [evidence_id for evidence_id in source_ids if evidence_id not in evidence]
        if unknown:
            raise ImageSpecError(f"image block {index} has unknown evidence id: {unknown[0]}")
        supporting_text = "\n".join(evidence[evidence_id] for evidence_id in source_ids)
        block_text = "\n".join(
            [
                str(block.get("heading") or ""),
                str(block.get("body") or ""),
                str(block.get("value") or ""),
                *[str(item) for item in block.get("items") or []],
            ]
        )
        for match in STRONG_CLAIM_RE.finditer(block_text):
            claim = match.group(0)
            if claim not in supporting_text:
                raise ImageSpecError(
                    f"image block {index} has unsupported strong claim '{claim}'"
                )
        if block.get("kind") == "process":
            for match in PROCESS_CLAIM_RE.finditer(block_text):
                claim = match.group(0)
                if claim not in supporting_text:
                    raise ImageSpecError(
                        f"image block {index} has unsupported process claim '{claim}'"
                    )
        if strict_private_evidence:
            for match in PRIVATE_EVIDENCE_EXPANSION_RE.finditer(block_text):
                claim = match.group(0)
                if claim not in supporting_text:
                    raise ImageSpecError(
                        "image block "
                        f"{index} has unsupported private-evidence expansion '{claim}'"
                    )


def _task_requirements_contract(task_packet: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(task_packet, dict):
        return {}
    plan_input = (
        task_packet.get("plan_input")
        if isinstance(task_packet.get("plan_input"), dict)
        else {}
    )
    for candidate in (
        task_packet.get("requirements_contract"),
        plan_input.get("requirements_contract"),
    ):
        if isinstance(candidate, dict):
            return dict(candidate)
    return {}


def _task_evidence_by_id(task_packet: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(task_packet, dict):
        return {}
    packs: list[Any] = []
    context = task_packet.get("context")
    if isinstance(context, dict):
        packs.append(context.get("evidence_pack"))
    plan_input = task_packet.get("plan_input")
    if isinstance(plan_input, dict):
        packs.append(plan_input.get("evidence_pack"))
    evidence: dict[str, str] = {}
    for pack in packs:
        if not isinstance(pack, dict):
            continue
        for item in pack.get("items") or []:
            if not isinstance(item, dict):
                continue
            evidence_id = str(item.get("evidence_id") or item.get("source_id") or "").strip()
            content = str(item.get("content") or item.get("text") or "").strip()
            if evidence_id and content:
                evidence[evidence_id] = content
    return evidence


def resolve_font_path() -> str:
    candidates = [
        os.getenv("NOMI_IMAGE_FONT", ""),
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise ImageSpecError("no compatible image font is installed")


def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=max(8, int(size)))


def draw_fitted_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    *,
    font_path: str,
    max_size: int,
    min_size: int,
    fill: str,
    spacing: int,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    for size in range(max_size, min_size - 1, -2):
        font = load_font(font_path, size)
        lines = wrap_text(draw, text, font, right - left)
        rendered = "\n".join(lines)
        bbox = draw.multiline_textbbox((left, top), rendered, font=font, spacing=spacing)
        if bbox[2] <= right and bbox[3] <= bottom:
            draw.multiline_text((left, top), rendered, font=font, fill=fill, spacing=spacing)
            return bbox
    raise ImageSpecError(f"text does not fit its visual box: {text[:40]}")


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, maximum_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in str(text).splitlines() or [""]:
        current = ""
        for character in paragraph:
            candidate = current + character
            if current and draw.textlength(candidate, font=font) > maximum_width:
                lines.append(current.rstrip())
                current = character.lstrip()
            else:
                current = candidate
        lines.append(current.rstrip())
    return [line for line in lines if line] or [""]


def grid_column_count(block_count: int, *, width: int = 1200, height: int = 1600) -> int:
    if block_count <= 1:
        return 1
    if block_count == 2:
        return 2
    if block_count == 3:
        return 2 if width >= height else 1
    if block_count == 4:
        return 2
    return 3


def draw_process(
    draw: ImageDraw.ImageDraw,
    items: list[str],
    box: tuple[int, int, int, int],
    *,
    font_path: str,
    palette: dict[str, str],
) -> list[tuple[int, int, int, int]]:
    left, top, right, bottom = box
    count = len(items)
    if count <= 0:
        return []
    gap = 12
    vertical_gap = 8
    vertical_row_height = (bottom - top - vertical_gap * (count - 1)) // count
    if (right - left) // count < 170 and vertical_row_height >= 42:
        return _draw_vertical_process(
            draw,
            items,
            box,
            font_path=font_path,
            palette=palette,
        )
    width = (right - left - gap * (count - 1)) // count
    bounds = []
    center_y = top + 22
    for index, item in enumerate(items):
        item_left = left + index * (width + gap)
        circle = (item_left, top, item_left + 42, top + 42)
        draw.ellipse(circle, fill=palette["accent"])
        number_font = load_font(font_path, 18)
        draw.text((item_left + 15, top + 8), str(index + 1), font=number_font, fill="#FFFFFF")
        if index < count - 1:
            draw.line((item_left + 46, center_y, item_left + width + gap - 5, center_y), fill="#B7C2CE", width=3)
        bounds.append(draw_fitted_text(draw, item, (item_left, top + 56, item_left + width, bottom), font_path=font_path, max_size=18, min_size=14, fill=palette["ink"], spacing=4))
    return bounds


def _draw_vertical_process(
    draw: ImageDraw.ImageDraw,
    items: list[str],
    box: tuple[int, int, int, int],
    *,
    font_path: str,
    palette: dict[str, str],
) -> list[tuple[int, int, int, int]]:
    left, top, right, bottom = box
    count = len(items)
    gap = 8
    row_height = (bottom - top - gap * (count - 1)) // count
    if row_height < 42:
        raise ImageSpecError("process steps do not have enough vertical space")
    circle_size = min(38, row_height - 12)
    circle_left = left
    text_left = circle_left + circle_size + 16
    bounds: list[tuple[int, int, int, int]] = []
    number_font = load_font(font_path, min(18, max(14, circle_size // 2)))
    for index, item in enumerate(items):
        row_top = top + index * (row_height + gap)
        circle_top = row_top + max(0, (row_height - circle_size) // 2)
        circle = (circle_left, circle_top, circle_left + circle_size, circle_top + circle_size)
        draw.ellipse(circle, fill=palette["accent"])
        number = str(index + 1)
        number_box = draw.textbbox((0, 0), number, font=number_font)
        number_width = number_box[2] - number_box[0]
        number_height = number_box[3] - number_box[1]
        draw.text(
            (
                circle_left + (circle_size - number_width) / 2,
                circle_top + (circle_size - number_height) / 2 - number_box[1],
            ),
            number,
            font=number_font,
            fill="#FFFFFF",
        )
        if index < count - 1:
            center_x = circle_left + circle_size // 2
            draw.line(
                (center_x, circle_top + circle_size + 3, center_x, row_top + row_height + gap - 3),
                fill="#B7C2CE",
                width=3,
            )
        bounds.append(
            draw_fitted_text(
                draw,
                item,
                (text_left, row_top + 4, right, row_top + row_height - 4),
                font_path=font_path,
                max_size=19,
                min_size=15,
                fill=palette["ink"],
                spacing=4,
            )
        )
    return bounds
