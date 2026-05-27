import json

import pytest
import sys
from pathlib import Path
from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_password_header_accepts_configured_password(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app.auth import is_authorized

    assert is_authorized("secret") is True
    assert is_authorized("wrong") is False
    assert is_authorized(None) is False


@pytest.mark.asyncio
async def test_qwen_client_reads_openai_compatible_response(monkeypatch):
    from app.model_client import QwenClient

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "你好，我可以帮你。"}}]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json, timeout):
            calls.append((url, json, timeout))
            return Response()

    monkeypatch.setattr("app.model_client.httpx.AsyncClient", Client)

    client = QwenClient("http://model.local:9161/")
    answer = await client.chat(
        [{"role": "user", "content": "你好"}],
        temperature=0.2,
    )

    assert answer == "你好，我可以帮你。"
    assert calls[0][0] == "http://model.local:9161/v1/chat/completions"
    assert calls[0][1]["messages"][0]["content"] == "你好"


@pytest.mark.asyncio
async def test_qwen_client_streams_openai_compatible_chunks(monkeypatch):
    from app.model_client import QwenClient

    calls = []

    class Line:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            for line in [
                'data: {"choices":[{"delta":{"content":"你"}}]}',
                'data: {"choices":[{"delta":{"content":"好"}}]}',
                "data: [DONE]",
            ]:
                yield line

    class Stream:
        async def __aenter__(self):
            return Line("")

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url, json, timeout):
            calls.append((method, url, json, timeout))
            return Stream()

    monkeypatch.setattr("app.model_client.httpx.AsyncClient", Client)

    chunks = []
    async for chunk in QwenClient("http://model.local:9161/").stream_chat(
        [{"role": "user", "content": "你好"}],
        temperature=0.2,
    ):
        chunks.append(chunk)

    assert chunks == ["你", "好"]
    assert calls[0][0] == "POST"
    assert calls[0][2]["stream"] is True


