#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from app.presentation_capability import PresentationSpecError, render_presentation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a verified editable Nomi presentation")
    parser.add_argument("--spec", required=True, help="Path to the presentation specification JSON")
    parser.add_argument("--output", required=True, help="PPTX output path")
    parser.add_argument("--manifest", required=True, help="Artifact manifest output path")
    parser.add_argument(
        "--packet",
        default=os.getenv("NOMI_OPENCODE_STEP_PACKET", ""),
        help="Optional Nomi task packet used to enforce the request contract",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        task_packet = (
            json.loads(Path(args.packet).read_text(encoding="utf-8"))
            if str(args.packet or "").strip()
            else None
        )
        manifest = render_presentation(
            spec,
            args.output,
            manifest_path=args.manifest,
            task_packet=task_packet,
        )
    except (OSError, json.JSONDecodeError, PresentationSpecError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"status": "passed", "manifest": manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
