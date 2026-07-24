import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def _spec() -> dict:
    return {
        "title": "大语言模型如何生成答案",
        "subtitle": "一张图看懂从输入到逐 token 生成",
        "purpose": "帮助没有技术背景的听众建立正确的工作原理心智模型",
        "audience": "普通用户",
        "visual_kind": "infographic",
        "canvas": {"width": 1600, "height": 1000, "background": "#F4F7F9"},
        "palette": {"ink": "#172033", "muted": "#526071", "accent": "#00897B", "highlight": "#FFB020"},
        "blocks": [
            {
                "kind": "process",
                "heading": "生成阶段是连续预测",
                "body": "模型基于当前上下文计算下一个 token 的分布，再按解码策略选择并继续。",
                "items": ["读取上下文", "计算概率分布", "选择 token", "追加后继续"],
                "source_evidence_ids": ["evt_llm_001"],
            },
            {
                "kind": "callout",
                "heading": "上下文决定当前可用信息",
                "body": "系统指令、用户输入、历史对话、检索证据和工具结果都可能进入本次上下文。",
                "source_evidence_ids": ["evt_llm_001"],
            },
            {
                "kind": "metric",
                "heading": "核心输出单位",
                "value": "TOKEN",
                "body": "token 可以是字、词或词的一部分，不等于固定的一个单词。",
                "source_evidence_ids": ["evt_llm_001"],
            },
        ],
        "footer": "Nomi · 可追溯信息图",
    }


def test_render_image_creates_readable_nonblank_traceable_infographic(tmp_path):
    from app.image_capability import render_image

    output = tmp_path / "llm-infographic.png"
    manifest_path = tmp_path / "manifest.json"
    manifest = render_image(_spec(), output, manifest_path=manifest_path)

    assert output.is_file()
    assert manifest["artifact_type"] == "png"
    assert manifest["capability_pack_id"] == "image"
    assert manifest["canvas"] == {"width": 1600, "height": 1000}
    assert manifest["source_evidence_ids"] == ["evt_llm_001"]
    assert manifest["evidence_to_content_map"]["evt_llm_001"] == ["block:1", "block:2", "block:3"]
    report = manifest["quality_report"]
    assert report["status"] == "passed"
    assert report["checks"]["text_fits_safe_bounds"] is True
    assert report["checks"]["minimum_contrast_met"] is True
    assert report["distinct_color_count"] >= 8
    assert report["non_background_ratio"] > 0.08

    with Image.open(output) as image:
        assert image.size == (1600, 1000)
        assert image.mode == "RGB"
        assert image.getbbox() == (0, 0, 1600, 1000)
        colors = image.resize((200, 125)).getcolors(maxcolors=50000)
        assert colors is not None and len(colors) >= 8


def test_validate_image_rejects_low_contrast_and_unknown_block_kind():
    from app.image_capability import ImageSpecError, validate_image_spec

    spec = _spec()
    spec["palette"]["ink"] = "#F5F5F5"
    spec["canvas"]["background"] = "#F4F4F4"
    with pytest.raises(ImageSpecError, match="contrast"):
        validate_image_spec(spec)

    spec = _spec()
    spec["blocks"][0]["kind"] = "photorealistic_portrait"
    with pytest.raises(ImageSpecError, match="unsupported block kind"):
        validate_image_spec(spec)


def test_validate_image_rejects_placeholder_or_overlong_content():
    from app.image_capability import ImageSpecError, validate_image_spec

    spec = _spec()
    spec["blocks"][0]["body"] = "TODO"
    with pytest.raises(ImageSpecError, match="placeholder"):
        validate_image_spec(spec)

    spec = _spec()
    spec["blocks"][0]["body"] = "过长正文" * 120
    with pytest.raises(ImageSpecError, match="too long"):
        validate_image_spec(spec)


def test_validate_image_rejects_emoji_that_the_renderer_font_cannot_display():
    from app.image_capability import ImageSpecError, validate_image_spec

    spec = _spec()
    spec["blocks"][0]["heading"] = "📥 消息进入记忆"

    with pytest.raises(ImageSpecError, match="emoji or pictographic"):
        validate_image_spec(spec)


def test_validate_image_normalizes_process_number_prefixes():
    from app.image_capability import validate_image_spec

    spec = _spec()
    spec["blocks"][0]["items"] = ["1. 读取上下文", "2、计算概率分布", "第3步：选择 token"]

    normalized = validate_image_spec(spec)

    assert normalized["blocks"][0]["items"] == ["读取上下文", "计算概率分布", "选择 token"]


def test_validate_image_rejects_non_string_list_items():
    from app.image_capability import ImageSpecError, validate_image_spec

    spec = _spec()
    spec["blocks"][0]["items"] = [{"label": "不能静默转成字典文本"}]

    with pytest.raises(ImageSpecError, match="items must be strings"):
        validate_image_spec(spec)


def test_validate_image_rejects_non_string_footer():
    from app.image_capability import ImageSpecError, validate_image_spec

    spec = _spec()
    spec["footer"] = {"text": "不能静默转成字典文本"}

    with pytest.raises(ImageSpecError, match="footer must be a string"):
        validate_image_spec(spec)


