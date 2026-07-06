import json
from pathlib import Path


DATASET_PATH = Path(__file__).resolve().parent / "fixtures" / "e2e_online_regression_dataset_2026_06_08.json"


def load_dataset():
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def resolve_ref(dataset, ref):
    current = dataset
    for part in ref.split("."):
        if isinstance(current, list):
            if part == "private_events":
                raise AssertionError("private_events must be resolved before list traversal")
            matches = [item for item in current if item.get("event_key") == part]
            assert matches, f"unresolved list ref part {part!r} in {ref!r}"
            current = matches[0]
            continue
        assert isinstance(current, dict), f"cannot traverse {part!r} in {ref!r}"
        assert part in current, f"unresolved ref {ref!r}"
        current = current[part]
    return current


def test_e2e_dataset_has_required_channel_and_product_coverage():
    dataset = load_dataset()
    cases = {case["case_id"]: case for case in dataset["cases"]}

    required_coverage = {
        "gmail_new_message",
        "whatsapp_new_message",
        "telegram_new_message",
        "automatic_agenda",
        "proactive_suggestion",
        "job_agent_pipeline",
        "long_tail_agent",
        "external_execution_blocking_or_authorization",
    }
    observed_coverage = {item for case in cases.values() for item in case["coverage"]}

    assert dataset["regression_run_id"] == "rg-20260608-e2e-fixture"
    assert required_coverage.issubset(observed_coverage)
    assert set(dataset["coverage_matrix"]) == required_coverage
    assert all(case_id in cases for case_ids in dataset["coverage_matrix"].values() for case_id in case_ids)


def test_e2e_dataset_private_events_are_offline_safe_and_traceable():
    dataset = load_dataset()
    events = dataset["private_events"]
    sources = {event["source"] for event in events}

    assert {"gmail", "whatsapp", "telegram"}.issubset(sources)
    assert all(event["raw_data"]["regression_run_id"] == dataset["regression_run_id"] for event in events)
    assert all(event["raw_data"].get("message_id") for event in events)
    assert all(event["expected_semantics"].get("primary_labels") for event in events)
    assert dataset["execution_contract"]["requires_real_external_services"] is False


def test_e2e_dataset_body_refs_resolve_to_fixture_payloads():
    dataset = load_dataset()
    refs = []
    for case in dataset["cases"]:
        for step in case["steps"]:
            if "body_ref" in step:
                refs.append(step["body_ref"])

    assert refs
    for ref in refs:
        resolved = resolve_ref(dataset, ref)
        assert isinstance(resolved, dict)
        assert resolved


def test_e2e_dataset_never_requires_live_external_execution():
    dataset = load_dataset()
    dangerous_terms = {"已付款", "已发送", "已提交", "booking completed", "live provider execution"}

    assert all(case["requires_real_external_service"] is False for case in dataset["cases"])
    for case in dataset["cases"]:
        forbidden = set(case.get("forbidden_outputs", []))
        if case["coverage"].count("external_execution_blocking_or_authorization"):
            assert forbidden
        case_expectations = json.dumps([step.get("expect", {}) for step in case["steps"]], ensure_ascii=False)
        for step in case["steps"]:
            expect = step.get("expect", {})
            if "decision.allowed" in expect:
                assert "does not execute a real" in step.get("note", "")
        if any(term in forbidden for term in dangerous_terms):
            assert any(
                key in case_expectations
                for key in [
                    "confirmation_required",
                    "blocked_until_delegated_grant",
                    "requires_confirmation",
                    "final_user_confirmation",
                    "forbidden",
                ]
            )


def test_e2e_dataset_documents_executable_runtime_paths():
    dataset = load_dataset()
    paths = {
        step.get("path") or step.get("path_template")
        for case in dataset["cases"]
        for step in case["steps"]
        if step["kind"] == "http"
    }

    assert "/event" in paths
    assert "/api/pipelines/run" in paths
    assert "/api/career/ats/preview" in paths
    assert "/api/agent-tasks" in paths
    assert "/api/delegated-automation/evaluate" in paths
    assert "/api/proactive/suggestions?limit=20" in paths
