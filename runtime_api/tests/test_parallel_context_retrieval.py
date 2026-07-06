import os
import sys
import time
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_parallel_context_retrieval_runs_independent_fetchers_concurrently():
    from app.chat_router import ChatContextRoute
    from app.context_parallel import retrieve_chat_context_parallel

    calls = []

    def slow(name):
        def fetch():
            time.sleep(0.15)
            calls.append(name)
            return [{"name": name}]

        return fetch

    route = ChatContextRoute(
        intent="task_request",
        needs_dialogue=True,
        needs_source=True,
        needs_memory=True,
        needs_agenda=True,
        needs_tasks=True,
    )

    start = time.perf_counter()
    result = retrieve_chat_context_parallel(
        route,
        fetchers={
            "source": slow("source"),
            "memory": slow("memory"),
            "dialogue": slow("dialogue"),
            "agenda": slow("agenda"),
            "tasks": slow("tasks"),
        },
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 0.45
    assert result["source"] == [{"name": "source"}]
    assert result["memory"] == [{"name": "memory"}]
    assert result["dialogue"] == [{"name": "dialogue"}]
    assert result["agenda"] == [{"name": "agenda"}]
    assert result["tasks"] == [{"name": "tasks"}]
    assert result["latency_trace"]["source_ms"] >= 100
    assert result["latency_trace"]["memory_ms"] >= 100
    assert result["latency_trace"]["total_ms"] < 450


def test_parallel_context_retrieval_runs_detailed_memory_fetchers_when_supplied():
    from app.chat_router import ChatContextRoute
    from app.context_parallel import retrieve_chat_context_parallel

    calls = []

    def slow(name):
        def fetch():
            time.sleep(0.12)
            calls.append(name)
            return [{"layer": name}]

        return fetch

    route = ChatContextRoute(
        intent="relationship_query",
        needs_dialogue=True,
        needs_memory=True,
        needs_memory_kv=True,
        needs_memory_graph=True,
        needs_memory_rag=True,
        needs_timeline=True,
    )

    start = time.perf_counter()
    result = retrieve_chat_context_parallel(
        route,
        fetchers={
            "dialogue": slow("dialogue"),
            "memory_kv": slow("memory_kv"),
            "memory_graph": slow("memory_graph"),
            "memory_rag": slow("memory_rag"),
            "timeline": slow("timeline"),
        },
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 0.4
    assert result["memory_kv"] == [{"layer": "memory_kv"}]
    assert result["memory_graph"] == [{"layer": "memory_graph"}]
    assert result["memory_rag"] == [{"layer": "memory_rag"}]
    assert result["timeline"] == [{"layer": "timeline"}]
    assert result["latency_trace"]["memory_kv_ms"] >= 100
    assert result["latency_trace"]["memory_graph_ms"] >= 100
    assert result["latency_trace"]["memory_rag_ms"] >= 100
    assert result["latency_trace"]["timeline_ms"] >= 100


def test_shared_memory_layer_fetchers_reuse_one_retrieve_context(monkeypatch):
    from app import main
    from app.chat_router import ChatContextRoute
    from app.context_parallel import retrieve_chat_context_parallel

    calls = []

    def fake_retrieve_context(query, limit, request_scope=None):
        calls.append((query, limit, request_scope))
        time.sleep(0.05)
        return [
            {"layer": "working_memory", "value": "kv"},
            {"layer": "entity_graph", "value": "graph"},
            {"layer": "vector_recall", "value": "rag"},
            {"layer": "timeline", "value": "timeline"},
        ]

    monkeypatch.setattr(main, "retrieve_context", fake_retrieve_context)

    fetchers = main.shared_memory_layer_fetchers(
        "张红是谁？",
        {
            "memory_kv": 2,
            "memory_graph": 2,
            "memory_rag": 2,
            "timeline": 2,
        },
        12,
        {"source_types": ["whatsapp"]},
        include_generic_memory=True,
    )
    route = ChatContextRoute(
        intent="relationship_query",
        needs_memory=True,
        needs_memory_kv=True,
        needs_memory_graph=True,
        needs_memory_rag=True,
        needs_timeline=True,
    )

    result = retrieve_chat_context_parallel(route, fetchers)

    assert len(calls) == 1
    assert calls[0] == ("张红是谁？", 12, {"source_types": ["whatsapp"]})
    assert result["memory_kv"] == [{"layer": "working_memory", "value": "kv"}]
    assert result["memory_graph"] == [{"layer": "entity_graph", "value": "graph"}]
    assert result["memory_rag"] == [{"layer": "vector_recall", "value": "rag"}]
    assert result["timeline"] == [{"layer": "timeline", "value": "timeline"}]
    assert len(result["memory"]) == 4
