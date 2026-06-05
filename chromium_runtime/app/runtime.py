import asyncio
import hashlib
import json
import os
import re
import time
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timezone
from typing import Optional

import httpx

try:
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover - fallback runtime path
    async_playwright = None


RUNTIME_API_URL = os.getenv("RUNTIME_API_URL", "http://runtime-api:8080")
RUNTIME_API_PASSWORD = os.getenv("RUNTIME_API_PASSWORD", os.getenv("APP_PASSWORD", ""))
CHROMIUM_EXECUTABLE = os.getenv("CHROMIUM_EXECUTABLE", "/usr/bin/chromium")
CHROMIUM_HEADLESS = os.getenv("CHROMIUM_HEADLESS", "true").lower() == "true"
CHROMIUM_CDP_URL = os.getenv("CHROMIUM_CDP_URL", "http://127.0.0.1:9222")
CHROMIUM_WINDOW_WIDTH = os.getenv("CHROMIUM_WINDOW_WIDTH", "1920")
CHROMIUM_WINDOW_HEIGHT = os.getenv("CHROMIUM_WINDOW_HEIGHT", "1080")
GMAIL_AUTO_OPEN = os.getenv("GMAIL_AUTO_OPEN", "true").lower() == "true"
CHROMIUM_AUTO_OPEN_SOURCES = os.getenv("CHROMIUM_AUTO_OPEN_SOURCES", "gmail,whatsapp,calendar,telegram,search")
WHATSAPP_HISTORY_SYNC = os.getenv("WHATSAPP_HISTORY_SYNC", "true").lower() == "true"
CHROMIUM_BOOKMARKS_PATH = os.getenv("CHROMIUM_BOOKMARKS_PATH", "/app/user_profile/Default/Bookmarks")
COLLECTORS = ["search", "whatsapp", "gmail", "calendar", "telegram", "focus", "bookmark"]
MANAGED_PAGE_CATALOG = {
    "gmail": {
        "host_fragment": "mail.google.com",
        "url": "https://mail.google.com/mail/u/0/#inbox",
    },
    "whatsapp": {
        "host_fragment": "web.whatsapp.com",
        "url": "https://web.whatsapp.com/",
    },
    "calendar": {
        "host_fragment": "calendar.google.com",
        "url": "https://calendar.google.com/calendar/u/0/r",
    },
    "telegram": {
        "host_fragment": "web.telegram.org",
        "url": "https://web.telegram.org/",
    },
    "search": {
        "host_fragment": "google.",
        "url": "https://www.google.com/",
    },
    "shopping": {
        "host_fragment": "amazon.",
        "url": "https://www.amazon.com/",
    },
}
SEEN_EVENTS: set[str] = set()
FOCUS_STATE: dict[str, dict[str, object]] = {}
SEARCH_STATE: dict[str, dict[str, str]] = {}
MANUAL_BROWSER_FOCUS: dict[str, object] = {"source": "", "until": 0.0}
WHATSAPP_UI_LINES = {
    "所有",
    "未读",
    "特别关注",
    "群组",
    "开启后台同步",
    "在后台同步消息，获享更快的性能。",
    "你的私人消息已进行端到端加密",
    "发送文档",
    "添加联系人",
}
GMAIL_UI_LINES = {
    "未选择任何内容",
    "跳至内容",
    "通过屏幕阅读器使用 Gmail",
    "搜索",
    "免费试用 Gemini",
    "写邮件",
    "标签",
    "收件箱",
    "已加星标",
    "已延后",
    "已发邮件",
    "草稿",
    "购物",
    "显示更多标签",
    "升级",
    "会话",
    "主要",
    "推广",
    "社交",
    "Gmail",
    "返回",
    "回复",
    "转发",
    "打印",
    "在新窗口中打开",
    "显示详细信息",
}
GMAIL_SECRET_LINK_RE = re.compile(r"https?://\S*(?:token|code|auth|verify|reset|password|login)\S*", re.I)
GMAIL_VERIFICATION_RE = re.compile(r"((?:验证码|校验码|verification code|code)[^\dA-Za-z]{0,8})([A-Za-z0-9-]{4,12})", re.I)
GMAIL_ORDER_RE = re.compile(r"((?:订单号|订单|order(?: id)?)[^\dA-Za-z]{0,8})([A-Za-z0-9-]{5,24})", re.I)
GMAIL_AMOUNT_RE = re.compile(r"(?<![\dA-Za-z_])(?:¥|￥|RMB\s*)?\d{1,7}(?:\.\d{2})?\s*(?:元|CNY|USD|美元)?(?![\dA-Za-z_])", re.I)
CALENDAR_UI_LINES = {
    "Google Calendar",
    "日历",
    "今天",
    "搜索",
    "设置",
    "创建",
    "月",
    "周",
    "日",
    "日程",
    "任务",
    "提醒",
    "全天",
    "更多",
}
TELEGRAM_UI_LINES = {
    "Telegram",
    "Search",
    "搜索",
    "Archived Chats",
    "归档聊天",
    "Saved Messages",
    "Contacts",
    "Settings",
    "New Group",
    "New Channel",
    "Menu",
}
COLLECTOR_SELECTOR_HINTS = {
    "gmail": ["div[role='main']", "tr[role='row']", "div[role='listitem']", "span[email]"],
    "calendar": ["[data-eventid]", "[role='gridcell']", "[aria-label*='event']", "[aria-label*='日程']"],
    "telegram": [".chatlist", "[class*='Chat']", "[class*='message']"],
    "whatsapp": ["#pane-side", "div[role='row']", "div[data-testid*='msg']", "div[aria-label*='message']"],
}
COLLECTOR_UI_LINES = {
    "gmail": GMAIL_UI_LINES,
    "calendar": CALENDAR_UI_LINES,
    "telegram": TELEGRAM_UI_LINES,
    "whatsapp": WHATSAPP_UI_LINES,
}


