import sys
import json
import subprocess
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_event_store_is_source_of_truth_and_rebuilds_derived_state():
    from app.long_tail_agent import LongTailEventStore

    store = LongTailEventStore()

    created = store.append_event(
        task_id="lta_1",
        event_type="task.created",
        payload={"original_goal": "Fill a form draft without submitting."},
        idempotency_key="lta_1:create",
    )
    duplicate = store.append_event(
        task_id="lta_1",
        event_type="task.created",
        payload={"original_goal": "duplicate should not overwrite"},
        idempotency_key="lta_1:create",
    )
    planned = store.append_event(
        task_id="lta_1",
        event_type="plan.validated",
        payload={"plan_version": 1, "current_node": "select_step"},
        idempotency_key="lta_1:plan:1",
    )
    store.append_event(
        task_id="lta_1",
        event_type="step.verified",
        step_id="inspect_page",
        payload={
            "status": "passed",
            "memory_patch": {
                "completed_step": {
                    "step_id": "inspect_page",
                    "summary": "Observed the page title and form fields.",
                }
            },
        },
        idempotency_key="lta_1:inspect_page:verified",
    )

    assert duplicate == created
    assert created["sequence"] == 1
    assert planned["sequence"] == 2

    state = store.rebuild_state("lta_1")

    assert state["task_id"] == "lta_1"
    assert state["event_count"] == 3
    assert state["original_goal"] == "Fill a form draft without submitting."
    assert state["current_node"] == "select_step"
    assert state["plan_version"] == 1
    assert state["completed_steps"] == [
        {
            "step_id": "inspect_page",
            "summary": "Observed the page title and form fields.",
        }
    ]


def test_postgres_event_store_persists_events_and_rebuilds_state_from_rows():
    from app.long_tail_agent import PostgresLongTailEventStore

    class FakeCursor:
        def __init__(self, row=None, rows=None):
            self._row = row
            self._rows = rows or []

        def fetchone(self):
            return self._row

        def fetchall(self):
            return self._rows

    class FakeConnection:
        def __init__(self):
            self.queries = []
            self.inserted_rows = []
            self.commits = 0

        def execute(self, sql, params=None):
            normalized_sql = " ".join(str(sql).split())
            self.queries.append((normalized_sql, params))
            if "WHERE task_id = %s AND idempotency_key = %s" in normalized_sql:
                return FakeCursor(row=None)
            if normalized_sql.startswith("SELECT pg_advisory_xact_lock"):
                return FakeCursor(row=None)
            if normalized_sql.startswith("SELECT COALESCE(MAX(sequence), 0) + 1"):
                return FakeCursor(row=(len(self.inserted_rows) + 1,))
            if normalized_sql.startswith("INSERT INTO long_tail_task_events"):
                self.inserted_rows.append(params)
                return FakeCursor(row=None)
            if normalized_sql.startswith("SELECT id, task_id, sequence"):
                rows = []
                for params in self.inserted_rows:
                    (
                        event_id,
                        task_id,
                        sequence,
                        event_type,
                        step_id,
                        node_name,
                        payload,
                        redaction_summary,
                        idempotency_key,
                    ) = params
                    rows.append(
                        (
                            event_id,
                            task_id,
                            sequence,
                            event_type,
                            step_id,
                            node_name,
                            payload.obj,
                            redaction_summary.obj,
                            idempotency_key,
                            "2026-06-03T00:00:00+00:00",
                        )
                    )
                return FakeCursor(rows=rows)
            raise AssertionError(f"Unexpected SQL: {normalized_sql}")

        def commit(self):
            self.commits += 1

    fake_conn = FakeConnection()
    store = PostgresLongTailEventStore(connection_factory=lambda: fake_conn)
    event = store.append_event(
        task_id="lta_pg",
        event_type="task.created",
        payload={"original_goal": "Persist this task"},
        idempotency_key="lta_pg:create",
    )
    store.append_event(
        task_id="lta_pg",
        event_type="plan.validated",
        payload={"plan_version": 1, "current_node": "select_step"},
        idempotency_key="lta_pg:validated",
    )

    events = store.task_events("lta_pg")
    state = store.rebuild_state("lta_pg")

    assert event["sequence"] == 1
    assert fake_conn.commits == 2
    assert fake_conn.inserted_rows[0][6].obj == {"original_goal": "Persist this task"}
    assert [item["event_type"] for item in events] == ["task.created", "plan.validated"]
    assert state["status"] == "running"
    assert state["original_goal"] == "Persist this task"
    assert state["current_node"] == "select_step"


def test_postgres_event_store_materializes_key_events_in_same_connection():
    from app.long_tail_agent import PostgresLongTailEventStore

    class FakeCursor:
        def __init__(self, row=None, rows=None):
            self._row = row
            self._rows = rows or []

        def fetchone(self):
            return self._row

        def fetchall(self):
            return self._rows

    class FakeConnection:
        def __init__(self):
            self.events = []
            self.materialized_tables = []

        def execute(self, sql, params=None):
            normalized_sql = " ".join(str(sql).split())
            if "WHERE task_id = %s AND idempotency_key = %s" in normalized_sql:
                return FakeCursor(row=None)
            if normalized_sql.startswith("SELECT pg_advisory_xact_lock"):
                return FakeCursor(row=None)
            if normalized_sql.startswith("SELECT COALESCE(MAX(sequence), 0) + 1"):
                return FakeCursor(row=(len(self.events) + 1,))
            if normalized_sql.startswith("INSERT INTO long_tail_task_events"):
                self.events.append(params)
                return FakeCursor(row=None)
            for table in [
                "long_tail_task_runs",
                "long_tail_task_plans",
                "long_tail_step_runs",
                "long_tail_action_requests",
                "long_tail_policy_reports",
                "long_tail_checkpoints",
            ]:
                if table in normalized_sql:
                    self.materialized_tables.append((table, normalized_sql, params))
                    return FakeCursor(row=None)
            raise AssertionError(f"Unexpected SQL: {normalized_sql}")

        def commit(self):
            pass

    fake_conn = FakeConnection()
    store = PostgresLongTailEventStore(
        connection_factory=lambda: fake_conn,
        materialize_events=True,
    )
    store.append_event(
        task_id="lta_mat",
        event_type="task.created",
        payload={"original_goal": "Materialize this task"},
    )
    store.append_event(
        task_id="lta_mat",
        event_type="plan.proposed",
        payload={"plan_version": 1, "plan": {"steps": [{"step_id": "inspect"}]}},
    )
    store.append_event(
        task_id="lta_mat",
        event_type="plan.validated",
        payload={"plan_version": 1, "current_node": "select_step", "validation_report": {"status": "valid"}},
    )
    store.append_event(
        task_id="lta_mat",
        event_type="step_packet.built",
        step_id="inspect",
        payload={"packet": {"step_id": "inspect", "allowed_actions": ["browser.observe"]}},
    )
    store.append_event(
        task_id="lta_mat",
        event_type="executor.action_requested",
        step_id="inspect",
        payload={
            "action_request": {
                "action_id": "act_1",
                "task_id": "lta_mat",
                "step_id": "inspect",
                "adapter": "browser",
                "action_type": "browser.observe",
                "target": {"kind": "page"},
                "input_summary": {},
                "risk_level": "read_only",
                "expected_effect": "Read page.",
                "requires_confirmation_token": False,
                "idempotency_key": "lta_mat:inspect:act_1",
            }
        },
    )
    store.append_event(
        task_id="lta_mat",
        event_type="policy.checked",
        step_id="inspect",
        payload={
            "action_request_id": "act_1",
            "policy_report": {
                "action_id": "act_1",
                "status": "allowed",
                "reason": "Read-only action.",
                "requires_confirmation": False,
            },
        },
    )
    store.append_event(
        task_id="lta_mat",
        event_type="checkpoint.saved",
        step_id="inspect",
        payload={"current_node": "select_step", "completed_steps": []},
    )

    tables = [table for table, _sql, _params in fake_conn.materialized_tables]

    assert tables.count("long_tail_task_runs") >= 2
    assert "long_tail_task_plans" in tables
    assert "long_tail_step_runs" in tables
    assert "long_tail_action_requests" in tables
    assert "long_tail_policy_reports" in tables
    assert "long_tail_checkpoints" in tables


def test_postgres_event_store_materializes_verifier_human_and_external_effect_events():
    from app.long_tail_agent import PostgresLongTailEventStore

    class FakeCursor:
        def __init__(self, row=None):
            self._row = row

        def fetchone(self):
            return self._row

    class FakeConnection:
        def __init__(self):
            self.event_count = 0
            self.materialized_tables = []

        def execute(self, sql, params=None):
            normalized_sql = " ".join(str(sql).split())
            if "WHERE task_id = %s AND idempotency_key = %s" in normalized_sql:
                return FakeCursor(row=None)
            if normalized_sql.startswith("SELECT pg_advisory_xact_lock"):
                return FakeCursor(row=None)
            if normalized_sql.startswith("SELECT COALESCE(MAX(sequence), 0) + 1"):
                return FakeCursor(row=(self.event_count + 1,))
            if normalized_sql.startswith("INSERT INTO long_tail_task_events"):
                self.event_count += 1
                return FakeCursor(row=None)
            for table in [
                "long_tail_step_runs",
                "long_tail_human_inputs",
                "long_tail_external_effects",
                "long_tail_task_memory",
            ]:
                if table in normalized_sql:
                    self.materialized_tables.append((table, normalized_sql, params))
                    return FakeCursor(row=None)
            return FakeCursor(row=None)

        def commit(self):
            pass

    fake_conn = FakeConnection()
    store = PostgresLongTailEventStore(
        connection_factory=lambda: fake_conn,
        materialize_events=True,
    )
    store.append_event(
        task_id="lta_effect",
        event_type="step.result_returned",
        step_id="send_email",
        payload={"executor_result": {"status": "passed", "summary": "Draft prepared."}},
    )
    store.append_event(
        task_id="lta_effect",
        event_type="step.verified",
        step_id="send_email",
        payload={"status": "passed", "memory_patch": {"completed_step": {"step_id": "send_email"}}},
    )
    store.append_event(
        task_id="lta_effect",
        event_type="memory.patch_applied",
        step_id="send_email",
        payload={"memory_patch": {"completed_step": {"step_id": "send_email"}}},
    )
    store.append_event(
        task_id="lta_effect",
        event_type="human_input.received",
        step_id="send_email",
        payload={"input_type": "confirmation", "response": {"approved": True}},
    )
    store.append_event(
        task_id="lta_effect",
        event_type="external_effect.proposed",
        step_id="send_email",
        payload={
            "effect_id": "effect_1",
            "action_request_id": "act_send",
            "effect_type": "email.send",
            "proposal": {"recipient": "alice@example.test"},
            "status": "waiting_for_confirmation",
        },
    )
    store.append_event(
        task_id="lta_effect",
        event_type="external_effect.confirmed",
        step_id="send_email",
        payload={"effect_id": "effect_1", "status": "confirmed"},
    )
    store.append_event(
        task_id="lta_effect",
        event_type="external_effect.executed",
        step_id="send_email",
        payload={"effect_id": "effect_1", "status": "executed"},
    )
    store.append_event(
        task_id="lta_effect",
        event_type="external_effect.compensation_proposed",
        step_id="send_email",
        payload={
            "effect_id": "effect_1",
            "status": "waiting_for_compensation_confirmation",
            "compensation_proposal": {"type": "correction_email"},
        },
    )

    tables = [table for table, _sql, _params in fake_conn.materialized_tables]

    assert tables.count("long_tail_step_runs") >= 2
    assert "long_tail_task_memory" in tables
    assert "long_tail_human_inputs" in tables
    assert tables.count("long_tail_external_effects") == 4


