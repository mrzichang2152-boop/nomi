#!/usr/bin/env python3
"""Validate memory ingestion, retrieval layers, and answer evidence quality."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request


CASES = [
    {
        "name": "LongMemEval degree fact",
        "query": "What degree did I graduate with?",
        "expected": ["Business Administration"],
        "required_layers": {"bm25_recall", "vector_recall"},
        "require_graph": True,
    },
    {
        "name": "LongMemEval coupon fact",
        "query": "Where did I redeem a $5 coupon on coffee creamer?",
        "expected": ["Target", "coffee creamer"],
        "required_layers": {"bm25_recall", "vector_recall"},
        "require_graph": True,
    },
    {
        "name": "LOCOMO identity fact",
        "query": "What is Caroline's identity?",
        "expected": ["Transgender", "跨性别"],
        "required_layers": {"bm25_recall", "vector_recall"},
        "require_graph": True,
    },
    {
        "name": "LOCOMO profile state",
        "query": "Caroline mentor transgender teen",
        "expected": ["mentor", "transgender teen", "指导", "跨性别青少年"],
        "required_layers": {"working_memory", "bm25_recall"},
        "require_state": True,
    },
]


def get_json(url: str, password: str) -> dict:
    request = urllib.request.Request(url, headers={"x-par-password": password})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def post_chat(base_url: str, password: str, message: str) -> dict:
    payload = json.dumps({"message": message, "limit": 12}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=payload,
        headers={"content-type": "application/json", "x-par-password": password},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def contains_any(payload: object, terms: list[str]) -> bool:
    text = json.dumps(payload, ensure_ascii=False).lower()
    return any(term.lower() in text for term in terms)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--password", default="par-dev")
    parser.add_argument("--chat", action="store_true", help="Also call the LLM-backed chat endpoint.")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    failures = 0
    probe = get_json(f"{base_url}/api/memory/embedding/probe", args.password)
    print("EMBEDDING_PROBE", json.dumps(probe, ensure_ascii=False))
    if probe.get("actual_provider") == "hash_fallback":
        print("FAIL embedding: actual provider is hash_fallback")
        failures += 1

    status = get_json(f"{base_url}/api/memory/status", args.password)
    print("MEMORY_STATUS", json.dumps(status, ensure_ascii=False))

    for case in CASES:
        debug = get_json(f"{base_url}/api/memory/debug?query={urllib.parse.quote(case['query'])}", args.password)
        layers = set(debug.get("retrieval_layers") or [])
        retrieval = debug.get("retrieval_sample") or []
        layer_ok = case["required_layers"].issubset(layers)
        evidence_ok = contains_any(retrieval, case["expected"])
        graph_ok = any(item.get("layer") == "entity_graph" and contains_any(item, case["expected"]) for item in retrieval)
        fact_ok = contains_any(debug.get("fact_samples") or [], case["expected"])
        state_ok = contains_any(debug.get("state_samples") or [], case["expected"])

        print(f"CASE {case['name']}")
        print(f"  query={case['query']}")
        print(f"  layers={debug.get('retrieval_layers')}")
        print(f"  evidence_ok={evidence_ok} graph_ok={graph_ok} fact_ok={fact_ok} state_ok={state_ok}")
        print(f"  retrieval_sample={json.dumps(retrieval[:2], ensure_ascii=False)[:1000]}")

        if not layer_ok:
            print(f"  FAIL missing layers: {sorted(case['required_layers'] - layers)}")
            failures += 1
        if case.get("require_graph") and not graph_ok:
            print("  FAIL expected graph evidence but graph layer did not contain the answer")
            failures += 1
        if case.get("require_state") and not state_ok:
            print("  FAIL expected KV/state evidence but state_samples did not contain the answer")
            failures += 1
        if not evidence_ok and not graph_ok and not fact_ok and not state_ok:
            print(f"  FAIL expected evidence not found: {case['expected']}")
            failures += 1

        if args.chat:
            chat = post_chat(base_url, args.password, case["query"])
            answer = chat.get("answer", "")
            answer_ok = contains_any(answer, case["expected"])
            print(f"  chat_answer={str(answer)[:500]}")
            if not answer_ok:
                print(f"  FAIL chat answer missing expected value: {case['expected']}")
                failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
