import json
import os
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def _write_manifest(root: Path, folder: str, payload: dict) -> Path:
    pack_dir = root / folder
    pack_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = pack_dir / "manifest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def _valid_manifest(*, pack_id: str, artifact_types: list[str]) -> dict:
    return {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "display_name": "Presentation Quality",
        "artifact_types": artifact_types,
        "default_agent": "presentation-producer",
        "resource_paths": {
            "skills": ["skills/presentation-quality/SKILL.md"],
            "agents": ["agents/presentation-producer.md"],
            "tools": ["tools/create_presentation.ts"],
            "plugins": [],
        },
        "quality_profile": {
            "minimum_slide_count": 1,
            "minimum_layout_kinds": 2,
            "maximum_text_chars_per_slide": 700,
            "require_visual_for_slide_count": 4,
        },
    }


def test_repository_presentation_pack_is_selected_for_pptx():
    from app.capability_packs import discover_capability_packs, select_capability_pack

    root = Path(__file__).resolve().parents[1] / "opencode_capabilities"
    packs = discover_capability_packs(root)
    selected = select_capability_pack("PPTX", packs=packs)

    assert selected is not None
    assert selected.pack_id == "presentation"
    assert selected.version == "1.0.0"
    assert selected.artifact_types == ("pptx",)
    assert selected.default_agent == "presentation-producer"
    assert selected.quality_profile["maximum_text_chars_per_slide"] == 360
    assert select_capability_pack("pdf", packs=packs) is None


def test_repository_spreadsheet_pack_is_selected_for_xlsx():
    from app.capability_packs import discover_capability_packs, select_capability_pack

    root = Path(__file__).resolve().parents[1] / "opencode_capabilities"
    packs = discover_capability_packs(root)
    selected = select_capability_pack("XLSX", packs=packs)

    assert selected is not None
    assert selected.pack_id == "spreadsheet"
    assert selected.version == "1.0.0"
    assert selected.default_agent == "spreadsheet-producer"
    assert selected.quality_profile["require_formula_cached_values"] is True


def test_adapter_selects_spreadsheet_pack_and_stages_only_spreadsheet_resources(tmp_path, monkeypatch):
    from scripts import nomi_opencode_cli_adapter as adapter

    monkeypatch.delenv("OPENCODE_CONFIG", raising=False)
    monkeypatch.delenv("OPENCODE_CONFIG_CONTENT", raising=False)
    monkeypatch.delenv("NOMI_OPENCODE_CLI_RUN_ARGS", raising=False)
    pack_root = Path(__file__).resolve().parents[1] / "opencode_capabilities"
    packet = {
        "route_decision": {"artifact_type": "xlsx"},
        "original_goal": "根据报价明细制作成本和利润率分析表",
    }

    staged = adapter.prepare_capability_pack(packet, workspace=tmp_path, packs_root=pack_root)
    config = adapter.ensure_opencode_runtime_defaults(staged_pack=staged)
    prompt = adapter.build_opencode_prompt(
        packet,
        workspace=tmp_path,
        manifest_path=tmp_path / "manifest.json",
        staged_pack=staged,
    )

    assert staged is not None
    assert staged.pack.pack_id == "spreadsheet"
    assert config["default_agent"] == "spreadsheet-producer"
    assert (tmp_path / ".opencode/skills/spreadsheet-quality/SKILL.md").is_file()
    assert (tmp_path / ".opencode/tools/create_spreadsheet.ts").is_file()
    assert not (tmp_path / ".opencode/tools/create_presentation.ts").exists()
    assert "spreadsheet@1.0.0" in prompt
    assert "spreadsheet-quality" in prompt


