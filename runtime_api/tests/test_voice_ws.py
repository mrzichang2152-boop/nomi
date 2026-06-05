import base64
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")
os.environ.setdefault("ASR_PROVIDER", "fake")


def test_voice_websocket_streams_partial_and_final(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("ASR_PROVIDER", "fake")
    from app import main

    client = TestClient(main.app)
    with client.websocket_connect("/ws/voice?password=secret") as websocket:
        websocket.send_json(
            {
                "type": "voice_start",
                "session_id": "voice-1",
                "client_type": "android_floating_ball_voice",
                "language_hint": "zh-CN",
                "audio": {
                    "codec": "pcm_s16le",
                    "sample_rate": 16000,
                    "channels": 1,
                    "frame_ms": 200,
                },
            }
        )
        ready = websocket.receive_json()

        websocket.send_json(
            {
                "type": "audio_chunk",
                "session_id": "voice-1",
                "seq": 1,
                "captured_at_ms": 1780001112223,
                "audio_base64": base64.b64encode(b"hello audio").decode("ascii"),
            }
        )
        partial = websocket.receive_json()

        websocket.send_json({"type": "voice_end", "session_id": "voice-1", "last_seq": 1})
        final = websocket.receive_json()

    assert ready == {
        "type": "voice_ready",
        "session_id": "voice-1",
        "provider": "fake",
        "max_duration_ms": 60000,
    }
    assert partial["type"] == "asr_partial"
    assert partial["session_id"] == "voice-1"
    assert partial["text"] == "测试语音"
    assert partial["stable"] is False
    assert 0.0 < partial["confidence"] < 1.0
    assert final["type"] == "asr_final"
    assert final["session_id"] == "voice-1"
    assert final["text"] == "测试语音"
    assert final["provider"] == "fake"
    assert final["confidence"] >= 0.78


def test_voice_websocket_rejects_wrong_password(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    client = TestClient(main.app)
    try:
        with client.websocket_connect("/ws/voice?password=wrong"):
            raise AssertionError("wrong password websocket should not connect")
    except Exception as exc:
        assert "1008" in str(exc) or "WebSocketDisconnect" in exc.__class__.__name__


def test_voice_websocket_rejects_oversized_audio_chunk(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("ASR_PROVIDER", "fake")
    from app import main

    client = TestClient(main.app)
    oversized = b"x" * 17000
    with client.websocket_connect("/ws/voice?password=secret") as websocket:
        websocket.send_json(
            {
                "type": "voice_start",
                "session_id": "voice-oversized",
                "audio": {"codec": "pcm_s16le", "sample_rate": 16000, "channels": 1, "frame_ms": 200},
            }
        )
        websocket.receive_json()
        websocket.send_json(
            {
                "type": "audio_chunk",
                "session_id": "voice-oversized",
                "seq": 1,
                "audio_base64": base64.b64encode(oversized).decode("ascii"),
            }
        )
        error = websocket.receive_json()

    assert error["type"] == "voice_error"
    assert error["code"] == "audio_chunk_too_large"
    assert "过大" in error["message"]


def test_voice_websocket_cancel_closes_provider_session(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("ASR_PROVIDER", "fake")
    from app import main

    client = TestClient(main.app)
    with client.websocket_connect("/ws/voice?password=secret") as websocket:
        websocket.send_json({"type": "voice_start", "session_id": "voice-cancel"})
        websocket.receive_json()
        websocket.send_json({"type": "voice_cancel", "session_id": "voice-cancel", "reason": "user"})
        cancelled = websocket.receive_json()

    assert cancelled == {
        "type": "voice_cancelled",
        "session_id": "voice-cancel",
        "reason": "user",
    }
