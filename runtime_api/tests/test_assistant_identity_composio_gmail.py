from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.assistant_identity.composio_gmail import (
    ASSISTANT_GMAIL_ALIAS,
    ASSISTANT_GMAIL_COMPOSIO_USER_ID,
    ASSISTANT_GMAIL_IDENTITY_ID,
    AssistantGmailConnectionError,
    AssistantGmailConnectionService,
    ComposioConnectedAccount,
    ComposioGmailProfile,
    ComposioLinkRequest,
    ComposioSdkGmailProvider,
    assistant_gmail_toolkit_version,
)
from app.assistant_identity.health import AssistantIdentityHealthService
from app.assistant_identity.registry import AssistantIdentityRegistry
from app.assistant_identity.repository import InMemoryAssistantIdentityHealthRepository


@dataclass
class FakeComposioGmailProvider:
    account: ComposioConnectedAccount | None = None
    profile: ComposioGmailProfile | None = None

    def __post_init__(self) -> None:
        self.authorization_calls: list[dict[str, str]] = []
        self.profile_calls: list[dict[str, str]] = []

    def begin_authorization(
        self,
        *,
        user_id: str,
        alias: str,
        callback_url: str,
    ) -> ComposioLinkRequest:
        self.authorization_calls.append(
            {"user_id": user_id, "alias": alias, "callback_url": callback_url}
        )
        return ComposioLinkRequest(
            redirect_url="https://connect.composio.dev/link/ln_nomi_gmail",
            connection_request_id="ln_nomi_gmail",
            session_id="sess_nomi_gmail",
        )

    def get_connected_account(
        self,
        *,
        user_id: str,
        connected_account_id: str,
    ) -> ComposioConnectedAccount:
        if self.account is None:
            raise RuntimeError("connected account is unavailable")
        return self.account

    def get_gmail_profile(
        self,
        *,
        user_id: str,
        connected_account_id: str,
    ) -> ComposioGmailProfile:
        self.profile_calls.append(
            {
                "user_id": user_id,
                "connected_account_id": connected_account_id,
            }
        )
        if self.profile is None:
            raise RuntimeError("gmail profile is unavailable")
        return self.profile


def build_service(
    provider: FakeComposioGmailProvider,
) -> tuple[AssistantGmailConnectionService, AssistantIdentityRegistry, AssistantIdentityHealthService]:
    registry = AssistantIdentityRegistry()
    registry.bootstrap_defaults()
    health = AssistantIdentityHealthService(InMemoryAssistantIdentityHealthRepository())
    service = AssistantGmailConnectionService(
        registry=registry,
        health_service=health,
        provider=provider,
        callback_base_url="https://nomi.example/api/assistant-identities/oauth/callback",
        state_factory=lambda: "oauth-state-123",
    )
    return service, registry, health


def active_assistant_account() -> ComposioConnectedAccount:
    return ComposioConnectedAccount(
        connected_account_id="ca_nomi_gmail",
        user_id=ASSISTANT_GMAIL_COMPOSIO_USER_ID,
        toolkit_slug="gmail",
        status="ACTIVE",
        alias=ASSISTANT_GMAIL_ALIAS,
    )


def test_connect_link_uses_stable_assistant_scope_alias_and_bound_callback():
    provider = FakeComposioGmailProvider()
    service, registry, _ = build_service(provider)

    result = service.create_connect_link()

    assert result["status"] == "authorization_pending"
    assert result["redirect_url"].endswith("ln_nomi_gmail")
    assert result["user_id"] == ASSISTANT_GMAIL_COMPOSIO_USER_ID
    assert result["alias"] == ASSISTANT_GMAIL_ALIAS
    assert provider.authorization_calls == [
        {
            "user_id": ASSISTANT_GMAIL_COMPOSIO_USER_ID,
            "alias": ASSISTANT_GMAIL_ALIAS,
            "callback_url": (
                "https://nomi.example/api/assistant-identities/oauth/callback"
                "?identity_id=nomi_gmail_primary&state=oauth-state-123"
            ),
        }
    ]
    identity = registry.get(ASSISTANT_GMAIL_IDENTITY_ID)
    assert identity is not None
    assert identity.status == "authorization_pending"
    provider_metadata = identity.metadata["provider_connection"]
    assert provider_metadata["composio_user_id"] == ASSISTANT_GMAIL_COMPOSIO_USER_ID
    assert provider_metadata["alias"] == ASSISTANT_GMAIL_ALIAS
    assert provider_metadata["oauth_state_sha256"]
    assert "oauth-state-123" not in repr(identity.metadata)


