from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_pillow_pin_is_compatible_with_fastembed_042():
    requirements = (ROOT / "runtime_api" / "requirements.txt").read_text(encoding="utf-8")

    assert "fastembed==0.4.2" in requirements
    assert "Pillow==10.4.0" in requirements
    assert "Pillow==11.3.0" not in requirements


def test_runtime_image_and_services_package_opencode_capability_packs():
    dockerfile = (ROOT / "runtime_api" / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "COPY opencode_capabilities ./opencode_capabilities" in dockerfile
    setting = "NOMI_CAPABILITY_PACKS_DIR: ${NOMI_CAPABILITY_PACKS_DIR:-/app/opencode_capabilities}"
    assert compose.count(setting) >= 2


def test_opencode_worker_timeout_and_lease_cover_real_correction_runs():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    timeout = "OPENCODE_ARTIFACT_TIMEOUT_SECONDS: ${OPENCODE_ARTIFACT_TIMEOUT_SECONDS:-600}"
    lease = "OPENCODE_ARTIFACT_WORKER_LEASE_SECONDS: ${OPENCODE_ARTIFACT_WORKER_LEASE_SECONDS:-900}"
    assert compose.count(timeout) >= 2
    assert compose.count(lease) >= 2


def test_assistant_gmail_uses_current_composio_trigger_sdk_and_deployment_settings():
    requirements = (ROOT / "runtime_api" / "requirements.txt").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "composio==0.18.0" in requirements
    assert "composio==0.13.1" not in requirements
    assert (
        "ASSISTANT_GMAIL_CALLBACK_URL=http://YOUR_SERVER_HOST/"
        "api/assistant-identities/oauth/callback"
    ) in env_example
    assert "ENABLE_ASSISTANT_GMAIL_SYNC=true" in env_example
    assert "ASSISTANT_GMAIL_SYNC_INTERVAL_SECONDS=90" in env_example
    assert "ASSISTANT_GMAIL_CALLBACK_URL: ${ASSISTANT_GMAIL_CALLBACK_URL:-}" in compose
    assert "ENABLE_ASSISTANT_GMAIL_SYNC: ${ENABLE_ASSISTANT_GMAIL_SYNC:-true}" in compose


def test_composio_018_uses_a_compatible_pydantic_pin():
    requirements = (ROOT / "runtime_api" / "requirements.txt").read_text(encoding="utf-8")

    assert "composio==0.18.0" in requirements
    assert "pydantic==2.13.4" in requirements
    assert "pydantic==2.10.4" not in requirements
