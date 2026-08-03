import json
import os

import pytest
import sys
from pathlib import Path
from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


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
async def test_qwen_client_uses_configured_timeout(monkeypatch):
    monkeypatch.setenv("MODEL_REQUEST_TIMEOUT_SECONDS", "180")
    from app.model_client import QwenClient

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "ok"}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json, timeout):
            calls.append(timeout)
            return Response()

    monkeypatch.setattr("app.model_client.httpx.AsyncClient", Client)

    assert await QwenClient("http://model.local:9161/").chat([{"role": "user", "content": "hi"}]) == "ok"
    assert calls == [180.0]


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


@pytest.mark.asyncio
async def test_chat_completion_client_calls_4sapi_openai_compatible_endpoint_with_user_key(monkeypatch):
    from app.model_client import ChatCompletionClient, ModelClientConfig

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "pong"}}]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json, headers, timeout):
            calls.append((url, json, headers, timeout))
            return Response()

    monkeypatch.setattr("app.model_client.httpx.AsyncClient", Client)

    client = ChatCompletionClient(
        ModelClientConfig(
            provider_type="openai_compatible",
            base_url="https://4sapi.com/v1",
            model="gpt-5.4-mini",
            api_key="sk-user-key",
            auth_header_format="raw",
        )
    )
    answer = await client.chat([{"role": "user", "content": "ping"}], temperature=0.2)

    assert answer == "pong"
    assert calls[0][0] == "https://4sapi.com/v1/chat/completions"
    assert calls[0][1]["model"] == "gpt-5.4-mini"
    assert calls[0][1]["messages"] == [{"role": "user", "content": "ping"}]
    assert calls[0][1]["stream"] is False
    assert calls[0][2]["Authorization"] == "sk-user-key"
    assert calls[0][2]["Accept"] == "application/json"


@pytest.mark.asyncio
async def test_chat_completion_client_calls_anthropic_messages_api(monkeypatch):
    from app.model_client import ChatCompletionClient, ModelClientConfig

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"content": [{"type": "text", "text": "anthropic answer"}]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json, headers, timeout):
            calls.append((url, json, headers, timeout))
            return Response()

    monkeypatch.setattr("app.model_client.httpx.AsyncClient", Client)

    client = ChatCompletionClient(
        ModelClientConfig(
            provider_type="anthropic",
            base_url="https://api.anthropic.com/v1",
            model="claude-sonnet-4-5",
            api_key="anthropic-key",
        )
    )
    answer = await client.chat(
        [
            {"role": "system", "content": "你是 Nomi。"},
            {"role": "user", "content": "你好"},
        ],
        temperature=0.3,
    )

    assert answer == "anthropic answer"
    assert calls[0][0] == "https://api.anthropic.com/v1/messages"
    assert calls[0][1]["model"] == "claude-sonnet-4-5"
    assert calls[0][1]["system"] == "你是 Nomi。"
    assert calls[0][1]["messages"] == [{"role": "user", "content": "你好"}]
    assert calls[0][1]["max_tokens"] == 8192
    assert calls[0][2]["x-api-key"] == "anthropic-key"
    assert calls[0][2]["anthropic-version"] == "2023-06-01"


@pytest.mark.asyncio
async def test_chat_completion_client_calls_google_generate_content_api(monkeypatch):
    from app.model_client import ChatCompletionClient, ModelClientConfig

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "google answer"}]}}
                ]
            }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json, headers, timeout):
            calls.append((url, json, headers, timeout))
            return Response()

    monkeypatch.setattr("app.model_client.httpx.AsyncClient", Client)

    client = ChatCompletionClient(
        ModelClientConfig(
            provider_type="google",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            model="gemini-2.5-flash",
            api_key="google-key",
        )
    )
    answer = await client.chat(
        [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好，我是 Nomi。"},
            {"role": "user", "content": "继续"},
        ]
    )

    assert answer == "google answer"
    assert calls[0][0] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=google-key"
    assert calls[0][1]["contents"][0]["role"] == "user"
    assert calls[0][1]["contents"][1]["role"] == "model"
    assert calls[0][1]["generationConfig"]["temperature"] == 0.4


