import sys
from pathlib import Path
import asyncio


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_parse_telegram_visible_chats_extracts_chat_preview_and_time():
    from app.runtime import parse_telegram_visible_chats

    lines = [
        "Telegram",
        "Search",
        "Alice",
        "09:42",
        "Can we move the meeting to Friday?",
        "PAR Dev Group",
        "Yesterday",
        "Bob: vector search test passed",
    ]

    chats = parse_telegram_visible_chats(lines)

    assert chats == [
        {
            "chat_name": "Alice",
            "timestamp_label": "09:42",
            "message": "Can we move the meeting to Friday?",
            "capture_scope": "telegram_visible_preview",
        },
        {
            "chat_name": "PAR Dev Group",
            "timestamp_label": "Yesterday",
            "message": "Bob: vector search test passed",
            "capture_scope": "telegram_visible_preview",
        },
    ]


def test_parse_telegram_visible_chats_skips_ui_and_deduplicates():
    from app.runtime import parse_telegram_visible_chats

    lines = [
        "Search",
        "Archived Chats",
        "Alice",
        "09:42",
        "Can we move the meeting to Friday?",
        "Alice",
        "09:42",
        "Can we move the meeting to Friday?",
    ]

    chats = parse_telegram_visible_chats(lines)

    assert len(chats) == 1
    assert chats[0]["chat_name"] == "Alice"


def test_parse_telegram_visible_chats_accepts_month_day_timestamp():
    from app.runtime import parse_telegram_visible_chats

    lines = [
        "Search",
        "Maya",
        "Jun 2",
        "The interview prep notes look good.",
    ]

    chats = parse_telegram_visible_chats(lines)

    assert chats == [
        {
            "chat_name": "Maya",
            "timestamp_label": "Jun 2",
            "message": "The interview prep notes look good.",
            "capture_scope": "telegram_visible_preview",
        }
    ]


def test_parse_telegram_visible_chats_extracts_preview_first_top_chat_layout():
    from app.runtime import parse_telegram_visible_chats

    lines = [
        "",
        "Search",
        "Never miss a message!",
        "Enable notifications to stay updated.",
        "NOMI_REG_WA_0629 明天15:30人民广场见，带合同",
        "2",
        "Ask",
        "Mon",
        "A",
        "Ricardo Logan",
        "Jun 26",
        "RL",
    ]

    chats = parse_telegram_visible_chats(lines)

    assert chats[0] == {
        "chat_name": "Ask",
        "timestamp_label": "Mon",
        "message": "NOMI_REG_WA_0629 明天15:30人民广场见，带合同",
        "capture_scope": "telegram_visible_preview",
    }


def test_parse_telegram_visible_chats_skips_open_chat_message_time_chain():
    from app.runtime import parse_telegram_visible_chats

    lines = [
        "Ask",
        "last seen yesterday at 10:22",
        "June 29",
        "NOMI_REG_TG_0629 周五10点静安寺地铁站见 Maya",
        "10:22",
        "NOMI_REG_WA_0629 明天15:30人民广场见，带合同",
        "10:22",
    ]

    chats = parse_telegram_visible_chats(lines)

    assert chats == []


def test_parse_telegram_visible_chats_skips_private_use_icon_preview():
    from app.runtime import parse_telegram_visible_chats

    lines = [
        "NOMI_REG_WA_0629 明天15:30人民广场见，带合同",
        "10:22",
        "",
    ]

    chats = parse_telegram_visible_chats(lines)

    assert chats == []


def test_parse_telegram_open_chat_messages_extracts_visible_chat_body():
    from app.runtime import parse_telegram_open_chat_messages

    lines = [
        "Maya",
        "last seen recently",
        "Tue, Jun 30",
        "NOMI_REG_TG_0629 周五10点静安寺地铁站见 Maya",
        "16:31",
        "Search",
        "Mute",
    ]

    messages = parse_telegram_open_chat_messages(lines)

    assert messages == [
        {
            "chat_name": "Maya",
            "message": "NOMI_REG_TG_0629 周五10点静安寺地铁站见 Maya",
            "capture_scope": "telegram_open_chat_message",
        }
    ]