async def report_health(client: httpx.AsyncClient, collector: str, status: str, details: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await client.post(
        f"{RUNTIME_API_URL}/collectors/health",
        json={
            "collector": collector,
            "status": status,
            "last_injection_at": now,
            "error_count": 0 if status == "healthy" else 1,
            "details": details,
        },
        timeout=10,
    )


def runtime_api_headers() -> dict[str, str]:
    return {"x-par-password": RUNTIME_API_PASSWORD} if RUNTIME_API_PASSWORD else {}


def build_degraded_details(
    collector: str,
    failure_reason: str,
    lines: list[str],
    *,
    url: str = "",
    title: str = "",
    min_lines: int = 40,
    matched_count: int = 0,
) -> dict[str, object]:
    ui_lines = COLLECTOR_UI_LINES.get(collector, set())
    meaningful_lines = [line for line in lines if line and line not in ui_lines]
    dom_sample = meaningful_lines[:8] or lines[:8]
    line_count = len(lines)
    quality_score = 0.0
    if min_lines > 0:
        quality_score = min(line_count / min_lines, 1.0) * 0.5
    if matched_count:
        quality_score += min(matched_count / 5, 1.0) * 0.5
    return {
        "message": f"{collector.title()} visible text did not match expected parser structure.",
        "failure_reason": failure_reason,
        "line_count": line_count,
        "matched_count": matched_count,
        "quality_score": round(min(quality_score, 1.0), 3),
        "selector_hints": COLLECTOR_SELECTOR_HINTS.get(collector, []),
        "dom_sample": dom_sample,
        "url": url,
        "title": title,
    }


def collector_allowed(source: str, settings: dict[str, dict]) -> bool:
    setting = settings.get(source)
    if not setting:
        return True
    return bool(setting.get("enabled", True)) and not bool(setting.get("paused", False))


def managed_page_targets(settings: dict[str, dict], auto_open_sources: Optional[str] = None) -> list[dict[str, str]]:
    source_text = auto_open_sources if auto_open_sources is not None else CHROMIUM_AUTO_OPEN_SOURCES
    enabled_sources = [source.strip() for source in source_text.split(",") if source.strip()]
    if GMAIL_AUTO_OPEN and "gmail" not in enabled_sources:
        enabled_sources.insert(0, "gmail")
    targets: list[dict[str, str]] = []
    for source in enabled_sources:
        target = MANAGED_PAGE_CATALOG.get(source)
        if not target or not collector_allowed(source, settings):
            continue
        targets.append({"source": source, **target})
    return targets


def missing_managed_page_targets(targets: list[dict[str, str]], open_urls: list[str]) -> list[dict[str, str]]:
    missing = []
    for target in targets:
        host_fragment = target["host_fragment"]
        if not any(host_fragment in url for url in open_urls):
            missing.append(target)
    return missing


def filter_managed_targets_for_manual_login(
    targets: list[dict[str, str]],
    manual_source: str,
) -> list[dict[str, str]]:
    source = (manual_source or "").strip().lower()
    if not source:
        return targets
    return [target for target in targets if target.get("source") == source]


def mark_manual_browser_focus(source: str, ttl_seconds: float = 600.0) -> None:
    MANUAL_BROWSER_FOCUS["source"] = (source or "").strip().lower()
    MANUAL_BROWSER_FOCUS["until"] = time.monotonic() + ttl_seconds


def active_manual_browser_focus_source() -> str:
    source = str(MANUAL_BROWSER_FOCUS.get("source") or "")
    until = float(MANUAL_BROWSER_FOCUS.get("until") or 0.0)
    if source and until > time.monotonic():
        return source
    return ""


def source_for_page_url(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if "mail.google.com" in parsed.netloc:
        return "gmail"
    if "web.whatsapp.com" in parsed.netloc:
        return "whatsapp"
    if "calendar.google.com" in parsed.netloc:
        return "calendar"
    if "web.telegram.org" in parsed.netloc:
        return "telegram"
    if "google." in parsed.netloc:
        return "search"
    return None


async def fetch_collector_settings(client: httpx.AsyncClient) -> dict[str, dict]:
    try:
        response = await client.get(
            f"{RUNTIME_API_URL}/api/collectors/settings",
            headers=runtime_api_headers(),
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return {}
    return {item["source"]: item for item in payload.get("collectors", [])}


async def main() -> None:
    async with httpx.AsyncClient() as client:
        if async_playwright is None:
            await run_degraded_loop(client, "Playwright package unavailable.")
            return

        try:
            async with async_playwright() as p:
                browser, context = await connect_to_visible_browser(p)
                if not context.pages:
                    await context.new_page()

                for collector in COLLECTORS:
                    await report_health(
                        client,
                        collector,
                        "degraded" if collector in {"whatsapp", "gmail", "calendar"} else "healthy",
                        {
                            "runtime": "playwright",
                            "message": "Collector scaffold loaded. Account login and DOM adapters are next.",
                        },
                    )

                asyncio.create_task(collector_loop(client, context))
                asyncio.create_task(browser_command_loop(client, context))

                while True:
                    page_count = sum(len(context.pages) for context in browser.contexts)
                    await report_health(client, "runtime", "healthy", {"pages": page_count})
                    await asyncio.sleep(60)
        except Exception as exc:
            await run_degraded_loop(client, f"Chromium unavailable: {exc}")


async def connect_to_visible_browser(playwright):
    if CHROMIUM_CDP_URL:
        browser = await playwright.chromium.connect_over_cdp(CHROMIUM_CDP_URL)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        return browser, context

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir="/app/user_profile",
        executable_path=CHROMIUM_EXECUTABLE,
        headless=CHROMIUM_HEADLESS,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--start-maximized",
            f"--window-size={CHROMIUM_WINDOW_WIDTH},{CHROMIUM_WINDOW_HEIGHT}",
        ],
    )
    return context.browser, context


async def ensure_page_open(context, host_fragment: str, url: str) -> None:
    for page in context.pages:
        if host_fragment in page.url:
            return
    page = await context.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)


def browser_command_target(source: str) -> Optional[dict[str, str]]:
    normalized = (source or "").strip().lower()
    target = MANAGED_PAGE_CATALOG.get(normalized)
    if not target:
        return None
    return {"source": normalized, **target}


async def execute_browser_open_command(context, command: dict) -> dict[str, str]:
    if not isinstance(command, dict) or command.get("action") != "open_url":
        return {"status": "ignored", "source": "", "url": ""}
    target = browser_command_target(str(command.get("source") or ""))
    if not target:
        return {"status": "ignored", "source": str(command.get("source") or ""), "url": ""}
    host_fragment = target["host_fragment"]
    url = target["url"]
    mark_manual_browser_focus(target["source"])
    page = current_browser_page(context)
    if page is not None:
        await close_other_pages(context, page)
        if host_fragment in page.url:
            await page.bring_to_front()
            return {"status": "focused", "source": target["source"], "url": url}
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.bring_to_front()
        return {"status": "navigated", "source": target["source"], "url": url}
    page = await context.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.bring_to_front()
    return {"status": "opened", "source": target["source"], "url": url}


