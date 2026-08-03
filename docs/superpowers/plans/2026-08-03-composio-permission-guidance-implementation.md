# Composio Permission Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert Composio API-key permission failures into safe structured responses and show an actionable in-page Dashboard link and retry flow in Nomi.

**Architecture:** Add a focused Python classifier that extracts only safe provider metadata, then map recognized failures at the Composio connect boundary without hiding unrelated server bugs. Add a small browser/CommonJS JavaScript module for structured API-error parsing and guidance models, while the existing workbench owns DOM rendering and external navigation.

**Tech Stack:** Python 3.12, FastAPI, Composio Python SDK 0.18.0, pytest, vanilla JavaScript, Node.js test runner, HTML/CSS, Docker Compose, Android WebView real-device validation.

---

## File map

- Create `runtime_api/app/composio_provider_errors.py`: safely classify Composio provider failures without importing UI or route code.
- Create `runtime_api/tests/test_composio_provider_errors.py`: unit coverage for provider payload extraction, permission mapping, and secret redaction.
- Modify `runtime_api/app/main.py`: translate recognized provider failures at the account-connect boundary and preserve unknown exceptions.
- Modify `runtime_api/tests/test_auth_and_model.py`: FastAPI contract tests for structured `403` responses and the unchanged success path.
- Create `runtime_api/app/static/composio-guidance.js`: browser/CommonJS functions for API-error parsing, safe Dashboard URL selection, and UI guidance models.
- Create `runtime_api/tests_js/composio_guidance.test.cjs`: Node unit tests for permission and generic-error guidance.
- Modify `runtime_api/app/static/index.html`: load the guidance module before `app.js`.
- Modify `runtime_api/app/static/app.js`: use structured API errors and render the Composio inline actions.
- Modify `runtime_api/app/static/styles.css`: style the accessible inline error card and actions.
- Create `runtime_api/tests/test_static_composio_guidance.py`: static integration contract for script ordering and external-link wiring.

The current worktree already contains unrelated user changes in `runtime_api/app/main.py` and `runtime_api/tests/test_auth_and_model.py`. Implementation must patch only the named regions, inspect the final diff, and must not stage or commit those overlapping files unless the user first separates the pre-existing changes.

### Task 1: Safe Composio provider-error classifier

**Files:**
- Create: `runtime_api/app/composio_provider_errors.py`
- Create: `runtime_api/tests/test_composio_provider_errors.py`

- [ ] **Step 1: Write failing classifier tests**

Create tests that model the shape of the real Composio SDK failure observed in production:

```python
from app.composio_provider_errors import classify_composio_provider_error


class FakeResponse:
    status_code = 403

    def json(self):
        return {
            "error": {
                "message": (
                    'This route requires "sessions" write access, '
                    'but the key has read access for "sessions".'
                ),
                "code": 812,
                "slug": "APIKey_InsufficientPermissions",
                "request_id": "req-safe-123",
                "suggested_fix": "Grant sessions write access.",
            }
        }


class FakePermissionDeniedError(Exception):
    status_code = 403
    response = FakeResponse()
    body = response.json()


def test_classifies_composio_scoped_key_permission_error_without_raw_exception():
    secret = "ak_test_secret_must_not_escape"
    error = FakePermissionDeniedError(f"provider failed with {secret}")

    classified = classify_composio_provider_error(error)

    assert classified == {
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
    assert secret not in repr(classified)


def test_unknown_provider_exception_is_not_misclassified():
    assert classify_composio_provider_error(RuntimeError("database failed")) is None


def test_classifies_known_authentication_and_upstream_failures_without_raw_text():
    class FakeProviderError(Exception):
        def __init__(self, status_code):
            super().__init__("ak_secret raw provider message")
            self.status_code = status_code
            self.body = {"error": {"slug": "ProviderFailure"}}

    authentication = classify_composio_provider_error(FakeProviderError(401))
    throttled = classify_composio_provider_error(FakeProviderError(429))
    unavailable = classify_composio_provider_error(FakeProviderError(503))

    assert authentication["detail"]["code"] == "composio_api_key_invalid"
    assert authentication["status_code"] == 503
    assert throttled["detail"]["code"] == "composio_rate_limited"
    assert throttled["detail"]["retryable"] is True
    assert unavailable["detail"]["code"] == "composio_upstream_unavailable"
    assert "ak_secret" not in repr((authentication, throttled, unavailable))


def test_classifies_live_executor_summary_from_composio():
    classified = classify_composio_provider_error({
        "status": "failed",
        "error": "PermissionDeniedError",
        "summary": (
            "Error code: 403 - {'error': {'slug': "
            "'APIKey_InsufficientPermissions', 'message': "
            "'This route requires sessions write access.'}}"
        ),
    })

    assert classified["status_code"] == 403
    assert classified["detail"]["required_permissions"] == [
        {"area": "sessions", "access": "read_and_write"}
    ]
```