def test_policy_gate_requires_action_request_before_adapter_execution():
    from app.long_tail_agent import ActionRequest, PolicyGate

    gate = PolicyGate()

    fill = ActionRequest(
        action_id="act_fill",
        task_id="lta_1",
        step_id="fill_name",
        adapter="browser",
        action_type="browser.fill_field",
        target={"kind": "dom_selector", "value": "input[name='name']", "visible_label": "Name"},
        input_summary={"value_type": "user_approved_profile_field", "redacted_value": "A***"},
        risk_level="external_draft",
        expected_effect="Fill a visible field without submitting.",
        idempotency_key="lta_1:fill_name:act_fill",
    )
    allowed = gate.evaluate(fill, allowed_actions={"browser.fill_field", "browser.observe"})

    assert allowed["status"] == "allowed"
    assert allowed["action_id"] == "act_fill"
    assert allowed["requires_confirmation"] is False

    submit = ActionRequest(
        action_id="act_submit",
        task_id="lta_1",
        step_id="submit_form",
        adapter="browser",
        action_type="browser.submit",
        target={"kind": "button", "visible_label": "Submit"},
        input_summary={},
        risk_level="external_write",
        expected_effect="Submit the form.",
        idempotency_key="lta_1:submit_form:act_submit",
    )
    blocked = gate.evaluate(submit, allowed_actions={"browser.fill_field", "browser.observe"})

    assert blocked["status"] == "blocked"
    assert "browser.submit" in blocked["reason"]
    assert blocked["may_execute"] is False

    send_email = ActionRequest(
        action_id="act_send",
        task_id="lta_1",
        step_id="send_email",
        adapter="composio",
        action_type="email.send",
        target={"kind": "email", "value": "alice@example.test"},
        input_summary={"subject": "Quote", "body_hash": "sha256:abc"},
        risk_level="external_message",
        expected_effect="Send an email to Alice.",
        idempotency_key="lta_1:send_email:act_send",
    )
    needs_confirmation = gate.evaluate(send_email, allowed_actions={"email.send"})

    assert needs_confirmation["status"] == "requires_confirmation"
    assert needs_confirmation["requires_confirmation"] is True
    assert needs_confirmation["may_execute"] is False


def test_verifier_rejects_executor_summary_without_independent_evidence():
    from app.long_tail_agent import StepVerifier

    verifier = StepVerifier()
    step = {
        "step_id": "inspect_page",
        "step_type": "browser_page_read",
        "objective": "Identify page title and visible form fields.",
        "expected_outputs": ["page_title", "field_list"],
        "verification_criteria": [
            "The page title is reported.",
            "The visible form fields are listed.",
        ],
    }
    executor_result = {
        "status": "passed",
        "summary": "Found an application page.",
        "outputs": {"page_title": "Apply Now", "field_list": ["name", "email"]},
        "evidence": [],
        "action_events": [],
    }

    report = verifier.verify(step, executor_result)

    assert report["status"] == "retry"
    assert report["score"] < 0.5
    assert "independent evidence" in report["reason"]
    assert report["missing_outputs"] == []


def test_verifier_accepts_browser_observation_with_required_outputs():
    from app.long_tail_agent import StepVerifier

    verifier = StepVerifier()
    step = {
        "step_id": "inspect_page",
        "step_type": "browser_page_read",
        "objective": "Identify page title and visible form fields.",
        "expected_outputs": ["page_title", "field_list"],
        "verification_criteria": [
            "The page title is reported.",
            "The visible form fields are listed.",
        ],
    }
    executor_result = {
        "status": "passed",
        "summary": "Found an application page.",
        "outputs": {"page_title": "Apply Now", "field_list": ["name", "email"]},
        "evidence": [
            {"type": "browser_observation", "label": "Page title", "value": "Apply Now"},
            {"type": "dom_excerpt", "label": "Fields", "value": "Name Email"},
        ],
        "action_events": [
            {"action_id": "act_1", "action_type": "browser.observe", "status": "success"}
        ],
    }

    report = verifier.verify(step, executor_result)

    assert report["status"] == "passed"
    assert report["score"] >= 0.8
    assert report["memory_patch"]["completed_step"]["step_id"] == "inspect_page"
    assert report["memory_patch"]["completed_step"]["summary"] == "Found an application page."


def test_verifier_rejects_browser_page_read_when_title_evidence_conflicts():
    from app.long_tail_agent import StepVerifier

    verifier = StepVerifier()
    step = {
        "step_id": "inspect_page",
        "step_type": "browser_page_read",
        "objective": "Identify page title and visible form fields.",
        "expected_outputs": ["page_title", "field_list"],
        "verification_criteria": [
            "The page title is reported from observed browser evidence.",
            "The visible form fields are listed.",
        ],
    }
    executor_result = {
        "status": "passed",
        "summary": "Found an application page.",
        "outputs": {"page_title": "Apply Now", "field_list": ["name", "email"]},
        "evidence": [
            {"type": "browser_observation", "label": "Page title", "value": "Pricing"},
            {"type": "dom_excerpt", "label": "Fields", "value": "Name Email"},
        ],
        "action_events": [{"action_id": "act_1", "action_type": "browser.observe", "status": "success"}],
    }

    report = verifier.verify(step, executor_result)

    assert report["status"] == "retry"
    assert "page_title evidence mismatch" in report["violations"]
    assert "browser page evidence conflicts" in report["reason"]


def test_verifier_blocks_draft_creation_if_executor_sent_message():
    from app.long_tail_agent import StepVerifier

    verifier = StepVerifier()
    step = {
        "step_id": "draft_email",
        "step_type": "draft_creation",
        "objective": "Prepare a draft email but do not send it.",
        "expected_outputs": ["draft_subject", "draft_body"],
        "forbidden_actions": ["email.send"],
        "verification_criteria": [
            "Draft content is available.",
            "No external send action happened.",
        ],
    }
    executor_result = {
        "status": "passed",
        "summary": "Drafted and sent the email.",
        "outputs": {"draft_subject": "Quote", "draft_body": "Hello Alice"},
        "evidence": [{"type": "draft_payload_hash", "value": "sha256:draft"}],
        "action_events": [
            {"action_id": "act_send", "action_type": "email.send", "status": "success"}
        ],
    }

    report = verifier.verify(step, executor_result)

    assert report["status"] == "blocked"
    assert "forbidden action executed: email.send" in report["violations"]
    assert "forbidden external action" in report["reason"]


def test_verifier_accepts_external_effect_confirmation_event_evidence():
    from app.long_tail_agent import StepVerifier

    verifier = StepVerifier()
    step = {
        "step_id": "confirm_send",
        "step_type": "external_effect_confirmation",
        "objective": "Confirm an external email send request before execution.",
        "expected_outputs": ["effect_id", "confirmation_status"],
        "verification_criteria": [
            "A confirmation event exists for the exact effect.",
            "The effect has not been executed yet.",
        ],
    }
    executor_result = {
        "status": "passed",
        "summary": "User confirmed the exact email send.",
        "outputs": {"effect_id": "effect_123", "confirmation_status": "confirmed"},
        "evidence": [
            {
                "type": "external_effect_event",
                "event_type": "external_effect.confirmed",
                "effect_id": "effect_123",
                "status": "confirmed",
                "confirmation_event_id": "evt_confirm",
            }
        ],
        "action_events": [],
    }

    report = verifier.verify(step, executor_result)

    assert report["status"] == "passed"
    assert report["score"] >= 0.8
    assert report["memory_patch"]["completed_step"]["step_id"] == "confirm_send"


def test_long_tail_agent_schema_sql_contains_v2_tables_and_constraints():
    from app.long_tail_agent import long_tail_agent_schema_sql

    combined = "\n".join(" ".join(sql.split()) for sql in long_tail_agent_schema_sql())

    assert "CREATE TABLE IF NOT EXISTS long_tail_task_runs" in combined
    assert "CREATE TABLE IF NOT EXISTS long_tail_task_events" in combined
    assert "CREATE TABLE IF NOT EXISTS long_tail_action_requests" in combined
    assert "CREATE TABLE IF NOT EXISTS long_tail_external_effects" in combined
    assert "long_tail_task_events_sequence_idx" in combined
    assert "long_tail_task_events_idempotency_idx" in combined


def test_main_runtime_imports_and_bootstraps_long_tail_schema():
    main_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    source = main_path.read_text()

    assert "long_tail_agent_schema_sql" in source
    assert "def ensure_long_tail_agent_schema" in source
    assert "ensure_long_tail_agent_schema()" in source
    assert "ENABLE_LONG_TAIL_RECOVERY_RUNNER" in source
    assert "long_tail_recovery_runner_loop()" in source


