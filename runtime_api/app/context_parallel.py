from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable
import time

from app.chat_router import ChatContextRoute


Fetchers = dict[str, Callable[[], list[Any]]]


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000.0))


def retrieve_chat_context_parallel(route: ChatContextRoute, fetchers: Fetchers) -> dict[str, Any]:
    total_start = time.perf_counter()
    enabled = {
        "source": route.needs_source,
        "memory": route.needs_memory,
        "memory_kv": getattr(route, "needs_memory_kv", False),
        "memory_graph": getattr(route, "needs_memory_graph", False),
        "memory_rag": getattr(route, "needs_memory_rag", False),
        "timeline": getattr(route, "needs_timeline", False),
        "dialogue": route.needs_dialogue,
        "agenda": route.needs_agenda,
        "tasks": route.needs_tasks,
        "external_tool_state": getattr(route, "needs_external_tool_state", False),
        "web": getattr(route, "needs_web", False),
        "attachments": getattr(route, "needs_attachments", False),
    }
    result: dict[str, Any] = {key: [] for key in enabled}
    latency: dict[str, int] = {f"{key}_ms": 0 for key in enabled}
    active = {key: fetchers[key] for key, should_run in enabled.items() if should_run and key in fetchers}

    if active:
        with ThreadPoolExecutor(max_workers=min(10, len(active))) as executor:
            future_to_key = {}
            starts: dict[str, float] = {}
            for key, fetcher in active.items():
                starts[key] = time.perf_counter()
                future_to_key[executor.submit(fetcher)] = key
            for future in as_completed(future_to_key):
                key = future_to_key[future]
                result[key] = list(future.result() or [])
                latency[f"{key}_ms"] = _elapsed_ms(starts[key])

    latency["total_ms"] = _elapsed_ms(total_start)
    result["latency_trace"] = latency
    return result
