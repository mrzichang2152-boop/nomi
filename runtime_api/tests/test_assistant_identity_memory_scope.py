import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_private_event_normalizes_assistant_owned_sources_separately():
    from app.private_events import normalize_private_event

    gmail = normalize_private_event(
        "assistant_gmail",
        {
            "message_id": "g1",
            "thread_id": "thread-a",
            "from": "alice@example.com",
            "to": ["nomi@example.com"],
            "body": "请让张子长回我电话。",
            "assistant_identity_id": "nomi_gmail_primary",
        },
        source_account_id="nomi_gmail_primary",
    )
    whatsapp = normalize_private_event(
        "assistant_whatsapp",
        {
            "wamid": "w1",
            "from": "+15551234567",
            "text": "请让张子长回我电话。",
            "assistant_identity_id": "nomi_whatsapp_primary",
        },
        source_account_id="nomi_whatsapp_primary",
    )

    assert gmail["source_type"] == "assistant_gmail"
    assert whatsapp["source_type"] == "assistant_whatsapp"
    assert gmail["visibility_scope"] == "assistant_identity_thread"
    assert whatsapp["visibility_scope"] == "assistant_identity_thread"
    assert gmail["source_account_id"] != "local_account"
    assert whatsapp["source_account_id"] != "local_account"


def test_assistant_event_private_payload_preserves_identity_and_classification():
    from app.assistant_identity.api import normalized_assistant_event_to_private_payload

    payload = normalized_assistant_event_to_private_payload(
        {
            "source_type": "assistant_gmail",
            "event_type": "assistant_email_received",
            "identity_id": "nomi_gmail_primary",
            "classification": "external_contact_message",
            "conversation_id": "gmail-thread-1",
            "external_message_id": "gmail-msg-1",
            "normalized_text": "请让张子长回我电话。",
            "normalized_payload": {"subject": "回电", "body_text": "请让张子长回我电话。"},
            "memory_scope": {
                "visibility_scope": "assistant_identity_thread",
                "counterparty_scope": "contact_maya",
            },
        }
    )

    assert payload["source"] == "assistant_gmail"
    assert payload["event_type"] == "assistant_email_received"
    assert payload["raw_data"]["assistant_identity_id"] == "nomi_gmail_primary"
    assert payload["raw_data"]["classification"] == "external_contact_message"
    assert payload["raw_data"]["visibility_scope"] == "assistant_identity_thread"
    assert payload["raw_data"]["counterparty_scope"] == "contact_maya"


def test_private_event_normalizes_assistant_phone_separately():
    from app.private_events import normalize_private_event

    sms = normalize_private_event(
        "assistant_phone",
        {
            "provider_message_id": "sms-1",
            "from": "+15551234567",
            "to": "+15550000000",
            "body_text": "请让张子长今天回我电话。",
            "assistant_identity_id": "nomi_phone_primary",
        },
        source_account_id="nomi_phone_primary",
    )

    assert sms["source_type"] == "assistant_phone"
    assert sms["source_account_id"] == "nomi_phone_primary"
    assert sms["visibility_scope"] == "assistant_identity_thread"
    assert sms["conversation_id"].startswith("+15551234567") or sms["conversation_id"].startswith("phone:")


def test_assistant_phone_event_private_payload_preserves_call_status():
    from app.assistant_identity.api import normalized_assistant_event_to_private_payload

    payload = normalized_assistant_event_to_private_payload(
        {
            "source_type": "assistant_phone",
            "event_type": "assistant_inbound_call_received",
            "identity_id": "nomi_phone_primary",
            "classification": "provider_status",
            "conversation_id": "phone:hash1",
            "external_message_id": "call-1",
            "normalized_text": "",
            "normalized_payload": {
                "call_direction": "inbound",
                "status": "answered_with_greeting",
                "from": "+15551234567",
            },
            "memory_scope": {
                "visibility_scope": "assistant_identity_thread",
                "counterparty_scope": "contact_maya",
            },
        }
    )

    assert payload["source"] == "assistant_phone"
    assert payload["raw_data"]["assistant_identity_id"] == "nomi_phone_primary"
    assert payload["raw_data"]["status"] == "answered_with_greeting"
    assert payload["raw_data"]["call_direction"] == "inbound"