def test_connect_link_can_be_refreshed_while_authorization_is_pending():
    provider = FakeComposioGmailProvider()
    service, registry, _ = build_service(provider)
    states = iter(["oauth-state-first", "oauth-state-second"])
    service.state_factory = lambda: next(states)

    first = service.create_connect_link()
    first_identity = registry.get(ASSISTANT_GMAIL_IDENTITY_ID)
    first_state_digest = first_identity.metadata["provider_connection"]["oauth_state_sha256"]

    second = service.create_connect_link()
    second_identity = registry.get(ASSISTANT_GMAIL_IDENTITY_ID)
    second_state_digest = second_identity.metadata["provider_connection"]["oauth_state_sha256"]

    assert first["status"] == "authorization_pending"
    assert second["status"] == "authorization_pending"
    assert len(provider.authorization_calls) == 2
    assert provider.authorization_calls[0]["callback_url"].endswith(
        "identity_id=nomi_gmail_primary&state=oauth-state-first"
    )
    assert provider.authorization_calls[1]["callback_url"].endswith(
        "identity_id=nomi_gmail_primary&state=oauth-state-second"
    )
    assert second_state_digest != first_state_digest
    assert second_identity.version > first_identity.version


def test_failed_reauthorization_does_not_invalidate_an_existing_connected_identity():
    provider = FakeComposioGmailProvider(
        account=active_assistant_account(),
        profile=ComposioGmailProfile(email_address="nomi.real@example.com"),
    )
    service, registry, _ = build_service(provider)
    service.create_connect_link()
    service.finish_connect(
        identity_id=ASSISTANT_GMAIL_IDENTITY_ID,
        state="oauth-state-123",
        callback_status="success",
        connected_account_id="ca_nomi_gmail",
    )

    def fail_authorization(**_values):
        raise RuntimeError("provider temporarily unavailable")

    provider.begin_authorization = fail_authorization

    with pytest.raises(
        AssistantGmailConnectionError,
        match="composio_authorization_failed",
    ):
        service.create_connect_link()

    identity = registry.get(ASSISTANT_GMAIL_IDENTITY_ID)
    assert identity is not None
    assert identity.status == "connected"
    assert identity.address == "nomi.real@example.com"
    assert identity.metadata["provider_connection"]["connected_account_id"] == "ca_nomi_gmail"


def test_cancelled_reauthorization_keeps_an_existing_connected_identity_active():
    provider = FakeComposioGmailProvider(
        account=active_assistant_account(),
        profile=ComposioGmailProfile(email_address="nomi.real@example.com"),
    )
    service, registry, _ = build_service(provider)
    service.create_connect_link()
    service.finish_connect(
        identity_id=ASSISTANT_GMAIL_IDENTITY_ID,
        state="oauth-state-123",
        callback_status="success",
        connected_account_id="ca_nomi_gmail",
    )
    service.state_factory = lambda: "oauth-state-reauthorize"

    link = service.create_connect_link()

    assert link["status"] == "connected"
    assert registry.get(ASSISTANT_GMAIL_IDENTITY_ID).status == "connected"

    with pytest.raises(
        AssistantGmailConnectionError,
        match="gmail_oauth_not_completed",
    ):
        service.finish_connect(
            identity_id=ASSISTANT_GMAIL_IDENTITY_ID,
            state="oauth-state-reauthorize",
            callback_status="cancelled",
            connected_account_id="",
        )

    identity = registry.get(ASSISTANT_GMAIL_IDENTITY_ID)
    assert identity is not None
    assert identity.status == "connected"
    assert identity.address == "nomi.real@example.com"


