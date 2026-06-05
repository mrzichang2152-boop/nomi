import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_browser_open_queues_whatsapp_login_command(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.long_tail_agent import LongTailEventStore

    queued = []
    store = LongTailEventStore()
    main._LONG_TAIL_EVENT_STORE = store

    class Redis:
        def rpush(self, key, value):
            queued.append((key, json.loads(value)))
            return 1

    monkeypatch.setattr(main, "redis_client", lambda: Redis())

    response = TestClient(main.app).post(
        "/api/browser/open",
        json={"source": "whatsapp"},
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["source"] == "whatsapp"
    assert body["target_url"] == "https://web.whatsapp.com/"
    assert queued[0][0] == "browser:commands"
    assert queued[0][1]["action"] == "open_url"
    assert queued[0][1]["host_fragment"] == "web.whatsapp.com"
    assert queued[0][1]["url"] == "https://web.whatsapp.com/"
    events = store.task_events("browser_login:whatsapp")
    assert [event["event_type"] for event in events] == [
        "executor.action_requested",
        "policy.checked",
        "executor.live_completed",
    ]
    assert events[0]["payload"]["action_request"]["action_type"] == "browser.open_url"
    assert events[1]["payload"]["policy_report"]["status"] == "allowed"
    assert events[2]["payload"]["live_result"]["status"] == "queued"
    assert events[2]["payload"]["live_result"]["external_side_effect"] is False


def test_browser_command_next_pops_one_sanitized_command(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    command = {
        "command_id": "cmd-1",
        "action": "open_url",
        "source": "telegram",
        "url": "https://web.telegram.org/",
        "host_fragment": "web.telegram.org",
        "created_at": "2026-06-01T00:00:00+00:00",
    }

    class Redis:
        def lpop(self, key):
            assert key == "browser:commands"
            return json.dumps(command)

    monkeypatch.setattr(main, "redis_client", lambda: Redis())

    response = TestClient(main.app).get(
        "/api/browser/commands/next",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    assert response.json()["command"] == command


def test_browser_open_rejects_unknown_or_arbitrary_url(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    response = TestClient(main.app).post(
        "/api/browser/open",
        json={"source": "https://evil.example/login"},
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "unsupported_browser_source"


def test_composio_connect_does_not_reauthorize_already_connected_toolkit(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    calls = {"authorize": 0}

    class Session:
        session_id = "session_1"
        mcp = {"url": "https://mcp.example", "headers": {"x": "y"}}

        def toolkits(self):
            class Result:
                items = [
                    {
                        "slug": "gmail",
                        "name": "Gmail",
                        "connection": {
                            "is_active": True,
                            "connected_account_id": "ca_existing",
                        },
                    }
                ]

            return Result()

        def authorize(self, toolkit_slug, callback_url=None):
            calls["authorize"] += 1
            raise AssertionError("already-connected toolkit should not create a new auth link")

    policy = {
        "session_kind": "readonly",
        "toolkits": {"enable": ["gmail"]},
        "tags": {"enable": ["readOnlyHint"], "disable": ["destructiveHint"]},
        "manage_connections": False,
    }
    monkeypatch.setattr(main, "get_or_create_composio_session", lambda user_id, session_kind: (Session(), policy))
    monkeypatch.setattr(main, "current_composio_user_id", lambda: "nomi_owner")

    response = TestClient(main.app).post(
        "/api/integrations/composio/connect/gmail",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "already_connected"
    assert response.json()["redirect_url"] == ""
    assert calls["authorize"] == 0
