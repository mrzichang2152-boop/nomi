from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")


def test_chat_has_a_server_backed_assistant_draft_region():
    chat_view = HTML[HTML.index('id="chatView"') : HTML.index('id="agendaView"')]

    assert 'id="chatAssistantDrafts"' in chat_view
    assert 'aria-live="polite"' in chat_view
    assert re.search(
        r'<div id="messages" class="messages">\s*<section\s+id="chatAssistantDrafts"',
        chat_view,
    )
    assert 'id="assistantIdentityDrafts"' not in chat_view
    assert 'const chatAssistantDrafts = document.querySelector("#chatAssistantDrafts")' in JS
    assert 'api("/api/assistant-outbound/drafts?limit=20")' in JS
    assert "function renderChatAssistantDrafts" in JS
    assert "function loadChatAssistantDrafts" in JS
    assert "function ensureChatAssistantDraftRegion" in JS


def test_chat_draft_cards_keep_the_authoritative_draft_id_and_all_required_actions():
    render_start = JS.index("function renderChatAssistantDrafts")
    render_end = JS.index("async function loadChatAssistantDrafts", render_start)
    render = JS[render_start:render_end]

    assert "draft.draft_id" in render
    assert "dataset.draftId" in render
    assert "确认并发送" in render
    assert "修改" in render
    assert "取消" in render
    assert "source_evidence_ids" in render
    assert "editAssistantDraft" in render
    assert "confirmAssistantDraft" in render
    assert "cancelAssistantDraft" in render
    assert '"sent"' in render
    assert '"delivered"' in render
    assert '"read"' in render
    assert '"delivery_unknown"' in render
    assert 'draft.status === "draft"' in render
    assert 'draft.status === "blocked" ? "重试发送"' not in render
    assert '["draft", "blocked"].includes(draft.status)' in render
    assert '["draft", "blocked", "failed", "rejected"].includes(draft.status)' not in render


def test_all_web_draft_actions_share_one_duplicate_tap_guard():
    assert "const assistantDraftActionsInFlight = new Set()" in JS
    assert "function runAssistantDraftAction" in JS

    guard_start = JS.index("async function runAssistantDraftAction")
    guard_end = JS.index("async function editAssistantDraft", guard_start)
    guard = JS[guard_start:guard_end]
    assert "assistantDraftActionsInFlight.has(stableDraftId)" in guard
    assert "assistantDraftActionsInFlight.add(stableDraftId)" in guard
    assert "assistantDraftActionsInFlight.delete(stableDraftId)" in guard

    assert "return runAssistantDraftAction(draftId" in JS


def test_chat_draft_layout_is_part_of_the_scrolling_message_flow():
    assert ".chat-assistant-drafts" in CSS
    assert ".chat-assistant-draft" in CSS
    assert "overflow-wrap: anywhere" in CSS

    draft_list_start = CSS.index(".chat-assistant-drafts {")
    draft_list_end = CSS.index("}", draft_list_start)
    draft_list_rule = CSS[draft_list_start:draft_list_end]
    assert "display: contents" in draft_list_rule
    assert "max-height:" not in draft_list_rule
    assert "overflow-y:" not in draft_list_rule

    add_message_start = JS.index("function addMessage")
    add_message_end = JS.index("\n}", add_message_start)
    add_message = JS[add_message_start:add_message_end]
    assert "ensureChatAssistantDraftRegion()" in add_message
    assert "messages.insertBefore(item, chatAssistantDrafts)" in add_message

    history_start = JS.index("async function loadChatHistory")
    history_end = JS.index("\n}", history_start)
    history = JS[history_start:history_end]
    assert 'messages.querySelector(".message")' in history


def test_chat_completion_refreshes_newly_created_server_drafts():
    http_start = JS.index("async function submitChatOverHttp")
    http_end = JS.index("async function submitChatMessage", http_start)
    http_submit = JS[http_start:http_end]
    assert "loadChatAssistantDrafts()" in http_submit

    realtime_start = JS.index('if (event.type === "chat_done")')
    realtime_end = JS.index('if (event.type === "openclaw_job_event")', realtime_start)
    realtime_done = JS[realtime_start:realtime_end]
    assert "loadChatAssistantDrafts()" in realtime_done
