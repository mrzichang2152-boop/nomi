from typing import Any

import httpx
import json
import os


def model_request_timeout_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("MODEL_REQUEST_TIMEOUT_SECONDS", "180")))
    except ValueError:
        return 180.0


class QwenClient:
    def __init__(self, base_url: str, model: str = "qwen3.6") -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def chat(self, messages: list[dict[str, str]], temperature: float = 0.4) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=model_request_timeout_seconds(),
            )
            response.raise_for_status()
            data = response.json()

        if "choices" in data:
            return str(data["choices"][0]["message"]["content"]).strip()
        if "response" in data:
            return str(data["response"]).strip()
        if "text" in data:
            return str(data["text"]).strip()
        if "content" in data:
            return str(data["content"]).strip()
        return str(data).strip()

    async def stream_chat(self, messages: list[dict[str, str]], temperature: float = 0.4):
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=model_request_timeout_seconds(),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    chunk = parse_stream_line(line)
                    if chunk:
                        yield chunk


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
    if "choices" in data:
        choice = data["choices"][0]
        delta = choice.get("delta") or {}
        if "content" in delta:
            return str(delta["content"])
        message = choice.get("message") or {}
        if "content" in message:
            return str(message["content"])
    for key in ("response", "text", "content"):
        if key in data:
            return str(data[key])
    return ""
