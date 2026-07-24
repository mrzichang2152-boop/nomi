from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass, replace
from typing import Callable, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.assistant_identity.health import AssistantIdentityHealthService
from app.assistant_identity.registry import AssistantIdentityRegistry


ASSISTANT_GMAIL_IDENTITY_ID = "nomi_gmail_primary"
ASSISTANT_GMAIL_COMPOSIO_USER_ID = "nomi-owned::nomi_gmail_primary"
ASSISTANT_GMAIL_ALIAS = "nomi-gmail-primary"
ASSISTANT_GMAIL_TOOLKIT = "gmail"
ASSISTANT_GMAIL_PROVIDER = "composio_gmail"
ASSISTANT_GMAIL_TOOLKIT_VERSION_ENV = "COMPOSIO_GMAIL_TOOLKIT_VERSION"
ASSISTANT_GMAIL_TOOLKIT_VERSION_DEFAULT = "20260721_00"

_EMAIL_ADDRESS = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def assistant_gmail_toolkit_version() -> str:
    return (
        os.getenv(ASSISTANT_GMAIL_TOOLKIT_VERSION_ENV, "").strip()
        or ASSISTANT_GMAIL_TOOLKIT_VERSION_DEFAULT
    )


class AssistantGmailConnectionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ComposioLinkRequest:
    redirect_url: str
    connection_request_id: str
    session_id: str = ""
    expires_at: object | None = None


@dataclass(frozen=True)
class ComposioConnectedAccount:
    connected_account_id: str
    user_id: str
    toolkit_slug: str
    status: str
    alias: str = ""


@dataclass(frozen=True)
class ComposioGmailProfile:
    email_address: str
    messages_total: int | None = None
    threads_total: int | None = None


class ComposioGmailProvider(Protocol):
    def begin_authorization(
        self,
        *,
        user_id: str,
        alias: str,
        callback_url: str,
    ) -> ComposioLinkRequest:
        ...

    def get_connected_account(
        self,
        *,
        user_id: str,
        connected_account_id: str,
    ) -> ComposioConnectedAccount:
        ...

    def get_gmail_profile(
        self,
        *,
        user_id: str,
        connected_account_id: str,
    ) -> ComposioGmailProfile:
        ...


def _object_value(value: object, name: str, default: object = None) -> object:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _serialized(value: object) -> object:
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return value.model_dump()
    if hasattr(value, "dict") and callable(value.dict):
        return value.dict()
    return value


def _collection_items(value: object) -> list[object]:
    normalized = _serialized(value)
    if isinstance(normalized, dict):
        items = normalized.get("items") or []
    else:
        items = getattr(normalized, "items", [])
    return list(items or [])


def _nested_value(value: object, *names: str) -> object:
    normalized = _serialized(value)
    if isinstance(normalized, dict):
        for name in names:
            if name in normalized and normalized[name] not in (None, ""):
                return normalized[name]
        for nested_key in ("data", "result", "response_data", "responseData"):
            nested = normalized.get(nested_key)
            if nested is not None:
                found = _nested_value(nested, *names)
                if found not in (None, ""):
                    return found
    return None