@pytest.mark.parametrize(
    "pack_id",
    ["presentation", "spreadsheet", "document", "image"],
)
def test_repository_pack_tools_use_configurable_local_renderer_runtime(pack_id):
    root = Path(__file__).resolve().parents[1] / "opencode_capabilities"
    tool_files = list((root / pack_id / "tools").glob("*.ts"))

    assert tool_files
    for tool_file in tool_files:
        source = tool_file.read_text(encoding="utf-8")
        assert "NOMI_RUNTIME_SCRIPTS_DIR" in source
        assert "NOMI_PYTHON_EXECUTABLE" in source
        assert "python /app/scripts/" not in source
        assert ".nothrow()" in source
        assert "result.stderr" in source
        assert 'status: "failed"' in source
        assert "rm(manifestPath, { force: true })" in source
        assert "--packet ${process.env.NOMI_OPENCODE_STEP_PACKET" in source


@pytest.mark.parametrize(
    ("pack_id", "required_markers"),
    [
        ("presentation", ("title: tool.schema.string()", "slides: tool.schema.array(")),
        ("spreadsheet", ("title: tool.schema.string()", "sheets: tool.schema.array(")),
        ("document", ("title: tool.schema.string()", "sections: tool.schema.array(")),
        ("image", ("title: tool.schema.string()", "blocks: tool.schema.array(")),
    ],
)
def test_repository_pack_tools_accept_flat_structured_arguments(pack_id, required_markers):
    root = Path(__file__).resolve().parents[1] / "opencode_capabilities"
    tool_files = list((root / pack_id / "tools").glob("*.ts"))

    assert tool_files
    for tool_file in tool_files:
        source = tool_file.read_text(encoding="utf-8")
        assert "specification:" not in source
        assert all(marker in source for marker in required_markers)
        if pack_id == "image":
            assert "const { filename, ...content } = args" in source
        else:
            assert "const { filename, ...specification } = args" in source
        assert "JSON.stringify(specification, null, 2)" in source


def test_image_tool_owns_verified_canvas_and_palette_defaults():
    root = Path(__file__).resolve().parents[1] / "opencode_capabilities"
    source = (root / "image/tools/create_image.ts").read_text(encoding="utf-8")

    assert "canvas: tool.schema.object" not in source
    assert "palette: tool.schema.object" not in source
    assert "DEFAULT_CANVAS" in source
    assert "DEFAULT_PALETTE" in source
    assert "canvas: DEFAULT_CANVAS" in source
    assert "palette: DEFAULT_PALETTE" in source


@pytest.mark.parametrize(
    "pack_id",
    ["presentation", "spreadsheet", "document", "image"],
)
def test_repository_pack_agents_call_renderer_without_runtime_skill_roundtrip(pack_id):
    root = Path(__file__).resolve().parents[1] / "opencode_capabilities"
    agent_files = list((root / pack_id / "agents").glob("*.md"))

    assert agent_files
    for agent_file in agent_files:
        source = agent_file.read_text(encoding="utf-8")
        assert "steps: 8" in source
        assert "steps: 20" not in source
        assert "Load `" not in source
        assert "加载 `" not in source
        assert '"*": deny' in source
        assert "-quality: allow" not in source
        assert "first action" in source.lower()


def test_spreadsheet_skill_documents_excel_a1_formula_templates():
    root = Path(__file__).resolve().parents[1] / "opencode_capabilities"
    skill = (root / "spreadsheet/skills/spreadsheet-quality/SKILL.md").read_text(encoding="utf-8")

    assert "=B{row}-C{row}" in skill
    assert "=IFERROR(D{row}/B{row},0)" in skill
    assert "{row}.revenue" in skill
    assert "禁止" in skill


def test_document_skill_preserves_observations_and_requires_flat_text_arrays():
    root = Path(__file__).resolve().parents[1] / "opencode_capabilities"
    skill = (root / "document/skills/document-quality/SKILL.md").read_text(encoding="utf-8")

    assert "flat array of strings" in skill
    assert "observed metric" in skill
    assert "target or commitment" in skill
    assert "unsupported status conclusion" in skill
    assert "causal" in skill

    agent = (root / "document/agents/document-producer.md").read_text(encoding="utf-8")
    assert "observed metric" in agent
    assert "target or commitment" in agent
    assert "causal" in agent