def test_main_builds_postgres_long_tail_store_for_non_test_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.delenv("LONG_TAIL_EVENT_STORE", raising=False)

    from app import main
    from app.long_tail_agent import LongTailEventStore, PostgresLongTailEventStore

    monkeypatch.setattr(main, "DATABASE_URL", "postgresql://user:pass@localhost:5432/nomi")
    postgres_store = main.build_long_tail_event_store()
    monkeypatch.setattr(main, "DATABASE_URL", "postgresql://test")
    memory_store = main.build_long_tail_event_store()

    assert isinstance(postgres_store, PostgresLongTailEventStore)
    assert postgres_store.materialize_events is True
    assert isinstance(memory_store, LongTailEventStore)
    assert not isinstance(memory_store, PostgresLongTailEventStore)


def test_graph_runner_creates_validated_task_and_builds_first_step_packet():
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner

    store = LongTailEventStore()
    runner = LongTailGraphRunner(event_store=store)
    plan = {
        "task_goal": "Prepare a form draft without submitting.",
        "success_criteria": ["Page is inspected.", "No submit action occurs."],
        "steps": [
            {
                "step_id": "inspect_page",
                "objective": "Identify the page and visible form fields.",
                "expected_outputs": ["page_title", "field_list"],
                "allowed_actions": ["browser.observe", "browser.screenshot"],
                "forbidden_actions": ["browser.submit", "email.send"],
                "verification_criteria": ["Page title is reported.", "Fields are listed."],
                "max_attempts": 2,
            }
        ],
    }

    task = runner.create_task(
        original_goal="帮我把这个报名网页填成草稿，但不要提交",
        route_decision={
            "route_type": "long_tail_agent",
            "capability_id": "long_tail.browser_or_tool_task",
            "risk_permission": "external_draft",
        },
        plan=plan,
    )
    step_packet = runner.run_next(task["task_id"])
    event_types = [event["event_type"] for event in store.task_events(task["task_id"])]

    assert task["status"] == "running"
    assert task["current_node"] == "select_step"
    assert event_types == [
        "task.created",
        "route.decided",
        "plan.proposed",
        "plan.validated",
        "memory.initialized",
        "checkpoint.saved",
        "step.selected",
        "step_packet.built",
    ]
    assert step_packet["task_id"] == task["task_id"]
    assert step_packet["step_id"] == "inspect_page"
    assert step_packet["step_objective"] == "Identify the page and visible form fields."
    assert step_packet["allowed_actions"] == ["browser.observe", "browser.screenshot"]
    assert "browser.submit" in step_packet["forbidden_actions"]
    assert runner.get_task_state(task["task_id"])["current_node"] == "awaiting_executor"


def test_graph_runner_blocks_invalid_plan_before_tool_execution():
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner

    store = LongTailEventStore()
    runner = LongTailGraphRunner(event_store=store)
    invalid_plan = {
        "task_goal": "Submit the form.",
        "success_criteria": ["Submitted"],
        "steps": [
            {
                "step_id": "submit_form",
                "objective": "Submit the form.",
                "expected_outputs": ["submitted"],
                "allowed_actions": ["browser.submit"],
                "forbidden_actions": [],
                "verification_criteria": [],
            }
        ],
    }

    task = runner.create_task(
        original_goal="帮我提交这个报名表",
        route_decision={
            "route_type": "long_tail_agent",
            "capability_id": "long_tail.browser_or_tool_task",
            "risk_permission": "external_write",
        },
        plan=invalid_plan,
    )

    assert task["status"] == "blocked"
    assert task["current_node"] == "blocked"
    assert "missing verification criteria" in task["validation_report"]["issues"]
    assert "external effect action is not converted to confirmation" in task["validation_report"]["issues"]
    assert [event["event_type"] for event in store.task_events(task["task_id"])] == [
        "task.created",
        "route.decided",
        "plan.proposed",
        "plan.validated",
    ]


def test_external_effect_requires_confirmation_before_execution():
    from app.long_tail_agent import ExternalEffectController, LongTailEventStore

    store = LongTailEventStore()
    controller = ExternalEffectController(event_store=store)
    effect = controller.propose(
        task_id="lta_1",
        step_id="send_email",
        action_request_id="act_send",
        effect_type="email.send",
        proposal={"recipient": "alice@example.test", "subject": "Quote", "body_hash": "sha256:abc"},
    )
    blocked = controller.execute(
        effect["effect_id"],
        execution_payload={"provider": "composio", "message_id": "msg_1"},
    )

    assert effect["status"] == "waiting_for_confirmation"
    assert blocked["status"] == "waiting_for_confirmation"
    assert blocked["may_execute"] is False
    assert [event["event_type"] for event in store.task_events("lta_1")] == ["external_effect.proposed"]

    confirmed = controller.confirm(
        effect["effect_id"],
        confirmation_payload={"confirmed_by": "user", "exact_recipient": "alice@example.test"},
    )
    executed = controller.execute(
        effect["effect_id"],
        execution_payload={"provider": "composio", "message_id": "msg_1"},
    )

    assert confirmed["status"] == "confirmed"
    assert executed["status"] == "executed"
    assert executed["may_execute"] is True
    assert [event["event_type"] for event in store.task_events("lta_1")] == [
        "external_effect.proposed",
        "external_effect.confirmed",
        "external_effect.executed",
    ]


def test_external_effect_controller_recovers_effect_from_event_log_before_confirmation():
    from app.long_tail_agent import ExternalEffectController, LongTailEventStore

    store = LongTailEventStore()
    first_controller = ExternalEffectController(event_store=store)
    effect = first_controller.propose(
        task_id="lta_recover_effect",
        step_id="send_email",
        action_request_id="act_send",
        effect_type="email.send",
        proposal={"recipient": "alice@example.test", "subject": "Quote"},
    )

    restarted_controller = ExternalEffectController(event_store=store)
    blocked = restarted_controller.execute(
        effect["effect_id"],
        task_id="lta_recover_effect",
        execution_payload={"message_id": "before_confirm"},
    )
    confirmed = restarted_controller.confirm(
        effect["effect_id"],
        task_id="lta_recover_effect",
        confirmation_payload={"confirmed_by": "user", "scope": "send_email"},
    )
    executed = restarted_controller.execute(
        effect["effect_id"],
        task_id="lta_recover_effect",
        execution_payload={"message_id": "after_confirm"},
    )

    assert blocked["may_execute"] is False
    assert blocked["status"] == "waiting_for_confirmation"
    assert confirmed["status"] == "confirmed"
    assert executed["status"] == "executed"
    assert executed["execution_payload"]["message_id"] == "after_confirm"
    assert [event["event_type"] for event in store.task_events("lta_recover_effect")] == [
        "external_effect.proposed",
        "external_effect.confirmed",
        "external_effect.executed",
    ]


def test_external_effect_rollback_only_describes_internal_state_and_compensation():
    from app.long_tail_agent import ExternalEffectController, LongTailEventStore

    controller = ExternalEffectController(event_store=LongTailEventStore())
    effect = controller.propose(
        task_id="lta_2",
        step_id="send_email",
        action_request_id="act_send",
        effect_type="email.send",
        proposal={"recipient": "alice@example.test", "subject": "Quote"},
    )
    controller.confirm(effect["effect_id"], confirmation_payload={"confirmed_by": "user"})
    controller.execute(effect["effect_id"], execution_payload={"message_id": "msg_1"})

    rollback = controller.describe_internal_rollback(effect["effect_id"])
    compensation = controller.propose_compensation(
        effect["effect_id"],
        proposal={"type": "draft_correction_email", "reason": "User requested undo after send."},
    )

    assert rollback["internal_state_can_rollback"] is True
    assert rollback["external_world_can_rollback"] is False
    assert "不能撤回第三方系统中已经发生的动作" in rollback["user_message"]
    assert rollback["action_card"] == {
        "title": "只能回滚 Nomi 内部状态",
        "message": rollback["user_message"],
        "actions": [
            {
                "id": "prepare_compensation",
                "label": "准备补偿操作",
                "requires_confirmation": True,
            }
        ],
    }
    assert compensation["status"] == "waiting_for_compensation_confirmation"
    assert compensation["compensation_proposal"]["type"] == "draft_correction_email"


def test_graph_runner_requests_and_resolves_pending_human_input_payload():
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner

    store = LongTailEventStore()
    runner = LongTailGraphRunner(event_store=store)
    task = runner.create_task(
        original_goal="帮我起草邮件，语气不明确时先问我",
        route_decision={"route_type": "long_tail_agent"},
        plan={
            "task_goal": "Draft email.",
            "success_criteria": ["Tone is known."],
            "steps": [
                {
                    "step_id": "draft_email",
                    "step_type": "draft_creation",
                    "objective": "Draft an email.",
                    "expected_outputs": ["draft_subject"],
                    "allowed_actions": ["email.draft"],
                    "forbidden_actions": ["email.send"],
                    "verification_criteria": ["Draft subject is present."],
                }
            ],
        },
    )

    requested = runner.request_human_input(
        task["task_id"],
        step_id="draft_email",
        input_type="clarification",
        question="这封邮件要正式一点还是轻松一点？",
        options=[
            {"id": "formal", "label": "正式"},
            {"id": "casual", "label": "轻松"},
        ],
    )
    waiting_state = runner.get_task_state(task["task_id"])
    received = runner.record_human_input(
        task["task_id"],
        step_id="draft_email",
        input_type="clarification",
        response={"choice": "formal"},
    )
    resolved_state = runner.get_task_state(task["task_id"])

    assert requested["event_type"] == "human_input.requested"
    assert waiting_state["current_node"] == "waiting_for_human_input"
    assert waiting_state["pending_human_input"] == {
        "step_id": "draft_email",
        "input_type": "clarification",
        "question": "这封邮件要正式一点还是轻松一点？",
        "options": [
            {"id": "formal", "label": "正式"},
            {"id": "casual", "label": "轻松"},
        ],
        "status": "waiting",
    }
    assert received["event_type"] == "human_input.received"
    assert resolved_state["current_node"] == "select_step"
    assert resolved_state.get("pending_human_input") is None


