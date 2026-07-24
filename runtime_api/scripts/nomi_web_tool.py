#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from typing import Any

import httpx


def runtime_api_url() -> str:
    return os.getenv("RUNTIME_API_URL", "http://runtime-api:8080").strip().rstrip("/")


def runtime_headers() -> dict[str, str]:
    password = (os.getenv("RUNTIME_API_PASSWORD") or os.getenv("APP_PASSWORD") or "").strip()
    if not password:
        raise RuntimeError("RUNTIME_API_PASSWORD is required")
    return {"x-par-password": password}


def search(
    query: str,
    *,
    mode: str = "balanced",
    freshness: str = "none",
    max_results: int = 8,
) -> dict[str, Any]:
    response = httpx.post(
        f"{runtime_api_url()}/api/web-search/search",
        headers=runtime_headers(),
        json={
            "query": query,
            "mode": mode,
            "freshness": freshness,
            "max_results": max_results,
        },
        timeout=float(os.getenv("NOMI_WEB_TOOL_TIMEOUT_SECONDS", "30")),
    )
    response.raise_for_status()
    return response.json()


def fetch(url: str, *, focus: str = "", max_chars: int = 12000) -> dict[str, Any]:
    response = httpx.post(
        f"{runtime_api_url()}/api/web-search/fetch",
        headers=runtime_headers(),
        json={"url": url, "focus": focus, "max_chars": max_chars},
        timeout=float(os.getenv("NOMI_WEB_TOOL_TIMEOUT_SECONDS", "30")),
    )
    response.raise_for_status()
    return response.json()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Use Nomi's audited read-only Web Evidence Runtime.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--mode", choices=["quick", "balanced", "research"], default="balanced")
    search_parser.add_argument(
        "--freshness",
        choices=["none", "day", "week", "month", "year"],
        default="none",
    )
    search_parser.add_argument("--max-results", type=int, default=8)
    fetch_parser = subparsers.add_parser("fetch")
    fetch_parser.add_argument("--url", required=True)
    fetch_parser.add_argument("--focus", default="")
    fetch_parser.add_argument("--max-chars", type=int, default=12000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "search":
            result = search(
                args.query,
                mode=args.mode,
                freshness=args.freshness,
                max_results=max(1, min(args.max_results, 20)),
            )
        else:
            result = fetch(args.url, focus=args.focus, max_chars=max(500, min(args.max_chars, 100000)))
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)[:500]}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