def current_browser_page(context):
    pages = list(getattr(context, "pages", []))
    if pages:
        return pages[0]
    return None


async def close_other_pages(context, keep_page) -> None:
    for page in list(getattr(context, "pages", [])):
        if page is keep_page:
            continue
        try:
            await page.close()
        except Exception:
            pass


async def fetch_browser_command(client: httpx.AsyncClient) -> Optional[dict]:
    response = await client.get(
        f"{RUNTIME_API_URL}/api/browser/commands/next",
        headers=runtime_api_headers(),
        timeout=5,
    )
    response.raise_for_status()
    payload = response.json()
    command = payload.get("command")
    return command if isinstance(command, dict) else None


async def browser_command_loop(client: httpx.AsyncClient, context) -> None:
    while True:
        try:
            command = await fetch_browser_command(client)
            if command:
                result = await execute_browser_open_command(context, command)
                source = result.get("source") or str(command.get("source") or "runtime")
                await report_health(
                    client,
                    source,
                    "degraded" if result.get("status") in {"opened", "focused", "navigated"} else "failed",
                    {
                        "browser_command": command.get("command_id"),
                        "command_result": result,
                        "message": "Remote browser has been navigated for user login.",
                    },
                )
                await asyncio.sleep(0.1)
                continue
        except Exception as exc:
            await report_health(
                client,
                "runtime",
                "degraded",
                {"message": f"browser command loop error: {exc}"},
            )
        await asyncio.sleep(1)


async def ensure_managed_pages(client: httpx.AsyncClient, context, settings: dict[str, dict]) -> None:
    targets = filter_managed_targets_for_manual_login(
        managed_page_targets(settings),
        active_manual_browser_focus_source(),
    )
    missing_targets = missing_managed_page_targets(targets, [page.url for page in context.pages])
    for target in missing_targets:
        try:
            await ensure_page_open(context, target["host_fragment"], target["url"])
            await report_health(
                client,
                target["source"],
                "degraded",
                {
                    "recovery": "page_reopened",
                    "url": target["url"],
                    "host_fragment": target["host_fragment"],
                    "message": "Managed page was missing and has been reopened for collector recovery.",
                },
            )
        except Exception as exc:
            await report_health(
                client,
                target["source"],
                "failed",
                {
                    "recovery": "page_reopen_failed",
                    "url": target["url"],
                    "host_fragment": target["host_fragment"],
                    "message": str(exc),
                },
            )


def event_key(source: str, event_type: str, value: str) -> str:
    return hashlib.sha256(f"{source}:{event_type}:{value}".encode("utf-8")).hexdigest()