- [ ] **Step 2: Run the tests and prove RED**

Run:

```bash
PYTHONPATH=runtime_api python3 -m pytest -q runtime_api/tests/test_composio_provider_errors.py
```

Expected: collection fails because `app.composio_provider_errors` does not exist.

- [ ] **Step 3: Implement the minimal classifier**

Create a pure module with a fixed Dashboard URL and allowlisted output:

```python
from __future__ import annotations

from typing import Any


COMPOSIO_API_KEY_SETTINGS_URL = "https://dashboard.composio.dev"


def _response_payload(error: object) -> dict[str, Any]:
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        return body
    response = getattr(error, "response", None)
    if response is not None:
        try:
            payload = response.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            return payload
    return {}


def _status_code(error: object) -> int:
    direct = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    nested = getattr(response, "status_code", None)
    try:
        return int(direct or nested or 0)
    except (TypeError, ValueError):
        return 0


def classify_composio_provider_error(error: object) -> dict[str, Any] | None:
    payload = _response_payload(error)
    provider_error = payload.get("error") if isinstance(payload.get("error"), dict) else payload
    slug = str(provider_error.get("slug") or "")
    message = str(provider_error.get("message") or "")
    request_id = str(provider_error.get("request_id") or "")
    summary = str(error.get("summary") or "") if isinstance(error, dict) else ""
    error_type = str(error.get("error") or "") if isinstance(error, dict) else type(error).__name__
    permission_denied = (
        (_status_code(error) == 403 and slug == "APIKey_InsufficientPermissions")
        or (
            error_type == "PermissionDeniedError"
            and "APIKey_InsufficientPermissions" in summary
            and "sessions" in summary.lower()
        )
    )
    status_code = _status_code(error)
    if permission_denied:
        detail = {
            "code": "composio_api_key_insufficient_permissions",
            "message": "Composio API Key 权限不足，无法创建账号授权会话。",
            "provider": "composio",
            "required_permissions": [
                {"area": "sessions", "access": "read_and_write"}
            ],
            "settings_url": COMPOSIO_API_KEY_SETTINGS_URL,
            "retryable": False,
        }
        if request_id:
            detail["provider_request_id"] = request_id
        return {"status_code": 403, "detail": detail}
    known = {
        401: (
            "composio_api_key_invalid",
            "Composio API Key 无效或已撤销，请更新配置。",
            False,
        ),
        429: (
            "composio_rate_limited",
            "Composio 请求过于频繁，请稍后重试。",
            True,
        ),
    }
    if status_code >= 500:
        known[status_code] = (
            "composio_upstream_unavailable",
            "Composio 服务暂时不可用，请稍后重试。",
            True,
        )
    if status_code not in known:
        return None
    code, safe_message, retryable = known[status_code]
    detail = {
        "code": code,
        "message": safe_message,
        "provider": "composio",
        "retryable": retryable,
    }
    if code == "composio_api_key_invalid":
        detail["settings_url"] = COMPOSIO_API_KEY_SETTINGS_URL
    if request_id:
        detail["provider_request_id"] = request_id
    return {"status_code": 502 if status_code >= 500 else 503, "detail": detail}
```

