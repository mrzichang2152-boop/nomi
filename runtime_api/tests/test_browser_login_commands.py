import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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


def test_browser_open_queues_linkedin_login_page_not_heavy_homepage(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.long_tail_agent import LongTailEventStore

    queued = []
    main._LONG_TAIL_EVENT_STORE = LongTailEventStore()

    class Redis:
        def rpush(self, key, value):
            queued.append((key, json.loads(value)))
            return 1

    monkeypatch.setattr(main, "redis_client", lambda: Redis())

    response = TestClient(main.app).post(
        "/api/browser/open",
        json={"source": "linkedin"},
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["source"] == "linkedin"
    assert body["target_url"] == "https://www.linkedin.com/login"
    assert queued[0][0] == "browser:commands"
    assert queued[0][1]["host_fragment"] == "linkedin.com"
    assert queued[0][1]["url"] == "https://www.linkedin.com/login"


def test_browser_open_linkedin_profile_queues_restricted_recruiter_profile_command(monkeypatch):
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
        "/api/browser/open-linkedin-profile",
        json={
            "profile_url": "https://www.linkedin.com/in/jane-chen-recruiter/?miniProfileUrn=abc",
            "reason": "validate recruiter contact snapshot from current job search",
        },
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["source"] == "linkedin"
    assert body["target_url"] == "https://www.linkedin.com/in/jane-chen-recruiter/"
    assert queued[0][0] == "browser:commands"
    command = queued[0][1]
    assert command["action"] == "open_url_direct"
    assert command["source"] == "linkedin"
    assert command["url"] == "https://www.linkedin.com/in/jane-chen-recruiter/"
    assert command["host_fragment"] == "linkedin.com"
    assert command["expected_event_type"] == "linkedin_contact_snapshot"
    events = store.task_events("browser_linkedin_profile:jane-chen-recruiter")
    assert [event["event_type"] for event in events] == [
        "executor.action_requested",
        "policy.checked",
        "executor.live_completed",
    ]
    assert events[0]["payload"]["action_request"]["target"]["kind"] == "linkedin_profile_url"
    assert events[2]["payload"]["live_result"]["external_side_effect"] is False


def test_browser_open_linkedin_profile_rejects_non_profile_urls(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    client = TestClient(main.app)
    for url in [
        "https://www.linkedin.com/jobs/search/?keywords=recruiter",
        "https://evil.example/in/jane-chen-recruiter/",
        "javascript:alert(1)",
    ]:
        response = client.post(
            "/api/browser/open-linkedin-profile",
            json={"profile_url": url},
            headers={"x-par-password": "secret"},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "unsupported_linkedin_profile_url"


def test_browser_open_linkedin_job_queues_restricted_job_detail_command(monkeypatch):
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
        "/api/browser/open-linkedin-job",
        json={
            "job_url": "https://www.linkedin.com/jobs/view/4378789245/?trackingId=abc",
            "reason": "open recommended job inside the logged-in managed LinkedIn browser",
        },
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["source"] == "linkedin"
    assert body["target_url"] == "https://www.linkedin.com/jobs/view/4378789245/"
    assert body["expected_event_type"] == "linkedin_job_description_snapshot"
    assert queued[0][0] == "browser:commands"
    command = queued[0][1]
    assert command["action"] == "open_linkedin_job_detail"
    assert command["source"] == "linkedin"
    assert command["url"] == "https://www.linkedin.com/jobs/view/4378789245/"
    assert command["host_fragment"] == "linkedin.com"
    assert command["expected_event_type"] == "linkedin_job_description_snapshot"
    events = store.task_events("browser_linkedin_job:4378789245")
    assert [event["event_type"] for event in events] == [
        "executor.action_requested",
        "policy.checked",
        "executor.live_completed",
    ]
    assert events[0]["payload"]["action_request"]["target"]["kind"] == "linkedin_job_detail_url"
    assert events[2]["payload"]["live_result"]["external_side_effect"] is False


def test_browser_open_linkedin_job_rejects_non_job_detail_urls(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    client = TestClient(main.app)
    for url in [
        "https://www.linkedin.com/jobs/search/?keywords=backend",
        "https://www.linkedin.com/in/jane-chen-recruiter/",
        "https://evil.example/jobs/view/4378789245/",
        "javascript:alert(1)",
    ]:
        response = client.post(
            "/api/browser/open-linkedin-job",
            json={"job_url": url},
            headers={"x-par-password": "secret"},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "unsupported_linkedin_job_url"


def test_browser_search_linkedin_contacts_queues_generated_people_search_command(monkeypatch):
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
        "/api/browser/search-linkedin-contacts",
        json={
            "company": "Example AI",
            "job_title": "Backend Engineer",
            "location": "Singapore",
            "reason": "find likely recruiter or hiring manager for the open role",
        },
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["source"] == "linkedin"
    assert body["host_fragment"] == "linkedin.com"
    assert body["expected_event_type"] == "linkedin_contact_snapshot"
    assert body["search_terms"]["company"] == "Example AI"
    assert body["search_terms"]["job_title"] == "Backend Engineer"
    assert body["search_terms"]["location"] == "Singapore"

    assert queued[0][0] == "browser:commands"
    command = queued[0][1]
    assert command["action"] == "open_linkedin_contact_search"
    assert command["source"] == "linkedin"
    assert command["host_fragment"] == "linkedin.com"
    assert command["expected_event_type"] == "linkedin_contact_snapshot"
    assert command["company"] == "Example AI"
    assert command["job_title"] == "Backend Engineer"
    assert command["location"] == "Singapore"
    parsed = urlparse(command["url"])
    assert parsed.scheme == "https"
    assert parsed.netloc == "www.linkedin.com"
    assert parsed.path == "/search/results/people/"
    keywords = parse_qs(parsed.query)["keywords"][0]
    assert "Example AI" in keywords
    assert "Backend Engineer" in keywords
    assert "Singapore" in keywords
    assert "recruiter" in keywords
    assert "talent acquisition" in keywords
    assert "hiring manager" in keywords

    events = store.task_events("browser_linkedin_contact_search:example-ai-backend-engineer")
    assert [event["event_type"] for event in events] == [
        "executor.action_requested",
        "policy.checked",
        "executor.live_completed",
    ]
    assert events[0]["payload"]["action_request"]["target"]["kind"] == "linkedin_people_search"
    assert events[2]["payload"]["live_result"]["external_side_effect"] is False


def test_browser_search_linkedin_jobs_queues_generated_jobs_search_command(monkeypatch):
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
        "/api/browser/search-linkedin-jobs",
        json={
            "query": "Backend Engineer",
            "location": "Singapore",
            "reason": "find suitable jobs for the user before ranking",
        },
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["source"] == "linkedin"
    assert body["host_fragment"] == "linkedin.com"
    assert body["expected_event_type"] == "linkedin_job_search_results"
    assert body["search_terms"]["query"] == "Backend Engineer"
    assert body["search_terms"]["location"] == "Singapore"

    assert queued[0][0] == "browser:commands"
    command = queued[0][1]
    assert command["action"] == "open_linkedin_job_search"
    assert command["source"] == "linkedin"
    assert command["host_fragment"] == "linkedin.com"
    assert command["expected_event_type"] == "linkedin_job_search_results"
    parsed = urlparse(command["url"])
    assert parsed.scheme == "https"
    assert parsed.netloc == "www.linkedin.com"
    assert parsed.path == "/jobs/search/"
    params = parse_qs(parsed.query)
    assert params["keywords"] == ["Backend Engineer"]
    assert params["location"] == ["Singapore"]

    events = store.task_events("browser_linkedin_job_search:backend-engineer-singapore")
    assert [event["event_type"] for event in events] == [
        "executor.action_requested",
        "policy.checked",
        "executor.live_completed",
    ]
    assert events[0]["payload"]["action_request"]["target"]["kind"] == "linkedin_jobs_search"
    assert events[2]["payload"]["live_result"]["external_side_effect"] is False


def test_browser_search_linkedin_jobs_rejects_empty_query(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    response = TestClient(main.app).post(
        "/api/browser/search-linkedin-jobs",
        json={"query": "", "location": ""},
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "empty_linkedin_job_search"


def test_browser_search_linkedin_contacts_rejects_empty_search(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    response = TestClient(main.app).post(
        "/api/browser/search-linkedin-contacts",
        json={"company": "", "job_title": ""},
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "empty_linkedin_contact_search"


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


def test_linkedin_contact_search_records_queue_status_and_status_endpoint(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    store: dict[str, str] = {}
    queued: list[dict[str, object]] = []

    class Redis:
        def rpush(self, key, value):
            assert key == "browser:commands"
            queued.append(json.loads(value))
            return 1

        def setex(self, key, ttl, value):
            store[key] = value
            return True

        def get(self, key):
            return store.get(key)

    monkeypatch.setattr(main, "redis_client", lambda: Redis())

    response = TestClient(main.app).post(
        "/api/browser/search-linkedin-contacts",
        json={"company": "ByteDance", "job_title": "Backend Engineer", "location": "Singapore"},
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    command_id = response.json()["command_id"]
    assert queued[0]["command_id"] == command_id

    status = TestClient(main.app).get(
        f"/api/browser/commands/{command_id}/status",
        headers={"x-par-password": "secret"},
    )
    assert status.status_code == 200
    assert status.json()["status"] == "queued"
    assert status.json()["source"] == "linkedin"
    assert status.json()["expected_event_type"] == "linkedin_contact_snapshot"


def test_browser_command_result_updates_status_for_linkedin_validation(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    store: dict[str, str] = {}

    class Redis:
        def setex(self, key, ttl, value):
            store[key] = value
            return True

        def get(self, key):
            return store.get(key)

    monkeypatch.setattr(main, "redis_client", lambda: Redis())

    response = TestClient(main.app).post(
        "/api/browser/commands/cmd-linkedin-1/result",
        json={
            "status": "opened",
            "source": "linkedin",
            "expected_event_type": "linkedin_contact_snapshot",
            "details": {"target_url": "https://www.linkedin.com/search/results/people/?keywords=ByteDance%20recruiter"},
        },
        headers={"x-par-password": "secret"},
    )
    assert response.status_code == 200

    status = TestClient(main.app).get(
        "/api/browser/commands/cmd-linkedin-1/status",
        headers={"x-par-password": "secret"},
    )
    assert status.status_code == 200
    assert status.json()["status"] == "opened"
    assert status.json()["details"]["target_url"].startswith("https://www.linkedin.com/search/results/people/")


def test_browser_type_queues_sanitized_manual_text_command(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    queued = []

    class Redis:
        def rpush(self, key, value):
            queued.append((key, json.loads(value)))
            return 1

    monkeypatch.setattr(main, "redis_client", lambda: Redis())

    response = TestClient(main.app).post(
        "/api/browser/type",
        json={"text": "mrzichang2152@gmail.com"},
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert queued[0][0] == "browser:commands"
    assert queued[0][1]["action"] == "type_text"
    assert queued[0][1]["text"] == "mrzichang2152@gmail.com"
    assert queued[0][1]["submit"] is False


def test_browser_command_next_pops_one_sanitized_type_command(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    command = {
        "command_id": "cmd-type-1",
        "action": "type_text",
        "text": "hello",
        "submit": False,
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
