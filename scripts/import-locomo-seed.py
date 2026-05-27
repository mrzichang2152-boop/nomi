#!/usr/bin/env python3
"""Import a small LoCoMo sample into PAR through the public event API."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request


LOCOMO_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"


def post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()

    with urllib.request.urlopen(LOCOMO_URL, timeout=60) as response:
        samples = json.loads(response.read().decode("utf-8"))

    imported = 0
    for sample_index, sample in enumerate(samples):
        qa = sample.get("qa", [])
        for item in qa:
            if imported >= args.limit:
                print(f"imported={imported}")
                return 0
            payload = {
                "source": "locomo_seed",
                "event_type": "long_term_memory_qa",
                "raw_data": {
                    "sample_index": sample_index,
                    "question": item.get("question"),
                    "answer": item.get("answer"),
                    "category": item.get("category"),
                    "evidence": item.get("evidence", []),
                    "dataset": "snap-research/locomo data/locomo10.json",
                },
            }
            post_json(f"{args.base_url.rstrip('/')}/event", payload)
            imported += 1
    print(f"imported={imported}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
