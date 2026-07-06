import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_clear_appointment_skips_model_call_and_keeps_reasonable_output(monkeypatch):
    from app import worker

    calls = []

    def fail_if_called(messages):
        calls.append(messages)
        raise AssertionError("model should not be called for clear deterministic appointment")

    monkeypatch.setattr(worker, "call_model", fail_if_called)

    semantic = worker.extract_semantics(
        "whatsapp",
        "message",
        {
            "text": "明天下午4点在人民广场见，带合同。",
            "sender_name": "Alice",
            "conversation_id": "rules-first",
            "timestamp": "2026-06-12T08:00:00+08:00",
        },
    )

    trace = semantic["entities"]["classification_trace"]
    assert calls == []
    assert trace["parser_mode"] == "rules_first"
    assert trace["latency_trace"]["model_ms"] == 0
    assert semantic["entities"]["primary_label"] == "appointment"
    assert "人民广场" in semantic["summary"]


def test_ambiguous_message_still_uses_model(monkeypatch):
    from app import worker

    calls = []

    def fake_model(messages):
        calls.append(messages)
        return '{"intent":"ordinary_chat","entities":{"labels":["ordinary_chat"]},"importance":0.1,"summary":"用户提到以后再说。"}'

    monkeypatch.setattr(worker, "call_model", fake_model)

    semantic = worker.extract_semantics(
        "whatsapp",
        "message",
        {
            "text": "这个我们之后再看看吧",
            "sender_name": "Alice",
            "conversation_id": "rules-first",
            "timestamp": "2026-06-12T08:00:00+08:00",
        },
    )

    assert len(calls) == 1
    assert semantic["entities"]["classification_trace"]["parser_mode"] == "hybrid_model_rules"
    assert semantic["summary"] == "用户提到以后再说。"
