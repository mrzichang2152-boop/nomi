import asyncio
import json
import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_model_semantic_router_upgrades_ambiguous_default_route(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CONTEXT_SEMANTIC_ROUTER_ENABLED", "true")
    from app import main
    from app.model_gateway import ModelAnswer

    class FakeGateway:
        async def chat(self, messages, temperature=0.4):
            return ModelAnswer(
                text=json.dumps(
                    {
                        "intent": "memory_query",
                        "confidence": 0.79,
                        "needs": {
                            "dialogue": True,
                            "source": True,
                            "memory_graph": True,
                            "memory_rag": True,
                            "timeline": True,
                            "agenda": False,
                            "tasks": False,
                        },
                        "reason": "semantic_ambiguous_message_status",
                    },
                    ensure_ascii=False,
                ),
                provider_id="fake-router",
                trace={},
            )

    deterministic = main.route_chat_context("有消息了吗", {})
    monkeypatch.setattr(main, "model_gateway", lambda: FakeGateway())

    route = asyncio.run(main.apply_semantic_context_router("有消息了吗", {}, deterministic))

    assert deterministic.intent == "simple_chat"
    assert route.intent == "memory_query"
    assert route.needs_memory_graph is True
    assert route.needs_memory_rag is True
    assert route.needs_timeline is True
    assert route.reason == "semantic_ambiguous_message_status"


def test_model_semantic_router_falls_back_when_model_output_is_invalid(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CONTEXT_SEMANTIC_ROUTER_ENABLED", "true")
    from app import main
    from app.model_gateway import ModelAnswer

    class FakeGateway:
        async def chat(self, messages, temperature=0.4):
            return ModelAnswer(text="not json", provider_id="fake-router", trace={})

    deterministic = main.route_chat_context("有消息了吗", {})
    monkeypatch.setattr(main, "model_gateway", lambda: FakeGateway())

    route = asyncio.run(main.apply_semantic_context_router("有消息了吗", {}, deterministic))

    assert route == deterministic
