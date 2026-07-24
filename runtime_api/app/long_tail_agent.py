from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from psycopg.types.json import Jsonb


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LongTailEventStore:
    """In-memory V2 event store used by tests and local runtime primitives."""

    def __init__(self) -> None:
        self.events_by_task: dict[str, list[dict[str, Any]]] = {}
        self.events_by_idempotency: dict[tuple[str, str], dict[str, Any]] = {}

    def append_event(
        self,
        *,
        task_id: str,
        event_type: str,
        payload: dict[str, Any],
        step_id: str | None = None,
        node_name: str = "",
        idempotency_key: str | None = None,
        redaction_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if idempotency_key:
            existing = self.events_by_idempotency.get((task_id, idempotency_key))
            if existing is not None:
                return dict(existing)

        task_events = self.events_by_task.setdefault(task_id, [])
        event = {
            "event_id": f"evt_{uuid.uuid4().hex}",
            "task_id": task_id,
            "sequence": len(task_events) + 1,
            "event_type": event_type,
            "step_id": step_id,
            "node_name": node_name,
            "payload": dict(payload),
            "redaction_summary": dict(redaction_summary or {}),
            "idempotency_key": idempotency_key or "",
            "created_at": utc_now_iso(),
        }
        task_events.append(event)
        if idempotency_key:
            self.events_by_idempotency[(task_id, idempotency_key)] = event
        return dict(event)

    def task_events(self, task_id: str) -> list[dict[str, Any]]:
        return [dict(event) for event in self.events_by_task.get(task_id, [])]

    def rebuild_state(self, task_id: str) -> dict[str, Any]:
        state: dict[str, Any] = {
            "task_id": task_id,
            "status": "unknown",
            "current_node": "",
            "plan_version": None,
            "original_goal": "",
            "completed_steps": [],
            "event_count": 0,
        }
        for event in self.task_events(task_id):
            state["event_count"] += 1
            payload = event["payload"]
            event_type = event["event_type"]
            if event_type == "task.created":
                state["status"] = "created"
                state["current_node"] = "created"
                state["original_goal"] = str(payload.get("original_goal") or "")
            elif event_type == "plan.validated":
                state["status"] = "running"
                state["plan_version"] = payload.get("plan_version")
                state["current_node"] = str(payload.get("current_node") or "select_step")
            elif event_type == "checkpoint.restored":
                state["status"] = "running"
                state["current_node"] = str(payload.get("current_node") or state["current_node"])
            elif event_type == "step.verified" and payload.get("status") == "passed":
                completed = (payload.get("memory_patch") or {}).get("completed_step")
                if completed:
                    state["completed_steps"].append(dict(completed))
            elif event_type == "task.completed":
                state["status"] = "completed"
                state["current_node"] = "completed"
        return state


class PostgresLongTailEventStore(LongTailEventStore):
    """Postgres-backed append-only event store for long-tail tasks."""

    def __init__(self, *, connection_factory: Callable[[], Any], materialize_events: bool = False) -> None:
        self.connection_factory = connection_factory
        self.materialize_events = materialize_events

    def append_event(
        self,
        *,
        task_id: str,
        event_type: str,
        payload: dict[str, Any],
        step_id: str | None = None,
        node_name: str = "",
        idempotency_key: str | None = None,
        redaction_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        conn = self.connection_factory()
        if idempotency_key:
            existing = conn.execute(
                """
                SELECT id, task_id, sequence, event_type, step_id, node_name,
                       payload_json, redaction_summary_json, idempotency_key, created_at
                FROM long_tail_task_events
                WHERE task_id = %s AND idempotency_key = %s
                """,
                (task_id, idempotency_key),
            ).fetchone()
            if existing:
                return self._event_from_row(existing)

        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (task_id,))
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM long_tail_task_events WHERE task_id = %s",
            (task_id,),
        ).fetchone()[0]
        event_id = f"evt_{uuid.uuid4().hex}"
        conn.execute(
            """
            INSERT INTO long_tail_task_events (
              id, task_id, sequence, event_type, step_id, node_name,
              payload_json, redaction_summary_json, idempotency_key
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event_id,
                task_id,
                next_sequence,
                event_type,
                step_id,
                node_name,
                Jsonb(dict(payload)),
                Jsonb(dict(redaction_summary or {})),
                idempotency_key,
            ),
        )
        event = {
            "event_id": event_id,
            "task_id": task_id,
            "sequence": int(next_sequence),
            "event_type": event_type,
            "step_id": step_id,
            "node_name": node_name,
            "payload": dict(payload),
            "redaction_summary": dict(redaction_summary or {}),
            "idempotency_key": idempotency_key or "",
            "created_at": utc_now_iso(),
        }
        if self.materialize_events:
            self._materialize_event(conn, event)
        conn.commit()
        return event

    def task_events(self, task_id: str) -> list[dict[str, Any]]:
        conn = self.connection_factory()
        rows = conn.execute(
            """
            SELECT id, task_id, sequence, event_type, step_id, node_name,
                   payload_json, redaction_summary_json, idempotency_key, created_at
            FROM long_tail_task_events
            WHERE task_id = %s
            ORDER BY sequence ASC
            """,
            (task_id,),
        ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def _event_from_row(self, row: Any) -> dict[str, Any]:
        return {
            "event_id": row[0],
            "task_id": row[1],
            "sequence": int(row[2]),
            "event_type": row[3],
            "step_id": row[4],
            "node_name": row[5] or "",
            "payload": dict(row[6] or {}),
            "redaction_summary": dict(row[7] or {}),
            "idempotency_key": row[8] or "",
            "created_at": row[9].isoformat() if hasattr(row[9], "isoformat") else str(row[9]),
        }

    def _materialize_event(self, conn: Any, event: dict[str, Any]) -> None:
        task_id = event["task_id"]
        event_type = event["event_type"]
        step_id = event.get("step_id")
        payload = dict(event.get("payload") or {})

        if event_type == "task.created":
            conn.execute(
                """
                INSERT INTO long_tail_task_runs (
                  id, original_goal, status, current_node, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, now(), now())
                ON CONFLICT (id) DO UPDATE SET
                  original_goal = EXCLUDED.original_goal,
                  status = EXCLUDED.status,
                  current_node = EXCLUDED.current_node,
                  updated_at = now()
                """,
                (task_id, str(payload.get("original_goal") or ""), "created", "created"),
            )
        elif event_type == "route.decided":
            conn.execute(
                """
                UPDATE long_tail_task_runs
                SET route_decision = %s, route_trace_id = %s, updated_at = now()
                WHERE id = %s
                """,
                (Jsonb(payload), str(payload.get("route_trace_id") or ""), task_id),
            )
        elif event_type == "plan.proposed":
            plan_version = int(payload.get("plan_version") or 1)
            conn.execute(
                """
                INSERT INTO long_tail_task_plans (
                  id, task_id, version, plan_json, validation_status, validation_report_json
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  plan_json = EXCLUDED.plan_json
                """,
                (
                    f"plan_{task_id}_{plan_version}",
                    task_id,
                    plan_version,
                    Jsonb(dict(payload.get("plan") or {})),
                    "proposed",
                    Jsonb({}),
                ),
            )
        elif event_type == "plan.validated":
            plan_version = int(payload.get("plan_version") or 1)
            validation_report = dict(payload.get("validation_report") or {})
            validation_status = str(validation_report.get("status") or "")
            task_status = "running" if validation_status == "valid" else "blocked"
            current_node = str(payload.get("current_node") or "")
            conn.execute(
                """
                UPDATE long_tail_task_runs
                SET status = %s, current_node = %s, plan_version = %s, updated_at = now()
                WHERE id = %s
                """,
                (task_status, current_node, plan_version, task_id),
            )
            conn.execute(
                """
                UPDATE long_tail_task_plans
                SET validation_status = %s, validation_report_json = %s
                WHERE id = %s
                """,
                (validation_status, Jsonb(validation_report), f"plan_{task_id}_{plan_version}"),
            )
        elif event_type == "step_packet.built":
            packet = dict(payload.get("packet") or {})
            packet_step_id = str(packet.get("step_id") or step_id or "")
            conn.execute(
                """
                INSERT INTO long_tail_step_runs (
                  id, task_id, step_id, attempt_number, executor_adapter,
                  step_packet_json, status, started_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (id) DO UPDATE SET
                  step_packet_json = EXCLUDED.step_packet_json,
                  status = EXCLUDED.status
                """,
                (
                    f"step_{task_id}_{packet_step_id}_1",
                    task_id,
                    packet_step_id,
                    1,
                    "",
                    Jsonb(packet),
                    "awaiting_executor",
                ),
            )
            conn.execute(
                "UPDATE long_tail_task_runs SET current_node = %s, current_step_id = %s, updated_at = now() WHERE id = %s",
                ("awaiting_executor", packet_step_id, task_id),
            )
        elif event_type == "executor.action_requested":
            action = dict(payload.get("action_request") or {})
            action_id = str(action.get("action_id") or f"act_{uuid.uuid4().hex}")
            conn.execute(
                """
                INSERT INTO long_tail_action_requests (
                  id, task_id, step_id, action_id, adapter, action_type,
                  target_json, input_summary_json, risk_level, expected_effect,
                  requires_confirmation_token, idempotency_key
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  target_json = EXCLUDED.target_json,
                  input_summary_json = EXCLUDED.input_summary_json
                """,
                (
                    action_id,
                    task_id,
                    str(action.get("step_id") or step_id or ""),
                    action_id,
                    str(action.get("adapter") or ""),
                    str(action.get("action_type") or ""),
                    Jsonb(dict(action.get("target") or {})),
                    Jsonb(dict(action.get("input_summary") or {})),
                    str(action.get("risk_level") or ""),
                    str(action.get("expected_effect") or ""),
                    bool(action.get("requires_confirmation_token")),
                    str(action.get("idempotency_key") or ""),
                ),
            )
        elif event_type == "policy.checked":
            report = dict(payload.get("policy_report") or {})
            action_id = str(payload.get("action_request_id") or report.get("action_id") or "")
            report_id = f"policy_{event['event_id']}"
            conn.execute(
                """
                INSERT INTO long_tail_policy_reports (
                  id, task_id, step_id, action_id, status, reason, requires_confirmation
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    report_id,
                    task_id,
                    step_id,
                    action_id,
                    str(report.get("status") or ""),
                    str(report.get("reason") or ""),
                    bool(report.get("requires_confirmation")),
                ),
            )
            conn.execute(
                """
                UPDATE long_tail_action_requests
                SET policy_status = %s, policy_report_id = %s
                WHERE action_id = %s
                """,
                (str(report.get("status") or ""), report_id, action_id),
            )
        elif event_type == "step.result_returned":
            result = dict(payload.get("executor_result") or {})
            conn.execute(
                """
                UPDATE long_tail_step_runs
                SET status = %s, result_json = %s, completed_at = now()
                WHERE task_id = %s AND step_id = %s
                """,
                (str(result.get("status") or "returned"), Jsonb(result), task_id, step_id),
            )
        elif event_type == "step.verified":
            conn.execute(
                """
                UPDATE long_tail_step_runs
                SET status = %s, verifier_report_json = %s
                WHERE task_id = %s AND step_id = %s
                """,
                (str(payload.get("status") or ""), Jsonb(payload), task_id, step_id),
            )
        elif event_type == "memory.patch_applied":
            memory_patch = dict(payload.get("memory_patch") or {})
            conn.execute(
                """
                INSERT INTO long_tail_task_memory (
                  id, task_id, memory_type, step_id, payload_json, payload_hash
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    f"memory_{event['event_id']}",
                    task_id,
                    "step_memory_patch",
                    step_id,
                    Jsonb(memory_patch),
                    hashlib.sha256(
                        json.dumps(memory_patch, ensure_ascii=False, sort_keys=True).encode("utf-8")
                    ).hexdigest(),
                ),
            )
        elif event_type == "checkpoint.saved":
            conn.execute(
                """
                INSERT INTO long_tail_checkpoints (
                  id, task_id, after_event_sequence, after_step_id,
                  checkpoint_payload_json, restore_policy
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    f"checkpoint_{event['event_id']}",
                    task_id,
                    int(event.get("sequence") or 0),
                    step_id,
                    Jsonb(payload),
                    "event_log_replay",
                ),
            )
        elif event_type == "human_input.requested":
            question = str(payload.get("question") or "")
            options = list(payload.get("options") or [])
            human_input_id = f"human_{event['event_id']}"
            conn.execute(
                """
                INSERT INTO long_tail_human_inputs (
                  id, task_id, step_id, input_type, question, options_json, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  question = EXCLUDED.question,
                  options_json = EXCLUDED.options_json,
                  status = EXCLUDED.status
                """,
                (
                    human_input_id,
                    task_id,
                    step_id,
                    str(payload.get("input_type") or "clarification"),
                    question,
                    Jsonb(options),
                    "waiting",
                ),
            )
            conn.execute(
                "UPDATE long_tail_task_runs SET current_node = %s, current_step_id = %s, updated_at = now() WHERE id = %s",
                ("waiting_for_human_input", step_id, task_id),
            )
        elif event_type == "human_input.received":
            conn.execute(
                """
                UPDATE long_tail_human_inputs
                SET status = %s, response_json = %s, resolved_at = now()
                WHERE task_id = %s
                  AND COALESCE(step_id, '') = COALESCE(%s, '')
                  AND input_type = %s
                  AND status = 'waiting'
                """,
                (
                    "resolved",
                    Jsonb(dict(payload.get("response") or {})),
                    task_id,
                    step_id,
                    str(payload.get("input_type") or "user_response"),
                ),
            )
            conn.execute(
                """
                INSERT INTO long_tail_human_inputs (
                  id, task_id, step_id, input_type, status, response_json, resolved_at
                )
                SELECT %s, %s, %s, %s, %s, %s, now()
                WHERE NOT EXISTS (
                  SELECT 1
                  FROM long_tail_human_inputs
                  WHERE task_id = %s
                    AND COALESCE(step_id, '') = COALESCE(%s, '')
                    AND input_type = %s
                    AND status = 'resolved'
                )
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    f"human_{event['event_id']}",
                    task_id,
                    step_id,
                    str(payload.get("input_type") or "user_response"),
                    "resolved",
                    Jsonb(dict(payload.get("response") or {})),
                    task_id,
                    step_id,
                    str(payload.get("input_type") or "user_response"),
                ),
            )
            conn.execute(
                "UPDATE long_tail_task_runs SET current_node = %s, updated_at = now() WHERE id = %s",
                ("select_step", task_id),
            )
        elif event_type == "external_effect.proposed":
            effect_id = str(payload.get("effect_id") or f"effect_{event['event_id']}")
            conn.execute(
                """
                INSERT INTO long_tail_external_effects (
                  id, task_id, step_id, action_request_id, effect_type, status, proposal_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  status = EXCLUDED.status,
                  proposal_json = EXCLUDED.proposal_json,
                  updated_at = now()
                """,
                (
                    effect_id,
                    task_id,
                    step_id,
                    str(payload.get("action_request_id") or ""),
                    str(payload.get("effect_type") or ""),
                    str(payload.get("status") or "waiting_for_confirmation"),
                    Jsonb(dict(payload.get("proposal") or {})),
                ),
            )
        elif event_type == "external_effect.confirmed":
            conn.execute(
                """
                UPDATE long_tail_external_effects
                SET status = %s, confirmation_event_id = %s, updated_at = now()
                WHERE id = %s
                """,
                (str(payload.get("status") or "confirmed"), event["event_id"], str(payload.get("effect_id") or "")),
            )
        elif event_type == "external_effect.executed":
            conn.execute(
                """
                UPDATE long_tail_external_effects
                SET status = %s, execution_event_id = %s, updated_at = now()
                WHERE id = %s
                """,
                (str(payload.get("status") or "executed"), event["event_id"], str(payload.get("effect_id") or "")),
            )
        elif event_type == "external_effect.compensation_proposed":
            conn.execute(
                """
                UPDATE long_tail_external_effects
                SET status = %s, compensation_proposal_json = %s, updated_at = now()
                WHERE id = %s
                """,
                (
                    str(payload.get("status") or "waiting_for_compensation_confirmation"),
                    Jsonb(dict(payload.get("compensation_proposal") or {})),
                    str(payload.get("effect_id") or ""),
                ),
            )


@dataclass(frozen=True)
class ActionRequest:
    action_id: str
    task_id: str
    step_id: str
    adapter: str
    action_type: str
    target: dict[str, Any]
    input_summary: dict[str, Any]
    risk_level: str
    expected_effect: str
    idempotency_key: str
    requires_confirmation_token: bool = False
    confirmation_token: str | None = None


@dataclass
class PolicyGate:
    hard_blocked_actions: set[str] = field(
        default_factory=lambda: {
            "browser.submit",
            "browser.click_write",
            "payment.transfer",
            "purchase.submit",
            "booking.confirm",
            "account.modify",
            "data.delete",
            "archive_or_destructive_update",
        }
    )
    confirmation_actions: set[str] = field(
        default_factory=lambda: {
            "message.send",
            "email.send",
            "payment.transfer",
            "purchase.submit",
            "booking.confirm",
        }
    )

    def evaluate(self, action: ActionRequest, *, allowed_actions: set[str]) -> dict[str, Any]:
        if action.action_type not in allowed_actions:
            return self._report(
                action,
                status="blocked",
                reason=f"{action.action_type} is outside allowed_actions.",
                requires_confirmation=False,
                may_execute=False,
            )
        if action.action_type in self.hard_blocked_actions:
            return self._report(
                action,
                status="blocked",
                reason=f"{action.action_type} is blocked before adapter execution.",
                requires_confirmation=False,
                may_execute=False,
            )
        needs_confirmation = (
            action.action_type in self.confirmation_actions
            or action.requires_confirmation_token
            or action.risk_level
            in {"external_write", "external_message", "purchase_or_payment", "destructive_or_account"}
        )
        if needs_confirmation and not action.confirmation_token:
            return self._report(
                action,
                status="requires_confirmation",
                reason=f"{action.action_type} requires a prior user confirmation event.",
                requires_confirmation=True,
                may_execute=False,
            )
        return self._report(
            action,
            status="allowed",
            reason=f"{action.action_type} is allowed by the current step policy.",
            requires_confirmation=False,
            may_execute=True,
        )

    def _report(
        self,
        action: ActionRequest,
        *,
        status: str,
        reason: str,
        requires_confirmation: bool,
        may_execute: bool,
    ) -> dict[str, Any]:
        return {
            "action_id": action.action_id,
            "task_id": action.task_id,
            "step_id": action.step_id,
            "adapter": action.adapter,
            "action_type": action.action_type,
            "status": status,
            "reason": reason,
            "requires_confirmation": requires_confirmation,
            "may_execute": may_execute,
        }


class StepVerifier:
    evidence_types_by_step_type: dict[str, set[str]] = {
        "browser_page_read": {
            "browser_observation",
            "dom_excerpt",
            "screenshot",
            "screenshot_hash",
            "accessibility_tree_excerpt",
        },
        "browser_field_fill": {
            "field_observation",
            "browser_observation",
            "dom_excerpt",
            "screenshot_hash",
        },
        "composio_read": {"provider_response", "tool_result", "scoped_result_summary"},
        "draft_creation": {"draft_payload_hash", "draft_id"},
        "external_effect_confirmation": {"external_effect_event", "confirmation_event"},
        "external_effect_execution": {"external_effect_event", "execution_event"},
        "local_memory_retrieval": {"source_ids", "retrieval_scope", "excluded_scope_summary"},
        "local_task_memory_write": {"event_id", "memory_patch_hash", "checkpoint_id"},
    }

    def verify(self, step: dict[str, Any], executor_result: dict[str, Any]) -> dict[str, Any]:
        expected_outputs = list(step.get("expected_outputs") or [])
        outputs = dict(executor_result.get("outputs") or {})
        missing_outputs = [key for key in expected_outputs if self._is_empty_output(outputs.get(key))]
        if missing_outputs:
            return {
                "status": "retry",
                "score": 0.3,
                "missing_outputs": missing_outputs,
                "violations": [],
                "reason": "Required outputs are missing.",
                "memory_patch": {},
            }

        forbidden_report = self._forbidden_action_report(step, executor_result)
        if forbidden_report is not None:
            return forbidden_report

        evidence = list(executor_result.get("evidence") or [])
        allowed_evidence_types = self.evidence_types_by_step_type.get(
            str(step.get("step_type") or ""), {"provider_response", "tool_result", "source_ids"}
        )
        has_independent_evidence = any(item.get("type") in allowed_evidence_types for item in evidence)
        if not has_independent_evidence:
            return {
                "status": "retry",
                "score": 0.4,
                "missing_outputs": [],
                "violations": [],
                "reason": "Step cannot pass without independent evidence.",
                "memory_patch": {},
            }

        step_type_report = self._verify_step_type_evidence(step, executor_result, evidence)
        if step_type_report is not None:
            return step_type_report

        return {
            "status": "passed",
            "score": 0.88,
            "missing_outputs": [],
            "violations": [],
            "reason": "Executor output matches required outputs and independent evidence.",
            "memory_patch": {
                "completed_step": {
                    "step_id": str(step.get("step_id") or ""),
                    "summary": str(executor_result.get("summary") or ""),
                },
                "artifacts": [],
            },
        }

    def _is_empty_output(self, value: Any) -> bool:
        return value is None or value == "" or value == [] or value == ()

    def _forbidden_action_report(
        self,
        step: dict[str, Any],
        executor_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        forbidden_actions = {str(action) for action in list(step.get("forbidden_actions") or []) if action}
        if not forbidden_actions:
            return None
        action_events = list(executor_result.get("action_events") or [])
        executed_forbidden: list[str] = []
        for event in action_events:
            action_type = str(event.get("action_type") or "")
            status = str(event.get("status") or "").lower()
            if action_type in forbidden_actions and status in {"success", "executed", "completed", "sent"}:
                executed_forbidden.append(action_type)
        if not executed_forbidden:
            return None
        violations = [f"forbidden action executed: {action}" for action in executed_forbidden]
        return {
            "status": "blocked",
            "score": 0.0,
            "missing_outputs": [],
            "violations": violations,
            "reason": "Step evidence shows a forbidden external action was executed.",
            "memory_patch": {},
        }

    def _verify_step_type_evidence(
        self,
        step: dict[str, Any],
        executor_result: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        step_type = str(step.get("step_type") or "")
        outputs = dict(executor_result.get("outputs") or {})
        if step_type == "browser_page_read":
            return self._verify_browser_page_read(outputs, evidence)
        if step_type == "draft_creation":
            return self._verify_draft_creation(outputs, evidence)
        if step_type == "external_effect_confirmation":
            return self._verify_external_effect_confirmation(outputs, evidence)
        if step_type == "external_effect_execution":
            return self._verify_external_effect_execution(outputs, evidence)
        return None

    def _retry_report(self, *, reason: str, violations: list[str] | None = None, score: float = 0.45) -> dict[str, Any]:
        return {
            "status": "retry",
            "score": score,
            "missing_outputs": [],
            "violations": list(violations or []),
            "reason": reason,
            "memory_patch": {},
        }

    def _evidence_texts(self, evidence: list[dict[str, Any]], *, types: set[str] | None = None) -> list[str]:
        texts: list[str] = []
        for item in evidence:
            if types is not None and item.get("type") not in types:
                continue
            parts = [
                item.get("label"),
                item.get("value"),
                item.get("text"),
                item.get("content"),
                item.get("title"),
                item.get("url"),
            ]
            compact = " ".join(str(part) for part in parts if part not in (None, ""))
            if compact:
                texts.append(compact.lower())
        return texts

    def _verify_browser_page_read(
        self,
        outputs: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        evidence_texts = self._evidence_texts(evidence)
        page_title = str(outputs.get("page_title") or "").strip()
        if page_title:
            title_evidence = self._evidence_texts(
                evidence,
                types={"browser_observation", "dom_excerpt", "accessibility_tree_excerpt"},
            )
            if title_evidence and not any(page_title.lower() in text for text in title_evidence):
                return self._retry_report(
                    reason="browser page evidence conflicts with the reported page_title.",
                    violations=["page_title evidence mismatch"],
                    score=0.35,
                )
        field_list = outputs.get("field_list")
        if isinstance(field_list, list) and field_list:
            missing_fields = [
                str(field)
                for field in field_list
                if field and not any(str(field).lower() in text for text in evidence_texts)
            ]
            if missing_fields:
                return self._retry_report(
                    reason="browser page evidence does not show all reported fields.",
                    violations=[f"field evidence missing: {field}" for field in missing_fields],
                    score=0.4,
                )
        return None

    def _verify_draft_creation(
        self,
        outputs: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        has_draft_identity = bool(outputs.get("draft_id")) or any(
            item.get("type") in {"draft_payload_hash", "draft_id"} and (item.get("value") or item.get("draft_id"))
            for item in evidence
        )
        has_draft_content = bool(outputs.get("draft_body") or outputs.get("draft_subject"))
        if not (has_draft_identity and has_draft_content):
            return self._retry_report(
                reason="draft creation needs a draft id or payload hash plus visible draft content.",
                violations=["draft evidence incomplete"],
                score=0.4,
            )
        return None

    def _verify_external_effect_confirmation(
        self,
        outputs: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        effect_id = str(outputs.get("effect_id") or "").strip()
        confirmation_status = str(outputs.get("confirmation_status") or "").strip()
        for item in evidence:
            if item.get("type") not in {"external_effect_event", "confirmation_event"}:
                continue
            if effect_id and str(item.get("effect_id") or "") != effect_id:
                continue
            event_type = str(item.get("event_type") or "")
            status = str(item.get("status") or "")
            if event_type == "external_effect.confirmed" and status == "confirmed" and confirmation_status == "confirmed":
                return None
        return self._retry_report(
            reason="external effect confirmation needs a matching confirmed event for the exact effect.",
            violations=["external effect confirmation evidence missing"],
            score=0.35,
        )

    def _verify_external_effect_execution(
        self,
        outputs: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        effect_id = str(outputs.get("effect_id") or "").strip()
        for item in evidence:
            if item.get("type") not in {"external_effect_event", "execution_event"}:
                continue
            if effect_id and str(item.get("effect_id") or "") != effect_id:
                continue
            if str(item.get("event_type") or "") == "external_effect.executed" and str(item.get("status") or "") == "executed":
                if item.get("confirmation_event_id") or item.get("confirmed_before_execution"):
                    return None
        return self._retry_report(
            reason="external effect execution needs executed evidence linked to a prior confirmation.",
            violations=["external effect execution evidence incomplete"],
            score=0.35,
        )


class LongTailLeaseManager:
    """Small local lease manager for V2 restart/recovery tests.

    Postgres will be the durable source in production; this class defines the
    ownership semantics the persistent implementation must preserve.
    """

    def __init__(self) -> None:
        self.leases_by_task: dict[str, dict[str, Any]] = {}

    def claim_task(
        self,
        task_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 30,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        existing = self.leases_by_task.get(task_id)
        if (
            existing
            and existing.get("status") == "leased"
            and existing.get("lease_expires_at") is not None
            and existing["lease_expires_at"] > now
        ):
            return {
                "task_id": task_id,
                "acquired": False,
                "reason": "active_lease",
                "lease_owner": existing["lease_owner"],
                "lease_expires_at": existing["lease_expires_at"],
                "attempt": existing["attempt"],
            }

        attempt = int(existing.get("attempt", 0)) + 1 if existing else 1
        lease = {
            "task_id": task_id,
            "status": "leased",
            "lease_owner": worker_id,
            "lease_expires_at": now + timedelta(seconds=lease_seconds),
            "attempt": attempt,
            "acquired_at": now,
        }
        self.leases_by_task[task_id] = lease
        return {"acquired": True, **dict(lease)}

    def release_task(self, task_id: str, *, worker_id: str) -> dict[str, Any]:
        existing = self.leases_by_task.get(task_id)
        if not existing:
            return {"task_id": task_id, "status": "not_found", "released": False}
        if existing.get("lease_owner") != worker_id:
            return {
                "task_id": task_id,
                "status": "not_owner",
                "released": False,
                "lease_owner": existing.get("lease_owner"),
            }
        existing["status"] = "released"
        existing["lease_owner"] = ""
        existing["lease_expires_at"] = None
        return {"task_id": task_id, "status": "released", "released": True}


class PostgresLongTailLeaseManager:
    def __init__(self, *, connection_factory: Callable[[], Any]) -> None:
        self.connection_factory = connection_factory

    def claim_task(
        self,
        task_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 30,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        conn = self.connection_factory()
        row = conn.execute(
            """
            UPDATE long_tail_task_runs
            SET lease_owner = %s, lease_expires_at = %s, updated_at = now()
            WHERE id = %s
              AND (
                lease_owner IS NULL
                OR lease_owner = ''
                OR lease_owner = %s
                OR lease_expires_at IS NULL
                OR lease_expires_at <= %s
              )
            RETURNING id, lease_owner, lease_expires_at
            """,
            (worker_id, lease_expires_at, task_id, worker_id, now),
        ).fetchone()
        if row:
            conn.commit()
            return {
                "task_id": row[0],
                "acquired": True,
                "lease_owner": row[1],
                "lease_expires_at": row[2],
            }

        existing = conn.execute(
            """
            SELECT id, lease_owner, lease_expires_at FROM long_tail_task_runs
            WHERE id = %s
            """,
            (task_id,),
        ).fetchone()
        if not existing:
            return {"task_id": task_id, "acquired": False, "reason": "task_not_found"}
        return {
            "task_id": existing[0],
            "acquired": False,
            "reason": "active_lease",
            "lease_owner": existing[1] or "",
            "lease_expires_at": existing[2],
        }

    def release_task(self, task_id: str, *, worker_id: str) -> dict[str, Any]:
        conn = self.connection_factory()
        row = conn.execute(
            """
            UPDATE long_tail_task_runs
            SET lease_owner = '', lease_expires_at = NULL, updated_at = now()
            WHERE id = %s AND lease_owner = %s
            RETURNING id, lease_owner, lease_expires_at
            """,
            (task_id, worker_id),
        ).fetchone()
        if not row:
            return {"task_id": task_id, "released": False, "status": "not_owner_or_missing"}
        conn.commit()
        return {"task_id": row[0], "released": True, "status": "released"}


class PostgresLongTailRecoveryScanner:
    def __init__(self, *, connection_factory: Callable[[], Any]) -> None:
        self.connection_factory = connection_factory

    def due_task_ids(self, *, limit: int = 20) -> list[str]:
        rows = self.connection_factory().execute(
            """
            SELECT id
            FROM long_tail_task_runs
            WHERE status IN ('created', 'running')
              AND (lease_expires_at IS NULL OR lease_expires_at <= now())
            ORDER BY updated_at ASC, created_at ASC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
        return [str(row[0]) for row in rows]


class LongTailGraphRunner:
    external_effect_actions = {
        "browser.submit",
        "browser.click_write",
        "email.send",
        "message.send",
        "payment.transfer",
        "purchase.submit",
        "booking.confirm",
        "account.modify",
        "data.delete",
        "archive_or_destructive_update",
    }

    def __init__(
        self,
        *,
        event_store: LongTailEventStore | None = None,
        verifier: StepVerifier | None = None,
    ) -> None:
        self.event_store = event_store or LongTailEventStore()
        self.verifier = verifier or StepVerifier()
        self.plans_by_task: dict[str, dict[str, Any]] = {}
        self.state_by_task: dict[str, dict[str, Any]] = {}

    def create_task(
        self,
        *,
        original_goal: str,
        route_decision: dict[str, Any],
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        task_id = f"lta_{uuid.uuid4().hex}"
        self.event_store.append_event(
            task_id=task_id,
            event_type="task.created",
            payload={"original_goal": original_goal},
            idempotency_key=f"{task_id}:task.created",
        )
        self.event_store.append_event(
            task_id=task_id,
            event_type="route.decided",
            payload=dict(route_decision),
            idempotency_key=f"{task_id}:route.decided",
        )
        self.event_store.append_event(
            task_id=task_id,
            event_type="plan.proposed",
            payload={"plan_version": 1, "plan": dict(plan)},
            idempotency_key=f"{task_id}:plan.proposed:1",
        )

        validation_report = self.validate_plan(plan)
        current_node = "select_step" if validation_report["status"] == "valid" else "blocked"
        status = "running" if validation_report["status"] == "valid" else "blocked"
        self.event_store.append_event(
            task_id=task_id,
            event_type="plan.validated",
            payload={
                "plan_version": 1,
                "current_node": current_node,
                "validation_report": validation_report,
            },
            idempotency_key=f"{task_id}:plan.validated:1",
        )

        task = {
            "task_id": task_id,
            "status": status,
            "current_node": current_node,
            "plan_version": 1,
            "original_goal": original_goal,
            "route_decision": dict(route_decision),
            "validation_report": validation_report,
            "completed_steps": [],
        }
        self.state_by_task[task_id] = task
        if status == "blocked":
            return dict(task)

        self.plans_by_task[task_id] = dict(plan)
        self.event_store.append_event(
            task_id=task_id,
            event_type="memory.initialized",
            payload={"plan_version": 1, "completed_steps": []},
            idempotency_key=f"{task_id}:memory.initialized:1",
        )
        self.event_store.append_event(
            task_id=task_id,
            event_type="checkpoint.saved",
            payload={"after_event_sequence": len(self.event_store.task_events(task_id)) + 1, "current_node": current_node},
            idempotency_key=f"{task_id}:checkpoint.initial:1",
        )
        return dict(task)

    def validate_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        issues: list[str] = []
        steps = list(plan.get("steps") or [])
        if not steps:
            issues.append("plan has no steps")
        for step in steps:
            if not step.get("verification_criteria"):
                issues.append("missing verification criteria")
            allowed_actions = set(step.get("allowed_actions") or [])
            if allowed_actions.intersection(self.external_effect_actions):
                issues.append("external effect action is not converted to confirmation")
            if not step.get("expected_outputs"):
                issues.append("missing expected outputs")
            if not step.get("objective"):
                issues.append("missing step objective")
        return {"status": "valid" if not issues else "blocked", "issues": issues}

    def run_next(self, task_id: str) -> dict[str, Any]:
        task = self.state_by_task[task_id]
        plan = self.plans_by_task[task_id]
        step = self._next_step(task_id)
        step_id = str(step["step_id"])
        self.event_store.append_event(
            task_id=task_id,
            event_type="step.selected",
            step_id=step_id,
            payload={"step_id": step_id, "objective": step.get("objective")},
            idempotency_key=f"{task_id}:{step_id}:selected",
        )
        packet = self.build_step_packet(task, step)
        self.event_store.append_event(
            task_id=task_id,
            event_type="step_packet.built",
            step_id=step_id,
            payload={"packet": packet},
            idempotency_key=f"{task_id}:{step_id}:packet",
        )
        task["current_node"] = "awaiting_executor"
        task["current_step_id"] = step_id
        return dict(packet)

    def recover_task(self, task_id: str, *, record_restore_event: bool = True) -> dict[str, Any]:
        events = self.event_store.task_events(task_id)
        if not events:
            raise KeyError(f"No events for task {task_id}")

        original_goal = ""
        route_decision: dict[str, Any] = {}
        validation_report: dict[str, Any] = {"status": "unknown", "issues": []}
        plan: dict[str, Any] = {}
        plan_version: int | None = None
        status = "unknown"
        current_node = "created"
        current_step_id = ""
        completed_by_step: dict[str, dict[str, Any]] = {}
        latest_checkpoint: dict[str, Any] = {}
        pending_executor_result: dict[str, Any] | None = None
        pending_human_input: dict[str, Any] | None = None
        failure_reason = ""

        for event in events:
            event_type = str(event.get("event_type") or "")
            payload = dict(event.get("payload") or {})
            event_step_id = str(event.get("step_id") or "")

            if event_type == "task.created":
                status = "created"
                current_node = "created"
                original_goal = str(payload.get("original_goal") or "")
            elif event_type == "route.decided":
                route_decision = payload
            elif event_type == "plan.proposed":
                plan_version = int(payload.get("plan_version") or 1)
                plan = dict(payload.get("plan") or {})
            elif event_type == "plan.validated":
                validation_report = dict(payload.get("validation_report") or {})
                status = "running" if validation_report.get("status") == "valid" else "blocked"
                current_node = str(payload.get("current_node") or current_node)
                plan_version = int(payload.get("plan_version") or plan_version or 1)
            elif event_type == "checkpoint.saved":
                latest_checkpoint = payload
                current_node = str(payload.get("current_node") or current_node)
                checkpoint_steps = payload.get("completed_steps")
                if isinstance(checkpoint_steps, list):
                    completed_by_step = {
                        str(step.get("step_id") or ""): dict(step)
                        for step in checkpoint_steps
                        if isinstance(step, dict) and step.get("step_id")
                    }
            elif event_type == "step.selected":
                current_step_id = str(payload.get("step_id") or event_step_id)
                current_node = "step_selected"
            elif event_type == "step_packet.built":
                packet = dict(payload.get("packet") or {})
                current_step_id = str(packet.get("step_id") or event_step_id or current_step_id)
                current_node = "awaiting_executor"
                pending_executor_result = None
            elif event_type == "step.result_returned":
                current_step_id = event_step_id or current_step_id
                current_node = "verify_step"
                pending_executor_result = dict(payload.get("executor_result") or {})
            elif event_type == "step.verified":
                if payload.get("status") == "passed":
                    memory_patch = dict(payload.get("memory_patch") or {})
                    completed_step = memory_patch.get("completed_step")
                    if isinstance(completed_step, dict) and completed_step.get("step_id"):
                        completed_by_step[str(completed_step["step_id"])] = dict(completed_step)
                    current_node = "select_step"
                pending_executor_result = None
            elif event_type == "fallback.decided":
                fallback = dict(payload.get("fallback_decision") or {})
                current_node = "select_step" if fallback.get("action") == "retry" else "blocked"
                status = "running" if current_node == "select_step" else "blocked"
                if current_node == "blocked":
                    failure_reason = str(fallback.get("reason") or "")
                pending_executor_result = None
            elif event_type == "human_input.requested":
                request_step_id = event_step_id or str(payload.get("step_id") or current_step_id)
                current_step_id = request_step_id
                pending_human_input = {
                    "step_id": request_step_id,
                    "input_type": str(payload.get("input_type") or "clarification"),
                    "question": str(payload.get("question") or ""),
                    "options": list(payload.get("options") or []),
                    "status": "waiting",
                    "created_at": str(event.get("created_at") or ""),
                }
                current_node = "waiting_for_human_input"
            elif event_type == "human_input.received":
                pending_human_input = None
                current_node = "select_step"
            elif event_type == "external_effect.proposed":
                current_node = "waiting_for_confirmation"
            elif event_type == "external_effect.confirmed":
                current_node = "select_step"
            elif event_type == "final.evaluated":
                current_node = "final_evaluation"
            elif event_type == "task.completed":
                status = "completed"
                current_node = "delivered"
            elif event_type == "task.cancelled":
                status = "cancelled"
                current_node = "cancelled"

        completed_steps = list(completed_by_step.values())
        task = {
            "task_id": task_id,
            "status": status,
            "current_node": current_node,
            "plan_version": plan_version,
            "original_goal": original_goal,
            "route_decision": route_decision,
            "validation_report": validation_report,
            "completed_steps": completed_steps,
            "latest_checkpoint": latest_checkpoint,
        }
        if current_step_id:
            task["current_step_id"] = current_step_id
        if pending_executor_result is not None:
            task["pending_executor_result"] = pending_executor_result
        if pending_human_input is not None:
            task["pending_human_input"] = pending_human_input
        if failure_reason:
            task["failure_reason"] = failure_reason

        self.state_by_task[task_id] = task
        if plan:
            self.plans_by_task[task_id] = plan

        if record_restore_event:
            last_sequence = int(events[-1].get("sequence") or len(events))
            self.event_store.append_event(
                task_id=task_id,
                event_type="checkpoint.restored",
                step_id=current_step_id or None,
                payload={
                    "current_node": current_node,
                    "current_step_id": current_step_id,
                    "completed_steps": completed_steps,
                    "latest_checkpoint": latest_checkpoint,
                    "after_event_sequence": last_sequence,
                },
                idempotency_key=f"{task_id}:checkpoint.restored:{last_sequence}",
            )
        return dict(task)

    def complete_current_step(self, task_id: str, *, executor_result: dict[str, Any]) -> dict[str, Any]:
        task = self.state_by_task[task_id]
        step = self._current_step(task_id)
        step_id = str(step["step_id"])
        self.event_store.append_event(
            task_id=task_id,
            event_type="step.result_returned",
            step_id=step_id,
            payload={"executor_result": dict(executor_result)},
            idempotency_key=f"{task_id}:{step_id}:result:{len(self.event_store.task_events(task_id))}",
        )
        verifier_report = self.verifier.verify(step, executor_result)
        self.event_store.append_event(
            task_id=task_id,
            event_type="step.verified",
            step_id=step_id,
            payload=verifier_report,
            idempotency_key=f"{task_id}:{step_id}:verified:{len(self.event_store.task_events(task_id))}",
        )
        if verifier_report["status"] == "passed":
            memory_patch = dict(verifier_report.get("memory_patch") or {})
            self.event_store.append_event(
                task_id=task_id,
                event_type="memory.patch_applied",
                step_id=step_id,
                payload={"memory_patch": memory_patch},
                idempotency_key=f"{task_id}:{step_id}:memory_patch",
            )
            completed_step = memory_patch.get("completed_step")
            if completed_step:
                task["completed_steps"].append(dict(completed_step))
            task["current_node"] = "final_evaluation" if self._all_steps_completed(task_id) else "select_step"
            self.event_store.append_event(
                task_id=task_id,
                event_type="checkpoint.saved",
                step_id=step_id,
                payload={
                    "after_step_id": step_id,
                    "current_node": task["current_node"],
                    "completed_steps": list(task["completed_steps"]),
                },
                idempotency_key=f"{task_id}:{step_id}:checkpoint",
            )
            return {"status": "verified", "verifier_report": verifier_report}

        fallback_decision = {
            "action": "retry" if verifier_report["status"] == "retry" else "stop",
            "reason": verifier_report["reason"],
            "checkpoint_id": "",
        }
        if verifier_report["status"] == "blocked" or verifier_report.get("violations"):
            fallback_decision["action_card"] = self._forbidden_external_action_card()
        self.event_store.append_event(
            task_id=task_id,
            event_type="fallback.decided",
            step_id=step_id,
            payload={"fallback_decision": fallback_decision},
            idempotency_key=f"{task_id}:{step_id}:fallback:{len(self.event_store.task_events(task_id))}",
        )
        task["current_node"] = "select_step" if fallback_decision["action"] == "retry" else "blocked"
        return {
            "status": "fallback",
            "verifier_report": verifier_report,
            "fallback_decision": fallback_decision,
        }

    def evaluate_final(self, task_id: str) -> dict[str, Any]:
        task = self.state_by_task[task_id]
        completed_steps = list(task.get("completed_steps") or [])
        completed_ids = {str(step.get("step_id") or "") for step in completed_steps}
        step_ids = [str(step.get("step_id") or "") for step in list(self.plans_by_task[task_id].get("steps") or [])]
        incomplete_steps = [step_id for step_id in step_ids if step_id not in completed_ids]
        if incomplete_steps:
            final = {
                "status": "partial",
                "completed_criteria": [],
                "incomplete_criteria": list(self.plans_by_task[task_id].get("success_criteria") or []),
                "incomplete_steps": incomplete_steps,
                "evidence": [],
                "violations": [],
                "delivery": {
                    "message": "还没有完成可验证步骤，任务保持在安全状态。",
                    "actions": [{"label": "继续执行", "action": "resume_from_checkpoint"}],
                },
            }
        else:
            summaries = [str(step.get("summary") or "") for step in completed_steps if step.get("summary")]
            message = "已完成：" + "；".join(summaries) if summaries else "已完成可验证步骤。"
            final = {
                "status": "passed",
                "completed_criteria": list(self.plans_by_task[task_id].get("success_criteria") or []),
                "incomplete_criteria": [],
                "incomplete_steps": [],
                "evidence": completed_steps,
                "violations": [],
                "delivery": {"message": message, "actions": self._external_effect_review_actions(task_id)},
            }
            task["status"] = "completed"
            task["current_node"] = "delivered"

        self.event_store.append_event(
            task_id=task_id,
            event_type="final.evaluated",
            payload={"final": final},
            idempotency_key=f"{task_id}:final:evaluated:{len(self.event_store.task_events(task_id))}",
        )
        self.event_store.append_event(
            task_id=task_id,
            event_type="delivery.created",
            payload={"delivery": final["delivery"]},
            idempotency_key=f"{task_id}:delivery:{len(self.event_store.task_events(task_id))}",
        )
        if final["status"] == "passed":
            self.event_store.append_event(
                task_id=task_id,
                event_type="task.completed",
                payload={"status": "completed"},
                idempotency_key=f"{task_id}:completed",
            )
        return final

    def cancel_task(self, task_id: str, *, reason: str = "") -> dict[str, Any]:
        task = self.state_by_task[task_id]
        task["status"] = "cancelled"
        task["current_node"] = "cancelled"
        self.event_store.append_event(
            task_id=task_id,
            event_type="task.cancelled",
            payload={"reason": reason},
            idempotency_key=f"{task_id}:cancelled:{len(self.event_store.task_events(task_id))}",
        )
        return dict(task)

    def request_human_input(
        self,
        task_id: str,
        *,
        step_id: str | None = None,
        input_type: str = "clarification",
        question: str = "",
        options: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        task = self.state_by_task[task_id]
        normalized_options = [dict(option) for option in list(options or [])]
        event = self.event_store.append_event(
            task_id=task_id,
            event_type="human_input.requested",
            step_id=step_id,
            payload={
                "step_id": step_id or "",
                "input_type": input_type,
                "question": question,
                "options": normalized_options,
                "status": "waiting",
            },
            idempotency_key=f"{task_id}:{step_id or 'task'}:human_input.requested:{len(self.event_store.task_events(task_id))}",
        )
        pending_human_input = {
            "step_id": step_id or "",
            "input_type": input_type,
            "question": question,
            "options": normalized_options,
            "status": "waiting",
            "created_at": str(event.get("created_at") or ""),
        }
        task["current_node"] = "waiting_for_human_input"
        task["pending_human_input"] = pending_human_input
        if step_id:
            task["current_step_id"] = step_id
        return event

    def record_human_input(
        self,
        task_id: str,
        *,
        step_id: str | None = None,
        input_type: str = "user_response",
        response: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = self.event_store.append_event(
            task_id=task_id,
            event_type="human_input.received",
            step_id=step_id,
            payload={"input_type": input_type, "response": dict(response or {})},
            idempotency_key=f"{task_id}:human_input:{len(self.event_store.task_events(task_id))}",
        )
        task = self.state_by_task.get(task_id)
        if task is not None:
            task["current_node"] = "select_step"
            task.pop("pending_human_input", None)
        return event

    def build_step_packet(self, task: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
        return {
            "task_id": task["task_id"],
            "step_id": str(step.get("step_id") or ""),
            "original_goal_summary": task["original_goal"],
            "step_objective": str(step.get("objective") or ""),
            "minimal_context": {},
            "expected_outputs": list(step.get("expected_outputs") or []),
            "allowed_actions": list(step.get("allowed_actions") or []),
            "forbidden_actions": list(step.get("forbidden_actions") or []),
            "verification_criteria": list(step.get("verification_criteria") or []),
            "return_schema": {
                "status": "passed | failed | blocked | needs_user_input",
                "summary": "string",
                "outputs": {},
                "evidence": [],
                "action_events": [],
                "next_risk": "none | external_write | payment | message_send",
            },
        }

    def get_task_state(self, task_id: str) -> dict[str, Any]:
        return dict(self.state_by_task[task_id])

    def _current_step(self, task_id: str) -> dict[str, Any]:
        task = self.state_by_task[task_id]
        current_step_id = str(task.get("current_step_id") or "")
        for step in list(self.plans_by_task[task_id].get("steps") or []):
            if str(step.get("step_id")) == current_step_id:
                return dict(step)
        return self._next_step(task_id)

    def _next_step(self, task_id: str) -> dict[str, Any]:
        completed_ids = {
            str(step.get("step_id") or "") for step in self.state_by_task[task_id].get("completed_steps", [])
        }
        for step in list(self.plans_by_task[task_id].get("steps") or []):
            if str(step.get("step_id")) not in completed_ids:
                return dict(step)
        raise ValueError(f"No pending step for task {task_id}")

    def _all_steps_completed(self, task_id: str) -> bool:
        completed_ids = {
            str(step.get("step_id") or "") for step in self.state_by_task[task_id].get("completed_steps", [])
        }
        step_ids = {str(step.get("step_id") or "") for step in list(self.plans_by_task[task_id].get("steps") or [])}
        return bool(step_ids) and step_ids.issubset(completed_ids)

    def _forbidden_external_action_card(self) -> dict[str, Any]:
        message = (
            "Nomi 已停止当前任务，并会保持内部状态可审查。"
            "如果第三方系统里已经发生动作，不能假装已经撤回第三方动作；"
            "只能准备补偿操作，并在你确认后执行。"
        )
        return {
            "title": "发现禁止的外部动作",
            "message": message,
            "actions": [
                {
                    "id": "review_external_effects",
                    "label": "查看外部动作与补偿",
                    "requires_confirmation": False,
                }
            ],
        }

    def _external_effect_review_actions(self, task_id: str) -> list[dict[str, Any]]:
        effects: dict[str, dict[str, Any]] = {}
        for event in self.event_store.task_events(task_id):
            payload = dict(event.get("payload") or {})
            effect_id = str(payload.get("effect_id") or "")
            if not effect_id:
                continue
            event_type = str(event.get("event_type") or "")
            effect = effects.setdefault(effect_id, {"effect_id": effect_id, "status": ""})
            if event_type == "external_effect.proposed":
                effect["status"] = str(payload.get("status") or "waiting_for_confirmation")
            elif event_type == "external_effect.confirmed":
                effect["status"] = str(payload.get("status") or "confirmed")
            elif event_type == "external_effect.executed":
                effect["status"] = str(payload.get("status") or "executed")
            elif event_type == "external_effect.compensation_proposed":
                effect["status"] = str(payload.get("status") or "waiting_for_compensation_confirmation")
        return [
            {
                "id": "review_external_effect_rollback",
                "label": "查看回滚与补偿",
                "effect_id": effect_id,
                "requires_confirmation": False,
            }
            for effect_id, effect in effects.items()
            if effect.get("status") == "executed"
        ]


class ExternalEffectController:
    def __init__(self, *, event_store: LongTailEventStore | None = None) -> None:
        self.event_store = event_store or LongTailEventStore()
        self.effects: dict[str, dict[str, Any]] = {}

    def propose(
        self,
        *,
        task_id: str,
        step_id: str,
        action_request_id: str,
        effect_type: str,
        proposal: dict[str, Any],
    ) -> dict[str, Any]:
        effect_id = f"effect_{uuid.uuid4().hex}"
        effect = {
            "effect_id": effect_id,
            "task_id": task_id,
            "step_id": step_id,
            "action_request_id": action_request_id,
            "effect_type": effect_type,
            "status": "waiting_for_confirmation",
            "proposal": dict(proposal),
            "confirmation_payload": {},
            "execution_payload": {},
            "compensation_proposal": {},
        }
        self.effects[effect_id] = effect
        self.event_store.append_event(
            task_id=task_id,
            event_type="external_effect.proposed",
            step_id=step_id,
            payload={
                "effect_id": effect_id,
                "action_request_id": action_request_id,
                "effect_type": effect_type,
                "proposal": dict(proposal),
                "status": "waiting_for_confirmation",
            },
            idempotency_key=f"{effect_id}:proposed",
        )
        return dict(effect)

    def recover_effect(self, task_id: str, effect_id: str) -> dict[str, Any]:
        recovered: dict[str, Any] | None = None
        for event in self.event_store.task_events(task_id):
            payload = dict(event.get("payload") or {})
            if str(payload.get("effect_id") or "") != effect_id:
                continue
            event_type = str(event.get("event_type") or "")
            if event_type == "external_effect.proposed":
                recovered = {
                    "effect_id": effect_id,
                    "task_id": task_id,
                    "step_id": str(event.get("step_id") or ""),
                    "action_request_id": str(payload.get("action_request_id") or ""),
                    "effect_type": str(payload.get("effect_type") or ""),
                    "status": str(payload.get("status") or "waiting_for_confirmation"),
                    "proposal": dict(payload.get("proposal") or {}),
                    "confirmation_payload": {},
                    "execution_payload": {},
                    "compensation_proposal": {},
                }
            elif recovered is not None and event_type == "external_effect.confirmed":
                recovered["status"] = str(payload.get("status") or "confirmed")
                recovered["confirmation_payload"] = dict(
                    payload.get("confirmation_payload") or payload.get("confirmation") or {}
                )
            elif recovered is not None and event_type == "external_effect.executed":
                recovered["status"] = str(payload.get("status") or "executed")
                recovered["execution_payload"] = dict(payload.get("execution_payload") or {})
            elif recovered is not None and event_type == "external_effect.compensation_proposed":
                recovered["status"] = str(payload.get("status") or "waiting_for_compensation_confirmation")
                recovered["compensation_proposal"] = dict(payload.get("compensation_proposal") or {})
        if recovered is None:
            raise KeyError(f"No external effect {effect_id} for task {task_id}")
        self.effects[effect_id] = recovered
        return dict(recovered)

    def _effect(self, effect_id: str, *, task_id: str | None = None) -> dict[str, Any]:
        if effect_id not in self.effects:
            if not task_id:
                raise KeyError(effect_id)
            self.recover_effect(task_id, effect_id)
        return self.effects[effect_id]

    def confirm(
        self,
        effect_id: str,
        *,
        confirmation_payload: dict[str, Any],
        task_id: str | None = None,
    ) -> dict[str, Any]:
        effect = self._effect(effect_id, task_id=task_id)
        effect["status"] = "confirmed"
        effect["confirmation_payload"] = dict(confirmation_payload)
        self.event_store.append_event(
            task_id=effect["task_id"],
            event_type="external_effect.confirmed",
            step_id=effect["step_id"],
            payload={
                "effect_id": effect_id,
                "confirmation_payload": dict(confirmation_payload),
                "status": "confirmed",
            },
            idempotency_key=f"{effect_id}:confirmed",
        )
        return dict(effect)

    def execute(
        self,
        effect_id: str,
        *,
        execution_payload: dict[str, Any],
        task_id: str | None = None,
    ) -> dict[str, Any]:
        effect = self._effect(effect_id, task_id=task_id)
        if effect["status"] != "confirmed":
            return {
                "effect_id": effect_id,
                "status": effect["status"],
                "may_execute": False,
                "reason": "External effect cannot execute before user confirmation.",
            }
        effect["status"] = "executed"
        effect["execution_payload"] = dict(execution_payload)
        self.event_store.append_event(
            task_id=effect["task_id"],
            event_type="external_effect.executed",
            step_id=effect["step_id"],
            payload={
                "effect_id": effect_id,
                "execution_payload": dict(execution_payload),
                "status": "executed",
            },
            idempotency_key=f"{effect_id}:executed",
        )
        return {**dict(effect), "may_execute": True}

    def describe_internal_rollback(self, effect_id: str, *, task_id: str | None = None) -> dict[str, Any]:
        effect = self._effect(effect_id, task_id=task_id)
        user_message = (
            "我可以回滚 Nomi 内部的任务状态，但不能撤回第三方系统中已经发生的动作。"
            "如果需要，我可以准备一个补偿操作给你确认。"
        )
        return {
            "effect_id": effect_id,
            "task_id": effect["task_id"],
            "internal_state_can_rollback": True,
            "external_world_can_rollback": False,
            "user_message": user_message,
            "action_card": {
                "title": "只能回滚 Nomi 内部状态",
                "message": user_message,
                "actions": [
                    {
                        "id": "prepare_compensation",
                        "label": "准备补偿操作",
                        "requires_confirmation": True,
                    }
                ],
            },
        }

    def propose_compensation(
        self,
        effect_id: str,
        *,
        proposal: dict[str, Any],
        task_id: str | None = None,
    ) -> dict[str, Any]:
        effect = self._effect(effect_id, task_id=task_id)
        effect["status"] = "waiting_for_compensation_confirmation"
        effect["compensation_proposal"] = dict(proposal)
        self.event_store.append_event(
            task_id=effect["task_id"],
            event_type="external_effect.compensation_proposed",
            step_id=effect["step_id"],
            payload={
                "effect_id": effect_id,
                "compensation_proposal": dict(proposal),
                "status": "waiting_for_compensation_confirmation",
            },
            idempotency_key=f"{effect_id}:compensation_proposed",
        )
        return dict(effect)


class ExecutorAdapterRegistry:
    def __init__(
        self,
        *,
        event_store: LongTailEventStore | None = None,
        policy_gate: PolicyGate | None = None,
    ) -> None:
        self.event_store = event_store or LongTailEventStore()
        self.policy_gate = policy_gate or PolicyGate()

    def propose_action(
        self,
        *,
        task_id: str,
        step_id: str,
        adapter: str,
        action_type: str,
        target: dict[str, Any],
        input_summary: dict[str, Any],
        risk_level: str,
        expected_effect: str,
        allowed_actions: set[str],
        confirmation_token: str | None = None,
        executor_trace: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action_id = f"act_{uuid.uuid4().hex}"
        trace_payload = dict(executor_trace or {})
        action = ActionRequest(
            action_id=action_id,
            task_id=task_id,
            step_id=step_id,
            adapter=adapter,
            action_type=action_type,
            target=dict(target),
            input_summary=dict(input_summary),
            risk_level=risk_level,
            expected_effect=expected_effect,
            idempotency_key=f"{task_id}:{step_id}:{action_id}",
            confirmation_token=confirmation_token,
        )
        action_payload = asdict(action)
        self.event_store.append_event(
            task_id=task_id,
            event_type="executor.action_requested",
            step_id=step_id,
            payload={"action_request": action_payload, "executor_trace": trace_payload},
            idempotency_key=f"{action.idempotency_key}:requested",
        )
        policy_report = self.policy_gate.evaluate(action, allowed_actions=allowed_actions)
        self.event_store.append_event(
            task_id=task_id,
            event_type="policy.checked",
            step_id=step_id,
            payload={
                "action_request_id": action.action_id,
                "policy_report": policy_report,
                "executor_trace": trace_payload,
            },
            idempotency_key=f"{action.idempotency_key}:policy",
        )
        return {"action_request": action_payload, "policy_report": policy_report, "executor_trace": trace_payload}

    def execute_dry_run(
        self,
        *,
        task_id: str,
        step_id: str,
        adapter: str,
        action_type: str,
        target: dict[str, Any],
        input_summary: dict[str, Any],
        risk_level: str,
        expected_effect: str,
        allowed_actions: set[str],
        confirmation_token: str | None = None,
        executor_trace: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        trace_payload = dict(executor_trace or {})
        trace_payload.setdefault("adapter_mode", "dry_run")
        proposed = self.propose_action(
            task_id=task_id,
            step_id=step_id,
            adapter=adapter,
            action_type=action_type,
            target=target,
            input_summary=input_summary,
            risk_level=risk_level,
            expected_effect=expected_effect,
            allowed_actions=allowed_actions,
            confirmation_token=confirmation_token,
            executor_trace=trace_payload,
        )
        may_execute = bool(proposed["policy_report"].get("may_execute"))
        status = "skipped_live_execution" if may_execute else "blocked_by_policy"
        dry_run_result = {
            "mode": "dry_run",
            "status": status,
            "would_execute_if_live": may_execute,
            "external_side_effect": False,
            "reason": (
                "Policy allowed this action, but dry-run mode skipped live adapter execution."
                if may_execute
                else "Policy blocked this action before dry-run adapter execution."
            ),
        }
        self.event_store.append_event(
            task_id=task_id,
            event_type="executor.dry_run_completed",
            step_id=step_id,
            payload={
                "action_request_id": proposed["action_request"]["action_id"],
                "policy_status": proposed["policy_report"]["status"],
                "dry_run_result": dry_run_result,
                "executor_trace": trace_payload,
            },
            idempotency_key=f"{proposed['action_request']['idempotency_key']}:dry_run_completed",
        )
        return {
            **proposed,
            "mode": "dry_run",
            "status": status,
            "dry_run_result": dry_run_result,
        }

    def execute_live(
        self,
        *,
        task_id: str,
        step_id: str,
        adapter: str,
        action_type: str,
        target: dict[str, Any],
        input_summary: dict[str, Any],
        risk_level: str,
        expected_effect: str,
        allowed_actions: set[str],
        executor: Callable[[dict[str, Any]], dict[str, Any]],
        confirmation_token: str | None = None,
        executor_trace: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        trace_payload = dict(executor_trace or {})
        trace_payload.setdefault("adapter_mode", "live")
        proposed = self.propose_action(
            task_id=task_id,
            step_id=step_id,
            adapter=adapter,
            action_type=action_type,
            target=target,
            input_summary=input_summary,
            risk_level=risk_level,
            expected_effect=expected_effect,
            allowed_actions=allowed_actions,
            confirmation_token=confirmation_token,
            executor_trace=trace_payload,
        )
        if not proposed["policy_report"].get("may_execute"):
            return {
                **proposed,
                "mode": "live",
                "status": "blocked_by_policy",
                "live_result": {
                    "mode": "live",
                    "status": "blocked_by_policy",
                    "external_side_effect": False,
                    "reason": proposed["policy_report"].get("reason", ""),
                },
            }

        try:
            live_result = dict(executor(dict(proposed["action_request"])) or {})
        except Exception as exc:
            live_result = {
                "status": "failed",
                "error": type(exc).__name__,
                "summary": str(exc)[:300],
                "external_side_effect": False,
            }
        live_result.setdefault("mode", "live")
        live_result.setdefault("status", "completed")
        live_result.setdefault("external_side_effect", risk_level != "read_only")
        for trace_key in ["provider_trace_id", "executor_trace_id", "toolkit", "tool_slug"]:
            if live_result.get(trace_key):
                trace_payload[trace_key] = live_result[trace_key]
        self.event_store.append_event(
            task_id=task_id,
            event_type="executor.live_completed",
            step_id=step_id,
            payload={
                "action_request_id": proposed["action_request"]["action_id"],
                "policy_status": proposed["policy_report"]["status"],
                "live_result": live_result,
                "executor_trace": trace_payload,
            },
            idempotency_key=f"{proposed['action_request']['idempotency_key']}:live_completed",
        )
        return {
            **proposed,
            "mode": "live",
            "status": live_result["status"],
            "live_result": live_result,
            "executor_trace": trace_payload,
        }


def long_tail_agent_schema_sql() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS long_tail_task_runs (
          id TEXT PRIMARY KEY,
          route_trace_id TEXT,
          original_goal TEXT NOT NULL DEFAULT '',
          route_decision JSONB NOT NULL DEFAULT '{}'::jsonb,
          status TEXT NOT NULL DEFAULT 'created',
          risk_permission TEXT NOT NULL DEFAULT '',
          confirmation_required BOOLEAN NOT NULL DEFAULT FALSE,
          current_node TEXT NOT NULL DEFAULT '',
          current_step_id TEXT,
          plan_version INTEGER,
          budget_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          token_usage_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          lease_owner TEXT,
          lease_expires_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS long_tail_task_events (
          id TEXT PRIMARY KEY,
          task_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,
          event_type TEXT NOT NULL,
          step_id TEXT,
          node_name TEXT NOT NULL DEFAULT '',
          payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          redaction_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          idempotency_key TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS long_tail_task_events_sequence_idx
        ON long_tail_task_events(task_id, sequence)
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS long_tail_task_events_idempotency_idx
        ON long_tail_task_events(task_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL
        """,
        """
        CREATE TABLE IF NOT EXISTS long_tail_task_plans (
          id TEXT PRIMARY KEY,
          task_id TEXT NOT NULL,
          version INTEGER NOT NULL,
          planner_model TEXT NOT NULL DEFAULT '',
          plan_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          validation_status TEXT NOT NULL DEFAULT '',
          validation_report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS long_tail_task_memory (
          id TEXT PRIMARY KEY,
          task_id TEXT NOT NULL,
          memory_type TEXT NOT NULL DEFAULT '',
          step_id TEXT,
          payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          payload_hash TEXT NOT NULL DEFAULT '',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS long_tail_step_runs (
          id TEXT PRIMARY KEY,
          task_id TEXT NOT NULL,
          step_id TEXT NOT NULL,
          attempt_number INTEGER NOT NULL DEFAULT 1,
          executor_adapter TEXT NOT NULL DEFAULT '',
          step_packet_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          policy_report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          status TEXT NOT NULL DEFAULT '',
          result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          verifier_report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          started_at TIMESTAMPTZ,
          completed_at TIMESTAMPTZ
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS long_tail_checkpoints (
          id TEXT PRIMARY KEY,
          task_id TEXT NOT NULL,
          after_event_sequence INTEGER NOT NULL,
          after_step_id TEXT,
          task_memory_hash TEXT NOT NULL DEFAULT '',
          checkpoint_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          restore_policy TEXT NOT NULL DEFAULT '',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS long_tail_human_inputs (
          id TEXT PRIMARY KEY,
          task_id TEXT NOT NULL,
          step_id TEXT,
          input_type TEXT NOT NULL DEFAULT '',
          question TEXT NOT NULL DEFAULT '',
          options_json JSONB NOT NULL DEFAULT '[]'::jsonb,
          status TEXT NOT NULL DEFAULT 'waiting',
          response_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          resolved_at TIMESTAMPTZ
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS long_tail_policy_reports (
          id TEXT PRIMARY KEY,
          task_id TEXT NOT NULL,
          step_id TEXT,
          action_id TEXT NOT NULL DEFAULT '',
          policy_level TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT '',
          reason TEXT NOT NULL DEFAULT '',
          requires_confirmation BOOLEAN NOT NULL DEFAULT FALSE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS long_tail_action_requests (
          id TEXT PRIMARY KEY,
          task_id TEXT NOT NULL,
          step_id TEXT NOT NULL,
          action_id TEXT NOT NULL,
          adapter TEXT NOT NULL,
          action_type TEXT NOT NULL,
          target_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          input_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          risk_level TEXT NOT NULL DEFAULT '',
          expected_effect TEXT NOT NULL DEFAULT '',
          requires_confirmation_token BOOLEAN NOT NULL DEFAULT FALSE,
          idempotency_key TEXT NOT NULL,
          policy_status TEXT NOT NULL DEFAULT '',
          policy_report_id TEXT,
          executed_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS long_tail_external_effects (
          id TEXT PRIMARY KEY,
          task_id TEXT NOT NULL,
          step_id TEXT,
          action_request_id TEXT,
          effect_type TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'proposed',
          proposal_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          confirmation_event_id TEXT,
          execution_event_id TEXT,
          compensation_proposal_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    ]
