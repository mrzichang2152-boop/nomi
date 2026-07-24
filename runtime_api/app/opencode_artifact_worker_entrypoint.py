from __future__ import annotations

import asyncio
import json
import os

from app import main as runtime_main


async def run() -> None:
    runtime_main.ensure_runtime_schemas()
    print(
        json.dumps(
            {
                "event": "opencode_artifact_worker_service_started",
                "command": os.getenv("OPENCODE_ARTIFACT_COMMAND", ""),
                "fallback_command": os.getenv("OPENCODE_ARTIFACT_FALLBACK_COMMAND", ""),
                "timeout_seconds": os.getenv("OPENCODE_ARTIFACT_TIMEOUT_SECONDS", ""),
                "batch_size": os.getenv("OPENCODE_ARTIFACT_WORKER_BATCH_SIZE", ""),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    await runtime_main.opencode_artifact_worker_loop()


if __name__ == "__main__":
    asyncio.run(run())
