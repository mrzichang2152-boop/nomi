from __future__ import annotations

import base64
import binascii
import os
from typing import Any, Callable

from fastapi import WebSocket, WebSocketDisconnect

from app.auth import is_authorized

from .asr_provider import StreamingAsrProvider, StreamingAsrSession
from .fake_provider import FakeStreamingAsrProvider


MAX_AUDIO_SECONDS = int(os.getenv("ASR_MAX_AUDIO_SECONDS", "60"))
MAX_DECODED_AUDIO_CHUNK_BYTES = int(os.getenv("VOICE_MAX_DECODED_AUDIO_CHUNK_BYTES", "16384"))
MAX_AUDIO_CHUNK_BASE64_CHARS = int(os.getenv("VOICE_MAX_AUDIO_CHUNK_BASE64_CHARS", "24576"))


def make_asr_provider() -> StreamingAsrProvider:
    provider = os.getenv("ASR_PROVIDER", "volcengine").strip().lower()
    if provider in {"fake", "test"}:
        return FakeStreamingAsrProvider()
    if provider in {"volc", "volcengine", "volcengine_bigmodel_async"}:
        from .volcengine_provider import VolcengineStreamingAsrProvider

        return VolcengineStreamingAsrProvider.from_env()
    return FakeStreamingAsrProvider()


async def handle_voice_websocket(
    websocket: WebSocket,
    password: str | None,
    provider_factory: Callable[[], StreamingAsrProvider] = make_asr_provider,
) -> None:
    if not is_authorized(password):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    provider = provider_factory()
    session: StreamingAsrSession | None = None
    session_id = ""
    last_seq = -1
    try:
        while True:
            data = await websocket.receive_json()
            event_type = str(data.get("type") or "")
            if event_type == "voice_start":
                if session is not None:
                    await websocket.send_json(
                        _voice_error(session_id, "voice_session_active", "已有语音识别正在进行。")
                    )
                    continue
                session_id = str(data.get("session_id") or "").strip() or "voice-session"
                metadata = _voice_metadata(data)
                session = await provider.open_session(metadata)
                await session.start(metadata)
                await websocket.send_json(
                    {
                        "type": "voice_ready",
                        "session_id": session_id,
                        "provider": getattr(provider, "provider_id", "unknown"),
                        "max_duration_ms": MAX_AUDIO_SECONDS * 1000,
                    }
                )
            elif event_type == "audio_chunk":
                if session is None:
                    await websocket.send_json(_voice_error(session_id, "voice_not_started", "请先开始语音识别。"))
                    continue
                chunk_session_id = str(data.get("session_id") or "")
                if chunk_session_id and chunk_session_id != session_id:
                    await websocket.send_json(_voice_error(session_id, "session_mismatch", "语音会话不匹配。"))
                    continue
                seq = int(data.get("seq") or 0)
                if seq <= last_seq:
                    await websocket.send_json(_voice_error(session_id, "audio_seq_out_of_order", "语音分包顺序异常。"))
                    continue
                audio = _decode_audio_base64(str(data.get("audio_base64") or ""))
                if len(audio) > MAX_DECODED_AUDIO_CHUNK_BYTES:
                    await websocket.send_json(_voice_error(session_id, "audio_chunk_too_large", "语音分包过大，请重试。"))
                    continue
                last_seq = seq
                for partial in await session.send_audio(audio, seq):
                    await websocket.send_json(
                        {
                            "type": "asr_partial",
                            "session_id": session_id,
                            "text": partial.text,
                            "confidence": _confidence(partial.confidence, 0.75),
                            "stable": bool(partial.stable),
                            "seq": seq,
                        }
                    )
            elif event_type == "voice_end":
                if session is None:
                    await websocket.send_json(_voice_error(session_id, "voice_not_started", "请先开始语音识别。"))
                    continue
                final = await session.finish()
                await websocket.send_json(
                    {
                        "type": "asr_final",
                        "session_id": session_id,
                        "transcript_id": f"voice_tr_{session_id}",
                        "text": final.text,
                        "confidence": _confidence(final.confidence, 0.86),
                        "duration_ms": final.duration_ms,
                        "provider": final.provider or getattr(provider, "provider_id", "unknown"),
                    }
                )
                session = None
            elif event_type == "voice_cancel":
                reason = str(data.get("reason") or "cancelled")
                if session is not None:
                    await session.cancel()
                await websocket.send_json({"type": "voice_cancelled", "session_id": session_id, "reason": reason})
                session = None
            elif event_type == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json(_voice_error(session_id, "unsupported_voice_message", "不支持的语音消息类型。"))
    except WebSocketDisconnect:
        if session is not None:
            await session.cancel()


def _voice_metadata(data: dict[str, Any]) -> dict[str, Any]:
    audio = data.get("audio") if isinstance(data.get("audio"), dict) else {}
    return {
        "session_id": str(data.get("session_id") or ""),
        "conversation_id": str(data.get("conversation_id") or ""),
        "client_type": str(data.get("client_type") or "android_floating_ball_voice"),
        "language_hint": str(data.get("language_hint") or "zh-CN"),
        "audio": {
            "codec": str(audio.get("codec") or "pcm_s16le"),
            "sample_rate": int(audio.get("sample_rate") or 16000),
            "channels": int(audio.get("channels") or 1),
            "frame_ms": int(audio.get("frame_ms") or 200),
        },
    }


def _decode_audio_base64(value: str) -> bytes:
    if len(value) > MAX_AUDIO_CHUNK_BASE64_CHARS:
        return b"x" * (MAX_DECODED_AUDIO_CHUNK_BYTES + 1)
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError):
        return b""


def _confidence(value: float | None, fallback: float) -> float:
    if value is None:
        return fallback
    return max(0.0, min(1.0, float(value)))


def _voice_error(session_id: str, code: str, message: str) -> dict[str, Any]:
    return {"type": "voice_error", "session_id": session_id, "code": code, "message": message}
