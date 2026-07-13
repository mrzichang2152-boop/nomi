from __future__ import annotations

import hashlib
import os
import sys
import unicodedata
import uuid
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from app.attachments.storage import (
    AttachmentRejected,
    resolve_storage_path,
    sanitize_display_filename,
    write_streamed_original,
)


class CountingStream:
    def __init__(self, chunks: list[bytes]):
        self.chunks = iter(chunks)
        self.read_count = 0
        self.requested_sizes: list[int] = []

    def read(self, size: int) -> bytes:
        self.read_count += 1
        self.requested_sizes.append(size)
        return next(self.chunks, b"")


class DisconnectingStream:
    def __init__(self):
        self.calls = 0

    def read(self, size: int) -> bytes:
        self.calls += 1
        if self.calls == 1:
            return b"partial upload"
        raise ConnectionError("client disconnected")


def test_stream_writer_hashes_in_bounded_chunks_and_returns_relative_path(tmp_path):
    payload = b"a" * 17 + b"b" * 23
    stream = CountingStream([payload[:17], payload[17:]])
    attachment_id = uuid.UUID("7fbe2065-957a-4a19-b101-f2f0631d34af")

    stored = write_streamed_original(
        stream,
        tmp_path,
        attachment_id,
        original_filename="quarterly report.pdf",
        max_bytes=1024,
    )

    assert stored.byte_size == len(payload)
    assert stored.sha256 == hashlib.sha256(payload).hexdigest()
    assert stored.relative_path.startswith("originals/7f/")
    assert not Path(stored.relative_path).is_absolute()
    assert resolve_storage_path(tmp_path, stored.relative_path).read_bytes() == payload
    assert all(size == 256 * 1024 for size in stream.requested_sizes)


def test_stream_writer_aborts_immediately_after_limit_and_removes_part(tmp_path):
    source = CountingStream([b"a" * 8, b"b" * 8, b"c" * 8, b"never read"])

    with pytest.raises(AttachmentRejected) as error:
        write_streamed_original(
            source,
            tmp_path,
            uuid.uuid4(),
            original_filename="large.pdf",
            max_bytes=16,
            chunk_size=8,
        )

    assert error.value.code == "too_large"
    assert source.read_count == 3
    assert list((tmp_path / "temporary").glob("*.part")) == []
    assert list((tmp_path / "originals").rglob("*.*")) == []


def test_stream_writer_removes_partial_file_when_client_disconnects(tmp_path):
    with pytest.raises(ConnectionError, match="client disconnected"):
        write_streamed_original(
            DisconnectingStream(),
            tmp_path,
            uuid.uuid4(),
            original_filename="notes.txt",
            max_bytes=1024,
        )

    assert list((tmp_path / "temporary").glob("*.part")) == []


def test_stream_writer_fsyncs_then_atomically_renames_on_same_filesystem(tmp_path, monkeypatch):
    from app.attachments import storage

    calls: list[tuple[str, object, object]] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def recording_fsync(fd: int) -> None:
        calls.append(("fsync", fd, None))
        real_fsync(fd)

    def recording_replace(source: os.PathLike[str], target: os.PathLike[str]) -> None:
        calls.append(("replace", Path(source), Path(target)))
        real_replace(source, target)

    monkeypatch.setattr(storage.os, "fsync", recording_fsync)
    monkeypatch.setattr(storage.os, "replace", recording_replace)

    write_streamed_original(
        CountingStream([b"durable"]),
        tmp_path,
        uuid.uuid4(),
        original_filename="notes.txt",
        max_bytes=1024,
    )

    fsync_index = next(index for index, call in enumerate(calls) if call[0] == "fsync")
    replace_index = next(index for index, call in enumerate(calls) if call[0] == "replace")
    assert fsync_index < replace_index
    source = calls[replace_index][1]
    target = calls[replace_index][2]
    assert isinstance(source, Path) and isinstance(target, Path)
    assert source.anchor == target.anchor == tmp_path.anchor


def test_server_filename_is_randomized_but_safe_extension_is_preserved(tmp_path):
    original_name = "../../My secret résumé.PDF"
    first = write_streamed_original(
        CountingStream([b"one"]),
        tmp_path,
        uuid.uuid4(),
        original_filename=original_name,
        max_bytes=1024,
    )
    second = write_streamed_original(
        CountingStream([b"two"]),
        tmp_path,
        uuid.uuid4(),
        original_filename=original_name,
        max_bytes=1024,
    )

    assert Path(first.relative_path).name != Path(second.relative_path).name
    assert Path(first.relative_path).suffix == ".pdf"
    assert "secret" not in Path(first.relative_path).name.lower()
    assert first.safe_display_filename == "My secret résumé.pdf"


def test_display_filename_is_nfc_sanitized_and_length_bounded():
    decomposed = "re\u0301sume\u0000/../" + ("x" * 400) + ".PDF"
    sanitized = sanitize_display_filename(decomposed)

    assert sanitized == unicodedata.normalize("NFC", sanitized)
    assert "/" not in sanitized and "\\" not in sanitized and "\x00" not in sanitized
    assert sanitized.endswith(".pdf")
    assert len(sanitized) <= 180


@pytest.mark.parametrize(
    "relative_path",
    ["../outside.txt", "/tmp/outside.txt", "originals/../../outside.txt"],
)
def test_resolve_storage_path_refuses_escape_from_attachment_root(tmp_path, relative_path):
    with pytest.raises(AttachmentRejected) as error:
        resolve_storage_path(tmp_path, relative_path)

    assert error.value.code == "storage_failed"
