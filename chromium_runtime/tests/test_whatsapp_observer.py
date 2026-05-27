import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_build_whatsapp_observer_script_installs_mutation_observer_queue():
    from app.runtime import build_whatsapp_observer_script

    script = build_whatsapp_observer_script()

    assert "MutationObserver" in script
    assert "__parWhatsAppObserverInstalled" in script
    assert "__parWhatsAppNewMessages" in script


def test_normalize_whatsapp_observer_records_extracts_structured_messages():
    from app.runtime import normalize_whatsapp_observer_records

    records = [
        {
            "text": "陈子扬\n09:42\n测试新消息",
            "captured_at": "2026-05-26T09:42:00+00:00",
        },
        {
            "text": "开启后台同步\n在后台同步消息，获享更快的性能。",
            "captured_at": "2026-05-26T09:43:00+00:00",
        },
    ]

    messages = normalize_whatsapp_observer_records(records)

    assert messages == [
        {
            "sender": "陈子扬",
            "chat_name": None,
            "source_kind": "unknown",
            "participants": [],
            "message_direction": "incoming",
            "timestamp_label": "09:42",
            "message": "测试新消息",
            "captured_at": "2026-05-26T09:42:00+00:00",
            "capture_scope": "mutation_observer",
        }
    ]


def test_extract_whatsapp_chat_context_identifies_open_chat_and_group_members():
    from app.runtime import extract_whatsapp_chat_context

    lines = [
        "WhatsApp",
        "PAR Dev Group",
        "点击此处查看联系人信息",
        "Alice, Bob, Chen",
        "昨天",
        "测试消息",
    ]

    context = extract_whatsapp_chat_context(lines)

    assert context == {
        "chat_name": "PAR Dev Group",
        "source_kind": "group",
        "participants": ["Alice", "Bob", "Chen"],
    }


def test_normalize_whatsapp_observer_records_includes_chat_context_and_direction():
    from app.runtime import normalize_whatsapp_observer_records

    messages = normalize_whatsapp_observer_records(
        [
            {
                "text": "陈子扬\n09:42\n测试新消息",
                "captured_at": "2026-05-26T09:42:00+00:00",
            }
        ],
        chat_context={"chat_name": "陈子扬", "source_kind": "direct", "participants": []},
    )

    assert messages[0]["chat_name"] == "陈子扬"
    assert messages[0]["source_kind"] == "direct"
    assert messages[0]["message_direction"] == "incoming"


def test_build_whatsapp_history_sync_script_scrolls_and_queues_visible_messages():
    from app.runtime import build_whatsapp_history_sync_script

    script = build_whatsapp_history_sync_script(max_records=80)

    assert "__parWhatsAppHistorySyncInstalled" in script
    assert "__parWhatsAppHistoryMessages" in script
    assert "scrollTop" in script
    assert "MutationObserver" not in script


def test_normalize_whatsapp_history_records_deduplicates_and_marks_scope():
    from app.runtime import normalize_whatsapp_history_records

    records = normalize_whatsapp_history_records(
        [
            {"text": "陈子扬\n09:42\n历史消息一", "captured_at": "2026-05-26T09:42:00+00:00"},
            {"text": "陈子扬\n09:42\n历史消息一", "captured_at": "2026-05-26T09:42:01+00:00"},
            {"text": "Alice\n昨天\n历史消息二", "captured_at": "2026-05-26T09:43:00+00:00"},
        ],
        chat_context={"chat_name": "PAR Dev Group", "source_kind": "group", "participants": ["Alice", "陈子扬"]},
    )

    assert len(records) == 2
    assert records[0]["capture_scope"] == "history_scroll_sync"
    assert records[0]["chat_name"] == "PAR Dev Group"
    assert records[0]["message"] == "历史消息一"
    assert records[1]["timestamp_label"] == "昨天"