class ComposioSdkGmailProvider:
    """Current Composio SDK adapter for one pinned Nomi-owned Gmail account."""

    def __init__(self, sdk: object) -> None:
        self.sdk = sdk

    def begin_authorization(
        self,
        *,
        user_id: str,
        alias: str,
        callback_url: str,
    ) -> ComposioLinkRequest:
        session = self.sdk.create(
            user_id=user_id,
            toolkits=[ASSISTANT_GMAIL_TOOLKIT],
            manage_connections=False,
            sandbox={"enable": False},
        )
        request = session.authorize(
            ASSISTANT_GMAIL_TOOLKIT,
            callback_url=callback_url,
            alias=alias,
        )
        return ComposioLinkRequest(
            redirect_url=str(
                _object_value(request, "redirect_url")
                or _object_value(request, "redirectUrl")
                or ""
            ),
            connection_request_id=str(
                _object_value(request, "id")
                or _object_value(request, "link_token")
                or _object_value(request, "linkToken")
                or ""
            ),
            session_id=str(
                _object_value(session, "session_id")
                or _object_value(session, "sessionId")
                or ""
            ),
            expires_at=(
                _object_value(request, "expires_at")
                or _object_value(request, "expiresAt")
            ),
        )

    def get_connected_account(
        self,
        *,
        user_id: str,
        connected_account_id: str,
    ) -> ComposioConnectedAccount:
        page = self.sdk.connected_accounts.list(user_ids=[user_id])
        matched = None
        for item in _collection_items(page):
            item_id = str(
                _object_value(item, "id")
                or _object_value(item, "nanoid")
                or ""
            )
            if item_id == connected_account_id:
                matched = item
                break
        if matched is None:
            raise AssistantGmailConnectionError("composio_account_scope_mismatch")
        toolkit = _object_value(matched, "toolkit") or {}
        return ComposioConnectedAccount(
            connected_account_id=connected_account_id,
            user_id=str(
                _object_value(matched, "user_id")
                or _object_value(matched, "userId")
                or user_id
            ),
            toolkit_slug=str(
                _object_value(toolkit, "slug")
                or _object_value(matched, "toolkit_slug")
                or _object_value(matched, "toolkitSlug")
                or ""
            ),
            status=str(_object_value(matched, "status") or ""),
            alias=str(_object_value(matched, "alias") or ""),
        )

    def get_gmail_profile(
        self,
        *,
        user_id: str,
        connected_account_id: str,
    ) -> ComposioGmailProfile:
        result = self.sdk.tools.execute(
            "GMAIL_GET_PROFILE",
            user_id=user_id,
            connected_account_id=connected_account_id,
            version=assistant_gmail_toolkit_version(),
            arguments={},
        )
        normalized = _serialized(result)
        if isinstance(normalized, dict) and normalized.get("successful") is False:
            raise AssistantGmailConnectionError("gmail_profile_fetch_failed")
        address = _nested_value(
            normalized,
            "emailAddress",
            "email_address",
            "email",
        )
        messages_total = _nested_value(normalized, "messagesTotal", "messages_total")
        threads_total = _nested_value(normalized, "threadsTotal", "threads_total")
        return ComposioGmailProfile(
            email_address=str(address or ""),
            messages_total=(
                int(messages_total) if messages_total is not None else None
            ),
            threads_total=(int(threads_total) if threads_total is not None else None),
        )

