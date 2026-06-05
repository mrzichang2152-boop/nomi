from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


SUCCESS_STATUSES = {"succeeded", "completed", "success", "accepted"}
UNSAFE_PERMISSIONS = {"purchase_or_payment", "payment_or_purchase", "external_message", "write", "destructive"}
UNSAFE_EFFECTS = {"purchase", "payment", "pay", "transfer", "book", "send", "send_email", "delete", "submit"}


@dataclass
class WorkflowDistiller:
    min_successes: int = 3
    patterns: dict[str, dict[str, Any]] = field(default_factory=dict)
    pipeline_candidates: dict[str, dict[str, Any]] = field(default_factory=dict)
    evaluation_runs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def observe_trace(self, trace: dict[str, Any]) -> dict[str, Any]:
        normalized_goal = normalize_goal(str(trace.get("normalized_goal") or trace.get("request") or ""))
        pattern_id = stable_id("pattern", normalized_goal)
        pattern = self.patterns.get(pattern_id)
        if pattern is None:
            pattern = new_pattern(pattern_id, normalized_goal, trace)
            self.patterns[pattern_id] = pattern

        succeeded = str(trace.get("status") or "").lower() in SUCCESS_STATUSES
        if succeeded:
            pattern["success_count"] += 1
            merge_observation(pattern, trace)
        else:
            pattern["failure_count"] += 1
        pattern["last_seen_at"] = utc_now()

        candidate = None
        if succeeded and pattern["success_count"] >= self.min_successes:
            candidate = self.pipeline_candidates.get(pattern_id)
            if candidate is None:
                candidate = build_candidate(pattern)
                self.pipeline_candidates[pattern_id] = candidate

        return {"pattern": dict(pattern), "candidate": dict(candidate) if candidate else None}

    def candidates(self) -> list[dict[str, Any]]:
        return [dict(candidate) for candidate in self.pipeline_candidates.values()]

    def record_evaluation(self, candidate_id: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
        candidate = self._candidate_by_id(candidate_id)
        runs = []
        for case in cases:
            run = {
                "run_id": stable_id("eval", f"{candidate_id}:{case.get('test_case_id')}:{len(self.evaluation_runs.get(candidate_id, []))}"),
                "candidate_id": candidate_id,
                "test_case_id": str(case.get("test_case_id") or "unnamed"),
                "status": str(case.get("status") or "pending"),
                "reasonableness_review": str(case.get("reasonableness_review") or ""),
            }
            runs.append(run)
        self.evaluation_runs.setdefault(candidate_id, []).extend(runs)
        passed = bool(runs) and all(run["status"] == "passed" for run in runs)
        candidate["evaluation_status"] = "passed_offline_evaluation" if passed else "failed_offline_evaluation"
        if not passed:
            candidate["promotion_blockers"] = ordered_unique([*candidate.get("promotion_blockers", []), "fix failed evaluation"])
        return dict(candidate)

    def approve_candidate(self, candidate_id: str, *, reviewer_id: str) -> dict[str, Any]:
        candidate = self.enable_candidate(candidate_id, reviewer_id=reviewer_id)
        return dict(candidate)

    def enable_candidate(self, candidate_id: str, *, reviewer_id: str | None = None) -> dict[str, Any]:
        candidate = self._candidate_by_id(candidate_id)
        if candidate.get("evaluation_status") != "passed_offline_evaluation":
            candidate["enable_blocked_reason"] = "offline evaluation must pass before human approval can enable this candidate"
            return dict(candidate)
        if not reviewer_id:
            candidate["enable_blocked_reason"] = "human approval is required before enabling this candidate"
            return dict(candidate)
        candidate["approval_status"] = "approved"
        candidate["approved_by"] = reviewer_id
        candidate["approved_at"] = utc_now()
        candidate["enabled"] = True
        candidate["enable_blocked_reason"] = ""
        candidate["promotion_blockers"] = []
        return dict(candidate)

    def _candidate_by_id(self, candidate_id: str) -> dict[str, Any]:
        for candidate in self.pipeline_candidates.values():
            if candidate.get("candidate_id") == candidate_id:
                return candidate
        raise KeyError(candidate_id)


def normalize_goal(value: str) -> str:
    text = value.strip().lower()
    if not text:
        return "unknown_workflow"
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[\d]+", "N", text)
    text = re.sub(r"[^0-9a-zA-Z_\u4e00-\u9fff]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown_workflow"


def stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_pattern(pattern_id: str, normalized_goal: str, trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "pattern_id": pattern_id,
        "source": str(trace.get("source") or "unknown"),
        "normalized_goal": normalized_goal,
        "trigger_features": trigger_features(trace),
        "required_slots": sorted_unique(trace.get("required_slots")),
        "observed_steps": ordered_unique(trace.get("steps")),
        "allowed_tools": sorted_unique(trace.get("tools")),
        "forbidden_tools": sorted_unique(trace.get("forbidden_tools") or trace.get("external_effects")),
        "risk_permission": str(trace.get("risk_permission") or "read_only"),
        "success_count": 0,
        "failure_count": 0,
        "last_seen_at": utc_now(),
    }


def merge_observation(pattern: dict[str, Any], trace: dict[str, Any]) -> None:
    pattern["required_slots"] = sorted_unique([*pattern.get("required_slots", []), *(trace.get("required_slots") or [])])
    pattern["observed_steps"] = ordered_unique([*pattern.get("observed_steps", []), *(trace.get("steps") or [])])
    pattern["allowed_tools"] = sorted_unique([*pattern.get("allowed_tools", []), *(trace.get("tools") or [])])
    pattern["forbidden_tools"] = sorted_unique(
        [*pattern.get("forbidden_tools", []), *(trace.get("forbidden_tools") or []), *(trace.get("external_effects") or [])]
    )
    risk = str(trace.get("risk_permission") or pattern.get("risk_permission") or "read_only")
    if risk in UNSAFE_PERMISSIONS:
        pattern["risk_permission"] = risk
    pattern["trigger_features"] = {
        **pattern.get("trigger_features", {}),
        **trigger_features(trace),
    }


def build_candidate(pattern: dict[str, Any]) -> dict[str, Any]:
    risk_permission = str(pattern.get("risk_permission") or "read_only")
    forbidden_tools = sorted_unique(pattern.get("forbidden_tools"))
    unsafe_effects = sorted(set(forbidden_tools) & UNSAFE_EFFECTS)
    unsafe = risk_permission in UNSAFE_PERMISSIONS or bool(unsafe_effects)
    candidate_id = stable_id("candidate", pattern["pattern_id"])
    proposed_pipeline_id = f"candidate_{pattern['normalized_goal']}_pipeline"
    return {
        "candidate_id": candidate_id,
        "pattern_id": pattern["pattern_id"],
        "normalized_goal": pattern["normalized_goal"],
        "proposed_pipeline_id": proposed_pipeline_id,
        "proposed_steps": list(pattern.get("observed_steps") or []),
        "input_schema": {"required_slots": list(pattern.get("required_slots") or [])},
        "output_schema": {"type": "assistant_task_result", "must_include_trace": True},
        "confirmation_policy": {
            "permission": risk_permission,
            "final_user_confirmation": unsafe,
            "external_effects_blocked_until_confirmation": unsafe,
        },
        "writeback_targets": ["assistant_turns", "task_trace", "workflow_patterns"],
        "evaluation_status": "needs_offline_evaluation",
        "approval_status": "pending_review",
        "enabled": False,
        "forbidden_tools": forbidden_tools,
        "promotion_blockers": ["offline evaluation", "human approval"],
        "reasonableness_review": reasonableness_review(pattern, unsafe, unsafe_effects),
    }


def reasonableness_review(pattern: dict[str, Any], unsafe: bool, unsafe_effects: list[str]) -> str:
    if unsafe:
        return (
            "unsafe external effect detected; candidate may be useful, but it must stay disabled until "
            f"offline evaluation and human approval. Effects: {', '.join(unsafe_effects) or pattern.get('risk_permission')}."
        )
    return "stable repeated successful read-only workflow; candidate is disabled pending offline evaluation and human approval."


def trigger_features(trace: dict[str, Any]) -> dict[str, Any]:
    request = str(trace.get("request") or "")
    return {
        "source": str(trace.get("source") or "unknown"),
        "has_external_effects": bool(trace.get("external_effects")),
        "request_length": len(request),
    }


def sorted_unique(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    result = {str(value).strip() for value in values if str(value).strip()}
    return sorted(result)


def ordered_unique(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    seen = set()
    result = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def workflow_distillation_schema_sql() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS workflow_patterns (
          pattern_id TEXT PRIMARY KEY,
          source TEXT NOT NULL DEFAULT '',
          normalized_goal TEXT NOT NULL,
          trigger_features JSONB NOT NULL DEFAULT '{}'::jsonb,
          required_slots TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          observed_steps TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          allowed_tools TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          forbidden_tools TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          risk_permission TEXT NOT NULL DEFAULT 'read_only',
          success_count INTEGER NOT NULL DEFAULT 0,
          failure_count INTEGER NOT NULL DEFAULT 0,
          last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pipeline_candidates (
          candidate_id TEXT PRIMARY KEY,
          pattern_id TEXT NOT NULL REFERENCES workflow_patterns(pattern_id) ON DELETE CASCADE,
          proposed_pipeline_id TEXT NOT NULL,
          proposed_steps TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          input_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
          output_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
          confirmation_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
          writeback_targets TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          evaluation_status TEXT NOT NULL DEFAULT 'needs_offline_evaluation',
          approval_status TEXT NOT NULL DEFAULT 'pending_review',
          approved_by TEXT NOT NULL DEFAULT '',
          approved_at TIMESTAMPTZ,
          enabled BOOLEAN NOT NULL DEFAULT FALSE,
          reasonableness_review TEXT NOT NULL DEFAULT '',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS skill_evaluation_runs (
          run_id TEXT PRIMARY KEY,
          candidate_id TEXT NOT NULL REFERENCES pipeline_candidates(candidate_id) ON DELETE CASCADE,
          test_case_id TEXT NOT NULL,
          input_event_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          expected_route JSONB NOT NULL DEFAULT '{}'::jsonb,
          expected_slots JSONB NOT NULL DEFAULT '{}'::jsonb,
          expected_user_message TEXT NOT NULL DEFAULT '',
          actual_result JSONB NOT NULL DEFAULT '{}'::jsonb,
          reasonableness_review TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'pending',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS workflow_patterns_goal_idx
        ON workflow_patterns(normalized_goal, last_seen_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS pipeline_candidates_status_idx
        ON pipeline_candidates(evaluation_status, approval_status, enabled)
        """,
        """
        CREATE INDEX IF NOT EXISTS skill_evaluation_runs_candidate_idx
        ON skill_evaluation_runs(candidate_id, created_at DESC)
        """,
    ]
