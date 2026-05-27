#!/usr/bin/env python3
"""Import LOCOMO conversation turns as PAR episodes."""

from __future__ import annotations

import argparse
import json
import re
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


def session_keys(sample: dict) -> list[str]:
    keys = [key for key in sample if re.match(r"^session_\d+$", key)]
    return sorted(keys, key=lambda value: int(value.split("_")[1]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--conversation-limit", type=int, default=3)
    parser.add_argument("--turn-limit", type=int, default=180)
    args = parser.parse_args()

    with urllib.request.urlopen(LOCOMO_URL, timeout=60) as response:
        samples = json.loads(response.read().decode("utf-8"))

    imported = 0
    for sample_index, sample in enumerate(samples[: args.conversation_limit]):
        conversation = sample.get("conversation", {})
        speaker_a = conversation.get("speaker_a")
        speaker_b = conversation.get("speaker_b")
        for session_key in session_keys(conversation):
            date_label = conversation.get(f"{session_key}_date_time")
            for turn_index, turn in enumerate(conversation.get(session_key, [])):
                if imported >= args.turn_limit:
                    print(f"imported={imported}")
                    return 0
                text = (turn.get("text") or "").strip()
                if not text:
                    continue
                speaker = turn.get("speaker")
                if speaker == "speaker_a":
                    speaker = speaker_a
                elif speaker == "speaker_b":
                    speaker = speaker_b
                payload = {
                    "source": "locomo_conversation",
                    "event_type": "conversation_turn",
                    "raw_data": {
                        "sample_index": sample_index,
                        "session": session_key,
                        "session_date": date_label,
                        "turn_index": turn_index,
                        "speaker": speaker,
                        "text": text,
                        "blip_caption": turn.get("blip_caption"),
                        "query": turn.get("query"),
                        "dataset": "snap-research/locomo data/locomo10.json",
                    },
                }
                post_json(f"{args.base_url.rstrip('/')}/event", payload)
                imported += 1
    print(f"imported={imported}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
