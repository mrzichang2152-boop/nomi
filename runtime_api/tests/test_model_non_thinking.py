import os
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


@pytest.mark.asyncio
async def test_openai_compatible_qwen_payload_uses_reasoning_effort_none(monkeypatch):
    from app.model_client import ChatCompletionClient, ModelClientConfig

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": "ok",
                            "reasoning_content": "",
                        }
                    }
                ],
                "usage": {"completion_tokens_details": {"reasoning_tokens": 0}},
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json, headers=None, timeout=None):
            captured.update(json)
            return FakeResponse()

    monkeypatch.setattr("app.model_client.httpx.AsyncClient", lambda *args, **kwargs: FakeClient())

    client = ChatCompletionClient(
        ModelClientConfig(
            provider_type="openai_compatible",
            base_url="http://qwen.local/v1",
            model="qwen3.6",
            api_key="",
            max_output_tokens=128,
            reasoning_effort="none",
        )
    )

    answer = await client.chat([{"role": "user", "content": "只回复 ok"}])

    assert answer == "ok"
    assert captured["reasoning_effort"] == "none"
    assert captured["enable_thinking"] is False
    assert "chat_template_kwargs" not in captured


def test_qwen_non_thinking_options_only_applies_to_qwen():
    from app.model_client import qwen_non_thinking_options

    assert qwen_non_thinking_options("qwen3.6") == {
        "reasoning_effort": "none",
        "enable_thinking": False,
    }
    assert qwen_non_thinking_options("qwen/qwen3.6-27b") == {
        "reasoning_effort": "none",
        "enable_thinking": False,
    }
    assert qwen_non_thinking_options("gpt-5.4-mini") == {}


def test_openclaw_context_model_uses_qwen_non_thinking_options(monkeypatch):
    monkeypatch.setenv("OPENCLAW_CONTEXT_MODEL_ENABLED", "true")

    from app import main

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"include_keys":[],"exclude_keys":[]}'}}]}

    def fake_post(url, json, timeout):
        captured.update(json)
        return FakeResponse()

    monkeypatch.setattr(main.httpx, "post", fake_post)

    result = main.model_context_necessity_delta(
        "帮我处理",
        {"id": "automation.browser.operate"},
        {"profile": "x"},
        {"profile": {"include": True}},
    )

    assert result == {"include_keys": [], "exclude_keys": []}
    assert captured["reasoning_effort"] == "none"
    assert captured["enable_thinking"] is False


def test_pipeline_slot_model_uses_qwen_non_thinking_options(monkeypatch):
    from app import main

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"slots":{},"confidence":0.5,"reason":"ok"}'}}]}

    def fake_post(url, json, timeout):
        captured.update(json)
        return FakeResponse()

    monkeypatch.setattr(main.httpx, "post", fake_post)

    result = main.call_pipeline_slot_model(
        "帮我订车",
        {"id": "ride_hailing", "required_slots": ["destination"]},
        {"use_model_slots": True},
        {},
    )

    assert result["reason"] == "ok"
    assert captured["reasoning_effort"] == "none"
    assert captured["enable_thinking"] is False