def _state_digest(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _callback_url(base_url: str, *, identity_id: str, state: str) -> str:
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({"identity_id": identity_id, "state": state})
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


class AssistantGmailConnectionService:
    def __init__(
        self,
        *,
        registry: AssistantIdentityRegistry,
        health_service: AssistantIdentityHealthService,
        provider: ComposioGmailProvider,
        callback_base_url: str,
        state_factory: Callable[[], str] | None = None,
    ) -> None:
        self.registry = registry
        self.health_service = health_service
        self.provider = provider
        self.callback_base_url = callback_base_url.strip()
        self.state_factory = state_factory or (lambda: secrets.token_urlsafe(32))

    def _identity(self, identity_id: str = ASSISTANT_GMAIL_IDENTITY_ID):
        identity = self.registry.get(identity_id)
        if identity is None:
            raise AssistantGmailConnectionError("assistant_gmail_identity_not_found")
        if identity.identity_id != ASSISTANT_GMAIL_IDENTITY_ID or identity.kind != "assistant_gmail":
            raise AssistantGmailConnectionError("assistant_gmail_identity_scope_mismatch")
        return identity

    def _save_provider_metadata(
        self,
        identity_id: str,
        values: dict[str, object],
        *,
        remove_keys: tuple[str, ...] = (),
    ):
        identity = self._identity(identity_id)
        metadata = dict(identity.metadata)
        provider_connection = dict(metadata.get("provider_connection") or {})
        for key in remove_keys:
            provider_connection.pop(key, None)
        provider_connection.update(values)
        metadata["provider_connection"] = provider_connection
        return self.registry.repository.save(
            replace(identity, metadata=metadata),
            expected_version=identity.version,
        )

    def create_connect_link(self) -> dict[str, object]:
        if not self.callback_base_url:
            raise AssistantGmailConnectionError("assistant_gmail_callback_url_missing")
        identity = self._identity()
        state = self.state_factory()
        if not state:
            raise AssistantGmailConnectionError("oauth_state_generation_failed")
        callback_url = _callback_url(
            self.callback_base_url,
            identity_id=ASSISTANT_GMAIL_IDENTITY_ID,
            state=state,
        )
        try:
            link = self.provider.begin_authorization(
                user_id=ASSISTANT_GMAIL_COMPOSIO_USER_ID,
                alias=ASSISTANT_GMAIL_ALIAS,
                callback_url=callback_url,
            )
        except Exception as exc:
            raise AssistantGmailConnectionError("composio_authorization_failed") from exc
        if not link.redirect_url or not link.connection_request_id:
            raise AssistantGmailConnectionError("composio_connect_link_invalid")

        existing_connection = dict(
            identity.metadata.get("provider_connection") or {}
        )
        keeps_verified_connection = bool(
            identity.status == "connected"
            and identity.provider
            and identity.address
            and existing_connection.get("connected_account_id")
        )
        pending = (
            identity
            if keeps_verified_connection
            else self.registry.lifecycle.request_authorization(
                ASSISTANT_GMAIL_IDENTITY_ID
            )
        )
        stored = self._save_provider_metadata(
            pending.identity_id,
            {
                "composio_user_id": ASSISTANT_GMAIL_COMPOSIO_USER_ID,
                "alias": ASSISTANT_GMAIL_ALIAS,
                "toolkit_slug": ASSISTANT_GMAIL_TOOLKIT,
                "oauth_state_sha256": _state_digest(state),
                "connection_request_id": link.connection_request_id,
                "session_id": link.session_id,
            },
        )
        return {
            "status": stored.status,
            "identity_id": stored.identity_id,
            "user_id": ASSISTANT_GMAIL_COMPOSIO_USER_ID,
            "alias": ASSISTANT_GMAIL_ALIAS,
            "redirect_url": link.redirect_url,
            "connection_request_id": link.connection_request_id,
            "expires_at": link.expires_at,
            "version": stored.version,
        }

    def _fail_verification(self, code: str) -> None:
        identity = self._identity()
        if identity.status in {"authorization_pending", "verifying", "degraded"}:
            self.registry.lifecycle.verification_failed(identity.identity_id, code)

    def finish_connect(
        self,
        *,
        identity_id: str,
        state: str,
        callback_status: str,
        connected_account_id: str,
    ) -> dict[str, object]:
        identity = self._identity(identity_id)
        connection = dict(identity.metadata.get("provider_connection") or {})
        expected_digest = str(connection.get("oauth_state_sha256") or "")
        if not expected_digest or not hmac.compare_digest(
            expected_digest,
            _state_digest(state),
        ):
            raise AssistantGmailConnectionError("oauth_state_mismatch")
        if callback_status.strip().lower() != "success":
            self._fail_verification("gmail_oauth_not_completed")
            raise AssistantGmailConnectionError("gmail_oauth_not_completed")
        if not connected_account_id.strip():
            self._fail_verification("composio_connected_account_missing")
            raise AssistantGmailConnectionError("composio_connected_account_missing")

        return self._verify_pinned_account(
            identity_id=identity_id,
            connected_account_id=connected_account_id.strip(),
        )

    def verify_existing_connection(self, identity_id: str) -> dict[str, object]:
        identity = self._identity(identity_id)
        connection = dict(identity.metadata.get("provider_connection") or {})
        connected_account_id = str(
            connection.get("connected_account_id") or ""
        ).strip()
        if not connected_account_id:
            raise AssistantGmailConnectionError(
                "assistant_gmail_connected_account_missing"
            )
        return self._verify_pinned_account(
            identity_id=identity_id,
            connected_account_id=connected_account_id,
        )

    def _verify_pinned_account(
        self,
        *,
        identity_id: str,
        connected_account_id: str,
    ) -> dict[str, object]:

        self.registry.lifecycle.begin_verification(identity_id)
        try:
            account = self.provider.get_connected_account(
                user_id=ASSISTANT_GMAIL_COMPOSIO_USER_ID,
                connected_account_id=connected_account_id,
            )
        except Exception as exc:
            self._fail_verification("composio_account_lookup_failed")
            raise AssistantGmailConnectionError("composio_account_lookup_failed") from exc

        failure_code = ""
        if account.connected_account_id != connected_account_id:
            failure_code = "composio_connected_account_mismatch"
        elif account.user_id != ASSISTANT_GMAIL_COMPOSIO_USER_ID:
            failure_code = "composio_account_scope_mismatch"
        elif account.toolkit_slug.strip().lower() != ASSISTANT_GMAIL_TOOLKIT:
            failure_code = "composio_toolkit_mismatch"
        elif account.alias != ASSISTANT_GMAIL_ALIAS:
            failure_code = "composio_account_alias_mismatch"
        if failure_code:
            self._fail_verification(failure_code)
            raise AssistantGmailConnectionError(failure_code)

        provider_status = account.status.strip().upper()
        if provider_status != "ACTIVE":
            status_code = (
                "composio_account_revoked"
                if provider_status == "REVOKED"
                else "composio_account_expired"
                if provider_status == "EXPIRED"
                else "composio_account_not_active"
            )
            if provider_status in {"EXPIRED", "REVOKED"}:
                self.registry.lifecycle.mark_expired(identity_id, status_code)
            else:
                self._fail_verification(status_code)
            raise AssistantGmailConnectionError("composio_account_not_active")

        try:
            profile = self.provider.get_gmail_profile(
                user_id=ASSISTANT_GMAIL_COMPOSIO_USER_ID,
                connected_account_id=connected_account_id,
            )
        except Exception as exc:
            self._fail_verification("gmail_profile_fetch_failed")
            raise AssistantGmailConnectionError("gmail_profile_fetch_failed") from exc
        address = profile.email_address.strip().lower()
        if not _EMAIL_ADDRESS.fullmatch(address):
            self._fail_verification("gmail_profile_address_invalid")
            raise AssistantGmailConnectionError("gmail_profile_address_invalid")

        current = self._identity(identity_id)
        connection = dict(current.metadata.get("provider_connection") or {})
        connection.pop("oauth_state_sha256", None)
        connection.update(
            {
                "composio_user_id": ASSISTANT_GMAIL_COMPOSIO_USER_ID,
                "alias": ASSISTANT_GMAIL_ALIAS,
                "toolkit_slug": ASSISTANT_GMAIL_TOOLKIT,
                "connected_account_id": connected_account_id,
                "account_status": provider_status,
                "profile_messages_total": profile.messages_total,
                "profile_threads_total": profile.threads_total,
            }
        )
        verified_identity = self._save_provider_metadata(
            identity_id,
            connection,
            remove_keys=("oauth_state_sha256",),
        )
        verified_identity = self.registry.lifecycle.provider_verified(
            verified_identity.identity_id,
            provider=ASSISTANT_GMAIL_PROVIDER,
            address=address,
            capabilities=["draft", "send", "thread_reply"],
        )
        self.health_service.record(
            identity_id,
            "credentials",
            "passed",
            details={"provider": ASSISTANT_GMAIL_PROVIDER, "account_status": "ACTIVE"},
        )
        self.health_service.record(
            identity_id,
            "profile",
            "passed",
            details={"address_verified": True},
        )
        self.health_service.record(
            identity_id,
            "outbound",
            "passed",
            details={
                "send_capability_authorized": True,
                "delivery_test_performed": False,
            },
        )
        return {
            "status": verified_identity.status,
            "identity_id": verified_identity.identity_id,
            "address": verified_identity.address,
            "provider": verified_identity.provider,
            "capabilities": list(verified_identity.capabilities),
            "connected_account_id": connected_account_id,
            "version": verified_identity.version,
        }
