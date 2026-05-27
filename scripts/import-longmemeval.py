#!/usr/bin/env python3
"""Import LongMemEval answer sessions as memory episodes."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import urllib.request


LONGMEMEVAL_URL = (
    "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/"
    "longmemeval_s_cleaned.json"
)


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


def parse_dataset_date(value: str) -> str | None:
    if not value:
        return None
    normalized = value.split(" (", 1)[0]
    for fmt in ("%Y/%m/%d %H:%M", "%Y/%m/%d"):
        try:
            return datetime.strptime(normalized, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    try:
        return parsedate_to_datetime(value).isoformat()
    except Exception:
        return None


def load_dataset(url: str) -> list[dict]:
    with urllib.request.urlopen(url, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--question-limit", type=int, default=100)
    parser.add_argument("--message-limit", type=int, default=800)
    parser.add_argument("--dataset-url", default=LONGMEMEVAL_URL)
    args = parser.parse_args()

    samples = load_dataset(args.dataset_url)
    imported = 0
    imported_questions = 0

    for sample in samples[: args.question_limit]:
        answer_session_ids = set(sample.get("answer_session_ids") or [])
        if not answer_session_ids:
            continue
        session_map = dict(zip(sample.get("haystack_session_ids") or [], sample.get("haystack_sessions") or []))
        date_map = dict(zip(sample.get("haystack_session_ids") or [], sample.get("haystack_dates") or []))
        imported_question = False
        for session_id in answer_session_ids:
            session = session_map.get(session_id) or []
            session_date = date_map.get(session_id)
            timestamp = parse_dataset_date(session_date)
            for message_index, message in enumerate(session):
                if imported >= args.message_limit:
                    print(f"imported_questions={imported_questions} imported_messages={imported}")
                    return 0
                content = (message.get("content") or "").strip()
                if not content:
                    continue
                payload = {
                    "source": "longmemeval_conversation",
                    "event_type": "conversation_turn",
                    "raw_data": {
                        "dataset": "xiaowu0162/longmemeval-cleaned/longmemeval_s_cleaned.json",
                        "question_id": sample.get("question_id"),
                        "question": sample.get("question"),
                        "answer": sample.get("answer"),
                        "session_id": session_id,
                        "session_date": session_date,
                        "message_index": message_index,
                        "role": message.get("role"),
                        "content": content,
                    },
                }
                if timestamp:
                    payload["timestamp"] = timestamp
                post_json(f"{args.base_url.rstrip('/')}/event", payload)
                imported += 1
                imported_question = True
        if imported_question:
            imported_questions += 1

    print(f"imported_questions={imported_questions} imported_messages={imported}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
