from __future__ import annotations

from starlette.responses import Response
from starlette.staticfiles import StaticFiles


class ImmutableViewerStaticFiles(StaticFiles):
    """Cache version-pinned viewer bundles without changing other static assets."""

    async def get_response(self, path: str, scope: dict) -> Response:
        response = await super().get_response(path, scope)
        normalized = path.lstrip("/")
        if response.status_code == 200 and normalized.startswith("vendor/file-viewer/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif response.status_code == 200:
            response.headers["Cache-Control"] = "no-cache"
        return response
