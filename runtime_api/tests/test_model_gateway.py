import pytest
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeProvider:
    def __init__(self, provider_id, *, chunks=None, answer=None, error=None):
        from app.model_gateway import ModelProviderConfig

        self.config = ModelProviderConfig(
            provider_id=provider_id,
            display_name=provider_id,
            base_url=f"http://{provider_id}.local",
            model="fake",
            provider_type="openai_compatible",
            api_key="sk-fake-secret" if provider_id == "primary" else "",
            priority=10 if provider_id == "primary" else 20,
            enabled=True,
            supports_streaming=True,
            context_window_tokens=256000,
            privacy_tier="private_cloud",
            task_classes=("chat",),
        )
        self.chunks = chunks or []
        self.answer = answer or "".join(self.chunks)
        self.error = error

    async def chat(self, messages, temperature=0.4):
        if self.error:
            raise self.error
        return self.answer

    async def stream_chat(self, messages, temperature=0.4):
        if self.error:
            raise self.error
        for chunk in self.chunks:
            yield chunk


@pytest.mark.asyncio
async def test_gateway_falls_back_when_primary_stream_fails():
    from app.model_gateway import ModelGateway

    primary = FakeProvider("primary", error=ConnectionError("connection refused"))
    fallback = FakeProvider("fallback", chunks=["你", "好"])
    gateway = ModelGateway([primary, fallback], failure_threshold=1)

    chunks = []
    async for chunk in gateway.stream_chat([{"role": "user", "content": "hi"}]):
        chunks.append(chunk.delta)

    status = gateway.status()
    assert chunks == ["你", "好"]
    assert status["active_provider_id"] == "fallback"
    providers = {item["provider_id"]: item for item in status["providers"]}
    assert providers["primary"]["state"] == "open"
    assert providers["primary"]["last_error_type"] == "unreachable"
    assert providers["fallback"]["state"] == "closed"


@pytest.mark.asyncio
async def test_gateway_reports_structured_failure_when_all_stream_providers_fail():
    from app.model_gateway import ModelGateway, ModelGatewayError

    gateway = ModelGateway(
        [
            FakeProvider("primary", error=ConnectionError("connection refused")),
            FakeProvider("fallback", error=RuntimeError("502 bad gateway")),
        ],
        failure_threshold=1,
    )

    with pytest.raises(ModelGatewayError) as exc_info:
        async for _chunk in gateway.stream_chat([{"role": "user", "content": "hi"}]):
            pass

    error = exc_info.value.to_payload()
    assert error["status"] == "model_unavailable"
    assert error["message"] == "模型服务暂时不可用，请稍后重试。"
    assert "primary" in error["reason"]
    assert "fallback" in error["reason"]


@pytest.mark.asyncio
async def test_gateway_redacts_provider_exception_secrets_from_payload():
    from app.model_gateway import ModelGateway, ModelGatewayError

    gateway = ModelGateway(
        [
            FakeProvider(
                "primary",
                error=RuntimeError("Authorization: Bearer secret-token token=abc123 secret=raw-secret password=plain"),
            ),
        ],
        failure_threshold=1,
    )

    with pytest.raises(ModelGatewayError) as exc_info:
        await gateway.chat([{"role": "user", "content": "hi"}])

    payload = exc_info.value.to_payload()
    serialized = str(payload)
    assert "secret-token" not in serialized
    assert "abc123" not in serialized
    assert "raw-secret" not in serialized
    assert "plain" not in serialized
    assert "Bearer REDACTED" in serialized
    assert "token=REDACTED" in serialized
    assert "secret=REDACTED" in serialized


@pytest.mark.asyncio
async def test_gateway_falls_back_for_non_stream_chat_and_records_trace():
    from app.model_gateway import ModelGateway

    primary = FakeProvider("primary", error=TimeoutError("timed out"))
    fallback = FakeProvider("fallback", answer="我可以继续帮你。")
    gateway = ModelGateway([primary, fallback], failure_threshold=1)

    answer = await gateway.chat([{"role": "user", "content": "继续"}])

    assert answer.text == "我可以继续帮你。"
    assert answer.provider_id == "fallback"
    assert answer.trace["fallback_from"] == ["primary"]
    assert gateway.status()["active_provider_id"] == "fallback"


def test_gateway_status_uses_configured_provider_order():
    from app.model_gateway import ModelGateway

    gateway = ModelGateway(
        [
            FakeProvider("fallback", chunks=["备"]),
            FakeProvider("primary", chunks=["主"]),
        ]
    )

    status = gateway.status()

    assert [item["provider_id"] for item in status["providers"]] == ["primary", "fallback"]
    assert status["active_provider_id"] == "primary"
    assert status["providers"][0]["provider_type"] == "openai_compatible"
    assert status["providers"][0]["api_key_configured"] is True
    assert "api_key" not in status["providers"][0]


def test_default_model_provider_uses_4sapi_gpt54mini_without_env(monkeypatch):
    from app.model_gateway import default_model_providers

    for key in [
        "MODEL_PROVIDER_ID",
        "MODEL_PROVIDER_NAME",
        "MODEL_PROVIDER_TYPE",
        "MODEL_BASE_URL",
        "MODEL_NAME",
        "MODEL_API_KEY",
        "MODEL_AUTH_HEADER_FORMAT",
    ]:
        monkeypatch.delenv(key, raising=False)

    providers = default_model_providers()
    config = providers[0].config

    assert config.provider_id == "4sapi_primary"
    assert config.display_name == "4sapi GPT-5.4 mini"
    assert config.provider_type == "openai_compatible"
    assert config.base_url == "https://4sapi.com/v1"
    assert config.model == "gpt-5.4-mini"
    assert config.api_key == ""
    assert config.privacy_tier == "external_api"