def test_graph_runner_recovers_pending_human_input_from_event_log():
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner

    store = LongTailEventStore()
    original_runner = LongTailGraphRunner(event_store=store)
    task = original_runner.create_task(
        original_goal="帮我准备回复，需要我确认语气",
        route_decision={"route_type": "long_tail_agent"},
        plan={
            "task_goal": "Prepare reply.",
            "success_criteria": ["Tone is clarified."],
            "steps": [
                {
                    "step_id": "draft_reply",
                    "step_type": "draft_creation",
                    "objective": "Draft a reply.",
                    "expected_outputs": ["draft_subject"],
                    "allowed_actions": ["email.draft"],
                    "forbidden_actions": ["email.send"],
                    "verification_criteria": ["Draft subject is present."],
                }
            ],
        },
    )
    original_runner.request_human_input(
        task["task_id"],
        step_id="draft_reply",
        input_type="clarification",
        question="使用什么语气？",
        options=[{"id": "short", "label": "简短"}],
    )

    restarted_runner = LongTailGraphRunner(event_store=store)
    recovered = restarted_runner.recover_task(task["task_id"])

    assert recovered["current_node"] == "waiting_for_human_input"
    assert recovered["pending_human_input"]["question"] == "使用什么语气？"
    assert recovered["pending_human_input"]["options"] == [{"id": "short", "label": "简短"}]


def test_graph_runner_fallback_contains_action_card_for_forbidden_external_action():
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner

    store = LongTailEventStore()
    runner = LongTailGraphRunner(event_store=store)
    task = runner.create_task(
        original_goal="帮我起草邮件但不要发送",
        route_decision={"route_type": "long_tail_agent"},
        plan={
            "task_goal": "Prepare draft only.",
            "success_criteria": ["Draft is prepared.", "No send action occurs."],
            "steps": [
                {
                    "step_id": "draft_email",
                    "step_type": "draft_creation",
                    "objective": "Prepare email draft.",
                    "expected_outputs": ["draft_subject", "draft_body"],
                    "allowed_actions": ["email.draft"],
                    "forbidden_actions": ["email.send"],
                    "verification_criteria": ["Draft subject/body are present.", "No send action occurs."],
                }
            ],
        },
    )
    runner.run_next(task["task_id"])

    result = runner.complete_current_step(
        task["task_id"],
        executor_result={
            "status": "passed",
            "summary": "Drafted and sent the email.",
            "outputs": {"draft_subject": "Quote", "draft_body": "Hello Alice"},
            "evidence": [{"type": "draft_payload_hash", "value": "sha256:draft"}],
            "action_events": [{"action_type": "email.send", "status": "success"}],
        },
    )

    assert result["status"] == "fallback"
    assert result["fallback_decision"]["action"] == "stop"
    assert result["fallback_decision"]["action_card"]["title"] == "发现禁止的外部动作"
    assert "不能假装已经撤回第三方动作" in result["fallback_decision"]["action_card"]["message"]
    assert result["fallback_decision"]["action_card"]["actions"][0]["id"] == "review_external_effects"


def test_graph_runner_final_delivery_includes_external_effect_review_card():
    from app.long_tail_agent import ExternalEffectController, LongTailEventStore, LongTailGraphRunner

    store = LongTailEventStore()
    runner = LongTailGraphRunner(event_store=store)
    controller = ExternalEffectController(event_store=store)
    task = runner.create_task(
        original_goal="帮我读取页面并发送前记录外部效果",
        route_decision={"route_type": "long_tail_agent"},
        plan={
            "task_goal": "Inspect page.",
            "success_criteria": ["Page title is known."],
            "steps": [
                {
                    "step_id": "inspect_page",
                    "step_type": "browser_page_read",
                    "objective": "Identify page title.",
                    "expected_outputs": ["page_title"],
                    "allowed_actions": ["browser.observe"],
                    "forbidden_actions": ["browser.submit"],
                    "verification_criteria": ["Page title is reported."],
                }
            ],
        },
    )
    runner.run_next(task["task_id"])
    runner.complete_current_step(
        task["task_id"],
        executor_result={
            "status": "passed",
            "summary": "Found page title.",
            "outputs": {"page_title": "Apply Now"},
            "evidence": [{"type": "browser_observation", "label": "Page title", "value": "Apply Now"}],
            "action_events": [{"action_type": "browser.observe", "status": "success"}],
        },
    )
    effect = controller.propose(
        task_id=task["task_id"],
        step_id="send_email",
        action_request_id="act_send",
        effect_type="email.send",
        proposal={"recipient": "alice@example.test", "subject": "Quote"},
    )
    controller.confirm(effect["effect_id"], confirmation_payload={"confirmed_by": "user"})
    controller.execute(effect["effect_id"], execution_payload={"provider": "composio", "message_id": "msg_1"})

    final = runner.evaluate_final(task["task_id"])

    assert final["status"] == "passed"
    assert final["delivery"]["actions"] == [
        {
            "id": "review_external_effect_rollback",
            "label": "查看回滚与补偿",
            "effect_id": effect["effect_id"],
            "requires_confirmation": False,
        }
    ]


def test_executor_adapter_registry_records_action_request_before_policy_decision():
    from app.long_tail_agent import ExecutorAdapterRegistry, LongTailEventStore, PolicyGate

    store = LongTailEventStore()
    registry = ExecutorAdapterRegistry(event_store=store, policy_gate=PolicyGate())

    allowed = registry.propose_action(
        task_id="lta_3",
        step_id="fill_name",
        adapter="browser",
        action_type="browser.fill_field",
        target={"kind": "dom_selector", "value": "input[name='name']"},
        input_summary={"redacted_value": "A***"},
        risk_level="external_draft",
        expected_effect="Fill a visible field.",
        allowed_actions={"browser.fill_field"},
    )
    blocked = registry.propose_action(
        task_id="lta_3",
        step_id="submit_form",
        adapter="browser",
        action_type="browser.submit",
        target={"kind": "button", "visible_label": "Submit"},
        input_summary={},
        risk_level="external_write",
        expected_effect="Submit the form.",
        allowed_actions={"browser.fill_field", "browser.submit"},
    )
    events = store.task_events("lta_3")

    assert allowed["policy_report"]["status"] == "allowed"
    assert allowed["policy_report"]["may_execute"] is True
    assert allowed["action_request"]["action_type"] == "browser.fill_field"
    assert blocked["policy_report"]["status"] == "blocked"
    assert blocked["policy_report"]["may_execute"] is False
    assert [event["event_type"] for event in events] == [
        "executor.action_requested",
        "policy.checked",
        "executor.action_requested",
        "policy.checked",
    ]
    assert events[0]["payload"]["action_request"]["action_type"] == "browser.fill_field"
    assert events[3]["payload"]["policy_report"]["status"] == "blocked"


def test_executor_adapter_registry_persists_provider_and_executor_trace_ids():
    from app.long_tail_agent import ExecutorAdapterRegistry, LongTailEventStore, PolicyGate

    store = LongTailEventStore()
    registry = ExecutorAdapterRegistry(event_store=store, policy_gate=PolicyGate())

    result = registry.propose_action(
        task_id="lta_trace",
        step_id="read_email",
        adapter="composio",
        action_type="gmail.fetch",
        target={"kind": "mailbox", "value": "inbox"},
        input_summary={"query": "from:alice"},
        risk_level="read_only",
        expected_effect="Read matching Gmail messages.",
        allowed_actions={"gmail.fetch"},
        executor_trace={
            "provider": "composio",
            "provider_trace_id": "cmp_run_123",
            "executor_trace_id": "exec_read_email_1",
            "toolkit": "gmail",
        },
    )
    events = store.task_events("lta_trace")

    assert result["executor_trace"]["provider_trace_id"] == "cmp_run_123"
    assert result["policy_report"]["status"] == "allowed"
    assert events[0]["payload"]["executor_trace"]["executor_trace_id"] == "exec_read_email_1"
    assert events[1]["payload"]["executor_trace"]["toolkit"] == "gmail"


def test_executor_adapter_registry_dry_run_records_trace_without_live_execution():
    from app.long_tail_agent import ExecutorAdapterRegistry, LongTailEventStore, PolicyGate

    store = LongTailEventStore()
    registry = ExecutorAdapterRegistry(event_store=store, policy_gate=PolicyGate())

    result = registry.execute_dry_run(
        task_id="lta_dry_run",
        step_id="inspect_page",
        adapter="openclaw",
        action_type="browser.observe",
        target={"kind": "page", "value": "current"},
        input_summary={},
        risk_level="read_only",
        expected_effect="Read page without changing external state.",
        allowed_actions={"browser.observe"},
        executor_trace={
            "provider_trace_id": "openclaw_dry_1",
            "executor_trace_id": "browser_observe_dry_1",
            "adapter_mode": "dry_run",
        },
    )
    events = store.task_events("lta_dry_run")

    assert result["mode"] == "dry_run"
    assert result["status"] == "skipped_live_execution"
    assert result["policy_report"]["status"] == "allowed"
    assert result["executor_trace"]["provider_trace_id"] == "openclaw_dry_1"
    assert result["dry_run_result"]["external_side_effect"] is False
    assert [event["event_type"] for event in events] == [
        "executor.action_requested",
        "policy.checked",
        "executor.dry_run_completed",
    ]
    assert events[-1]["payload"]["executor_trace"]["executor_trace_id"] == "browser_observe_dry_1"


