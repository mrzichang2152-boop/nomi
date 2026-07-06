import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_ppt_request_routes_to_artifact_creation_task():
    from app.artifact_tasks import route_artifact_task

    route = route_artifact_task("帮我依据刚刚王总给的资料，写一份 PPT")

    assert route["message_kind"] == "task_request"
    assert route["task_type"] == "artifact_creation"
    assert route["artifact_type"] == "pptx"
    assert route["confidence"] >= 0.8
    assert route["requires_task_run"] is True
    assert route["requires_user_confirmation_before_external_effect"] is False
    assert route["risk_level"] == "medium"
    assert "PPT" in route["reason"]


def test_plain_question_stays_chat_answer():
    from app.artifact_tasks import route_artifact_task

    route = route_artifact_task("王总刚刚说了什么？")

    assert route["message_kind"] == "chat_answer"
    assert route["task_type"] == "none"
    assert route["artifact_type"] == "none"
    assert route["requires_task_run"] is False


def test_wang_zong_recent_material_plan_has_scoped_sources_and_missing_inputs():
    from app.artifact_tasks import build_context_requirement_plan

    plan = build_context_requirement_plan("帮我依据刚刚王总给的资料，写一份 PPT")

    assert plan["needed_context"][0]["type"] == "recent_messages"
    assert plan["needed_context"][0]["entity_hint"] == "王总"
    assert plan["needed_context"][0]["time_window"] == "recent"
    assert "whatsapp" in plan["needed_context"][0]["source"]
    assert "telegram" in plan["needed_context"][0]["source"]
    assert plan["needed_context"][1]["type"] == "attachments"
    assert "PPT用途" in plan["missing_user_inputs"]
    assert "目标听众" in plan["missing_user_inputs"]
    assert "期望页数" in plan["missing_user_inputs"]
    assert plan["can_start_without_missing_inputs"] is True


def test_evidence_pack_marks_missing_topic_when_no_evidence_is_found():
    from app.artifact_tasks import build_evidence_pack

    pack = build_evidence_pack(
        "帮我依据刚刚王总给的资料，写一份 PPT",
        context_plan={"needed_context": [], "missing_user_inputs": ["PPT用途"]},
        source_context=[],
        memory_context=[],
    )

    assert pack["items"] == []
    assert pack["coverage"]["has_topic"] is False
    assert pack["coverage"]["has_data_points"] is False
    assert "未找到王总最近资料" in pack["missing_evidence"]


def test_evidence_pack_uses_real_source_items_and_explains_relevance():
    from app.artifact_tasks import build_evidence_pack

    source_item = {
        "event_id": "evt_whatsapp_1",
        "source": "whatsapp",
        "actor": "王总",
        "timestamp": "2026-07-06T10:30:00+08:00",
        "content": "王总：本次客户汇报重点是上线计划、预算和风险。",
    }

    pack = build_evidence_pack(
        "帮我依据刚刚王总给的资料，写一份 PPT",
        context_plan={"needed_context": [], "missing_user_inputs": []},
        source_context=[source_item],
        memory_context=[],
    )

    assert pack["items"][0]["evidence_id"] == "evt_whatsapp_1"
    assert pack["items"][0]["source"] == "whatsapp"
    assert pack["items"][0]["actor"] == "王总"
    assert "客户汇报重点" in pack["items"][0]["excerpt"]
    assert pack["items"][0]["confidence"] >= 0.8
    assert "王总" in pack["items"][0]["reason"]
    assert pack["coverage"]["has_topic"] is True
    assert pack["coverage"]["has_data_points"] is True


def test_get_task_returns_artifact_task_state_and_evidence(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    created_at = datetime(2026, 7, 6, 10, 30, tzinfo=timezone.utc)
    executed = []

    class Cursor:
        def __init__(self, rows=None, row=None):
            self.rows = rows or []
            self.row = row

        def fetchone(self):
            return self.row

        def fetchall(self):
            return self.rows

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            compact = " ".join(sql.split())
            executed.append((compact, params))
            if "FROM task_runs" in compact:
                return Cursor(
                    row=(
                        "task_artifact_1",
                        "artifact_creation",
                        ["evt_whatsapp_wang_1"],
                        "ppt_creation_pipeline",
                        "artifact_task",
                        "queued",
                        "local_artifact_only",
                        False,
                        "依据王总资料生成 PPT",
                        {"route": {"artifact_type": "pptx"}},
                        created_at,
                        created_at,
                    )
                )
            if "FROM task_steps" in compact:
                return Cursor(
                    rows=[
                        ("step_1", "interpret_request", 0, "succeeded", {"message": "写 PPT"}, {}, "", 1, created_at),
                        ("step_2", "gather_evidence", 1, "queued", {}, {}, "", 0, created_at),
                    ]
                )
            if "FROM task_evidence_links" in compact:
                return Cursor(
                    rows=[
                        (
                            "link_1",
                            "evt_whatsapp_wang_1",
                            "event",
                            "whatsapp",
                            "王总",
                            "artifact_evidence",
                            0.9,
                            created_at,
                        )
                    ]
                )
            raise AssertionError(f"unexpected query: {compact}")

    monkeypatch.setattr(main, "db", lambda: Conn())

    response = TestClient(main.app).get("/api/tasks/task_artifact_1", headers={"x-par-password": "secret"})

    assert response.status_code == 200
    body = response.json()
    assert body["task"]["task_run_id"] == "task_artifact_1"
    assert body["task"]["task_type"] == "artifact_creation"
    assert body["task"]["artifact_type"] == "pptx"
    assert body["task"]["status"] == "queued"
    assert body["steps"][0]["step_name"] == "interpret_request"
    assert body["steps"][0]["status"] == "succeeded"
    assert body["steps"][1]["step_name"] == "gather_evidence"
    assert body["evidence_links"][0]["evidence_id"] == "evt_whatsapp_wang_1"
    assert body["evidence_links"][0]["source"] == "whatsapp"
    assert any("FROM task_runs" in sql for sql, _ in executed)


def test_get_task_artifacts_returns_empty_list_for_planning_task(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    class Cursor:
        def fetchall(self):
            return []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            compact = " ".join(sql.split())
            assert "FROM task_artifacts" in compact
            assert params == ("task_artifact_1",)
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())

    response = TestClient(main.app).get("/api/tasks/task_artifact_1/artifacts", headers={"x-par-password": "secret"})

    assert response.status_code == 200
    assert response.json() == {"task_run_id": "task_artifact_1", "artifacts": []}
