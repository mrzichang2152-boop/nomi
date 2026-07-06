import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_worker_semantic_trace_contains_step_timing(monkeypatch):
    from app import worker

    monkeypatch.setattr(worker, "call_model", lambda messages: (_ for _ in ()).throw(TimeoutError("slow")))

    semantic = worker.extract_semantics(
        "whatsapp",
        "message",
        {
            "text": "明天下午4点人民广场见，带合同。",
            "conversation_id": "timing-test",
            "sender_name": "Alice",
            "timestamp": "2026-06-12T08:00:00+08:00",
        },
    )

    trace = semantic["entities"]["classification_trace"]
    assert trace["parser_mode"] == "rules_first"
    assert "latency_trace" in trace
    assert trace["latency_trace"]["total_ms"] >= 0
    assert trace["latency_trace"]["rule_ms"] >= 0
    assert trace["latency_trace"]["model_ms"] >= 0
    assert semantic["entities"]["primary_label"] == "appointment"
    assert "人民广场" in semantic["summary"]
