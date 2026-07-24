from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")


def test_web_search_settings_compact_list_and_detail_contract():
    required_html = [
        'data-settings-section="webSearchSettingsView"',
        'id="webSearchSettingsView"',
        'id="webSearchProviderList"',
        'id="webSearchConfiguredSummary"',
        'id="webSearchProviderDetail"',
        'id="webSearchProviderDetailTitle"',
        'id="webSearchKeyInput" type="password"',
        'id="webSearchSaveAndTest"',
        'id="webSearchTestStored"',
        'id="webSearchDeleteKey"',
        'id="webSearchEnabledToggle"',
        'id="webSearchToggleKeyVisibility"',
        'id="webSearchLastTestedAt"',
        'id="webSearchRoutingStrategy"',
        'id="webSearchRoutingOrder"',
    ]

    for fragment in required_html:
        assert fragment in HTML


def test_web_search_settings_javascript_uses_authenticated_settings_endpoints():
    required_endpoints = [
        'api("/api/web-search/settings")',
        '`/api/web-search/settings/${provider}`',
        '`/api/web-search/settings/${provider}/test`',
        '`/api/web-search/settings/${provider}/key`',
        'api("/api/web-search/settings/routing"',
    ]

    for endpoint in required_endpoints:
        assert endpoint in JS


def test_web_search_api_keys_are_never_written_to_browser_storage():
    storage_writes = re.findall(
        r"(?:localStorage|sessionStorage)\.setItem\(([^\n;]+)",
        JS,
    )

    assert all("webSearch" not in write and "api_key" not in write for write in storage_writes)
    assert "webSearchKeyInput.value = \"\"" in JS
    assert 'webSearchKeyInput.type = webSearchKeyInput.type === "password" ? "text" : "password"' in JS
    assert 'webSearchKeyInput.type = "password"' in JS


def test_web_search_ui_refreshes_failed_health_and_excludes_invalid_provider_count():
    test_function = JS[
        JS.index("async function testStoredWebSearchProvider"):
        JS.index("async function updateWebSearchProviderEnabled")
    ]

    assert 'item.connection_status !== "invalid_key"' in JS
    assert "finally {\n    await loadWebSearchSettings({ reopenProvider: provider });" in test_function
    assert 'message.includes("provider_secret_error")' in JS
    assert "WEB_SEARCH_CONFIG_ENCRYPTION_SECRET" in JS


def test_web_search_settings_have_mobile_safe_touch_and_scroll_styles():
    assert ".web-search-provider-row" in CSS
    assert "min-height: 44px" in CSS
    assert ".web-search-provider-detail" in CSS
    assert "overflow-y: auto" in CSS


def test_web_search_encryption_secret_is_exposed_to_runtime_container():
    repository_root = ROOT.parent
    compose = (repository_root / "docker-compose.yml").read_text(encoding="utf-8")
    env_example = (repository_root / ".env.example").read_text(encoding="utf-8")

    assert "WEB_SEARCH_CONFIG_ENCRYPTION_SECRET:" in compose
    assert "WEB_SEARCH_CONFIG_ENCRYPTION_SECRET=" in env_example
