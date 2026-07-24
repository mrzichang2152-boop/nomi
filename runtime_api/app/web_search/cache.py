from __future__ import annotations

import json
import time
from threading import Lock
from typing import Any, Protocol

from app.web_search.schema import SearchResponse


class WebSearchCache(Protocol):
    def get(self, key: str) -> SearchResponse | None: ...

    def set(self, key: str, response: SearchResponse, ttl_seconds: int) -> None: ...


class MemoryWebSearchCache:
    def __init__(self) -> None:
        self._values: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = Lock()

    def get(self, key: str) -> SearchResponse | None:
        with self._lock:
            item = self._values.get(key)
            if not item:
                return None
            expires_at, payload = item
            if expires_at <= time.time():
                self._values.pop(key, None)
                return None
            return SearchResponse.model_validate(payload)

    def set(self, key: str, response: SearchResponse, ttl_seconds: int) -> None:
        with self._lock:
            self._values[key] = (time.time() + max(1, ttl_seconds), response.model_dump(mode="json"))


class RedisWebSearchCache:
    def __init__(self, client: Any, prefix: str = "nomi:web-search:") -> None:
        self.client = client
        self.prefix = prefix

    def get(self, key: str) -> SearchResponse | None:
        try:
            raw = self.client.get(f"{self.prefix}{key}")
        except Exception:
            return None
        if not raw:
            return None
        try:
            return SearchResponse.model_validate(json.loads(raw))
        except (TypeError, ValueError):
            return None

    def set(self, key: str, response: SearchResponse, ttl_seconds: int) -> None:
        try:
            self.client.setex(
                f"{self.prefix}{key}",
                max(1, ttl_seconds),
                response.model_dump_json(),
            )
        except Exception:
            return
