import os
import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient


os.environ.setdefault("MODEL_BASE_URL", "http://model.local:9161")
os.environ.setdefault("MODEL_NAME", "qwen3.6")


def load_router_main():
    module_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("model_router_app_main", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_model_route_forwards_chat_to_openai_compatible_backend(monkeypatch):
    main = load_router_main()

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "{\"intent\":\"test\"}"}}]}

    def fake_post(url, json, timeout):
        calls.append((url, json, timeout))
        return Response()

    monkeypatch.setattr(main.httpx, "post", fake_post)

    client = TestClient(main.app)
    response = client.post(
        "/model/route",
        json={
            "task": "semantic_extraction",
            "messages": [{"role": "user", "content": "提取语义"}],
            "temperature": 0.2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["task"] == "semantic_extraction"
    assert body["route"] == "external_llm"
    assert body["model"] == "qwen3.6"
    assert body["content"] == "{\"intent\":\"test\"}"
    assert calls[0][0] == "http://model.local:9161/v1/chat/completions"
    assert calls[0][1]["model"] == "qwen3.6"
    assert calls[0][1]["messages"][0]["content"] == "提取语义"


def test_model_route_forwards_non_thinking_flags(monkeypatch):
    main = load_router_main()

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url, json, timeout):
        calls.append((url, json, timeout))
        return Response()

    monkeypatch.setattr(main.httpx, "post", fake_post)

    response = TestClient(main.app).post(
        "/model/route",
        json={
            "task": "semantic_extraction",
            "messages": [{"role": "user", "content": "ping"}],
            "reasoning_effort": "none",
            "enable_thinking": False,
        },
    )

    assert response.status_code == 200
    assert calls[0][1]["reasoning_effort"] == "none"
    assert calls[0][1]["enable_thinking"] is False


def test_model_route_does_not_duplicate_v1_when_base_url_includes_v1(monkeypatch):
    monkeypatch.setenv("MODEL_BASE_URL", "http://model.local:9161/v1")
    main = load_router_main()

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "模型可用"}}]}

    def fake_post(url, json, timeout):
        calls.append((url, json, timeout))
        return Response()

    monkeypatch.setattr(main.httpx, "post", fake_post)

    response = TestClient(main.app).post(
        "/model/route",
        json={"task": "semantic_extraction", "messages": [{"role": "user", "content": "ping"}]},
    )

    assert response.status_code == 200
    assert response.json()["content"] == "模型可用"
    assert calls[0][0] == "http://model.local:9161/v1/chat/completions"


def test_model_route_describes_embedding_without_remote_chat_call(monkeypatch):
    main = load_router_main()

    def fail_post(*args, **kwargs):
        raise AssertionError("embedding route should not call chat backend")

    monkeypatch.setattr(main.httpx, "post", fail_post)

    client = TestClient(main.app)
    response = client.post("/model/route", json={"task": "embedding", "messages": []})

    assert response.status_code == 200
    assert response.json()["route"] == "local_embedding"
    assert response.json()["content"] == ""
