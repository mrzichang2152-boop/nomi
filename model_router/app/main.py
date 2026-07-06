import os
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "http://localhost:9161").rstrip("/")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen3.6")
CHAT_COMPLETIONS_SUFFIX = "/chat/completions"


class RouteRequest(BaseModel):
    task: str = Field(default="semantic_extraction")
    messages: list[dict[str, str]] = Field(default_factory=list)
    temperature: float = 0.1
    stream: bool = False
    reasoning_effort: str = "none"
    enable_thinking: Optional[bool] = None


app = FastAPI(title="PAR Model Router", version="0.1.0")


def route_for_task(task: str) -> dict[str, str]:
    if task == "embedding":
        return {"route": "local_embedding", "model": os.getenv("FASTEMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")}
    if task == "reranking":
        return {"route": "lightweight_reranker", "model": os.getenv("RERANKING_MODEL", "rules-v0")}
    return {"route": "external_llm", "model": MODEL_NAME}


def extract_content(data: dict[str, Any]) -> str:
    if "choices" in data:
        return str(data["choices"][0]["message"]["content"])
    if "response" in data:
        return str(data["response"])
    if "text" in data:
        return str(data["text"])
    if "content" in data:
        return str(data["content"])
    return str(data)


def chat_completions_url() -> str:
    if MODEL_BASE_URL.endswith("/v1"):
        return f"{MODEL_BASE_URL}{CHAT_COMPLETIONS_SUFFIX}"
    return f"{MODEL_BASE_URL}/v1{CHAT_COMPLETIONS_SUFFIX}"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/model/route")
def model_route(body: RouteRequest) -> dict[str, Any]:
    selected = route_for_task(body.task)
    if selected["route"] != "external_llm":
        return {
            "task": body.task,
            "route": selected["route"],
            "model": selected["model"],
            "content": "",
        }

    payload = {
        "model": selected["model"],
        "messages": body.messages,
        "temperature": body.temperature,
        "stream": body.stream,
    }
    if body.reasoning_effort:
        payload["reasoning_effort"] = body.reasoning_effort
    if body.enable_thinking is not None:
        payload["enable_thinking"] = body.enable_thinking
    try:
        response = httpx.post(chat_completions_url(), json=payload, timeout=60)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"model backend unavailable: {exc}") from exc

    return {
        "task": body.task,
        "route": selected["route"],
        "model": selected["model"],
        "content": extract_content(response.json()),
    }
