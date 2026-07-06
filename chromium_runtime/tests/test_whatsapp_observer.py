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


def test_extract_whatsapp_chat_context_identifies_open_chat_without_contact_hint():
    from app.runtime import extract_whatsapp_chat_context

    lines = [
        "1",
        "所有",
        "未读",
        "1",
        "特别关注",
        "群组",
        "消息通知已关闭。 开启",
        "大刚",
        "11:30",
        "哈哈哈今天太阳真大。 测试码N1",
        "2条未读消息",
        "+86 137 5203 1655",
        "星期一",
        "NOMI_REG_WA_0629 明天15:30人民广场见，带合同",
        "2",
        "陈子扬",
        "2026年5月25日",
        "测试",
        "你的私人消息已进行端到端加密",
        "大刚",
        "今天",
        "消息和通话已进行端到端加密。只有此聊天中的成员可以查看、收听或分享。点击了解更多",
        "你好呀",
        "07:53",
        "请记住：我的测试暗号是海盐拿铁。 测试码P1",
        "11:29",
    ]

    context = extract_whatsapp_chat_context(lines)

    assert context["chat_name"] == "大刚"
    assert context["source_kind"] == "direct"


def test_split_whatsapp_open_chat_transcript_from_full_page_text():
    from app.runtime import extract_whatsapp_chat_context, split_whatsapp_open_chat_transcript

    lines = [
        "1",
        "所有",
        "未读",
        "1",
        "特别关注",
        "群组",
        "消息通知已关闭。 开启",
        "大刚",
        "11:30",
        "哈哈哈今天太阳真大。 测试码N1",
        "2条未读消息",
        "+86 137 5203 1655",
        "星期一",
        "NOMI_REG_WA_0629 明天15:30人民广场见，带合同",
        "2",
        "陈子扬",
        "2026年5月25日",
        "测试",
        "你的私人消息已进行端到端加密",
        "大刚",
        "今天",
        "消息和通话已进行端到端加密。只有此聊天中的成员可以查看、收听或分享。点击了解更多",
        "你好呀",
        "07:53",
        "请记住：我的测试暗号是海盐拿铁。 测试码P1",
        "11:29",
        "明天下午3点半在人民广场见，带合同。 测试码M1",
        "11:29",
        "周五18点前把报价单发我，记得核对成本和利润率。 测试码T1",
        "11:29",
        "哈哈哈今天太阳真大。 测试码N1",
        "11:30",
        "输入消息",
    ]

    messages = split_whatsapp_open_chat_transcript(
        lines,
        captured_at="2026-07-01T12:20:00+00:00",
        chat_context=extract_whatsapp_chat_context(lines),
        capture_scope="history_scroll_sync",
        limit=120,
    )

    assert [message["message"] for message in messages] == [
        "你好呀",
        "请记住：我的测试暗号是海盐拿铁。 测试码P1",
        "明天下午3点半在人民广场见，带合同。 测试码M1",
        "周五18点前把报价单发我，记得核对成本和利润率。 测试码T1",
        "哈哈哈今天太阳真大。 测试码N1",
    ]
    assert all(message["sender"] == "大刚" for message in messages)
    assert all(message["chat_name"] == "大刚" for message in messages)


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


def test_build_whatsapp_open_latest_chat_script_targets_chat_list_rows():
    from app.runtime import build_whatsapp_open_latest_chat_script

    script = build_whatsapp_open_latest_chat_script()

    assert "#pane-side" in script
    assert '[role="row"]' in script
    assert "__parLastAutoOpenedWhatsAppChatAt" in script
    assert "row.click()" in script
    assert "输入消息" in script


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