- [ ] **Step 4: Run the classifier tests and prove GREEN**

Run the command from Step 2.

Expected: `4 passed` and no warning containing either test secret.

- [ ] **Step 5: Inspect the focused diff**

Run:

```bash
git diff --check -- runtime_api/app/composio_provider_errors.py runtime_api/tests/test_composio_provider_errors.py
git diff -- runtime_api/app/composio_provider_errors.py runtime_api/tests/test_composio_provider_errors.py
```

Expected: only the classifier and its tests are present. Do not commit yet because the next task establishes the API behavior that makes this unit useful.

### Task 2: Map permission failures at the FastAPI connect boundary

**Files:**
- Modify: `runtime_api/app/main.py:7350-7440`
- Modify: `runtime_api/app/main.py:11404-11413`
- Modify: `runtime_api/tests/test_auth_and_model.py:3052-3255`

- [ ] **Step 1: Add the failing endpoint contract test**

Add a test beside the existing Composio connect tests:

```python
def test_composio_connect_maps_scoped_key_permission_failure_to_actionable_403(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("COMPOSIO_API_KEY", "ak_test_secret_must_not_escape")
    from fastapi.testclient import TestClient
    from app import main

    class FakeResponse:
        status_code = 403

        def json(self):
            return {
                "error": {
                    "message": (
                        'This route requires "sessions" write access, '
                        'but the key has read access for "sessions".'
                    ),
                    "slug": "APIKey_InsufficientPermissions",
                    "request_id": "req-contract-1",
                }
            }

    class FakePermissionDeniedError(Exception):
        status_code = 403
        response = FakeResponse()
        body = response.json()

    monkeypatch.setattr(
        main,
        "get_or_create_composio_session",
        lambda user_id, session_kind: (_ for _ in ()).throw(
            FakePermissionDeniedError("ak_test_secret_must_not_escape")
        ),
    )

    response = TestClient(main.app).post(
        "/api/integrations/composio/connect/gmail",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "composio_api_key_insufficient_permissions",
        "message": "Composio API Key 权限不足，无法创建账号授权会话。",
        "provider": "composio",
        "required_permissions": [
            {"area": "sessions", "access": "read_and_write"}
        ],
        "settings_url": "https://dashboard.composio.dev",
        "retryable": False,
        "provider_request_id": "req-contract-1",
    }
    assert "ak_test_secret_must_not_escape" not in response.text
```

- [ ] **Step 2: Run the endpoint test and prove RED**

Run:

```bash
PYTHONPATH=runtime_api python3 -m pytest -q \
  runtime_api/tests/test_auth_and_model.py::test_composio_connect_maps_scoped_key_permission_failure_to_actionable_403
```

Expected: FAIL with status `500` rather than `403`.

- [ ] **Step 3: Add minimal route-boundary translation**

Import `classify_composio_provider_error` into `main.py`, then wrap only the Composio connect call:

```python
from app.composio_provider_errors import classify_composio_provider_error


def raise_classified_composio_error(error: object) -> None:
    classified = classify_composio_provider_error(error)
    if classified is None:
        return
    raise HTTPException(
        status_code=int(classified["status_code"]),
        detail=dict(classified["detail"]),
    )


@app.post("/api/integrations/composio/connect/{toolkit_slug}")
def composio_connect_toolkit(
    toolkit_slug: str,
    session_kind: str = Query(default=""),
    force: bool = Query(default=False),
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    try:
        return create_composio_connect_link(
            toolkit_slug,
            requested_kind=session_kind,
            force=force,
        )
    except HTTPException:
        raise
    except Exception as error:
        raise_classified_composio_error(error)
        raise
```

For SDK errors swallowed by `execute_live`, classify the allowlisted `live_result` before returning the existing generic `502`:

```python
    if live_result.get("status") == "failed":
        classified = classify_composio_provider_error(live_result)
        if classified is not None:
            raise HTTPException(
                status_code=int(classified["status_code"]),
                detail=dict(classified["detail"]),
            )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "composio_connect_failed",
                "message": "Composio 暂时无法创建授权链接，请稍后重试。",
                "provider": "composio",
                "retryable": True,
            },
        )
```

