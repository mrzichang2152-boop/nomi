from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_chat_composer_has_accessible_icon_button_input_and_integrated_tray():
    html = read("index.html")

    assert 'id="attachmentButton"' in html
    assert 'aria-label="添加附件"' in html
    assert 'title="添加附件"' in html
    assert 'class="icon-button' in html
    assert 'id="attachmentInput"' in html
    assert 'type="file"' in html
    assert "multiple" in html
    for extension in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".docx", ".pptx", ".xlsx", ".csv", ".txt", ".md"):
        assert extension in html
    assert 'id="attachmentTray"' in html
    assert 'aria-live="polite"' in html
    assert html.index('id="attachmentTray"') < html.index('id="messageInput"')


def test_static_scripts_expose_progress_retry_remove_and_authenticated_previews():
    html = read("index.html")
    app = read("app.js")
    module = read("chat-attachments.js")

    assert 'src="/static/chat-attachments.js"' in html
    assert "FormData" in app
    assert '"x-par-password"' in app.lower()
    assert "URL.createObjectURL" in app
    assert "URL.revokeObjectURL" in app
    assert "attachment-retry" in app
    assert "attachment-remove" in app
    assert "attachment-preview-fallback" in app
    assert "role = \"progressbar\"" in app or 'role="progressbar"' in app
    assert "const rawError = await response.text()" in app
    assert "await response.json()" not in app[app.index("async function attachmentApi"):app.index("function clearAttachmentPoll")]
    assert "attachment_ids" in module
    assert "client_request_id" in module
    assert "loadAuthenticatedAttachmentBlob" in app
    attachment_transport = app[
        app.index("async function loadAuthenticatedAttachmentBlob") : app.index("function renderMessageAttachments")
    ]
    assert 'searchParams.set("password"' not in attachment_transport


def test_attachment_cards_and_tray_have_mobile_safe_layout_contracts():
    css = read("styles.css")

    for selector in (
        ".composer-main",
        ".attachment-tray",
        ".attachment-draft",
        ".message-attachments",
        ".message-attachment-card",
        ".attachment-thumbnail",
        ".attachment-preview-fallback",
    ):
        assert selector in css
    assert "overflow-wrap: anywhere" in css
    assert "-webkit-line-clamp: 2" in css
    assert "min-width: 0" in css


def test_composer_does_not_add_visible_instructional_feature_copy():
    html = read("index.html")

    assert "支持上传图片、PDF、Word、PPT" not in html
    assert "选择附件后可以一起发送" not in html
