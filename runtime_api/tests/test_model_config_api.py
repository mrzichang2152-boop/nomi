import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_model_config_put_accepts_4sapi_key_without_echoing_secret(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    saved = {}

    def fake_save(body):
        saved.update(body.model_dump())
        return {
            "provider_id": "user_primary",
            "display_name": "4sapi GPT-5.4 mini",
            "provider_type": body.provider_type,
            "base_url": body.base_url,
            "model": body.model,
            "api_key_configured": bool(body.api_key),
            "api_key_hint": "****" + body.api_key[-4:],
            "auth_header_format": body.auth_header_format,
        }

    monkeypatch.setattr(main, "save_user_model_config", fake_save)
    monkeypatch.setattr(main, "reset_model_gateway", lambda: None)

    client = TestClient(main.app)
    response = client.put(
        "/api/model/config",
        headers={"x-par-password": "secret"},
        json={
            "provider_type": "openai_compatible",
            "base_url": "https://4sapi.com/v1",
            "model": "gpt-5.4-mini",
            "api_key": "sk-user-secret",
            "auth_header_format": "raw",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider_type"] == "openai_compatible"
    assert payload["base_url"] == "https://4sapi.com/v1"
    assert payload["model"] == "gpt-5.4-mini"
    assert payload["api_key_configured"] is True
    assert "sk-user-secret" not in json.dumps(payload, ensure_ascii=False)
    assert saved["api_key"] == "sk-user-secret"


def test_model_api_key_envelope_encrypts_local_secret(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    envelope = main.encrypt_model_api_key("sk-user-secret")

    assert "sk-user-secret" not in json.dumps(envelope, ensure_ascii=False)
    assert main.decrypt_model_api_key(envelope) == "sk-user-secret"


def test_model_config_get_requires_password(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    client = TestClient(main.app)
    response = client.get("/api/model/config")

    assert response.status_code == 401
