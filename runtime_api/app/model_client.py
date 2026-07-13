from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote, urlencode

import httpx
import json
import os

from app.attachments.model_content import ChatContent, ChatMessage, qwen_provider_messages


def model_request_timeout_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("MODEL_REQUEST_TIMEOUT_SECONDS", "180")))
    except ValueError:
        return 180.0


def qwen_non_thinking_options(model: str) -> dict[str, Any]:
    if "qwen" not in str(model or "").lower():
        return {}
    return {
        "reasoning_effort": "none",
        "enable_thinking": False,
    }


@dataclass(frozen=True)
class ModelClientConfig:
    provider_type: str = "openai_compatible"
    base_url: str = "https://4sapi.com/v1"
    model: str = "gpt-5.4-mini"
    api_key: str = ""
    auth_header_format: str = "raw"
    max_output_tokens: int = 8192
    reasoning_effort: str = "none"
    enable_thinking: Optional[bool] = None
    anthropic_version: str = "2023-06-01"


class ChatCompletionClient:
    def __init__(self, config: ModelClientConfig) -> None:
        self.config = config
        self.provider_type = normalize_provider_type(config.provider_type)
        self.base_url = config.base_url.rstrip("/")
        self.model = config.model
        self.enable_thinking = config.enable_thinking
        if self.enable_thinking is None and "qwen" in self.model.lower():
            self.enable_thinking = False

    async def chat(self, messages: list[ChatMessage], temperature: float = 0.4) -> str:
        payload, url, headers = self._build_chat_request(messages, temperature=temperature, stream=False)
        async with httpx.AsyncClient() as client:
            if headers:
                response = await client.post(url, json=payload, headers=headers, timeout=model_request_timeout_seconds())
            else:
                response = await client.post(url, json=payload, timeout=model_request_timeout_seconds())
            response.raise_for_status()
            return extract_chat_response_text(self.provider_type, response.json()).strip()

    async def stream_chat(self, messages: list[ChatMessage], temperature: float = 0.4):
        payload, url, headers = self._build_chat_request(messages, temperature=temperature, stream=True)
        async with httpx.AsyncClient() as client:
            stream_kwargs: dict[str, Any] = {
                "json": payload,
                "timeout": model_request_timeout_seconds(),
            }
            if headers:
                stream_kwargs["headers"] = headers
            async with client.stream("POST", url, **stream_kwargs) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    chunk = parse_provider_stream_line(self.provider_type, line)
                    if chunk:
                        yield chunk

    def _build_chat_request(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float,
        stream: bool,
    ) -> tuple[dict[str, Any], str, dict[str, str]]:
        if self.provider_type == "anthropic":
            return self._build_anthropic_request(messages, temperature=temperature, stream=stream)
        if self.provider_type == "google":
            return self._build_google_request(messages, temperature=temperature, stream=stream)
        return self._build_openai_compatible_request(messages, temperature=temperature, stream=stream)

    def _build_openai_compatible_request(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float,
        stream: bool,
    ) -> tuple[dict[str, Any], str, dict[str, str]]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": qwen_provider_messages(messages),
            "temperature": temperature,
            "max_tokens": self.config.max_output_tokens,
            "stream": stream,
        }
        reasoning_effort = str(self.config.reasoning_effort or "").strip()
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if self.enable_thinking is not None:
            payload["enable_thinking"] = bool(self.enable_thinking)
        headers: dict[str, str] = {}
        if self.config.api_key.strip():
            headers["Accept"] = "application/json"
            headers["Content-Type"] = "application/json"
            headers["Authorization"] = authorization_header(self.config.api_key, self.config.auth_header_format, self.base_url)
        return payload, openai_compatible_chat_url(self.base_url), headers

    def _build_anthropic_request(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float,
        stream: bool,
    ) -> tuple[dict[str, Any], str, dict[str, str]]:
        system, conversation = anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": conversation,
            "temperature": temperature,
            "max_tokens": self.config.max_output_tokens,
            "stream": stream,
        }
        if system:
            payload["system"] = system
        return payload, f"{self.base_url}/messages", {
            "x-api-key": self.config.api_key,
            "anthropic-version": self.config.anthropic_version,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _build_google_request(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float,
        stream: bool,
    ) -> tuple[dict[str, Any], str, dict[str, str]]:
        system, contents = google_contents(messages)
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": self.config.max_output_tokens,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        verb = "streamGenerateContent" if stream else "generateContent"
        query = urlencode({"key": self.config.api_key})
        return payload, f"{self.base_url}/models/{quote(self.model, safe='') }:{verb}?{query}", {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }


class QwenClient:
    def __init__(self, base_url: str, model: str = "qwen3.6", api_key: str = "", auth_header_format: str = "bearer") -> None:
        self._client = ChatCompletionClient(
            ModelClientConfig(
                provider_type="openai_compatible",
                base_url=base_url,
                model=model,
                api_key=api_key,
                auth_header_format=auth_header_format,
            )
        )

    async def chat(self, messages: list[ChatMessage], temperature: float = 0.4) -> str:
        return await self._client.chat(messages, temperature=temperature)

    async def stream_chat(self, messages: list[ChatMessage], temperature: float = 0.4):
        async for chunk in self._client.stream_chat(messages, temperature=temperature):
            yield chunk


def normalize_provider_type(provider_type: str) -> str:
    value = (provider_type or "").strip().lower()
    aliases = {
        "openai": "openai_compatible",
        "openai-compatible": "openai_compatible",
        "openai_compatible": "openai_compatible",
        "4sapi": "openai_compatible",
        "anthropic": "anthropic",
        "claude": "anthropic",
        "google": "google",
        "gemini": "google",
    }
    if value not in aliases:
        raise ValueError(f"unsupported model provider type: {provider_type}")
    return aliases[value]


def openai_compatible_chat_url(base_url: str) -> str:
    clean = base_url.rstrip("/")
    if clean.endswith("/v1"):
        return f"{clean}/chat/completions"
    return f"{clean}/v1/chat/completions"


def authorization_header(api_key: str, mode: str, base_url: str) -> str:
    value = (api_key or "").strip()
    if not value:
        return ""
    if value.lower().startswith("bearer "):
        return value
    normalized_mode = (mode or "").strip().lower()
    if normalized_mode == "raw":
        return value
    if normalized_mode == "bearer":
        return f"Bearer {value}"
    if "4sapi.com" in base_url.lower():
        return value
    return f"Bearer {value}"


def _text_from_content(content: ChatContent) -> str:
    if isinstance(content, str):
        return content
    return "".join(
        str(part.get("text") or "")
        for part in content
        if isinstance(part, dict) and part.get("type") == "text"
    )


def split_system_messages(messages: list[ChatMessage]) -> tuple[str, list[ChatMessage]]:
    system_parts: list[str] = []
    conversation: list[ChatMessage] = []
    for message in messages:
        role = str(message.get("role") or "user").strip().lower()
        raw_content = message.get("content", "")
        content: ChatContent = raw_content if isinstance(raw_content, (str, list)) else ""
        if role == "system":
            system_text = _text_from_content(content)
            if system_text:
                system_parts.append(system_text)
            continue
        if role not in {"user", "assistant"}:
            role = "user"
        conversation.append({"role": role, "content": content})
    return "\n\n".join(system_parts).strip(), conversation or [{"role": "user", "content": ""}]


def anthropic_messages(messages: list[ChatMessage]) -> tuple[str, list[ChatMessage]]:
    return split_system_messages(messages)


def google_contents(messages: list[ChatMessage]) -> tuple[str, list[dict[str, Any]]]:
    system, conversation = split_system_messages(messages)
    contents: list[dict[str, Any]] = []
    for message in conversation:
        role = "model" if message["role"] == "assistant" else "user"
        content = message["content"]
        parts = [{"text": content}] if isinstance(content, str) else [
            {"text": str(part.get("text") or "")}
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        contents.append({"role": role, "parts": parts or [{"text": ""}]})
    return system, contents


def extract_chat_response_text(provider_type: str, data: dict[str, Any]) -> str:
    provider = normalize_provider_type(provider_type)
    if provider == "anthropic":
        parts = data.get("content") or []
        return "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
    if provider == "google":
        candidates = data.get("candidates") or []
        if candidates:
            parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
            return "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
    if "choices" in data:
        return _text_from_response_content((data["choices"][0].get("message") or {}).get("content"))
    if "response" in data:
        return str(data["response"]).strip()
    if "text" in data:
        return str(data["text"]).strip()
    if "content" in data:
        return str(data["content"]).strip()
    return str(data).strip()


def _text_from_response_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") in {None, "text", "output_text"}
        ).strip()
    return str(content).strip()


def parse_provider_stream_line(provider_type: str, line: str) -> str:
    provider = normalize_provider_type(provider_type)
    line = (line or "").strip()
    if not line:
        return ""
    if line.startswith("data:"):
        line = line[5:].strip()
    if line == "[DONE]":
        return ""
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return line
    if provider == "anthropic":
        if data.get("type") == "content_block_delta":
            delta = data.get("delta") or {}
            return str(delta.get("text") or "")
        return ""
    if provider == "google":
        return extract_chat_response_text("google", data)
    return parse_stream_data(data)


def parse_stream_line(line: str) -> str:
    line = (line or "").strip()
    if not line:
        return ""
    if line.startswith("data:"):
        line = line[5:].strip()
    if line == "[DONE]":
        return ""
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return line
    return parse_stream_data(data)


def parse_stream_data(data: dict[str, Any]) -> str:
    if "choices" in data:
        choice = data["choices"][0]
        delta = choice.get("delta") or {}
        if "content" in delta:
            return str(delta["content"])
        message = choice.get("message") or {}
        if "content" in message:
            return _text_from_response_content(message["content"])
    for key in ("response", "text", "content"):
        if key in data:
            return str(data[key])
    return ""
