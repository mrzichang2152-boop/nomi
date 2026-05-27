import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_parse_calendar_visible_events_extracts_time_title_and_date_context():
    from app.runtime import parse_calendar_visible_events

    lines = [
        "Google Calendar",
        "2026年5月26日星期二",
        "全天",
        "09:30",
        "10:00",
        "和 Alex 开产品评审会",
        "11:00",
        "12:00",
        "云服务器续费提醒",
        "创建",
    ]

    events = parse_calendar_visible_events(lines)

    assert events == [
        {
            "date_context": "2026年5月26日星期二",
            "start_time": "09:30",
            "end_time": "10:00",
            "title": "和 Alex 开产品评审会",
            "capture_scope": "calendar_visible",
        },
        {
            "date_context": "2026年5月26日星期二",
            "start_time": "11:00",
            "end_time": "12:00",
            "title": "云服务器续费提醒",
            "capture_scope": "calendar_visible",
        },
    ]


def test_parse_calendar_visible_events_skips_ui_and_deduplicates():
    from app.runtime import parse_calendar_visible_events

    lines = [
        "今天",
        "09:30",
        "10:00",
        "搜索",
        "09:30",
        "10:00",
        "和 Alex 开产品评审会",
        "09:30",
        "10:00",
        "和 Alex 开产品评审会",
    ]

    events = parse_calendar_visible_events(lines)

    assert len(events) == 1
    assert events[0]["title"] == "和 Alex 开产品评审会"
