from __future__ import annotations

import asyncio
import gzip
import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from .asr_provider import AsrFinal, AsrPartial, StreamingAsrSession


PROTOCOL_VERSION = 0x1
HEADER_SIZE_WORDS = 0x1

MESSAGE_TYPE_FULL_CLIENT_REQUEST = 0x1
MESSAGE_TYPE_AUDIO_ONLY_REQUEST = 0x2
MESSAGE_TYPE_FULL_SERVER_RESPONSE = 0x9
MESSAGE_TYPE_ERROR_RESPONSE = 0xF

MESSAGE_FLAG_LAST_PACKAGE = 0x2

SERIALIZATION_NONE = 0x0
SERIALIZATION_JSON = 0x1

COMPRESSION_NONE = 0x0
COMPRESSION_GZIP = 0x1

DEFAULT_ENDPOINT = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
DEFAULT_RESOURCE_ID = "volc.bigasr.sauc.duration"


@dataclass(frozen=True)
class VolcengineHeader:
    version: int
    header_size_words: int
    message_type: int
    flags: int
    serialization: int
    compression: int
    reserved: int

    @property
    def last_package(self) -> bool:
        return bool(self.flags & MESSAGE_FLAG_LAST_PACKAGE)


@dataclass(frozen=True)
class VolcengineConfig:
    endpoint: str = DEFAULT_ENDPOINT
    resource_id: str = DEFAULT_RESOURCE_ID
    api_key: str = ""
    app_key: str = ""
    access_key: str = ""
    connect_timeout_seconds: float = 5.0
    stream_timeout_seconds: float = 90.0

    @classmethod
    def from_env(cls) -> "VolcengineConfig":
        api_key = os.getenv("VOLC_ASR_API_KEY", "").strip()
        app_key = (os.getenv("VOLC_ASR_APP_KEY") or os.getenv("VOLC_ASR_SECRET_KEY") or "").strip()
        access_key = (os.getenv("VOLC_ASR_ACCESS_KEY") or os.getenv("VOLC_ASR_ACCESS_TOKEN") or "").strip()
        return cls(
            endpoint=os.getenv("VOLC_ASR_ENDPOINT", DEFAULT_ENDPOINT).strip() or DEFAULT_ENDPOINT,
            resource_id=os.getenv("VOLC_ASR_RESOURCE_ID", DEFAULT_RESOURCE_ID).strip() or DEFAULT_RESOURCE_ID,
            api_key=api_key,
            app_key=app_key,
            access_key=access_key,
            connect_timeout_seconds=float(os.getenv("ASR_CONNECT_TIMEOUT_SECONDS", "5")),
            stream_timeout_seconds=float(os.getenv("ASR_STREAM_TIMEOUT_SECONDS", "90")),
        )

    def headers(self, request_id: str) -> dict[str, str]:
        headers = {
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
        }
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        else:
            headers["X-Api-App-Key"] = self.app_key
            headers["X-Api-Access-Key"] = self.access_key
        return headers


@dataclass(frozen=True)
class ParsedVolcengineResponse:
    kind: str
    sequence: int = 0
    text: str = ""
    confidence: float = 0.0
    stable: bool = False
    duration_ms: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    provider_error_code: int = 0
    user_message: str = ""


class VolcengineStreamingAsrProvider:
    provider_id = "volcengine_bigmodel_async"

    def __init__(self, config: VolcengineConfig) -> None:
        self.config = config

    @classmethod
    def from_env(cls) -> "VolcengineStreamingAsrProvider":
        return cls(VolcengineConfig.from_env())

    async def open_session(self, metadata: dict[str, Any]) -> StreamingAsrSession:
        return VolcengineStreamingAsrSession(self.config, metadata)


