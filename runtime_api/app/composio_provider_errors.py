import re
from typing import Any, Dict, Mapping, Optional, Tuple


_COMPOSIO_DASHBOARD_URL = "https://dashboard.composio.dev"


def classify_composio_provider_error(error: object) -> Optional[Dict[str, Any]]:
    """Return a public, allowlisted error description for known Composio failures."""
    if isinstance(error, dict):
        if _is_live_permission_result(error):
            return _permission_result()
        return None

    status_code, slug, has_provider_error = _structured_provider_error(error)
    if status_code is None or not has_provider_error:
        return None

    if status_code == 403 and slug == "APIKey_InsufficientPermissions":
        return _permission_result()

    if status_code == 401:
        return _public_result(
            status_code=503,
            code="composio_api_key_invalid",
            message="Composio API Key 无效或已失效。",
            retryable=False,
            settings_url=_COMPOSIO_DASHBOARD_URL,
        )
    if status_code == 429:
        return _public_result(
            status_code=503,
            code="composio_rate_limited",
            message="Composio 服务请求频率受限，请稍后重试。",
            retryable=True,
        )
    if status_code >= 500:
        return _public_result(
            status_code=502,
            code="composio_upstream_unavailable",
            message="Composio 上游服务暂时不可用。",
            retryable=True,
        )
    return None


def _structured_provider_error(
    error: object,
) -> Tuple[Optional[int], Optional[str], bool]:
    response = _safe_getattr(error, "response")
    status_code = _http_status(_safe_getattr(error, "status_code"))
    if status_code is None and response is not None:
        status_code = _http_status(_safe_getattr(response, "status_code"))

    body = _safe_getattr(error, "body")
    has_provider_error, slug = _provider_slug_from_payload(body)
    if has_provider_error:
        return status_code, slug, True

    if response is not None:
        response_json = _safe_getattr(response, "json")
        if callable(response_json):
            try:
                body = response_json()
            except Exception:
                body = None

    has_provider_error, slug = _provider_slug_from_payload(body)
    return status_code, slug, has_provider_error


def _provider_slug_from_payload(payload: Any) -> Tuple[bool, Optional[str]]:
    if not isinstance(payload, dict):
        return False, None

    nested_error = payload.get("error")
    if isinstance(nested_error, dict) and _has_nested_provider_error_fields(
        nested_error
    ):
        return True, _non_empty_string_value(nested_error, "slug")
    if _has_top_level_provider_error_fields(payload):
        return True, _non_empty_string_value(payload, "slug")
    return False, None


def _has_nested_provider_error_fields(payload: Mapping[str, Any]) -> bool:
    return _has_non_empty_string(payload, "slug") or _has_non_empty_string(
        payload, "message"
    )


def _has_top_level_provider_error_fields(payload: Mapping[str, Any]) -> bool:
    return _has_non_empty_string(payload, "slug") and _has_non_empty_string(
        payload, "message"
    )


def _has_non_empty_string(payload: Mapping[str, Any], field: str) -> bool:
    return _non_empty_string_value(payload, field) is not None


def _non_empty_string_value(
    payload: Mapping[str, Any], field: str
) -> Optional[str]:
    value = payload.get(field)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _is_live_permission_result(result: Mapping[str, Any]) -> bool:
    summary = result.get("summary")
    error_name = result.get("error")
    if (
        result.get("status") != "failed"
        or error_name != "PermissionDeniedError"
        or not isinstance(summary, str)
    ):
        return False
    summary_lower = summary.lower()
    return (
        re.search(r"\b403\b", summary) is not None
        and "apikey_insufficientpermissions" in summary_lower
        and "sessions" in summary_lower
        and "write" in summary_lower
    )


def _permission_result() -> Dict[str, Any]:
    result = _public_result(
        status_code=403,
        code="composio_api_key_insufficient_permissions",
        message="Composio API Key 权限不足，无法创建账号授权会话。",
        retryable=False,
        settings_url=_COMPOSIO_DASHBOARD_URL,
    )
    result["detail"]["required_permissions"] = [
        {"area": "sessions", "access": "read_and_write"}
    ]
    return result


def _public_result(
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool,
    settings_url: Optional[str] = None,
) -> Dict[str, Any]:
    detail: Dict[str, Any] = {
        "code": code,
        "message": message,
        "provider": "composio",
    }
    if settings_url is not None:
        detail["settings_url"] = settings_url
    detail["retryable"] = retryable
    return {"status_code": status_code, "detail": detail}


def _http_status(value: Any) -> Optional[int]:
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 100 <= value <= 599
    ):
        return value
    return None


def _safe_getattr(value: object, name: str) -> Any:
    try:
        return getattr(value, name, None)
    except Exception:
        return None
