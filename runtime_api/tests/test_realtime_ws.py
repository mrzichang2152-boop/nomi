import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_websocket_streams_chat_delta_and_done(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    monkeypatch.setattr(main, "retrieve_context", lambda message, limit, request_scope=None: [{"layer": "semantic_memory", "summary": "用户最近收到订单邮件"}])

    async def fake_stream_chat(self, messages, temperature=0.4):
        yield "需要"
        yield "处理"

    monkeypatch.setattr(main.QwenClient, "stream_chat", fake_stream_chat)

    async def no_realtime_listener(websocket):
        await main.asyncio.Event().wait()

    monkeypatch.setattr(main, "redis_realtime_listener", no_realtime_listener)

    client = TestClient(main.app)
    with client.websocket_connect("/ws?password=secret") as websocket:
        websocket.send_json({"type": "chat_message", "message": "我有什么要处理？"})
        first = websocket.receive_json()
        second = websocket.receive_json()
        done = websocket.receive_json()

    assert first == {"type": "chat_delta", "delta": "需要"}
    assert second == {"type": "chat_delta", "delta": "处理"}
    assert done["type"] == "chat_done"
    assert done["answer"] == "需要处理"
    assert done["sources"][0]["layer"] == "semantic_memory"


def test_websocket_rejects_wrong_password(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    client = TestClient(main.app)
    try:
        with client.websocket_connect("/ws?password=wrong"):
            raise AssertionError("wrong password websocket should not connect")
    except Exception as exc:
        assert "1008" in str(exc) or "WebSocketDisconnect" in exc.__class__.__name__
