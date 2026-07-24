from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")


def test_assistant_identity_is_a_first_level_view_separate_from_user_accounts():
    nav_start = HTML.index('<nav class="nav-actions"')
    nav_end = HTML.index("</nav>", nav_start)
    nav = HTML[nav_start:nav_end]

    assert 'data-view="assistantIdentitiesView"' in nav
    assert ">助理身份</button>" in nav
    assert nav.index('data-view="assistantIdentitiesView"') < nav.index('data-view="toolsView"')
    assert 'id="assistantIdentitiesView"' in HTML
    assert 'id="assistantIdentityList"' in HTML


def test_assistant_identity_view_exposes_operational_gmail_sections_without_secret_fields():
    required = [
        'id="assistantIdentityGmail"',
        'id="assistantIdentityInbox"',
        'id="assistantIdentityDrafts"',
        'id="assistantIdentityHistory"',
        'id="assistantIdentityAudit"',
        'id="refreshAssistantIdentities"',
    ]
    for fragment in required:
        assert fragment in HTML

    identity_view = HTML[
        HTML.index('id="assistantIdentitiesView"') : HTML.index('id="webSearchSettingsView"')
    ]
    assert 'type="password"' not in identity_view


def test_assistant_identity_javascript_uses_authoritative_apis_and_never_browser_storage():
    required_endpoints = [
        'api("/api/assistant-identities")',
        '`/api/assistant-identities/${identityId}/health`',
        'api("/api/assistant-inbox?limit=20")',
        'api("/api/assistant-outbound/drafts?limit=20")',
        'api("/api/assistant-outbound/messages?limit=20")',
        'api("/api/assistant-audit?limit=30")',
        'api("/api/assistant-identities/nomi_gmail_primary/connect-link"',
    ]
    for endpoint in required_endpoints:
        assert endpoint in JS

    storage_writes = re.findall(r"(?:localStorage|sessionStorage)\.setItem\(([^\n;]+)", JS)
    assert all("assistantIdentity" not in write and "connected_account" not in write for write in storage_writes)
    assert "verifiedAssistantIdentityAddress" in JS
    assert 'address === "nomi@example.com"' in JS


def test_assistant_identity_actions_cover_provider_lifecycle_and_draft_confirmation():
    for action in [
        "connectAssistantGmail",
        "verifyAssistantIdentity",
        "disableAssistantIdentity",
        "enableAssistantIdentity",
        "disconnectAssistantIdentity",
        "confirmAssistantDraft",
        "sendAssistantDraft",
    ]:
        assert f"function {action}" in JS or f"async function {action}" in JS


def test_blocked_identity_draft_can_only_be_edited_or_cancelled():
    render_start = JS.index("function renderAssistantIdentityDrafts")
    render_end = JS.index("function renderAssistantIdentityHistory", render_start)
    render = JS[render_start:render_end]

    assert 'draft.status === "draft"' in render
    assert "重试发送" not in render
    assert '["draft", "blocked"].includes(draft.status)' in render


def test_assistant_identity_layout_is_responsive_and_overflow_safe():
    assert ".assistant-identity-layout" in CSS
    assert ".assistant-identity-address" in CSS
    assert "overflow-wrap: anywhere" in CSS
    assert "@media (max-width: 860px)" in CSS
