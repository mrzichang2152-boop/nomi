from __future__ import annotations

import time
import threading
from collections.abc import Callable
from typing import Any


class MemoryBatcher:
    def __init__(
        self,
        *,
        max_items: int,
        max_age_seconds: float,
        flush_fn: Callable[[list[dict[str, Any]]], None],
        now: Callable[[], float] | None = None,
    ) -> None:
        self.max_items = max(1, int(max_items))
        self.max_age_seconds = max(0.1, float(max_age_seconds))
        self.flush_fn = flush_fn
        self.now = now or time.time
        self.items: list[dict[str, Any]] = []
        self.first_item_at: float | None = None
        self._lock = threading.Lock()

    def add(self, item: dict[str, Any]) -> list[list[dict[str, Any]]]:
        batch: list[dict[str, Any]] = []
        with self._lock:
            if not self.items:
                self.first_item_at = self.now()
            self.items.append(item)
            if len(self.items) >= self.max_items:
                batch = self._drain_unlocked()
        return [self._emit(batch)] if batch else []

    def flush_due(self) -> list[list[dict[str, Any]]]:
        batch: list[dict[str, Any]] = []
        with self._lock:
            if not self.items or self.first_item_at is None:
                return []
            if self.now() - self.first_item_at >= self.max_age_seconds:
                batch = self._drain_unlocked()
        return [self._emit(batch)] if batch else []

    def flush(self) -> list[dict[str, Any]]:
        with self._lock:
            batch = self._drain_unlocked()
        return self._emit(batch)

    def _drain_unlocked(self) -> list[dict[str, Any]]:
        batch = list(self.items)
        self.items.clear()
        self.first_item_at = None
        return batch

    def _emit(self, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if batch:
            self.flush_fn(batch)
        return batch
