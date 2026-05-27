import sys
from pathlib import Path


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
