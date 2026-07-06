import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_worker_model_uses_short_online_timeout(monkeypatch):
    from app import worker

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}]}

    def fake_post(url, json, timeout):
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(worker.httpx, "post", fake_post)
    monkeypatch.setenv("MODEL_ROUTER_URL", "")
    monkeypatch.setenv("WORKER_ONLINE_MODEL_TIMEOUT_SECONDS", "8")

    worker.call_model([{"role": "user", "content": "test"}])

    assert captured["timeout"] == 8
