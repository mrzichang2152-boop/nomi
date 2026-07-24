#!/usr/bin/env python3
"""Run the semantic acceptance cases for the Nomi-owned Gmail identity.

Each case points to a focused test that inspects the domain payload or side
effect count named in ``semantic_expectation``. A green process exit alone is
not treated as product evidence; the mapping makes the expected meaning
reviewable and keeps the command reproducible in local and cloud environments.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

CASES = [
    {
        "case_id": "unconfigured_identity",
        "node_id": "runtime_api/tests/test_assistant_identity_api.py::test_assistant_identities_endpoint_lists_defaults",
        "semantic_expectation": "The default Nomi Gmail identity is visible but cannot claim a provider address or connected state before configuration.",
    },
    {
        "case_id": "truthful_provider_verification",
        "node_id": "runtime_api/tests/test_assistant_identity_composio_gmail.py::test_active_pinned_account_and_profile_complete_verification",
        "semantic_expectation": "Connected state and sender address come from the active pinned Composio account and Gmail profile result.",
    },
    {
        "case_id": "assistant_account_isolation",
        "node_id": "runtime_api/tests/test_assistant_identity_composio_gmail.py::test_existing_connection_verification_never_discovers_an_unpinned_account",
        "semantic_expectation": "A user-owned or otherwise unpinned Gmail account cannot be selected as Nomi's sender identity.",
    },
    {
        "case_id": "opencode_draft_only",
        "node_id": "runtime_api/tests/test_assistant_identity_tool_gateway.py::test_opencode_can_create_idempotent_confirmation_required_email_draft",
        "semantic_expectation": "OpenCode can create a scoped persisted draft but receives no raw provider credential or direct-send capability.",
    },
    {
        "case_id": "deterministic_pipeline_routing",
        "node_id": "runtime_api/tests/test_assistant_trigger_routing.py::test_explicit_nomi_gmail_send_routes_to_core_pipeline_not_agent",
        "semantic_expectation": "An explicit Nomi Gmail request routes to the deterministic draft pipeline rather than an unrestricted agent send.",
    },
    {
        "case_id": "confirmation_binding",
        "node_id": "runtime_api/tests/test_assistant_outbound_repository.py::test_edit_persists_and_invalidates_confirmation_across_pipeline_recreation",
        "semantic_expectation": "Editing protected draft content persists the edit and invalidates the old confirmation token across pipeline recreation.",
    },
    {
        "case_id": "concurrent_duplicate_suppression",
        "node_id": "runtime_api/tests/test_assistant_outbound_repository.py::test_concurrent_cross_surface_confirmation_claim_calls_provider_only_once",
        "semantic_expectation": "Concurrent Web and Android requests with independent valid confirmation tokens permit exactly one draft claim and one Gmail provider call.",
    },
    {
        "case_id": "restart_persistence",
        "node_id": "runtime_api/tests/test_assistant_outbound_repository.py::test_outbound_state_and_confirmation_survive_pipeline_recreation",
        "semantic_expectation": "Draft, confirmation, idempotency key, and sent provider result remain authoritative after pipeline recreation.",
    },
    {
        "case_id": "inbound_scope_and_deduplication",
        "node_id": "runtime_api/tests/test_assistant_identity_api.py::test_assistant_inbox_reads_persisted_gmail_events_and_deduplicates_sync",
        "semantic_expectation": "Nomi Gmail inbound events retain assistant identity scope, normalized content, stable ids, and duplicate suppression.",
    },
    {
        "case_id": "redacted_audit",
        "node_id": "runtime_api/tests/test_assistant_identity_audit.py::test_outbound_audit_is_complete_append_only_and_redacted",
        "semantic_expectation": "Lifecycle and outbound audit events remain append-only and expose no message body, recipient secret, token, or provider credential.",
    },
]


def run_case(case: dict[str, str]) -> dict[str, object]:
    started = time.perf_counter()
    environment = os.environ.copy()
    python_path = str(ROOT / "runtime_api")
    existing_python_path = environment.get("PYTHONPATH", "").strip()
    environment["PYTHONPATH"] = (
        python_path if not existing_python_path else f"{python_path}{os.pathsep}{existing_python_path}"
    )
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", case["node_id"]],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    return {
        **case,
        "status": "passed" if completed.returncode == 0 else "failed",
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "exit_code": completed.returncode,
        "output": (completed.stdout + completed.stderr).strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="List cases without executing pytest.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    arguments = parser.parse_args()

    if arguments.list:
        payload: dict[str, object] = {"status": "listed", "cases": CASES}
    else:
        results = [run_case(case) for case in CASES]
        failed = [result for result in results if result["status"] != "passed"]
        payload = {
            "status": "passed" if not failed else "failed",
            "case_count": len(results),
            "passed_count": len(results) - len(failed),
            "failed_count": len(failed),
            "duration_ms": round(sum(float(item["duration_ms"]) for item in results), 2),
            "cases": results,
        }

    if arguments.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Nomi Gmail semantic regression: {payload['status']}")
        for case in payload["cases"]:
            suffix = "" if arguments.list else f" [{case['status']}, {case['duration_ms']} ms]"
            print(f"- {case['case_id']}{suffix}")
            print(f"  expected: {case['semantic_expectation']}")
            if not arguments.list and case["status"] != "passed":
                print(f"  evidence: {case['output']}")

    return 0 if payload["status"] in {"listed", "passed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