def test_render_image_rejects_unknown_evidence_and_unsupported_strong_claims(tmp_path):
    from app.image_capability import ImageSpecError, render_image

    packet = {
        "plan_input": {
            "evidence_pack": {
                "items": [
                    {
                        "evidence_id": "memory_correction",
                        "content": "用户可以纠正错误关系和事实。",
                    }
                ]
            }
        }
    }

    spec = _spec()
    spec["blocks"][0]["source_evidence_ids"] = ["missing_evidence"]
    with pytest.raises(ImageSpecError, match="unknown evidence id"):
        render_image(spec, tmp_path / "unknown.png", task_packet=packet)

    spec = _spec()
    for block in spec["blocks"]:
        block["source_evidence_ids"] = ["memory_correction"]
    spec["blocks"][0]["items"] = ["您的修改会立即生效"]
    with pytest.raises(ImageSpecError, match="unsupported strong claim.*立即"):
        render_image(spec, tmp_path / "unsupported.png", task_packet=packet)

    spec = _spec()
    for block in spec["blocks"]:
        block["source_evidence_ids"] = ["memory_correction"]
    spec["subtitle"] = "您的信息始终安全"
    with pytest.raises(ImageSpecError, match="unsupported strong claim.*始终"):
        render_image(spec, tmp_path / "unsupported-title.png", task_packet=packet)

    spec = _spec()
    for block in spec["blocks"]:
        block["source_evidence_ids"] = ["memory_correction"]
    spec["subtitle"] = "五步保障您的隐私"
    with pytest.raises(ImageSpecError, match="unsupported strong claim.*保障"):
        render_image(spec, tmp_path / "unsupported-security.png", task_packet=packet)

    spec = _spec()
    for block in spec["blocks"]:
        block["source_evidence_ids"] = ["memory_correction"]
    spec["blocks"][0]["body"] = "原始资料不会离开用户控制范围。"
    with pytest.raises(ImageSpecError, match="unsupported strong claim.*不会离开"):
        render_image(spec, tmp_path / "unsupported-boundary.png", task_packet=packet)

    spec = _spec()
    for block in spec["blocks"]:
        block["source_evidence_ids"] = ["memory_correction"]
    spec["blocks"][0]["items"] = ["多路检索结果合并返回"]
    with pytest.raises(ImageSpecError, match="unsupported process claim.*合并返回"):
        render_image(spec, tmp_path / "unsupported-process.png", task_packet=packet)


def test_render_image_rejects_unsupported_private_evidence_expansion(tmp_path):
    from app.image_capability import ImageSpecError, render_image

    spec = _spec()
    spec["blocks"] = [
        {
            "kind": "callout",
            "heading": "阶段一：检索",
            "body": "检索找到相关资料。检索质量直接影响后续生成的准确性。",
            "source_evidence_ids": ["evt_rag"],
        }
    ]
    packet = {
        "plan_input": {
            "requirements_contract": {
                "source_policy": "must_use_private_evidence",
            },
            "evidence_pack": {
                "items": [
                    {
                        "evidence_id": "evt_rag",
                        "content": "检索找到相关资料。",
                    }
                ]
            },
        }
    }

    with pytest.raises(ImageSpecError, match="unsupported private-evidence expansion.*直接影响"):
        render_image(spec, tmp_path / "unsupported-expansion.png", task_packet=packet)


def test_narrow_process_card_uses_vertical_steps_for_readability():
    from app.image_capability import draw_process, resolve_font_path

    image = Image.new("RGB", (600, 700), "#FFFFFF")
    draw = __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).Draw(image)
    bounds = draw_process(
        draw,
        ["消息到达并识别会话", "按会话和参与者隔离", "提取事实事件和关系", "存入记忆供检索"],
        (40, 40, 560, 660),
        font_path=resolve_font_path(),
        palette={"ink": "#172033", "muted": "#526071", "accent": "#00897B", "highlight": "#FFB020"},
    )

    assert len(bounds) == 4
    assert len({bbox[1] for bbox in bounds}) == 4
    assert all(bbox[0] >= 90 for bbox in bounds)


def test_dense_five_step_process_uses_vertical_layout_when_text_can_fit():
    from app.image_capability import draw_process, resolve_font_path

    image = Image.new("RGB", (600, 420), "#FFFFFF")
    draw = __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).Draw(image)
    bounds = draw_process(
        draw,
        [
            "会话与参与者隔离",
            "提取事实信息",
            "识别并记录事件",
            "梳理实体关系",
            "写入记忆",
        ],
        (40, 40, 560, 340),
        font_path=resolve_font_path(),
        palette={"ink": "#172033", "muted": "#526071", "accent": "#00897B", "highlight": "#FFB020"},
    )

    assert len({bbox[1] for bbox in bounds}) == 5


def test_three_block_infographic_uses_full_width_cards():
    from app.image_capability import grid_column_count

    assert grid_column_count(1) == 1
    assert grid_column_count(2) == 2
    assert grid_column_count(3, width=800, height=1600) == 1
    assert grid_column_count(3, width=1600, height=1000) == 2
    assert grid_column_count(4) == 2
    assert grid_column_count(5) == 3


def test_image_cli_writes_verified_manifest(tmp_path):
    spec_path = tmp_path / "spec.json"
    output = tmp_path / "visual.png"
    manifest = tmp_path / "manifest.json"
    spec_path.write_text(json.dumps(_spec(), ensure_ascii=False), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "scripts" / "nomi_image_tool.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--spec", str(spec_path), "--output", str(output), "--manifest", str(manifest)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["manifest"]["quality_report"]["checks"]["font_loaded"] is True
    assert json.loads(manifest.read_text(encoding="utf-8"))["filename"] == "visual.png"
