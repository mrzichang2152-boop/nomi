import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_default_registry_bootstraps_nomi_gmail_whatsapp_and_phone():
    from app.assistant_identity.registry import AssistantIdentityRegistry

    registry = AssistantIdentityRegistry()
    identities = registry.bootstrap_defaults()

    assert [identity.identity_id for identity in identities] == [
        "nomi_gmail_primary",
        "nomi_whatsapp_primary",
        "nomi_phone_primary",
    ]
    assert identities[0].kind == "assistant_gmail"
    assert identities[0].capabilities == []
    assert "send" in identities[0].metadata["supported_capabilities"]
    assert identities[1].kind == "assistant_whatsapp"
    assert identities[1].capabilities == []
    assert "send_text" in identities[1].metadata["supported_capabilities"]
    assert identities[2].kind == "assistant_phone"
    assert identities[2].capabilities == []
    assert "send_sms" in identities[2].metadata["supported_capabilities"]
    assert "outbound_call_playback" in identities[2].metadata["supported_capabilities"]


def test_registry_rejects_user_owned_identity_kind():
    from app.assistant_identity.models import AssistantIdentity
    from app.assistant_identity.registry import AssistantIdentityRegistry

    registry = AssistantIdentityRegistry()
    identity = AssistantIdentity(
        identity_id="user_gmail",
        kind="user_gmail",
        display_name="Personal Gmail",
        address="me@example.com",
        capabilities=["send"],
    )

    try:
        registry.add(identity)
    except ValueError as exc:
        assert "Nomi-owned identity" in str(exc)
    else:
        raise AssertionError("registry accepted a user-owned identity kind")


def test_registry_connect_begins_authorization_for_nomi_phone_identity_kind():
    from app.assistant_identity.registry import AssistantIdentityRegistry

    registry = AssistantIdentityRegistry()
    identity = registry.connect_kind("assistant_phone")

    assert identity.identity_id == "nomi_phone_primary"
    assert identity.kind == "assistant_phone"
    assert identity.status == "authorization_pending"
