import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


from app.pipelines.agenda import run_agenda_pipeline


def test_agenda_resolves_clear_relative_datetime_against_anchor_time():
    result = run_agenda_pipeline(
        "agenda_pipeline",
        "明天下午5点在人民广场见，带合同",
        {
            "operation": "create",
            "title": "人民广场见面",
            "time_window": {"text": "明天下午5点", "type": "fuzzy"},
            "anchor_time": "2026-06-18T10:00:00+08:00",
            "source_event_ids": ["evt-relative-time"],
        },
    )

    time_window = result["resolved_slots"]["time_window"]
    assert time_window["type"] == "exact"
    assert time_window["start"] == "2026-06-19T17:00:00+08:00"
    assert time_window["display_date"] == "2026-06-19"
    assert time_window["display_time"] == "17:00"
    assert time_window["display"] == "2026-06-19 周五 17:00"
    assert time_window["text"] == "2026-06-19 周五 17:00"
    assert time_window["raw_text"] == "明天下午5点"
    assert result["output"]["notification_plan"]["time_precision"] == "exact"
    assert result["output"]["notification_plan"]["concrete_reminder"]["time_window"]["start"] == "2026-06-19T17:00:00+08:00"


def test_agenda_rejects_unsupported_model_exact_time_and_keeps_fuzzy_rule_time():
    result = run_agenda_pipeline(
        "agenda_pipeline",
        "那就周日见，聊发布计划",
        {
            "operation": "create",
            "rule_candidate": {
                "title": "聊发布计划",
                "time_window": {"text": "周日", "type": "fuzzy"},
                "exact_time_supported": False,
            },
            "model_candidate": {
                "title": "聊发布计划",
                "time_window": {"start": "2026-05-31T10:00:00+08:00", "type": "exact"},
            },
            "source_event_ids": ["evt-weekend"],
        },
    )

    assert result["pipeline_id"] == "agenda_pipeline"
    assert result["status"] == "confirmation_required"
    assert result["resolved_slots"]["time_window"] == {"text": "周日", "type": "fuzzy"}
    assert result["resolved_slots"]["operation"] == "create"
    assert "unsupported_model_exact_time:time_window" in result["slot_extraction"]["validation_warnings"]
    assert result["writeback_plan"][0]["target"] == "agenda_items"
    assert result["writeback_plan"][0]["operation"] == "create"
    assert result["writeback_plan"][0]["confirmation_required"] is False
    calendar_plan = result["writeback_plan"][1]
    assert calendar_plan["target"] == "external_calendar"
    assert calendar_plan["operation"] == "propose_write"
    assert calendar_plan["confirmation_required"] is True
    assert result["risk"]["confirmation_required"] is True
    assert "write_calendar" in result["external_effects"]


def test_agenda_reschedule_cancel_update_and_complete_operations_are_internal_plans():
    cases = [
        ("reschedule", "agenda-1", "reschedule"),
        ("cancel", "agenda-2", "cancel"),
        ("update", "agenda-3", "update"),
        ("complete", "agenda-4", "complete"),
    ]

    for operation, agenda_id, expected_plan_operation in cases:
        result = run_agenda_pipeline(
            "agenda_pipeline",
            "把会面改一下",
            {
                "operation": operation,
                "agenda_item_id": agenda_id,
                "title": "产品会面",
                "time_window": {"text": "今晚", "type": "fuzzy"},
                "source_event_ids": [f"evt-{operation}"],
            },
        )

        assert result["status"] == "confirmation_required"
        assert result["resolved_slots"]["operation"] == operation
        assert result["resolved_slots"]["agenda_item_id"] == agenda_id
        assert result["writeback_plan"][0]["operation"] == expected_plan_operation
        assert result["writeback_plan"][0]["target"] == "agenda_items"
        assert result["writeback_plan"][0]["confirmation_required"] is False
        assert result["output"]["agenda_item"]["status"] == ("completed" if operation == "complete" else operation)


