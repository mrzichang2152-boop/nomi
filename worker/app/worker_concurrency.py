from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar


T = TypeVar("T")
R = TypeVar("R")


class DedupeLockRegistry:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def lock_for(self, key: str) -> threading.Lock:
        normalized = str(key or "default")
        with self._guard:
            lock = self._locks.get(normalized)
            if lock is None:
                lock = threading.Lock()
                self._locks[normalized] = lock
            return lock


def process_entries_with_locks(
    entries: list[T],
    *,
    process_fn: Callable[[T], R],
    key_fn: Callable[[T], str],
    lock_registry: DedupeLockRegistry,
    max_workers: int,
) -> list[R]:
    worker_count = max(1, int(max_workers))
    if worker_count == 1 or len(entries) <= 1:
        return [process_fn(entry) for entry in entries]

    def guarded(entry: T) -> R:
        with lock_registry.lock_for(key_fn(entry)):
            return process_fn(entry)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(guarded, entry) for entry in entries]
        return [future.result() for future in futures]