def test_memory_delete_requires_password(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    client = TestClient(main.app)
    response = client.post("/memory/delete", json={"memory_id": "11111111-1111-1111-1111-111111111111"})

    assert response.status_code == 401


def test_memory_delete_accepts_json_body_with_password(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    executed = []

    class Cursor:
        rowcount = 1

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            executed.append((sql, params))
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())

    client = TestClient(main.app)
    response = client.post(
        "/memory/delete",
        json={"memory_id": "11111111-1111-1111-1111-111111111111"},
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"deleted": 1}
    assert "DELETE FROM semantic_memory" in executed[0][0]


def test_collector_settings_can_pause_source_and_event_is_rejected(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    executed = []
    settings = {"gmail": {"enabled": True, "paused_until": None, "reason": ""}}

    class Cursor:
        rowcount = 1

        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchall(self):
            return self.rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            executed.append((sql, params))
            normalized = " ".join(sql.split())
            if "FROM collector_settings" in normalized and "SELECT source" in normalized:
                return Cursor(
                    [
                        (
                            "gmail",
                            settings["gmail"]["enabled"],
                            settings["gmail"]["paused_until"],
                            settings["gmail"]["reason"],
                            {},
                            "2026-05-26T00:00:00+00:00",
                        )
                    ]
                )
            if "INSERT INTO collector_settings" in normalized:
                source, enabled, paused_until, reason, metadata = params
                settings[source] = {
                    "enabled": enabled,
                    "paused_until": paused_until,
                    "reason": reason,
                    "metadata": metadata,
                }
                return Cursor()
            if "SELECT enabled, paused_until" in normalized:
                current = settings.get(params[0], {"enabled": True, "paused_until": None, "reason": ""})
                return Cursor([(current["enabled"], current["paused_until"], current["reason"])])
            raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr(main, "db", lambda: Conn())

    client = TestClient(main.app)
    before = client.get("/api/collectors/settings", headers={"x-par-password": "secret"})
    assert before.status_code == 200
    before_collectors = {item["source"]: item for item in before.json()["collectors"]}
    assert before_collectors["gmail"]["enabled"] is True
    assert before_collectors["calendar"]["enabled"] is True

    updated = client.patch(
        "/api/collectors/settings/gmail",
        headers={"x-par-password": "secret"},
        json={"enabled": False, "reason": "manual pause during login"},
    )
    assert updated.status_code == 200
    assert updated.json()["source"] == "gmail"
    assert updated.json()["enabled"] is False
    assert "manual pause" in updated.json()["reason"]

    rejected = client.post(
        "/event",
        json={"source": "gmail", "event_type": "gmail_message_preview", "raw_data": {"subject": "test"}},
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["source"] == "gmail"
    assert rejected.json()["detail"]["enabled"] is False


def test_event_endpoint_protects_raw_payload_before_storage_and_queue(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    inserted = []
    queued = []

    class Cursor:
        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchone(self):
            return self.rows[0] if self.rows else None

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            if "SELECT enabled, paused_until" in normalized:
                return Cursor()
            if "INSERT INTO events" in normalized:
                inserted.append(params)
                return Cursor()
            raise AssertionError(f"Unexpected SQL: {sql}")

    class Redis:
        def xadd(self, stream, fields):
            queued.append((stream, fields))

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: Redis())

    client = TestClient(main.app)
    response = client.post(
        "/event",
        json={
            "source": "gmail",
            "event_type": "gmail_thread_snapshot",
            "raw_data": {
                "subject": "安全提醒：验证码 839201",
                "body": "身份证 110105199001011234，银行卡 6222020202020202020，OAuth 链接 https://x.test/cb#access_token=tok_abc123",
            },
        },
    )

    assert response.status_code == 200
    stored_payload = inserted[0][4]
    queued_payload = queued[0][1]["raw_data"]
    combined = f"{stored_payload} {queued_payload}"
    assert "839201" not in combined
    assert "110105199001011234" not in combined
    assert "6222020202020202020" not in combined
    assert "tok_abc123" not in combined
    assert "安全提醒" in combined
    assert "身份证" in combined
    protected = json.loads(stored_payload)
    assert protected["sensitive"] is True
    assert "verification_code" in protected["sensitive_reasons"]
    assert "id_card" in protected["sensitive_reasons"]
    assert "bank_card" in protected["sensitive_reasons"]
    assert queued[0][0] == "events:raw"


def test_event_endpoint_keeps_encrypted_private_raw_payload_for_authorized_read(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("RAW_DATA_ENCRYPTION_KEY", "local-only-secret")

    from app import main

    original = {
        "subject": "安全提醒：验证码 839201",
        "body": "身份证 110105199001011234，银行卡 6222020202020202020",
    }
    encrypted = main.encrypt_private_raw_data(original)

    assert encrypted["format"] == "fernet-json-v1"
    assert "839201" not in encrypted["ciphertext"]
    assert "110105199001011234" not in encrypted["ciphertext"]
    assert main.decrypt_private_raw_data(encrypted) == original

    class Cursor:
        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchone(self):
            return self.rows[0] if self.rows else None

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            if "SELECT raw_data_private" in normalized:
                return Cursor([(encrypted,)])
            raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr(main, "db", lambda: Conn())

    client = TestClient(main.app)
    unauthorized = client.get("/api/events/11111111-1111-1111-1111-111111111111/private-raw")
    assert unauthorized.status_code == 401

    authorized = client.get(
        "/api/events/11111111-1111-1111-1111-111111111111/private-raw",
        headers={"x-par-password": "secret"},
    )
    assert authorized.status_code == 200
    assert authorized.json()["raw_data"] == original


def test_collector_status_merges_settings_and_health(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    class Cursor:
        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchall(self):
            return self.rows

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            if "FROM collector_settings" in normalized:
                return Cursor(
                    [
                        ("gmail", True, None, "", {}, "2026-05-26T00:00:00+00:00"),
                        ("whatsapp", False, None, "user paused from UI", {}, "2026-05-26T00:00:00+00:00"),
                    ]
                )
            if "FROM collector_health" in normalized:
                return Cursor(
                    [
                        ("gmail", "healthy", "2026-05-26T01:00:00+00:00", "2026-05-26T01:01:00+00:00", 0, {"preview_count": 10}, "2026-05-26T01:01:00+00:00"),
                        ("whatsapp", "degraded", None, "2026-05-26T01:02:00+00:00", 1, {"message": "login needed"}, "2026-05-26T01:02:00+00:00"),
                    ]
                )
            raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr(main, "db", lambda: Conn())

    client = TestClient(main.app)
    response = client.get("/api/collectors/status", headers={"x-par-password": "secret"})

    assert response.status_code == 200
    gmail = next(item for item in response.json()["collectors"] if item["source"] == "gmail")
    whatsapp = next(item for item in response.json()["collectors"] if item["source"] == "whatsapp")
    assert gmail["enabled"] is True
    assert gmail["health_status"] == "healthy"
    assert gmail["details"] == {"preview_count": 10}
    assert whatsapp["enabled"] is False
    assert whatsapp["health_status"] == "degraded"


def test_memory_governance_filters_events_and_exposes_sensitive_flag(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    class Cursor:
        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchall(self):
            return self.rows

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            if "FROM events e" in normalized:
                assert "e.source = %s" in normalized
                assert "COALESCE((e.raw_data->>'sensitive')::boolean, false) = %s" in normalized
                return Cursor(
                    [
                        (
                            "11111111-1111-1111-1111-111111111111",
                            "gmail",
                            "gmail_thread_snapshot",
                            {"subject": "安全提醒", "sensitive": True, "sensitive_reasons": ["verification_code"]},
                            "2026-05-26T01:00:00+00:00",
                            "处理安全提醒",
                            "email_todo",
                            0.8,
                        )
                    ]
                )
            if "FROM semantic_memory" in normalized:
                return Cursor([])
            if "FROM memory_states" in normalized:
                return Cursor([])
            raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr(main, "db", lambda: Conn())

    client = TestClient(main.app)
    response = client.get(
        "/api/memory/governance?source=gmail&sensitive=true&q=安全",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["filters"] == {"source": "gmail", "sensitive": True, "q": "安全"}
    assert body["events"][0]["sensitive"] is True
    assert body["events"][0]["sensitive_reasons"] == ["verification_code"]
    assert body["events"][0]["summary"] == "处理安全提醒"


def test_memory_correction_updates_semantic_memory_content_and_audit_log(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    executed = []

    class Cursor:
        rowcount = 1

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            executed.append((sql, params))
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())

    client = TestClient(main.app)
    response = client.patch(
        "/api/memory/semantic/11111111-1111-1111-1111-111111111111",
        headers={"x-par-password": "secret"},
        json={"summary": "用户更正后的长期记忆。", "reason": "manual correction"},
    )

    assert response.status_code == 200
    assert response.json() == {"updated": 1}
    assert "UPDATE semantic_memory" in executed[0][0]
    assert "INSERT INTO memory_audit_log" in executed[1][0]


def test_tool_catalog_requires_password(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    client = TestClient(main.app)

    response = client.get("/api/tools/catalog")

    assert response.status_code == 401


def test_tool_catalog_returns_twenty_high_frequency_tools_with_permission_levels(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    client = TestClient(main.app)

    response = client.get("/api/tools/catalog", headers={"x-par-password": "secret"})

    assert response.status_code == 200
    payload = response.json()
    tools = payload["tools"]
    assert len(tools) == 20
    by_id = {tool["id"]: tool for tool in tools}
    assert by_id["gmail"]["phase"] == "core"
    assert by_id["browser_automation"]["recommended_adapter"] == "playwright_mcp"
    assert by_id["uber"]["risk_level"] == "high"
    assert "external_execution" in by_id["uber"]["permission_levels"]
    assert by_id["amazon_shopping"]["confirmation_required"] is True
    assert payload["permission_policy"]["external_execution"] == "requires_explicit_confirmation"


def test_tool_route_prefers_core_pipeline_for_reply(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    client = TestClient(main.app)

    response = client.post(
        "/api/tools/route",
        headers={"x-par-password": "secret"},
        json={"request": "帮我回复 Alice，说明周五八点可以"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["route_type"] == "core_pipeline"
    assert payload["pipeline"]["id"] == "reply_pipeline"
    assert payload["capability"]["id"] == "communication.message.draft_reply"
    assert payload["execution_guard"]["requires_confirmation"] is True


def test_tool_route_uses_long_tail_candidates_for_hubspot(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    client = TestClient(main.app)

    response = client.post(
        "/api/tools/route",
        headers={"x-par-password": "secret"},
        json={"request": "帮我把这个客户加到 HubSpot，并备注他对企业版感兴趣"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["route_type"] == "long_tail_tool"
    assert payload["capability"]["id"] == "business.crm.contact.upsert"
    assert payload["candidate_tools"][0]["id"] == "crm"
    assert payload["candidate_tools"][0]["recommended_adapter"] == "composio_or_zapier_mcp"
    assert payload["execution_guard"]["requires_confirmation"] is True


def test_tool_route_falls_back_to_browser_for_unknown_site(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    client = TestClient(main.app)

    response = client.post(
        "/api/tools/route",
        headers={"x-par-password": "secret"},
        json={"request": "帮我去一个不支持 MCP 的网站填写报名表"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["route_type"] == "long_tail_tool"
    assert payload["capability"]["id"] == "automation.browser.operate"
    assert payload["candidate_tools"][0]["id"] == "browser_automation"


def test_composio_status_reports_unconfigured_without_calling_network(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
    from fastapi.testclient import TestClient
    from app import main

    def fail_get(*args, **kwargs):
        raise AssertionError("missing API key should not call Composio")

    monkeypatch.setattr(main.httpx, "get", fail_get)
    client = TestClient(main.app)

    response = client.get("/api/tools/composio/status", headers={"x-par-password": "secret"})

    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert response.json()["reachable"] is False


def test_composio_status_uses_v3_mcp_servers_endpoint(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("COMPOSIO_API_KEY", "test-key")
    from fastapi.testclient import TestClient
    from app import main

    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"items": [{"id": "server_1"}, {"id": "server_2"}]}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(main.httpx, "get", fake_get)
    client = TestClient(main.app)

    response = client.get("/api/tools/composio/status", headers={"x-par-password": "secret"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is True
    assert payload["reachable"] is True
    assert payload["mcp_server_count"] == 2
    assert captured["url"] == "https://backend.composio.dev/api/v3/mcp/servers"
    assert captured["headers"]["x-api-key"] == "test-key"