def test_memory_delete_requires_password(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    client = TestClient(main.app)
    response = client.post("/memory/delete", json={"memory_id": "11111111-1111-1111-1111-111111111111"})

    assert response.status_code == 401


def test_model_status_endpoint_reports_configured_provider(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("MODEL_PROVIDER_ID", "qwen36_primary")
    monkeypatch.setenv("MODEL_BASE_URL", "http://model.local:9161")
    monkeypatch.setenv("MODEL_NAME", "qwen3.6")

    from app import main

    client = TestClient(main.app)
    response = client.get("/api/model/status", headers={"x-par-password": "secret"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_provider_id"] == "qwen36_primary"
    assert payload["unavailable"] is False
    assert payload["providers"][0]["provider_id"] == "qwen36_primary"
    assert payload["providers"][0]["model"] == "qwen3.6"
    assert payload["providers"][0]["base_url"] == "http://model.local:9161"


def test_model_status_endpoint_requires_password(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    client = TestClient(main.app)
    response = client.get("/api/model/status")

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


def test_memory_delete_can_remove_state_memory_and_write_audit(monkeypatch):
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
        json={"state_key": "current_focus"},
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"deleted": 1}
    assert "DELETE FROM memory_states WHERE key = %s" in executed[0][0]
    assert executed[0][1] == ("current_focus",)
    assert "INSERT INTO memory_audit_log" in executed[1][0]
    assert executed[1][1][2] == "memory_state"
    assert executed[1][1][3] == "current_focus"


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


def test_event_endpoint_does_not_requeue_same_linkedin_profile_snapshot(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    inserted_event_ids = set()
    queued = []

    class Cursor:
        def __init__(self, rows=None, rowcount=0):
            self.rows = rows or []
            self.rowcount = rowcount

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
                event_id = str(params[0])
                if event_id in inserted_event_ids:
                    return Cursor(rowcount=0)
                inserted_event_ids.add(event_id)
                return Cursor(rowcount=1)
            raise AssertionError(f"Unexpected SQL: {sql}")

    class Redis:
        def xadd(self, stream, fields):
            queued.append((stream, fields))

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: Redis())

    client = TestClient(main.app)
    base_payload = {
        "source": "linkedin",
        "event_type": "linkedin_profile_snapshot",
        "raw_data": {
            "url": "https://www.linkedin.com/feed",
            "title": "Feed | LinkedIn",
            "profile_name": "张子长",
            "headline": "Program Manager at Beijing Sankuai Technology Ltd.",
            "location": "Beijing",
            "company": "Beijing Sankuai Technology Ltd.",
            "capture_scope": "visible_profile_snapshot",
            "text": "张子长\nProgram Manager at Beijing Sankuai Technology Ltd.\nBeijing\nBeijing Sankuai Technology Ltd.",
        },
    }

    first = client.post("/event", json=base_payload)
    second = client.post(
        "/event",
        json={
            **base_payload,
            "raw_data": {
                **base_payload["raw_data"],
                "url": "https://www.linkedin.com/feed/",
            },
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["event_id"] == second.json()["event_id"]
    assert first.json()["status"] == "queued"
    assert second.json()["status"] == "duplicate"
    assert len(inserted_event_ids) == 1
    assert len(queued) == 1


def test_stable_collector_event_key_dedupes_whatsapp_chat_list_message_across_relative_time_labels(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    base = {
        "url": "https://web.whatsapp.com/",
        "title": "(1) WhatsApp",
        "sender": "PHONE_1",
        "message": "NOMI_REG_WA_0629 明天15:30人民广场见，带合同",
        "chat_name": None,
        "source_kind": "direct",
        "capture_scope": "chat_list_preview",
        "timestamp_label": "09:48",
    }

    first_key = main.stable_collector_event_key("whatsapp", "whatsapp_message", base)
    second_key = main.stable_collector_event_key(
        "whatsapp",
        "whatsapp_message",
        {
            **base,
            "title": "WhatsApp",
            "timestamp_label": "昨天",
            "line_count": 18,
        },
    )

    assert first_key
    assert first_key == second_key


def test_stable_collector_event_key_dedupes_outgoing_whatsapp_list_and_visible_dom_sender_labels(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    marker = "NOMI_REAL_WA_20260727_A codename AmberKite deadline 2026-08-09"
    list_key = main.stable_collector_event_key(
        "whatsapp",
        "whatsapp_message",
        {
            "chat_name": "陈子扬",
            "sender": "self",
            "message": marker,
            "message_direction": "outgoing",
            "capture_scope": "chat_list_preview",
        },
    )
    visible_key = main.stable_collector_event_key(
        "whatsapp",
        "whatsapp_message",
        {
            "chat_name": "陈子扬",
            "sender": "子长",
            "message": marker,
            "message_direction": "outgoing",
            "capture_scope": "visible_dom",
        },
    )

    assert list_key
    assert list_key == visible_key


def test_stable_collector_event_key_dedupes_telegram_open_chat_rescans_but_keeps_chat_scope(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    base = {
        "url": "https://web.telegram.org/k/#@yshucheng",
        "title": "Telegram Web",
        "chat_name": "Ask",
        "message": "NOMI_REG_TG_0629 周五10点静安寺地铁站见 Maya",
        "capture_scope": "telegram_open_chat_message",
    }

    first_key = main.stable_collector_event_key("telegram", "telegram_message_preview", base)
    second_key = main.stable_collector_event_key(
        "telegram",
        "telegram_message_preview",
        {
            **base,
            "capture_scope": "telegram_visible_preview",
            "timestamp_label": "June 29",
        },
    )
    other_chat_key = main.stable_collector_event_key(
        "telegram",
        "telegram_message_preview",
        {
            **base,
            "chat_name": "Maya",
        },
    )

    assert first_key
    assert first_key == second_key
    assert other_chat_key != first_key


def test_collect_sensitive_reasons_does_not_label_phone_as_amount(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    reasons = main.collect_sensitive_reasons({"phone": "+86 138 0000 0000"})
    technical_reasons = main.collect_sensitive_reasons(
        {"url": "https://forms.example/apply?token=abc123", "approved_at": "2026-05-28T09:16:57.626043+00:00"}
    )
    payment_reasons = main.collect_sensitive_reasons({"message": "请支付给张三 138 元"})

    assert "phone" in reasons
    assert "amount" not in reasons
    assert "amount" not in technical_reasons
    assert "phone" not in technical_reasons
    assert "amount" in payment_reasons


def test_private_payload_preserves_iso_deadline_time_while_redacting_phone(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    protected = main.protect_private_payload(
        {
            "subject": "申请截止提醒",
            "body": "Please submit before 2026-06-15 18:00. Call +1 415 555 2671 if questions.",
        }
    )

    assert protected["body"] == "Please submit before 2026-06-15 18:00. Call PHONE_1 if questions."
    assert "phone" in protected["sensitive_reasons"]


def test_private_payload_preserves_iso_time_before_chinese_punctuation(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    protected = main.protect_private_payload(
        {
            "text": "面试安排在2026-06-13 10:30，Zoom链接稍后发。联系电话 +86 138 0000 0000。",
        }
    )

    assert protected["text"] == "面试安排在2026-06-13 10:30，Zoom链接稍后发。联系电话 PHONE_1。"
    assert "phone" in protected["sensitive_reasons"]


def test_private_payload_preserves_linkedin_job_detail_urls_while_redacting_phone(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    protected = main.protect_private_payload(
        {
            "url": "https://www.linkedin.com/jobs/view/4404787524/",
            "text": "岗位链接 https://www.linkedin.com/jobs/view/4378789245/，联系电话 +86 138 0000 0000。",
        }
    )

    assert protected["url"] == "https://www.linkedin.com/jobs/view/4404787524/"
    assert "https://www.linkedin.com/jobs/view/4378789245/" in protected["text"]
    assert "PHONE_1" in protected["text"]
    assert "phone" in protected["sensitive_reasons"]


def test_collect_sensitive_reasons_does_not_label_linkedin_job_id_as_phone(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    reasons = main.collect_sensitive_reasons({"url": "https://www.linkedin.com/jobs/view/4404787524/"})

    assert "phone" not in reasons


def test_collect_sensitive_reasons_does_not_label_iso_deadline_time_as_phone(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    reasons = main.collect_sensitive_reasons({"body": "Please submit before 2026-06-15 18:00."})

    assert "phone" not in reasons


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
            if "FROM composio_toolkits" in normalized:
                return Cursor([])
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


def test_collector_status_label_explains_managed_browser_page_recovery(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app.main import collector_status_labels

    label, detail = collector_status_labels(
        "whatsapp",
        enabled=True,
        paused=False,
        auth_status="browser_required",
        browser_login_status="unknown",
        collection_status="degraded",
        details={
            "recovery": "page_reopened",
            "message": "Managed page was missing and has been reopened for collector recovery.",
        },
    )

    assert label == "页面恢复中"
    assert "托管浏览器页面刚被重开" in detail
    assert "下一轮" in detail


def test_collector_status_label_explains_managed_browser_opened_waiting_for_detection(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app.main import collector_status_labels

    label, detail = collector_status_labels(
        "whatsapp",
        enabled=True,
        paused=False,
        auth_status="browser_required",
        browser_login_status="unknown",
        collection_status="healthy",
        details={
            "browser_command": "cmd-1",
            "command_result": {"status": "focused", "url": "https://web.whatsapp.com/"},
        },
    )

    assert label == "浏览器已打开"
    assert "等待下一轮采集确认" in detail


def test_collector_status_exposes_channel_capability_boundaries(monkeypatch):
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
                return Cursor([])
            if "FROM collector_health" in normalized:
                return Cursor([])
            if "FROM composio_toolkits" in normalized:
                return Cursor([])
            raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr(main, "db", lambda: Conn())

    payload = TestClient(main.app).get(
        "/api/collectors/status",
        headers={"x-par-password": "secret"},
    ).json()

    by_source = {item["source"]: item for item in payload["collectors"]}
    gmail_capability = by_source["gmail"]["capability"]
    whatsapp_capability = by_source["whatsapp"]["capability"]
    telegram_capability = by_source["telegram"]["capability"]
    assert gmail_capability["mode"] == "api_or_browser"
    assert "composio:gmail" in gmail_capability["adapters"]
    assert "full_mailbox_sync_when_connected" in gmail_capability["supported_operations"]
    assert whatsapp_capability["mode"] == "managed_browser_visible_dom"
    assert whatsapp_capability["full_history_guarantee"] is False
    assert "visible_chat_list" in whatsapp_capability["supported_operations"]
    assert telegram_capability["mode"] == "managed_browser_visible_dom"
    assert telegram_capability["full_history_guarantee"] is False


def test_collector_status_exposes_auth_browser_and_collection_dimensions(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    now = "2026-06-25T08:00:00+00:00"

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
                        ("gmail", True, None, "", {}, now),
                        ("whatsapp", True, None, "", {}, now),
                        ("telegram", True, None, "", {}, now),
                        ("linkedin", True, None, "", {}, now),
                    ]
                )
            if "FROM collector_health" in normalized:
                return Cursor(
                    [
                        (
                            "gmail",
                            "degraded",
                            None,
                            now,
                            1,
                            {"runtime": "playwright", "login_state": "logged_out", "url": "https://accounts.google.com/v3/signin/accountchooser"},
                            now,
                        ),
                        (
                            "whatsapp",
                            "degraded",
                            None,
                            now,
                            1,
                            {"failure_reason": "login_required", "login_state": "logged_out", "url": "https://web.whatsapp.com/"},
                            now,
                        ),
                        (
                            "telegram",
                            "healthy",
                            now,
                            now,
                            0,
                            {"login_state": "logged_in", "preview_count": 9, "url": "https://web.telegram.org/k/"},
                            now,
                        ),
                        (
                            "linkedin",
                            "degraded",
                            now,
                            now,
                            1,
                            {"login_state": "logged_in", "failure_reason": "no_linkedin_snapshot_match", "url": "https://www.linkedin.com/search/results/people/"},
                            now,
                        ),
                    ]
                )
            if "FROM composio_toolkits" in normalized:
                return Cursor([("gmail", True), ("googlecalendar", False)])
            raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr(main, "db", lambda: Conn())

    payload = TestClient(main.app).get(
        "/api/collectors/status",
        headers={"x-par-password": "secret"},
    ).json()

    by_source = {item["source"]: item for item in payload["collectors"]}
    assert by_source["gmail"]["auth_status"] == "api_connected"
    assert by_source["gmail"]["browser_login_status"] == "logged_out"
    assert by_source["gmail"]["collection_status"] == "degraded"
    assert by_source["gmail"]["status_label"] == "API 已连接"
    assert "浏览器未登录" in by_source["gmail"]["status_detail"]

    assert by_source["whatsapp"]["auth_status"] == "browser_required"
    assert by_source["whatsapp"]["browser_login_status"] == "logged_out"
    assert by_source["whatsapp"]["status_label"] == "未登录"
    assert "扫码" in by_source["whatsapp"]["status_detail"]

    assert by_source["telegram"]["auth_status"] == "browser_required"
    assert by_source["telegram"]["browser_login_status"] == "logged_in"
    assert by_source["telegram"]["status_label"] == "已登录"
    assert by_source["telegram"]["collection_status"] == "healthy"

    assert by_source["linkedin"]["browser_login_status"] == "logged_in"
    assert by_source["linkedin"]["status_label"] == "已登录 / 采集异常"
    assert "可见页面解析异常" in by_source["linkedin"]["status_detail"]


def test_gmail_composio_fetch_persists_messages_as_collector_events(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    executed = []
    queued = []
    captured_body = {}

    def fake_execute_composio_tool_call(body):
        captured_body["toolkit_slug"] = body.toolkit_slug
        captured_body["tool_slug"] = body.tool_slug
        captured_body["arguments"] = dict(body.arguments)
        return {
            "status": "completed",
            "live_result": {
                "result": {
                    "messages": [
                        {
                            "id": "gmail-1",
                            "threadId": "thread-1",
                            "subject": "报价截止提醒",
                            "from": "alice@example.com",
                            "to": ["me@example.com"],
                            "snippet": "周五 18:00 前确认报价。",
                            "body": "请在周五 18:00 前确认 PHONE_1 报价。",
                        }
                    ]
                }
            },
        }

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
            if "SELECT event_id FROM events" in normalized:
                return Cursor()
            if "INSERT INTO events" in normalized:
                executed.append((normalized, params))
                return Cursor()
            raise AssertionError(f"Unexpected SQL: {sql}")

    class Redis:
        def xadd(self, stream, fields):
            queued.append((stream, fields))

    monkeypatch.setattr(main, "execute_composio_tool_call", fake_execute_composio_tool_call)
    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: Redis())

    response = TestClient(main.app).post(
        "/api/collectors/gmail/composio/fetch",
        headers={"x-par-password": "secret"},
        json={"query": "newer_than:1d", "limit": 10},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["fetched_count"] == 1
    assert payload["persisted_count"] == 1
    assert captured_body == {
        "toolkit_slug": "gmail",
        "tool_slug": "GMAIL_FETCH_EMAILS",
        "arguments": {"query": "newer_than:1d", "max_results": 10},
    }
    event_params = executed[0][1]
    assert event_params[2] == "gmail"
    assert event_params[3] == "gmail_message_snapshot"
    stored = json.loads(event_params[4])
    assert stored["message_id"] == "gmail-1"
    assert stored["thread_id"] == "thread-1"
    assert stored["subject"] == "报价截止提醒"
    assert stored["source_adapter"] == "composio:gmail"
    assert queued[0][0] == "events:raw"


def test_gmail_composio_fetch_flattens_preview_objects_before_persisting(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    executed = []
    queued = []

    def fake_execute_composio_tool_call(body):
        return {
            "status": "completed",
            "live_result": {
                "result": {
                    "messages": [
                        {
                            "messageId": "gmail-preview-dict",
                            "threadId": "thread-preview-dict",
                            "preview": {
                                "body": "请明天下午4点在人民广场见面，带合同。",
                                "subject": "明天下午4点人民广场见",
                            },
                            "sender": '"张子长" <sender@example.com>',
                            "recipients": ["me@example.com"],
                        }
                    ]
                }
            },
        }

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
            if "SELECT event_id FROM events" in normalized:
                return Cursor()
            if "INSERT INTO events" in normalized:
                executed.append((normalized, params))
                return Cursor()
            raise AssertionError(f"Unexpected SQL: {sql}")

    class Redis:
        def xadd(self, stream, fields):
            queued.append((stream, fields))

    monkeypatch.setattr(main, "execute_composio_tool_call", fake_execute_composio_tool_call)
    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: Redis())

    response = TestClient(main.app).post(
        "/api/collectors/gmail/composio/fetch",
        headers={"x-par-password": "secret"},
        json={"query": "newer_than:1d", "limit": 1},
    )

    assert response.status_code == 200
    event_params = executed[0][1]
    stored_public = json.loads(event_params[4])
    stored_private = json.loads(event_params[5])
    assert stored_public["subject"] == "明天下午4点人民广场见"
    assert stored_private["format"] == "fernet-json-v1"
    assert stored_public["body"] == "请明天下午4点在人民广场见面，带合同。"
    assert stored_public["snippet"] == "请明天下午4点在人民广场见面，带合同。"
    assert "{'body'" not in json.dumps(stored_public, ensure_ascii=False)
    queued_payload = json.loads(queued[0][1]["raw_data"])
    assert queued_payload["subject"] == "明天下午4点人民广场见"
    assert queued_payload["body"] == "请明天下午4点在人民广场见面，带合同。"
    assert "{'body'" not in json.dumps(queued_payload, ensure_ascii=False)
    assert queued[0][0] == "events:raw"


def test_gmail_composio_fetch_normalizes_large_html_and_uses_email_timestamp(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    executed = []
    queued = []
    large_html = "<html><body><style>.x{}</style><p>明天3点记得在腾讯会议上开线上会议</p>" + (" filler" * 6000) + "</body></html>"

    def fake_execute_composio_tool_call(body):
        return {
            "status": "completed",
            "live_result": {
                "result": {
                    "messages": [
                        {
                            "id": "gmail-large-html",
                            "threadId": "thread-large-html",
                            "subject": "会议提醒",
                            "from": "sender@example.com",
                            "to": ["me@example.com"],
                            "date": "Wed, 24 Jun 2026 20:18:00 +0800",
                            "body": large_html,
                            "payload": {"body": {"data": "huge-html-should-not-be-copied"}},
                        }
                    ]
                }
            },
        }

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
            if "SELECT event_id FROM events" in normalized:
                return Cursor()
            if "INSERT INTO events" in normalized:
                executed.append((normalized, params))
                return Cursor()
            raise AssertionError(f"Unexpected SQL: {sql}")

    class Redis:
        def xadd(self, stream, fields):
            queued.append((stream, fields))

    monkeypatch.setattr(main, "execute_composio_tool_call", fake_execute_composio_tool_call)
    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: Redis())

    response = TestClient(main.app).post(
        "/api/collectors/gmail/composio/fetch",
        headers={"x-par-password": "secret"},
        json={"query": "newer_than:1d", "limit": 1},
    )

    assert response.status_code == 200
    event_params = executed[0][1]
    assert event_params[1].isoformat() == "2026-06-24T12:18:00+00:00"
    stored_public = json.loads(event_params[4])
    stored_private = json.loads(event_params[5])
    queued_payload = json.loads(queued[0][1]["raw_data"])
    assert "<html" not in stored_public["body"].lower()
    assert "明天3点记得在腾讯会议上开线上会议" in stored_public["body"]
    assert len(stored_public["body"]) < len(large_html)
    assert stored_public["raw"]["omitted"] is True
    assert "payload" in stored_public["raw"]["source_keys"]
    assert "huge-html-should-not-be-copied" not in json.dumps(stored_public, ensure_ascii=False)
    assert "huge-html-should-not-be-copied" not in json.dumps(stored_private, ensure_ascii=False)
    assert len(json.dumps(queued_payload, ensure_ascii=False)) < 18000


def test_gmail_composio_fetch_uses_composio_message_timestamp_when_date_is_missing(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    executed = []
    queued = []

    def fake_execute_composio_tool_call(body):
        return {
            "status": "completed",
            "live_result": {
                "result": {
                    "messages": [
                        {
                            "messageId": "gmail-message-ts",
                            "threadId": "thread-message-ts",
                            "subject": "明天3点会议",
                            "messageText": "明天3点记得在腾讯会议上开线上会议",
                            "messageTimestamp": "2026-06-24T12:17:41Z",
                        }
                    ]
                }
            },
        }

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
            if "SELECT event_id FROM events" in normalized:
                return Cursor()
            if "INSERT INTO events" in normalized:
                executed.append((normalized, params))
                return Cursor()
            raise AssertionError(f"Unexpected SQL: {sql}")

    class Redis:
        def xadd(self, stream, fields):
            queued.append((stream, fields))

    monkeypatch.setattr(main, "execute_composio_tool_call", fake_execute_composio_tool_call)
    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: Redis())

    response = TestClient(main.app).post(
        "/api/collectors/gmail/composio/fetch",
        headers={"x-par-password": "secret"},
        json={"query": "newer_than:1d", "limit": 1},
    )

    assert response.status_code == 200
    event_params = executed[0][1]
    stored_public = json.loads(event_params[4])
    assert event_params[1].isoformat() == "2026-06-24T12:17:41+00:00"
    assert stored_public["date"] == "2026-06-24T12:17:41+00:00"
    assert queued


def test_gmail_composio_fetch_skips_duplicate_message_ids(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    executed = []
    queued = []

    def fake_execute_composio_tool_call(body):
        return {
            "status": "completed",
            "live_result": {
                "result": {
                    "messages": [
                        {
                            "id": "gmail-duplicate",
                            "threadId": "thread-duplicate",
                            "subject": "重复邮件",
                            "body": "已经入库过的邮件不应该再次入队。",
                        }
                    ]
                }
            },
        }

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
            if "SELECT event_id FROM events" in normalized:
                return Cursor([("existing-event-id",)])
            if "INSERT INTO events" in normalized:
                executed.append((normalized, params))
                return Cursor()
            raise AssertionError(f"Unexpected SQL: {sql}")

    class Redis:
        def xadd(self, stream, fields):
            queued.append((stream, fields))

    monkeypatch.setattr(main, "execute_composio_tool_call", fake_execute_composio_tool_call)
    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: Redis())

    response = TestClient(main.app).post(
        "/api/collectors/gmail/composio/fetch",
        headers={"x-par-password": "secret"},
        json={"query": "newer_than:1d", "limit": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["events"] == [{"event_id": "existing-event-id", "message_id": "gmail-duplicate", "status": "duplicate"}]
    assert payload["persisted_count"] == 0
    assert payload["created_count"] == 0
    assert payload["duplicate_count"] == 1
    assert payload["seen_count"] == 1
    assert executed == []
    assert queued == []


def test_gmail_composio_fetch_enqueues_after_database_context_commits(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    queued = []
    lifecycle = []

    def fake_execute_composio_tool_call(body):
        return {
            "status": "completed",
            "live_result": {
                "result": {
                    "messages": [
                        {
                            "id": "gmail-commit-race",
                            "threadId": "thread-commit-race",
                            "subject": "明天3点会议",
                            "body": "明天3点记得在腾讯会议上开线上会议",
                        }
                    ]
                }
            },
        }

    class Cursor:
        def fetchone(self):
            return None

    class Conn:
        committed = False

        def __enter__(self):
            lifecycle.append("enter")
            return self

        def __exit__(self, exc_type, exc, tb):
            lifecycle.append("commit")
            Conn.committed = True
            return None

        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            if "SELECT enabled, paused_until" in normalized:
                return Cursor()
            if "SELECT event_id FROM events" in normalized:
                return Cursor()
            if "INSERT INTO events" in normalized:
                lifecycle.append("insert_event")
                return Cursor()
            raise AssertionError(f"Unexpected SQL: {sql}")

    class Redis:
        def xadd(self, stream, fields):
            lifecycle.append("enqueue")
            queued.append((stream, fields, Conn.committed))

    monkeypatch.setattr(main, "execute_composio_tool_call", fake_execute_composio_tool_call)
    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "redis_client", lambda: Redis())

    response = TestClient(main.app).post(
        "/api/collectors/gmail/composio/fetch",
        headers={"x-par-password": "secret"},
        json={"query": "newer_than:1d", "limit": 1},
    )

    assert response.status_code == 200
    assert queued
    assert queued[0][2] is True
    assert lifecycle.index("commit") < lifecycle.index("enqueue")


def test_gmail_composio_sync_once_fetches_when_readonly_gmail_is_connected(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    calls = []

    class Cursor:
        def fetchone(self):
            return (True,)

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            if "FROM composio_toolkits" in normalized:
                assert params == ("gmail", "readonly")
                return Cursor()
            raise AssertionError(f"Unexpected SQL: {sql}")

    def fake_run_gmail_composio_fetch(*, query, limit):
        calls.append({"query": query, "limit": limit})
        return {"status": "completed", "persisted_count": 1}

    monkeypatch.setattr(main, "COMPOSIO_API_KEY", "ak_test")
    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "run_gmail_composio_fetch", fake_run_gmail_composio_fetch)

    result = main.gmail_composio_sync_once(query="newer_than:1d", limit=3)

    assert result["status"] == "synced"
    assert result["fetch"]["persisted_count"] == 1
    assert calls == [{"query": "newer_than:1d", "limit": 3}]


def test_gmail_composio_sync_once_skips_when_readonly_gmail_is_not_connected(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    class Cursor:
        def fetchone(self):
            return None

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            if "FROM composio_toolkits" in normalized:
                return Cursor()
            raise AssertionError(f"Unexpected SQL: {sql}")

    def fail_fetch(*, query, limit):
        raise AssertionError("fetch should not run when Gmail is not connected")

    monkeypatch.setattr(main, "COMPOSIO_API_KEY", "ak_test")
    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "run_gmail_composio_fetch", fail_fetch)

    result = main.gmail_composio_sync_once(query="newer_than:1d", limit=3)

    assert result == {"status": "skipped", "reason": "gmail_not_connected"}


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


def test_tool_catalog_returns_high_frequency_tools_with_permission_levels(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    client = TestClient(main.app)

    response = client.get("/api/tools/catalog", headers={"x-par-password": "secret"})

    assert response.status_code == 200
    payload = response.json()
    tools = payload["tools"]
    assert len(tools) >= 21
    by_id = {tool["id"]: tool for tool in tools}
    assert by_id["gmail"]["phase"] == "core"
    assert by_id["telegram"]["phase"] == "core"
    assert by_id["telegram"]["recommended_adapter"] == "managed_browser_first"
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


def test_core_pipeline_registry_matches_design_pipeline_set(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    pipelines = {pipeline["id"]: pipeline for pipeline in main.core_pipeline_registry()}
    expected_pipeline_ids = {
        "event_ingestion_pipeline",
        "memory_write_pipeline",
        "context_pack_pipeline",
        "personal_search_pipeline",
        "chat_response_pipeline",
        "reply_pipeline",
        "email_pipeline",
        "agenda_pipeline",
        "task_todo_pipeline",
        "proactive_suggestion_pipeline",
        "route_pipeline",
        "ride_pipeline",
        "shopping_pipeline",
        "payment_bill_pipeline",
        "contact_relationship_pipeline",
        "document_file_pipeline",
        "account_login_pipeline",
        "governance_audit_pipeline",
    }

    assert expected_pipeline_ids.issubset(pipelines.keys())
    for pipeline_id in expected_pipeline_ids:
        pipeline = pipelines[pipeline_id]
        assert pipeline["capability_id"]
        assert pipeline["steps"]
        assert "permission" in pipeline
        assert "required_slots" in pipeline
        assert "allowed_tools" in pipeline
        assert "forbidden_tools" in pipeline
        assert "writeback_targets" in pipeline
        assert "external_effects" in pipeline

    assert pipelines["personal_search_pipeline"]["permission"] == "read_only"
    assert pipelines["ride_pipeline"]["permission"] == "payment_or_purchase"
    assert "send_message" in pipelines["reply_pipeline"]["external_effects"]
    assert "events" in pipelines["event_ingestion_pipeline"]["writeback_targets"]


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
    assert payload["route_type"] == "openclaw_tool"
    assert payload["legacy_route_type"] == "long_tail_tool"
    assert payload["task_route_decision"]["route_type"] == "openclaw_tool"
    assert payload["task_route_decision"]["pipeline_id"] is None
    assert payload["task_route_decision"]["risk_permission"] == "write"
    assert payload["task_route_decision"]["confirmation_required"] is True
    assert "OpenClaw" in payload["task_route_decision"]["reason"]
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
    assert payload["route_type"] == "openclaw_tool"
    assert payload["legacy_route_type"] == "long_tail_tool"
    assert payload["task_route_decision"]["route_type"] == "openclaw_tool"
    assert payload["task_route_decision"]["risk_permission"] == "external_execution"
    assert payload["capability"]["id"] == "automation.browser.operate"
    assert payload["candidate_tools"][0]["id"] == "browser_automation"


def test_openclaw_packet_minimizes_context_and_forbids_external_effects(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    client = TestClient(main.app)

    response = client.post(
        "/api/tools/route",
        headers={"x-par-password": "secret"},
        json={
            "request": "帮我去一个不支持 MCP 的网站填写报名表，但不要提交",
            "context": {
                "current_url": "https://forms.example/apply?token=abc123&email=alice@example.com",
                "page_title": "报名表",
                "selected_text": "申请岗位：产品经理",
                "source_event_ids": ["evt_1", "evt_2"],
                "active_source_scope": {"source": "whatsapp", "conversation_id": "chat_a", "contact_id": "alice"},
                "user_approved_fields": {"name": "Alice", "phone": "+86 138 0000 0000"},
                "raw_memory_dump": "Bob 私下说 Alice 不靠谱，千万不要泄露。",
                "recent_messages": [{"conversation_id": "chat_b", "text": "另一个联系人 B 的隐私"}],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    packet = payload["openclaw_task_packet"]
    minimal_context = packet["minimal_context"]

    assert payload["route_type"] == "openclaw_tool"
    assert packet["goal"] == "帮我去一个不支持 MCP 的网站填写报名表，但不要提交"
    assert packet["allowed_actions"] == ["open_page", "read_page", "fill_form", "download_file"]
    assert "submit" in packet["forbidden_actions"]
    assert "pay" in packet["forbidden_actions"]
    assert "send_message" in packet["forbidden_actions"]
    assert packet["requires_stop_before"] == ["submission", "payment", "external_message", "external_write"]
    assert packet["return_schema"]["status"] == "draft_ready | completed_read_only | blocked | needs_user_input | failed"
    assert minimal_context["current_url"] == "https://forms.example/apply?token=REDACTED&email=REDACTED"
    assert minimal_context["active_source_scope"]["conversation_id"] == "chat_a"
    assert minimal_context["source_event_ids"] == ["evt_1", "evt_2"]
    assert "raw_memory_dump" not in minimal_context
    assert "recent_messages" not in minimal_context
    assert "Bob 私下说" not in json.dumps(minimal_context, ensure_ascii=False)


def test_openclaw_sensitive_field_release_endpoint_requires_password_and_returns_audit_payload(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    client = TestClient(main.app)
    body = {
        "field": "phone",
        "value": "+86 138 0000 0000",
        "purpose": "填写报名表联系电话",
        "task_id": "openclaw_apply_form",
    }

    unauthorized = client.post("/api/tools/openclaw/field-release", json=body)
    assert unauthorized.status_code == 401

    response = client.post(
        "/api/tools/openclaw/field-release",
        headers={"x-par-password": "secret"},
        json=body,
    )

    assert response.status_code == 200
    payload = response.json()
    release = payload["approved_sensitive_fields"]["phone"]
    assert release["value"] == "+86 138 0000 0000"
    assert release["approved"] is True
    assert release["purpose"] == "填写报名表联系电话"
    assert release["task_id"] == "openclaw_apply_form"
    assert release["approval_id"].startswith("sfr_")
    assert release["approved_at"]


def test_openclaw_packet_includes_raw_sensitive_value_only_through_approved_release(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    release = main.build_sensitive_field_release(
        field="phone",
        value="+86 138 0000 0000",
        purpose="填写报名表联系电话",
        task_id="openclaw_apply_form",
    )
    route = main.route_tool_request(
        "帮我去一个不支持 MCP 的网站填写报名表，但不要提交",
        {
            "current_url": "https://forms.example/apply?token=abc123",
            "user_approved_fields": {"phone": "+86 138 0000 0000"},
            "approved_sensitive_fields": release["approved_sensitive_fields"],
        },
    )

    packet = route["openclaw_task_packet"]
    minimal_context = packet["minimal_context"]

    assert minimal_context["user_approved_fields"]["phone"] == "PHONE_1"
    assert minimal_context["approved_sensitive_fields"]["phone"]["value"] == "+86 138 0000 0000"
    assert minimal_context["approved_sensitive_fields"]["phone"]["approval_id"].startswith("sfr_")
    assert packet["context_necessity"]["approved_sensitive_releases"][0]["field"] == "phone"
    assert "raw_value_released_after_user_approval" in packet["context_necessity"]["decisions"]["approved_sensitive_fields"]["reason"]


@pytest.mark.parametrize(
    ("task_request", "expected_capability"),
    [
        ("帮我处理一下这个客户", "business.crm.contact.upsert"),
        ("帮我付款", "finance.payment_bill.manage"),
    ],
)
def test_ambiguous_external_effect_request_asks_user_before_openclaw(monkeypatch, task_request, expected_capability):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    client = TestClient(main.app)

    response = client.post(
        "/api/tools/route",
        headers={"x-par-password": "secret"},
        json={"request": task_request},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["route_type"] == "ask_user"
    assert payload["legacy_route_type"] == "ask_user"
    assert payload["capability"]["id"] == expected_capability
    assert payload["pipeline"] is None
    assert "openclaw_task_packet" not in payload
    assert payload["task_route_decision"]["route_type"] == "ask_user"
    assert payload["clarification"]["required"] is True
    assert payload["clarification"]["missing_fields"]
    assert "需要先确认" in payload["task_route_decision"]["reason"]


def test_task_route_trace_schema_creates_table(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed = []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            executed.append((sql, params))

    monkeypatch.setattr(main, "db", lambda: Conn())

    main.ensure_task_routing_schema()

    sql_text = "\n".join(sql for sql, _ in executed)
    assert "CREATE TABLE IF NOT EXISTS task_route_traces" in sql_text
    assert "route_type TEXT NOT NULL" in sql_text
    assert "openclaw_task_packet JSONB" in sql_text
    assert "task_route_traces_created_idx" in sql_text


def test_persist_task_route_trace_records_decision_and_packet(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    route = main.route_tool_request(
        "帮我去一个不支持 MCP 的网站填写报名表，但不要提交",
        {"current_url": "https://forms.example/apply?token=abc123"},
    )
    executed = []

    class Cursor:
        rowcount = 1

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            return Cursor()

    trace_id = main.persist_task_route_trace(Conn(), route)

    assert trace_id == route["task_trace_id"]
    assert "INSERT INTO task_route_traces" in executed[0][0]
    params = executed[0][1]
    assert params[1] == "帮我去一个不支持 MCP 的网站填写报名表，但不要提交"
    assert params[2] == "openclaw_tool"
    assert params[3] == "automation.browser.operate"
    assert params[5] == "external_execution"
    assert params[7].obj["route_type"] == "openclaw_tool"
    assert params[8].obj["goal"] == "帮我去一个不支持 MCP 的网站填写报名表，但不要提交"


def test_task_route_traces_api_filters_and_returns_audit_rows(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    executed = []

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
            executed.append((sql, params))
            normalized = " ".join(sql.split())
            assert "FROM task_route_traces" in normalized
            assert "route_type = %s" in normalized
            assert "capability_id = %s" in normalized
            assert "request ILIKE %s" in normalized
            return Cursor(
                [
                    (
                        "11111111-1111-1111-1111-111111111111",
                        "帮我去一个不支持 MCP 的网站填写报名表",
                        "openclaw_tool",
                        "automation.browser.operate",
                        None,
                        "external_execution",
                        True,
                        {"route_type": "openclaw_tool", "reason": "交给 OpenClaw"},
                        {"goal": "帮我去一个不支持 MCP 的网站填写报名表"},
                        None,
                        {"current_url": "https://forms.example/apply?token=REDACTED"},
                        "2026-05-28T08:00:00+00:00",
                    )
                ]
            )

    monkeypatch.setattr(main, "db", lambda: Conn())
    client = TestClient(main.app)

    response = client.get(
        "/api/tools/route/traces?route_type=openclaw_tool&capability=automation.browser.operate&q=报名&limit=5",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["filters"] == {
        "route_type": "openclaw_tool",
        "capability": "automation.browser.operate",
        "q": "报名",
        "limit": 5,
    }
    assert body["traces"][0]["route_type"] == "openclaw_tool"
    assert body["traces"][0]["capability_id"] == "automation.browser.operate"
    assert body["traces"][0]["openclaw_task_packet"]["goal"] == "帮我去一个不支持 MCP 的网站填写报名表"
    assert executed[0][1] == ("openclaw_tool", "automation.browser.operate", "%报名%", 5)


def test_openclaw_execute_dry_run_blocks_live_call_when_disabled(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.delenv("OPENCLAW_ENABLED", raising=False)
    from app import main

    route = main.route_tool_request("帮我去一个不支持 MCP 的网站填写报名表，但不要提交")
    result = main.execute_openclaw_task_packet(route["openclaw_task_packet"], route["execution_guard"])

    assert result["mode"] == "dry_run"
    assert result["status"] == "blocked"
    assert result["needs_confirmation"] is True
    assert "OPENCLAW_ENABLED" in result["reason"]
    assert result["packet"]["forbidden_actions"]


def test_openclaw_execute_live_uses_openresponses_endpoint(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("OPENCLAW_ENABLED", "true")
    monkeypatch.setenv("OPENCLAW_BASE_URL", "http://gateway.local:18789/")
    monkeypatch.setenv("OPENCLAW_API_TOKEN", "secret-token")
    from app import main

    route = main.route_tool_request(
        "帮我去一个不支持 MCP 的网站填写报名表，但不要提交",
        {"current_url": "https://forms.example/apply?token=abc123"},
    )
    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "resp_1", "output_text": "表单草稿已准备，未提交。"}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(main.httpx, "post", fake_post)

    result = main.execute_openclaw_task_packet(route["openclaw_task_packet"], route["execution_guard"])

    assert result["mode"] == "live"
    assert result["status"] == "completed_read_only"
    assert result["summary"] == "表单草稿已准备，未提交。"
    assert captured["url"] == "http://gateway.local:18789/v1/responses"
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert "禁止动作" in captured["json"]["input"]
    assert "submit" in captured["json"]["input"]
    assert captured["json"]["metadata"]["nomi_permission"] == "external_execution"


def test_openclaw_live_execution_records_long_tail_action_request_policy_and_trace(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("OPENCLAW_ENABLED", "true")
    from app import main
    from app.long_tail_agent import LongTailEventStore

    store = LongTailEventStore()
    main._LONG_TAIL_EVENT_STORE = store
    route = main.route_tool_request(
        "帮我去一个不支持 MCP 的网站填写报名表，但不要提交",
        {"current_url": "https://forms.example/apply?token=abc123"},
    )

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "resp_openclaw_live_1", "output_text": "表单草稿已准备，未提交。"}

    monkeypatch.setattr(main.httpx, "post", lambda *args, **kwargs: FakeResponse())

    result = main.execute_openclaw_task_packet(route["openclaw_task_packet"], route["execution_guard"])
    events = store.task_events(route["openclaw_task_packet"]["task_id"])

    assert result["mode"] == "live"
    assert [event["event_type"] for event in events] == [
        "executor.action_requested",
        "policy.checked",
        "executor.live_completed",
    ]
    assert events[0]["payload"]["action_request"]["action_type"] == "openclaw.run_task_packet"
    assert events[1]["payload"]["policy_report"]["status"] == "allowed"
    assert events[1]["payload"]["policy_report"]["may_execute"] is True
    assert events[2]["payload"]["executor_trace"]["provider"] == "openclaw"
    assert events[2]["payload"]["executor_trace"]["provider_trace_id"] == "resp_openclaw_live_1"
    assert events[2]["payload"]["executor_trace"]["executor_trace_id"].startswith("openclaw_exec_")
    assert events[2]["payload"]["live_result"]["external_side_effect"] is False


def test_openclaw_execute_live_normalizes_gateway_tool_events(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("OPENCLAW_ENABLED", "true")
    from app import main

    route = main.route_tool_request(
        "帮我去一个不支持 MCP 的网站填写报名表，但不要提交",
        {"current_url": "https://forms.example/apply?token=abc123"},
    )

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": "resp_events_1",
                "output_text": "读取页面并填入草稿，没有提交。",
                "events": [
                    {
                        "type": "tool_call",
                        "name": "browser.open",
                        "status": "completed",
                        "message": "打开报名页面",
                        "url": "https://forms.example/apply?token=abc123",
                    }
                ],
            }

    monkeypatch.setattr(main.httpx, "post", lambda *args, **kwargs: FakeResponse())

    result = main.execute_openclaw_task_packet(route["openclaw_task_packet"], route["execution_guard"])

    assert result["mode"] == "live"
    assert result["raw_response_id"] == "resp_events_1"
    assert result["events"][0]["event_type"] == "tool_call"
    assert result["events"][0]["tool_name"] == "browser.open"
    assert result["events"][0]["message"] == "打开报名页面"
    assert result["events"][0]["payload"]["url"] == "https://forms.example/apply?token=REDACTED"


def test_openclaw_job_transition_retries_transient_failure_then_stops(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    transient = main.classify_openclaw_job_result(
        {"status": "failed", "error": "timeout while opening page", "events": [{"event_type": "error", "message": "timeout"}]},
        attempt_count=1,
        max_attempts=3,
    )
    exhausted = main.classify_openclaw_job_result(
        {"status": "failed", "error": "timeout while opening page"},
        attempt_count=3,
        max_attempts=3,
    )
    completed = main.classify_openclaw_job_result(
        {"status": "completed_read_only", "summary": "页面读取完成"},
        attempt_count=1,
        max_attempts=3,
    )

    assert transient["status"] == "retry_scheduled"
    assert transient["retryable"] is True
    assert transient["next_attempt_delay_seconds"] == 30
    assert exhausted["status"] == "failed"
    assert exhausted["retryable"] is False
    assert completed["status"] == "completed"
    assert completed["retryable"] is False


def test_openclaw_job_enqueue_endpoint_records_job_and_queued_event(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    executed = []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            executed.append((sql, params))

    monkeypatch.setattr(main, "db", lambda: Conn())
    route = main.route_tool_request("帮我去一个不支持 MCP 的网站填写报名表，但不要提交")
    client = TestClient(main.app)

    response = client.post(
        "/api/tools/openclaw/jobs",
        headers={"x-par-password": "secret"},
        json={"packet": route["openclaw_task_packet"], "execution_guard": route["execution_guard"], "max_attempts": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["max_attempts"] == 2
    assert body["job_id"]
    assert any("INSERT INTO openclaw_execution_jobs" in sql for sql, _ in executed)
    assert any("INSERT INTO openclaw_execution_events" in sql for sql, _ in executed)
    assert executed[0][1][1] == route["openclaw_task_packet"]["task_id"]
    assert executed[1][1][2] == "queued"


def test_run_openclaw_job_once_records_attempt_events_and_retry(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    job_id = "11111111-1111-1111-1111-111111111111"
    packet = {"task_id": "openclaw_task_1", "goal": "打开页面"}
    guard = {"permission": "external_execution", "requires_confirmation": True}
    executed = []

    class Cursor:
        def fetchone(self):
            return (
                job_id,
                "openclaw_task_1",
                None,
                "queued",
                0,
                2,
                packet,
                guard,
                None,
                None,
                "2026-05-28T08:00:00+00:00",
                "2026-05-28T08:00:00+00:00",
                "2026-05-28T08:00:00+00:00",
                None,
            )

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            if "SELECT id, task_id" in sql:
                return Cursor()

    def fake_executor(openclaw_packet, execution_guard):
        assert openclaw_packet == packet
        assert execution_guard == guard
        return {
            "status": "failed",
            "error": "timeout while opening page",
            "events": [
                {
                    "event_type": "tool_call",
                    "tool_name": "browser.open",
                    "message": "打开页面超时",
                    "payload": {"url": "https://forms.example/apply?token=REDACTED"},
                }
            ],
        }

    result = main.run_openclaw_execution_job_once(Conn(), job_id, executor=fake_executor)

    inserted_events = [params for sql, params in executed if "INSERT INTO openclaw_execution_events" in sql]
    update_sql = " ".join(sql for sql, _ in executed if "UPDATE openclaw_execution_jobs" in sql)

    assert result["status"] == "retry_scheduled"
    assert result["attempt_count"] == 1
    assert result["transition"]["next_attempt_delay_seconds"] == 30
    assert [event[2] for event in inserted_events] == ["attempt_started", "tool_call", "retry_scheduled"]
    assert inserted_events[1][3] == "打开页面超时"
    assert "last_result" in update_sql


def test_record_openclaw_execution_event_publishes_realtime_payload(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed = []
    published = []

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))

    class Redis:
        def publish(self, channel, payload):
            published.append((channel, json.loads(payload)))

    event_id = main.record_openclaw_execution_event(
        Conn(),
        job_id="11111111-1111-1111-1111-111111111111",
        event_type="tool_call",
        message="打开报名页面",
        payload={"url": "https://forms.example/apply?token=abc123"},
        redis_obj=Redis(),
    )

    assert event_id
    assert "INSERT INTO openclaw_execution_events" in executed[0][0]
    assert published[0][0] == main.REALTIME_CHANNEL
    message = published[0][1]
    assert message["type"] == "openclaw_job_event"
    assert message["job_id"] == "11111111-1111-1111-1111-111111111111"
    assert message["event_type"] == "tool_call"
    assert message["message"] == "打开报名页面"
    assert message["payload"]["url"] == "https://forms.example/apply?token=REDACTED"


def test_run_openclaw_job_once_publishes_attempt_tool_and_retry_events(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    job_id = "11111111-1111-1111-1111-111111111111"
    packet = {"task_id": "openclaw_task_1", "goal": "打开页面"}
    guard = {"permission": "external_execution", "requires_confirmation": True}
    published = []

    class Cursor:
        def fetchone(self):
            return (
                job_id,
                "openclaw_task_1",
                None,
                "queued",
                0,
                2,
                packet,
                guard,
                None,
                None,
                "2026-05-28T08:00:00+00:00",
                "2026-05-28T08:00:00+00:00",
                "2026-05-28T08:00:00+00:00",
                None,
            )

    class Conn:
        def execute(self, sql, params=()):
            if "SELECT id, task_id" in sql:
                return Cursor()

    class Redis:
        def publish(self, channel, payload):
            published.append(json.loads(payload))

    def fake_executor(openclaw_packet, execution_guard):
        return {
            "status": "failed",
            "error": "timeout while opening page",
            "events": [{"event_type": "tool_call", "tool_name": "browser.open", "message": "打开页面超时"}],
        }

    result = main.run_openclaw_execution_job_once(Conn(), job_id, executor=fake_executor, redis_obj=Redis())

    assert result["status"] == "retry_scheduled"
    assert [message["event_type"] for message in published] == ["attempt_started", "tool_call", "retry_scheduled"]
    assert all(message["type"] == "openclaw_job_event" for message in published)


def test_openclaw_job_status_endpoint_returns_job_with_events(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    job_id = "11111111-1111-1111-1111-111111111111"

    class Cursor:
        def __init__(self, row=None, rows=None):
            self.row = row
            self.rows = rows or []

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
            if "FROM openclaw_execution_jobs" in sql:
                return Cursor(
                    row=(
                        job_id,
                        "openclaw_task_1",
                        None,
                        "retry_scheduled",
                        1,
                        2,
                        {"task_id": "openclaw_task_1"},
                        {"permission": "external_execution"},
                        {"status": "failed", "error": "timeout"},
                        "timeout",
                        "2026-05-28T08:01:00+00:00",
                        "2026-05-28T08:00:00+00:00",
                        "2026-05-28T08:00:30+00:00",
                        None,
                    )
                )
            if "FROM openclaw_execution_events" in sql:
                return Cursor(
                    rows=[
                        (
                            "22222222-2222-2222-2222-222222222222",
                            job_id,
                            "retry_scheduled",
                            "OpenClaw job scheduled for retry.",
                            {"delay_seconds": 30},
                            "2026-05-28T08:00:30+00:00",
                        )
                    ]
                )
            raise AssertionError(sql)

    monkeypatch.setattr(main, "db", lambda: Conn())
    client = TestClient(main.app)

    response = client.get(f"/api/tools/openclaw/jobs/{job_id}", headers={"x-par-password": "secret"})

    assert response.status_code == 200
    body = response.json()
    assert body["job"]["status"] == "retry_scheduled"
    assert body["job"]["last_result"]["error"] == "timeout"
    assert body["events"][0]["event_type"] == "retry_scheduled"
    assert body["events"][0]["payload"]["delay_seconds"] == 30


def test_fetch_due_openclaw_execution_job_ids_locks_queued_and_retry_jobs(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed = []

    class Cursor:
        def fetchall(self):
            return [
                ("11111111-1111-1111-1111-111111111111",),
                ("22222222-2222-2222-2222-222222222222",),
            ]

    class Conn:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            return Cursor()

    job_ids = main.fetch_due_openclaw_execution_job_ids(Conn(), limit=2)

    normalized_sql = " ".join(executed[0][0].split())
    assert job_ids == ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"]
    assert "status IN ('queued', 'retry_scheduled')" in normalized_sql
    assert "next_attempt_at <= now()" in normalized_sql
    assert "FOR UPDATE SKIP LOCKED" in normalized_sql
    assert executed[0][1] == (2,)


def test_process_due_openclaw_execution_jobs_once_runs_due_jobs(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    ran = []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(
        main,
        "fetch_due_openclaw_execution_job_ids",
        lambda conn, limit: ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"],
    )

    def fake_run(conn, job_id, executor=main.execute_openclaw_task_packet, redis_obj=None):
        ran.append(job_id)
        return {"job_id": job_id, "status": "completed"}

    monkeypatch.setattr(main, "run_openclaw_execution_job_once", fake_run)

    result = main.process_due_openclaw_execution_jobs_once(limit=5)

    assert ran == ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"]
    assert result["processed"] == 2
    assert result["results"][0]["status"] == "completed"


def test_openclaw_execute_endpoint_requires_password(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    route = main.route_tool_request("帮我去一个不支持 MCP 的网站填写报名表，但不要提交")
    client = TestClient(main.app)

    response = client.post(
        "/api/tools/openclaw/execute",
        json={"packet": route["openclaw_task_packet"], "execution_guard": route["execution_guard"]},
    )

    assert response.status_code == 401


def test_openclaw_execute_endpoint_returns_dry_run_result(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.delenv("OPENCLAW_ENABLED", raising=False)
    from fastapi.testclient import TestClient
    from app import main

    route = main.route_tool_request("帮我去一个不支持 MCP 的网站填写报名表，但不要提交")
    client = TestClient(main.app)

    response = client.post(
        "/api/tools/openclaw/execute",
        headers={"x-par-password": "secret"},
        json={"packet": route["openclaw_task_packet"], "execution_guard": route["execution_guard"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "dry_run"
    assert payload["status"] == "blocked"
    assert payload["needs_confirmation"] is True


def test_openclaw_context_necessity_rules_explain_excluded_private_context(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    capability = main.match_capability("帮我去一个不支持 MCP 的网站填写报名表")
    assessment = main.assess_openclaw_context_necessity(
        "帮我去一个不支持 MCP 的网站填写报名表",
        capability,
        {
            "current_url": "https://forms.example/apply?token=abc123",
            "selected_text": "申请岗位：产品经理",
            "raw_memory_dump": "Bob 私下说 Alice 不靠谱。",
            "recent_messages": [{"conversation_id": "chat_b", "text": "另一个联系人 B 的隐私"}],
        },
    )

    assert assessment["mode"] == "rules"
    assert assessment["decisions"]["current_url"]["include"] is True
    assert assessment["decisions"]["current_url"]["sensitive"] is True
    assert assessment["decisions"]["raw_memory_dump"]["include"] is False
    assert assessment["decisions"]["raw_memory_dump"]["reason"] == "not_in_openclaw_allowlist"
    assert assessment["decisions"]["recent_messages"]["include"] is False
    assert "raw_memory_dump" not in assessment["minimal_context"]
    assert "recent_messages" not in assessment["minimal_context"]


def test_openclaw_context_necessity_model_can_only_reduce_context(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("OPENCLAW_CONTEXT_MODEL_ENABLED", "true")
    from app import main

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "include_keys": ["current_url", "raw_memory_dump"],
                                    "exclude_keys": ["selected_text"],
                                    "reason": "selected_text is not required",
                                }
                            )
                        }
                    }
                ]
            }

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(main.httpx, "post", fake_post)
    capability = main.match_capability("帮我去一个不支持 MCP 的网站填写报名表")
    assessment = main.assess_openclaw_context_necessity(
        "帮我去一个不支持 MCP 的网站填写报名表",
        capability,
        {
            "current_url": "https://forms.example/apply?token=abc123",
            "selected_text": "申请岗位：产品经理",
            "raw_memory_dump": "不允许传给 OpenClaw 的私密内容",
        },
    )

    assert assessment["mode"] == "rules+model"
    assert assessment["decisions"]["selected_text"]["include"] is False
    assert assessment["decisions"]["selected_text"]["reason"] == "model_excluded"
    assert assessment["decisions"]["raw_memory_dump"]["include"] is False
    assert "raw_memory_dump" not in assessment["minimal_context"]
    assert "selected_text" not in assessment["minimal_context"]
    assert "token=REDACTED" in captured["json"]["messages"][1]["content"]
    assert "abc123" not in captured["json"]["messages"][1]["content"]


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


def test_composio_tool_execute_readonly_uses_policy_gate_and_persists_invocation(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("COMPOSIO_API_KEY", "test-key")
    from fastapi.testclient import TestClient
    from app import main

    captured = {}
    executed = []

    class FakeSession:
        def execute_tool(self, tool_slug, arguments):
            captured["tool_slug"] = tool_slug
            captured["arguments"] = dict(arguments)
            return {
                "emails": [
                    {"subject": "报价截止提醒", "from": "alice@example.com"}
                ]
            }

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            executed.append((" ".join(sql.split()), params))
            return self

        def fetchone(self):
            return None

        def fetchall(self):
            return []

    monkeypatch.setattr(
        main,
        "get_or_create_composio_session",
        lambda user_id, session_kind: (
            FakeSession(),
            {
                "session_kind": session_kind,
                "toolkits": {"enable": ["gmail"]},
                "tags": {"enable": ["readOnlyHint"], "disable": ["destructiveHint"]},
                "manage_connections": False,
            },
        ),
    )
    monkeypatch.setattr(main, "current_composio_user_id", lambda: "nomi_owner")
    monkeypatch.setattr(main, "db", lambda: Conn())

    response = TestClient(main.app).post(
        "/api/integrations/composio/tools/execute",
        headers={"x-par-password": "secret"},
        json={
            "session_kind": "readonly",
            "toolkit_slug": "gmail",
            "tool_slug": "GMAIL_FETCH_EMAILS",
            "arguments": {"query": "from:alice newer_than:1d"},
            "task_id": "task_email_read",
            "step_id": "fetch_recent_email",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["toolkit_slug"] == "gmail"
    assert payload["tool_slug"] == "GMAIL_FETCH_EMAILS"
    assert payload["live_result"]["external_side_effect"] is False
    assert captured == {
        "tool_slug": "GMAIL_FETCH_EMAILS",
        "arguments": {"query": "from:alice newer_than:1d"},
    }
    assert any("INSERT INTO composio_tool_invocations" in sql for sql, _ in executed)
    invocation_params = next(params for sql, params in executed if "INSERT INTO composio_tool_invocations" in sql)
    assert invocation_params[2] == "gmail"
    assert invocation_params[3] == "GMAIL_FETCH_EMAILS"
    assert invocation_params[5] == "completed"


def test_composio_tool_execute_blocks_external_message_without_confirmation(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("COMPOSIO_API_KEY", "test-key")
    from fastapi.testclient import TestClient
    from app import main
    executed = []

    class FakeSession:
        def execute_tool(self, tool_slug, arguments):
            raise AssertionError("send tool must not execute without confirmation")

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            executed.append((" ".join(sql.split()), params))
            return self

    monkeypatch.setattr(
        main,
        "get_or_create_composio_session",
        lambda user_id, session_kind: (
            FakeSession(),
            {
                "session_kind": session_kind,
                "toolkits": {"enable": ["gmail"]},
                "tags": {"disable": ["destructiveHint"]},
                "manage_connections": False,
            },
        ),
    )
    monkeypatch.setattr(main, "db", lambda: Conn())
    response = TestClient(main.app).post(
        "/api/integrations/composio/tools/execute",
        headers={"x-par-password": "secret"},
        json={
            "session_kind": "write",
            "toolkit_slug": "gmail",
            "tool_slug": "GMAIL_SEND_EMAIL",
            "arguments": {"to": "alice@example.com", "body": "hello"},
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "composio_tool_execution_requires_confirmation"
    assert any("INSERT INTO composio_tool_invocations" in sql for sql, _ in executed)
    invocation_params = next(params for sql, params in executed if "INSERT INTO composio_tool_invocations" in sql)
    assert invocation_params[5] == "requires_confirmation"


def test_composio_connect_requires_api_key_without_calling_sdk(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
    from fastapi.testclient import TestClient
    from app import main

    def fail_factory(*args, **kwargs):
        raise AssertionError("missing API key should not create Composio client")

    monkeypatch.setattr(main, "create_composio_sdk_client", fail_factory, raising=False)
    response = TestClient(main.app).post(
        "/api/integrations/composio/connect/gmail",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "composio_api_key_missing"


def test_composio_connect_creates_manual_authorization_link_and_persists_without_exposing_headers(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("COMPOSIO_API_KEY", "test-key")
    monkeypatch.setenv("COMPOSIO_USER_ID", "nomi_owner")
    from fastapi.testclient import TestClient
    from app import main
    from app.long_tail_agent import LongTailEventStore

    executed = []
    captured = {}
    event_store = LongTailEventStore()

    class Cursor:
        rowcount = 1

        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            executed.append((normalized, params))
            if "FROM composio_sessions" in normalized:
                return Cursor()
            return Cursor()

    class FakeMcp:
        url = "https://mcp.composio.test/session"
        headers = {"authorization": "Bearer sdk-secret", "x-session": "session-secret"}

    class FakeConnectRequest:
        id = "link_req_1"
        redirect_url = "https://connect.composio.dev/link/ln_test"
        connected_account_id = "ca_pending"
        expires_at = "2026-05-28T12:00:00Z"

    class FakeSession:
        session_id = "sess_readonly"
        mcp = FakeMcp()

        def authorize(self, toolkit_slug, callback_url=None):
            captured["authorize"] = {"toolkit_slug": toolkit_slug, "callback_url": callback_url}
            return FakeConnectRequest()

    class FakeComposio:
        def create(self, **kwargs):
            captured["create"] = kwargs
            return FakeSession()

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "create_composio_sdk_client", lambda api_key: FakeComposio())
    monkeypatch.setattr(main, "long_tail_event_store", lambda: event_store)

    response = TestClient(main.app).post(
        "/api/integrations/composio/connect/gmail",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["toolkit_slug"] == "gmail"
    assert payload["session_kind"] == "readonly"
    assert payload["redirect_url"] == "https://connect.composio.dev/link/ln_test"
    assert payload["connection_request_id"] == "link_req_1"
    assert payload["session"]["session_id"] == "sess_readonly"
    assert payload["session"]["mcp_url"] == "https://mcp.composio.test/session"
    assert payload["session"]["mcp_headers_present"] is True
    assert "sdk-secret" not in json.dumps(payload)
    assert "test-key" not in json.dumps(payload)
    assert captured["create"]["user_id"] == "nomi_owner"
    assert captured["create"]["manage_connections"] is False
    assert "google_maps" in captured["create"]["toolkits"]["enable"]
    assert "googlemaps" not in captured["create"]["toolkits"]["enable"]
    assert captured["create"]["tags"]["disable"] == ["destructiveHint"]
    assert captured["authorize"]["toolkit_slug"] == "gmail"
    assert any("INSERT INTO composio_sessions" in sql for sql, _ in executed)
    assert any("INSERT INTO composio_connect_requests" in sql for sql, _ in executed)
    assert any("INSERT INTO account_connections" in sql for sql, _ in executed)
    events = event_store.task_events("composio:readonly:gmail:connect")
    assert [event["event_type"] for event in events] == [
        "executor.action_requested",
        "policy.checked",
        "executor.live_completed",
    ]
    assert events[0]["payload"]["action_request"]["action_type"] == "composio.authorize_toolkit"
    assert events[1]["payload"]["policy_report"]["status"] == "allowed"
    assert events[2]["payload"]["live_result"]["status"] == "link_created"
    assert events[2]["payload"]["live_result"]["external_side_effect"] is False


def test_composio_connect_includes_callback_when_configured(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("COMPOSIO_API_KEY", "test-key")
    monkeypatch.setenv("COMPOSIO_CALLBACK_URL", "https://nomi.example/api/integrations/composio/callback")
    from fastapi.testclient import TestClient
    from app import main

    captured = {}

    class Cursor:
        rowcount = 1

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
            if "FROM composio_sessions" in normalized:
                return Cursor()
            return Cursor()

    class FakeMcp:
        url = "https://mcp.composio.test/session"
        headers = {"authorization": "Bearer sdk-secret"}

    class FakeConnectRequest:
        id = "link_req_1"
        redirect_url = "https://connect.composio.dev/link/ln_test"
        connected_account_id = ""
        expires_at = None

    class FakeSession:
        session_id = "sess_readonly"
        mcp = FakeMcp()

        def authorize(self, toolkit_slug, callback_url=None):
            captured["toolkit_slug"] = toolkit_slug
            captured["callback_url"] = callback_url
            return FakeConnectRequest()

    class FakeComposio:
        def create(self, **kwargs):
            return FakeSession()

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "create_composio_sdk_client", lambda api_key: FakeComposio())

    response = TestClient(main.app).post(
        "/api/integrations/composio/connect/gmail",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    assert captured["toolkit_slug"] == "gmail"
    assert captured["callback_url"] == (
        "https://nomi.example/api/integrations/composio/callback?toolkit=gmail&session_kind=readonly"
    )


def test_composio_callback_returns_android_deep_link_without_auth_or_sensitive_echo(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    response = TestClient(main.app).get(
        "/api/integrations/composio/callback"
        "?toolkit=gmail&session_kind=readonly&status=success&connectedAccountId=ca_secret"
    )

    assert response.status_code == 200
    text = response.text
    assert "nomi://composio/connected?toolkit=gmail&amp;session_kind=readonly&amp;status=success" in text
    assert "intent://composio/connected" in text
    assert "返回 Nomi 授权列表" in text
    assert "ca_secret" not in text


def test_composio_toolkits_sync_returns_connected_status_and_redacts_session_headers(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("COMPOSIO_API_KEY", "test-key")
    from fastapi.testclient import TestClient
    from app import main
    from app.long_tail_agent import LongTailEventStore

    executed = []
    event_store = LongTailEventStore()

    class Cursor:
        rowcount = 1

        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            executed.append((normalized, params))
            if "FROM composio_sessions" in normalized:
                return Cursor([("sess_readonly", "https://mcp.composio.test/session", {"authorization": "Bearer secret"})])
            return Cursor()

    class Connection:
        is_active = True

        class connected_account:
            id = "ca_gmail"

    class Toolkit:
        slug = "gmail"
        name = "Gmail"
        logo = "https://logo.test/gmail.png"
        connection = Connection()

    class ToolkitResult:
        items = [Toolkit()]
        next_cursor = None

    class FakeMcp:
        url = "https://mcp.composio.test/session"
        headers = {"authorization": "Bearer secret"}

    class FakeSession:
        session_id = "sess_readonly"
        mcp = FakeMcp()

        def toolkits(self, **kwargs):
            return ToolkitResult()

    class FakeComposio:
        def use(self, session_id):
            assert session_id == "sess_readonly"
            return FakeSession()

    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "create_composio_sdk_client", lambda api_key: FakeComposio())
    monkeypatch.setattr(main, "long_tail_event_store", lambda: event_store)

    response = TestClient(main.app).get(
        "/api/integrations/composio/toolkits?session_kind=readonly",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session"]["session_id"] == "sess_readonly"
    assert payload["session"]["mcp_headers_present"] is True
    assert "secret" not in json.dumps(payload)
    assert payload["toolkits"] == [
        {
            "slug": "gmail",
            "name": "Gmail",
            "logo": "https://logo.test/gmail.png",
            "connected": True,
            "connected_account_id": "ca_gmail",
        }
    ]
    assert any("INSERT INTO composio_toolkits" in sql for sql, _ in executed)
    events = event_store.task_events("composio:readonly:toolkits:sync")
    assert [event["event_type"] for event in events] == [
        "executor.action_requested",
        "policy.checked",
        "executor.live_completed",
    ]
    assert events[0]["payload"]["action_request"]["action_type"] == "composio.list_toolkits"
    assert events[1]["payload"]["policy_report"]["status"] == "allowed"
    live_result = events[2]["payload"]["live_result"]
    assert live_result["status"] == "toolkits_synced"
    assert live_result["toolkit_count"] == 1
    assert live_result["connected_count"] == 1
    assert live_result["external_side_effect"] is False
