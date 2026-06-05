from __future__ import annotations

from typing import Any

from .asr_provider import AsrFinal, AsrPartial, StreamingAsrSession


class FakeStreamingAsrProvider:
    provider_id = "fake"

    async def open_session(self, metadata: dict[str, Any]) -> StreamingAsrSession:
        return FakeStreamingAsrSession(metadata)


class FakeStreamingAsrSession:
    def __init__(self, metadata: dict[str, Any]) -> None:
        self.metadata = metadata
        self.started = False
        self.cancelled = False
        self.audio_chunks: list[bytes] = []

    async def start(self, metadata: dict[str, Any]) -> None:
        self.started = True

    async def send_audio(self, pcm: bytes, seq: int) -> list[AsrPartial]:
        self.audio_chunks.append(pcm)
        return [AsrPartial(text="测试语音", confidence=0.72, stable=False, provider_seq=seq)]

    async def finish(self) -> AsrFinal:
        duration_ms = max(200, len(self.audio_chunks) * 200)
        return AsrFinal(
            text="测试语音",
            confidence=0.86,
            duration_ms=duration_ms,
            provider="fake",
            provider_trace={"chunks": len(self.audio_chunks)},
        )

    async def cancel(self) -> None:
        self.cancelled = True
