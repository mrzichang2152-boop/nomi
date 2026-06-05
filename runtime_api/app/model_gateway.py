from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterable, Protocol

import httpx

from app.model_client import QwenClient, model_request_timeout_seconds


MODEL_UNAVAILABLE_MESSAGE = "模型服务暂时不可用，请稍后重试。"


@dataclass(frozen=True)
class ModelProviderConfig:
    provider_id: str
    display_name: str
    base_url: str
    model: str
    priority: int = 100
    enabled: bool = True
    supports_streaming: bool = True
    supports_tool_calling: bool = False
    context_window_tokens: int = 256000
    default_max_output_tokens: int = 8192
    privacy_tier: str = "private_cloud"
    task_classes: tuple[str, ...] = ("chat", "classification", "slot_extraction", "summarization")


@dataclass
class ProviderRuntimeState:
    provider_id: str
    state: str = "closed"
    failure_count: int = 0
    success_count: int = 0
    last_error_type: str = ""
    last_error: str = ""
    last_failure_at: float | None = None
    last_success_at: float | None = None
    opened_at: float | None = None
    cooldown_until: float | None = None


@dataclass(frozen=True)
class ModelStreamChunk:
    delta: str
    provider_id: str
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelAnswer:
    text: str
    provider_id: str
    trace: dict[str, Any] = field(default_factory=dict)


class ModelGatewayError(RuntimeError):
    def __init__(self, reason: str, failures: list[dict[str, Any]]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.failures = failures

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": "model_unavailable",
            "message": MODEL_UNAVAILABLE_MESSAGE,
            "reason": self.reason,
            "failures": self.failures,
        }


class ChatProvider(Protocol):
    config: ModelProviderConfig

    async def chat(self, messages: list[dict[str, str]], temperature: float = 0.4) -> str:
        ...

    def stream_chat(self, messages: list[dict[str, str]], temperature: float = 0.4) -> AsyncIterator[str]:
        ...


class QwenHTTPProvider:
    def __init__(self, config: ModelProviderConfig) -> None:
        self.config = config
        self._client = QwenClient(config.base_url, config.model)

    async def chat(self, messages: list[dict[str, str]], temperature: float = 0.4) -> str:
        return await self._client.chat(messages, temperature=temperature)

    async def stream_chat(self, messages: list[dict[str, str]], temperature: float = 0.4) -> AsyncIterator[str]:
        async for chunk in self._client.stream_chat(messages, temperature=temperature):
            yield chunk

    async def health_check(self) -> dict[str, Any]:
        models_url = f"{self.config.base_url.rstrip('/')}/v1/models"
        async with httpx.AsyncClient() as client:
            response = await client.get(models_url, timeout=min(model_request_timeout_seconds(), 10.0))
            response.raise_for_status()
        return {"status": "healthy", "url": models_url}


