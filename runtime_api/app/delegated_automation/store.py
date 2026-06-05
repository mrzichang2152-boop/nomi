from __future__ import annotations

from dataclasses import replace

from app.delegated_automation.models import DelegationGrant, ExecutionTrace, TargetManifest


class InMemoryDelegatedAutomationStore:
    def __init__(self) -> None:
        self._grants: dict[str, DelegationGrant] = {}
        self._manifests: dict[str, TargetManifest] = {}
        self._traces: list[ExecutionTrace] = []

    def clear(self) -> None:
        self._grants.clear()
        self._manifests.clear()
        self._traces.clear()

    def upsert_grant(self, grant: DelegationGrant) -> DelegationGrant:
        self._grants[grant.grant_id] = grant
        return grant

    def get_grant(self, grant_id: str) -> DelegationGrant | None:
        return self._grants.get(grant_id)

    def list_grants(self) -> list[DelegationGrant]:
        return sorted(self._grants.values(), key=lambda grant: grant.created_at, reverse=True)

    def pause_grant(self, grant_id: str, reason: str = "") -> DelegationGrant:
        grant = self._grants[grant_id]
        metadata = dict(grant.metadata)
        metadata["pause_reason"] = reason
        paused = replace(grant, status="paused", metadata=metadata)
        self._grants[grant_id] = paused
        return paused

    def upsert_manifest(self, manifest: TargetManifest) -> TargetManifest:
        self._manifests[manifest.manifest_id] = manifest
        return manifest

    def get_manifest(self, manifest_id: str) -> TargetManifest | None:
        return self._manifests.get(manifest_id)

    def append_trace(self, trace: ExecutionTrace) -> ExecutionTrace:
        self._traces.append(trace)
        return trace

    def traces_for_grant(self, grant_id: str) -> list[ExecutionTrace]:
        return [trace for trace in self._traces if trace.grant_id == grant_id]

    def list_traces(self, limit: int = 100) -> list[ExecutionTrace]:
        return list(reversed(self._traces))[:limit]
