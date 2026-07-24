from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping


PACK_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$")
RESOURCE_KINDS = ("skills", "agents", "tools", "plugins")


class CapabilityPackError(ValueError):
    pass


@dataclass(frozen=True)
class CapabilityPack:
    pack_id: str
    version: str
    display_name: str
    artifact_types: tuple[str, ...]
    default_agent: str
    pack_dir: Path
    resource_paths: Mapping[str, tuple[str, ...]]
    quality_profile: Mapping[str, Any]

    def paths_for(self, kind: str) -> tuple[Path, ...]:
        return tuple(self.pack_dir / relative for relative in self.resource_paths.get(kind, ()))

    def as_metadata(self) -> dict[str, Any]:
        return {
            "capability_pack_id": self.pack_id,
            "capability_pack_version": self.version,
            "artifact_types": list(self.artifact_types),
            "default_agent": self.default_agent,
            "quality_profile": dict(self.quality_profile),
        }


@dataclass(frozen=True)
class StagedCapabilityPack:
    pack: CapabilityPack
    workspace: Path
    opencode_root: Path
    staged_resources: Mapping[str, tuple[str, ...]]

    def config_overlay(self) -> dict[str, Any]:
        return {
            "default_agent": self.pack.default_agent,
            "skills": {"paths": [str(self.opencode_root / "skills")]},
        }

    def as_metadata(self) -> dict[str, Any]:
        return {
            **self.pack.as_metadata(),
            "staged_resources": {
                kind: list(paths) for kind, paths in self.staged_resources.items()
            },
        }


