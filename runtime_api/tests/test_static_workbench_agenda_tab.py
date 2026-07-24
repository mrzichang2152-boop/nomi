import os
import sys
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def read_static(name: str) -> str:
    return (ROOT / "app" / "static" / name).read_text(encoding="utf-8")


def workbench_nav_html(html: str) -> str:
    start = html.index('<nav class="nav-actions"')
    end = html.index("</nav>", start)
    return html[start:end]


def test_workbench_javascript_is_parseable():
    result = subprocess.run(
        ["node", "--check", str(ROOT / "app" / "static" / "app.js")],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_workbench_has_dedicated_agenda_navigation_and_view():
    html = read_static("index.html")

    assert 'data-view="agendaView"' in html
    assert "日程" in html
    assert 'id="agendaView"' in html
    assert 'id="refreshAgenda"' in html
    assert 'id="agendaDayTabs"' in html
    assert 'id="agendaContent"' in html

    nav = workbench_nav_html(html)
    nav_order = [
        nav.index('data-view="chatView"'),
        nav.index('data-view="agendaView"'),
        nav.index('data-view="searchView"'),
    ]
    assert nav_order == sorted(nav_order)


def test_workbench_has_dedicated_career_navigation_and_view():
    html = read_static("index.html")

    assert 'data-view="careerView"' in html
    assert "求职" in html
    assert 'id="careerView"' in html
    assert 'id="refreshCareer"' in html
    assert 'id="careerOffers"' in html
    assert 'id="careerAtsPreviewForm"' in html
    assert 'id="careerAtsPreviewUrl"' in html
    assert 'id="careerAtsListPreview"' in html
    assert 'id="careerProfileIngestForm"' in html
    assert 'id="careerResumeText"' in html
    assert 'id="careerTargetRoles"' in html
    assert 'id="careerTargetLocations"' in html
    assert 'id="careerResumeFileImportForm"' in html
    assert 'id="careerResumeFile"' in html
    assert 'id="careerResumeLibrary"' in html
    assert 'id="careerContent"' in html

    nav = workbench_nav_html(html)
    nav_order = [
        nav.index('data-view="chatView"'),
        nav.index('data-view="agendaView"'),
        nav.index('data-view="careerView"'),
        nav.index('data-view="searchView"'),
    ]
    assert nav_order == sorted(nav_order)


def test_desktop_sidebar_keeps_navigation_compact_and_top_aligned():
    css = read_static("styles.css")
    sidebar_start = css.index(".sidebar {")
    sidebar_end = css.index("}", sidebar_start)
    sidebar_rule = css[sidebar_start:sidebar_end]

    assert "justify-content: flex-start" in sidebar_rule
    assert "gap: 32px" in sidebar_rule
    assert "overflow-y: auto" in sidebar_rule
    assert "justify-content: space-between" not in sidebar_rule


def test_workbench_versions_core_stylesheet_to_avoid_stale_layout():
    html = read_static("index.html")

    assert 'href="/static/styles.css?v=20260723-chat-inline-drafts"' in html


def test_mobile_assistant_shell_prioritizes_chat_and_moves_tools_to_settings():
    html = read_static("index.html")
    css = read_static("styles.css")
    js = read_static("app.js")

    assert 'class="assistant-topbar"' in html
    assert 'id="assistantSettingsToggle"' in html
    assert 'id="assistantCloseButton"' in html
    assert 'id="assistantWorkspaceToggle"' not in html
    assert 'title="关闭对话框"' in html
    assert 'id="assistantSettingsPanel"' in html
    assert 'class="assistant-settings-grid"' in html
    assert 'data-view="agendaView"' in html
    assert 'data-view="careerView"' in html
    assert 'data-action="full-workspace"' not in html
    assert "完整工作台" not in html
    assert "账号连接" in html
    assert "记忆治理" in html

    assert ".assistant-topbar" in css
    assert ".assistant-settings-panel" in css
    assert "@media (max-width: 860px)" in css
    assert ".assistant-topbar" in css
    assert ".sidebar" in css and "display: none" in css
    assert ".app-panel.full-workspace" not in css
    assert "--assistant-topbar-height" in css
    assert "grid-template-rows: var(--assistant-topbar-height) minmax(0, 1fr)" in css

    assert 'document.querySelector("#assistantSettingsToggle")' in js
    assert 'document.querySelector("#assistantCloseButton")' in js
    assert 'document.querySelector("#assistantSettingsPanel")' in js
    assert "toggleAssistantSettings" in js
    assert "closeAssistantWorkspace" in js
    assert "window.NomiAndroid.closeWorkspace()" in js
    assert "setAssistantWorkspaceMode" not in js
    assert "workspaceModeKey" not in js
    assert "assistant-settings-item" in js


def test_account_connection_view_title_matches_settings_entry():
    html = read_static("index.html")

    settings_entry = '<button class="assistant-settings-item" data-view="toolsView" type="button">'
    assert settings_entry in html
    assert '<button class="nav-button" data-view="toolsView" type="button">账号</button>' in html
    assert "<strong>账号连接</strong>" in html
    tools_view_start = html.index('<section id="toolsView" class="view settings-child-view">')
    tools_view_header = html[tools_view_start : html.index("</header>", tools_view_start)]
    assert "<h2>账号连接</h2>" in tools_view_header
    assert "<h2>工具目录</h2>" not in tools_view_header


def test_settings_items_keep_dedicated_hash_routes_instead_of_falling_back_to_chat():
    js = read_static("app.js")

    assert "const viewHashMap" in js
    assert 'toolsView: "tools"' in js
    assert 'agendaView: "agenda"' in js
    assert 'careerView: "career"' in js
    assert "function viewIdFromHash" in js
    assert 'switchView(viewIdFromHash(location.hash) || "chatView")' in js

    settings_handler_start = js.index('document.querySelectorAll(".assistant-settings-item")')
    settings_handler_end = js.index('document.querySelectorAll("[data-action=\\"back-to-settings\\"]")', settings_handler_start)
    settings_handler = js[settings_handler_start:settings_handler_end]
    assert "hashForView(buttonNode.dataset.view)" in settings_handler
    assert 'buttonNode.dataset.view === "chatView" ? "chat" : ""' not in settings_handler

    hashchange_start = js.index('window.addEventListener("hashchange"')
    hashchange_end = js.index('window.addEventListener("nomi-pending-proactive"', hashchange_start)
    hashchange_handler = js[hashchange_start:hashchange_end]
    assert "viewIdFromHash(location.hash)" in hashchange_handler
    assert 'if (location.hash === "#chat") switchView("chatView");' not in hashchange_handler


def test_account_connection_view_keeps_browser_login_channels_visible():
    js = read_static("app.js")

    assert "renderBrowserLoginPanel" in js
    assert "云端浏览器登录" in js
    assert "web.whatsapp.com" in js
    assert "web.telegram.org" in js
    assert "linkedin.com/login" in js
    assert "browserLoginChannels" in js
    assert "whatsapp" in js
    assert "telegram" in js
    assert "linkedin" in js


def test_account_connection_remote_browser_url_uses_readable_no_vnc_mode():
    js = read_static("app.js")

    assert "vnc.html" in js
    assert "resize: \"scale\"" in js
    assert "view_clip" not in js
    assert "vnc_lite.html" not in js
    assert "scale: \"true\"" not in js


def test_account_connection_notifies_android_before_opening_remote_browser():
    js = read_static("app.js")

    assert "function enterRemoteBrowserMode" in js
    assert "window.NomiAndroid.enterRemoteBrowserMode()" in js
    open_start = js.index("open.addEventListener")
    open_end = js.index("row.append(label, open)", open_start)
    login_handler = js[open_start:open_end]
    assert login_handler.index("enterRemoteBrowserMode()") < login_handler.index("openExternalUrl(url)")


def test_account_connection_renders_browser_login_before_remote_status_calls():
    js = read_static("app.js")
    load_tools_start = js.index("async function loadTools()")
    load_tools_end = js.index("function collectorBySource", load_tools_start)
    load_tools = js[load_tools_start:load_tools_end]

    first_browser_panel = load_tools.index("renderBrowserLoginPanel")
    first_catalog_request = load_tools.index('api("/api/tools/catalog")')

    assert first_browser_panel < first_catalog_request
    assert '"工具目录暂时不可用，网页登录入口仍可继续使用。"' in load_tools


def test_account_connection_buttons_stay_readable_on_mobile():
    css = read_static("styles.css")

    assert ".connection-row button" in css
    assert "white-space: nowrap" in css
    assert "min-width: 104px" in css


def test_sensitive_field_release_lives_in_privacy_management_not_account_connection():
    html = read_static("index.html")
    css = read_static("styles.css")

    assert '<button class="assistant-settings-item" data-view="privacyView" type="button">' in html
    assert "<strong>隐私管理</strong>" in html
    assert '<section id="privacyView" class="view settings-child-view">' in html

    privacy_start = html.index('<section id="privacyView" class="view settings-child-view">')
    privacy_html = html[privacy_start : html.index("</section>", privacy_start)]
    assert 'id="fieldReleaseForm"' in privacy_html
    assert 'id="fieldReleaseName"' in privacy_html
    assert 'id="fieldReleaseValue"' in privacy_html
    assert 'id="fieldReleasePurpose"' in privacy_html
    assert "放行字段" in privacy_html

    tools_start = html.index('<section id="toolsView" class="view settings-child-view">')
    tools_html = html[tools_start : html.index("</section>", tools_start)]
    assert 'id="toolRouteForm"' not in tools_html
    assert 'id="toolRouteInput"' not in tools_html
    assert "看看 Nomi 会走哪个 Pipeline 或工具" not in tools_html
    assert 'id="fieldReleaseForm"' not in tools_html
    assert 'id="fieldReleaseName"' not in tools_html
    assert "放行字段" not in tools_html

    assert "#privacyView.active" in css
    assert ".privacy-explainer" in css


def test_settings_child_views_have_back_to_settings_controls():
    html = read_static("index.html")
    js = read_static("app.js")

    settings_child_views = [
        "agendaView",
        "careerView",
        "suggestionsView",
        "toolsView",
        "privacyView",
        "governanceView",
        "collectorsView",
        "searchView",
    ]
    for view_id in settings_child_views:
        view_start = html.index(f'<section id="{view_id}" class="view settings-child-view">')
        view_header = html[view_start : html.index("</header>", view_start)]
        assert "back-to-settings" in view_header
        assert 'data-action="back-to-settings"' in view_header
        assert "返回设置" in view_header

    assert 'document.querySelectorAll("[data-action=\\"back-to-settings\\"]")' in js
    assert "returnToAssistantSettings" in js
    assert 'switchView("chatView")' in js
    assert "toggleAssistantSettings(true)" in js


def test_proactive_messages_render_as_chat_cards_in_compact_assistant():
    js = read_static("app.js")

    assert "function addProactiveSuggestionCard" in js
    assert "suggestion-inline-card" in js
    assert "可能需要关注" in js
    assert "event.suggestion_id || event.id" in js
    assert "addProactiveSuggestionCard(event)" in js
    assert "function shouldPreserveCurrentViewForAssistantEvent" in js
    assert "renderAssistantEventWithoutStealingView" in js


def test_realtime_assistant_events_do_not_steal_settings_child_views():
    js = read_static("app.js")

    helper_start = js.index("function shouldPreserveCurrentViewForAssistantEvent")
    helper_end = js.index("function renderAssistantEventWithoutStealingView", helper_start)
    helper = js[helper_start:helper_end]
    assert "viewIdFromHash(location.hash)" in helper
    assert '"chatView"' in helper

    realtime_start = js.index("function handleRealtimeMessage(event)")
    realtime_end = js.index("function consumePendingProactive()", realtime_start)
    realtime_handler = js[realtime_start:realtime_end]
    assert "renderAssistantEventWithoutStealingView" in realtime_handler
    assert 'location.hash = "chat"' not in realtime_handler

    pending_start = js.index("function consumePendingProactive()")
    pending_end = js.index("function consumePendingAgentEvent()", pending_start)
    pending_handler = js[pending_start:pending_end]
    assert "renderAssistantEventWithoutStealingView" in pending_handler
    assert 'location.hash = "chat"' not in pending_handler


def test_chat_messages_wrap_long_urls_inside_bubbles():
    css = read_static("styles.css")

    message_start = css.index(".message {")
    message_end = css.index(".message.user", message_start)
    message_css = css[message_start:message_end]
    assert "overflow-wrap: anywhere" in message_css
    assert "word-break: break-word" in message_css
    assert "min-width: 0" in message_css

    assert ".message a" in css
    assert ".suggestion-inline-card" in css
    assert "overflow-wrap: anywhere" in css


def test_workbench_chat_history_prefers_conversation_id_from_url():
    js = read_static("app.js")

    assert "function conversationIdFromUrl()" in js
    assert "window.location?.search || \"\"" in js
    assert "new URLSearchParams(search)" in js
    assert 'params.get("conversation_id")' in js
    assert 'key === "conversation_id"' in js
    assert "let chatConversationId = conversationIdFromUrl() || localStorage.getItem(conversationKey) || \"\";" in js
    assert "if (conversationIdFromUrl()) setChatConversationId(conversationIdFromUrl());" in js


def test_workbench_reports_conversation_id_to_android_bridge():
    js = read_static("app.js")

    assert "function notifyAndroidConversationId" in js
    assert "window.NomiAndroid?.updateConversationId" in js
    assert "window.NomiAndroid.updateConversationId(chatConversationId)" in js
    assert "notifyAndroidConversationId()" in js


def test_proactive_job_recommendation_actions_can_open_job_url_directly():
    js = read_static("app.js")

    assert "url: action.url || \"\"" in js
    assert "if (action.url)" in js
    assert "openExternalUrl(action.url)" in js
    assert "event.actions || event.metadata?.actions" in js


def test_proactive_job_recommendation_card_uses_clickable_bounded_links():
    js = read_static("app.js")
    css = read_static("styles.css")

    assert "function renderProactiveJobRecommendationCard" in js
    assert "job-recommendation-card" in js
    assert "job-recommendation-link" in js
    assert "anchor.href = job.url" in js
    assert "anchor.target = \"_blank\"" in js
    assert "anchor.rel = \"noopener\"" in js
    assert "anchor.addEventListener(\"click\"" in js
    assert "openExternalUrl(job.url)" in js
    assert "recommended_jobs" in js
    assert ".job-recommendation-link" in css
    assert "overflow-wrap: anywhere" in css
    assert "word-break: break-word" in css


def test_android_workspace_close_is_owned_by_web_topbar_bridge():
    activity = (ROOT.parent / "android_app" / "app" / "src" / "main" / "java" / "com" / "par" / "assistant" / "android" / "WebWorkspaceActivity.java").read_text(encoding="utf-8")

    assert 'addJavascriptInterface(new WorkspaceBridge(), "NomiAndroid")' in activity
    assert "@JavascriptInterface" in activity
    assert "public void closeWorkspace()" in activity
    assert "runOnUiThread(WebWorkspaceActivity.this::closeWorkspace)" in activity
    assert "Button close = new Button" not in activity
    assert "root.addView(close" not in activity


def test_workbench_loads_and_manages_agenda_items_from_runtime_api():
    js = read_static("app.js")

    assert 'document.querySelector("#agendaContent")' in js
    assert 'document.querySelector("#refreshAgenda")' in js
    assert 'if (viewId === "agendaView") loadAgenda();' in js
    assert "loadAgenda()" in js
    assert 'api("/api/agenda?limit=50")' in js
    assert "renderAgendaDayTabs" in js
    assert "selectedAgendaDate" in js
    assert "agendaDateKeyForItem" in js
    assert "formatAgendaTimeWindow(timeWindow = {}, item = {})" in js
    assert "renderAgendaItem" in js
    assert "updateAgendaItemStatus" in js
    assert "snoozeAgendaItem" in js
    assert 'api(`/api/agenda/${id}`' in js
    assert 'api(`/api/agenda/${id}/snooze`' in js


def test_workbench_loads_and_manages_career_board_from_runtime_api():
    js = read_static("app.js")

    assert 'document.querySelector("#careerResumeLibrary")' in js
    assert 'document.querySelector("#careerContent")' in js
    assert 'document.querySelector("#careerAtsPreviewForm")' in js
    assert 'document.querySelector("#careerAtsPreviewUrl")' in js
    assert 'document.querySelector("#careerAtsListPreview")' in js
    assert 'document.querySelector("#careerProfileIngestForm")' in js
    assert 'document.querySelector("#careerResumeText")' in js
    assert 'document.querySelector("#careerTargetRoles")' in js
    assert 'document.querySelector("#careerTargetLocations")' in js
    assert 'document.querySelector("#careerResumeFileImportForm")' in js
    assert 'document.querySelector("#careerResumeFile")' in js
    assert 'document.querySelector("#refreshCareer")' in js
    assert 'document.querySelector("#careerOffers")' in js
    assert 'if (viewId === "careerView") loadCareerBoard();' in js
    assert "loadCareerBoard()" in js
    assert 'api("/api/career/board?limit=50")' in js
    assert 'api("/api/career/offers")' in js
    assert "career_resumes" in js
    assert "renderCareerResumeLibrary" in js
    assert "renderCareerBaseResumeCard" in js
    assert "careerResumeSummaryText" in js
    assert "setDefaultCareerResume" in js
    assert "deleteCareerResume" in js
    assert 'api(`/api/career/resumes/${resumeId}`' in js
    assert 'method: "DELETE"' in js
    assert "loadCareerOffers" in js
    assert "renderCareerOffers" in js
    assert 'api("/api/career/ats/preview"' in js
    assert 'api("/api/career/ats/list-preview"' in js
    assert "previewCareerAtsList" in js
    assert 'api("/api/career/profile/ingest"' in js
    assert 'api("/api/career/resumes/import"' in js
    assert 'api("/api/career/resumes/export"' in js
    assert "importCareerResumeFile" in js
    assert "exportCareerResumeDraft" in js
    assert "downloadCareerArtifact" in js
    assert "renderCareerAtsPreview" in js
    assert "renderCareerProfileIngestResult" in js
    assert "careerAtsPreviewText" in js
    assert "renderCareerOpportunityCard" in js
    assert "careerApplicationStatusText" in js
    assert "updateCareerApplicationStatus" in js
    assert 'api(`/api/career/applications/${applicationId}`' in js
    assert "标记已投递" in js
    assert "忽略" in js


def test_workbench_opens_career_opportunity_detail_with_grounded_drafts():
    js = read_static("app.js")

    assert "loadCareerDetail" in js
    assert "renderCareerDetail" in js
    assert "careerDetailText" in js
    assert "返回看板" in js
    assert "查看详情" in js
    assert 'api(`/api/career/opportunities/${jobId}`' in js
    assert "Cover Letter" in js
    assert "外联草稿" in js
    assert "面试准备" in js
    assert "drafts_are_not_sent" in js
    assert "renderCareerResumeSectionEditor" in js
    assert "readCareerEditedResumeSections" in js
    assert "data-career-resume-section" in js
    assert "简历逐段编辑" in js


def test_career_board_card_text_combines_job_fit_application_and_resume_context():
    script = r"""
const fs = require("fs");
const vm = require("vm");
const path = process.argv[1];
function element() {
  return {
    classList: { add() {}, remove() {}, toggle() {} },
    style: { setProperty() {} },
    children: [],
    value: "",
    textContent: "",
    innerHTML: "",
    dataset: {},
    append(...nodes) { this.children.push(...nodes); },
    appendChild(node) { this.children.push(node); return node; },
    remove() {},
    setAttribute() {},
    addEventListener() {},
    querySelector() { return element(); },
    scrollIntoView() {},
    blur() {},
    focus() {},
    setSelectionRange() {},
  };
}
const document = {
  documentElement: { style: { setProperty() {} } },
  querySelector() { return element(); },
  querySelectorAll() { return []; },
  createElement() { return element(); },
};
const windowObj = {
  addEventListener() {},
  dispatchEvent() {},
  visualViewport: null,
  innerHeight: 900,
  location: { hash: "" },
};
const context = {
  window: windowObj,
  document,
  localStorage: { getItem() { return ""; }, setItem() {}, removeItem() {} },
  location: windowObj.location,
  setTimeout,
  clearTimeout,
  console,
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  Event: function Event() {},
};
windowObj.window = windowObj;
vm.createContext(context);
vm.runInContext(fs.readFileSync(path, "utf8"), context);
const debug = context.window.nomiCareerDebug;
if (!debug) throw new Error("missing nomiCareerDebug");
const text = debug.careerOpportunityCardText(
  {
    id: "job_pm_ai_1",
    title: "AI Product Manager",
    company: "Example AI",
    location: "Shanghai",
    fit_score: 0.82,
    status: "tracked",
    payload: { matched_requirements: ["LLM product", "workflow automation"], gap_requirements: ["B2B SaaS"] },
  },
  {
    id: "application_job_pm_ai_1_submit_application",
    status: "blocked_until_delegated_grant",
    stage: "apply_submit_blocked",
    next_step: "request_delegated_grant_and_target_manifest",
  },
  {
    status: "draft",
    payload: { changes: [{ section: "summary", change: "突出 LLM product" }] },
  }
);
for (const expected of [
  "Example AI · Shanghai",
  "匹配度：0.82",
  "匹配项：LLM product、workflow automation",
  "差距：B2B SaaS",
  "应用阶段：等待授权",
  "下一步：申请分级授权并确认投递范围",
  "简历草稿：summary：突出 LLM product",
]) {
  if (!text.includes(expected)) throw new Error(`missing ${expected} in ${text}`);
}
"""
    result = subprocess.run(
        ["node", "-e", script, str(ROOT / "app" / "static" / "app.js")],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_career_detail_text_includes_drafts_interview_and_confirmation_state():
    script = r"""
const fs = require("fs");
const vm = require("vm");
const path = process.argv[1];
function element() {
  return {
    classList: { add() {}, remove() {}, toggle() {} },
    style: { setProperty() {} },
    children: [],
    value: "",
    textContent: "",
    innerHTML: "",
    dataset: {},
    append(...nodes) { this.children.push(...nodes); },
    appendChild(node) { this.children.push(node); return node; },
    remove() {},
    setAttribute() {},
    addEventListener() {},
    querySelector() { return element(); },
    scrollIntoView() {},
    blur() {},
    focus() {},
    setSelectionRange() {},
  };
}
const document = {
  documentElement: { style: { setProperty() {} } },
  querySelector() { return element(); },
  querySelectorAll() { return []; },
  createElement() { return element(); },
};
const windowObj = {
  addEventListener() {},
  dispatchEvent() {},
  visualViewport: null,
  innerHeight: 900,
  location: { hash: "" },
};
const context = {
  window: windowObj,
  document,
  localStorage: { getItem() { return ""; }, setItem() {}, removeItem() {} },
  location: windowObj.location,
  setTimeout,
  clearTimeout,
  console,
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  Event: function Event() {},
};
windowObj.window = windowObj;
vm.createContext(context);
vm.runInContext(fs.readFileSync(path, "utf8"), context);
const debug = context.window.nomiCareerDebug;
const text = debug.careerDetailText({
  opportunity: { title: "AI Product Manager", company: "Example AI", location: "Shanghai", requirements: ["LLM product"] },
  fit_summary: { fit_score: 0.82, matched_requirements: ["LLM product"], gap_requirements: ["B2B SaaS"], evidence_ids: ["jd_evt_1"] },
  resume_draft: { payload: { changes: [{ section: "summary", change: "突出 LLM product" }] } },
  cover_letter_draft: { send_blocked: true, draft: { subject: "Application interest", body: "LLM product and workflow automation" } },
  outreach_draft: { confirmation_card: { final_user_confirmation: true }, draft: { recipient: "Maya", body: "Hi Maya" } },
  interview_prep: { prep_brief: { talking_points: ["LLM product"], risk_questions: ["如何解释 B2B SaaS?"] } },
  generated_from: { drafts_are_not_sent: true },
});
for (const expected of [
  "AI Product Manager · Example AI",
  "匹配度：0.82",
  "证据：jd_evt_1",
  "简历草案：summary：突出 LLM product",
  "Cover Letter（未发送）：Application interest",
  "外联草稿（需确认）：Maya",
  "面试准备：LLM product",
  "风险问题：如何解释 B2B SaaS?",
  "所有草稿均未发送",
]) {
  if (!text.includes(expected)) throw new Error(`missing ${expected} in ${text}`);
}
"""
    result = subprocess.run(
        ["node", "-e", script, str(ROOT / "app" / "static" / "app.js")],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_career_ats_preview_text_is_read_only_and_actionable():
    script = r"""
const fs = require("fs");
const vm = require("vm");
const path = process.argv[1];
function element() {
  return {
    classList: { add() {}, remove() {}, toggle() {} },
    style: { setProperty() {} },
    children: [],
    value: "",
    textContent: "",
    innerHTML: "",
    dataset: {},
    append(...nodes) { this.children.push(...nodes); },
    appendChild(node) { this.children.push(node); return node; },
    remove() {},
    setAttribute() {},
    addEventListener() {},
    querySelector() { return element(); },
    scrollIntoView() {},
    blur() {},
    focus() {},
    setSelectionRange() {},
  };
}
const document = {
  documentElement: { style: { setProperty() {} } },
  querySelector() { return element(); },
  querySelectorAll() { return []; },
  createElement() { return element(); },
};
const windowObj = {
  addEventListener() {},
  dispatchEvent() {},
  visualViewport: null,
  innerHeight: 900,
  location: { hash: "" },
};
const context = {
  window: windowObj,
  document,
  localStorage: { getItem() { return ""; }, setItem() {}, removeItem() {} },
  location: windowObj.location,
  setTimeout,
  clearTimeout,
  console,
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  Event: function Event() {},
};
windowObj.window = windowObj;
vm.createContext(context);
vm.runInContext(fs.readFileSync(path, "utf8"), context);
const text = context.window.nomiCareerDebug.careerAtsPreviewText({
  status: "completed_read_only",
  source: "greenhouse_public",
  writeback_performed: false,
  next_actions: ["匹配简历", "生成外联草稿", "加入机会跟踪"],
  job_opportunities: [{
    title: "AI Product Manager",
    company: "Example AI",
    location: "Shanghai",
    source_event_ids: ["ats_preview_1"],
    requirements: ["LLM product", "workflow automation"],
  }],
});
for (const expected of [
  "AI Product Manager · Example AI",
  "来源：greenhouse_public",
  "要求：LLM product、workflow automation",
  "下一步：匹配简历、生成外联草稿、加入机会跟踪",
  "只读预览，尚未写入求职看板",
]) {
  if (!text.includes(expected)) throw new Error(`missing ${expected} in ${text}`);
}
"""
    result = subprocess.run(
        ["node", "-e", script, str(ROOT / "app" / "static" / "app.js")],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_career_resume_summary_text_marks_default_and_parsed_excerpt():
    script = r"""
const fs = require("fs");
const vm = require("vm");
const path = process.argv[1];
function element() {
  return {
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    style: { setProperty() {} },
    children: [],
    value: "",
    textContent: "",
    innerHTML: "",
    dataset: {},
    append(...nodes) { this.children.push(...nodes); },
    appendChild(node) { this.children.push(node); return node; },
    remove() {},
    setAttribute() {},
    addEventListener() {},
    querySelector() { return element(); },
    querySelectorAll() { return []; },
    scrollIntoView() {},
    blur() {},
    focus() {},
    setSelectionRange() {},
  };
}
const document = {
  documentElement: { style: { setProperty() {} } },
  querySelector() { return element(); },
  querySelectorAll() { return []; },
  createElement() { return element(); },
};
const windowObj = {
  addEventListener() {},
  dispatchEvent() {},
  visualViewport: null,
  innerHeight: 900,
  location: { hash: "" },
};
const context = {
  window: windowObj,
  document,
  localStorage: { getItem() { return ""; }, setItem() {}, removeItem() {} },
  location: windowObj.location,
  setTimeout,
  clearTimeout,
  console,
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  Event: function Event() {},
};
windowObj.window = windowObj;
vm.createContext(context);
vm.runInContext(fs.readFileSync(path, "utf8"), context);
const text = context.window.nomiCareerDebug.careerResumeSummaryText({
  id: "career_resume_base_1",
  filename: "base-product-resume.docx",
  file_type: "docx",
  status: "active",
  parsed_text_summary: "Product leader with LLM product, workflow automation, and data analysis experience.",
  source_event_ids: ["resume_evt_1"],
  payload: { is_default: true },
});
for (const expected of [
  "base-product-resume.docx · docx",
  "默认基础简历",
  "解析摘要：Product leader with LLM product, workflow automation, and data analysis experience.",
  "来源证据：resume_evt_1",
]) {
  if (!text.includes(expected)) throw new Error(`missing ${expected} in ${text}`);
}
"""
    result = subprocess.run(
        ["node", "-e", script, str(ROOT / "app" / "static" / "app.js")],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_career_resume_draft_sections_can_be_overridden_before_export():
    script = r"""
const fs = require("fs");
const vm = require("vm");
const path = process.argv[1];
function element() {
  return {
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    style: { setProperty() {} },
    children: [],
    value: "",
    textContent: "",
    innerHTML: "",
    dataset: {},
    append(...nodes) { this.children.push(...nodes); },
    appendChild(node) { this.children.push(node); return node; },
    remove() {},
    setAttribute() {},
    addEventListener() {},
    querySelector(selector) {
      if (selector === ".career-section-title") return { value: this.dataset.title || "" };
      if (selector === ".career-section-body") return { value: this.dataset.body || "" };
      return element();
    },
    querySelectorAll() { return []; },
    scrollIntoView() {},
    blur() {},
    focus() {},
    setSelectionRange() {},
  };
}
const editedSection = element();
editedSection.dataset.title = "Summary";
editedSection.dataset.body = "Edited summary focused on LLM product evidence.";
const document = {
  documentElement: { style: { setProperty() {} } },
  querySelector() { return element(); },
  querySelectorAll(selector) {
    return selector === "[data-career-resume-section]" ? [editedSection] : [];
  },
  createElement() { return element(); },
};
const windowObj = {
  addEventListener() {},
  dispatchEvent() {},
  visualViewport: null,
  innerHeight: 900,
  location: { hash: "" },
};
const calls = [];
const context = {
  window: windowObj,
  document,
  localStorage: { getItem() { return ""; }, setItem() {}, removeItem() {} },
  location: windowObj.location,
  setTimeout,
  clearTimeout,
  console,
  fetch: async (url, options) => {
    calls.push({ url, body: JSON.parse(options.body) });
    return { ok: true, json: async () => ({ content_base64: "WA==", filename: "x.docx" }) };
  },
  Blob: function Blob() {},
  Uint8Array,
  atob(value) { return Buffer.from(value, "base64").toString("binary"); },
  URL: { createObjectURL() { return "blob:test"; }, revokeObjectURL() {} },
  Event: function Event() {},
};
windowObj.window = windowObj;
vm.createContext(context);
vm.runInContext(fs.readFileSync(path, "utf8"), context);
(async () => {
  await context.window.nomiCareerDebug.exportCareerResumeDraft({
    opportunity: { title: "AI Product Manager", company: "Example AI" },
    fit_summary: { evidence_ids: ["jd_evt_1"] },
    generated_from: { source_event_ids: ["jd_evt_1"] },
  }, "docx");
  if (calls.length !== 1) throw new Error("export API was not called");
  const payload = calls[0].body;
  if (payload.sections.length !== 1) throw new Error(`unexpected sections ${JSON.stringify(payload.sections)}`);
  if (payload.sections[0].title !== "Summary") throw new Error(`unexpected title ${payload.sections[0].title}`);
  if (payload.sections[0].body !== "Edited summary focused on LLM product evidence.") {
    throw new Error(`unexpected body ${payload.sections[0].body}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    result = subprocess.run(
        ["node", "-e", script, str(ROOT / "app" / "static" / "app.js")],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


class Cursor:
    rowcount = 1

    def __init__(self, rows=None):
        self.rows = rows or []

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


def install_fake_db(monkeypatch, main, handler):
    executed = []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            executed.append((normalized, params))
            return handler(normalized, params)

    monkeypatch.setattr(main, "db", lambda: Conn())
    return executed


def career_base_resume_row(status="active", payload=None):
    return (
        "career_resume_base_1",
        "base-product-resume.docx",
        "docx",
        status,
        ["resume_evt_1"],
        "Product leader with LLM product, workflow automation, and data analysis experience. " * 8,
        payload or {"is_default": True},
        "2026-06-08T09:00:00+08:00",
        "2026-06-08T09:30:00+08:00",
    )


def test_career_board_returns_base_resumes_with_parsed_summaries(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    def handler(sql, params):
        if "FROM career_resumes" in sql:
            assert "status <> 'deleted'" in sql
            return Cursor([career_base_resume_row()])
        return Cursor()

    install_fake_db(monkeypatch, main, handler)
    response = TestClient(main.app).get("/api/career/board", headers={"x-par-password": "secret"})

    assert response.status_code == 200
    resumes = response.json()["career_resumes"]
    assert resumes[0]["id"] == "career_resume_base_1"
    assert resumes[0]["filename"] == "base-product-resume.docx"
    assert resumes[0]["payload"]["is_default"] is True
    assert "LLM product" in resumes[0]["parsed_text_summary"]
    assert "parsed_text" not in resumes[0]


def test_career_board_redacts_sensitive_resume_summary(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    def handler(sql, params):
        if "FROM career_resumes" in sql:
            return Cursor(
                [
                    career_base_resume_row(
                        payload={"is_default": True},
                    )[:5]
                    + (
                        "基本信息: 姓名：范小刚 手机：15510261379 邮箱：xiaogangfan1228@gmail.com "
                        "技术能力: 精通 Java、Go，熟练 Claude Code、Cursor，有 AI Agent 项目经验。",
                    )
                    + career_base_resume_row()[6:]
                ]
            )
        return Cursor()

    install_fake_db(monkeypatch, main, handler)
    response = TestClient(main.app).get("/api/career/board", headers={"x-par-password": "secret"})

    assert response.status_code == 200
    summary = response.json()["career_resumes"][0]["parsed_text_summary"]
    assert "15510261379" not in summary
    assert "xiaogangfan1228@gmail.com" not in summary
    assert "基本信息" not in summary
    assert "Cursor" in summary
    assert "AI Agent" in summary


def test_career_resume_default_and_delete_endpoints_update_lightweight_state(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from fastapi.testclient import TestClient
    from app import main

    def handler(sql, params):
        if "UPDATE career_resumes" in sql and "RETURNING id, filename" in sql:
            status = "deleted" if "status = 'deleted'" in sql else "active"
            payload = {"deleted_from": "workbench"} if status == "deleted" else {"is_default": True}
            return Cursor([career_base_resume_row(status=status, payload=payload)])
        return Cursor()

    executed = install_fake_db(monkeypatch, main, handler)
    client = TestClient(main.app)
    patch_response = client.patch(
        "/api/career/resumes/career_resume_base_1",
        headers={"x-par-password": "secret"},
        json={"make_default": True},
    )
    delete_response = client.delete(
        "/api/career/resumes/career_resume_base_1",
        headers={"x-par-password": "secret"},
    )

    assert patch_response.status_code == 200
    assert patch_response.json()["payload"]["is_default"] is True
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "deleted"
    assert any("payload = payload ||" in sql and "is_default" in str(params) for sql, params in executed)
    assert any("status = 'deleted'" in sql for sql, _ in executed)


def test_mobile_navigation_reserves_space_for_agenda_tab():
    css = read_static("styles.css")

    assert "repeat(8, minmax(0, 1fr))" in css or "auto-fit" in css


def test_agenda_view_has_weekday_tab_styles():
    css = read_static("styles.css")

    assert ".agenda-day-tabs" in css
    assert ".agenda-day-tab.active" in css


def test_agenda_formats_relative_time_as_absolute_date_and_weekday():
    script = r"""
const fs = require("fs");
const vm = require("vm");
const path = process.argv[1];
function element() {
  return {
    classList: { add() {}, remove() {}, toggle() {} },
    style: { setProperty() {} },
    children: [],
    value: "",
    textContent: "",
    innerHTML: "",
    dataset: {},
    append(...nodes) { this.children.push(...nodes); },
    appendChild(node) { this.children.push(node); return node; },
    remove() {},
    setAttribute() {},
    addEventListener() {},
    querySelector() { return element(); },
    scrollIntoView() {},
    blur() {},
    focus() {},
    setSelectionRange() {},
  };
}
const document = {
  documentElement: { style: { setProperty() {} } },
  querySelector() { return element(); },
  querySelectorAll() { return []; },
  createElement() { return element(); },
};
const windowObj = {
  addEventListener() {},
  dispatchEvent() {},
  visualViewport: null,
  innerHeight: 900,
  location: { hash: "" },
};
const context = {
  window: windowObj,
  document,
  localStorage: { getItem() { return ""; }, setItem() {}, removeItem() {} },
  location: windowObj.location,
  setTimeout,
  clearTimeout,
  console,
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  Event: function Event() {},
};
windowObj.window = windowObj;
vm.createContext(context);
vm.runInContext(fs.readFileSync(path, "utf8"), context);
const item = {
  title: "明天下午4点在人民广场见",
  created_at: "2026-06-03T09:00:00+08:00",
  time_window: {
    text: "明天下午4点",
    raw_text: "明天下午4点",
    source_event_timestamp: "2026-06-03T09:00:00+08:00",
  },
};
const debug = context.window.nomiAgendaDebug;
const display = debug.formatAgendaTimeWindow(item.time_window, item);
const key = debug.agendaDateKeyForItem(item);
if (display !== "2026-06-04 周四 16:00") {
  throw new Error(`unexpected display: ${display}`);
}
if (key !== "2026-06-04") {
  throw new Error(`unexpected date key: ${key}`);
}
"""
    result = subprocess.run(
        ["node", "-e", script, str(ROOT / "app" / "static" / "app.js")],
        text=True,
        capture_output=True,
        check=False,
        env={**__import__("os").environ, "TZ": "Asia/Shanghai"},
    )

    assert result.returncode == 0, result.stderr


def test_agenda_title_replaces_relative_time_with_absolute_date_and_weekday():
    script = r"""
const fs = require("fs");
const vm = require("vm");
const path = process.argv[1];
function element() {
  return {
    classList: { add() {}, remove() {}, toggle() {} },
    style: { setProperty() {} },
    children: [],
    value: "",
    textContent: "",
    innerHTML: "",
    dataset: {},
    append(...nodes) { this.children.push(...nodes); },
    appendChild(node) { this.children.push(node); return node; },
    remove() {},
    setAttribute() {},
    addEventListener() {},
    querySelector() { return element(); },
    scrollIntoView() {},
    blur() {},
    focus() {},
    setSelectionRange() {},
  };
}
const document = {
  documentElement: { style: { setProperty() {} } },
  querySelector() { return element(); },
  querySelectorAll() { return []; },
  createElement() { return element(); },
};
const windowObj = {
  addEventListener() {},
  dispatchEvent() {},
  visualViewport: null,
  innerHeight: 900,
  location: { hash: "" },
};
const context = {
  window: windowObj,
  document,
  localStorage: { getItem() { return ""; }, setItem() {}, removeItem() {} },
  location: windowObj.location,
  setTimeout,
  clearTimeout,
  console,
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  Event: function Event() {},
};
windowObj.window = windowObj;
vm.createContext(context);
vm.runInContext(fs.readFileSync(path, "utf8"), context);
const item = {
  title: "明天下午4点人民广场见面",
  created_at: "2026-06-03T09:00:00+08:00",
  time_window: {
    text: "明天下午4点在人民广场见，带合同。",
    raw_text: "明天下午4点在人民广场见，带合同。",
    source_event_timestamp: "2026-06-03T09:00:00+08:00",
  },
};
const display = context.window.nomiAgendaDebug.formatAgendaTitle(item);
if (display !== "2026-06-04 周四 16:00 人民广场见面") {
  throw new Error(`unexpected title: ${display}`);
}
"""
    result = subprocess.run(
        ["node", "-e", script, str(ROOT / "app" / "static" / "app.js")],
        text=True,
        capture_output=True,
        check=False,
        env={**__import__("os").environ, "TZ": "Asia/Shanghai"},
    )

    assert result.returncode == 0, result.stderr


def test_workbench_restores_chat_history_and_reuses_conversation_id():
    js = read_static("app.js")

    assert 'const conversationKey = "nomi-conversation-id"' in js
    assert "let chatConversationId" in js
    assert "function setChatConversationId" in js
    assert "async function loadChatHistory" in js
    assert "loadChatHistory()" in js
    assert 'api(`/api/chat/history${query}`)' in js
    assert "setChatConversationId(event.conversation_id)" in js
    assert "conversation_id: chatConversationId || undefined" in js


def test_workbench_keeps_chat_composer_above_mobile_keyboard():
    js = read_static("app.js")
    css = read_static("styles.css")

    assert "function updateViewportMetrics" in js
    assert "function computeViewportMetrics" in js
    assert "window.visualViewport" in js
    assert "window.screen" in js
    assert "--mobile-sidebar-height" in js
    assert "keyboard-open" in js
    assert "messageInput.scrollIntoView" in js
    assert "--app-height" in css
    assert "--mobile-sidebar-height" in css
    assert "100dvh" in css
    assert ".composer" in css
    assert "position: sticky" in css


def test_viewport_metrics_do_not_double_shrink_android_adjust_resize():
    script = r"""
const fs = require("fs");
const vm = require("vm");
const path = process.argv[1];
function element() {
  return {
    classList: { add() {}, remove() {}, toggle() {} },
    style: { setProperty() {} },
    children: [],
    value: "",
    textContent: "",
    innerHTML: "",
    dataset: {},
    append(...nodes) { this.children.push(...nodes); },
    appendChild(node) { this.children.push(node); return node; },
    remove() {},
    setAttribute() {},
    addEventListener() {},
    querySelector() { return element(); },
    scrollIntoView() {},
    blur() {},
    focus() {},
    setSelectionRange() {},
  };
}
const document = {
  activeElement: null,
  body: { classList: { toggle() {} } },
  documentElement: { style: { setProperty() {} } },
  querySelector() { return element(); },
  querySelectorAll() { return []; },
  createElement() { return element(); },
};
const windowObj = {
  addEventListener() {},
  dispatchEvent() {},
  visualViewport: null,
  innerHeight: 960,
  screen: { height: 2400 },
  location: { hash: "" },
};
const context = {
  window: windowObj,
  document,
  localStorage: { getItem() { return ""; }, setItem() {}, removeItem() {} },
  location: windowObj.location,
  setTimeout,
  clearTimeout,
  requestAnimationFrame(fn) { fn(); },
  console,
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  Event: function Event() {},
};
windowObj.window = windowObj;
vm.createContext(context);
vm.runInContext(fs.readFileSync(path, "utf8"), context);
const debug = context.window.nomiViewportDebug;
if (!debug) throw new Error("missing nomiViewportDebug");

const resized = debug.computeViewportMetrics({
  focusedComposer: true,
  rawViewportHeight: 960,
  viewportOffsetTop: 0,
  innerHeight: 960,
  screenHeight: 2400,
});
if (resized.keyboardBottom !== 0) {
  throw new Error(`adjustResize should not fabricate keyboardBottom, got ${resized.keyboardBottom}`);
}
if (resized.appHeight !== 960) {
  throw new Error(`adjustResize should keep appHeight at resized viewport, got ${resized.appHeight}`);
}
if (!resized.keyboardLikelyOpen) {
  throw new Error("adjustResize should still mark keyboard as open for styling");
}

const overlay = debug.computeViewportMetrics({
  focusedComposer: true,
  rawViewportHeight: 2400,
  viewportOffsetTop: 0,
  innerHeight: 2400,
  screenHeight: 2420,
});
if (overlay.keyboardBottom <= 80) {
  throw new Error(`overlay keyboard should use fallback keyboardBottom, got ${overlay.keyboardBottom}`);
}
if (overlay.appHeight >= 2400) {
  throw new Error(`overlay keyboard should shrink appHeight, got ${overlay.appHeight}`);
}
"""
    result = subprocess.run(
        ["node", "-e", script, str(ROOT / "app" / "static" / "app.js")],
        text=True,
        capture_output=True,
        check=False,
        env={**__import__("os").environ, "TZ": "Asia/Shanghai"},
    )

    assert result.returncode == 0, result.stderr


def test_chat_send_keeps_keyboard_open_and_blurs_only_from_message_area():
    js = read_static("app.js")

    assert 'const chatSubmitButton = document.querySelector("#chatForm button[type=\'submit\']")' in js
    assert "chatSubmitButton.addEventListener(\"pointerdown\"" in js
    assert "chatSubmitButton.addEventListener(\"touchstart\"" in js
    assert "chatSubmitButton.addEventListener(\"mousedown\"" in js
    assert "chatSubmitButton.addEventListener(\"click\"" in js
    assert "event.preventDefault()" in js
    assert "refocusMessageInput" in js
    assert "messageInput.setSelectionRange" in js
    assert "submitChatMessage()" in js
    assert "messages.addEventListener(\"pointerdown\"" in js
    assert "messageInput.blur()" in js


def test_realtime_chat_shows_pending_error_and_timeout_states():
    js = read_static("app.js")

    assert "正在结合本地记忆思考..." in js
    assert "clearRealtimeChatWatchdog" in js
    assert "startRealtimeChatWatchdog" in js
    assert "realtimeChatHadDelta" in js
    assert "实时回复超时" in js
    assert "实时通道已断开" in js


def test_governance_state_memory_shows_sources_and_can_be_deleted():
    js = read_static("app.js")

    assert "function renderStateGovernanceItem" in js
    assert "source_fact_ids" in js
    assert "来源 ${sourceFactIds.length} 条事实" in js
    assert 'body: JSON.stringify({ state_key: item.key })' in js
    assert "node.remove()" in js


def test_workbench_renders_long_tail_rollback_and_compensation_action_cards():
    js = read_static("app.js")
    css = read_static("styles.css")

    assert "function renderLongTailActionCard" in js
    assert "function handleLongTailActionCardAction" in js
    assert "function consumePendingAgentEvent" in js
    assert "nomi-pending-agent-event" in js
    assert "handleRealtimeMessage(event)" in js
    assert 'event.type === "agent_task_delivery"' in js
    assert 'event.type === "agent_task_fallback"' in js
    assert 'review_external_effect_rollback' in js
    assert 'prepare_compensation' in js
    assert 'external-effects/${effectId}/rollback' in js
    assert 'external-effects/${effectId}/compensation' in js
    assert ".long-tail-action-card" in css
    assert ".long-tail-action-card .actions" in css


def test_chat_artifact_urls_render_in_the_internal_viewer_across_all_reply_paths():
    js = read_static("app.js")
    css = read_static("styles.css")

    assert "function renderMessageContent(node, text)" in js
    assert "function isArtifactDownloadUrl(url)" in js
    assert "function artifactFilenameFromMessage(text)" in js
    assert 'anchor.className = "artifact-view-link"' in js
    assert 'anchor.textContent = `点击查看${filename ? `：${filename}` : "文件"}`' in js
    assert "openInternalFileViewer({ source: url, filename })" in js
    assert "window.NomiAndroid.openFileViewer(viewerUrl)" in js
    assert "renderMessageContent(item, text)" in js
    assert "renderMessageContent(activeAssistantNode, activeAssistantNode.textContent)" in js
    assert "renderMessageContent(pendingNode, result.answer)" in js
    assert ".artifact-view-link" in css
