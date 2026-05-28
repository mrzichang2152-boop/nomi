import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


class Cursor:
    rowcount = 1

    def __init__(self, rows=None):
        self.rows = rows or []

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


def install_fake_db(monkeypatch, main, handler):
    executed = []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            executed.append((normalized, params))
            return handler(normalized, params)

    monkeypatch.setattr(main, "db", lambda: Conn())
    return executed


def test_reply_pipeline_execution_returns_draft_ready_contract(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    result = main.run_core_pipeline(
        "帮我回复 Alice，说我周五八点可以",
        {"active_source_scope": {"source": "whatsapp", "conversation_id": "chat-alice"}},
    )

    assert result["route_type"] == "core_pipeline"
    assert result["pipeline_id"] == "reply_pipeline"
    assert result["status"] == "draft_ready"
    assert result["resolved_slots"]["recipient"] == "Alice"
    assert result["resolved_slots"]["channel"] == "whatsapp"
    assert "周五八点可以" in result["resolved_slots"]["message_intent"]
    assert result["risk"]["permission"] == "external_message"
    assert result["risk"]["confirmation_required"] is True
    assert "send_message" in result["external_effects"]
    assert result["missing_slots"] == []


def test_route_pipeline_execution_returns_read_only_contract(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    result = main.run_core_pipeline("查一下去武康路要多久")

    assert result["pipeline_id"] == "route_pipeline"
    assert result["status"] == "completed_read_only"
    assert result["resolved_slots"]["destination"] == "武康路"
    assert result["missing_slots"] == []
    assert result["risk"]["permission"] == "read_only"
    assert result["risk"]["confirmation_required"] is False


def test_ride_pipeline_execution_requires_pickup_before_booking(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    result = main.run_core_pipeline("帮我打车去武康路")

    assert result["pipeline_id"] == "ride_pipeline"
    assert result["status"] == "needs_user_input"
    assert result["resolved_slots"]["destination"] == "武康路"
    assert "pickup" in result["missing_slots"]
    assert result["risk"]["permission"] == "payment_or_purchase"
    assert result["risk"]["final_user_confirmation"] is True
    assert "book_ride" in result["external_effects"]


def test_vague_payment_pipeline_execution_asks_for_missing_fields(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    result = main.run_core_pipeline("帮我付款")

    assert result["route_type"] == "ask_user"
    assert result["status"] == "needs_user_input"
    assert result["pipeline_id"] is None
    assert {"amount_or_bill", "counterparty"}.issubset(set(result["missing_slots"]))
    assert "付款" in result["input"]["user_request"]


def test_pipeline_run_endpoint_returns_execution_contract(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    response = TestClient(main.app).post(
        "/api/pipelines/run",
        headers={"x-par-password": "secret"},
        json={"request": "查路线去武康路", "context": {"source_event_ids": ["evt-1"]}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pipeline_id"] == "route_pipeline"
    assert body["status"] == "completed_read_only"
    assert body["resolved_slots"]["destination"] == "武康路"
    assert body["input"]["source_event_ids"] == ["evt-1"]


def test_hybrid_slot_parser_uses_model_when_rules_are_missing(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("PIPELINE_SLOT_MODEL_ENABLED", "1")
    from app import main

    monkeypatch.setattr(
        main,
        "call_pipeline_slot_model",
        lambda request, pipeline, context, rule_slots: {
            "slots": {"recipient": "Alice", "message_intent": "周五八点可以"},
            "confidence": 0.91,
            "reason": "上下文里的 she 指 Alice。",
        },
    )

    result = main.run_core_pipeline(
        "帮我回复她，就说周五八点可以",
        {"active_source_scope": {"source": "whatsapp", "conversation_id": "chat-alice"}},
    )

    assert result["pipeline_id"] == "reply_pipeline"
    assert result["status"] == "draft_ready"
    assert result["resolved_slots"]["recipient"] == "Alice"
    assert result["resolved_slots"]["channel"] == "whatsapp"
    assert result["resolved_slots"]["message_intent"] == "周五八点可以"
    assert result["slot_extraction"]["parser_mode"] == "hybrid_model_rules"
    assert result["slot_extraction"]["model_used"] is True
    assert result["slot_extraction"]["validation_warnings"] == []


def test_hybrid_slot_parser_keeps_rule_slot_when_model_conflicts(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("PIPELINE_SLOT_MODEL_ENABLED", "1")
    from app import main

    monkeypatch.setattr(
        main,
        "call_pipeline_slot_model",
        lambda request, pipeline, context, rule_slots: {
            "slots": {"destination": "外滩"},
            "confidence": 0.94,
            "reason": "模型误判目的地。",
        },
    )

    result = main.run_core_pipeline("查路线去武康路")

    assert result["pipeline_id"] == "route_pipeline"
    assert result["resolved_slots"]["destination"] == "武康路"
    assert "model_conflict:destination" in result["slot_extraction"]["validation_warnings"]
    assert result["slot_extraction"]["model_slots"]["destination"] == "外滩"


def test_pipeline_execution_schema_bootstrap(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    def handler(sql, params):
        return Cursor()

    executed = install_fake_db(monkeypatch, main, handler)
    main.ensure_task_routing_schema()
    combined = "\n".join(sql for sql, _ in executed)

    assert "CREATE TABLE IF NOT EXISTS pipeline_execution_results" in combined
    assert "pipeline_execution_results_trace_idx" in combined
    assert "ALTER TABLE task_route_traces ADD COLUMN IF NOT EXISTS source_event_ids" in combined
    assert "task_route_traces_source_event_idx" in combined
    assert "CREATE TABLE IF NOT EXISTS provider_call_traces" in combined
    assert "CREATE TABLE IF NOT EXISTS confirmation_ledger" in combined
    assert "CREATE TABLE IF NOT EXISTS event_quarantine" in combined
    assert "CREATE TABLE IF NOT EXISTS duplicate_skip" in combined
    assert "CREATE TABLE IF NOT EXISTS internal_todos" in combined
    assert "CREATE TABLE IF NOT EXISTS internal_reminders" in combined
    assert "CREATE TABLE IF NOT EXISTS search_audit" in combined
    assert "CREATE TABLE IF NOT EXISTS account_connections" in combined
    assert "CREATE TABLE IF NOT EXISTS composio_sessions" in combined
    assert "CREATE TABLE IF NOT EXISTS composio_connect_requests" in combined
    assert "CREATE TABLE IF NOT EXISTS composio_toolkits" in combined
    assert "CREATE TABLE IF NOT EXISTS composio_tool_invocations" in combined
    assert "CREATE TABLE IF NOT EXISTS composio_triggers" in combined
    assert "CREATE TABLE IF NOT EXISTS pipeline_health_metrics" in combined
    assert "UPDATE task_route_traces t SET source_event_ids" in combined
    assert "UPDATE pipeline_execution_results p SET source_event_ids" in combined


def test_pipeline_run_endpoint_persists_execution_result_when_enabled(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("PIPELINE_EXECUTION_TEST_PERSIST", "1")
    from app import main

    def handler(sql, params):
        return Cursor()

    executed = install_fake_db(monkeypatch, main, handler)
    response = TestClient(main.app).post(
        "/api/pipelines/run",
        headers={"x-par-password": "secret"},
        json={
            "request": "查路线去武康路",
            "context": {"source_event_ids": ["evt-1"], "conversation_id": "conv-1"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pipeline_id"] == "route_pipeline"
    assert body["pipeline_execution_id"]
    assert body["execution_persisted"] is True
    assert any("INSERT INTO pipeline_execution_results" in sql for sql, _ in executed)
    insert_params = next(params for sql, params in executed if "INSERT INTO pipeline_execution_results" in sql)
    assert insert_params[12] == ["evt-1"]
    assert insert_params[13] == "conv-1"


def test_pipeline_run_endpoint_applies_local_writeback_plan_when_enabled(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("PIPELINE_EXECUTION_TEST_PERSIST", "1")
    from app import main

    def handler(sql, params):
        return Cursor()

    executed = install_fake_db(monkeypatch, main, handler)
    response = TestClient(main.app).post(
        "/api/pipelines/run",
        headers={"x-par-password": "secret"},
        json={
            "request": "坏事件",
            "context": {
                "pipeline_id": "event_ingestion_pipeline",
                "source": "whatsapp",
                "event_type": "message",
                "timestamp": "2026-05-28T09:00:00+08:00",
                "raw_event": {"text": "missing id"},
                "schema_errors": ["missing_message_id"],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["writeback_applied"] is True
    assert any("INSERT INTO pipeline_execution_results" in sql for sql, _ in executed)
    assert any("INSERT INTO event_quarantine" in sql for sql, _ in executed)
    assert any("INSERT INTO collector_health" in sql for sql, _ in executed)
    assert any("INSERT INTO pipeline_health_metrics" in sql for sql, _ in executed)


def test_local_writeback_executor_records_governance_audit_tables(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    def handler(sql, params):
        return Cursor()

    executed = install_fake_db(monkeypatch, main, handler)
    result = main.run_core_pipeline(
        "审计",
        {
            "pipeline_id": "governance_audit_pipeline",
            "task_id": "task-ride-1",
            "provider_call_plan": {
                "provider": "uber",
                "action": "estimate_ride",
                "status": "proposed_only",
            },
            "confirmation_card": {
                "kind": "ride_booking",
                "confirm_action": "book_ride",
                "final_user_confirmation": True,
            },
        },
    )
    summary = main.apply_pipeline_writeback_plan(main.db(), result)

    assert summary["applied"] is True
    assert any("INSERT INTO provider_call_traces" in sql for sql, _ in executed)
    assert any("INSERT INTO confirmation_ledger" in sql for sql, _ in executed)
    assert any("INSERT INTO pipeline_health_metrics" in sql for sql, _ in executed)


def test_pipeline_results_include_contract_version(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    result = main.run_core_pipeline(
        "查路线",
        {"pipeline_id": "route_pipeline", "destination": "武康路"},
    )

    assert result["version"] == "2026-05-28"
    assert result["pipeline_version"] == "2026-05-28"


def test_personal_search_pipeline_retrieves_memory_hits_from_local_db(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    def handler(sql, params):
        if "FROM facts" in sql:
            return Cursor(
                [
                    (
                        "fact-1",
                        "Alex",
                        "meeting_place",
                        "武康路",
                        0.92,
                        ["evt-1"],
                        {"scope": "chat_alex"},
                        "2026-05-28T09:00:00+08:00",
                    )
                ]
            )
        if "FROM memory_items" in sql:
            return Cursor([])
        return Cursor()

    install_fake_db(monkeypatch, main, handler)
    result = main.run_core_pipeline(
        "Alex 在哪里见面",
        {
            "pipeline_id": "personal_search_pipeline",
            "query": "Alex 见面地点",
            "current_scope": "chat_alex",
        },
    )

    assert result["status"] == "completed_read_only"
    assert result["output"]["citations"][0]["id"] == "fact-1"
    assert "武康路" in result["output"]["answer_summary"]


def test_context_pack_pipeline_retrieves_local_memory_agenda_and_turns(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    agenda_id = "2c56a26f-651e-45f6-b45f-d47ce8034c9d"
    turn_event_id = "1b56a26f-651e-45f6-b45f-d47ce8034c9c"

    def handler(sql, params):
        if "FROM facts" in sql:
            return Cursor(
                [
                    (
                        "fact-context-1",
                        "Alex",
                        "meeting_topic",
                        "周末见面",
                        0.91,
                        ["evt-alex-1"],
                        {"scope": {"kind": "contact", "id": "alex"}},
                        "2026-05-28T10:00:00+08:00",
                    )
                ]
            )
        if "FROM memory_items" in sql:
            return Cursor([])
        if "FROM agenda_items" in sql:
            return Cursor(
                [
                    (
                        agenda_id,
                        "appointment",
                        "Alex 周末见面",
                        "scheduled",
                        "fuzzy",
                        {"start": "2026-05-30", "end": "2026-05-31"},
                        "",
                        ["Alex"],
                        ["exact_time", "exact_place"],
                        True,
                        0.84,
                        ["evt-alex-1"],
                        {"scope": {"kind": "contact", "id": "alex"}},
                        "2026-05-28T09:00:00+08:00",
                        "2026-05-28T09:00:00+08:00",
                        None,
                        None,
                        None,
                    )
                ]
            )
        if "FROM assistant_turns" in sql:
            return Cursor(
                [
                    (
                        turn_event_id,
                        "conv-alex",
                        "user",
                        "帮我盯一下和 Alex 周末见面的事",
                        "2026-05-28T09:30:00+08:00",
                        {},
                    )
                ]
            )
        return Cursor()

    install_fake_db(monkeypatch, main, handler)
    result = main.run_core_pipeline(
        "那就周日吧",
        {
            "pipeline_id": "context_pack_pipeline",
            "request_or_event_id": "req-context-1",
            "current_scope": {"kind": "contact", "id": "alex"},
            "conversation_id": "conv-alex",
        },
    )

    assert result["status"] == "completed_read_only"
    output = result["output"]
    assert output["included_memory_ids"] == ["fact-context-1"]
    assert output["included_agenda_ids"] == [agenda_id]
    assert output["recent_turn_ids"] == [turn_event_id]
    assert output["scope_boundary"]["current_scope"] == {"kind": "contact", "id": "alex"}


def test_writeback_executor_materializes_internal_event_agenda_search_and_route(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    def handler(sql, params):
        return Cursor()

    executed = install_fake_db(monkeypatch, main, handler)
    result = {
        "pipeline_execution_id": "exec-1",
        "task_trace_id": "trace-1",
        "pipeline_id": "test_pipeline",
        "status": "completed_read_only",
        "writeback_plan": [
            {
                "target": "events",
                "operation": "upsert",
                "payload": {
                    "event_id": "evt-local-writeback",
                    "source": "whatsapp",
                    "event_type": "message",
                    "timestamp": "2026-05-28T10:00:00+08:00",
                    "raw_event": {"text": "周末见"},
                },
            },
            {
                "target": "agenda_items",
                "operation": "create",
                "item": {
                    "agenda_item_id": "agenda-local-writeback",
                    "title": "Alex 周末见面",
                    "operation": "create",
                    "status": "scheduled",
                    "certainty": "fuzzy",
                    "time_window": {"start": "2026-05-30", "end": "2026-05-31"},
                    "missing_fields": ["exact_time", "exact_place"],
                    "source_event_ids": ["evt-local-writeback"],
                },
            },
            {
                "target": "search_audit",
                "operation": "record",
                "payload": {"query": "Alex 见面", "scope": "chat_alex", "result_count": 1},
            },
            {
                "target": "route_cache",
                "operation": "record",
                "payload": {"origin": "当前位置", "destination": "武康路", "mode": "transit"},
            },
        ],
    }

    summary = main.apply_pipeline_writeback_plan(main.db(), result)

    assert summary["applied"] is True
    assert summary["applied_count"] == 4
    assert any("INSERT INTO events" in sql for sql, _ in executed)
    assert any("INSERT INTO agenda_items" in sql for sql, _ in executed)
    assert any("INSERT INTO agenda_item_versions" in sql for sql, _ in executed)
    assert any("INSERT INTO search_audit" in sql for sql, _ in executed)
    assert any("INSERT INTO route_cache" in sql for sql, _ in executed)


def test_pipeline_health_dashboard_returns_materialized_audit_tables(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    def handler(sql, params):
        if "FROM pipeline_health_metrics" in sql:
            return Cursor(
                [
                    (
                        "11111111-1111-1111-1111-111111111111",
                        "route_pipeline",
                        "completed_read_only",
                        2,
                        0,
                        1,
                        {"applied": True},
                        "2026-05-28T10:00:00+08:00",
                    )
                ]
            )
        if "FROM provider_call_traces" in sql:
            return Cursor(
                [
                    (
                        "22222222-2222-2222-2222-222222222222",
                        "task-1",
                        "uber",
                        "estimate_ride",
                        "planned",
                        {"mode": "proposed_only"},
                        "2026-05-28T10:01:00+08:00",
                    )
                ]
            )
        if "FROM confirmation_ledger" in sql:
            return Cursor(
                [
                    (
                        "33333333-3333-3333-3333-333333333333",
                        "task-1",
                        "ride_booking",
                        "book_ride",
                        True,
                        "required",
                        {"confirm_action": "book_ride"},
                        "2026-05-28T10:02:00+08:00",
                    )
                ]
            )
        if "FROM search_audit" in sql:
            return Cursor(
                [
                    (
                        "44444444-4444-4444-4444-444444444444",
                        "personal_search_pipeline",
                        "Alex 见面地点",
                        "chat_alex",
                        1,
                        {"citation_ids": ["fact-1"]},
                        "2026-05-28T10:03:00+08:00",
                    )
                ]
            )
        return Cursor()

    install_fake_db(monkeypatch, main, handler)
    response = TestClient(main.app).get("/api/pipelines/health", headers={"x-par-password": "secret"})

    assert response.status_code == 200
    body = response.json()
    assert body["pipeline_health_metrics"][0]["pipeline_id"] == "route_pipeline"
    assert body["provider_call_traces"][0]["provider"] == "uber"
    assert body["confirmation_ledger"][0]["confirm_action"] == "book_ride"
    assert body["search_audit"][0]["query"] == "Alex 见面地点"


def test_task_route_trace_persists_explicit_references(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    def handler(sql, params):
        return Cursor()

    executed = install_fake_db(monkeypatch, main, handler)
    route = main.route_tool_request(
        "查路线去武康路",
        {
            "source_event_ids": ["evt-1"],
            "conversation_id": "conv-1",
            "suggestion_id": "sug-1",
            "agenda_item_ids": ["agenda-1"],
        },
    )
    main.persist_task_route_trace(main.db(), route)

    sql, params = next(item for item in executed if "INSERT INTO task_route_traces" in item[0])
    assert "source_event_ids" in sql
    assert "conversation_id" in sql
    assert "suggestion_id" in sql
    assert "agenda_item_ids" in sql
    assert params[11] == ["evt-1"]
    assert params[12] == "conv-1"
    assert params[13] == "sug-1"
    assert params[14] == ["agenda-1"]


def test_event_trace_uses_explicit_refs_and_returns_pipeline_executions(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed = []

    def handler(sql, params):
        executed.append((sql, params))
        if "FROM events" in sql and "WHERE event_id = %s" in sql:
            return Cursor([("evt-1", "whatsapp", "message", {"message": "去武康路"}, "2026-05-28T09:00:00+00:00")])
        if "FROM task_route_traces" in sql:
            return Cursor(
                [
                    (
                        "trace-1",
                        "查路线去武康路",
                        "core_pipeline",
                        "local_service.route.lookup",
                        "route_pipeline",
                        "read_only",
                        False,
                        {},
                        None,
                        None,
                        {},
                        "2026-05-28T09:01:00+00:00",
                        ["evt-1"],
                        "conv-1",
                        "sug-1",
                        ["agenda-1"],
                    )
                ]
            )
        if "FROM pipeline_execution_results" in sql:
            return Cursor(
                [
                    (
                        "exec-1",
                        "trace-1",
                        "查路线去武康路",
                        "core_pipeline",
                        "local_service.route.lookup",
                        "route_pipeline",
                        "completed_read_only",
                        ["destination"],
                        {"destination": "武康路"},
                        [],
                        {"permission": "read_only"},
                        {"requires_confirmation": False},
                        ["evt-1"],
                        "conv-1",
                        "sug-1",
                        ["agenda-1"],
                        {"status": "completed_read_only"},
                        "2026-05-28T09:01:01+00:00",
                    )
                ]
            )
        return Cursor()

    monkeypatch.setattr(main, "db", lambda: type("Conn", (), {
        "__enter__": lambda self: self,
        "__exit__": lambda self, exc_type, exc, tb: None,
        "execute": lambda self, sql, params=(): handler(" ".join(sql.split()), params),
    })())

    body = TestClient(main.app).get(
        "/api/events/evt-1/trace",
        headers={"x-par-password": "secret"},
    ).json()

    route_sql = next(sql for sql, _ in executed if "FROM task_route_traces" in sql)
    execution_sql = next(sql for sql, _ in executed if "FROM pipeline_execution_results" in sql)
    assert "ANY(source_event_ids)" in route_sql
    assert "ANY(source_event_ids)" in execution_sql
    assert body["route_traces"][0]["source_event_ids"] == ["evt-1"]
    assert body["pipeline_executions"][0]["pipeline_execution_id"] == "exec-1"
    assert body["pipeline_executions"][0]["resolved_slots"]["destination"] == "武康路"


def test_direct_pipeline_dispatch_returns_module_output(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    result = main.run_core_pipeline(
        "查路线",
        {"pipeline_id": "route_pipeline", "destination": "武康路", "current_location": "上海图书馆"},
    )

    assert result["pipeline_id"] == "route_pipeline"
    assert result["status"] == "completed_read_only"
    assert result["resolved_slots"]["destination"] == "武康路"
    assert result["output"]["route_request"]["destination"] == "武康路"
    assert result["output"]["provider_needed"] == "google_maps"
    assert result["provider_calls"] == []


def test_direct_pipeline_dispatch_preserves_module_control_fields(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    result = main.run_core_pipeline(
        "帮我打车",
        {"pipeline_id": "ride_pipeline", "pickup": "上海图书馆", "destination": "武康路"},
    )

    assert result["pipeline_id"] == "ride_pipeline"
    assert result["status"] == "confirmation_required"
    assert result["provider_call_plan"]["mode"] == "blocked_until_confirmation"
    assert result["confirmation_card"]["confirm_action"] == "book_ride"
    assert "book_ride" in result["blocked_effects"]
    assert {
        check["name"]
        for check in result["safety_checks"]
    }.issuperset({"requires_final_user_confirmation", "ride_not_booked"})


def test_governance_audit_pipeline_records_explicit_reference_plan(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    result = main.run_core_pipeline(
        "记录审计",
        {
            "pipeline_id": "governance_audit_pipeline",
            "task_id": "task-1",
            "source_event_ids": ["evt-1"],
            "conversation_id": "conv-1",
            "suggestion_id": "sug-1",
            "agenda_item_ids": ["agenda-1"],
        },
    )

    assert result["pipeline_id"] == "governance_audit_pipeline"
    assert result["status"] == "completed_read_only"
    assert result["output"]["trace_chain"]["task_id"] == "task-1"
    assert result["output"]["trace_chain"]["source_event_ids"] == ["evt-1"]
    assert "pipeline_execution_results" in result["writeback_targets"]


def test_governance_audit_pipeline_records_provider_and_confirmation_plans(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    result = main.run_core_pipeline(
        "记录外部动作审计",
        {
            "pipeline_id": "governance_audit_pipeline",
            "task_id": "task-ride-1",
            "source_event_ids": ["evt-ride-1"],
            "provider_call_plan": {
                "provider": "uber",
                "action": "estimate_ride",
                "status": "proposed_only",
            },
            "confirmation_card": {
                "kind": "ride_booking",
                "confirm_action": "book_ride",
                "final_user_confirmation": True,
            },
        },
    )

    audit = result["output"]
    assert audit["provider_call_audit"]["status"] == "planned"
    assert audit["provider_call_audit"]["provider"] == "uber"
    assert audit["confirmation_ledger"]["required"] is True
    assert audit["confirmation_ledger"]["final_user_confirmation"] is True
    assert {
        "provider_call_traces",
        "confirmation_ledger",
    }.issubset(set(result["writeback_targets"]))
    assert any(plan["target"] == "provider_call_traces" for plan in result["writeback_plan"])
    assert any(plan["target"] == "confirmation_ledger" for plan in result["writeback_plan"])


def test_contact_relationship_pipeline_returns_scoped_graph_plan(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    result = main.run_core_pipeline(
        "记录 Alex 喜欢安静的餐厅",
        {
            "pipeline_id": "contact_relationship_pipeline",
            "contact_or_actor": "Alex",
            "relationship_fact": "喜欢安静的餐厅",
            "source_event_ids": ["evt-1"],
            "conversation_id": "conv-alex",
        },
    )

    assert result["pipeline_id"] == "contact_relationship_pipeline"
    assert result["status"] == "completed_read_only"
    assert result["resolved_slots"]["contact_or_actor"] == "Alex"
    assert result["output"]["relationship_update"]["contact_or_actor"] == "Alex"
    assert result["output"]["relationship_update"]["scope"]["conversation_id"] == "conv-alex"
    assert "knowledge_edges" in result["writeback_targets"]