def default_capability_packs_dir() -> Path:
    configured = str(os.getenv("NOMI_CAPABILITY_PACKS_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parents[1] / "opencode_capabilities").resolve()


def discover_capability_packs(root: str | os.PathLike[str] | None = None) -> tuple[CapabilityPack, ...]:
    packs_root = Path(root).expanduser().resolve() if root is not None else default_capability_packs_dir()
    if not packs_root.exists():
        return ()
    if not packs_root.is_dir():
        raise CapabilityPackError(f"Capability packs root is not a directory: {packs_root}")

    packs: list[CapabilityPack] = []
    artifact_owners: dict[str, str] = {}
    for manifest_path in sorted(packs_root.glob("*/manifest.json")):
        pack = _load_capability_pack(manifest_path)
        for artifact_type in pack.artifact_types:
            existing_owner = artifact_owners.get(artifact_type)
            if existing_owner is not None:
                raise CapabilityPackError(
                    f"Artifact type '{artifact_type}' is already owned by capability pack '{existing_owner}'."
                )
            artifact_owners[artifact_type] = pack.pack_id
        packs.append(pack)
    return tuple(packs)


def select_capability_pack(
    artifact_type: str,
    *,
    packs: Iterable[CapabilityPack] | None = None,
) -> CapabilityPack | None:
    normalized = str(artifact_type or "").strip().lower().lstrip(".")
    if not normalized:
        return None
    available = tuple(packs) if packs is not None else discover_capability_packs()
    for pack in available:
        if normalized in pack.artifact_types:
            return pack
    return None


def stage_capability_pack(pack: CapabilityPack, workspace: str | os.PathLike[str]) -> StagedCapabilityPack:
    workspace_path = Path(workspace).expanduser().resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)
    opencode_root = workspace_path / ".opencode"
    staged: dict[str, tuple[str, ...]] = {}
    for kind in RESOURCE_KINDS:
        copied: list[str] = []
        for relative in pack.resource_paths.get(kind, ()):
            relative_path = Path(relative)
            parts = relative_path.parts
            if not parts or parts[0] != kind:
                raise CapabilityPackError(
                    f"Capability pack resource '{relative}' must be placed under its '{kind}/' directory."
                )
            destination = (opencode_root / kind / Path(*parts[1:])).resolve()
            try:
                destination.relative_to(opencode_root.resolve())
            except ValueError as exc:
                raise CapabilityPackError(
                    f"Capability pack staging destination escaped .opencode: {destination}"
                ) from exc
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pack.pack_dir / relative_path, destination)
            copied.append(destination.relative_to(workspace_path).as_posix())
        staged[kind] = tuple(copied)

    metadata_path = workspace_path / "nomi_capability_pack.json"
    metadata_path.write_text(
        json.dumps(pack.as_metadata(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return StagedCapabilityPack(
        pack=pack,
        workspace=workspace_path,
        opencode_root=opencode_root,
        staged_resources=MappingProxyType(staged),
    )


def _load_capability_pack(manifest_path: Path) -> CapabilityPack:
    pack_dir = manifest_path.parent.resolve()
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityPackError(f"Invalid capability pack manifest: {manifest_path}") from exc
    if not isinstance(raw, dict):
        raise CapabilityPackError(f"Capability pack manifest must be an object: {manifest_path}")

    schema_version = raw.get("schema_version")
    if schema_version != 1:
        raise CapabilityPackError(f"Unsupported capability pack schema_version: {schema_version!r}")
    pack_id = _required_string(raw, "id", manifest_path)
    if not PACK_ID_RE.fullmatch(pack_id):
        raise CapabilityPackError(f"Capability pack id is invalid: {pack_id!r}")
    if pack_id != pack_dir.name:
        raise CapabilityPackError(
            f"Capability pack id '{pack_id}' must match directory '{pack_dir.name}'."
        )
    version = _required_string(raw, "version", manifest_path)
    if not VERSION_RE.fullmatch(version):
        raise CapabilityPackError(f"Capability pack version must be semantic: {version!r}")
    display_name = _required_string(raw, "display_name", manifest_path)
    default_agent = _required_string(raw, "default_agent", manifest_path)

    artifact_types_raw = raw.get("artifact_types")
    if not isinstance(artifact_types_raw, list) or not artifact_types_raw:
        raise CapabilityPackError(f"Capability pack '{pack_id}' must declare artifact_types.")
    artifact_types = tuple(
        dict.fromkeys(str(item).strip().lower().lstrip(".") for item in artifact_types_raw if str(item).strip())
    )
    if not artifact_types:
        raise CapabilityPackError(f"Capability pack '{pack_id}' has no valid artifact_types.")

    raw_resources = raw.get("resource_paths")
    if not isinstance(raw_resources, dict):
        raise CapabilityPackError(f"Capability pack '{pack_id}' must declare resource_paths.")
    resources: dict[str, tuple[str, ...]] = {}
    for kind in RESOURCE_KINDS:
        values = raw_resources.get(kind, [])
        if not isinstance(values, list):
            raise CapabilityPackError(f"Capability pack '{pack_id}' resource_paths.{kind} must be a list.")
        normalized_paths: list[str] = []
        for value in values:
            relative = str(value or "").strip()
            if not relative:
                continue
            resolved = (pack_dir / relative).resolve()
            try:
                resolved.relative_to(pack_dir)
            except ValueError as exc:
                raise CapabilityPackError(
                    f"Capability pack resource '{relative}' must stay inside its pack directory."
                ) from exc
            if not resolved.is_file():
                raise CapabilityPackError(f"Capability pack resource does not exist: {resolved}")
            normalized_paths.append(resolved.relative_to(pack_dir).as_posix())
        resources[kind] = tuple(dict.fromkeys(normalized_paths))

    quality_profile = raw.get("quality_profile") or {}
    if not isinstance(quality_profile, dict):
        raise CapabilityPackError(f"Capability pack '{pack_id}' quality_profile must be an object.")

    return CapabilityPack(
        pack_id=pack_id,
        version=version,
        display_name=display_name,
        artifact_types=artifact_types,
        default_agent=default_agent,
        pack_dir=pack_dir,
        resource_paths=MappingProxyType(resources),
        quality_profile=MappingProxyType(dict(quality_profile)),
    )


def _required_string(payload: dict[str, Any], key: str, manifest_path: Path) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise CapabilityPackError(f"Capability pack manifest is missing '{key}': {manifest_path}")
    return value