class VolcengineStreamingAsrSession:
    def __init__(self, config: VolcengineConfig, metadata: dict[str, Any]) -> None:
        self.config = config
        self.metadata = metadata
        self.request_id = str(uuid.uuid4())
        self.websocket: Any = None
        self.provider_log_id = ""
        self.last_text = ""
        self.duration_ms = 0
        self.closed = False

    async def start(self, metadata: dict[str, Any]) -> None:
        websockets = await _import_websockets()
        headers = self.config.headers(self.request_id)
        try:
            self.websocket = await asyncio.wait_for(
                websockets.connect(self.config.endpoint, additional_headers=headers, max_size=None),
                timeout=self.config.connect_timeout_seconds,
            )
        except TypeError:
            self.websocket = await asyncio.wait_for(
                websockets.connect(self.config.endpoint, extra_headers=headers, max_size=None),
                timeout=self.config.connect_timeout_seconds,
            )
        self.provider_log_id = _response_header(self.websocket, "X-Tt-Logid")
        await self.websocket.send(build_full_client_request(metadata))
        await self._drain_provider_events(timeout=0.2)

    async def send_audio(self, pcm: bytes, seq: int) -> list[AsrPartial]:
        if self.websocket is None:
            raise RuntimeError("volcengine websocket is not connected")
        await self.websocket.send(build_audio_only_request(pcm, last=False))
        return await self._drain_provider_events(timeout=0.01)

    async def finish(self) -> AsrFinal:
        if self.websocket is None:
            raise RuntimeError("volcengine websocket is not connected")
        await self.websocket.send(build_audio_only_request(b"", last=True))
        deadline = asyncio.get_running_loop().time() + self.config.stream_timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            partials = await self._drain_provider_events(timeout=0.5)
            if partials and partials[-1].stable:
                break
            if self.closed:
                break
        await self._close()
        return AsrFinal(
            text=self.last_text,
            confidence=0.86 if self.last_text else 0.0,
            duration_ms=self.duration_ms,
            provider="volcengine_bigmodel_async",
            provider_trace={"request_id": self.request_id, "provider_log_id": self.provider_log_id},
        )

    async def cancel(self) -> None:
        await self._close()

    async def _drain_provider_events(self, timeout: float) -> list[AsrPartial]:
        if self.websocket is None:
            return []
        partials: list[AsrPartial] = []
        while True:
            try:
                frame = await asyncio.wait_for(self.websocket.recv(), timeout=timeout)
            except asyncio.TimeoutError:
                break
            if isinstance(frame, str):
                frame = frame.encode("utf-8")
            parsed = parse_server_response(frame)
            if parsed.kind == "error":
                raise RuntimeError(parsed.user_message)
            if parsed.kind == "result":
                self.last_text = parsed.text or self.last_text
                self.duration_ms = parsed.duration_ms or self.duration_ms
                if parsed.text:
                    partials.append(
                        AsrPartial(
                            text=parsed.text,
                            confidence=parsed.confidence,
                            stable=parsed.stable,
                            provider_seq=parsed.sequence,
                        )
                    )
            timeout = 0.001
        return partials

    async def _close(self) -> None:
        if self.websocket is not None:
            await self.websocket.close()
            self.websocket = None
        self.closed = True


async def _import_websockets() -> Any:
    import websockets

    return websockets


