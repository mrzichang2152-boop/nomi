from pathlib import Path
import os
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime_api"))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_readme_public_branding_uses_nomi_not_legacy_par_name():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert readme.startswith("# Nomi\n")
    assert "Private-cloud personal assistant" in readme
    assert "Personal AI Runtime" not in readme
    assert "cd /opt/par" not in readme


def test_runtime_api_public_title_uses_nomi(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from fastapi.testclient import TestClient
    from app import main

    client = TestClient(main.app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Nomi Personal Assistant Runtime"
