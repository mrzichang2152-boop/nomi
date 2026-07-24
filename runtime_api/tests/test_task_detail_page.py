import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_task_detail_page_route_serves_web_ui(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    response = TestClient(main.app).get("/tasks/task_123")

    assert response.status_code == 200
    assert "Nomi Task Detail" in response.text
    assert "taskDetailRoot" in response.text
    assert "/static/task-detail.js" in response.text


def test_task_detail_static_page_exposes_steps_evidence_and_artifacts_sections():
    static_dir = Path(__file__).resolve().parents[1] / "app" / "static"
    html = (static_dir / "task.html").read_text(encoding="utf-8")
    script = (static_dir / "task-detail.js").read_text(encoding="utf-8")

    assert "任务步骤" in html
    assert "证据链接" in html
    assert "交付文件" in html
    assert "fetchTaskDetail" in script
    assert "/api/tasks/" in script
    assert "/artifacts" in script