def build_full_client_request(metadata: dict[str, Any]) -> bytes:
    audio = metadata.get("audio") if isinstance(metadata.get("audio"), dict) else {}
    payload = {
        "user": {
            "uid": "nomi-local-user",
            "platform": "Android",
            "app_version": str(metadata.get("client_type") or "nomi-android"),
        },
        "audio": {
            "format": "pcm",
            "codec": "raw",
            "rate": int(audio.get("sample_rate") or 16000),
            "bits": 16,
            "channel": int(audio.get("channels") or 1),
        },
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "enable_ddc": True,
            "enable_nonstream": True,
            "show_utterances": True,
        },
    }
    return _build_client_frame(
        MESSAGE_TYPE_FULL_CLIENT_REQUEST,
        flags=0,
        serialization=SERIALIZATION_JSON,
        compression=COMPRESSION_GZIP,
        payload=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


def build_audio_only_request(pcm: bytes, *, last: bool) -> bytes:
    return _build_client_frame(
        MESSAGE_TYPE_AUDIO_ONLY_REQUEST,
        flags=MESSAGE_FLAG_LAST_PACKAGE if last else 0,
        serialization=SERIALIZATION_NONE,
        compression=COMPRESSION_GZIP,
        payload=pcm,
    )


def parse_server_response(frame: bytes) -> ParsedVolcengineResponse:
    header = parse_header(frame[:4])
    if header.message_type == MESSAGE_TYPE_ERROR_RESPONSE:
        return _parse_error_response(header, frame)
    if header.message_type != MESSAGE_TYPE_FULL_SERVER_RESPONSE:
        return ParsedVolcengineResponse(kind="ignored")
    sequence = int.from_bytes(frame[4:8], "big", signed=True)
    payload_size = int.from_bytes(frame[8:12], "big", signed=False)
    payload = frame[12 : 12 + payload_size]
    decoded = _decode_payload(payload, header)
    data = json.loads(decoded.decode("utf-8")) if decoded else {}
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    text = str(result.get("text") or "")
    utterances = result.get("utterances") if isinstance(result.get("utterances"), list) else []
    stable = any(bool(item.get("definite")) for item in utterances if isinstance(item, dict))
    audio_info = data.get("audio_info") if isinstance(data.get("audio_info"), dict) else {}
    duration_ms = int(audio_info.get("duration") or 0)
    return ParsedVolcengineResponse(
        kind="result",
        sequence=sequence,
        text=text,
        confidence=_estimate_confidence(text, stable),
        stable=stable,
        duration_ms=duration_ms,
        payload=data,
    )


def parse_header(header: bytes) -> VolcengineHeader:
    if len(header) != 4:
        raise ValueError("volcengine frame header must be 4 bytes")
    return VolcengineHeader(
        version=(header[0] >> 4) & 0xF,
        header_size_words=header[0] & 0xF,
        message_type=(header[1] >> 4) & 0xF,
        flags=header[1] & 0xF,
        serialization=(header[2] >> 4) & 0xF,
        compression=header[2] & 0xF,
        reserved=header[3],
    )


def build_server_response_for_test(sequence: int, payload: dict[str, Any]) -> bytes:
    body = gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return (
        _header(MESSAGE_TYPE_FULL_SERVER_RESPONSE, 0, SERIALIZATION_JSON, COMPRESSION_GZIP)
        + int(sequence).to_bytes(4, "big", signed=True)
        + len(body).to_bytes(4, "big", signed=False)
        + body
    )


def build_error_response_for_test(error_code: int, message: str) -> bytes:
    body = message.encode("utf-8")
    return (
        _header(MESSAGE_TYPE_ERROR_RESPONSE, 0, SERIALIZATION_NONE, COMPRESSION_NONE)
        + int(error_code).to_bytes(4, "big", signed=False)
        + len(body).to_bytes(4, "big", signed=False)
        + body
    )


def _build_client_frame(
    message_type: int,
    *,
    flags: int,
    serialization: int,
    compression: int,
    payload: bytes,
) -> bytes:
    body = gzip.compress(payload) if compression == COMPRESSION_GZIP else payload
    return _header(message_type, flags, serialization, compression) + len(body).to_bytes(4, "big", signed=False) + body


def _header(message_type: int, flags: int, serialization: int, compression: int) -> bytes:
    return bytes(
        [
            (PROTOCOL_VERSION << 4) | HEADER_SIZE_WORDS,
            ((message_type & 0xF) << 4) | (flags & 0xF),
            ((serialization & 0xF) << 4) | (compression & 0xF),
            0,
        ]
    )


def _parse_error_response(header: VolcengineHeader, frame: bytes) -> ParsedVolcengineResponse:
    provider_error_code = int.from_bytes(frame[4:8], "big", signed=False)
    payload_size = int.from_bytes(frame[8:12], "big", signed=False)
    payload = frame[12 : 12 + payload_size]
    decoded = _decode_payload(payload, header)
    message = decoded.decode("utf-8", errors="replace")
    error_code, user_message = _map_error(provider_error_code)
    return ParsedVolcengineResponse(
        kind="error",
        provider_error_code=provider_error_code,
        error_code=error_code,
        user_message=user_message,
        payload={"message": message},
    )


def _decode_payload(payload: bytes, header: VolcengineHeader) -> bytes:
    return gzip.decompress(payload) if header.compression == COMPRESSION_GZIP else payload


def _estimate_confidence(text: str, stable: bool) -> float:
    if not text:
        return 0.0
    if stable:
        return 0.82
    return 0.75


def _map_error(provider_error_code: int) -> tuple[str, str]:
    if provider_error_code == 45000001:
        return "volc_invalid_request", "语音识别参数配置不正确。"
    if provider_error_code == 45000002:
        return "empty_audio", "没听清，再说一次。"
    if provider_error_code == 45000081:
        return "asr_stream_timeout", "语音识别等待超时，请重试。"
    if provider_error_code == 45000151:
        return "invalid_audio_format", "语音音频格式不正确。"
    if provider_error_code == 55000031:
        return "asr_provider_busy", "语音识别服务繁忙，请稍后再试。"
    if str(provider_error_code).startswith("550"):
        return "asr_provider_error", "语音识别服务暂时不可用。"
    return "asr_provider_error", "语音识别服务暂时不可用。"


def _response_header(websocket: Any, name: str) -> str:
    headers = getattr(websocket, "response_headers", None)
    if headers is None:
        headers = getattr(websocket, "response", None)
        headers = getattr(headers, "headers", None)
    if headers is None:
        return ""
    try:
        return str(headers.get(name, ""))
    except AttributeError:
        return ""
