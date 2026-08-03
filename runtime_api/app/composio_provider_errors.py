import re
from typing import Any, Dict, Mapping, Optional, Tuple


_COMPOSIO_DASHBOARD_URL = "https://dashboard.composio.dev"
_SAFE_REQUEST_ID = re.compile(r"^req[-_][A-Za-z0-9][A-Za-z0-9._:-]{0,123}$")


def classify_composio_provider_error(error: object) -> Optional[Dict[str, Any]]:
    """Return a public, allowlisted error description for known Composio failures."""
    if isinstance(error, dict):
        if _is_live_permission_result(error):
            return _permission_result()
        return None

    status_code, provider_error = _structured_provider_error(error)
    if status_code is None or provider_error is None:
        return None

    slug = provider_error.get("slug")
    request_id = _safe_request_id(provider_error.get("request_id"))

    if status_code == 403 and slug == "APIKey_InsufficientPermissions":
        return _permission_result(request_id)

    if status_code == 401:
        return _public_result(
            status_code=503,
            code="composio_api_key_invalid",
            message="Composio API Key 无效或已失效。",
            retryable=False,
            request_id=request_id,
            settings_url=_COMPOSIO_DASHBOARD_URL,
        )
    if status_code == 429:
        return _public_result(
            status_code=503,
            code="composio_rate_limited",
            message="Composio 服务请求频率受限，请稍后重试。",
            retryable=True,
            request_id=request_id,
        )
    if status_code >= 500:
        return _public_result(
            status_code=502,
            code="composio_upstream_unavailable",
            message="Composio 上游服务暂时不可用。",
            retryable=True,
            request_id=request_id,
        )
    return None


def _structured_provider_error(
    error: object,
) -> Tuple[Optional[int], Optional[Mapping[str, Any]]]:
    response = _safe_getattr(error, "response")
    status_code = _http_status(_safe_getattr(error, "status_code"))
    if status_code is None and response is not None:
        status_code = _http_status(_safe_getattr(response, "status_code"))

    body = _safe_getattr(error, "body")
    if not isinstance(body, dict) and response is not None:
        response_json = _safe_getattr(response, "json")
        if callable(response_json):
            try:
                body = response_json()
            except Exception:
                body = None

    if not isinstance(body, dict):
        return status_code, None
    provider_error = body.get("error")
    if not isinstance(provider_error, dict):
        return status_code, None
    return status_code, provider_error


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


def _permission_result(request_id: Optional[str] = None) -> Dict[str, Any]:
    result = _public_result(
        status_code=403,
        code="composio_api_key_insufficient_permissions",
        message="Composio API Key 权限不足，无法创建账号授权会话。",
        retryable=False,
        request_id=request_id,
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
    request_id: Optional[str] = None,
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
    if request_id is not None:
        detail["provider_request_id"] = request_id
    return {"status_code": status_code, "detail": detail}


def _safe_request_id(value: Any) -> Optional[str]:
    if isinstance(value, str) and _SAFE_REQUEST_ID.fullmatch(value):
        return value
    return None


def _http_status(value: Any) -> Optional[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _safe_getattr(value: object, name: str) -> Any:
    try:
        return getattr(value, name, None)
    except Exception:
        return None
