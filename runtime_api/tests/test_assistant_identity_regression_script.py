import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "runtime_api" / "scripts" / "assistant-identity-configuration-regression.py"


def test_regression_script_lists_all_required_semantic_cases():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--list", "--json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    cases = {item["case_id"]: item for item in payload["cases"]}
    assert set(cases) == {
        "unconfigured_identity",
        "truthful_provider_verification",
        "assistant_account_isolation",
        "opencode_draft_only",
        "deterministic_pipeline_routing",
        "confirmation_binding",
        "concurrent_duplicate_suppression",
        "restart_persistence",
        "inbound_scope_and_deduplication",
        "redacted_audit",
    }
    assert all(item["node_id"].startswith("runtime_api/tests/") for item in cases.values())
    assert all(item["semantic_expectation"] for item in cases.values())