def test_agenda_outputs_duplicate_merge_conflict_and_fuzzy_notification_plans():
    result = run_agenda_pipeline(
        "agenda_pipeline",
        "周日继续聊发布计划",
        {
            "operation": "create",
            "title": "聊发布计划",
            "time_window": {"text": "周日", "type": "fuzzy"},
            "participants": ["me", "Alice"],
            "source_event_ids": ["evt-new"],
            "existing_agenda_candidates": [
                {
                    "agenda_item_id": "agenda-existing",
                    "title": "聊发布计划",
                    "time_window": {"text": "周日", "type": "fuzzy"},
                    "participants": ["Alice", "me"],
                    "source_event_ids": ["evt-old"],
                    "status": "open",
                }
            ],
            "same_time_agenda_items": [
                {"agenda_item_id": "agenda-existing", "title": "聊发布计划"},
                {"agenda_item_id": "agenda-other", "title": "家庭晚饭"},
            ],
        },
    )

    merge_plan = result["output"]["merge_plan"]
    assert merge_plan["decision"] == "duplicate"
    assert merge_plan["matched_item_id"] == "agenda-existing"
    assert merge_plan["source_event_ids"] == ["evt-new", "evt-old"]
    assert "title_time_participants_overlap" in merge_plan["reason"]

    conflict_plan = result["output"]["conflict_plan"]
    assert conflict_plan["conflict_type"] == "same_time_multiple_items"
    assert conflict_plan["conflicting_item_ids"] == ["agenda-existing", "agenda-other"]
    assert {option["action"] for option in conflict_plan["resolution_options"]} == {
        "keep_both",
        "merge_items",
        "reschedule_one",
    }

    notification_plan = result["output"]["notification_plan"]
    assert notification_plan["time_precision"] == "fuzzy"
    assert notification_plan["concrete_reminder"] is None
    assert {item["type"] for item in notification_plan["items"]} == {"clarification", "monitor"}
    assert result["writeback_plan"][0]["confirmation_required"] is False
    assert result["writeback_plan"][1]["target"] == "external_calendar"
    assert result["writeback_plan"][1]["operation"] == "propose_write"
    assert result["writeback_plan"][1]["confirmation_required"] is True


def test_agenda_outputs_reschedule_merge_and_precise_reminder_plan():
    result = run_agenda_pipeline(
        "agenda_pipeline",
        "把发布会改到明天 10:30",
        {
            "operation": "reschedule",
            "agenda_item_id": "agenda-7",
            "title": "发布会",
            "time_window": {"start": "2026-05-29T10:30:00+08:00", "type": "exact"},
            "participants": ["me", "Bob"],
            "source_event_ids": ["evt-reschedule"],
            "existing_agenda_candidates": [
                {
                    "agenda_item_id": "agenda-7",
                    "title": "发布会",
                    "time_window": {"start": "2026-05-28T15:00:00+08:00", "type": "exact"},
                    "participants": ["me", "Bob"],
                    "source_event_ids": ["evt-original"],
                    "status": "open",
                }
            ],
        },
    )

    assert result["output"]["merge_plan"]["decision"] == "reschedule"
    assert result["output"]["merge_plan"]["matched_item_id"] == "agenda-7"
    assert result["output"]["notification_plan"]["time_precision"] == "exact"
    assert result["output"]["notification_plan"]["concrete_reminder"]["time_window"] == {
        "start": "2026-05-29T10:30:00+08:00",
        "type": "exact",
    }
    assert result["output"]["conflict_plan"]["conflict_type"] == "none"


def test_task_todo_extracts_owner_due_sources_and_reminder_plan_without_external_write():
    result = run_agenda_pipeline(
        "task_todo_pipeline",
        "提醒我明天下午跟 Alice 确认合同",
        {
            "source_event_ids": ["evt-chat-1"],
            "owner": "me",
            "due_window": {"text": "明天下午", "type": "fuzzy"},
            "external_task_requested": True,
        },
    )

    assert result["pipeline_id"] == "task_todo_pipeline"
    assert result["status"] == "completed_read_only"
    assert result["resolved_slots"]["task_title"] == "跟 Alice 确认合同"
    assert result["resolved_slots"]["owner"] == "me"
    assert result["resolved_slots"]["due_window"] == {"text": "明天下午", "type": "fuzzy"}
    assert result["resolved_slots"]["source_event_ids"] == ["evt-chat-1"]
    assert result["output"]["todo_item"]["task_title"] == "跟 Alice 确认合同"
    assert result["output"]["reminder_plan"]["status"] == "planned_internal"
    assert result["writeback_plan"][0]["target"] == "internal_todos"
    assert result["writeback_plan"][0]["confirmation_required"] is False
    assert result["writeback_plan"][2]["target"] == "external_task_tool"
    assert result["writeback_plan"][2]["confirmation_required"] is True
    assert result["risk"]["confirmation_required"] is False