def test_callback_rejects_wrong_state_without_verifying_account():
    provider = FakeComposioGmailProvider(
        account=active_assistant_account(),
        profile=ComposioGmailProfile(email_address="nomi@example.com"),
    )
    service, registry, _ = build_service(provider)
    service.create_connect_link()

    with pytest.raises(AssistantGmailConnectionError, match="oauth_state_mismatch"):
        service.finish_connect(
            identity_id=ASSISTANT_GMAIL_IDENTITY_ID,
            state="forged-state",
            callback_status="success",
            connected_account_id="ca_nomi_gmail",
        )

    assert provider.profile_calls == []
    assert registry.get(ASSISTANT_GMAIL_IDENTITY_ID).status == "authorization_pending"


def test_active_pinned_account_and_profile_complete_verification():
    provider = FakeComposioGmailProvider(
        account=active_assistant_account(),
        profile=ComposioGmailProfile(
            email_address="nomi.real@example.com",
            messages_total=123,
            threads_total=45,
        ),
    )
    service, registry, health = build_service(provider)
    service.create_connect_link()

    result = service.finish_connect(
        identity_id=ASSISTANT_GMAIL_IDENTITY_ID,
        state="oauth-state-123",
        callback_status="success",
        connected_account_id="ca_nomi_gmail",
    )

    assert result["status"] == "connected"
    assert result["address"] == "nomi.real@example.com"
    assert result["connected_account_id"] == "ca_nomi_gmail"
    identity = registry.get(ASSISTANT_GMAIL_IDENTITY_ID)
    assert identity.provider == "composio_gmail"
    assert identity.address == "nomi.real@example.com"
    assert identity.capabilities == ["draft", "send", "thread_reply"]
    metadata = identity.metadata["provider_connection"]
    assert metadata["connected_account_id"] == "ca_nomi_gmail"
    assert metadata["composio_user_id"] == ASSISTANT_GMAIL_COMPOSIO_USER_ID
    assert "oauth_state_sha256" not in metadata
    current_health = health.current(identity)
    assert current_health["checks"]["credentials"] == "passed"
    assert current_health["checks"]["profile"] == "passed"
    assert current_health["status"] == "connected"


def test_existing_connection_verification_reuses_only_persisted_account_id():
    provider = FakeComposioGmailProvider(
        account=active_assistant_account(),
        profile=ComposioGmailProfile(email_address="nomi.real@example.com"),
    )
    service, registry, _ = build_service(provider)
    service.create_connect_link()
    service.finish_connect(
        identity_id=ASSISTANT_GMAIL_IDENTITY_ID,
        state="oauth-state-123",
        callback_status="success",
        connected_account_id="ca_nomi_gmail",
    )
    provider.profile_calls.clear()

    result = service.verify_existing_connection(ASSISTANT_GMAIL_IDENTITY_ID)

    assert result["status"] == "connected"
    assert result["connected_account_id"] == "ca_nomi_gmail"
    assert provider.profile_calls == [
        {
            "user_id": ASSISTANT_GMAIL_COMPOSIO_USER_ID,
            "connected_account_id": "ca_nomi_gmail",
        }
    ]
    assert registry.get(ASSISTANT_GMAIL_IDENTITY_ID).address == "nomi.real@example.com"


def test_existing_connection_verification_never_discovers_an_unpinned_account():
    provider = FakeComposioGmailProvider(
        account=active_assistant_account(),
        profile=ComposioGmailProfile(email_address="nomi.real@example.com"),
    )
    service, registry, _ = build_service(provider)

    with pytest.raises(
        AssistantGmailConnectionError,
        match="assistant_gmail_connected_account_missing",
    ):
        service.verify_existing_connection(ASSISTANT_GMAIL_IDENTITY_ID)

    assert provider.profile_calls == []
    assert registry.get(ASSISTANT_GMAIL_IDENTITY_ID).status == "unconfigured"