def test_emit_whatsapp_list_previews_accepts_weekday_timestamp(monkeypatch):
    import asyncio
    from app import runtime

    emitted = []

    async def fake_emit_event(client, source, event_type, payload):
        emitted.append((source, event_type, payload))

    monkeypatch.setattr(runtime, "emit_event", fake_emit_event)

    lines = [
        "1",
        "All",
        "Unread",
        "1",
        "Favorites",
        "Groups",
        "Message notifications are off.\u00a0Turn on",
        "2 unread messages",
        "+86 137 5203 1655",
        "Monday",
        "NOMI_REG_WA_0629 明天15:30人民广场见，带合同",
        "2",
    ]

    asyncio.run(runtime.emit_whatsapp_list_previews(None, lines, "https://web.whatsapp.com/", "(1) WhatsApp"))

    assert emitted == [
        (
            "whatsapp",
            "whatsapp_message",
            {
                "sender": "+86 137 5203 1655",
                "chat_name": None,
                "source_kind": "unknown",
                "message_direction": "unknown",
                "message": "NOMI_REG_WA_0629 明天15:30人民广场见，带合同",
                "timestamp_label": "Monday",
                "capture_scope": "chat_list_preview",
                "url": "https://web.whatsapp.com/",
                "title": "(1) WhatsApp",
            },
        )
    ]


def test_emit_whatsapp_list_previews_rejects_ui_words_as_timestamp_labels(monkeypatch):
    import asyncio
    from app import runtime

    emitted = []

    async def fake_emit_event(client, source, event_type, payload):
        emitted.append((source, event_type, payload))

    monkeypatch.setattr(runtime, "emit_event", fake_emit_event)

    lines = [
        "Alice",
        "日程",
        "NOMI_REG_WA_0629 明天15:30人民广场见，带合同",
        "Bob",
        "任务",
        "请记得带合同",
    ]

    asyncio.run(runtime.emit_whatsapp_list_previews(None, lines, "https://web.whatsapp.com/", "WhatsApp"))

    assert emitted == []


def test_emit_whatsapp_list_previews_skips_open_chat_transcript(monkeypatch):
    import asyncio
    from app import runtime

    emitted = []

    async def fake_emit_event(client, source, event_type, payload):
        emitted.append((source, event_type, payload))

    monkeypatch.setattr(runtime, "emit_event", fake_emit_event)

    lines = [
        "大刚",
        "消息和通话已进行端到端加密。只有此聊天中的成员可以查看、收听或分享。",
        "你好呀",
        "07:53",
        "请记住：我的测试暗号是海盐拿铁。 测试码P1",
        "11:29",
        "明天下午3点半在人民广场见，带合同。 测试码M1",
        "11:29",
        "周五18点前把报价单发我，记得核对成本和利润率。 测试码T1",
        "11:29",
        "哈哈哈今天太阳真大。 测试码N1",
        "11:30",
        "输入消息",
    ]

    asyncio.run(runtime.emit_whatsapp_list_previews(None, lines, "https://web.whatsapp.com/", "(1) WhatsApp"))

    assert emitted == []


def test_normalize_whatsapp_observer_records_splits_open_chat_transcript_and_filters_ui_noise():
    from app.runtime import normalize_whatsapp_observer_records

    records = [
        {
            "text": "\n".join(
                [
                    "大刚",
                    "消息和通话已进行端到端加密。只有此聊天中的成员可以查看、收听或分享。点击了解更多",
                    "你好呀",
                    "07:53",
                    "请记住：我的测试暗号是海盐拿铁。 测试码P1",
                    "11:29",
                    "明天下午3点半在人民广场见，带合同。 测试码M1",
                    "11:29",
                    "周五18点前把报价单发我，记得核对成本和利润率。 测试码T1",
                    "11:29",
                    "哈哈哈今天太阳真大。 测试码N1",
                    "11:30",
                    "输入消息",
                ]
            ),
            "captured_at": "2026-07-01T11:38:00+00:00",
        }
    ]

    messages = normalize_whatsapp_observer_records(records)

    assert [message["message"] for message in messages] == [
        "你好呀",
        "请记住：我的测试暗号是海盐拿铁。 测试码P1",
        "明天下午3点半在人民广场见，带合同。 测试码M1",
        "周五18点前把报价单发我，记得核对成本和利润率。 测试码T1",
        "哈哈哈今天太阳真大。 测试码N1",
    ]
    assert all(message["sender"] == "大刚" for message in messages)
    assert all(message["capture_scope"] == "mutation_observer" for message in messages)
