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


def execute_tool(
    *,
    task_id: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    response = httpx.post(
        f"{runtime_api_url()}/api/assistant-tools/execute",
        headers=runtime_headers(),
        json={
            "task_id": task_id,
            "tool_name": tool_name,
            "arguments": dict(arguments),
        },
        timeout=float(os.getenv("NOMI_ASSISTANT_TOOL_TIMEOUT_SECONDS", "30")),
    )
    response.raise_for_status()
    return response.json()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Use Nomi's task-scoped assistant tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in (
        "identity-status",
        "resolve-contact",
        "create-email-draft",
        "outbound-status",
        "cancel-draft",
    ):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--task-id", required=True)

    subparsers.choices["identity-status"].add_argument(
        "--identity-id", default="nomi_gmail_primary"
    )
    subparsers.choices["resolve-contact"].add_argument("--contact-id", required=True)
    draft = subparsers.choices["create-email-draft"]
    draft.add_argument("--identity-id", default="nomi_gmail_primary")
    draft.add_argument("--contact-id", required=True)
    draft.add_argument("--subject", default="")
    draft.add_argument("--body-text", required=True)
    draft.add_argument("--evidence-id", action="append", default=[])
    draft.add_argument("--idempotency-key", required=True)
    subparsers.choices["outbound-status"].add_argument("--draft-id", required=True)
    subparsers.choices["cancel-draft"].add_argument("--draft-id", required=True)
    return parser


def command_tool_call(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    if args.command == "identity-status":
        return "assistant.identity.get_status", {"identity_id": args.identity_id}
    if args.command == "resolve-contact":
        return "assistant.contacts.resolve", {"contact_id": args.contact_id}
    if args.command == "create-email-draft":
        return "assistant.email.create_draft", {
            "identity_id": args.identity_id,
            "recipient": {"contact_id": args.contact_id},
            "subject": args.subject,
            "body_text": args.body_text,
            "source_evidence_ids": list(args.evidence_id),
            "task_id": args.task_id,
            "idempotency_key": args.idempotency_key,
        }
    if args.command == "outbound-status":
        return "assistant.outbound.get_status", {"draft_id": args.draft_id}
    return "assistant.outbound.cancel_draft", {"draft_id": args.draft_id}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    tool_name, arguments = command_tool_call(args)
    try:
        result = execute_tool(
            task_id=args.task_id,
            tool_name=tool_name,
            arguments=arguments,
        )
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)[:500]}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