@pytest.mark.parametrize(
    ("account", "expected_code"),
    [
        (
            ComposioConnectedAccount(
                connected_account_id="ca_user_gmail",
                user_id="nomi_owner",
                toolkit_slug="gmail",
                status="ACTIVE",
                alias="personal-gmail",
            ),
            "composio_account_scope_mismatch",
        ),
        (
            ComposioConnectedAccount(
                connected_account_id="ca_nomi_gmail",
                user_id=ASSISTANT_GMAIL_COMPOSIO_USER_ID,
                toolkit_slug="github",
                status="ACTIVE",
                alias=ASSISTANT_GMAIL_ALIAS,
            ),
            "composio_toolkit_mismatch",
        ),
        (
            ComposioConnectedAccount(
                connected_account_id="ca_nomi_gmail",
                user_id=ASSISTANT_GMAIL_COMPOSIO_USER_ID,
                toolkit_slug="gmail",
                status="ACTIVE",
                alias="user-gmail",
            ),
            "composio_account_alias_mismatch",
        ),
    ],
)
def test_user_owned_or_wrong_toolkit_account_is_never_selected(account, expected_code):
    provider = FakeComposioGmailProvider(
        account=account,
        profile=ComposioGmailProfile(email_address="wrong@example.com"),
    )
    service, registry, _ = build_service(provider)
    service.create_connect_link()

    with pytest.raises(AssistantGmailConnectionError, match=expected_code):
        service.finish_connect(
            identity_id=ASSISTANT_GMAIL_IDENTITY_ID,
            state="oauth-state-123",
            callback_status="success",
            connected_account_id=account.connected_account_id,
        )

    assert provider.profile_calls == []
    failed = registry.get(ASSISTANT_GMAIL_IDENTITY_ID)
    assert failed.status == "failed"
    assert failed.address == ""


@pytest.mark.parametrize("provider_status", ["EXPIRED", "REVOKED"])
def test_expired_or_revoked_account_maps_to_expired_lifecycle(provider_status):
    account = active_assistant_account()
    account = ComposioConnectedAccount(
        connected_account_id=account.connected_account_id,
        user_id=account.user_id,
        toolkit_slug=account.toolkit_slug,
        status=provider_status,
        alias=account.alias,
    )
    provider = FakeComposioGmailProvider(account=account)
    service, registry, _ = build_service(provider)
    service.create_connect_link()

    with pytest.raises(AssistantGmailConnectionError, match="composio_account_not_active"):
        service.finish_connect(
            identity_id=ASSISTANT_GMAIL_IDENTITY_ID,
            state="oauth-state-123",
            callback_status="success",
            connected_account_id="ca_nomi_gmail",
        )

    expired = registry.get(ASSISTANT_GMAIL_IDENTITY_ID)
    assert expired.status == "expired"
    assert expired.last_error_code in {
        "composio_account_expired",
        "composio_account_revoked",
    }


def test_profile_address_must_come_from_provider_and_be_a_valid_email():
    provider = FakeComposioGmailProvider(
        account=active_assistant_account(),
        profile=ComposioGmailProfile(email_address="not-an-email"),
    )
    service, registry, _ = build_service(provider)
    service.create_connect_link()

    with pytest.raises(AssistantGmailConnectionError, match="gmail_profile_address_invalid"):
        service.finish_connect(
            identity_id=ASSISTANT_GMAIL_IDENTITY_ID,
            state="oauth-state-123",
            callback_status="success",
            connected_account_id="ca_nomi_gmail",
        )

    failed = registry.get(ASSISTANT_GMAIL_IDENTITY_ID)
    assert failed.status == "failed"
    assert failed.address == ""


def test_sdk_provider_creates_assistant_only_session_and_alias_connect_link():
    class Authorization:
        redirect_url = "https://connect.composio.dev/link/ln_sdk"
        id = "ln_sdk"
        expires_at = "2026-07-21T16:00:00Z"

    class Session:
        session_id = "sess_sdk"

        def authorize(self, toolkit, *, callback_url, alias):
            assert toolkit == "gmail"
            assert callback_url.endswith("state=state-1")
            assert alias == ASSISTANT_GMAIL_ALIAS
            return Authorization()

    class Sdk:
        def __init__(self):
            self.create_calls = []

        def create(self, *, user_id, **config):
            self.create_calls.append({"user_id": user_id, **config})
            return Session()

    sdk = Sdk()
    provider = ComposioSdkGmailProvider(sdk)

    link = provider.begin_authorization(
        user_id=ASSISTANT_GMAIL_COMPOSIO_USER_ID,
        alias=ASSISTANT_GMAIL_ALIAS,
        callback_url="https://nomi.example/callback?state=state-1",
    )

    assert link.connection_request_id == "ln_sdk"
    assert link.session_id == "sess_sdk"
    assert sdk.create_calls == [
        {
            "user_id": ASSISTANT_GMAIL_COMPOSIO_USER_ID,
            "toolkits": ["gmail"],
            "manage_connections": False,
            "sandbox": {"enable": False},
        }
    ]


