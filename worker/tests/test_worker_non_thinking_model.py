import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_worker_model_payload_uses_reasoning_effort_none(monkeypatch):
    from app import worker

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": "{\"intent\":\"普通聊天\",\"entities\":{},\"importance\":0.1,\"summary\":\"测试\"}",
                            "reasoning_content": "",
                        }
                    }
                ],
                "usage": {"completion_tokens_details": {"reasoning_tokens": 0}},
            }

    def fake_post(url, json, timeout):
        captured.update(json)
        return FakeResponse()

    monkeypatch.setattr(worker.httpx, "post", fake_post)
    monkeypatch.setenv("MODEL_ROUTER_URL", "")

    content = worker.call_model([{"role": "user", "content": "test"}])

    assert "普通聊天" in content
    assert captured["reasoning_effort"] == "none"
    assert captured["enable_thinking"] is False
