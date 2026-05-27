from __future__ import annotations

import hashlib
import math
import os

import httpx


VECTOR_DIMENSIONS = 384
FASTEMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
FASTEMBED_CACHE_DIR = "/models/fastembed"
_FASTEMBED_MODEL_CACHE = None


def embedding_status() -> dict[str, str | int]:
    provider = os.getenv("EMBEDDING_PROVIDER", "").strip().lower()
    if provider == "fastembed":
        return {
            "provider": "fastembed",
            "model": os.getenv("FASTEMBED_MODEL", FASTEMBED_MODEL),
            "dimensions": VECTOR_DIMENSIONS,
        }
    base_url = os.getenv("EMBEDDING_BASE_URL", "").strip()
    if base_url:
        return {
            "provider": "openai_compatible",
            "base_url": base_url,
            "model": os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            "dimensions": VECTOR_DIMENSIONS,
        }
    return {"provider": "hash_fallback", "dimensions": VECTOR_DIMENSIONS}


def normalize_vector(vector: list[float], dimensions: int = VECTOR_DIMENSIONS) -> list[float]:
    if len(vector) != dimensions:
        projected = [0.0] * dimensions
        for index, value in enumerate(vector):
            projected[index % dimensions] += float(value)
        vector = projected
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [round(float(value) / norm, 6) for value in vector]


def external_embedding(text: str) -> list[float] | None:
    base_url = os.getenv("EMBEDDING_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        return None
    payload = {
        "model": os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        "input": text,
    }
    try:
        response = httpx.post(f"{base_url}/v1/embeddings", json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        embedding = data["data"][0]["embedding"]
        return normalize_vector([float(value) for value in embedding])
    except Exception:
        return None


def fastembed_embedding(text: str) -> list[float] | None:
    global _FASTEMBED_MODEL_CACHE
    if os.getenv("EMBEDDING_PROVIDER", "").strip().lower() != "fastembed":
        return None
    try:
        if _FASTEMBED_MODEL_CACHE is None:
            from fastembed import TextEmbedding

            _FASTEMBED_MODEL_CACHE = TextEmbedding(
                model_name=os.getenv("FASTEMBED_MODEL", FASTEMBED_MODEL),
                cache_dir=os.getenv("FASTEMBED_CACHE_DIR", FASTEMBED_CACHE_DIR),
            )
        vector = next(_FASTEMBED_MODEL_CACHE.embed([text]))
        return normalize_vector([float(value) for value in vector])
    except Exception:
        return None


def text_embedding_with_provider(text: str, dimensions: int = VECTOR_DIMENSIONS) -> tuple[list[float], str]:
    if dimensions == VECTOR_DIMENSIONS:
        embedded = fastembed_embedding(text)
        if embedded:
            return embedded, "fastembed"
        embedded = external_embedding(text)
        if embedded:
            return embedded, "openai_compatible"
    vector = [0.0] * dimensions
    tokens = [token for token in text.lower().replace("\n", " ").split(" ") if token]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    return normalize_vector(vector, dimensions), "hash_fallback"


def text_embedding(text: str, dimensions: int = VECTOR_DIMENSIONS) -> list[float]:
    vector, _ = text_embedding_with_provider(text, dimensions)
    return vector


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"