- [ ] **Step 4: Run focused backend tests and prove GREEN**

Run:

```bash
PYTHONPATH=runtime_api python3 -m pytest -q \
  runtime_api/tests/test_composio_provider_errors.py \
  runtime_api/tests/test_auth_and_model.py \
  -k 'composio_connect or composio_provider_error'
```

Expected: all selected tests pass, including missing-key, successful link, callback, existing-connection, and permission-error cases.

- [ ] **Step 5: Confirm unknown exceptions remain visible to diagnostics**

Add and run this focused test:

```python
def test_composio_connect_does_not_hide_unknown_internal_failure(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("COMPOSIO_API_KEY", "test-key")
    from fastapi.testclient import TestClient
    from app import main

    monkeypatch.setattr(
        main,
        "create_composio_connect_link",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("database invariant failed")),
    )

    client = TestClient(main.app, raise_server_exceptions=False)
    response = client.post(
        "/api/integrations/composio/connect/gmail",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 500
```

Expected: PASS. This prevents unrelated code defects from being mislabeled as Composio permission problems.

### Task 3: Build and test the browser guidance model

**Files:**
- Create: `runtime_api/app/static/composio-guidance.js`
- Create: `runtime_api/tests_js/composio_guidance.test.cjs`

- [ ] **Step 1: Write failing Node tests**

```javascript
const test = require("node:test");
const assert = require("node:assert/strict");

const guidance = require("../app/static/composio-guidance.js");

test("structured permission error becomes actionable Composio guidance", () => {
  const error = guidance.createApiError(403, JSON.stringify({
    detail: {
      code: "composio_api_key_insufficient_permissions",
      message: "Composio API Key 权限不足，无法创建账号授权会话。",
      settings_url: "https://dashboard.composio.dev",
      required_permissions: [{ area: "sessions", access: "read_and_write" }],
      retryable: false,
    },
  }));

  assert.deepEqual(guidance.guidanceForError(error), {
    title: "Composio API Key 权限不足",
    message: "当前 Key 无法创建授权会话。请创建具备 Sessions 读写权限的 Key，并更新 Nomi 配置。",
    settingsUrl: "https://dashboard.composio.dev",
    showSettings: true,
    showRetry: true,
  });
});

test("untrusted settings URL falls back to the fixed Composio Dashboard", () => {
  assert.equal(
    guidance.safeSettingsUrl("https://attacker.example/steal"),
    "https://dashboard.composio.dev"
  );
  assert.equal(
    guidance.safeSettingsUrl("http://dashboard.composio.dev"),
    "https://dashboard.composio.dev"
  );
});

test("generic provider failure offers retry without a settings link", () => {
  const error = guidance.createApiError(502, JSON.stringify({
    detail: {
      code: "composio_connect_failed",
      message: "Composio 暂时无法创建授权链接，请稍后重试。",
      retryable: true,
    },
  }));

  assert.equal(guidance.guidanceForError(error).showSettings, false);
  assert.equal(guidance.guidanceForError(error).showRetry, true);
});
```

- [ ] **Step 2: Run Node tests and prove RED**

Run:

```bash
node --test runtime_api/tests_js/composio_guidance.test.cjs
```

Expected: FAIL because `composio-guidance.js` does not exist.

- [ ] **Step 3: Implement the minimal browser/CommonJS module**

Use the same UMD pattern as `chat-attachments.js`:

