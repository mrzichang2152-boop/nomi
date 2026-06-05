from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskOrchestrator:
    def __init__(self, now: Callable[[], datetime] = utc_now) -> None:
        self.now = now
        self.task_runs: dict[str, dict[str, Any]] = {}
        self.task_by_idempotency: dict[str, str] = {}
        self.steps: dict[str, dict[str, Any]] = {}
        self.notifications: dict[str, dict[str, Any]] = {}

    def create_task_run(self, task_type: str, idempotency_key: str, steps: list[str]) -> dict[str, Any]:
        if idempotency_key in self.task_by_idempotency:
            return self.task_runs[self.task_by_idempotency[idempotency_key]]
        task_run_id = f"task_{uuid.uuid4().hex}"
        task = {
            "task_run_id": task_run_id,
            "task_type": task_type,
            "idempotency_key": idempotency_key,
            "status": "queued",
            "created_at": self.now(),
            "updated_at": self.now(),
        }
        self.task_runs[task_run_id] = task
        self.task_by_idempotency[idempotency_key] = task_run_id
        for index, step_name in enumerate(steps):
            step_id = f"step_{uuid.uuid4().hex}"
            self.steps[step_id] = {
                "task_step_id": step_id,
                "task_run_id": task_run_id,
                "step_name": step_name,
                "step_order": index,
                "status": "queued",
                "input_json": {},
                "output_json": {},
                "reasoning_summary": "",
                "attempt_count": 0,
                "lease_owner": "",
                "lease_expires_at": None,
                "updated_at": self.now(),
            }
        return task

    def acquire_next_step(self, worker_id: str, lease_seconds: int = 30) -> dict[str, Any] | None:
        now = self.now()
        candidates = sorted(self.steps.values(), key=lambda step: (step["step_order"], step["updated_at"]))
        for step in candidates:
            if step["status"] == "succeeded":
                continue
            lease_expired = step["lease_expires_at"] is not None and step["lease_expires_at"] <= now
            if step["status"] not in {"queued", "running"}:
                continue
            if step["status"] == "running" and not lease_expired:
                continue
            task = self.task_runs[step["task_run_id"]]
            task["status"] = "running"
            task["updated_at"] = now
            step["status"] = "running"
            step["attempt_count"] += 1
            step["lease_owner"] = worker_id
            step["lease_expires_at"] = now + timedelta(seconds=lease_seconds)
            step["updated_at"] = now
            return dict(step)
        return None

    def complete_step(self, task_step_id: str, *, output: dict[str, Any], reason: str = "") -> dict[str, Any]:
        step = self.steps[task_step_id]
        step["status"] = "succeeded"
        step["output_json"] = output
        step["reasoning_summary"] = reason
        step["lease_expires_at"] = None
        step["updated_at"] = self.now()
        task_steps = [item for item in self.steps.values() if item["task_run_id"] == step["task_run_id"]]
        if all(item["status"] == "succeeded" for item in task_steps):
            task = self.task_runs[step["task_run_id"]]
            task["status"] = "succeeded"
            task["updated_at"] = self.now()
        return dict(step)

    def enqueue_notification(
        self,
        *,
        task_run_id: str,
        suggestion_id: str,
        channel: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        notification_id = f"notif_{uuid.uuid4().hex}"
        row = {
            "notification_id": notification_id,
            "task_run_id": task_run_id,
            "suggestion_id": suggestion_id,
            "channel": channel,
            "payload_json": payload,
            "delivery_status": "queued",
            "created_at": self.now(),
            "delivered_at": None,
            "acked_at": None,
            "retry_count": 0,
        }
        self.notifications[notification_id] = row
        return dict(row)

    def ack_notification(self, notification_id: str, *, status: str = "acked") -> dict[str, Any]:
        row = self.notifications[notification_id]
        row["delivery_status"] = status
        row["acked_at"] = self.now()
        return dict(row)

    def replay_unacked(self, *, channel: str) -> list[dict[str, Any]]:
        replayable = []
        for row in self.notifications.values():
            if row["channel"] != channel:
                continue
            if row["acked_at"] is not None:
                continue
            if row["delivery_status"] in {"dismissed", "done", "cancelled"}:
                continue
            row["delivery_status"] = "delivered"
            row["delivered_at"] = self.now()
            replayable.append(dict(row))
        return sorted(replayable, key=lambda item: item["created_at"])


def task_orchestrator_schema_sql() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS task_runs (
          task_run_id TEXT PRIMARY KEY,
          task_type TEXT NOT NULL DEFAULT '',
          source_event_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          pipeline_id TEXT,
          route_type TEXT,
          status TEXT NOT NULL DEFAULT 'queued',
          idempotency_key TEXT NOT NULL DEFAULT '',
          risk_permission TEXT NOT NULL DEFAULT '',
          requires_user_confirmation BOOLEAN NOT NULL DEFAULT FALSE,
          final_user_visible_summary TEXT NOT NULL DEFAULT '',
          payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS task_steps (
          task_step_id TEXT PRIMARY KEY,
          task_run_id TEXT NOT NULL REFERENCES task_runs(task_run_id) ON DELETE CASCADE,
          step_name TEXT NOT NULL DEFAULT '',
          step_order INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'queued',
          input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          reasoning_summary TEXT NOT NULL DEFAULT '',
          error_type TEXT NOT NULL DEFAULT '',
          attempt_count INTEGER NOT NULL DEFAULT 0,
          lease_owner TEXT NOT NULL DEFAULT '',
          lease_expires_at TIMESTAMPTZ,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS notification_outbox (
          notification_id TEXT PRIMARY KEY,
          task_run_id TEXT NOT NULL DEFAULT '',
          suggestion_id TEXT NOT NULL DEFAULT '',
          channel TEXT NOT NULL DEFAULT '',
          payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          delivery_status TEXT NOT NULL DEFAULT 'queued',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          delivered_at TIMESTAMPTZ,
          acked_at TIMESTAMPTZ,
          retry_count INTEGER NOT NULL DEFAULT 0
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS task_runs_idempotency_idx
        ON task_runs(idempotency_key)
        """,
        """
        CREATE INDEX IF NOT EXISTS task_steps_lease_idx
        ON task_steps(status, lease_expires_at, step_order)
        """,
        """
        CREATE INDEX IF NOT EXISTS notification_outbox_replay_idx
        ON notification_outbox(channel, delivery_status, created_at)
        """,
    ]
