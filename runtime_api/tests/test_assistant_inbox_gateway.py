import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_user_gmail_to_nomi_becomes_user_direct_command():
    from app.assistant_identity.contact_resolver import ContactResolver
    from app.assistant_identity.inbox_gateway import AssistantInboxGateway

    gateway = AssistantInboxGateway(ContactResolver(user_keys={"owner@example.com"}))

    event = gateway.normalize_gmail(
        identity_id="nomi_gmail_primary",
        message={
            "id": "gmail-1",
            "thread_id": "thread-1",
            "from": "owner@example.com",
            "to": ["nomi@example.com"],
            "subject": "帮我处理",
            "body": "帮我问 Alice 明天几点见。",
            "date": "2026-06-04T12:00:00Z",
        },
    )

    assert event["classification"] == "user_direct_command"
    assert event["source_type"] == "assistant_gmail"
    assert event["conversation_id"] == "thread-1"
    assert event["normalized_text"] == "帮我问 Alice 明天几点见。"
    assert event["memory_scope"]["visibility_scope"] == "assistant_identity_thread"


def test_known_external_whatsapp_sender_creates_inbox_suggestion_channel():
    from app.assistant_identity.contact_resolver import ContactResolver
    from app.assistant_identity.inbox_gateway import AssistantInboxGateway

    gateway = AssistantInboxGateway(
        ContactResolver(known_contacts={"+15551234567": "contact_maya"})
    )

    event = gateway.normalize_whatsapp(
        identity_id="nomi_whatsapp_primary",
        payload={
            "wamid": "wamid-1",
            "from": "+15551234567",
            "text": "请让张子长今天回我电话。",
            "timestamp": "2026-06-04T12:05:00Z",
        },
    )

    assert event["classification"] == "external_contact_message"
    assert event["suggestion_channel"] == "assistant_channel_external_contact"
    assert event["sender"]["contact_id"] == "contact_maya"
    assert event["memory_scope"]["counterparty_scope"] == "contact_maya"


def test_unknown_sender_goes_to_low_trust_inbox():
    from app.assistant_identity.contact_resolver import ContactResolver
    from app.assistant_identity.inbox_gateway import AssistantInboxGateway

    gateway = AssistantInboxGateway(ContactResolver())

    event = gateway.normalize_whatsapp(
        identity_id="nomi_whatsapp_primary",
        payload={"wamid": "wamid-2", "from": "+19990001111", "text": "hello"},
    )

    assert event["classification"] == "unknown_sender"
    assert event["suggestion_channel"] == "assistant_channel_unknown_sender"
    assert event["memory_scope"]["visibility_scope"] == "low_trust_assistant_inbox"


def test_user_sms_to_nomi_phone_becomes_user_direct_command():
    from app.assistant_identity.contact_resolver import ContactResolver
    from app.assistant_identity.inbox_gateway import AssistantInboxGateway

    gateway = AssistantInboxGateway(ContactResolver(user_keys={"+15550000000"}))

    event = gateway.normalize_sms(
        identity_id="nomi_phone_primary",
        payload={
            "provider_message_id": "sms-1",
            "from": "+15550000000",
            "to": "+15551112222",
            "body": "Nomi，帮我查一下报价。",
            "timestamp": "2026-06-05T12:00:00Z",
        },
    )

    assert event["source_type"] == "assistant_phone"
    assert event["event_type"] == "assistant_sms_received"
    assert event["classification"] == "user_direct_command"
    assert event["conversation_id"].startswith("sms:")
    assert event["normalized_text"] == "Nomi，帮我查一下报价。"
    assert event["memory_scope"]["visibility_scope"] == "assistant_identity_thread"


def test_known_external_sms_to_nomi_phone_creates_suggestion_channel():
    from app.assistant_identity.contact_resolver import ContactResolver
    from app.assistant_identity.inbox_gateway import AssistantInboxGateway

    gateway = AssistantInboxGateway(
        ContactResolver(known_contacts={"+15551234567": "contact_maya"})
    )

    event = gateway.normalize_sms(
        identity_id="nomi_phone_primary",
        payload={
            "provider_message_id": "sms-2",
            "from": "+15551234567",
            "body": "请让张子长今天回我电话。",
            "timestamp": "2026-06-05T12:01:00Z",
        },
    )

    assert event["classification"] == "external_contact_message"
    assert event["suggestion_channel"] == "assistant_channel_external_contact"
    assert event["sender"]["contact_id"] == "contact_maya"
    assert event["memory_scope"]["counterparty_scope"] == "contact_maya"


def test_inbound_phone_call_to_nomi_phone_is_auditable_status_event():
    from app.assistant_identity.contact_resolver import ContactResolver
    from app.assistant_identity.inbox_gateway import AssistantInboxGateway

    gateway = AssistantInboxGateway(
        ContactResolver(known_contacts={"+15551234567": "contact_maya"})
    )

    event = gateway.normalize_phone_call(
        identity_id="nomi_phone_primary",
        payload={
            "provider_call_id": "call-1",
            "from": "+15551234567",
            "direction": "inbound",
            "status": "answered_with_greeting",
            "timestamp": "2026-06-05T12:02:00Z",
        },
    )

    assert event["source_type"] == "assistant_phone"
    assert event["event_type"] == "assistant_inbound_call_received"
    assert event["classification"] == "provider_status"
    assert event["normalized_payload"]["call_direction"] == "inbound"
    assert event["normalized_payload"]["status"] == "answered_with_greeting"
