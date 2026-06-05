from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class AsrPartial:
    text: str
    confidence: float | None = None
    stable: bool = False
    provider_seq: int | None = None


@dataclass(frozen=True)
class AsrFinal:
    text: str
    confidence: float | None = None
    duration_ms: int = 0
    provider: str = ""
    provider_trace: dict[str, Any] = field(default_factory=dict)


class StreamingAsrSession(Protocol):
    async def start(self, metadata: dict[str, Any]) -> None:
        raise NotImplementedError

    async def send_audio(self, pcm: bytes, seq: int) -> list[AsrPartial]:
        raise NotImplementedError

    async def finish(self) -> AsrFinal:
        raise NotImplementedError

    async def cancel(self) -> None:
        raise NotImplementedError


class StreamingAsrProvider(Protocol):
    provider_id: str

    async def open_session(self, metadata: dict[str, Any]) -> StreamingAsrSession:
        raise NotImplementedError