def test_image_skill_documents_flat_items_and_string_footer():
    root = Path(__file__).resolve().parents[1] / "opencode_capabilities"
    skill = (root / "image/skills/image-quality/SKILL.md").read_text(encoding="utf-8")
    agent = (root / "image/agents/image-producer.md").read_text(encoding="utf-8")

    assert "flat array of strings" in skill
    assert "footer" in skill
    assert "single string" in skill
    assert "strong claim" in skill
    assert "emoji" in skill
    assert "vertical" in skill
    assert "process step" in skill
    assert "flat array of strings" in agent
    assert "single string" in agent
    assert "strong claim" in agent
    assert "emoji" in agent
    assert "vertical" in agent
    assert "process step" in agent


def test_repository_document_pack_is_selected_for_docx():
    from app.capability_packs import discover_capability_packs, select_capability_pack

    root = Path(__file__).resolve().parents[1] / "opencode_capabilities"
    packs = discover_capability_packs(root)
    selected = select_capability_pack("DOCX", packs=packs)

    assert selected is not None
    assert selected.pack_id == "document"
    assert selected.version == "1.0.0"
    assert selected.default_agent == "document-producer"
    assert selected.quality_profile["require_heading_hierarchy"] is True


def test_repository_image_pack_is_selected_for_image_and_png():
    from app.capability_packs import discover_capability_packs, select_capability_pack

    root = Path(__file__).resolve().parents[1] / "opencode_capabilities"
    packs = discover_capability_packs(root)

    for artifact_type in ("image", "png"):
        selected = select_capability_pack(artifact_type, packs=packs)
        assert selected is not None
        assert selected.pack_id == "image"
        assert selected.version == "1.0.0"
        assert selected.default_agent == "image-producer"


def test_discovery_rejects_manifest_resource_outside_pack(tmp_path):
    from app.capability_packs import CapabilityPackError, discover_capability_packs

    manifest = _valid_manifest(pack_id="unsafe", artifact_types=["pptx"])
    manifest["resource_paths"]["skills"] = ["../outside/SKILL.md"]
    _write_manifest(tmp_path, "unsafe", manifest)

    with pytest.raises(CapabilityPackError, match="inside its pack directory"):
        discover_capability_packs(tmp_path)


def test_discovery_rejects_missing_declared_resource(tmp_path):
    from app.capability_packs import CapabilityPackError, discover_capability_packs

    _write_manifest(tmp_path, "missing", _valid_manifest(pack_id="missing", artifact_types=["pptx"]))

    with pytest.raises(CapabilityPackError, match="does not exist"):
        discover_capability_packs(tmp_path)


def test_discovery_rejects_duplicate_artifact_type_ownership(tmp_path):
    from app.capability_packs import CapabilityPackError, discover_capability_packs

    for folder in ("first", "second"):
        manifest = _valid_manifest(pack_id=folder, artifact_types=["pptx"])
        for relative_path in (
            "skills/presentation-quality/SKILL.md",
            "agents/presentation-producer.md",
            "tools/create_presentation.ts",
        ):
            path = tmp_path / folder / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("resource", encoding="utf-8")
        _write_manifest(tmp_path, folder, manifest)

    with pytest.raises(CapabilityPackError, match="already owned"):
        discover_capability_packs(tmp_path)


def test_discovery_rejects_manifest_folder_id_mismatch(tmp_path):
    from app.capability_packs import CapabilityPackError, discover_capability_packs

    manifest = _valid_manifest(pack_id="different", artifact_types=["pptx"])
    for relative_path in (
        "skills/presentation-quality/SKILL.md",
        "agents/presentation-producer.md",
        "tools/create_presentation.ts",
    ):
        path = tmp_path / "folder-name" / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("resource", encoding="utf-8")
    _write_manifest(tmp_path, "folder-name", manifest)

    with pytest.raises(CapabilityPackError, match="must match directory"):
        discover_capability_packs(tmp_path)


