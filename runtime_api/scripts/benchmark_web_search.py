#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "runtime_api"))

from app.web_search.runtime import build_web_search_service, web_search_provider_status  # noqa: E402
from app.web_search.schema import SearchRequest  # noqa: E402


MODES = ("quick", "balanced", "research")


def percentile(values: list[int], ratio: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * ratio))))
    return ordered[index]


def domain_matches(domain: str, expected: list[str]) -> bool:
    value = domain.lower().removeprefix("www.")
    return any(value == target.lower() or value.endswith(f".{target.lower()}") for target in expected)


def evaluate_case(case: dict[str, Any], mode: str, service: Any) -> dict[str, Any]:
    started = time.perf_counter()
    response = service.search(
        SearchRequest(
            query=str(case["query"]),
            mode=mode,
            freshness="month" if case.get("category") in {"fresh_technical", "fresh_news"} else "none",
            max_results=8,
            trace_context={"benchmark_case_id": case["id"]},
        )
    )
    domains = [(urlsplit(source.url).hostname or "").lower() for source in response.sources]
    expected = [str(value) for value in case.get("expected_domains") or []]
    first_match_rank = next((index for index, domain in enumerate(domains, start=1) if domain_matches(domain, expected)), 0)
    return {
        "case_id": case["id"],
        "category": case.get("category"),
        "mode": mode,
        "query": case["query"],
        "status": response.status,
        "source_count": len(response.sources),
        "providers_attempted": response.providers_attempted,
        "latency_ms": response.latency_ms or int((time.perf_counter() - started) * 1000),
        "expected_domains": expected,
        "top_domains": domains,
        "expected_domain_rank": first_match_rank,
        "reciprocal_rank": round(1.0 / first_match_rank, 4) if first_match_rank else 0.0,
        "errors": [error.model_dump(mode="json") for error in response.errors],
        "sources": [source.model_dump(mode="json") for source in response.sources],
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [int(item["latency_ms"]) for item in results]
    completed = [item for item in results if item["status"] in {"completed", "partial"}]
    nonempty = [item for item in results if item["source_count"] > 0]
    domain_hits = [item for item in results if item["expected_domain_rank"] > 0]
    return {
        "case_count": len(results),
        "completion_rate": round(len(completed) / max(len(results), 1), 4),
        "nonempty_rate": round(len(nonempty) / max(len(results), 1), 4),
        "expected_domain_hit_rate": round(len(domain_hits) / max(len(results), 1), 4),
        "mean_reciprocal_rank": round(statistics.fmean(item["reciprocal_rank"] for item in results), 4) if results else 0.0,
        "latency_p50_ms": percentile(latencies, 0.50),
        "latency_p95_ms": percentile(latencies, 0.95),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        default=str(ROOT / "research" / "web-search" / "fixtures" / "benchmark_queries.json"),
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "research" / "web-search" / "results" / "benchmark_result.json"),
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    provider_status = web_search_provider_status()
    if not provider_status["configured_providers"]:
        print(json.dumps({"status": "blocked", "reason": "no_web_search_provider_configured", **provider_status}, ensure_ascii=False))
        return 2
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    if args.limit > 0:
        cases = cases[: args.limit]
    service = build_web_search_service()
    results = [evaluate_case(case, mode, service) for case in cases for mode in MODES]
    payload = {
        "status": "completed",
        "provider_status": provider_status,
        "summary": summarize(results),
        "results": results,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