def test_parse_telegram_open_chat_messages_accepts_date_separator_before_message():
    from app.runtime import parse_telegram_open_chat_messages

    lines = [
        "Ask",
        "last seen yesterday at 10:22",
        "Phone number",
        "Registration date",
        "China",
        "July 2021",
        "June 29",
        "NOMI_REG_TG_0629 周五10点静安寺地铁站见 Maya",
        "10:22",
        "NOMI_REG_WA_0629 明天15:30人民广场见，带合同",
        "10:22",
    ]

    messages = parse_telegram_open_chat_messages(lines)

    assert messages[:2] == [
        {
            "chat_name": "Ask",
            "message": "NOMI_REG_TG_0629 周五10点静安寺地铁站见 Maya",
            "capture_scope": "telegram_open_chat_message",
        },
        {
            "chat_name": "Ask",
            "message": "NOMI_REG_WA_0629 明天15:30人民广场见，带合同",
            "capture_scope": "telegram_open_chat_message",
        },
    ]


def test_detect_telegram_open_chat_profile_with_phone_number_is_logged_in():
    from app.runtime import detect_browser_login_state

    state = detect_browser_login_state(
        "telegram",
        "https://web.telegram.org/k/#@yshucheng",
        "Telegram Web",
        [
            "Search",
            "Ask",
            "last seen yesterday at 10:22",
            "Phone number",
            "Registration date",
            "June 29",
            "NOMI_REG_TG_0629 周五10点静安寺地铁站见 Maya",
            "10:22",
            "Message",
        ],
    )

    assert state["login_state"] == "logged_in"


def test_collect_telegram_emits_open_chat_messages_even_when_preview_parser_has_sidebar(monkeypatch):
    from app import runtime

    emitted = []
    health = []

    async def fake_emit_event(client, source, event_type, raw_data):
        emitted.append((source, event_type, raw_data))

    async def fake_report_health(client, collector, status, details):
        health.append((collector, status, details))

    class Locator:
        async def inner_text(self, timeout):
            return "\n".join(
                [
                    "Search",
                    "Ask",
                    "Mon",
                    "A",
                    "Maya",
                    "last seen recently",
                    "Tue, Jun 30",
                    "NOMI_REG_TG_0629 周五10点静安寺地铁站见 Maya",
                    "16:31",
                ]
            )

    class Page:
        url = "https://web.telegram.org/k/#@maya"

        async def title(self):
            return "Telegram Web"

        def locator(self, selector):
            assert selector == "body"
            return Locator()

    monkeypatch.setattr(runtime, "emit_event", fake_emit_event)
    monkeypatch.setattr(runtime, "report_health", fake_report_health)

    asyncio.run(runtime.collect_telegram(object(), Page()))

    event_types = [event_type for _, event_type, _ in emitted]
    assert event_types == ["telegram_message_preview", "telegram_message_preview"]
    open_chat = emitted[1][2]
    assert open_chat["capture_scope"] == "telegram_open_chat_message"
    assert open_chat["chat_name"] == "Maya"
    assert open_chat["message"] == "NOMI_REG_TG_0629 周五10点静安寺地铁站见 Maya"
    assert health[-1][2]["open_chat_message_count"] == 1


def test_collect_telegram_emits_visible_snapshot_when_preview_parser_misses_logged_in_page(monkeypatch):
    from app import runtime

    emitted = []
    health = []

    async def fake_emit_event(client, source, event_type, raw_data):
        emitted.append((source, event_type, raw_data))

    async def fake_report_health(client, collector, status, details):
        health.append((collector, status, details))

    class Locator:
        async def inner_text(self, timeout):
            return "\n".join(
                [
                    "",
                    "",
                    "Never miss a message!",
                    "Enable notifications to stay updated.",
                    "Telegram sent you a gift for $1.19",
                    "1",
                    "Jun 2",
                    "last seen yesterday at 09:55",
                ]
            )

    class Page:
        url = "https://web.telegram.org/k/"

        async def title(self):
            return "Telegram Web"

        def locator(self, selector):
            assert selector == "body"
            return Locator()

    monkeypatch.setattr(runtime, "emit_event", fake_emit_event)
    monkeypatch.setattr(runtime, "report_health", fake_report_health)

    asyncio.run(runtime.collect_telegram(object(), Page()))

    assert [event_type for _, event_type, _ in emitted] == ["telegram_visible_snapshot"]
    snapshot = emitted[0][2]
    assert snapshot["capture_scope"] == "telegram_visible_snapshot"
    assert snapshot["parsed_preview_count"] == 0
    assert snapshot["login_state"] == "logged_in"
    assert "Telegram sent you a gift for $1.19" in snapshot["visible_text"]
    assert health[-1][0] == "telegram"
    assert health[-1][1] == "healthy"
    assert health[-1][2]["snapshot_collected"] is True
    assert health[-1][2]["preview_count"] == 0