def test_stage_capability_pack_copies_only_declared_resources(tmp_path):
    from app.capability_packs import discover_capability_packs, select_capability_pack, stage_capability_pack

    pack_root = Path(__file__).resolve().parents[1] / "opencode_capabilities"
    pack = select_capability_pack("pptx", packs=discover_capability_packs(pack_root))
    assert pack is not None
    undeclared = pack.pack_dir / "skills" / "not-declared" / "SKILL.md"
    undeclared.parent.mkdir(parents=True, exist_ok=True)
    undeclared.write_text("must not be staged", encoding="utf-8")
    try:
        staged = stage_capability_pack(pack, tmp_path / "workspace")
    finally:
        undeclared.unlink()
        undeclared.parent.rmdir()

    opencode_root = tmp_path / "workspace" / ".opencode"
    assert (opencode_root / "skills" / "presentation-quality" / "SKILL.md").is_file()
    assert (opencode_root / "agents" / "presentation-producer.md").is_file()
    assert (opencode_root / "tools" / "create_presentation.ts").is_file()
    assert not (opencode_root / "skills" / "not-declared" / "SKILL.md").exists()
    assert staged.pack.pack_id == "presentation"
    assert staged.staged_resources["skills"] == (
        ".opencode/skills/presentation-quality/SKILL.md",
    )


def test_adapter_selects_and_injects_presentation_pack_without_losing_qwen_config(tmp_path, monkeypatch):
    from scripts import nomi_opencode_cli_adapter as adapter

    monkeypatch.delenv("OPENCODE_CONFIG", raising=False)
    monkeypatch.delenv("OPENCODE_CONFIG_CONTENT", raising=False)
    monkeypatch.delenv("NOMI_OPENCODE_CLI_RUN_ARGS", raising=False)
    monkeypatch.setenv("MODEL_BASE_URL", "http://model.local:9161/v1")
    pack_root = Path(__file__).resolve().parents[1] / "opencode_capabilities"
    packet = {
        "route_decision": {"artifact_type": "pptx"},
        "original_goal": "为普通人制作一份 LLM 原理 PPT",
        "plan_input": {
            "requirements_contract": {
                "page_count": 4,
                "audience": "普通人",
            }
        },
    }

    staged = adapter.prepare_capability_pack(packet, workspace=tmp_path, packs_root=pack_root)
    config = adapter.ensure_opencode_runtime_defaults(staged_pack=staged)
    prompt = adapter.build_opencode_prompt(
        packet,
        workspace=tmp_path,
        manifest_path=tmp_path / "manifest.json",
        staged_pack=staged,
    )

    assert staged is not None
    assert staged.pack.pack_id == "presentation"
    assert config["model"] == "nomi-qwen/qwen/qwen3.6-27b"
    assert config["provider"]["nomi-qwen"]["options"]["baseURL"] == "http://model.local:9161/v1"
    assert config["default_agent"] == "presentation-producer"
    assert config["skills"]["paths"] == [str(tmp_path / ".opencode" / "skills")]
    assert "presentation@1.0.0" in prompt
    assert "presentation-quality" in prompt
    assert "精确页数：4（少一页或多一页都不合格）" in prompt
    assert "目标受众：普通人" in prompt
    assert "在 manifest 成功写出前不得结束任务" in prompt
    assert "--agent presentation-producer" in os.environ["NOMI_OPENCODE_CLI_RUN_ARGS"]


def test_adapter_does_not_stage_pack_for_unsupported_artifact(tmp_path):
    from scripts import nomi_opencode_cli_adapter as adapter

    pack_root = Path(__file__).resolve().parents[1] / "opencode_capabilities"
    staged = adapter.prepare_capability_pack(
        {"route_decision": {"artifact_type": "pdf"}},
        workspace=tmp_path,
        packs_root=pack_root,
    )

    assert staged is None
    assert not (tmp_path / ".opencode").exists()


def test_presentation_agent_denies_runtime_skill_loading():
    agent_path = (
        Path(__file__).resolve().parents[1]
        / "opencode_capabilities"
        / "presentation"
        / "agents"
        / "presentation-producer.md"
    )
    content = agent_path.read_text(encoding="utf-8")

    assert '"*": deny' in content
    assert "presentation-quality: allow" not in content
    assert "write: allow" not in content
