import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


AGENDA_ID = "11111111-1111-1111-1111-111111111111"
EVENT_ID = "22222222-2222-2222-2222-222222222222"
SUGGESTION_ID = "33333333-3333-3333-3333-333333333333"
CONVERSATION_ID = "44444444-4444-4444-4444-444444444444"


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


def agenda_row(
    agenda_id=AGENDA_ID,
    title="Alex 说周末见。",
    status="scheduled",
    certainty="fuzzy",
    metadata=None,
):
    return (
        agenda_id,
        "appointment",
        title,
        status,
        certainty,
        {"raw_text": "周末见", "has_exact_time": False, "has_fuzzy_time": True},
        "",
        ["Alex"],
        ["exact_time", "exact_place"],
        True,
        0.82,
        [EVENT_ID],
        metadata or {"dedupe_key": "agenda:appointment:whatsapp:alex"},
        "2026-05-28T09:00:00+00:00",
        "2026-05-28T09:30:00+00:00",
        "create",
        "create agenda from semantic event: Alex 说周末见。",
        "2026-05-28T09:00:01+00:00",
    )


def test_agenda_list_filters_fuzzy_items_with_latest_version(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    def handler(sql, params):
        if "FROM agenda_items" in sql:
            assert "certainty = %s" in sql
            assert "fuzzy" in params
            return Cursor([agenda_row()])
        return Cursor()

    install_fake_db(monkeypatch, main, handler)
    response = TestClient(main.app).get(
        "/api/agenda?certainty=fuzzy",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] == AGENDA_ID
    assert item["certainty"] == "fuzzy"
    assert item["needs_clarification"] is True
    assert item["missing_fields"] == ["exact_time", "exact_place"]
    assert item["latest_version"]["operation"] == "create"
    assert item["source_event_ids"] == [EVENT_ID]


def test_agenda_list_filters_low_value_browser_ui_noise(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    def handler(sql, params):
        if "FROM agenda_items" in sql:
            return Cursor(
                [
                    agenda_row(
                        agenda_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                        title="0 notifications total\nKeyboard shortcuts\nClose jump menu",
                        metadata={"source": "linkedin"},
                    ),
                    agenda_row(
                        agenda_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                        title="2026-06-25 周四 16:00 人民广场会面",
                        certainty="exact",
                        metadata={"source": "gmail"},
                    ),
                ]
            )
        return Cursor()

    install_fake_db(monkeypatch, main, handler)
    response = TestClient(main.app).get(
        "/api/agenda?limit=50",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == ["bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"]


def test_agenda_list_filters_low_value_gmail_receipts_marketing_and_policy(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    def handler(sql, params):
        if "FROM agenda_items" in sql:
            return Cursor(
                [
                    agenda_row(
                        agenda_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                        title="Apple 收据：Your receipt from Apple, total $0.99",
                        metadata={"source": "gmail", "event_type": "gmail_message_snapshot"},
                    ),
                    agenda_row(
                        agenda_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                        title="Limited time offer upgrade today, unsubscribe anytime",
                        metadata={"source": "gmail", "event_type": "gmail_message_snapshot"},
                    ),
                    agenda_row(
                        agenda_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
                        title="We updated our Privacy Policy and Terms of Service",
                        metadata={"source": "gmail", "event_type": "gmail_message_snapshot"},
                    ),
                    agenda_row(
                        agenda_id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                        title=(
                            "He was offered six figures to leave Kajabi. He said no.："
                            "Five platforms tried to buy Roberto Blake away from Kajabi. "
                            "Here's why none of them could. Nearly $1M. Almost a Decade. Zero Temptation to Switch Platforms."
                        ),
                        metadata={"source": "gmail", "event_type": "gmail_message_snapshot"},
                    ),
                    agenda_row(
                        agenda_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
                        title="2026-07-02 14:00 后端岗位技术面",
                        certainty="exact",
                        metadata={"source": "gmail", "event_type": "gmail_message_snapshot"},
                    ),
                ]
            )
        return Cursor()

    install_fake_db(monkeypatch, main, handler)
    response = TestClient(main.app).get(
        "/api/agenda?limit=50",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == ["dddddddd-dddd-dddd-dddd-dddddddddddd"]


def test_agenda_list_filters_real_world_gmail_and_telegram_noise(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    def handler(sql, params):
        if "FROM agenda_items" in sql:
            return Cursor(
                [
                    agenda_row(
                        agenda_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                        title="让您提供的服务更清晰，开始撰写，OpenAI 1455 3rd Street，取消订阅，隐私 · 条款",
                        metadata={"source": "gmail", "event_type": "gmail_message_snapshot"},
                    ),
                    agenda_row(
                        agenda_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                        title="You have 2 new messages View messages:https://www.linkedin.com/comm/messaging/",
                        metadata={"source": "gmail", "event_type": "gmail_message_snapshot"},
                    ),
                    agenda_row(
                        agenda_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
                        title="订单支付成功：https://www.henghost.com/ 客户名称：请更新姓名",
                        metadata={"source": "gmail", "event_type": "gmail_message_snapshot"},
                    ),
                    agenda_row(
                        agenda_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
                        title="官方安全中心提醒您，请前往安全中心进行账号验证：https://www.tregsafety.com Telegram Web",
                        metadata={"source": "telegram", "event_type": "telegram_visible_snapshot"},
                    ),
                    agenda_row(
                        agenda_id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                        title="2026-07-03 15:30 人民广场见面，带合同",
                        certainty="exact",
                        metadata={"source": "whatsapp", "event_type": "whatsapp_message_snapshot"},
                    ),
                ]
            )
        return Cursor()

    install_fake_db(monkeypatch, main, handler)
    response = TestClient(main.app).get(
        "/api/agenda?limit=50",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == ["eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"]


def test_agenda_list_filters_current_cloud_gmail_noise_without_hiding_useful_reminders(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    def handler(sql, params):
        if "FROM agenda_items" in sql:
            return Cursor(
                [
                    agenda_row(
                        agenda_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                        title="She cried in front of 1,462 people and made zero sales. Then this happened.",
                        metadata={"source": "gmail", "event_type": "gmail_message_snapshot"},
                    ),
                    agenda_row(
                        agenda_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                        title='比较两种完成方式：<!DOCTYPE html><html dir="ltr"><head><meta charset="utf-8">',
                        metadata={"source": "gmail", "event_type": "gmail_message_snapshot"},
                    ),
                    agenda_row(
                        agenda_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
                        title="订单已生成，请及时支付",
                        metadata={"source": "gmail", "event_type": "gmail_message_snapshot"},
                    ),
                    agenda_row(
                        agenda_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
                        title="订单支付提醒",
                        metadata={"source": "gmail", "event_type": "gmail_message_snapshot"},
                    ),
                    agenda_row(
                        agenda_id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                        title="明天3点记得在腾讯会议上开线上会议",
                        certainty="exact",
                        metadata={"source": "gmail", "event_type": "gmail_message_snapshot"},
                    ),
                    agenda_row(
                        agenda_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
                        title="云服务器产品即将到期，请及时续费",
                        certainty="exact",
                        metadata={"source": "gmail", "event_type": "gmail_message_snapshot"},
                    ),
                ]
            )
        return Cursor()

    install_fake_db(monkeypatch, main, handler)
    response = TestClient(main.app).get(
        "/api/agenda?limit=50",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [
        "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        "ffffffff-ffff-ffff-ffff-ffffffffffff",
    ]


def test_agenda_patch_writes_user_correction_version(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    def handler(sql, params):
        if "FROM agenda_items" in sql and "LEFT JOIN LATERAL" in sql:
            return Cursor([agenda_row(title="Alex 说周末见。")])
        return Cursor()

    executed = install_fake_db(monkeypatch, main, handler)
    response = TestClient(main.app).patch(
        f"/api/agenda/{AGENDA_ID}",
        headers={"x-par-password": "secret"},
        json={"title": "周日和 Alex 见面", "place": "武康路", "status": "scheduled", "reason": "用户修正地点"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["agenda_id"] == AGENDA_ID
    assert body["version"]["operation"] == "user_correction"
    assert body["version"]["previous_value"]["title"] == "Alex 说周末见。"
    assert body["version"]["new_value"]["title"] == "周日和 Alex 见面"
    assert body["version"]["new_value"]["place"] == "武康路"
    assert any("UPDATE agenda_items" in sql for sql, _ in executed)
    assert any("INSERT INTO agenda_item_versions" in sql for sql, _ in executed)


def test_agenda_patch_fetch_query_qualifies_agenda_timestamps(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    def handler(sql, params):
        if "FROM agenda_items" in sql and "LEFT JOIN LATERAL" in sql:
            assert "agenda_items.created_at" in sql
            assert "agenda_items.updated_at" in sql
            assert "metadata, created_at, updated_at" not in sql
            return Cursor([agenda_row(title="LinkedIn browser noise")])
        return Cursor()

    install_fake_db(monkeypatch, main, handler)
    response = TestClient(main.app).patch(
        f"/api/agenda/{AGENDA_ID}",
        headers={"x-par-password": "secret"},
        json={"status": "dismissed", "reason": "cleanup polluted agenda item"},
    )

    assert response.status_code == 200


def test_agenda_snooze_updates_metadata_and_version(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    def handler(sql, params):
        if "FROM agenda_items" in sql and "LEFT JOIN LATERAL" in sql:
            return Cursor([agenda_row()])
        return Cursor()

    install_fake_db(monkeypatch, main, handler)
    response = TestClient(main.app).post(
        f"/api/agenda/{AGENDA_ID}/snooze",
        headers={"x-par-password": "secret"},
        json={"snoozed_until": "2026-05-29T09:00:00+08:00", "reason": "明天再提醒"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["agenda_id"] == AGENDA_ID
    assert body["version"]["operation"] == "snooze"
    assert body["version"]["new_value"]["metadata"]["snoozed_until"] == "2026-05-29T09:00:00+08:00"
    assert body["version"]["new_value"]["metadata"]["snooze_reason"] == "明天再提醒"


def test_user_feedback_schema_bootstrap(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed = []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            executed.append(" ".join(sql.split()))
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())
    main.ensure_proactive_feedback_schema()

    combined = "\n".join(executed)
    assert "CREATE TABLE IF NOT EXISTS proactive_candidates" in combined
    assert "CREATE TABLE IF NOT EXISTS user_feedback" in combined
    assert "user_feedback_suggestion_idx" in combined


def test_suggestion_action_records_feedback_and_routes_to_pipeline(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    published_route_traces = []

    def handler(sql, params):
        if "FROM proactive_suggestions" in sql and "SELECT id" in sql:
            return Cursor(
                [
                    (
                        SUGGESTION_ID,
                        EVENT_ID,
                        "跟进近期安排",
                        "Alex 约你周日去武康路见面。",
                        0.88,
                        "open",
                        {
                            "suggestion_type": "social_followup",
                            "source": "whatsapp",
                            "actions": [
                                {"id": "route_lookup", "label": "查路线", "next_step": "route_lookup"},
                                {"id": "ride_prepare", "label": "帮我打车", "next_step": "prepare_ride_request"},
                            ],
                        },
                        "2026-05-28T09:00:00+00:00",
                        "2026-05-28T09:00:00+00:00",
                    )
                ]
            )
        if "INSERT INTO task_route_traces" in sql:
            published_route_traces.append(params)
        return Cursor()

    install_fake_db(monkeypatch, main, handler)
    response = TestClient(main.app).post(
        f"/api/proactive/suggestions/{SUGGESTION_ID}/action",
        headers={"x-par-password": "secret"},
        json={"action_id": "route_lookup", "reason": "用户想先看路线"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["suggestion_id"] == SUGGESTION_ID
    assert body["action_id"] == "route_lookup"
    assert body["feedback_recorded"] is True
    assert body["route_result"]["route_type"] == "core_pipeline"
    assert body["route_result"]["pipeline"]["id"] == "route_pipeline"
    assert body["route_result"]["execution_guard"]["requires_confirmation"] is False
    assert body["pipeline_result"]["pipeline_id"] == "route_pipeline"
    assert body["pipeline_result"]["status"] == "completed_read_only"
    assert body["pipeline_result"]["resolved_slots"]["destination"] == "武康路"
    assert body["pipeline_result"]["output"]["route_request"]["destination"] == "武康路"
    assert "路线查询 Pipeline" in body["chat_summary"]
    assert "目的地：武康路" in body["chat_summary"]
    assert "执行状态：completed_read_only" in body["chat_summary"]
    assert published_route_traces


def test_suggestion_action_ride_prepare_keeps_final_confirmation(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    def handler(sql, params):
        if "FROM proactive_suggestions" in sql and "SELECT id" in sql:
            return Cursor(
                [
                    (
                        SUGGESTION_ID,
                        EVENT_ID,
                        "出行安排",
                        "Alex 约你周日去武康路见面。",
                        0.88,
                        "open",
                        {"actions": [{"id": "ride_prepare", "label": "帮我打车"}]},
                        "2026-05-28T09:00:00+00:00",
                        "2026-05-28T09:00:00+00:00",
                    )
                ]
            )
        return Cursor()

    install_fake_db(monkeypatch, main, handler)
    response = TestClient(main.app).post(
        f"/api/proactive/suggestions/{SUGGESTION_ID}/action",
        headers={"x-par-password": "secret"},
        json={"action_id": "ride_prepare", "reason": "用户想准备叫车"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["route_result"]["route_type"] == "core_pipeline"
    assert body["route_result"]["pipeline"]["id"] == "ride_pipeline"
    assert body["route_result"]["execution_guard"]["requires_confirmation"] is True
    assert body["route_result"]["execution_guard"]["final_user_confirmation"] is True


def test_suggestion_action_snooze_records_feedback_and_keeps_evidence(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed_updates = []

    def handler(sql, params):
        if "FROM proactive_suggestions" in sql and "SELECT id" in sql:
            return Cursor(
                [
                    (
                        SUGGESTION_ID,
                        EVENT_ID,
                        "跟进近期安排",
                        "Alex 约你周日去武康路见面。",
                        0.88,
                        "open",
                        {"source": "whatsapp"},
                        "2026-05-28T09:00:00+00:00",
                        "2026-05-28T09:00:00+00:00",
                    )
                ]
            )
        if "UPDATE proactive_suggestions" in sql:
            executed_updates.append((sql, params))
        return Cursor()

    install_fake_db(monkeypatch, main, handler)
    response = TestClient(main.app).post(
        f"/api/proactive/suggestions/{SUGGESTION_ID}/action",
        headers={"x-par-password": "secret"},
        json={
            "action_id": "snooze",
            "reason": "晚点提醒",
            "snoozed_until": "2026-05-29T09:00:00+08:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["feedback_recorded"] is True
    assert body["local_result"]["status"] == "open"
    assert body["local_result"]["metadata"]["snoozed_until"] == "2026-05-29T09:00:00+08:00"
    assert executed_updates


def test_event_trace_returns_connected_memory_agenda_suggestion_and_routes(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    def handler(sql, params):
        if "FROM events" in sql and "WHERE event_id = %s" in sql:
            return Cursor([(EVENT_ID, "whatsapp", "whatsapp_message", {"message": "周日去武康路见"}, "2026-05-28T09:00:00+00:00")])
        if "FROM semantic_events" in sql:
            return Cursor([("sem-1", "social_plan", {"primary_label": "appointment"}, 0.88, "Alex 约你周日去武康路见面。", "qwen3.6")])
        if "FROM memory_vectors" in sql:
            return Cursor([("vec-1", "Alex 约你周日去武康路见面。", {"memory_scope": {"conversation_label": "Alex"}})])
        if "FROM facts" in sql:
            return Cursor([("fact-1", "alex", "social_plan", "wukang road", 0.88, [EVENT_ID], {"summary": "见面安排"})])
        if "FROM agenda_items" in sql:
            return Cursor([agenda_row()])
        if "FROM agenda_item_versions" in sql:
            return Cursor([("ver-1", AGENDA_ID, "create", {}, {"title": "Alex 说周末见。"}, "created", [EVENT_ID], 0.82, "2026-05-28T09:00:01+00:00")])
        if "FROM proactive_suggestions" in sql:
            return Cursor([(SUGGESTION_ID, EVENT_ID, "跟进近期安排", "Alex 约你周日去武康路见面。", 0.88, "open", {}, "2026-05-28T09:01:00+00:00", "2026-05-28T09:01:00+00:00")])
        if "FROM task_route_traces" in sql:
            return Cursor([(
                "trace-1",
                "查路线：Alex 约你周日去武康路见面。",
                "core_pipeline",
                "local_service.route.lookup",
                "route_pipeline",
                "read_only",
                False,
                {},
                None,
                None,
                {"source_event_ids": [EVENT_ID]},
                "2026-05-28T09:02:00+00:00",
                [EVENT_ID],
                CONVERSATION_ID,
                SUGGESTION_ID,
                [AGENDA_ID],
            )])
        if "FROM pipeline_execution_results" in sql:
            return Cursor([(
                "exec-1",
                "trace-1",
                "查路线：Alex 约你周日去武康路见面。",
                "core_pipeline",
                "local_service.route.lookup",
                "route_pipeline",
                "completed_read_only",
                ["destination"],
                {"destination": "武康路"},
                [],
                {"permission": "read_only"},
                {"requires_confirmation": False},
                [EVENT_ID],
                CONVERSATION_ID,
                SUGGESTION_ID,
                [AGENDA_ID],
                {"status": "completed_read_only", "resolved_slots": {"destination": "武康路"}},
                "2026-05-28T09:02:02+00:00",
            )])
        return Cursor()

    install_fake_db(monkeypatch, main, handler)
    response = TestClient(main.app).get(
        f"/api/events/{EVENT_ID}/trace",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["event"]["event_id"] == EVENT_ID
    assert body["semantic_event"]["intent"] == "social_plan"
    assert body["memory_vectors"][0]["metadata"]["memory_scope"]["conversation_label"] == "Alex"
    assert body["facts"][0]["predicate"] == "social_plan"
    assert body["agenda_items"][0]["latest_version"]["operation"] == "create"
    assert body["suggestions"][0]["id"] == SUGGESTION_ID
    assert body["route_traces"][0]["pipeline_id"] == "route_pipeline"
    assert body["route_traces"][0]["source_event_ids"] == [EVENT_ID]
    assert body["route_traces"][0]["conversation_id"] == CONVERSATION_ID
    assert body["pipeline_executions"][0]["pipeline_id"] == "route_pipeline"
    assert body["pipeline_executions"][0]["resolved_slots"]["destination"] == "武康路"


def test_conversation_trace_returns_turns_context_and_routes(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    def handler(sql, params):
        if "FROM assistant_conversations" in sql:
            return Cursor([(CONVERSATION_ID, "android", "2026-05-28T09:00:00+00:00", "2026-05-28T09:10:00+00:00", None, {"source": "nomi_chat"}, "active")])
        if "FROM assistant_turns" in sql:
            return Cursor([("turn-1", CONVERSATION_ID, "user", "帮我盯一下周末和 Alex 见面", EVENT_ID, None, None, "2026-05-28T09:00:00+00:00", None)])
        if "FROM context_snapshots" in sql:
            return Cursor([("ctx-1", EVENT_ID, "chat_response", [EVENT_ID], [], [AGENDA_ID], "bounded context pack", {"agenda_context": [{"id": AGENDA_ID}]}, "2026-05-28T09:00:01+00:00")])
        if "FROM proactive_suggestions" in sql:
            return Cursor([(SUGGESTION_ID, EVENT_ID, "跟进近期安排", "Alex 约你周日去武康路见面。", 0.88, "open", {}, "2026-05-28T09:01:00+00:00", "2026-05-28T09:01:00+00:00")])
        if "FROM task_route_traces" in sql:
            return Cursor([(
                "trace-1",
                "查路线",
                "core_pipeline",
                "local_service.route.lookup",
                "route_pipeline",
                "read_only",
                False,
                {},
                None,
                None,
                {"conversation_id": CONVERSATION_ID},
                "2026-05-28T09:02:00+00:00",
                [EVENT_ID],
                CONVERSATION_ID,
                SUGGESTION_ID,
                [AGENDA_ID],
            )])
        if "FROM pipeline_execution_results" in sql:
            return Cursor([(
                "exec-1",
                "trace-1",
                "查路线",
                "core_pipeline",
                "local_service.route.lookup",
                "route_pipeline",
                "completed_read_only",
                ["destination"],
                {"destination": "武康路"},
                [],
                {"permission": "read_only"},
                {"requires_confirmation": False},
                [EVENT_ID],
                CONVERSATION_ID,
                SUGGESTION_ID,
                [AGENDA_ID],
                {"status": "completed_read_only", "resolved_slots": {"destination": "武康路"}},
                "2026-05-28T09:02:02+00:00",
            )])
        return Cursor()

    install_fake_db(monkeypatch, main, handler)
    response = TestClient(main.app).get(
        f"/api/chat/conversations/{CONVERSATION_ID}/trace",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation"]["id"] == CONVERSATION_ID
    assert body["turns"][0]["content"] == "帮我盯一下周末和 Alex 见面"
    assert body["context_snapshots"][0]["included_agenda_ids"] == [AGENDA_ID]
    assert body["suggestions"][0]["source_event_id"] == EVENT_ID
    assert body["route_traces"][0]["pipeline_id"] == "route_pipeline"
    assert body["route_traces"][0]["conversation_id"] == CONVERSATION_ID
    assert body["pipeline_executions"][0]["conversation_id"] == CONVERSATION_ID


def test_build_context_pack_includes_active_agenda_and_excludes_unrelated():
    from app.main import build_chat_messages, build_context_pack

    pack = build_context_pack(
        "那就周日吧",
        base_context=[],
        assistant_context=[],
        conversation_id="conv-active",
        agenda_context=[
            {
                "id": AGENDA_ID,
                "title": "周末和 Alex 见面",
                "participants": ["Alex"],
                "certainty": "fuzzy",
                "missing_fields": ["exact_time", "exact_place"],
                "source_event_ids": [EVENT_ID],
            },
            {
                "id": "55555555-5555-5555-5555-555555555555",
                "title": "缴纳服务器账单",
                "participants": [],
                "certainty": "exact",
                "missing_fields": [],
                "source_event_ids": ["66666666-6666-6666-6666-666666666666"],
            },
        ],
    )

    assert [item["id"] for item in pack["agenda_context"]] == [AGENDA_ID]
    assert pack["included_agenda_ids"] == [AGENDA_ID]
    assert EVENT_ID in pack["included_event_ids"]
    prompt = build_chat_messages("那就周日吧", pack)[1]["content"]
    assert "周末和 Alex 见面" in prompt
    assert "缴纳服务器账单" not in prompt