```javascript
(function attachModule(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.NomiComposioGuidance = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createModule() {
  "use strict";

  const DASHBOARD_URL = "https://dashboard.composio.dev";

  function safeSettingsUrl(value) {
    try {
      const parsed = new URL(String(value || ""));
      if (parsed.protocol === "https:" && parsed.hostname === "dashboard.composio.dev") {
        return parsed.toString().replace(/\/$/, "");
      }
    } catch (error) {
      return DASHBOARD_URL;
    }
    return DASHBOARD_URL;
  }

  function createApiError(status, rawText) {
    let detail = {};
    try {
      const payload = JSON.parse(String(rawText || ""));
      detail = payload && typeof payload.detail === "object" ? payload.detail : payload;
    } catch (error) {
      detail = {};
    }
    const message = String(detail.message || "请求失败，请稍后重试。");
    const apiError = new Error(message);
    apiError.status = Number(status || 0);
    apiError.code = String(detail.code || "request_failed");
    apiError.settingsUrl = safeSettingsUrl(detail.settings_url);
    apiError.requiredPermissions = Array.isArray(detail.required_permissions)
      ? detail.required_permissions
      : [];
    apiError.retryable = detail.retryable !== false;
    return apiError;
  }

  function guidanceForError(error) {
    if (error && error.code === "composio_api_key_insufficient_permissions") {
      return {
        title: "Composio API Key 权限不足",
        message: "当前 Key 无法创建授权会话。请创建具备 Sessions 读写权限的 Key，并更新 Nomi 配置。",
        settingsUrl: safeSettingsUrl(error.settingsUrl),
        showSettings: true,
        showRetry: true,
      };
    }
    return {
      title: "无法生成授权链接",
      message: String(error && error.message || "Composio 暂时不可用，请稍后重试。"),
      settingsUrl: DASHBOARD_URL,
      showSettings: false,
      showRetry: true,
    };
  }

  return { DASHBOARD_URL, createApiError, guidanceForError, safeSettingsUrl };
});
```

- [ ] **Step 4: Run Node tests and prove GREEN**

Run the Step 2 command.

Expected: `3` tests pass with zero failures.

### Task 4: Wire the inline panel, external Dashboard action, and retry

**Files:**
- Modify: `runtime_api/app/static/index.html:383-385`
- Modify: `runtime_api/app/static/app.js:805-816`
- Modify: `runtime_api/app/static/app.js:4184-4235`
- Modify: `runtime_api/app/static/styles.css:1484-1524`
- Create: `runtime_api/tests/test_static_composio_guidance.py`

- [ ] **Step 1: Write the failing static integration test**

```python
from pathlib import Path


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_composio_guidance_module_loads_before_workbench_and_is_used():
    html = (STATIC / "index.html").read_text()
    app = (STATIC / "app.js").read_text()

    assert html.index('/static/composio-guidance.js') < html.index('/static/app.js')
    assert "NomiComposioGuidance.createApiError" in app
    assert "NomiComposioGuidance.guidanceForError" in app
    assert 'window.open(model.settingsUrl, "_blank", "noopener,noreferrer")' in app
    assert "打开 Composio API Key 设置" in app
    assert "重试" in app
```

- [ ] **Step 2: Run the static test and prove RED**

Run:

```bash
PYTHONPATH=runtime_api python3 -m pytest -q runtime_api/tests/test_static_composio_guidance.py
```

Expected: FAIL because the new script and wiring are absent.

- [ ] **Step 3: Load the module and parse structured API failures**

Add the module before `app.js` in `index.html`:

```html
<script src="/static/chat-attachments.js"></script>
<script src="/static/file-viewer-links.js"></script>
<script src="/static/composio-guidance.js?v=20260803-permission-guidance"></script>
<script src="/static/app.js?v=20260803-composio-permission-guidance"></script>
```

Change the non-success branch in `api()`:

```javascript
  if (!response.ok) {
    const rawError = await response.text();
    if (window.NomiComposioGuidance) {
      throw window.NomiComposioGuidance.createApiError(response.status, rawError);
    }
    throw new Error(rawError || "请求失败，请稍后重试。");
  }
```

- [ ] **Step 4: Render the inline guidance and retry action**

Inside `renderComposioPanel`, create one `aria-live` region after the grid and use a closure that retains the clicked toolkit:

