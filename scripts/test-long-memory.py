#!/usr/bin/env python3
"""Run a few long-term-memory checks against the assistant chat API."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


CASES = [
    ("What did Caroline research?", ["Adoption agencies"]),
    ("When is Melanie planning on going camping?", ["June 2023", "2023 年 6 月", "2023年6月"]),
    ("What is Caroline's relationship status?", ["Single", "单身"]),
    ("When did Melanie paint a sunrise?", ["2022"]),
    ("What is Caroline's identity?", ["Transgender woman", "跨性别女性"]),
    ("What fields would Caroline be likely to pursue in her educaton?", ["Psychology", "counseling"]),
    ("Where did Caroline move from 4 years ago?", ["Sweden", "瑞典"]),
    ("What activities does Melanie partake in?", ["pottery", "camping", "painting", "swimming", "陶艺", "露营"]),
]


def post_chat(base_url: str, password: str, message: str) -> dict:
    payload = json.dumps({"message": message, "limit": 12}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=payload,
        headers={"content-type": "application/json", "x-par-password": password},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--password", default="par-dev")
    args = parser.parse_args()

    failures = 0
    for question, expected_values in CASES:
        try:
            result = post_chat(args.base_url, args.password, question)
        except urllib.error.HTTPError as exc:
            print(f"FAIL {question}: HTTP {exc.code}")
            failures += 1
            continue
        answer = str(result.get("answer", ""))
        ok = any(expected.lower() in answer.lower() for expected in expected_values)
        status = "PASS" if ok else "FAIL"
        print(f"{status} {question}")
        print(f"  expected one of: {', '.join(expected_values)}")
        print(f"  answer: {answer[:300]}")
        if not ok:
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
