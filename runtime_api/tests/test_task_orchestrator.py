import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_expired_lease_task_resumes_once_and_keeps_step_output():
    from app.task_orchestrator import TaskOrchestrator

    now = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)
    orchestrator = TaskOrchestrator(now=lambda: now)
    task = orchestrator.create_task_run(
        task_type="proactive_suggestion",
        idempotency_key="evt-1:proactive",
        steps=["classify_event", "notify_user"],
    )

    first_step = orchestrator.acquire_next_step(worker_id="worker-a", lease_seconds=5)
    assert first_step["task_run_id"] == task["task_run_id"]
    orchestrator.complete_step(first_step["task_step_id"], output={"label": "appointment"}, reason="appointment detected")

    second_step = orchestrator.acquire_next_step(worker_id="worker-a", lease_seconds=5)
    assert second_step["step_name"] == "notify_user"

    now = now + timedelta(seconds=10)
    resumed = orchestrator.acquire_next_step(worker_id="worker-b", lease_seconds=5)

    assert resumed["task_step_id"] == second_step["task_step_id"]
    assert resumed["attempt_count"] == 2
    assert orchestrator.steps[first_step["task_step_id"]]["output_json"] == {"label": "appointment"}
    assert orchestrator.create_task_run("proactive_suggestion", "evt-1:proactive", ["classify_event"])["task_run_id"] == task["task_run_id"]


def test_notification_outbox_replays_only_unacked_active_messages():
    from app.task_orchestrator import TaskOrchestrator

    orchestrator = TaskOrchestrator()
    active = orchestrator.enqueue_notification(
        task_run_id="task-1",
        suggestion_id="sug-1",
        channel="android",
        payload={"message": "可能需要查路线"},
    )
    dismissed = orchestrator.enqueue_notification(
        task_run_id="task-2",
        suggestion_id="sug-2",
        channel="android",
        payload={"message": "旧建议"},
    )
    orchestrator.ack_notification(dismissed["notification_id"], status="dismissed")

    replay = orchestrator.replay_unacked(channel="android")

    assert [item["notification_id"] for item in replay] == [active["notification_id"]]
    assert replay[0]["payload_json"]["message"] == "可能需要查路线"


def test_task_orchestrator_schema_sql_creates_task_and_outbox_tables():
    from app.task_orchestrator import task_orchestrator_schema_sql

    combined = "\n".join(" ".join(sql.split()) for sql in task_orchestrator_schema_sql())

    assert "CREATE TABLE IF NOT EXISTS task_runs" in combined
    assert "CREATE TABLE IF NOT EXISTS task_steps" in combined
    assert "CREATE TABLE IF NOT EXISTS notification_outbox" in combined
    assert "CREATE TABLE IF NOT EXISTS task_artifacts" in combined
    assert "CREATE TABLE IF NOT EXISTS task_evidence_links" in combined
    assert "task_runs_idempotency_idx" in combined
    assert "task_artifacts_task_idx" in combined
    assert "task_evidence_links_task_idx" in combined


def test_create_artifact_task_run_preserves_route_payload_and_source_evidence():
    from app.task_orchestrator import TaskOrchestrator

    orchestrator = TaskOrchestrator()

    task = orchestrator.create_task_run(
        task_type="artifact_creation",
        idempotency_key="conv-1:msg-1:artifact",
        steps=["interpret_request", "gather_evidence"],
        pipeline_id="ppt_creation_pipeline",
        route_type="artifact_task",
        source_event_ids=["evt_whatsapp_1"],
        payload={
            "artifact_type": "pptx",
            "context_plan": {"needed_context": [{"entity_hint": "王总"}]},
        },
        risk_permission="local_artifact_generation",
        requires_user_confirmation=False,
    )

    assert task["task_type"] == "artifact_creation"
    assert task["pipeline_id"] == "ppt_creation_pipeline"
    assert task["route_type"] == "artifact_task"
    assert task["source_event_ids"] == ["evt_whatsapp_1"]
    assert task["payload"]["artifact_type"] == "pptx"
    assert task["risk_permission"] == "local_artifact_generation"
    assert task["requires_user_confirmation"] is False

    duplicate = orchestrator.create_task_run(
        task_type="artifact_creation",
        idempotency_key="conv-1:msg-1:artifact",
        steps=["interpret_request"],
        payload={"artifact_type": "docx"},
    )

    assert duplicate["task_run_id"] == task["task_run_id"]
    assert duplicate["payload"]["artifact_type"] == "pptx"