def test_executor_adapter_registry_live_execution_records_trace_and_blocks_policy():
    from app.long_tail_agent import ExecutorAdapterRegistry, LongTailEventStore, PolicyGate

    store = LongTailEventStore()
    registry = ExecutorAdapterRegistry(event_store=store, policy_gate=PolicyGate())
    calls = []

    def fake_composio_executor(action_request):
        calls.append(action_request)
        return {
            "status": "completed_read_only",
            "provider_trace_id": "cmp_read_1",
            "executor_trace_id": "gmail_fetch_1",
            "external_side_effect": False,
            "summary": "Fetched 2 Gmail messages.",
        }

    allowed = registry.execute_live(
        task_id="lta_composio_live",
        step_id="read_gmail",
        adapter="composio",
        action_type="gmail.fetch",
        target={"kind": "mailbox", "value": "inbox"},
        input_summary={"query": "from:alice"},
        risk_level="read_only",
        expected_effect="Read matching Gmail messages.",
        allowed_actions={"gmail.fetch"},
        executor=fake_composio_executor,
        executor_trace={"provider": "composio", "toolkit": "gmail"},
    )
    blocked = registry.execute_live(
        task_id="lta_composio_live",
        step_id="send_gmail",
        adapter="composio",
        action_type="email.send",
        target={"kind": "email", "value": "alice@example.test"},
        input_summary={"subject": "Quote"},
        risk_level="external_message",
        expected_effect="Send an email.",
        allowed_actions={"email.send"},
        executor=fake_composio_executor,
        executor_trace={"provider": "composio", "toolkit": "gmail"},
    )
    events = store.task_events("lta_composio_live")

    assert allowed["status"] == "completed_read_only"
    assert allowed["live_result"]["provider_trace_id"] == "cmp_read_1"
    assert blocked["status"] == "blocked_by_policy"
    assert len(calls) == 1
    assert calls[0]["action_type"] == "gmail.fetch"
    assert [event["event_type"] for event in events] == [
        "executor.action_requested",
        "policy.checked",
        "executor.live_completed",
        "executor.action_requested",
        "policy.checked",
    ]
    assert events[2]["payload"]["executor_trace"]["provider_trace_id"] == "cmp_read_1"
    assert events[2]["payload"]["live_result"]["external_side_effect"] is False


def test_agent_task_api_requires_password_and_exposes_state_events_and_run_next(monkeypatch):
    import os
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner

    store = LongTailEventStore()
    main._LONG_TAIL_EVENT_STORE = store
    main._LONG_TAIL_RUNNER = LongTailGraphRunner(event_store=store)

    client = TestClient(main.app)
    create_body = {
        "original_goal": "帮我检查报名页面",
        "route_decision": {"route_type": "long_tail_agent"},
        "plan": {
            "task_goal": "Inspect the page.",
            "success_criteria": ["Page title is known."],
            "steps": [
                {
                    "step_id": "inspect_page",
                    "step_type": "browser_page_read",
                    "objective": "Identify page title.",
                    "expected_outputs": ["page_title"],
                    "allowed_actions": ["browser.observe"],
                    "forbidden_actions": ["browser.submit"],
                    "verification_criteria": ["Page title is reported."],
                }
            ],
        },
    }
    unauthorized = client.post("/api/agent-tasks", json=create_body)

    assert unauthorized.status_code == 401

    response = client.post(
        "/api/agent-tasks",
        headers={"x-par-password": "secret"},
        json=create_body,
    )
    payload = response.json()
    task_id = payload["task_id"]

    assert response.status_code == 200
    assert payload["status"] == "running"

    packet_response = client.post(
        f"/api/agent-tasks/{task_id}/run-next",
        headers={"x-par-password": "secret"},
    )
    state_response = client.get(
        f"/api/agent-tasks/{task_id}",
        headers={"x-par-password": "secret"},
    )
    events_response = client.get(
        f"/api/agent-tasks/{task_id}/events",
        headers={"x-par-password": "secret"},
    )

    assert packet_response.status_code == 200
    assert packet_response.json()["step_id"] == "inspect_page"
    assert state_response.json()["state"]["current_node"] == "awaiting_executor"
    assert [event["event_type"] for event in events_response.json()["events"]] == [
        "task.created",
        "route.decided",
        "plan.proposed",
        "plan.validated",
        "memory.initialized",
        "checkpoint.saved",
        "step.selected",
        "step_packet.built",
    ]


