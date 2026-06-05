import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_channel_inputs_normalize_to_same_private_event_shape():
    from app.private_events import normalize_private_event

    inputs = [
        ("gmail", {"message_id": "gmail-1", "thread_id": "thread-a", "from": "alice@example.com", "to": ["me@example.com"], "text": "周五 18:00 前确认报价。"}),
        ("whatsapp", {"message_id": "wa-1", "chat_id": "chat-a", "sender": "Alice", "text": "周五 18:00 前确认报价。"}),
        ("telegram", {"message_id": "tg-1", "chat_id": "chat-a", "sender": "Alice", "text": "周五 18:00 前确认报价。"}),
        ("browser", {"page_session_id": "page-1", "url": "https://example.com", "title": "订单", "visible_text": "订单需要今天付款。"}),
        ("nomi_chat", {"turn_id": "turn-1", "conversation_id": "conv-1", "role": "user", "content": "提醒我核对利润率。"}),
    ]

    envelopes = [normalize_private_event(source, payload, source_account_id="local-1") for source, payload in inputs]
    key_sets = [set(envelope.keys()) for envelope in envelopes]

    assert all(keys == key_sets[0] for keys in key_sets)
    assert {envelope["source_type"] for envelope in envelopes} == {"gmail", "whatsapp", "telegram", "browser", "nomi_chat"}
    assert all(envelope["event_id"].startswith("evt_") for envelope in envelopes)
    assert all(envelope["dedupe_hash"] for envelope in envelopes)
    assert envelopes[0]["conversation_id"] == "thread-a"
    assert envelopes[1]["conversation_id"] == "chat-a"
    assert envelopes[4]["text"] == "提醒我核对利润率。"


def test_private_event_dedupe_hash_is_stable_and_scope_sensitive():
    from app.private_events import normalize_private_event

    first = normalize_private_event(
        "whatsapp",
        {"message_id": "m1", "chat_id": "chat-a", "sender": "Alice", "text": "明天 4 点见。"},
        source_account_id="account-a",
    )
    duplicate = normalize_private_event(
        "whatsapp",
        {"message_id": "m1", "chat_id": "chat-a", "sender": "Alice", "text": "明天 4 点见。"},
        source_account_id="account-a",
    )
    other_chat = normalize_private_event(
        "whatsapp",
        {"message_id": "m1", "chat_id": "chat-b", "sender": "Alice", "text": "明天 4 点见。"},
        source_account_id="account-a",
    )

    assert first["dedupe_hash"] == duplicate["dedupe_hash"]
    assert first["dedupe_hash"] != other_chat["dedupe_hash"]


def test_dedupe_index_accepts_first_event_and_rejects_duplicate():
    from app.private_events import PrivateEventDedupeIndex, normalize_private_event

    index = PrivateEventDedupeIndex()
    event = normalize_private_event("gmail", {"message_id": "g1", "thread_id": "t1", "text": "需要付款"}, source_account_id="local")

    assert index.accept(event) is True
    assert index.accept(dict(event)) is False
    assert index.duplicate_of(event) == event["event_id"]


def test_private_event_gateway_schema_sql_creates_source_tables():
    from app.private_events import private_event_gateway_schema_sql

    combined = "\n".join(" ".join(sql.split()) for sql in private_event_gateway_schema_sql())

    assert "CREATE TABLE IF NOT EXISTS source_events" in combined
    assert "CREATE TABLE IF NOT EXISTS source_cursors" in combined
    assert "source_events_dedupe_idx" in combined