```javascript
  const guidanceRegion = document.createElement("section");
  guidanceRegion.className = "composio-guidance hidden";
  guidanceRegion.setAttribute("aria-live", "polite");

  function clearGuidance() {
    guidanceRegion.classList.add("hidden");
    guidanceRegion.replaceChildren();
  }

  function showGuidance(error, retry) {
    const model = window.NomiComposioGuidance.guidanceForError(error);
    const title = document.createElement("strong");
    title.textContent = model.title;
    const message = document.createElement("p");
    message.textContent = model.message;
    const actions = document.createElement("div");
    actions.className = "composio-guidance-actions";
    if (model.showSettings) {
      const settings = button("打开 Composio API Key 设置");
      settings.classList.add("secondary");
      settings.addEventListener("click", () => {
        window.open(model.settingsUrl, "_blank", "noopener,noreferrer");
      });
      actions.appendChild(settings);
    }
    const retryButton = button("重试");
    retryButton.classList.add("secondary");
    retryButton.addEventListener("click", retry);
    actions.appendChild(retryButton);
    guidanceRegion.replaceChildren(title, message, actions);
    guidanceRegion.classList.remove("hidden");
  }
```

Replace the current anonymous click body with an `attemptConnect` closure inside the toolkit loop:

```javascript
    async function attemptConnect() {
      clearGuidance();
      connect.disabled = true;
      connect.textContent = "生成链接...";
      try {
        const result = await api(
          `/api/integrations/composio/connect/${encodeURIComponent(slug)}`,
          { method: "POST" }
        );
        if (!result.redirect_url) throw new Error("授权服务未返回链接");
        window.open(result.redirect_url, "_blank", "noopener,noreferrer");
      } catch (error) {
        showGuidance(error, attemptConnect);
      } finally {
        connect.disabled = !status.configured;
        connect.textContent = connection?.connected ? "重新连接" : "连接";
      }
    }
    connect.addEventListener("click", attemptConnect);
```

- [ ] **Step 5: Add responsive styling**

```css
.composio-guidance {
  display: grid;
  gap: 8px;
  padding: 14px;
  border: 1px solid #f3b4ad;
  border-radius: 10px;
  background: #fff4f2;
  color: #7a271a;
}

.composio-guidance p {
  margin: 0;
  color: #912018;
}

.composio-guidance-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.composio-guidance-actions button {
  min-height: 40px;
}
```

- [ ] **Step 6: Run frontend tests and prove GREEN**

Run:

```bash
node --test runtime_api/tests_js/composio_guidance.test.cjs
PYTHONPATH=runtime_api python3 -m pytest -q runtime_api/tests/test_static_composio_guidance.py
```

Expected: all Node and pytest cases pass.

### Task 5: Focused regression, deployment, and real-environment acceptance

**Files:**
- Verify all files named in Tasks 1-4.
- Deploy only the Runtime API source and static assets to `/opt/nomi` on `150.109.235.138`.

- [ ] **Step 1: Run the full focused regression set**

```bash
PYTHONPATH=runtime_api python3 -m pytest -q \
  runtime_api/tests/test_composio_provider_errors.py \
  runtime_api/tests/test_static_composio_guidance.py \
  runtime_api/tests/test_auth_and_model.py \
  -k 'composio or static_composio'
node --test \
  runtime_api/tests_js/composio_guidance.test.cjs \
  runtime_api/tests_js/chat_attachments.test.cjs \
  runtime_api/tests_js/file_viewer_links.test.cjs
git diff --check
```

Expected: zero failed tests and no whitespace errors. If unrelated pre-existing diffs make the broad `git diff --check` fail, rerun it with the exact Task 1-4 paths and report both results.

- [ ] **Step 2: Review the implementation diff without staging user changes**

```bash
git diff -- \
  runtime_api/app/composio_provider_errors.py \
  runtime_api/app/main.py \
  runtime_api/app/static/composio-guidance.js \
  runtime_api/app/static/index.html \
  runtime_api/app/static/app.js \
  runtime_api/app/static/styles.css \
  runtime_api/tests/test_composio_provider_errors.py \
  runtime_api/tests/test_auth_and_model.py \
  runtime_api/tests/test_static_composio_guidance.py \
  runtime_api/tests_js/composio_guidance.test.cjs
```