def test_sdk_provider_lists_only_expected_user_and_executes_profile_with_pinned_account():
    class Accounts:
        def __init__(self):
            self.list_calls = []

        def list(self, **filters):
            self.list_calls.append(filters)

            class Page:
                items = [
                    {
                        "id": "ca_nomi_gmail",
                        "user_id": ASSISTANT_GMAIL_COMPOSIO_USER_ID,
                        "status": "ACTIVE",
                        "alias": ASSISTANT_GMAIL_ALIAS,
                        "toolkit": {"slug": "gmail"},
                    }
                ]

            return Page()

    class Tools:
        def __init__(self):
            self.execute_calls = []

        def execute(self, tool_slug, **kwargs):
            self.execute_calls.append((tool_slug, kwargs))
            return {
                "successful": True,
                "data": {
                    "emailAddress": "nomi.sdk@example.com",
                    "messagesTotal": 77,
                    "threadsTotal": 31,
                },
            }

    class Sdk:
        def __init__(self):
            self.connected_accounts = Accounts()
            self.tools = Tools()

    sdk = Sdk()
    provider = ComposioSdkGmailProvider(sdk)

    account = provider.get_connected_account(
        user_id=ASSISTANT_GMAIL_COMPOSIO_USER_ID,
        connected_account_id="ca_nomi_gmail",
    )
    profile = provider.get_gmail_profile(
        user_id=ASSISTANT_GMAIL_COMPOSIO_USER_ID,
        connected_account_id="ca_nomi_gmail",
    )

    assert account.user_id == ASSISTANT_GMAIL_COMPOSIO_USER_ID
    assert account.toolkit_slug == "gmail"
    assert account.alias == ASSISTANT_GMAIL_ALIAS
    assert sdk.connected_accounts.list_calls == [
        {"user_ids": [ASSISTANT_GMAIL_COMPOSIO_USER_ID]}
    ]
    assert sdk.tools.execute_calls == [
        (
            "GMAIL_GET_PROFILE",
            {
                "user_id": ASSISTANT_GMAIL_COMPOSIO_USER_ID,
                "connected_account_id": "ca_nomi_gmail",
                "version": "20260721_00",
                "arguments": {},
            },
        )
    ]
    assert profile == ComposioGmailProfile(
        email_address="nomi.sdk@example.com",
        messages_total=77,
        threads_total=31,
    )


def test_gmail_toolkit_version_can_be_pinned_by_environment(monkeypatch):
    monkeypatch.setenv("COMPOSIO_GMAIL_TOOLKIT_VERSION", "20260720_00")

    assert assistant_gmail_toolkit_version() == "20260720_00"


def test_sdk_provider_does_not_fall_back_to_another_connected_account():
    class Accounts:
        def list(self, **filters):
            return {
                "items": [
                    {
                        "id": "ca_someone_else",
                        "user_id": ASSISTANT_GMAIL_COMPOSIO_USER_ID,
                        "status": "ACTIVE",
                        "alias": "other-gmail",
                        "toolkit": {"slug": "gmail"},
                    }
                ]
            }

    class Sdk:
        connected_accounts = Accounts()

    provider = ComposioSdkGmailProvider(Sdk())

    with pytest.raises(AssistantGmailConnectionError, match="composio_account_scope_mismatch"):
        provider.get_connected_account(
            user_id=ASSISTANT_GMAIL_COMPOSIO_USER_ID,
            connected_account_id="ca_nomi_gmail",
        )
