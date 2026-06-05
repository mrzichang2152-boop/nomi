import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_static(name: str) -> str:
    return (ROOT / "app" / "static" / name).read_text(encoding="utf-8")


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

    nav_order = [
        html.index('data-view="chatView"'),
        html.index('data-view="agendaView"'),
        html.index('data-view="searchView"'),
    ]
    assert nav_order == sorted(nav_order)


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


def test_mobile_navigation_reserves_space_for_agenda_tab():
    css = read_static("styles.css")

    assert "repeat(7, minmax(0, 1fr))" in css or "auto-fit" in css


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
    assert "window.visualViewport" in js
    assert "--mobile-sidebar-height" in js
    assert "keyboard-open" in js
    assert "messageInput.scrollIntoView" in js
    assert "--app-height" in css
    assert "--mobile-sidebar-height" in css
    assert "100dvh" in css
    assert ".composer" in css
    assert "position: sticky" in css


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
