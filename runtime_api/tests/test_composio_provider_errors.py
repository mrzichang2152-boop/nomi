import json

from app.composio_provider_errors import classify_composio_provider_error


class PermissionDeniedError(Exception):
    def __init__(
        self, *, status_code: int, body: dict, message: str = "denied"
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class FakeResponse:
    def __init__(self, *, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        return self._body


class ResponseProviderError(Exception):
    def __init__(self, *, response: FakeResponse, message: str) -> None:
        super().__init__(message)
        self.response = response


class BodyProviderError(Exception):
    def __init__(self, *, status_code: int, body: dict, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def test_classifies_insufficient_composio_api_key_permissions() -> None:
    error = PermissionDeniedError(
        status_code=403,
        body={
            "error": {
                "slug": "APIKey_InsufficientPermissions",
                "message": "This route requires sessions write access.",
                "request_id": "req-safe-123",
            }
        },
    )

    result = classify_composio_provider_error(error)

    assert result == {
        "status_code": 403,
        "detail": {
            "code": "composio_api_key_insufficient_permissions",
            "message": "Composio API Key 权限不足，无法创建账号授权会话。",
            "provider": "composio",
            "required_permissions": [
                {"area": "sessions", "access": "read_and_write"}
            ],
            "settings_url": "https://dashboard.composio.dev",
            "retryable": False,
            "provider_request_id": "req-safe-123",
        },
    }


def test_never_copies_exception_text_into_permission_result() -> None:
    secret = "ak_test_secret_must_not_escape"
    error = PermissionDeniedError(
        status_code=403,
        body={
            "error": {
                "slug": "APIKey_InsufficientPermissions",
                "message": "This route requires sessions write access.",
            }
        },
        message=f"permission denied for api_key={secret}",
    )

    result = classify_composio_provider_error(error)

    assert result is not None
    assert secret not in json.dumps(result, ensure_ascii=False)


def test_returns_none_for_unrecognized_internal_error() -> None:
    assert classify_composio_provider_error(RuntimeError("database failed")) is None


def test_classifies_permission_error_swallowed_by_live_executor() -> None:
    live_result = {
        "status": "failed",
        "error": "PermissionDeniedError",
        "summary": (
            "Error code: 403 - APIKey_InsufficientPermissions; "
            "this route requires sessions write access"
        ),
    }

    result = classify_composio_provider_error(live_result)

    assert result == {
        "status_code": 403,
        "detail": {
            "code": "composio_api_key_insufficient_permissions",
            "message": "Composio API Key 权限不足，无法创建账号授权会话。",
            "provider": "composio",
            "required_permissions": [
                {"area": "sessions", "access": "read_and_write"}
            ],
            "settings_url": "https://dashboard.composio.dev",
            "retryable": False,
        },
    }


def test_classifies_invalid_api_key_from_response_json_without_leaking_raw_fields(
) -> None:
    secret = "ak_test_invalid_secret_must_not_escape"
    error = ResponseProviderError(
        response=FakeResponse(
            status_code=401,
            body={
                "error": {
                    "message": f"invalid API key {secret}",
                    "suggested_fix": f"replace {secret}",
                    "request_id": "req-auth-401",
                }
            },
        ),
        message=f"authentication failed: {secret}",
    )

    result = classify_composio_provider_error(error)

    assert result == {
        "status_code": 503,
        "detail": {
            "code": "composio_api_key_invalid",
            "message": "Composio API Key 无效或已失效。",
            "provider": "composio",
            "settings_url": "https://dashboard.composio.dev",
            "retryable": False,
            "provider_request_id": "req-auth-401",
        },
    }
    assert secret not in json.dumps(result, ensure_ascii=False)


def test_omits_untrusted_request_id_and_never_copies_headers() -> None:
    malicious_request_id = "ak_test_secret_must_not_escape"
    api_key_header = "ak_header_secret"
    authorization_header = "Bearer authorization_header_secret"
    exception_header = "ak_exception_header_secret"
    response = FakeResponse(
        status_code=401,
        body={
            "error": {
                "message": "invalid API key",
                "request_id": malicious_request_id,
            }
        },
    )
    response.headers = {
        "x-api-key": api_key_header,
        "authorization": authorization_header,
    }
    error = ResponseProviderError(response=response, message="authentication failed")
    error.headers = {"x-api-key": exception_header}

    result = classify_composio_provider_error(error)

    assert result is not None
    assert "provider_request_id" not in result["detail"]
    rendered_result = repr(result)
    for secret in (
        malicious_request_id,
        api_key_header,
        authorization_header,
        exception_header,
    ):
        assert secret not in rendered_result


def test_classifies_rate_limit_as_retryable_service_unavailable() -> None:
    secret = "ak_test_rate_limit_secret_must_not_escape"
    error = BodyProviderError(
        status_code=429,
        body={
            "error": {
                "message": f"quota for {secret} exceeded",
                "request_id": "req-rate-429",
            }
        },
        message=f"rate limited: {secret}",
    )

    result = classify_composio_provider_error(error)

    assert result == {
        "status_code": 503,
        "detail": {
            "code": "composio_rate_limited",
            "message": "Composio 服务请求频率受限，请稍后重试。",
            "provider": "composio",
            "retryable": True,
            "provider_request_id": "req-rate-429",
        },
    }
    assert secret not in json.dumps(result, ensure_ascii=False)


def test_classifies_provider_server_error_as_retryable_bad_gateway() -> None:
    secret = "ak_test_upstream_secret_must_not_escape"
    error = ResponseProviderError(
        response=FakeResponse(
            status_code=503,
            body={
                "error": {
                    "message": f"upstream failed near {secret}",
                    "request_id": "req-upstream-503",
                }
            },
        ),
        message=f"provider unavailable: {secret}",
    )

    result = classify_composio_provider_error(error)

    assert result == {
        "status_code": 502,
        "detail": {
            "code": "composio_upstream_unavailable",
            "message": "Composio 上游服务暂时不可用。",
            "provider": "composio",
            "retryable": True,
            "provider_request_id": "req-upstream-503",
        },
    }
    assert secret not in json.dumps(result, ensure_ascii=False)
