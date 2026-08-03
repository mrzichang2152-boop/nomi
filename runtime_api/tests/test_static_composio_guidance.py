from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def function_source(source: str, name: str, next_name: str) -> str:
    start = source.index(f"function {name}")
    end = source.index(f"function {next_name}", start)
    return source[start:end]


def test_composio_guidance_loads_after_shared_helpers_and_before_versioned_app():
    html = read("index.html")

    chat = 'src="/static/chat-attachments.js"'
    viewer = 'src="/static/file-viewer-links.js"'
    guidance = 'src="/static/composio-guidance.js?v=20260803-permission-guidance"'
    app = 'src="/static/app.js?v=20260803-composio-permission-guidance"'

    assert guidance in html
    assert app in html
    assert html.index(chat) < html.index(guidance)
    assert html.index(viewer) < html.index(guidance)
    assert html.index(guidance) < html.index(app)


def test_global_api_uses_safe_structured_errors_without_echoing_raw_responses():
    app = read("app.js")
    api = function_source(app, "api", "applyWorkbenchRoute")

    assert "const rawError = await response.text();" in api
    assert "window.NomiComposioGuidance" in api
    assert "createApiError(response.status, rawError)" in api
    assert 'throw new Error("请求失败，请稍后重试。");' in api
    assert "return response.json();" in api
    assert "throw new Error(await response.text())" not in api
    assert "throw new Error(rawError)" not in api


def test_composio_panel_renders_one_accessible_shared_guidance_region():
    app = read("app.js")
    panel = function_source(app, "renderComposioPanel", "renderToolCard")

    assert 'guidanceRegion.className = "composio-guidance hidden";' in panel
    assert 'guidanceRegion.setAttribute("aria-live", "polite");' in panel
    assert "node.append(grid, guidanceRegion);" in panel
    assert "function clearGuidance()" in panel
    assert "guidanceRegion.replaceChildren();" in panel
    assert 'guidanceRegion.classList.add("hidden");' in panel
    assert "function showGuidance(error, retry)" in panel
    assert "NomiComposioGuidance.guidanceForError(error)" in panel

    guidance = panel[panel.index("function showGuidance"):panel.index("for (const slug", panel.index("function showGuidance"))]
    assert "title.textContent = model.title;" in guidance
    assert "message.textContent = model.message;" in guidance
    assert "innerHTML" not in guidance


def test_composio_guidance_actions_open_safe_settings_externally_and_retry():
    app = read("app.js")
    panel = function_source(app, "renderComposioPanel", "renderToolCard")

    assert 'actions.className = "composio-guidance-actions";' in panel
    assert "model.showSettings" in panel
    assert 'button("打开 Composio API Key 设置")' in panel
    assert 'settingsButton.className = "secondary";' in panel
    assert 'window.open(model.settingsUrl, "_blank", "noopener,noreferrer")' in panel
    assert "model.showRetry" in panel
    assert 'button("重试")' in panel
    assert "retryButton.addEventListener(\"click\", retry);" in panel
    assert "location.assign" not in panel


def test_each_composio_connection_attempt_clears_guidance_and_can_retry():
    app = read("app.js")
    panel = function_source(app, "renderComposioPanel", "renderToolCard")

    assert "const attemptConnect = async () => {" in panel
    assert "clearGuidance();" in panel
    assert 'connect.textContent = "生成链接...";' in panel
    assert 'window.open(result.redirect_url, "_blank", "noopener,noreferrer")' in panel
    assert 'result.status === "already_connected"' in panel
    assert 'throw new Error("授权服务未返回链接，请重试。");' in panel
    assert "showGuidance(error, attemptConnect);" in panel
    assert 'connect.textContent = connection?.connected ? "重新连接" : "连接";' in panel
    assert 'connect.addEventListener("click", attemptConnect);' in panel
    assert "生成失败" not in panel


def test_composio_guidance_card_is_readable_accessible_and_mobile_safe():
    css = read("styles.css")

    assert ".composio-guidance {" in css
    assert ".composio-guidance p {" in css
    assert "margin: 0;" in css[css.index(".composio-guidance p {") :]
    assert ".composio-guidance-actions {" in css
    actions = css[css.index(".composio-guidance-actions {") :]
    assert "display: flex;" in actions
    assert "flex-wrap: wrap;" in actions
    assert "gap:" in actions
    assert ".composio-guidance-actions button {" in css
    buttons = css[css.index(".composio-guidance-actions button {") :]
    assert "min-height: 40px;" in buttons
    assert "max-width: 100%;" in buttons
    assert "overflow-wrap: anywhere;" in css