def test_task_todo_complete_cancel_reschedule_update_create_lifecycle_outputs():
    cases = [
        ("create", None, "open", None),
        ("update", "open", "open", None),
        ("complete", "open", "completed", None),
        ("cancel", "open", "cancelled", None),
        ("reschedule", "open", "open", "rescheduled"),
    ]

    for operation, previous_status, new_status, reminder_action in cases:
        result = run_agenda_pipeline(
            "task_todo_pipeline",
            "调整待办",
            {
                "operation": operation,
                "todo_item_id": f"todo-{operation}",
                "task_title": "确认合同",
                "owner": "me",
                "due_window": {"start": "2026-05-29T09:00:00+08:00", "type": "exact"},
                "previous_status": previous_status,
                "source_event_ids": [f"evt-{operation}"],
            },
        )

        lifecycle = result["output"]["todo_lifecycle"]
        assert lifecycle["previous_status"] == previous_status
        assert lifecycle["new_status"] == new_status
        assert lifecycle["source_event_ids"] == [f"evt-{operation}"]
        assert lifecycle["reason"] == f"{operation}_requested"
        assert result["resolved_slots"]["operation"] == operation
        assert result["writeback_plan"][0]["operation"] == operation
        if reminder_action:
            assert result["output"]["reminder_adjustment"]["action"] == reminder_action
            assert result["output"]["reminder_adjustment"]["due_window"] == {
                "start": "2026-05-29T09:00:00+08:00",
                "type": "exact",
            }
        else:
            assert result["output"]["reminder_adjustment"] is None


def test_proactive_route_suggestion_card_has_expected_actions_risks_and_cooldown_metadata():
    result = run_agenda_pipeline(
        "proactive_suggestion_pipeline",
        "会议地点在武康路，可能需要出发提醒",
        {
            "candidate_type": "route_need",
            "source_event_ids": ["evt-meeting-place"],
            "destination": "武康路",
            "cooldown": {"key": "route_need:evt-meeting-place", "seconds_remaining": 900},
            "dedupe": {"key": "route_need:evt-meeting-place", "matched_existing": False},
        },
    )

    assert result["pipeline_id"] == "proactive_suggestion_pipeline"
    assert result["status"] == "draft_ready"
    assert result["resolved_slots"]["candidate_type"] == "route_need"
    assert result["resolved_slots"]["source_event_ids"] == ["evt-meeting-place"]
    assert "武康路" in result["output"]["suggestion_card"]["title"]
    actions = {action["label"]: action for action in result["output"]["suggestion_card"]["actions"]}
    assert set(actions) == {"查路线", "帮我打车", "稍后提醒"}
    assert actions["查路线"]["risk"]["permission"] == "read_only"
    assert actions["查路线"]["risk"]["confirmation_required"] is False
    assert actions["帮我打车"]["risk"]["permission"] == "payment_or_purchase"
    assert actions["帮我打车"]["risk"]["final_user_confirmation"] is True
    assert actions["稍后提醒"]["risk"]["permission"] == "write"
    assert actions["稍后提醒"]["risk"]["confirmation_required"] is False
    assert result["output"]["cooldown"]["seconds_remaining"] == 900
    assert result["output"]["dedupe"]["matched_existing"] is False


def test_proactive_suggestion_suppresses_duplicate_or_cooldown_and_keeps_action_targets():
    duplicate = run_agenda_pipeline(
        "proactive_suggestion_pipeline",
        "会议地点在武康路，可能需要出发提醒",
        {
            "candidate_type": "route_need",
            "source_event_ids": ["evt-meeting-place"],
            "destination": "武康路",
            "feedback_history": [{"candidate_type": "route_need", "feedback": "dismissed"}],
            "recent_suggestions": [{"dedupe_key": "route_need:evt-meeting-place"}],
            "dedupe": {"matched_existing": True},
        },
    )

    assert duplicate["status"] == "suppressed"
    assert duplicate["output"]["delivery_decision"] == {
        "deliver": False,
        "suppress_reason": "duplicate",
    }
    assert duplicate["output"]["notification_payload"]["bubble_text"]
    assert duplicate["output"]["notification_payload"]["deep_link_tab"] == "proactive"
    assert {
        action["target_pipeline"] for action in duplicate["output"]["notification_payload"]["actions"]
    } == {"route_pipeline", "ride_pipeline", "task_todo_pipeline"}
    assert duplicate["output"]["learning_signal"]["negative_feedback_count"] == 1

    cooldown = run_agenda_pipeline(
        "proactive_suggestion_pipeline",
        "会议地点在武康路，可能需要出发提醒",
        {
            "candidate_type": "route_need",
            "source_event_ids": ["evt-meeting-place-2"],
            "destination": "武康路",
            "cooldown_seconds_remaining": 120,
            "dedupe": {"matched_existing": False},
        },
    )

    assert cooldown["status"] == "suppressed"
    assert cooldown["output"]["delivery_decision"] == {
        "deliver": False,
        "suppress_reason": "cooldown_active",
    }
    assert cooldown["output"]["cooldown"]["seconds_remaining"] == 120


def test_returns_none_for_unowned_pipeline_id():
    assert run_agenda_pipeline("route_pipeline", "查路线去武康路", {}) is None