async def emit_event(client: httpx.AsyncClient, source: str, event_type: str, raw_data: dict) -> None:
    key = event_key(source, event_type, str(raw_data))
    if key in SEEN_EVENTS:
        return
    SEEN_EVENTS.add(key)
    await client.post(
        f"{RUNTIME_API_URL}/event",
        json={
            "source": source,
            "event_type": event_type,
            "raw_data": raw_data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        timeout=10,
    )


async def collector_loop(client: httpx.AsyncClient, context) -> None:
    while True:
        settings = await fetch_collector_settings(client)
        await ensure_managed_pages(client, context, settings)
        if collector_allowed("bookmark", settings):
            await collect_bookmarks(client)
        for page in list(context.pages):
            try:
                page_source = source_for_page_url(page.url)
                await inject_runtime_hooks(page, page_source)
                await collect_runtime_network_events(client, page, page_source)
                if collector_allowed("search", settings):
                    await collect_search(client, page)
                if collector_allowed("whatsapp", settings):
                    await collect_whatsapp(client, page)
                if collector_allowed("gmail", settings):
                    await collect_gmail(client, page)
                if collector_allowed("calendar", settings):
                    await collect_calendar(client, page)
                if collector_allowed("telegram", settings):
                    await collect_telegram(client, page)
                if collector_allowed("focus", settings):
                    await collect_focus(client, page)
            except Exception as exc:
                await report_health(
                    client,
                    "runtime",
                    "degraded",
                    {"message": f"collector loop error: {exc}"},
                )
        await asyncio.sleep(20)


async def collect_search(client: httpx.AsyncClient, page) -> None:
    parsed = urlparse(page.url)
    page_key = str(id(page))
    previous_search_url = SEARCH_STATE.get(page_key, {}).get("last_search_url")
    clicked = extract_google_clicked_result(previous_search_url, page.url, await page.title())
    if clicked:
        await emit_event(client, "search", "search_result_click", clicked)
        SEARCH_STATE[page_key] = {}
        return
    if "google." not in parsed.netloc or parsed.path != "/search":
        return
    query = parse_qs(parsed.query).get("q", [""])[0].strip()
    if not query:
        return
    result_candidates = await page.evaluate(
        """
        (() => Array.from(document.querySelectorAll('a')).slice(0, 80).map((anchor) => {
          const title = (anchor.querySelector('h3')?.innerText || anchor.innerText || '').trim();
          const url = anchor.href || '';
          const container = anchor.closest('div');
          const snippet = (container?.innerText || '').replace(title, '').trim().slice(0, 500);
          return { title, url, snippet };
        }))();
        """
    )
    results = parse_google_search_results(result_candidates if isinstance(result_candidates, list) else [])
    SEARCH_STATE[page_key] = {"last_search_url": page.url, "query": query}
    await emit_event(
        client,
        "search",
        "search",
        {"query": query, "url": page.url, "title": await page.title(), "results": results},
    )
    await report_health(client, "search", "healthy", {"last_query": query, "result_count": len(results)})


def parse_google_search_results(candidates: list[dict[str, str]], limit: int = 10) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    seen: set[str] = set()
    for candidate in candidates:
        title = str(candidate.get("title") or "").strip()
        url = str(candidate.get("url") or "").strip()
        snippet = str(candidate.get("snippet") or "").strip()
        parsed = urlparse(url)
        if not title or not url or not parsed.scheme.startswith("http"):
            continue
        if "google." in parsed.netloc:
            continue
        if url in seen:
            continue
        seen.add(url)
        results.append(
            {
                "title": title[:240],
                "url": url,
                "snippet": snippet[:500],
                "rank": len(results) + 1,
            }
        )
        if len(results) >= limit:
            break
    return results


def extract_google_clicked_result(previous_url: Optional[str], current_url: str, title: str) -> Optional[dict[str, str]]:
    if not previous_url:
        return None
    previous = urlparse(previous_url)
    current = urlparse(current_url)
    if "google." not in previous.netloc or previous.path != "/search":
        return None
    if "google." in current.netloc or not current.scheme.startswith("http"):
        return None
    return {
        "from_search_url": previous_url,
        "clicked_url": current_url,
        "clicked_title": title,
        "capture_scope": "search_result_click",
    }


async def collect_whatsapp(client: httpx.AsyncClient, page) -> None:
    if "web.whatsapp.com" not in page.url:
        return
    await inject_whatsapp_observer(page)
    observer_records = await drain_whatsapp_observer_records(page)
    body_text = await page.locator("body").inner_text(timeout=5000)
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    title = await page.title()
    if "WhatsApp 已在另一窗口中打开" in body_text:
        await report_health(
            client,
            "whatsapp",
            "degraded",
            build_degraded_details(
                "whatsapp",
                "opened_in_another_window",
                lines,
                url=page.url,
                title=title,
                min_lines=8,
            ),
        )
        return
    if len(body_text.strip()) < 40:
        await report_health(
            client,
            "whatsapp",
            "degraded",
            build_degraded_details("whatsapp", "too_little_visible_text", lines, url=page.url, title=title, min_lines=8),
        )
        return
    chat_context = extract_whatsapp_chat_context(lines)
    for message in normalize_whatsapp_observer_records(observer_records, chat_context=chat_context):
        await emit_event(
            client,
            "whatsapp",
            "whatsapp_message",
            {
                **message,
                "url": page.url,
                "title": title,
            },
        )
    chat_name = chat_context.get("chat_name")
    if WHATSAPP_HISTORY_SYNC and chat_name:
        await inject_whatsapp_history_sync(page)
        history_records = normalize_whatsapp_history_records(await drain_whatsapp_history_records(page), chat_context=chat_context)
        for message in history_records:
            await emit_event(
                client,
                "whatsapp",
                "whatsapp_message",
                {
                    **message,
                    "url": page.url,
                    "title": title,
                },
            )

    await emit_whatsapp_list_previews(client, lines, page.url, title, chat_context=chat_context)

    if chat_name:
        await emit_event(
            client,
            "whatsapp",
            "whatsapp_open_chat_snapshot",
            {
                "chat_name": chat_name,
                "source_kind": chat_context.get("source_kind"),
                "participants": chat_context.get("participants", []),
                "visible_text": body_text[:6000],
                "line_count": len(lines),
                "url": page.url,
                "title": title,
            },
        )

    await emit_event(
        client,
        "whatsapp",
        "whatsapp_snapshot",
        {
            "chat_name": chat_name,
            "source_kind": chat_context.get("source_kind"),
            "participants": chat_context.get("participants", []),
            "visible_text": body_text[:4000],
            "line_count": len(lines),
            "url": page.url,
            "title": title,
        },
    )
    await report_health(client, "whatsapp", "healthy", {"line_count": len(lines), "chat_name": chat_name})


def runtime_injection_plan(source: Optional[str]) -> list[dict[str, str]]:
    plan = [
        {"hook": "network", "queue": "__parRuntimeQueues.network"},
        {"hook": "focus", "queue": "__parFocusSignals"},
    ]
    if source == "whatsapp":
        plan.append({"hook": "whatsapp_dom", "queue": "__parWhatsAppNewMessages"})
    return plan


def build_network_hook_script() -> str:
    return """
    (() => {
      window.__parRuntimeQueues = window.__parRuntimeQueues || { network: [], websocket: [] };
      if (window.__parNetworkHookInstalled) return true;
      window.__parNetworkHookInstalled = true;
      const now = () => new Date().toISOString();
      const trimQueue = (queue) => {
        if (queue.length > 200) queue.splice(0, queue.length - 200);
      };
      const recordNetwork = (record) => {
        window.__parRuntimeQueues.network.push({ ...record, captured_at: now() });
        trimQueue(window.__parRuntimeQueues.network);
      };
      const originalFetch = window.fetch;
      if (typeof originalFetch === 'function') {
        window.fetch = async function(input, init) {
          const method = (init && init.method) || (input && input.method) || 'GET';
          const url = typeof input === 'string' ? input : (input && input.url) || '';
          try {
            const response = await originalFetch.apply(this, arguments);
            recordNetwork({ kind: 'fetch', method, url, status: response.status });
            return response;
          } catch (error) {
            recordNetwork({ kind: 'fetch', method, url, status: 0, error: String(error && error.message || error) });
            throw error;
          }
        };
      }
      const originalOpen = XMLHttpRequest.prototype.open;
      const originalSend = XMLHttpRequest.prototype.send;
      XMLHttpRequest.prototype.open = function(method, url) {
        this.__parRequest = { method, url };
        return originalOpen.apply(this, arguments);
      };
      XMLHttpRequest.prototype.send = function() {
        this.addEventListener('loadend', () => {
          const request = this.__parRequest || {};
          recordNetwork({ kind: 'xhr', method: request.method || 'GET', url: request.url || '', status: this.status || 0 });
        });
        return originalSend.apply(this, arguments);
      };
      const OriginalWebSocket = window.WebSocket;
      if (typeof OriginalWebSocket === 'function' && !OriginalWebSocket.__parWrapped) {
        const WrappedWebSocket = function(url, protocols) {
          const socket = protocols === undefined ? new OriginalWebSocket(url) : new OriginalWebSocket(url, protocols);
          recordNetwork({ kind: 'websocket', url: String(url || ''), direction: 'open' });
          socket.addEventListener('close', () => recordNetwork({ kind: 'websocket', url: String(url || ''), direction: 'close' }));
          return socket;
        };
        WrappedWebSocket.prototype = OriginalWebSocket.prototype;
        WrappedWebSocket.__parWrapped = true;
        window.WebSocket = WrappedWebSocket;
      }
      return true;
    })();
    """


def strip_url_query(value: str) -> str:
    parsed = urlparse(str(value or ""))
    if not parsed.scheme or not parsed.netloc:
        return str(value or "")[:500]
    return parsed._replace(query="", fragment="").geturl()[:500]


def normalize_network_records(records: list[dict[str, object]], source: str, page_url: str, title: str) -> list[dict[str, object]]:
    normalized = []
    for record in records[:50]:
        if not isinstance(record, dict):
            continue
        kind = str(record.get("kind") or "")[:40]
        if kind not in {"fetch", "xhr", "websocket"}:
            continue
        normalized.append(
            {
                "source": source,
                "kind": kind,
                "method": str(record.get("method"))[:12] if record.get("method") else None,
                "url": strip_url_query(str(record.get("url") or "")),
                "status": int(record["status"]) if isinstance(record.get("status"), (int, float)) else None,
                "direction": str(record.get("direction"))[:20] if record.get("direction") else None,
                "page_url": page_url,
                "title": title,
                "captured_at": str(record.get("captured_at") or datetime.now(timezone.utc).isoformat()),
                "capture_scope": "runtime_network_hook",
            }
        )
    return normalized


async def inject_runtime_hooks(page, source: Optional[str]) -> None:
    await page.evaluate(build_network_hook_script())
    await inject_focus_observer(page)
    if source == "whatsapp":
        await inject_whatsapp_observer(page)


async def drain_network_records(page) -> list[dict[str, object]]:
    records = await page.evaluate(
        """
        (() => {
          window.__parRuntimeQueues = window.__parRuntimeQueues || { network: [], websocket: [] };
          const records = window.__parRuntimeQueues.network || [];
          window.__parRuntimeQueues.network = [];
          return records;
        })();
        """
    )
    return records if isinstance(records, list) else []


async def collect_runtime_network_events(client: httpx.AsyncClient, page, source: Optional[str]) -> None:
    if not source or source == "focus":
        return
    title = await page.title()
    for record in normalize_network_records(await drain_network_records(page), source=source, page_url=page.url, title=title):
        await emit_event(client, source, "browser_network_event", record)


def split_participants(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,，、]", value) if part.strip() and len(part.strip()) <= 80]


def extract_whatsapp_chat_context(lines: list[str]) -> dict[str, object]:
    chat_name = None
    participants: list[str] = []
    if "点击此处查看联系人信息" in lines:
        index = lines.index("点击此处查看联系人信息")
        if index > 0:
            chat_name = lines[index - 1]
        if index + 1 < len(lines):
            participants = split_participants(lines[index + 1])
    source_kind = "group" if len(participants) >= 2 else "direct"
    return {
        "chat_name": chat_name,
        "source_kind": source_kind,
        "participants": participants,
    }


async def emit_whatsapp_list_previews(
    client: httpx.AsyncClient,
    lines: list[str],
    url: str,
    title: str,
    chat_context: Optional[dict[str, object]] = None,
) -> None:
    excluded = WHATSAPP_UI_LINES
    chat_context = chat_context or {}
    for index, line in enumerate(lines):
        if line in excluded or len(line) > 40:
            continue
        if index + 2 >= len(lines):
            continue
        timestamp_label = lines[index + 1]
        message = lines[index + 2]
        if timestamp_label in excluded or message in excluded:
            continue
        if timestamp_label not in {"昨天", "今天"} and ":" not in timestamp_label and "/" not in timestamp_label:
            continue
        await emit_event(
            client,
            "whatsapp",
            "whatsapp_message",
            {
                "sender": line,
                "chat_name": chat_context.get("chat_name"),
                "source_kind": chat_context.get("source_kind", "unknown"),
                "message_direction": "unknown",
                "message": message,
                "timestamp_label": timestamp_label,
                "capture_scope": "chat_list_preview",
                "url": url,
                "title": title,
            },
        )


def build_whatsapp_observer_script() -> str:
    return """
    (() => {
      if (window.__parWhatsAppObserverInstalled) return true;
      window.__parWhatsAppObserverInstalled = true;
      window.__parWhatsAppNewMessages = window.__parWhatsAppNewMessages || [];
      const capture = (node) => {
        const text = (node && node.innerText || '').trim();
        if (!text || text.length < 4 || text.length > 2000) return;
        window.__parWhatsAppNewMessages.push({
          text,
          captured_at: new Date().toISOString()
        });
        if (window.__parWhatsAppNewMessages.length > 200) {
          window.__parWhatsAppNewMessages.splice(0, window.__parWhatsAppNewMessages.length - 200);
        }
      };
      const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
          for (const node of mutation.addedNodes || []) {
            if (node && node.nodeType === Node.ELEMENT_NODE) capture(node);
          }
        }
      });
      observer.observe(document.body, { childList: true, subtree: true });
      window.__parWhatsAppObserver = observer;
      return true;
    })();
    """


async def inject_whatsapp_observer(page) -> None:
    await page.evaluate(build_whatsapp_observer_script())


async def drain_whatsapp_observer_records(page) -> list[dict[str, str]]:
    records = await page.evaluate(
        """
        (() => {
          const records = window.__parWhatsAppNewMessages || [];
          window.__parWhatsAppNewMessages = [];
          return records;
        })();
        """
    )
    return records if isinstance(records, list) else []


def build_whatsapp_history_sync_script(max_records: int = 120) -> str:
    return f"""
    (() => {{
      window.__parWhatsAppHistoryMessages = window.__parWhatsAppHistoryMessages || [];
      if (window.__parWhatsAppHistorySyncInstalled) return true;
      window.__parWhatsAppHistorySyncInstalled = true;
      const maxRecords = {int(max_records)};
      const queueVisible = () => {{
        const nodes = Array.from(document.querySelectorAll('[role="row"], [data-testid*="msg"], div.copyable-text')).slice(-maxRecords);
        const captured_at = new Date().toISOString();
        for (const node of nodes) {{
          const text = (node.innerText || '').trim();
          if (!text || text.length < 3) continue;
          window.__parWhatsAppHistoryMessages.push({{ text, captured_at }});
        }}
        if (window.__parWhatsAppHistoryMessages.length > maxRecords) {{
          window.__parWhatsAppHistoryMessages.splice(0, window.__parWhatsAppHistoryMessages.length - maxRecords);
        }}
      }};
      const pane = document.querySelector('#main [tabindex="0"], #main [role="application"], div[role="application"], main') || document.scrollingElement;
      if (pane && typeof pane.scrollTop === 'number') {{
        pane.scrollTop = Math.max(0, pane.scrollTop - Math.max(pane.clientHeight || 600, 400));
      }}
      queueVisible();
      return true;
    }})();
    """


async def inject_whatsapp_history_sync(page) -> None:
    await page.evaluate(build_whatsapp_history_sync_script())


async def drain_whatsapp_history_records(page) -> list[dict[str, str]]:
    records = await page.evaluate(
        """
        (() => {
          const records = window.__parWhatsAppHistoryMessages || [];
          window.__parWhatsAppHistoryMessages = [];
          return records;
        })();
        """
    )
    return records if isinstance(records, list) else []


def normalize_whatsapp_observer_records(
    records: list[dict[str, str]],
    limit: int = 50,
    chat_context: Optional[dict[str, object]] = None,
) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    chat_context = chat_context or {}
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        text = str(record.get("text") or "").strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        if any(line in WHATSAPP_UI_LINES for line in lines[:2]):
            continue
        sender, timestamp_label, message = lines[0], lines[1], "\n".join(lines[2:])
        if timestamp_label not in {"昨天", "今天"} and ":" not in timestamp_label and "/" not in timestamp_label:
            continue
        if not sender or not message or len(sender) > 80 or len(message) > 1500:
            continue
        key = (sender, timestamp_label, message)
        if key in seen:
            continue
        seen.add(key)
        messages.append(
            {
                "sender": sender,
                "chat_name": chat_context.get("chat_name"),
                "source_kind": chat_context.get("source_kind", "unknown"),
                "participants": chat_context.get("participants", []),
                "message_direction": "incoming",
                "timestamp_label": timestamp_label,
                "message": message,
                "captured_at": str(record.get("captured_at") or ""),
                "capture_scope": "mutation_observer",
            }
        )
        if len(messages) >= limit:
            break
    return messages


def normalize_whatsapp_history_records(
    records: list[dict[str, str]],
    chat_context: Optional[dict[str, object]] = None,
) -> list[dict[str, object]]:
    normalized = normalize_whatsapp_observer_records(records, chat_context=chat_context)
    seen = set()
    deduped = []
    for item in normalized:
        key = (item.get("chat_name"), item.get("sender"), item.get("timestamp_label"), item.get("message"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append({**item, "capture_scope": "history_scroll_sync"})
    return deduped


def is_gmail_timestamp_label(value: str) -> bool:
    return bool(re.match(r"^(\d{1,2}:\d{2}|\d{1,2}月\d{1,2}日|\d{4}/\d{1,2}/\d{1,2})$", value))


def is_probable_gmail_sender(value: str) -> bool:
    if not value or value in GMAIL_UI_LINES:
        return False
    if value.isdigit():
        return False
    if len(value) > 80:
        return False
    return True


def parse_gmail_inbox_previews(lines: list[str], limit: int = 10) -> list[dict[str, str]]:
    previews: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, line in enumerate(lines):
        if line != "-":
            continue
        if index < 2 or index + 1 >= len(lines):
            continue

        subject = lines[index - 1].strip()
        sender_index = index - 2
        while sender_index >= 0 and (lines[sender_index].strip().isdigit() or lines[sender_index].strip() in GMAIL_UI_LINES):
            sender_index -= 1
        if sender_index < 0:
            continue

        sender = lines[sender_index].strip()
        snippet = lines[index + 1].strip()
        if not subject or not snippet or not is_probable_gmail_sender(sender):
            continue
        if subject in GMAIL_UI_LINES or len(subject) > 180 or len(snippet) < 8:
            continue

        timestamp_label = ""
        for candidate in lines[index + 2 : index + 7]:
            candidate = candidate.strip()
            if is_gmail_timestamp_label(candidate):
                timestamp_label = candidate
                break

        key = (sender, subject, snippet[:120])
        if key in seen:
            continue
        seen.add(key)
        previews.append(
            {
                "sender": sender[:120],
                "subject": subject[:220],
                "snippet": snippet[:1000],
                "timestamp_label": timestamp_label,
                "capture_scope": "inbox_preview",
            }
        )
        if len(previews) >= limit:
            break
    return previews


def is_gmail_open_thread_time(value: str) -> bool:
    return bool(
        re.match(r"^\d{1,2}:\d{2}(?:\s*\(.+\))?$", value)
        or re.match(r"^\d{4}年\d{1,2}月\d{1,2}日.*\d{1,2}:\d{2}$", value)
        or re.match(r"^\d{1,2}月\d{1,2}日.*\d{1,2}:\d{2}$", value)
    )


def is_probable_gmail_sender_line(value: str) -> bool:
    return bool("<" in value and "@" in value and ">" in value) or bool("@" in value and len(value) < 160)


def is_probable_attachment_filename(value: str) -> bool:
    return bool(re.search(r"\.(pdf|docx?|xlsx?|pptx?|txt|csv|zip|rar|png|jpe?g|webp)$", value.strip(), re.I))


def parse_gmail_labels(value: str) -> list[str]:
    if not value.startswith("标签:") and not value.lower().startswith("labels:"):
        return []
    label_text = re.sub(r"^(标签:|labels:)\s*", "", value, flags=re.I).strip()
    return [label for label in re.split(r"[\s,，/]+", label_text) if label]


def protect_gmail_text(text: str) -> tuple[str, list[str]]:
    reasons: list[str] = []
    protected = text
    if GMAIL_SECRET_LINK_RE.search(protected):
        reasons.append("secret_link")
        protected = GMAIL_SECRET_LINK_RE.sub("URL_REDACTED", protected)
    if GMAIL_VERIFICATION_RE.search(protected):
        reasons.append("verification_code")
        protected = GMAIL_VERIFICATION_RE.sub(r"\1CODE_1", protected)
    if GMAIL_ORDER_RE.search(protected):
        reasons.append("order_or_payment")
        protected = GMAIL_ORDER_RE.sub(r"\1ORDER_1", protected)
    if re.search(r"(付款|支付|金额|price|payment|paid)", protected, re.I) and GMAIL_AMOUNT_RE.search(protected):
        if "order_or_payment" not in reasons:
            reasons.append("order_or_payment")
        protected = GMAIL_AMOUNT_RE.sub("AMOUNT_1", protected)
    return protected, reasons


def protect_gmail_payload(payload: dict[str, object]) -> dict[str, object]:
    protected = dict(payload)
    reasons: list[str] = []
    for field in ("subject", "body", "snippet"):
        value = protected.get(field)
        if not isinstance(value, str):
            continue
        masked, field_reasons = protect_gmail_text(value)
        protected[field] = masked
        reasons.extend(field_reasons)
    deduped_reasons = list(dict.fromkeys(reasons))
    protected["sensitive"] = bool(deduped_reasons)
    if deduped_reasons:
        protected["sensitive_reasons"] = deduped_reasons
    return protected


def parse_gmail_open_thread(lines: list[str]) -> Optional[dict[str, str]]:
    cleaned = [line.strip() for line in lines if line.strip()]
    for index, line in enumerate(cleaned):
        if not is_probable_gmail_sender_line(line):
            continue
        if index == 0 or index + 1 >= len(cleaned):
            continue
        timestamp_label = cleaned[index + 1]
        if not is_gmail_open_thread_time(timestamp_label):
            continue

        subject_index = index - 1
        while subject_index >= 0 and cleaned[subject_index] in GMAIL_UI_LINES:
            subject_index -= 1
        if subject_index < 0:
            continue
        subject = cleaned[subject_index]
        if not subject or subject in GMAIL_UI_LINES or subject == "-":
            continue

        body_lines: list[str] = []
        attachments: list[str] = []
        labels: list[str] = []
        for candidate in cleaned[index + 2 :]:
            if candidate in GMAIL_UI_LINES:
                break
            if is_probable_gmail_sender_line(candidate) or is_gmail_open_thread_time(candidate):
                break
            if candidate in {"附件", "Attachments"}:
                continue
            parsed_labels = parse_gmail_labels(candidate)
            if parsed_labels:
                labels.extend(parsed_labels)
                continue
            if is_probable_attachment_filename(candidate):
                if candidate not in attachments:
                    attachments.append(candidate[:240])
                continue
            if candidate == "-" or len(candidate) < 2:
                continue
            body_lines.append(candidate)
            if len("\n".join(body_lines)) >= 4000:
                break
        if not body_lines:
            continue
        thread = {
            "subject": subject[:220],
            "sender": line[:180],
            "timestamp_label": timestamp_label[:120],
            "body": "\n".join(body_lines)[:4000],
            "capture_scope": "open_thread_visible_body",
        }
        if attachments:
            thread["attachments"] = attachments
        if labels:
            thread["labels"] = list(dict.fromkeys(labels))
        return thread
    return None


def is_calendar_time_label(value: str) -> bool:
    return bool(re.match(r"^\d{1,2}:\d{2}$", value.strip()))


def is_calendar_date_context(value: str) -> bool:
    return bool(
        re.search(r"\d{4}年\d{1,2}月\d{1,2}日", value)
        or re.search(r"\d{1,2}月\d{1,2}日", value)
        or value in {"今天", "明天", "昨天"}
    )


def is_probable_calendar_title(value: str) -> bool:
    if not value or value in CALENDAR_UI_LINES:
        return False
    if is_calendar_time_label(value) or is_calendar_date_context(value):
        return False
    if len(value) > 160:
        return False
    return True


def parse_calendar_visible_events(lines: list[str], limit: int = 20) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    date_context = ""
    cleaned = [line.strip() for line in lines if line.strip()]
    for index, line in enumerate(cleaned):
        if is_calendar_date_context(line):
            date_context = line
        if not is_calendar_time_label(line):
            continue
        if index + 2 >= len(cleaned) or not is_calendar_time_label(cleaned[index + 1]):
            continue
        start_time = line
        end_time = cleaned[index + 1]
        title = cleaned[index + 2]
        if not is_probable_calendar_title(title):
            continue
        key = (date_context, start_time, end_time, title)
        if key in seen:
            continue
        seen.add(key)
        events.append(
            {
                "date_context": date_context,
                "start_time": start_time,
                "end_time": end_time,
                "title": title,
                "capture_scope": "calendar_visible",
            }
        )
        if len(events) >= limit:
            break
    return events


def parse_chromium_bookmarks(payload: dict, limit: int = 500) -> list[dict[str, str]]:
    bookmarks: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    def visit(node: dict, path: list[str]) -> None:
        if len(bookmarks) >= limit:
            return
        node_type = node.get("type")
        name = str(node.get("name") or "").strip()
        if node_type == "url":
            url = str(node.get("url") or "").strip()
            if not name or not url or url in seen_urls:
                return
            seen_urls.add(url)
            bookmarks.append(
                {
                    "title": name[:240],
                    "url": url,
                    "folder_path": " / ".join(path),
                    "date_added": str(node.get("date_added") or ""),
                    "capture_scope": "chromium_bookmarks",
                }
            )
            return
        children = node.get("children") or []
        next_path = path + ([name] if name else [])
        for child in children:
            if isinstance(child, dict):
                visit(child, next_path)

    roots = payload.get("roots") or {}
    for root in roots.values():
        if isinstance(root, dict):
            visit(root, [])
    return bookmarks


def is_telegram_timestamp_label(value: str) -> bool:
    value = value.strip()
    return bool(
        re.match(r"^\d{1,2}:\d{2}$", value)
        or value in {"Yesterday", "Today", "昨天", "今天"}
        or re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", value)
    )


def is_probable_telegram_chat_name(value: str) -> bool:
    if not value or value in TELEGRAM_UI_LINES:
        return False
    if is_telegram_timestamp_label(value):
        return False
    if len(value) > 80:
        return False
    return True


def parse_telegram_visible_chats(lines: list[str], limit: int = 30) -> list[dict[str, str]]:
    chats: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    cleaned = [line.strip() for line in lines if line.strip()]
    for index, line in enumerate(cleaned):
        if not is_probable_telegram_chat_name(line):
            continue
        if index + 2 >= len(cleaned):
            continue
        timestamp_label = cleaned[index + 1]
        message = cleaned[index + 2]
        if not is_telegram_timestamp_label(timestamp_label):
            continue
        if not message or message in TELEGRAM_UI_LINES or len(message) > 500:
            continue
        key = (line, timestamp_label, message)
        if key in seen:
            continue
        seen.add(key)
        chats.append(
            {
                "chat_name": line,
                "timestamp_label": timestamp_label,
                "message": message[:500],
                "capture_scope": "telegram_visible_preview",
            }
        )
        if len(chats) >= limit:
            break
    return chats


async def collect_bookmarks(client: httpx.AsyncClient) -> None:
    if not os.path.exists(CHROMIUM_BOOKMARKS_PATH):
        await report_health(client, "bookmark", "degraded", {"message": "Chromium bookmarks file does not exist yet."})
        return
    try:
        with open(CHROMIUM_BOOKMARKS_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        await report_health(client, "bookmark", "degraded", {"message": f"Could not read bookmarks: {exc}"})
        return

    bookmarks = parse_chromium_bookmarks(payload)
    for bookmark in bookmarks:
        await emit_event(client, "bookmark", "bookmark_item", bookmark)

    await report_health(
        client,
        "bookmark",
        "healthy",
        {"bookmark_count": len(bookmarks), "latest_title": bookmarks[0]["title"] if bookmarks else None},
    )


async def collect_telegram(client: httpx.AsyncClient, page) -> None:
    if "web.telegram.org" not in page.url:
        return
    body_text = await page.locator("body").inner_text(timeout=8000)
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    title = await page.title()
    if len(body_text.strip()) < 40:
        await report_health(
            client,
            "telegram",
            "degraded",
            build_degraded_details("telegram", "too_little_visible_text", lines, url=page.url, title=title, min_lines=8),
        )
        return

    chats = parse_telegram_visible_chats(lines)
    for chat in chats:
        await emit_event(
            client,
            "telegram",
            "telegram_message_preview",
            {
                **chat,
                "url": page.url,
                "title": title,
            },
        )

    if chats:
        await report_health(
            client,
            "telegram",
            "healthy",
            {"preview_count": len(chats), "latest_chat": chats[0]["chat_name"]},
        )
    else:
        await report_health(
            client,
            "telegram",
            "degraded",
            build_degraded_details(
                "telegram",
                "no_chat_preview_match",
                lines,
                url=page.url,
                title=title,
                min_lines=8,
                matched_count=0,
            ),
        )


async def collect_gmail(client: httpx.AsyncClient, page) -> None:
    if "mail.google.com" not in page.url:
        return
    body_text = await page.locator("body").inner_text(timeout=8000)
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    title = await page.title()
    if len(body_text.strip()) < 80:
        await report_health(
            client,
            "gmail",
            "degraded",
            build_degraded_details("gmail", "too_little_visible_text", lines, url=page.url, title=title, min_lines=12),
        )
        return

    open_thread = parse_gmail_open_thread(lines)
    if open_thread:
        await emit_event(
            client,
            "gmail",
            "gmail_thread_snapshot",
            protect_gmail_payload({
                **open_thread,
                "url": page.url,
                "title": title,
            }),
        )

    previews = parse_gmail_inbox_previews(lines, limit=10)
    for preview in previews:
        await emit_event(
            client,
            "gmail",
            "gmail_message_preview",
            {
                **preview,
                "url": page.url,
                "title": title,
            },
        )

    if previews:
        await report_health(
            client,
            "gmail",
            "healthy",
            {"preview_count": len(previews), "latest_subject": previews[0]["subject"]},
        )
    else:
        await report_health(
            client,
            "gmail",
            "degraded",
            build_degraded_details(
                "gmail",
                "no_inbox_preview_match",
                lines,
                url=page.url,
                title=title,
                min_lines=12,
                matched_count=0,
            ),
        )


async def collect_calendar(client: httpx.AsyncClient, page) -> None:
    if "calendar.google.com" not in page.url:
        return
    body_text = await page.locator("body").inner_text(timeout=8000)
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    title = await page.title()
    if len(body_text.strip()) < 40:
        await report_health(
            client,
            "calendar",
            "degraded",
            build_degraded_details("calendar", "too_little_visible_text", lines, url=page.url, title=title, min_lines=8),
        )
        return

    events = parse_calendar_visible_events(lines)
    for event in events:
        await emit_event(
            client,
            "calendar",
            "calendar_event",
            {
                **event,
                "url": page.url,
                "title": title,
            },
        )

    if events:
        await report_health(
            client,
            "calendar",
            "healthy",
            {"event_count": len(events), "latest_title": events[0]["title"]},
        )
    else:
        await report_health(
            client,
            "calendar",
            "degraded",
            build_degraded_details(
                "calendar",
                "no_event_match",
                lines,
                url=page.url,
                title=title,
                min_lines=8,
                matched_count=0,
            ),
        )


async def collect_focus(client: httpx.AsyncClient, page) -> None:
    await inject_focus_observer(page)
    key = str(id(page))
    now = datetime.now(timezone.utc)
    state = FOCUS_STATE.get(key)
    if not state or state.get("url") != page.url:
        FOCUS_STATE[key] = {"url": page.url, "title": await page.title(), "started_at": now, "emitted": False}
        return
    if state.get("emitted"):
        return
    started_at = state["started_at"]
    if not isinstance(started_at, datetime):
        return
    duration = int((now - started_at).total_seconds())
    if duration < 120:
        return
    signals = await drain_focus_signals(page)
    focus_score = compute_focus_score(duration, signals)
    await emit_event(
        client,
        "focus",
        "deep_focus",
        {
            "url": page.url,
            "title": state.get("title"),
            "duration": duration,
            "signals": signals,
            "focus_score": focus_score,
        },
    )
    state["emitted"] = True
    await report_health(client, "focus", "healthy", {"url": page.url, "duration": duration, "focus_score": focus_score})


def build_focus_observer_script() -> str:
    return """
    (() => {
      if (window.__parFocusObserverInstalled) return true;
      window.__parFocusObserverInstalled = true;
      window.__parFocusSignals = window.__parFocusSignals || { scroll: 0, click: 0, input: 0, copy: 0 };
      const inc = (key) => { window.__parFocusSignals[key] = (window.__parFocusSignals[key] || 0) + 1; };
      window.addEventListener('scroll', () => inc('scroll'), { passive: true, capture: true });
      window.addEventListener('click', () => inc('click'), { passive: true, capture: true });
      window.addEventListener('input', () => inc('input'), { passive: true, capture: true });
      window.addEventListener('copy', () => inc('copy'), { passive: true, capture: true });
      return true;
    })();
    """


async def inject_focus_observer(page) -> None:
    await page.evaluate(build_focus_observer_script())


async def drain_focus_signals(page) -> dict[str, int]:
    signals = await page.evaluate(
        """
        (() => {
          const current = window.__parFocusSignals || { scroll: 0, click: 0, input: 0, copy: 0 };
          window.__parFocusSignals = { scroll: 0, click: 0, input: 0, copy: 0 };
          return current;
        })();
        """
    )
    if not isinstance(signals, dict):
        return {"scroll": 0, "click": 0, "input": 0, "copy": 0}
    return {key: int(signals.get(key) or 0) for key in ["scroll", "click", "input", "copy"]}


def compute_focus_score(duration_seconds: int, signals: dict[str, int]) -> float:
    duration_score = min(max(duration_seconds, 0) / 300, 1.0) * 0.55
    interaction_points = (
        min(signals.get("scroll", 0), 5) * 0.05
        + min(signals.get("click", 0), 5) * 0.05
        + min(signals.get("input", 0), 3) * 0.08
        + min(signals.get("copy", 0), 2) * 0.08
    )
    return round(min(duration_score + interaction_points, 1.0), 3)


async def run_degraded_loop(client: httpx.AsyncClient, message: str) -> None:
    for collector in COLLECTORS:
        await report_health(
            client,
            collector,
            "degraded",
            {
                "runtime": "fallback",
                "message": message,
            },
        )

    while True:
        await report_health(client, "runtime", "degraded", {"message": message})
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