Expected: only the approved error mapping and guidance behavior is newly introduced. Leave implementation changes unstaged because `main.py` and `test_auth_and_model.py` contain pre-existing user edits.

- [ ] **Step 3: Sync and rebuild the Runtime API only**

Use the existing SSH key and known-host file. Sync explicit files so `.env`, Postgres data, and unrelated services remain untouched:

```bash
rsync -rlpt -e "ssh -4 -i ./background.pem -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/tmp/nomi_new_server_known_hosts" \
  runtime_api/app/composio_provider_errors.py \
  runtime_api/app/main.py \
  ubuntu@150.109.235.138:/opt/nomi/runtime_api/app/

rsync -rlpt -e "ssh -4 -i ./background.pem -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/tmp/nomi_new_server_known_hosts" \
  runtime_api/app/static/composio-guidance.js \
  runtime_api/app/static/index.html \
  runtime_api/app/static/app.js \
  runtime_api/app/static/styles.css \
  ubuntu@150.109.235.138:/opt/nomi/runtime_api/app/static/

ssh -4 -i ./background.pem \
  -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile=/tmp/nomi_new_server_known_hosts \
  ubuntu@150.109.235.138 \
  'cd /opt/nomi && sudo docker compose build runtime-api && sudo docker compose up -d --no-deps --force-recreate runtime-api'
```

Expected: the Runtime API image builds, one container is recreated, and database volumes are unchanged.

- [ ] **Step 4: Verify the real restricted-key API response**

```bash
curl -sS -D /tmp/nomi-composio-headers.txt \
  -o /tmp/nomi-composio-body.json \
  -X POST \
  -H 'x-par-password: par-dev' \
  http://150.109.235.138/api/integrations/composio/connect/gmail

python3 -c 'import json; p=json.load(open("/tmp/nomi-composio-body.json")); assert p["detail"]["code"] == "composio_api_key_insufficient_permissions"; assert p["detail"]["settings_url"] == "https://dashboard.composio.dev"; print(p["detail"]["code"])'
```

Expected: HTTP `403`, stable permission error code, fixed Dashboard URL, and no API Key in headers or body.

- [ ] **Step 5: Verify desktop and Android interaction**

In the desktop browser, refresh `http://150.109.235.138/#tools`, click Gmail, and confirm the inline card contains the exact title and both actions. Click the settings action and confirm a new browser tab opens on `https://dashboard.composio.dev` while the Nomi tab remains open.

On Android device `DQYTCYFMO7VSEAJB`, force-stop and reopen `com.par.assistant.android`, enter Settings → Account Connections, click Gmail, and confirm the same inline guidance is readable without horizontal clipping. Click the settings action and verify Android opens the external browser through `WebWorkspaceActivity.onCreateWindow` while Nomi remains in recents.

- [ ] **Step 6: Verify service health after acceptance**

```bash
curl -fsS -H 'x-par-password: par-dev' http://150.109.235.138/health
ssh -4 -i ./background.pem \
  -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile=/tmp/nomi_new_server_known_hosts \
  ubuntu@150.109.235.138 \
  "sudo docker inspect --format='health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} restart_count={{.RestartCount}} oom_killed={{.State.OOMKilled}}' nomi-runtime-api-1 && sudo docker logs --since 10m nomi-runtime-api-1 2>&1 | tail -200"
```

Expected: `/health` returns `{"status":"ok"}`, container health is `healthy`, restart count is stable, OOM is false, and the expected restricted-key request is logged as `403` without an uncaught ASGI traceback.

- [ ] **Step 7: Verify the success path when a write-capable Key is available**

After the user creates a Key with `Sessions: Read and write`, update only `COMPOSIO_API_KEY`, recreate `runtime-api`, and repeat the Gmail request.

Expected: HTTP `200`, `status` is `link_created` or `already_connected`, and a new link begins with `https://connect.composio.dev/`. Never print or persist the new Key outside the protected server `.env`.
