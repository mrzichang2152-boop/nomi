import gzip
import json
import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_volcengine_headers_support_access_token_and_secret_key_aliases(monkeypatch):
    monkeypatch.setenv("VOLC_ASR_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("VOLC_ASR_SECRET_KEY", "secret-key")
    monkeypatch.setenv("VOLC_ASR_RESOURCE_ID", "volc.bigasr.sauc.duration")
    from app.voice.volcengine_provider import VolcengineConfig

    config = VolcengineConfig.from_env()
    headers = config.headers("request-1")

    assert headers["X-Api-App-Key"] == "secret-key"
    assert headers["X-Api-Access-Key"] == "access-token"
    assert headers["X-Api-Resource-Id"] == "volc.bigasr.sauc.duration"
    assert headers["X-Api-Request-Id"] == "request-1"
    assert headers["X-Api-Sequence"] == "-1"


def test_volcengine_headers_prefer_new_api_key(monkeypatch):
    monkeypatch.setenv("VOLC_ASR_API_KEY", "api-key")
    monkeypatch.setenv("VOLC_ASR_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("VOLC_ASR_SECRET_KEY", "secret-key")
    from app.voice.volcengine_provider import VolcengineConfig

    config = VolcengineConfig.from_env()
    headers = config.headers("request-2")

    assert headers["X-Api-Key"] == "api-key"
    assert "X-Api-App-Key" not in headers
    assert "X-Api-Access-Key" not in headers


def test_full_client_request_frame_is_gzipped_json():
    from app.voice.volcengine_provider import (
        COMPRESSION_GZIP,
        MESSAGE_TYPE_FULL_CLIENT_REQUEST,
        SERIALIZATION_JSON,
        build_full_client_request,
        parse_header,
    )

    frame = build_full_client_request(
        {
            "session_id": "voice-1",
            "client_type": "android_floating_ball_voice",
            "audio": {"sample_rate": 16000, "channels": 1, "frame_ms": 200},
        }
    )

    header = parse_header(frame[:4])
    payload_size = int.from_bytes(frame[4:8], "big", signed=False)
    payload = gzip.decompress(frame[8 : 8 + payload_size])
    decoded = json.loads(payload.decode("utf-8"))

    assert header.message_type == MESSAGE_TYPE_FULL_CLIENT_REQUEST
    assert header.serialization == SERIALIZATION_JSON
    assert header.compression == COMPRESSION_GZIP
    assert decoded["audio"]["format"] == "pcm"
    assert decoded["audio"]["rate"] == 16000
    assert decoded["request"]["model_name"] == "bigmodel"
    assert decoded["request"]["enable_nonstream"] is True


def test_audio_only_frame_marks_last_package():
    from app.voice.volcengine_provider import (
        COMPRESSION_GZIP,
        MESSAGE_TYPE_AUDIO_ONLY_REQUEST,
        build_audio_only_request,
        parse_header,
    )

    frame = build_audio_only_request(b"pcm-bytes", last=True)
    header = parse_header(frame[:4])
    payload_size = int.from_bytes(frame[4:8], "big", signed=False)
    payload = gzip.decompress(frame[8 : 8 + payload_size])

    assert header.message_type == MESSAGE_TYPE_AUDIO_ONLY_REQUEST
    assert header.compression == COMPRESSION_GZIP
    assert header.last_package is True
    assert payload == b"pcm-bytes"


def test_parse_server_response_maps_utterance_stability():
    from app.voice.volcengine_provider import build_server_response_for_test, parse_server_response

    response = build_server_response_for_test(
        sequence=7,
        payload={
            "result": {
                "text": "帮我查路线",
                "utterances": [{"text": "帮我查路线", "definite": True}],
            },
            "audio_info": {"duration": 1200},
        },
    )

    parsed = parse_server_response(response)

    assert parsed.kind == "result"
    assert parsed.sequence == 7
    assert parsed.text == "帮我查路线"
    assert parsed.stable is True
    assert parsed.duration_ms == 1200
    assert parsed.confidence == 0.82


def test_parse_error_response_maps_user_visible_code():
    from app.voice.volcengine_provider import build_error_response_for_test, parse_server_response

    response = build_error_response_for_test(45000002, "empty audio")
    parsed = parse_server_response(response)

    assert parsed.kind == "error"
    assert parsed.error_code == "empty_audio"
    assert "没听清" in parsed.user_message
