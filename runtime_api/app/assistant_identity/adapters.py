from __future__ import annotations

from typing import Any, Optional, Protocol


class ProviderHttpResponse(Protocol):
    status_code: int

    def json(self) -> Any:
        """Return the provider response body parsed as JSON."""


class ProviderHttpClient(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> ProviderHttpResponse:
        """Issue a provider HTTP POST request."""


class HttpxProviderHttpClient:
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> ProviderHttpResponse:
        import httpx

        return httpx.post(url, headers=headers, json=json, timeout=timeout)


def blocked_misconfigured_result(*, provider: str, missing_env: list[str]) -> dict[str, object]:
    return {
        "status": "blocked",
        "reason": "misconfigured",
        "misconfigured": True,
        "provider": provider,
        "missing_env": list(missing_env),
        "provider_result": {
            "status": "misconfigured",
            "missing_env": list(missing_env),
        },
    }


def bearer_json_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    }


def join_url(base_url: str, path: str) -> str:
    return str(base_url or "").rstrip("/") + "/" + str(path or "").lstrip("/")


def provider_response_result(response: ProviderHttpResponse) -> dict[str, object]:
    try:
        body: object = response.json()
    except Exception:
        body = {"unparseable_json": True}
    return {
        "status_code": int(getattr(response, "status_code", 0) or 0),
        "body": body,
    }


def provider_http_error_result(*, provider: str, exc: Exception) -> dict[str, object]:
    return {
        "status": "failed",
        "reason": "provider_http_error",
        "provider": provider,
        "provider_result": {
            "status": "error",
            "error_type": exc.__class__.__name__,
        },
    }


def http_success(status_code: object) -> bool:
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return False
    return 200 <= code < 300


def first_body_value(body: object, keys: list[str]) -> str:
    if not isinstance(body, dict):
        return ""
    for key in keys:
        value = body.get(key)
        if value:
            return str(value)
    return ""


class AssistantGmailAdapter(Protocol):
    def send_message(
        self,
        *,
        sender: str,
        recipient: str,
        subject: str,
        body_text: str,
        thread_id: Optional[str] = None,
    ) -> dict[str, object]:
        """Send a confirmed Nomi-owned Gmail message through a provider adapter."""


class AssistantWhatsAppAdapter(Protocol):
    def send_text(
        self,
        *,
        phone_number_id: str,
        to: str,
        body_text: str,
    ) -> dict[str, object]:
        """Send a confirmed Nomi-owned WhatsApp text through a provider adapter."""


class AssistantSmsAdapter(Protocol):
    def send_sms(
        self,
        *,
        from_number: str,
        to_number: str,
        body_text: str,
    ) -> dict[str, object]:
        """Send a confirmed Nomi-owned SMS through a provider adapter."""


class AssistantPhoneCallAdapter(Protocol):
    def create_playback_call(
        self,
        *,
        from_number: str,
        to_number: str,
        script_text: str,
        audio_url: Optional[str] = None,
        voice: str = "default",
    ) -> dict[str, object]:
        """Place a confirmed one-way playback call through a provider adapter."""


class AssistantDuplexPhoneCallAdapter(Protocol):
    def create_duplex_call(
        self,
        *,
        from_number: str,
        to_number: str,
        opening_script: str,
        media_stream_url: Optional[str] = None,
        voice: str = "default",
    ) -> dict[str, object]:
        """Place a confirmed turn-based duplex voice call through a provider adapter."""