class ModelGateway:
    def __init__(
        self,
        providers: Iterable[ChatProvider],
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
        now: Any | None = None,
    ) -> None:
        self.providers = sorted(list(providers), key=lambda provider: provider.config.priority)
        self.failure_threshold = max(1, failure_threshold)
        self.cooldown_seconds = max(1.0, cooldown_seconds)
        self._now = now or time.time
        self._states = {
            provider.config.provider_id: ProviderRuntimeState(provider.config.provider_id)
            for provider in self.providers
        }
        self._last_active_provider_id: str = self.providers[0].config.provider_id if self.providers else ""

    def status(self) -> dict[str, Any]:
        providers = [self._provider_status(provider) for provider in self.providers]
        active = self._select_provider()
        return {
            "active_provider_id": active.config.provider_id if active else self._last_active_provider_id,
            "providers": providers,
            "unavailable": active is None,
        }

    async def chat(self, messages: list[dict[str, str]], temperature: float = 0.4) -> ModelAnswer:
        failures: list[dict[str, Any]] = []
        fallback_from: list[str] = []
        for provider in self._eligible_providers():
            provider_id = provider.config.provider_id
            try:
                text = (await provider.chat(messages, temperature=temperature)).strip()
                if not text:
                    raise RuntimeError("empty model response")
                self._mark_success(provider_id)
                return ModelAnswer(text=text, provider_id=provider_id, trace={"fallback_from": fallback_from})
            except Exception as exc:
                failure = self._mark_failure(provider_id, exc)
                failures.append(failure)
                fallback_from.append(provider_id)
                continue
        raise self._unavailable_error(failures)

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.4,
    ) -> AsyncIterator[ModelStreamChunk]:
        failures: list[dict[str, Any]] = []
        fallback_from: list[str] = []
        for provider in self._eligible_providers():
            provider_id = provider.config.provider_id
            emitted = False
            try:
                async for delta in provider.stream_chat(messages, temperature=temperature):
                    if not delta:
                        continue
                    emitted = True
                    yield ModelStreamChunk(delta=delta, provider_id=provider_id, trace={"fallback_from": fallback_from})
                if emitted:
                    self._mark_success(provider_id)
                    return
                raise RuntimeError("empty model stream")
            except Exception as exc:
                failure = self._mark_failure(provider_id, exc)
                failures.append(failure)
                fallback_from.append(provider_id)
                if emitted:
                    raise self._unavailable_error(failures) from exc
                continue
        raise self._unavailable_error(failures)

    def _eligible_providers(self) -> list[ChatProvider]:
        return [provider for provider in self.providers if provider.config.enabled and not self._is_open(provider.config.provider_id)]

    def _select_provider(self) -> ChatProvider | None:
        eligible = self._eligible_providers()
        return eligible[0] if eligible else None

    def _is_open(self, provider_id: str) -> bool:
        state = self._states[provider_id]
        if state.state != "open":
            return False
        if state.cooldown_until is not None and self._now() >= state.cooldown_until:
            state.state = "half_open"
            return False
        return True

    def _mark_success(self, provider_id: str) -> None:
        state = self._states[provider_id]
        state.state = "closed"
        state.success_count += 1
        state.failure_count = 0
        state.last_error_type = ""
        state.last_error = ""
        state.last_success_at = self._now()
        state.cooldown_until = None
        self._last_active_provider_id = provider_id

    def _mark_failure(self, provider_id: str, exc: Exception) -> dict[str, Any]:
        state = self._states[provider_id]
        error_type = classify_model_error(exc)
        state.failure_count += 1
        state.last_error_type = error_type
        state.last_error = str(exc)[:500]
        state.last_failure_at = self._now()
        if state.failure_count >= self.failure_threshold:
            state.state = "open"
            state.opened_at = self._now()
            state.cooldown_until = self._now() + self.cooldown_seconds
        return {
            "provider_id": provider_id,
            "error_type": error_type,
            "error": state.last_error,
            "state": state.state,
        }

    def _provider_status(self, provider: ChatProvider) -> dict[str, Any]:
        state = self._states[provider.config.provider_id]
        return {
            "provider_id": provider.config.provider_id,
            "display_name": provider.config.display_name,
            "base_url": provider.config.base_url,
            "model": provider.config.model,
            "priority": provider.config.priority,
            "enabled": provider.config.enabled,
            "state": state.state,
            "failure_count": state.failure_count,
            "success_count": state.success_count,
            "last_error_type": state.last_error_type,
            "last_error": state.last_error,
            "cooldown_until": state.cooldown_until,
            "privacy_tier": provider.config.privacy_tier,
            "context_window_tokens": provider.config.context_window_tokens,
        }

    def _unavailable_error(self, failures: list[dict[str, Any]]) -> ModelGatewayError:
        if failures:
            reason = "; ".join(
                f"{item['provider_id']} {item['error_type']}: {item['error']}"
                for item in failures
            )
        else:
            reason = "no eligible model provider configured"
        return ModelGatewayError(reason=reason, failures=failures)


def classify_model_error(exc: Exception) -> str:
    if isinstance(exc, (ConnectionError, httpx.ConnectError, httpx.NetworkError)):
        return "unreachable"
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code == 401 or status_code == 403:
            return "auth_failed"
        if status_code == 429:
            return "rate_limited"
        return "http_error"
    message = str(exc).lower()
    if "connection refused" in message or "name or service not known" in message:
        return "unreachable"
    if "timeout" in message or "timed out" in message:
        return "timeout"
    if "502" in message or "503" in message or "504" in message or "bad gateway" in message:
        return "http_error"
    if "empty" in message:
        return "invalid_response"
    return "runtime_error"


def default_model_gateway() -> ModelGateway:
    return ModelGateway(default_model_providers())


def default_model_providers() -> list[QwenHTTPProvider]:
    primary = QwenHTTPProvider(
        ModelProviderConfig(
            provider_id=os.getenv("MODEL_PROVIDER_ID", "qwen36_primary"),
            display_name=os.getenv("MODEL_PROVIDER_NAME", "Qwen 3.6 private endpoint"),
            base_url=os.getenv("MODEL_BASE_URL", "http://localhost:9161").rstrip("/"),
            model=os.getenv("MODEL_NAME", "qwen3.6"),
            priority=10,
            enabled=os.getenv("MODEL_PROVIDER_ENABLED", "true").lower() not in {"0", "false", "no"},
            supports_streaming=True,
            context_window_tokens=int(os.getenv("MODEL_CONTEXT_WINDOW_TOKENS", "256000")),
            privacy_tier=os.getenv("MODEL_PRIVACY_TIER", "private_cloud"),
        )
    )
    providers = [primary]
    fallback_url = os.getenv("MODEL_FALLBACK_BASE_URL", "").strip()
    if fallback_url:
        providers.append(
            QwenHTTPProvider(
                ModelProviderConfig(
                    provider_id=os.getenv("MODEL_FALLBACK_PROVIDER_ID", "fallback_model"),
                    display_name=os.getenv("MODEL_FALLBACK_PROVIDER_NAME", "Fallback model endpoint"),
                    base_url=fallback_url.rstrip("/"),
                    model=os.getenv("MODEL_FALLBACK_NAME", os.getenv("MODEL_NAME", "qwen3.6")),
                    priority=20,
                    enabled=os.getenv("MODEL_FALLBACK_ENABLED", "true").lower() not in {"0", "false", "no"},
                    supports_streaming=True,
                    context_window_tokens=int(os.getenv("MODEL_FALLBACK_CONTEXT_WINDOW_TOKENS", "256000")),
                    privacy_tier=os.getenv("MODEL_FALLBACK_PRIVACY_TIER", "private_cloud"),
                )
            )
        )
    return providers
