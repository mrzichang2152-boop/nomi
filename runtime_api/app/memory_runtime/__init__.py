from __future__ import annotations

try:
    from app.memory_runtime.schema import memory_runtime_phase1_schema_sql
except ModuleNotFoundError:  # pragma: no cover - local package import fallback
    from runtime_api.app.memory_runtime.schema import memory_runtime_phase1_schema_sql

__all__ = ["memory_runtime_phase1_schema_sql"]
