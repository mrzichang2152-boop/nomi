import os
import sys
from pathlib import Path

import httpx
import psycopg
from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")
os.environ.setdefault("APP_PASSWORD", "secret")


class EmptyConn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def execute(self, sql, params=()):
        return EmptyCursor()


class EmptyCursor:
    def fetchone(self):
        return None

    def fetchall(self):
        return []


def test_android_chat_route_reports_model_timeout_without_dropping_connection(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    async def timeout_chat(messages):
        raise httpx.TimeoutException("upstream model timed out")

    class TimeoutGateway:
        chat = staticmethod(timeout_chat)

    turn_counter = {"value": 0}

    def fake_persist_turn(conn, redis_obj, *, role, content, conversation_id, client_type, **kwargs):
        turn_counter["value"] += 1
        return {
            "event_id": f"event-{turn_counter['value']}",
            "turn_id": f"turn-{turn_counter['value']}",
            "conversation_id": conversation_id or "11111111-1111-1111-1111-111111111111",
        }

    monkeypatch.setattr(main, "db", lambda: EmptyConn())
    monkeypatch.setattr(main, "redis_client", lambda: object())
    monkeypatch.setattr(main, "persist_assistant_turn", fake_persist_turn)
    monkeypatch.setattr(main, "retrieve_current_source_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_assistant_dialogue_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_agenda_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "retrieve_active_task_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(main, "model_gateway", lambda: TimeoutGateway())

    response = TestClient(main.app, raise_server_exceptions=False).post(
        "/api/chat",
        headers={"x-par-password": "secret"},
        json={
            "message": "Android 真机测试",
            "client_type": "android",
            "client_context_delta": [{"role": "user", "content": "上一轮"}],
        },
    )

    assert response.status_code == 503
    body = response.json()
    assert body["detail"]["error"] == "model_timeout"
    assert "did not respond" in body["detail"]["message"]


def test_android_career_board_returns_semantic_empty_state_when_schema_is_not_deployed(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    class MissingCareerTablesConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            raise psycopg.errors.UndefinedTable("relation career_profiles does not exist")

    monkeypatch.setattr(main, "db", lambda: MissingCareerTablesConn())

    response = TestClient(main.app, raise_server_exceptions=False).get(
        "/api/career/board?limit=50",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "schema_missing"
    assert body["filters"] == {"status": None, "limit": 50}
    assert body["profiles"] == []
    assert body["opportunities"] == []
    assert body["resume_versions"] == []
    assert body["career_resumes"] == []
    assert body["applications"] == []
    assert body["next_actions"] == [
        "deploy_runtime_api_schema",
        "run_career_pipeline_writeback",
        "reload_android_career_board",
    ]