def test_agent_task_route_endpoint_normalizes_openclaw_to_long_tail_agent(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main

    client = TestClient(main.app)
    response = client.post(
        "/api/agent-tasks/route",
        headers={"x-par-password": "secret"},
        json={"request": "帮我打开网页填写报名表但不要提交", "context": {}},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["route_type"] == "long_tail_agent"
    assert payload["legacy_route_type"] == "openclaw_tool"
    assert payload["capability_id"] == "automation.browser.operate"


def test_agent_task_api_complete_step_and_cancel_write_events(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner, StepVerifier

    store = LongTailEventStore()
    main._LONG_TAIL_EVENT_STORE = store
    main._LONG_TAIL_RUNNER = LongTailGraphRunner(event_store=store, verifier=StepVerifier())

    client = TestClient(main.app)
    created = client.post(
        "/api/agent-tasks",
        headers={"x-par-password": "secret"},
        json={
            "original_goal": "帮我检查报名页面",
            "route_decision": {"route_type": "long_tail_agent"},
            "plan": {
                "task_goal": "Inspect the page.",
                "success_criteria": ["Page title is known."],
                "steps": [
                    {
                        "step_id": "inspect_page",
                        "step_type": "browser_page_read",
                        "objective": "Identify page title.",
                        "expected_outputs": ["page_title"],
                        "allowed_actions": ["browser.observe"],
                        "forbidden_actions": ["browser.submit"],
                        "verification_criteria": ["Page title is reported."],
                    }
                ],
            },
        },
    ).json()
    task_id = created["task_id"]
    client.post(f"/api/agent-tasks/{task_id}/run-next", headers={"x-par-password": "secret"})

    completed = client.post(
        f"/api/agent-tasks/{task_id}/complete-step",
        headers={"x-par-password": "secret"},
        json={
            "executor_result": {
                "status": "passed",
                "summary": "Found page title.",
                "outputs": {"page_title": "Apply Now"},
                "evidence": [{"type": "browser_observation", "label": "Page title", "value": "Apply Now"}],
                "action_events": [{"action_id": "act_1", "action_type": "browser.observe"}],
            }
        },
    )
    final = client.post(
        f"/api/agent-tasks/{task_id}/finalize",
        headers={"x-par-password": "secret"},
    )
    cancelled = client.post(
        f"/api/agent-tasks/{task_id}/cancel",
        headers={"x-par-password": "secret"},
        json={"reason": "user cancelled after review"},
    )

    assert completed.json()["verifier_report"]["status"] == "passed"
    assert final.json()["status"] == "passed"
    assert final.json()["delivery"]["message"] == "已完成：Found page title."
    assert cancelled.json()["state"]["status"] == "cancelled"
    assert store.task_events(task_id)[-1]["event_type"] == "task.cancelled"


def test_agent_task_api_resume_recovers_task_from_event_log_when_runner_state_is_empty(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner, StepVerifier

    store = LongTailEventStore()
    first_runner = LongTailGraphRunner(event_store=store, verifier=StepVerifier())
    main._LONG_TAIL_EVENT_STORE = store
    main._LONG_TAIL_RUNNER = first_runner

    client = TestClient(main.app)
    created = client.post(
        "/api/agent-tasks",
        headers={"x-par-password": "secret"},
        json={
            "original_goal": "帮我检查报名页面",
            "route_decision": {"route_type": "long_tail_agent"},
            "plan": {
                "task_goal": "Inspect the page.",
                "success_criteria": ["Page title is known."],
                "steps": [
                    {
                        "step_id": "inspect_page",
                        "step_type": "browser_page_read",
                        "objective": "Identify page title.",
                        "expected_outputs": ["page_title"],
                        "allowed_actions": ["browser.observe"],
                        "forbidden_actions": ["browser.submit"],
                        "verification_criteria": ["Page title is reported."],
                    }
                ],
            },
        },
    ).json()
    task_id = created["task_id"]
    client.post(f"/api/agent-tasks/{task_id}/run-next", headers={"x-par-password": "secret"})

    main._LONG_TAIL_RUNNER = LongTailGraphRunner(event_store=store, verifier=StepVerifier())
    resumed = client.post(f"/api/agent-tasks/{task_id}/resume", headers={"x-par-password": "secret"})
    state = client.get(f"/api/agent-tasks/{task_id}", headers={"x-par-password": "secret"}).json()["state"]

    assert resumed.status_code == 200
    assert resumed.json()["state"]["current_node"] == "awaiting_executor"
    assert resumed.json()["state"]["current_step_id"] == "inspect_page"
    assert "waiting for executor result" in resumed.json()["message"]
    assert state["current_node"] == "awaiting_executor"


def test_agent_task_api_human_input_and_confirm_events_are_visible(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner

    store = LongTailEventStore()
    main._LONG_TAIL_EVENT_STORE = store
    main._LONG_TAIL_RUNNER = LongTailGraphRunner(event_store=store)

    client = TestClient(main.app)
    created = client.post(
        "/api/agent-tasks",
        headers={"x-par-password": "secret"},
        json={
            "original_goal": "帮我起草邮件，发送前让我确认",
            "route_decision": {"route_type": "long_tail_agent"},
            "plan": {
                "task_goal": "Draft only.",
                "success_criteria": ["Draft is prepared."],
                "steps": [
                    {
                        "step_id": "draft_email",
                        "step_type": "draft_creation",
                        "objective": "Prepare email draft.",
                        "expected_outputs": ["draft_subject"],
                        "allowed_actions": ["email.draft"],
                        "forbidden_actions": ["email.send"],
                        "verification_criteria": ["Draft subject is present."],
                    }
                ],
            },
        },
    ).json()
    task_id = created["task_id"]

    human = client.post(
        f"/api/agent-tasks/{task_id}/human-input",
        headers={"x-par-password": "secret"},
        json={
            "step_id": "draft_email",
            "input_type": "clarification",
            "response": {"choice": "tone_formal", "note": "正式一点"},
        },
    )
    confirm = client.post(
        f"/api/agent-tasks/{task_id}/confirm",
        headers={"x-par-password": "secret"},
        json={
            "step_id": "draft_email",
            "confirmation": {"confirmed_by": "user", "scope": "draft_only"},
        },
    )
    events = client.get(
        f"/api/agent-tasks/{task_id}/events",
        headers={"x-par-password": "secret"},
    ).json()["events"]

    assert human.status_code == 200
    assert human.json()["event_type"] == "human_input.received"
    assert human.json()["payload"]["response"]["choice"] == "tone_formal"
    assert confirm.status_code == 200
    assert confirm.json()["event_type"] == "external_effect.confirmed"
    assert confirm.json()["payload"]["confirmation"]["scope"] == "draft_only"
    assert [event["event_type"] for event in events][-2:] == [
        "human_input.received",
        "external_effect.confirmed",
    ]


def test_agent_task_api_exposes_pending_human_input_until_answered(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner

    store = LongTailEventStore()
    runner = LongTailGraphRunner(event_store=store)
    main._LONG_TAIL_EVENT_STORE = store
    main._LONG_TAIL_RUNNER = runner

    client = TestClient(main.app)
    created = client.post(
        "/api/agent-tasks",
        headers={"x-par-password": "secret"},
        json={
            "original_goal": "帮我起草一封需要确认语气的邮件",
            "route_decision": {"route_type": "long_tail_agent"},
            "plan": {
                "task_goal": "Draft with clarified tone.",
                "success_criteria": ["Tone is clarified."],
                "steps": [
                    {
                        "step_id": "draft_email",
                        "step_type": "draft_creation",
                        "objective": "Prepare email draft.",
                        "expected_outputs": ["draft_subject"],
                        "allowed_actions": ["email.draft"],
                        "forbidden_actions": ["email.send"],
                        "verification_criteria": ["Draft subject is present."],
                    }
                ],
            },
        },
    ).json()
    task_id = created["task_id"]
    runner.request_human_input(
        task_id,
        step_id="draft_email",
        input_type="clarification",
        question="这封邮件要正式还是轻松？",
        options=[{"id": "formal", "label": "正式"}],
    )

    waiting_state = client.get(
        f"/api/agent-tasks/{task_id}",
        headers={"x-par-password": "secret"},
    ).json()["state"]
    answered = client.post(
        f"/api/agent-tasks/{task_id}/human-input",
        headers={"x-par-password": "secret"},
        json={
            "step_id": "draft_email",
            "input_type": "clarification",
            "response": {"choice": "formal"},
        },
    )
    resolved_state = client.get(
        f"/api/agent-tasks/{task_id}",
        headers={"x-par-password": "secret"},
    ).json()["state"]

    assert waiting_state["current_node"] == "waiting_for_human_input"
    assert waiting_state["pending_human_input"]["question"] == "这封邮件要正式还是轻松？"
    assert waiting_state["pending_human_input"]["options"] == [{"id": "formal", "label": "正式"}]
    assert answered.status_code == 200
    assert resolved_state["current_node"] == "select_step"
    assert resolved_state.get("pending_human_input") is None


def test_agent_task_api_external_effects_use_controller_state_machine(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main
    from app.long_tail_agent import ExternalEffectController, LongTailEventStore, LongTailGraphRunner

    store = LongTailEventStore()
    main._LONG_TAIL_EVENT_STORE = store
    main._LONG_TAIL_RUNNER = LongTailGraphRunner(event_store=store)
    main._LONG_TAIL_EFFECT_CONTROLLER = ExternalEffectController(event_store=store)

    client = TestClient(main.app)
    created = client.post(
        "/api/agent-tasks",
        headers={"x-par-password": "secret"},
        json={
            "original_goal": "准备邮件草稿，发送前确认",
            "route_decision": {"route_type": "long_tail_agent"},
            "plan": {
                "task_goal": "Prepare draft.",
                "success_criteria": ["Draft is confirmed before send."],
                "steps": [
                    {
                        "step_id": "send_email",
                        "step_type": "external_effect_confirmation",
                        "objective": "Confirm email send.",
                        "expected_outputs": ["effect_id"],
                        "allowed_actions": ["email.draft"],
                        "forbidden_actions": ["email.send"],
                        "verification_criteria": ["External send is confirmed first."],
                    }
                ],
            },
        },
    ).json()
    task_id = created["task_id"]
    proposed = client.post(
        f"/api/agent-tasks/{task_id}/external-effects",
        headers={"x-par-password": "secret"},
        json={
            "step_id": "send_email",
            "action_request_id": "act_send_email",
            "effect_type": "email.send",
            "proposal": {"recipient": "alice@example.test", "subject": "报价"},
        },
    )
    effect_id = proposed.json()["effect_id"]
    main._LONG_TAIL_EFFECT_CONTROLLER = ExternalEffectController(event_store=store)

    blocked = client.post(
        f"/api/agent-tasks/{task_id}/external-effects/{effect_id}/execute",
        headers={"x-par-password": "secret"},
        json={"execution_payload": {"message_id": "before_confirm"}},
    )
    confirmed = client.post(
        f"/api/agent-tasks/{task_id}/external-effects/{effect_id}/confirm",
        headers={"x-par-password": "secret"},
        json={"confirmation": {"confirmed_by": "user", "scope": "send_email"}},
    )
    executed = client.post(
        f"/api/agent-tasks/{task_id}/external-effects/{effect_id}/execute",
        headers={"x-par-password": "secret"},
        json={"execution_payload": {"message_id": "after_confirm"}},
    )
    event_types = [
        event["event_type"]
        for event in client.get(
            f"/api/agent-tasks/{task_id}/events",
            headers={"x-par-password": "secret"},
        ).json()["events"]
    ]

    assert proposed.status_code == 200
    assert proposed.json()["status"] == "waiting_for_confirmation"
    assert blocked.status_code == 200
    assert blocked.json()["may_execute"] is False
    assert confirmed.json()["status"] == "confirmed"
    assert executed.json()["status"] == "executed"
    assert executed.json()["may_execute"] is True
    assert event_types[-3:] == [
        "external_effect.proposed",
        "external_effect.confirmed",
        "external_effect.executed",
    ]


def test_agent_task_api_external_effect_rollback_card_and_compensation(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main
    from app.long_tail_agent import ExternalEffectController, LongTailEventStore, LongTailGraphRunner

    store = LongTailEventStore()
    main._LONG_TAIL_EVENT_STORE = store
    main._LONG_TAIL_RUNNER = LongTailGraphRunner(event_store=store)
    main._LONG_TAIL_EFFECT_CONTROLLER = ExternalEffectController(event_store=store)

    client = TestClient(main.app)
    created = client.post(
        "/api/agent-tasks",
        headers={"x-par-password": "secret"},
        json={
            "original_goal": "准备邮件草稿，发送前确认",
            "route_decision": {"route_type": "long_tail_agent"},
            "plan": {
                "task_goal": "Prepare draft.",
                "success_criteria": ["Draft is confirmed before send."],
                "steps": [
                    {
                        "step_id": "send_email",
                        "step_type": "external_effect_confirmation",
                        "objective": "Confirm email send.",
                        "expected_outputs": ["effect_id"],
                        "allowed_actions": ["email.draft"],
                        "forbidden_actions": ["email.send"],
                        "verification_criteria": ["External send is confirmed first."],
                    }
                ],
            },
        },
    ).json()
    task_id = created["task_id"]
    effect = client.post(
        f"/api/agent-tasks/{task_id}/external-effects",
        headers={"x-par-password": "secret"},
        json={
            "step_id": "send_email",
            "action_request_id": "act_send_email",
            "effect_type": "email.send",
            "proposal": {"recipient": "alice@example.test", "subject": "报价"},
        },
    ).json()
    effect_id = effect["effect_id"]
    client.post(
        f"/api/agent-tasks/{task_id}/external-effects/{effect_id}/confirm",
        headers={"x-par-password": "secret"},
        json={"confirmation": {"confirmed_by": "user"}},
    )
    client.post(
        f"/api/agent-tasks/{task_id}/external-effects/{effect_id}/execute",
        headers={"x-par-password": "secret"},
        json={"execution_payload": {"message_id": "sent_1"}},
    )
    main._LONG_TAIL_EFFECT_CONTROLLER = ExternalEffectController(event_store=store)

    rollback = client.post(
        f"/api/agent-tasks/{task_id}/external-effects/{effect_id}/rollback",
        headers={"x-par-password": "secret"},
    )
    compensation = client.post(
        f"/api/agent-tasks/{task_id}/external-effects/{effect_id}/compensation",
        headers={"x-par-password": "secret"},
        json={"proposal": {"type": "draft_correction_email", "reason": "用户要求补偿"}},
    )

    assert rollback.status_code == 200
    assert rollback.json()["external_world_can_rollback"] is False
    assert rollback.json()["action_card"]["actions"][0]["id"] == "prepare_compensation"
    assert compensation.status_code == 200
    assert compensation.json()["status"] == "waiting_for_compensation_confirmation"
    assert compensation.json()["compensation_proposal"]["type"] == "draft_correction_email"


def test_graph_runner_verifies_executor_result_before_checkpointing_step():
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner, StepVerifier

    store = LongTailEventStore()
    runner = LongTailGraphRunner(event_store=store, verifier=StepVerifier())
    task = runner.create_task(
        original_goal="帮我检查报名页面",
        route_decision={"route_type": "long_tail_agent"},
        plan={
            "task_goal": "Inspect the page.",
            "success_criteria": ["Page title and fields are known."],
            "steps": [
                {
                    "step_id": "inspect_page",
                    "step_type": "browser_page_read",
                    "objective": "Identify page title and visible form fields.",
                    "expected_outputs": ["page_title", "field_list"],
                    "allowed_actions": ["browser.observe"],
                    "forbidden_actions": ["browser.submit"],
                    "verification_criteria": ["Page title is reported.", "Fields are listed."],
                }
            ],
        },
    )
    runner.run_next(task["task_id"])

    completion = runner.complete_current_step(
        task["task_id"],
        executor_result={
            "status": "passed",
            "summary": "Found application page fields.",
            "outputs": {"page_title": "Apply Now", "field_list": ["name", "email"]},
            "evidence": [
                {"type": "browser_observation", "label": "Page title", "value": "Apply Now"},
                {"type": "dom_excerpt", "label": "Fields", "value": "Name Email"},
            ],
            "action_events": [{"action_id": "act_1", "action_type": "browser.observe"}],
        },
    )
    state = runner.get_task_state(task["task_id"])
    event_types = [event["event_type"] for event in store.task_events(task["task_id"])]

    assert completion["verifier_report"]["status"] == "passed"
    assert state["current_node"] == "final_evaluation"
    assert state["completed_steps"] == [
        {"step_id": "inspect_page", "summary": "Found application page fields."}
    ]
    assert event_types[-4:] == [
        "step.result_returned",
        "step.verified",
        "memory.patch_applied",
        "checkpoint.saved",
    ]


def test_graph_runner_failed_verification_goes_to_fallback_without_checkpoint():
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner, StepVerifier

    store = LongTailEventStore()
    runner = LongTailGraphRunner(event_store=store, verifier=StepVerifier())
    task = runner.create_task(
        original_goal="帮我检查报名页面",
        route_decision={"route_type": "long_tail_agent"},
        plan={
            "task_goal": "Inspect the page.",
            "success_criteria": ["Page title and fields are known."],
            "steps": [
                {
                    "step_id": "inspect_page",
                    "step_type": "browser_page_read",
                    "objective": "Identify page title and visible form fields.",
                    "expected_outputs": ["page_title", "field_list"],
                    "allowed_actions": ["browser.observe"],
                    "forbidden_actions": ["browser.submit"],
                    "verification_criteria": ["Page title is reported.", "Fields are listed."],
                }
            ],
        },
    )
    runner.run_next(task["task_id"])

    completion = runner.complete_current_step(
        task["task_id"],
        executor_result={
            "status": "passed",
            "summary": "Trust me, I saw the page.",
            "outputs": {"page_title": "Apply Now", "field_list": ["name", "email"]},
            "evidence": [],
            "action_events": [],
        },
    )
    state = runner.get_task_state(task["task_id"])
    event_types = [event["event_type"] for event in store.task_events(task["task_id"])]

    assert completion["verifier_report"]["status"] == "retry"
    assert completion["fallback_decision"]["action"] == "retry"
    assert state["current_node"] == "select_step"
    assert state["completed_steps"] == []
    assert event_types[-3:] == ["step.result_returned", "step.verified", "fallback.decided"]


def test_graph_runner_final_evaluator_creates_grounded_delivery():
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner, StepVerifier

    store = LongTailEventStore()
    runner = LongTailGraphRunner(event_store=store, verifier=StepVerifier())
    task = runner.create_task(
        original_goal="帮我检查报名页面",
        route_decision={"route_type": "long_tail_agent"},
        plan={
            "task_goal": "Inspect the page.",
            "success_criteria": ["Page title and fields are known."],
            "steps": [
                {
                    "step_id": "inspect_page",
                    "step_type": "browser_page_read",
                    "objective": "Identify page title and visible form fields.",
                    "expected_outputs": ["page_title", "field_list"],
                    "allowed_actions": ["browser.observe"],
                    "forbidden_actions": ["browser.submit"],
                    "verification_criteria": ["Page title is reported.", "Fields are listed."],
                }
            ],
        },
    )
    runner.run_next(task["task_id"])
    runner.complete_current_step(
        task["task_id"],
        executor_result={
            "status": "passed",
            "summary": "Found application page fields.",
            "outputs": {"page_title": "Apply Now", "field_list": ["name", "email"]},
            "evidence": [
                {"type": "browser_observation", "label": "Page title", "value": "Apply Now"},
                {"type": "dom_excerpt", "label": "Fields", "value": "Name Email"},
            ],
            "action_events": [{"action_id": "act_1", "action_type": "browser.observe"}],
        },
    )

    final = runner.evaluate_final(task["task_id"])
    state = runner.get_task_state(task["task_id"])
    event_types = [event["event_type"] for event in store.task_events(task["task_id"])]

    assert final["status"] == "passed"
    assert final["delivery"]["message"] == "已完成：Found application page fields."
    assert final["delivery"]["actions"] == []
    assert state["status"] == "completed"
    assert state["current_node"] == "delivered"
    assert event_types[-3:] == ["final.evaluated", "delivery.created", "task.completed"]


def test_graph_runner_final_evaluator_returns_partial_when_steps_missing():
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner

    runner = LongTailGraphRunner(event_store=LongTailEventStore())
    task = runner.create_task(
        original_goal="帮我检查报名页面并列出字段",
        route_decision={"route_type": "long_tail_agent"},
        plan={
            "task_goal": "Inspect the page.",
            "success_criteria": ["Page is inspected.", "Fields are listed."],
            "steps": [
                {
                    "step_id": "inspect_page",
                    "step_type": "browser_page_read",
                    "objective": "Identify page title.",
                    "expected_outputs": ["page_title"],
                    "allowed_actions": ["browser.observe"],
                    "forbidden_actions": ["browser.submit"],
                    "verification_criteria": ["Page title is reported."],
                },
                {
                    "step_id": "list_fields",
                    "step_type": "browser_page_read",
                    "objective": "List visible form fields.",
                    "expected_outputs": ["field_list"],
                    "allowed_actions": ["browser.observe"],
                    "forbidden_actions": ["browser.submit"],
                    "verification_criteria": ["Fields are listed."],
                },
            ],
        },
    )

    final = runner.evaluate_final(task["task_id"])

    assert final["status"] == "partial"
    assert final["incomplete_steps"] == ["inspect_page", "list_fields"]
    assert "还没有完成可验证步骤" in final["delivery"]["message"]


def test_graph_runner_recovers_awaiting_executor_from_event_log_after_restart():
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner, StepVerifier

    store = LongTailEventStore()
    first_runner = LongTailGraphRunner(event_store=store, verifier=StepVerifier())
    task = first_runner.create_task(
        original_goal="帮我读取当前网页标题，不要提交任何内容",
        route_decision={"route_type": "long_tail_agent"},
        plan={
            "task_goal": "Inspect page title only.",
            "success_criteria": ["Page title is known.", "No submit action occurs."],
            "steps": [
                {
                    "step_id": "inspect_page",
                    "step_type": "browser_page_read",
                    "objective": "Identify page title.",
                    "expected_outputs": ["page_title"],
                    "allowed_actions": ["browser.observe"],
                    "forbidden_actions": ["browser.submit"],
                    "verification_criteria": ["Page title is reported."],
                }
            ],
        },
    )
    first_runner.run_next(task["task_id"])

    restarted_runner = LongTailGraphRunner(event_store=store, verifier=StepVerifier())
    recovered = restarted_runner.recover_task(task["task_id"])
    completion = restarted_runner.complete_current_step(
        task["task_id"],
        executor_result={
            "status": "passed",
            "summary": "Recovered runner verified page title.",
            "outputs": {"page_title": "Dashboard"},
            "evidence": [
                {"type": "browser_observation", "label": "Page title", "value": "Dashboard"}
            ],
            "action_events": [{"action_id": "act_1", "action_type": "browser.observe"}],
        },
    )

    assert recovered["status"] == "running"
    assert recovered["current_node"] == "awaiting_executor"
    assert recovered["current_step_id"] == "inspect_page"
    assert completion["status"] == "verified"
    assert restarted_runner.get_task_state(task["task_id"])["current_node"] == "final_evaluation"


def test_graph_runner_recovers_completed_steps_and_runs_next_step_after_restart():
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner, StepVerifier

    store = LongTailEventStore()
    first_runner = LongTailGraphRunner(event_store=store, verifier=StepVerifier())
    task = first_runner.create_task(
        original_goal="帮我检查网页并列出字段，不要提交",
        route_decision={"route_type": "long_tail_agent"},
        plan={
            "task_goal": "Inspect page and list fields.",
            "success_criteria": ["Page title is known.", "Fields are listed."],
            "steps": [
                {
                    "step_id": "inspect_page",
                    "step_type": "browser_page_read",
                    "objective": "Identify page title.",
                    "expected_outputs": ["page_title"],
                    "allowed_actions": ["browser.observe"],
                    "forbidden_actions": ["browser.submit"],
                    "verification_criteria": ["Page title is reported."],
                },
                {
                    "step_id": "list_fields",
                    "step_type": "browser_page_read",
                    "objective": "List visible form fields.",
                    "expected_outputs": ["field_list"],
                    "allowed_actions": ["browser.observe"],
                    "forbidden_actions": ["browser.submit"],
                    "verification_criteria": ["Fields are listed."],
                },
            ],
        },
    )
    first_runner.run_next(task["task_id"])
    first_runner.complete_current_step(
        task["task_id"],
        executor_result={
            "status": "passed",
            "summary": "Observed title.",
            "outputs": {"page_title": "Apply"},
            "evidence": [{"type": "browser_observation", "label": "Page title", "value": "Apply"}],
            "action_events": [{"action_id": "act_1", "action_type": "browser.observe"}],
        },
    )

    restarted_runner = LongTailGraphRunner(event_store=store, verifier=StepVerifier())
    recovered = restarted_runner.recover_task(task["task_id"])
    packet = restarted_runner.run_next(task["task_id"])

    assert recovered["current_node"] == "select_step"
    assert recovered["completed_steps"] == [{"step_id": "inspect_page", "summary": "Observed title."}]
    assert packet["step_id"] == "list_fields"
    assert packet["expected_outputs"] == ["field_list"]


def test_long_tail_lease_manager_blocks_active_lease_and_recovers_expired_lease():
    from datetime import datetime, timedelta, timezone

    from app.long_tail_agent import LongTailLeaseManager

    manager = LongTailLeaseManager()
    now = datetime(2026, 6, 3, 8, 0, tzinfo=timezone.utc)

    first = manager.claim_task("lta_lease", worker_id="worker-a", lease_seconds=10, now=now)
    blocked = manager.claim_task(
        "lta_lease",
        worker_id="worker-b",
        lease_seconds=10,
        now=now + timedelta(seconds=5),
    )
    recovered = manager.claim_task(
        "lta_lease",
        worker_id="worker-b",
        lease_seconds=10,
        now=now + timedelta(seconds=11),
    )
    released = manager.release_task("lta_lease", worker_id="worker-b")

    assert first["acquired"] is True
    assert first["lease_owner"] == "worker-a"
    assert blocked["acquired"] is False
    assert blocked["reason"] == "active_lease"
    assert blocked["lease_owner"] == "worker-a"
    assert recovered["acquired"] is True
    assert recovered["lease_owner"] == "worker-b"
    assert recovered["attempt"] == 2
    assert released["status"] == "released"


def test_postgres_long_tail_lease_manager_claims_releases_and_reports_active_lease():
    from datetime import datetime, timedelta, timezone

    from app.long_tail_agent import PostgresLongTailLeaseManager

    class FakeCursor:
        def __init__(self, row=None):
            self._row = row

        def fetchone(self):
            return self._row

    class FakeConnection:
        def __init__(self):
            self.now = datetime(2026, 6, 3, 8, 0, tzinfo=timezone.utc)
            self.expires = self.now + timedelta(seconds=30)
            self.update_rows = [
                ("lta_pg_lease", "worker-a", self.expires),
                None,
                ("lta_pg_lease", "", None),
            ]
            self.queries = []
            self.commits = 0

        def execute(self, sql, params=None):
            normalized_sql = " ".join(str(sql).split())
            self.queries.append((normalized_sql, params))
            if normalized_sql.startswith("UPDATE long_tail_task_runs") and "RETURNING id, lease_owner, lease_expires_at" in normalized_sql:
                return FakeCursor(row=self.update_rows.pop(0))
            if normalized_sql.startswith("SELECT id, lease_owner, lease_expires_at FROM long_tail_task_runs"):
                return FakeCursor(row=("lta_pg_lease", "worker-a", self.expires))
            raise AssertionError(f"Unexpected SQL: {normalized_sql}")

        def commit(self):
            self.commits += 1

    fake_conn = FakeConnection()
    manager = PostgresLongTailLeaseManager(connection_factory=lambda: fake_conn)

    first = manager.claim_task(
        "lta_pg_lease",
        worker_id="worker-a",
        lease_seconds=30,
        now=fake_conn.now,
    )
    blocked = manager.claim_task(
        "lta_pg_lease",
        worker_id="worker-b",
        lease_seconds=30,
        now=fake_conn.now + timedelta(seconds=1),
    )
    released = manager.release_task("lta_pg_lease", worker_id="worker-a")

    assert first["acquired"] is True
    assert first["lease_owner"] == "worker-a"
    assert blocked["acquired"] is False
    assert blocked["reason"] == "active_lease"
    assert blocked["lease_owner"] == "worker-a"
    assert released["released"] is True
    assert fake_conn.commits == 2


def test_postgres_recovery_scanner_lists_due_unleased_or_expired_tasks():
    from app.long_tail_agent import PostgresLongTailRecoveryScanner

    class FakeCursor:
        def fetchall(self):
            return [("lta_due_1",), ("lta_due_2",)]

    class FakeConnection:
        def __init__(self):
            self.last_query = ""
            self.last_params = None

        def execute(self, sql, params=None):
            self.last_query = " ".join(str(sql).split())
            self.last_params = params
            return FakeCursor()

    fake_conn = FakeConnection()
    scanner = PostgresLongTailRecoveryScanner(connection_factory=lambda: fake_conn)

    due = scanner.due_task_ids(limit=2)

    assert due == ["lta_due_1", "lta_due_2"]
    assert "status IN ('created', 'running')" in fake_conn.last_query
    assert "lease_expires_at IS NULL OR lease_expires_at <= now()" in fake_conn.last_query
    assert fake_conn.last_params == (2,)


def test_long_tail_recovery_runner_claims_recovers_and_releases_due_tasks(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("REDIS_URL", "redis://test")
    monkeypatch.setenv("APP_PASSWORD", "secret")

    from app import main
    from app.long_tail_agent import LongTailEventStore, LongTailGraphRunner, StepVerifier

    class FakeScanner:
        def due_task_ids(self, *, limit: int):
            self.limit = limit
            return ["lta_recover_1", "lta_recover_2"]

    class FakeLeaseManager:
        def __init__(self):
            self.claimed = []
            self.released = []

        def claim_task(self, task_id, *, worker_id, lease_seconds, now=None):
            self.claimed.append((task_id, worker_id, lease_seconds))
            if task_id == "lta_recover_2":
                return {"task_id": task_id, "acquired": False, "reason": "active_lease"}
            return {"task_id": task_id, "acquired": True, "lease_owner": worker_id}

        def release_task(self, task_id, *, worker_id):
            self.released.append((task_id, worker_id))
            return {"task_id": task_id, "released": True}

    store = LongTailEventStore()
    runner = LongTailGraphRunner(event_store=store, verifier=StepVerifier())
    task = runner.create_task(
        original_goal="恢复后继续等待页面读取结果",
        route_decision={"route_type": "long_tail_agent"},
        plan={
            "task_goal": "Recover waiting step.",
            "success_criteria": ["Page title is known."],
            "steps": [
                {
                    "step_id": "inspect_page",
                    "step_type": "browser_page_read",
                    "objective": "Identify page title.",
                    "expected_outputs": ["page_title"],
                    "allowed_actions": ["browser.observe"],
                    "forbidden_actions": ["browser.submit"],
                    "verification_criteria": ["Page title is reported."],
                }
            ],
        },
    )
    runner.run_next(task["task_id"])
    store.events_by_task["lta_recover_1"] = store.events_by_task.pop(task["task_id"])
    for event in store.events_by_task["lta_recover_1"]:
        event["task_id"] = "lta_recover_1"

    main._LONG_TAIL_EVENT_STORE = store
    main._LONG_TAIL_RUNNER = LongTailGraphRunner(event_store=store, verifier=StepVerifier())
    scanner = FakeScanner()
    lease_manager = FakeLeaseManager()

    summary = main.process_due_long_tail_recovery_once(
        scanner=scanner,
        lease_manager=lease_manager,
        worker_id="worker-test",
        limit=5,
        lease_seconds=15,
    )

    assert scanner.limit == 5
    assert summary["processed"] == 1
    assert summary["skipped"] == 1
    assert summary["results"][0]["task_id"] == "lta_recover_1"
    assert summary["results"][0]["state"]["current_node"] == "awaiting_executor"
    assert summary["results"][1]["status"] == "skipped"
    assert lease_manager.claimed == [
        ("lta_recover_1", "worker-test", 15),
        ("lta_recover_2", "worker-test", 15),
    ]
    assert lease_manager.released == [("lta_recover_1", "worker-test")]


def test_long_tail_regression_script_prints_reasonable_intermediate_artifacts():
    script = Path(__file__).resolve().parents[2] / "scripts" / "validate-long-tail-agent-runtime-v2.py"

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=Path(__file__).resolve().parents[2],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    lines = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    stages = [line["stage"] for line in lines]

    assert stages == [
        "task_created",
        "step_packet",
        "restart_recovery",
        "human_input_waiting",
        "human_input_resolved",
        "external_effect_waiting_confirmation",
        "external_effect_confirmed_and_executed",
        "policy_block_submit",
        "policy_allow_observe",
        "adapter_dry_run_observe",
        "adapter_live_observe",
        "adapter_live_policy_block",
        "fallback_external_action_card",
        "verification_passed",
        "final_delivery_external_effect_card",
        "event_trace",
        "api_mode_state_and_events",
        "api_external_effect_state_machine",
        "api_external_effect_rollback_card",
        "static_workbench_action_card_surface",
        "online_deployed_api_mode",
    ]
    assert all(line["reasonable"] is True for line in lines)
    assert lines[2]["output"]["current_node"] == "awaiting_executor"
    assert lines[3]["output"]["pending_human_input"]["question"] == "是否继续只读检查网页？"
    assert lines[4]["output"]["current_node"] == "select_step"
    assert lines[5]["output"]["effect"]["status"] == "waiting_for_confirmation"
    assert lines[5]["output"]["premature_execute"]["may_execute"] is False
    assert lines[6]["output"]["executed"]["may_execute"] is True
    assert lines[7]["output"]["policy_report"]["status"] == "blocked"
    assert lines[9]["output"]["status"] == "skipped_live_execution"
    assert lines[9]["output"]["dry_run_result"]["external_side_effect"] is False
    assert lines[10]["output"]["status"] == "completed"
    assert lines[10]["output"]["live_result"]["external_side_effect"] is False
    assert lines[11]["output"]["status"] == "blocked_by_policy"
    assert lines[12]["output"]["fallback_decision"]["action_card"]["actions"][0]["id"] == "review_external_effects"
    assert "不能假装已经撤回第三方动作" in lines[12]["output"]["fallback_decision"]["action_card"]["message"]
    assert lines[13]["output"]["verifier_report"]["status"] == "passed"
    assert lines[14]["output"]["status"] == "passed"
    assert lines[14]["output"]["delivery"]["actions"][0]["id"] == "review_external_effect_rollback"
    assert lines[16]["output"]["route"]["route_type"] == "long_tail_agent"
    assert lines[16]["output"]["route"]["capability_id"] == "automation.browser.operate"
    assert lines[16]["output"]["state"]["status"] == "running"
    assert "task.created" in lines[16]["output"]["event_types"]
    assert lines[17]["output"]["blocked"]["may_execute"] is False
    assert lines[17]["output"]["executed"]["may_execute"] is True
    assert lines[17]["output"]["event_types"][-3:] == [
        "external_effect.proposed",
        "external_effect.confirmed",
        "external_effect.executed",
    ]
    assert lines[18]["output"]["rollback"]["external_world_can_rollback"] is False
    assert lines[18]["output"]["rollback"]["action_card"]["actions"][0]["id"] == "prepare_compensation"
    assert lines[18]["output"]["compensation"]["status"] == "waiting_for_compensation_confirmation"
    assert lines[19]["output"]["has_delivery_handler"] is True
    assert lines[19]["output"]["has_compensation_handler"] is True
    assert lines[20]["output"]["status"] in {"skipped", "validated"}
    if lines[20]["output"]["status"] == "validated":
        assert lines[20]["output"]["route_type"] == "long_tail_agent"
        assert lines[20]["output"]["event_count"] >= 2
