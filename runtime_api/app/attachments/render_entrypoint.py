from __future__ import annotations

import os
from pathlib import Path

from app.attachments.visual_render import create_visual_render_server, load_render_secret


def run() -> None:
    storage_root = Path(os.getenv("NOMI_ATTACHMENT_ROOT", "/app/data/attachments"))
    secret = load_render_secret(
        os.getenv("ATTACHMENT_RENDER_SECRET_FILE", "/run/nomi-secrets/render-token")
    )
    server = create_visual_render_server(
        host=os.getenv("ATTACHMENT_RENDER_HOST", "0.0.0.0"),
        port=int(os.getenv("ATTACHMENT_RENDER_PORT", "9170")),
        storage_root=storage_root,
        secret=secret,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
