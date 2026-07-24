from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

import httpx

from app.attachments.parsers.common import ParsedDerivative
from app.attachments.parsers.pdf import render_pdf_page
from app.attachments.storage import resolve_storage_path


def load_render_secret(path: Path | str) -> bytes:
    try:
        secret = Path(path).read_bytes().strip()
    except OSError as exc:
        raise OSError("attachment_render_secret_unavailable") from exc
    if len(secret) < 32:
        raise OSError("attachment_render_secret_too_short")
    return secret


def _canonical_render_request(
    *,
    source_relative_path: str,
    page_number: int,
    max_edge: int,
    expires_at: int,
) -> bytes:
    return json.dumps(
        {
            "expires_at": int(expires_at),
            "max_edge": int(max_edge),
            "page_number": int(page_number),
            "source_relative_path": str(source_relative_path),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sign_render_request(
    secret: bytes,
    *,
    source_relative_path: str,
    page_number: int,
    max_edge: int,
    expires_at: int,
) -> str:
    canonical = _canonical_render_request(
        source_relative_path=source_relative_path,
        page_number=page_number,
        max_edge=max_edge,
        expires_at=expires_at,
    )
    return hmac.new(secret, canonical, hashlib.sha256).hexdigest()


class RemotePdfRenderer:
    def __init__(
        self,
        *,
        endpoint: str,
        storage_root: Path | str,
        secret: bytes | None = None,
        secret_file: Path | str | None = None,
        timeout_seconds: float = 15.0,
        signature_ttl_seconds: int = 30,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.endpoint = str(endpoint)
        self.storage_root = Path(storage_root).resolve()
        if secret is None and secret_file is None:
            raise ValueError("attachment_render_secret_required")
        self.secret = bytes(secret) if secret is not None else None
        self.secret_file = Path(secret_file) if secret_file is not None else None
        if self.secret is not None and len(self.secret) < 32:
            raise ValueError("attachment_render_secret_too_short")
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.signature_ttl_seconds = max(1, min(int(signature_ttl_seconds), 60))
        self.clock = clock

    def _secret(self) -> bytes:
        if self.secret is not None:
            return self.secret
        assert self.secret_file is not None
        return load_render_secret(self.secret_file)

    def __call__(
        self,
        path: Path,
        *,
        page_number: int,
        max_edge: int = 2048,
    ) -> ParsedDerivative:
        try:
            relative_path = Path(path).resolve().relative_to(self.storage_root).as_posix()
        except ValueError as exc:
            raise OSError("attachment_render_source_outside_root") from exc
        expires_at = int(self.clock()) + self.signature_ttl_seconds
        signature = _sign_render_request(
            self._secret(),
            source_relative_path=relative_path,
            page_number=int(page_number),
            max_edge=int(max_edge),
            expires_at=expires_at,
        )
        try:
            response = httpx.post(
                self.endpoint,
                json={
                    "source_relative_path": relative_path,
                    "page_number": int(page_number),
                    "max_edge": int(max_edge),
                },
                headers={
                    "X-Nomi-Render-Expires": str(expires_at),
                    "X-Nomi-Render-Signature": signature,
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            width = int(response.headers.get("X-Nomi-Image-Width", "0"))
            height = int(response.headers.get("X-Nomi-Image-Height", "0"))
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise OSError("attachment_render_worker_unavailable") from exc
        return ParsedDerivative(
            kind="pdf_page",
            mime_type=response.headers.get("Content-Type", "image/png"),
            extension=".png",
            locator={"page": int(page_number)},
            metadata={"width": width, "height": height},
            payload=response.content,
        )


class _VisualRenderServer(ThreadingHTTPServer):
    storage_root: Path
    render_secret: bytes
    renderer: Callable[..., ParsedDerivative]
    render_limiter: threading.BoundedSemaphore
    clock: Callable[[], float]
    max_signature_ttl_seconds: int


class _VisualRenderHandler(BaseHTTPRequestHandler):
    server: _VisualRenderServer

    def _error(self, status: int, code: str) -> None:
        payload = json.dumps({"error": code}, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        if self.path != "/render/pdf":
            self._error(404, "not_found")
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length < 2 or content_length > 16 * 1024:
                raise ValueError("invalid_render_request_size")
            request = json.loads(self.rfile.read(content_length))
            relative_path = str(request["source_relative_path"])
            page_number = int(request["page_number"])
            max_edge = int(request.get("max_edge") or 2048)
            expires_at = int(self.headers.get("X-Nomi-Render-Expires", "0"))
            supplied_signature = self.headers.get("X-Nomi-Render-Signature", "")
            now = int(self.server.clock())
            if expires_at < now or expires_at > now + self.server.max_signature_ttl_seconds:
                self._error(401, "invalid_render_signature")
                return
            expected_signature = _sign_render_request(
                self.server.render_secret,
                source_relative_path=relative_path,
                page_number=page_number,
                max_edge=max_edge,
                expires_at=expires_at,
            )
            if not hmac.compare_digest(supplied_signature, expected_signature):
                self._error(401, "invalid_render_signature")
                return
            if page_number < 1 or max_edge < 128 or max_edge > 4096:
                raise ValueError("invalid_render_request_values")
            source_path = resolve_storage_path(self.server.storage_root, relative_path)
            if not source_path.is_file():
                raise ValueError("render_source_missing")
            with self.server.render_limiter:
                derivative = self.server.renderer(
                    source_path,
                    page_number=page_number,
                    max_edge=max_edge,
                )
            if not derivative.payload:
                raise ValueError("render_result_empty")
        except (KeyError, TypeError, ValueError, OSError):
            self._error(422, "invalid_render_request")
            return
        payload = derivative.payload
        self.send_response(200)
        self.send_header("Content-Type", derivative.mime_type or "image/png")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Nomi-Image-Width", str(int(derivative.metadata.get("width") or 0)))
        self.send_header("X-Nomi-Image-Height", str(int(derivative.metadata.get("height") or 0)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path != "/health":
            self._error(404, "not_found")
            return
        payload = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return None


def create_visual_render_server(
    *,
    host: str,
    port: int,
    storage_root: Path | str,
    secret: bytes,
    renderer: Callable[..., ParsedDerivative] = render_pdf_page,
    limiter: threading.BoundedSemaphore | None = None,
    clock: Callable[[], float] = time.time,
    max_signature_ttl_seconds: int = 60,
) -> _VisualRenderServer:
    server = _VisualRenderServer((str(host), int(port)), _VisualRenderHandler)
    server.storage_root = Path(storage_root)
    server.render_secret = bytes(secret)
    if len(server.render_secret) < 32:
        server.server_close()
        raise ValueError("attachment_render_secret_too_short")
    server.renderer = renderer
    server.render_limiter = limiter or threading.BoundedSemaphore(1)
    server.clock = clock
    server.max_signature_ttl_seconds = max(1, min(int(max_signature_ttl_seconds), 60))
    return server


__all__ = ["RemotePdfRenderer", "create_visual_render_server", "load_render_secret"]
