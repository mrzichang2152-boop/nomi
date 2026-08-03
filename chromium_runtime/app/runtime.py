import asyncio
import hashlib
import json
import os
import re
import time
from urllib.parse import parse_qs, urlencode, urlparse
from datetime import datetime, timezone
from typing import Any, Optional

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
GMAIL_AUTO_OPEN = os.getenv("GMAIL_AUTO_OPEN", "false").lower() == "true"
CHROMIUM_AUTO_OPEN_SOURCES = os.getenv("CHROMIUM_AUTO_OPEN_SOURCES", "")
WHATSAPP_HISTORY_SYNC = os.getenv("WHATSAPP_HISTORY_SYNC", "false").lower() == "true"
CHROMIUM_BOOKMARKS_PATH = os.getenv("CHROMIUM_BOOKMARKS_PATH", "/app/user_profile/Default/Bookmarks")
CLOSE_PAGE_TIMEOUT_SECONDS = float(os.getenv("CLOSE_PAGE_TIMEOUT_SECONDS", "1.5"))
LINKEDIN_SEARCH_GOTO_TIMEOUT_MS = int(os.getenv("LINKEDIN_SEARCH_GOTO_TIMEOUT_MS", "8000"))
COLLECTORS = ["search", "whatsapp", "gmail", "calendar", "telegram", "linkedin", "focus", "bookmark"]
MANAGED_PAGE_CATALOG = {
    "gmail": {
        "host_fragment": "mail.google.com",
        "url": (
            "https://accounts.google.com/ServiceLogin?service=mail"
            "&continue=https%3A%2F%2Fmail.google.com%2Fmail%2Fu%2F0%2F%23inbox"
        ),
        "alternate_url_fragments": ["accounts.google.com"],
    },
    "whatsapp": {
        "host_fragment": "web.whatsapp.com",
        "url": "https://web.whatsapp.com/",
    },
    "calendar": {
        "host_fragment": "calendar.google.com",
        "url": "https://calendar.google.com/calendar/u/0/r",
        "alternate_url_fragments": ["workspace.google.com/intl/en-US/products/calendar"],
    },
    "telegram": {
        "host_fragment": "web.telegram.org",
        "url": "https://web.telegram.org/",
    },
    "linkedin": {
        "host_fragment": "linkedin.com",
        "url": "https://www.linkedin.com/login",
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
LINKEDIN_AUTO_OPENED_PROFILES: set[str] = set()
FOCUS_COLLECTION_EXCLUDED_SOURCES = {"whatsapp", "telegram", "linkedin", "gmail", "calendar"}
WHATSAPP_UI_LINES = {
    "所有",
    "未读",
    "特别关注",
    "群组",
    "All",
    "Unread",
    "Favorites",
    "Groups",
    "开启后台同步",
    "在后台同步消息，获享更快的性能。",
    "Message notifications are off.\u00a0Turn on",
    "Message notifications are off. Turn on",
    "你的私人消息已进行端到端加密",
    "Your personal messages are end-to-end encrypted",
    "消息和通话已进行端到端加密。只有此聊天中的成员可以查看、收听或分享。",
    "消息和通话已进行端到端加密。只有此聊天中的成员可以查看、收听或分享。点击了解更多",
    "Messages and calls are end-to-end encrypted.",
    "发送文档",
    "添加联系人",
    "Send document",
    "Add contact",
    "输入消息",
    "Type a message",
}
WHATSAPP_RELATIVE_TIME_LABELS = {
    "今天",
    "昨天",
    "Today",
    "Yesterday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
    "周一",
    "周二",
    "周三",
    "周四",
    "周五",
    "周六",
    "周日",
    "星期一",
    "星期二",
    "星期三",
    "星期四",
    "星期五",
    "星期六",
    "星期日",
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
GMAIL_THREAD_SUBJECT_CHROME_RE = re.compile(
    r"^(?:"
    r"第\s*\d+\s*个会话，共\s*\d+\s*个|"
    r"全部打印|"
    r"在新窗口中查看|"
    r"搜索所有带.+标签的邮件|"
    r"从此会话中移除.+标签"
    r")$"
)
GMAIL_THREAD_LEADING_BODY_UI_LINES = {
    "添加回应",
    "更多",
    "回复",
    "转发",
    "添加表情符号回应",
}
GMAIL_THREAD_BODY_TERMINATORS = {
    "回复",
    "转发",
    "添加表情符号回应",
}
GMAIL_SECRET_LINK_RE = re.compile(r"https?://\S*(?:token|code|auth|verify|reset|password|login)\S*", re.I)
GMAIL_VERIFICATION_RE = re.compile(
    r"("
    r"(?:(?:验证码|校验码)[^\dA-Za-z]{0,8}|"
    r"(?:verification\s+code|login\s+code|security\s+code|code)\b[^\dA-Za-z]{1,8})"
    r")([A-Za-z0-9-]{4,12})",
    re.I,
)
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
LINKEDIN_UI_LINES = {
    "LinkedIn",
    "Home",
    "My Network",
    "Jobs",
    "Messaging",
    "Notifications",
    "Me",
    "For Business",
    "Search",
    "Skip to search",
    "Skip to main content",
    "Skip to sidebar",
    "Skip to primary content",
    "Skip to aside",
    "Start a post",
    "Video",
    "Photo",
    "Write article",
    "Feed post",
    "Suggested",
    "Promoted",
    "Follow",
    "Connect",
    "Apply",
    "Easy Apply",
    "Save",
    "Share",
    "Show more",
    "About",
    "Privacy & Terms",
    "Ad Choices",
    "Advertising",
    "Business Services",
    "Get the LinkedIn app",
    "People",
    "1st",
    "2nd",
    "3rd+",
    "Locations",
    "Current companies",
    "All filters",
    "Next",
}
COLLECTOR_SELECTOR_HINTS = {
    "gmail": ["div[role='main']", "tr[role='row']", "div[role='listitem']", "span[email]"],
    "calendar": ["[data-eventid]", "[role='gridcell']", "[aria-label*='event']", "[aria-label*='日程']"],
    "telegram": [".chatlist", "[class*='Chat']", "[class*='message']"],
    "whatsapp": ["#pane-side", "div[role='row']", "div[data-testid*='msg']", "div[aria-label*='message']"],
    "linkedin": [
        "main",
        "[data-job-id]",
        ".jobs-search-results-list",
        ".jobs-details",
        ".feed-shared-update-v2",
        ".profile-card-member-details",
    ],
}
COLLECTOR_UI_LINES = {
    "gmail": GMAIL_UI_LINES,
    "calendar": CALENDAR_UI_LINES,
    "telegram": TELEGRAM_UI_LINES,
    "whatsapp": WHATSAPP_UI_LINES,
    "linkedin": LINKEDIN_UI_LINES,
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


async def safe_report_health(client: httpx.AsyncClient, collector: str, status: str, details: dict) -> None:
    try:
        await report_health(client, collector, status, details)
    except Exception:
        return


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
        fragments = [target["host_fragment"], *target.get("alternate_url_fragments", [])]
        if not any(any(fragment in url for fragment in fragments) for url in open_urls):
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


def is_browser_context_closed_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "target page, context or browser has been closed" in message


def resolve_browser_context(context_or_ref):
    if isinstance(context_or_ref, dict) and "context" in context_or_ref:
        return context_or_ref["context"]
    return context_or_ref


def source_for_page_url(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if "mail.google.com" in parsed.netloc:
        return "gmail"
    if "accounts.google.com" in parsed.netloc:
        params = parse_qs(parsed.query)
        service = (params.get("service") or [""])[0]
        continue_url = (params.get("continue") or [""])[0]
        followup = (params.get("followup") or [""])[0]
        target = " ".join([service, continue_url, followup])
        if "mail.google.com" in target or service == "mail":
            return "gmail"
        if "calendar.google.com" in target or service == "cl":
            return "calendar"
    if "web.whatsapp.com" in parsed.netloc:
        return "whatsapp"
    if "calendar.google.com" in parsed.netloc:
        return "calendar"
    if "web.telegram.org" in parsed.netloc:
        return "telegram"
    if "linkedin.com" in parsed.netloc:
        return "linkedin"
    if "google." in parsed.netloc:
        return "search"
    return None


def detect_browser_login_state(source: str, url: str, title: str, lines_or_text) -> dict[str, object]:
    normalized = (source or "").strip().lower()
    if isinstance(lines_or_text, str):
        lines = [line.strip() for line in lines_or_text.splitlines() if line.strip()]
    else:
        lines = [str(line).strip() for line in (lines_or_text or []) if str(line).strip()]
    text = "\n".join(lines)
    parsed = urlparse(url or "")
    lower_text = text.lower()
    result: dict[str, object] = {
        "login_state": "unknown",
        "confidence": 0.0,
        "url": url,
        "title": title,
    }

    if normalized in {"gmail", "calendar"} and "accounts.google.com" in parsed.netloc:
        result.update(
            {
                "login_state": "logged_out",
                "confidence": 0.95,
                "failure_reason": "login_required",
                "user_action": "请在云端浏览器完成 Google 登录。",
            }
        )
        return result

    if normalized == "whatsapp":
        whatsapp_storage_error_markers = [
            "database error",
            "browser database error",
            "relink your device",
            "re-link your device",
            "数据库错误",
            "重新关联你的设备",
            "重新链接你的设备",
            "请重新关联",
            "请重新链接",
        ]
        if any(marker in lower_text for marker in whatsapp_storage_error_markers):
            result.update(
                {
                    "login_state": "storage_error",
                    "confidence": 0.95,
                    "failure_reason": "browser_message_database_error",
                    "user_action": "WhatsApp Web 本地消息数据库异常，请清理该浏览器的 WhatsApp 会话后重新扫码关联。",
                }
            )
            return result
        whatsapp_syncing_markers = [
            "loading your chats",
            "loading your messages",
            "downloading your messages",
            "please do not close this window",
            "正在加载你的对话",
            "正在加载对话",
            "消息正在下载",
            "请不要关闭此窗口",
            "正在登录",
            "确保 whatsapp 在两台设备上保持打开状态",
        ]
        if any(marker in lower_text for marker in whatsapp_syncing_markers):
            result.update(
                {
                    "login_state": "syncing",
                    "confidence": 0.9,
                    "failure_reason": "message_database_syncing",
                    "user_action": "保持 WhatsApp 手机端和云端浏览器在线，等待消息数据库同步完成。",
                }
            )
            return result
        whatsapp_login_markers = [
            "Scan to log in",
            "Scan the QR code",
            "Link with phone number",
            "Log in with phone number",
            "扫描登录",
            "扫描二维码",
            "使用电话号码登录",
            "电话号码",
            "开始使用",
            "创建账户",
            "关联到你的账户",
        ]
        if any(marker in text for marker in whatsapp_login_markers):
            result.update(
                {
                    "login_state": "logged_out",
                    "confidence": 0.98,
                    "failure_reason": "login_required",
                    "user_action": "请在云端浏览器扫码登录 WhatsApp Web。",
                }
            )
            return result
        if any(marker in text for marker in ["搜索或开始新聊天", "Search or start new chat", "你的私人消息已进行端到端加密", "end-to-end encrypted"]):
            result.update({"login_state": "logged_in", "confidence": 0.8})
            return result

    if normalized == "telegram":
        telegram_logged_in_markers = [
            "Search",
            "Contacts",
            "Settings",
            "last seen",
            "Contacts last seen",
            "Message",
            "ADD TO CONTACTS",
            "BLOCK USER",
        ]
        if any(marker in text for marker in telegram_logged_in_markers) or any(
            marker in lower_text for marker in ["last seen", "message"]
        ):
            result.update({"login_state": "logged_in", "confidence": 0.85})
            return result
        if any(marker in lower_text for marker in ["log in by phone", "phone number", "please confirm your country code"]):
            result.update(
                {
                    "login_state": "logged_out",
                    "confidence": 0.95,
                    "failure_reason": "login_required",
                    "user_action": "请在云端浏览器登录 Telegram Web。",
                }
            )
            return result

    if normalized == "linkedin":
        page_kind = linkedin_page_kind(url, title)
        result["page_kind"] = page_kind
        linkedin_logged_in_markers = ["Home", "My Network", "Jobs", "Messaging", "Notifications", "People", "Apply", "Easy Apply"]
        if any(marker in text for marker in linkedin_logged_in_markers):
            result.update({"login_state": "logged_in", "confidence": 0.85})
            return result
        if parsed.path.rstrip("/") in {"/login", "/uas/login"} or any(
            marker in lower_text for marker in ["email or phone", "join linkedin"]
        ):
            result.update(
                {
                    "login_state": "logged_out",
                    "confidence": 0.95,
                    "failure_reason": "login_required",
                    "user_action": "请在云端浏览器登录 LinkedIn。",
                }
            )
            return result

    return result


def is_google_gsi_blank_popup_state(state: dict) -> bool:
    url = str(state.get("url") or "")
    parsed = urlparse(url)
    if "accounts.google.com" not in parsed.netloc or parsed.path != "/gsi/select":
        return False
    if str(state.get("ready_state") or "").lower() != "complete":
        return False
    if str(state.get("window_name") or "") != "g_credential_picker":
        return False
    if not bool(state.get("opener_is_self")):
        return False
    body_text = str(state.get("body_text") or "").strip()
    if body_text:
        return False
    try:
        visible_content_height = float(state.get("visible_content_height") or 0)
    except (TypeError, ValueError):
        visible_content_height = 0
    return visible_content_height <= 1


async def google_gsi_popup_state(page) -> dict:
    return await page.evaluate(
        """
        () => {
            const visibleContentHeight = Array.from(document.body ? document.body.children : [])
                .map((el) => {
                    const style = getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return 0;
                    const rect = el.getBoundingClientRect();
                    return Math.max(0, rect.height);
                })
                .reduce((total, value) => total + value, 0);
            let openerIsSelf = false;
            try {
                openerIsSelf = window.opener === window;
            } catch (error) {
                openerIsSelf = false;
            }
            return {
                url: location.href,
                ready_state: document.readyState,
                window_name: window.name || '',
                opener_is_self: openerIsSelf,
                body_text: document.body ? document.body.innerText : '',
                visible_content_height: visibleContentHeight,
            };
        }
        """
    )


async def recover_google_gsi_blank_popup_if_needed(client: httpx.AsyncClient, page) -> bool:
    try:
        state = await google_gsi_popup_state(page)
    except Exception:
        return False
    if not is_google_gsi_blank_popup_state(state):
        return False
    target_url = MANAGED_PAGE_CATALOG["linkedin"]["url"]
    original_url = str(state.get("url") or getattr(page, "url", ""))
    await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
    await page.bring_to_front()
    await report_health(
        client,
        "linkedin",
        "degraded",
        {
            "recovery": "google_gsi_blank_popup",
            "url": original_url,
            "target_url": target_url,
            "message": "Google sign-in popup lost its LinkedIn opener context and was restored to LinkedIn login.",
        },
    )
    return True


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


async def report_initial_collector_health(client: httpx.AsyncClient) -> None:
    await asyncio.gather(
        *[
            safe_report_health(
                client,
                collector,
                "degraded" if collector in {"whatsapp", "gmail", "calendar", "linkedin"} else "healthy",
                {
                    "runtime": "playwright",
                    "message": "Collector scaffold loaded. Account login and DOM adapters are next.",
                },
            )
            for collector in COLLECTORS
        ]
    )


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
                context_ref = {"browser": browser, "context": context}

                background_tasks = [
                    asyncio.create_task(collector_loop(client, context_ref), name="collector_loop"),
                    asyncio.create_task(browser_command_loop(client, context_ref), name="browser_command_loop"),
                ]
                asyncio.create_task(report_initial_collector_health(client), name="initial_collector_health")

                while True:
                    for task in background_tasks:
                        if task.done():
                            exc = task.exception()
                            await safe_report_health(
                                client,
                                "runtime",
                                "degraded",
                                {
                                    "message": f"background task stopped: {task.get_name()}",
                                    "error": str(exc) if exc else "",
                                },
                            )
                    page_count = sum(len(context.pages) for context in browser.contexts)
                    await report_health(client, "runtime", "healthy", {"pages": page_count})
                    await asyncio.sleep(60)
        except Exception as exc:
            await run_degraded_loop(client, f"Chromium unavailable: {exc}")


async def connect_to_visible_browser(playwright, attempts: int = 30, delay_seconds: float = 1.0):
    if CHROMIUM_CDP_URL:
        last_error: Exception | None = None
        for attempt in range(max(1, attempts)):
            try:
                browser = await playwright.chromium.connect_over_cdp(CHROMIUM_CDP_URL)
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                return browser, context
            except Exception as exc:
                last_error = exc
                if attempt >= attempts - 1:
                    break
                await asyncio.sleep(delay_seconds)
        raise last_error or RuntimeError("Could not connect to Chromium CDP.")

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir="/app/user_profile",
        executable_path=CHROMIUM_EXECUTABLE,
        headless=CHROMIUM_HEADLESS,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-gpu-rasterization",
            "--disable-session-crashed-bubble",
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
    await goto_managed_url(page, source_for_page_url(url), url)


def is_nonfatal_managed_navigation_timeout(source: str, url: str, exc: Exception) -> bool:
    if (source or "").strip().lower() != "whatsapp":
        return False
    if "web.whatsapp.com" not in str(url or ""):
        return False
    message = str(exc)
    return "Timeout" in message and "Page.goto" in message


async def goto_managed_url(page, source: str, url: str) -> dict[str, object]:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return {"ok": True, "timed_out": False}
    except Exception as exc:
        if is_nonfatal_managed_navigation_timeout(source, url, exc):
            return {
                "ok": True,
                "timed_out": True,
                "message": "WhatsApp Web navigation started but did not finish domcontentloaded before timeout.",
            }
        raise


async def start_linkedin_search_navigation(page, url: str) -> dict[str, object]:
    """Start heavy LinkedIn search navigation without waiting for the full app shell.

    LinkedIn jobs/people search can spend a long time hydrating the logged-in SPA.
    The command queue only needs to move the visible browser to the target; the
    collector will validate and parse the DOM on subsequent cycles.
    """
    async def background_goto() -> None:
        await page.goto(url, wait_until="commit", timeout=LINKEDIN_SEARCH_GOTO_TIMEOUT_MS)

    task = asyncio.create_task(background_goto())

    def consume_task_exception(done_task: asyncio.Task) -> None:
        try:
            done_task.exception()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    task.add_done_callback(consume_task_exception)
    await asyncio.sleep(0)
    return {"ok": True, "method": "goto_background", "timed_out": False}


async def bring_page_to_front_best_effort(page, timeout_seconds: float = 1.0) -> None:
    try:
        await asyncio.wait_for(page.bring_to_front(), timeout=timeout_seconds)
    except Exception:
        pass


def browser_command_target(source: str) -> Optional[dict[str, str]]:
    normalized = (source or "").strip().lower()
    target = MANAGED_PAGE_CATALOG.get(normalized)
    if not target:
        return None
    return {"source": normalized, **target}


def normalize_allowed_direct_browser_url(source: str, url: str) -> Optional[str]:
    normalized_source = (source or "").strip().lower()
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = re.sub(r"/+", "/", parsed.path or "/")
    if normalized_source != "linkedin":
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    if host not in {"linkedin.com", "www.linkedin.com"}:
        return None
    if not re.fullmatch(r"/in/[A-Za-z0-9._%-]+/?", path):
        return None
    if not path.endswith("/"):
        path += "/"
    return f"https://www.linkedin.com{path}"


def normalize_allowed_linkedin_job_detail_url(source: str, url: str) -> Optional[str]:
    normalized_source = (source or "").strip().lower()
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = re.sub(r"/+", "/", parsed.path or "/")
    if normalized_source != "linkedin":
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    if host not in {"linkedin.com", "www.linkedin.com"}:
        return None
    if not re.fullmatch(r"/jobs/view/[0-9]+/?", path):
        return None
    if not path.endswith("/"):
        path += "/"
    return f"https://www.linkedin.com{path}"


def normalize_allowed_linkedin_contact_search_url(source: str, url: str) -> Optional[str]:
    normalized_source = (source or "").strip().lower()
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = re.sub(r"/+", "/", parsed.path or "/")
    if normalized_source != "linkedin":
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    if host not in {"linkedin.com", "www.linkedin.com"}:
        return None
    if path.rstrip("/") != "/search/results/people":
        return None
    keywords = (parse_qs(parsed.query).get("keywords") or [""])[0].strip()
    if not keywords:
        return None
    return "https://www.linkedin.com/search/results/people/?" + urlencode({"keywords": keywords[:500]})


def normalize_allowed_linkedin_job_search_url(source: str, url: str) -> Optional[str]:
    normalized_source = (source or "").strip().lower()
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = re.sub(r"/+", "/", parsed.path or "/")
    if normalized_source != "linkedin":
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    if host not in {"linkedin.com", "www.linkedin.com"}:
        return None
    if path.rstrip("/") != "/jobs/search":
        return None
    query = (parse_qs(parsed.query).get("keywords") or [""])[0].strip()
    location = (parse_qs(parsed.query).get("location") or [""])[0].strip()
    if not query:
        return None
    params = {"keywords": query[:500]}
    if location:
        params["location"] = location[:180]
    return "https://www.linkedin.com/jobs/search/?" + urlencode(params)


async def execute_browser_open_command(context, command: dict) -> dict[str, str]:
    if not isinstance(command, dict) or command.get("action") != "open_url":
        return {"status": "ignored", "source": "", "url": ""}
    target = browser_command_target(str(command.get("source") or ""))
    if not target:
        return {"status": "ignored", "source": str(command.get("source") or ""), "url": ""}
    host_fragment = target["host_fragment"]
    url = target["url"]
    page = current_browser_page(context, target["source"], allow_last_fallback=False)
    mark_manual_browser_focus(target["source"])
    if page is not None:
        if host_fragment in page.url:
            nav = await goto_managed_url(page, target["source"], url)
            await page.bring_to_front()
            await close_other_pages(context, page)
            result = {"status": "focused", "source": target["source"], "url": url}
            if nav.get("timed_out"):
                result["message"] = str(nav.get("message") or "")
            return result
        nav = await goto_managed_url(page, target["source"], url)
        await page.bring_to_front()
        await close_other_pages(context, page)
        result = {"status": "navigated", "source": target["source"], "url": url}
        if nav.get("timed_out"):
            result["message"] = str(nav.get("message") or "")
        return result
    page = await context.new_page()
    nav = await goto_managed_url(page, target["source"], url)
    await page.bring_to_front()
    await close_other_pages(context, page)
    result = {"status": "opened", "source": target["source"], "url": url}
    if nav.get("timed_out"):
        result["message"] = str(nav.get("message") or "")
    return result


async def execute_browser_open_direct_command(context, command: dict) -> dict[str, str]:
    source = str(command.get("source") or "")
    url = str(command.get("url") or "")
    allowed_url = normalize_allowed_direct_browser_url(source, url)
    if not allowed_url:
        return {
            "status": "ignored",
            "source": source,
            "url": url,
            "message": "URL is not allowed for direct browser navigation.",
        }
    page = current_browser_page(context, "linkedin", allow_last_fallback=False)
    mark_manual_browser_focus("linkedin")
    if page is None:
        page = await context.new_page()
        await page.goto(allowed_url, wait_until="domcontentloaded", timeout=30000)
        await page.bring_to_front()
        return {"status": "opened", "source": "linkedin", "url": allowed_url}
    await page.goto(allowed_url, wait_until="domcontentloaded", timeout=30000)
    await page.bring_to_front()
    return {"status": "navigated", "source": "linkedin", "url": allowed_url}


async def execute_browser_open_linkedin_job_detail_command(context, command: dict) -> dict[str, str]:
    source = str(command.get("source") or "")
    url = str(command.get("url") or "")
    allowed_url = normalize_allowed_linkedin_job_detail_url(source, url)
    if not allowed_url:
        return {
            "status": "ignored",
            "source": source,
            "url": url,
            "message": "URL is not allowed for LinkedIn job detail.",
        }
    page = current_browser_page(context, "linkedin", allow_last_fallback=False)
    mark_manual_browser_focus("linkedin")
    if page is None:
        page = await context.new_page()
        await page.goto(allowed_url, wait_until="domcontentloaded", timeout=30000)
        await page.bring_to_front()
        return {"status": "opened", "source": "linkedin", "url": allowed_url}
    await page.goto(allowed_url, wait_until="domcontentloaded", timeout=30000)
    await page.bring_to_front()
    return {"status": "navigated", "source": "linkedin", "url": allowed_url}


async def execute_browser_open_linkedin_contact_search_command(context, command: dict) -> dict[str, str]:
    source = str(command.get("source") or "")
    url = str(command.get("url") or "")
    allowed_url = normalize_allowed_linkedin_contact_search_url(source, url)
    if not allowed_url:
        return {
            "status": "ignored",
            "source": source,
            "url": url,
            "message": "URL is not allowed for LinkedIn contact search.",
        }
    page = current_browser_page(context, "linkedin", allow_last_fallback=False)
    mark_manual_browser_focus("linkedin")
    if page is None:
        page = await context.new_page()
        nav = await start_linkedin_search_navigation(page, allowed_url)
        await bring_page_to_front_best_effort(page)
        result = {"status": "opened", "source": "linkedin", "url": allowed_url}
        if nav.get("timed_out"):
            result["message"] = str(nav.get("message") or "")
        return result
    nav = await start_linkedin_search_navigation(page, allowed_url)
    await bring_page_to_front_best_effort(page)
    result = {"status": "navigated", "source": "linkedin", "url": allowed_url}
    if nav.get("timed_out"):
        result["message"] = str(nav.get("message") or "")
    return result


async def execute_browser_open_linkedin_job_search_command(context, command: dict) -> dict[str, str]:
    source = str(command.get("source") or "")
    url = str(command.get("url") or "")
    allowed_url = normalize_allowed_linkedin_job_search_url(source, url)
    if not allowed_url:
        return {
            "status": "ignored",
            "source": source,
            "url": url,
            "message": "URL is not allowed for LinkedIn job search.",
        }
    page = current_browser_page(context, "linkedin", allow_last_fallback=False)
    mark_manual_browser_focus("linkedin")
    if page is None:
        page = await context.new_page()
        nav = await start_linkedin_search_navigation(page, allowed_url)
        await bring_page_to_front_best_effort(page)
        result = {"status": "opened", "source": "linkedin", "url": allowed_url}
        if nav.get("timed_out"):
            result["message"] = str(nav.get("message") or "")
        return result
    nav = await start_linkedin_search_navigation(page, allowed_url)
    await bring_page_to_front_best_effort(page)
    result = {"status": "navigated", "source": "linkedin", "url": allowed_url}
    if nav.get("timed_out"):
        result["message"] = str(nav.get("message") or "")
    return result


async def execute_browser_type_command(context, command: dict) -> dict[str, str]:
    if not isinstance(command, dict) or command.get("action") != "type_text":
        return {"status": "ignored", "source": "manual", "url": ""}
    text = str(command.get("text") or "")
    if not text:
        return {"status": "ignored", "source": "manual", "url": ""}
    manual_source = active_manual_browser_focus_source()
    page = current_manual_login_page(context, manual_source) if manual_source else current_browser_page(context)
    if page is None:
        return {"status": "failed", "source": "manual", "url": "", "message": "No visible browser page."}
    await page.bring_to_front()
    await page.keyboard.type(text[:2048], delay=1)
    if bool(command.get("submit", False)):
        await page.keyboard.press("Enter")
    return {"status": "typed", "source": "manual", "url": page.url}


async def execute_browser_command(context, command: dict) -> dict[str, str]:
    action = command.get("action") if isinstance(command, dict) else ""
    if action == "open_url":
        return await execute_browser_open_command(context, command)
    if action == "open_url_direct":
        return await execute_browser_open_direct_command(context, command)
    if action == "open_linkedin_job_detail":
        return await execute_browser_open_linkedin_job_detail_command(context, command)
    if action == "open_linkedin_contact_search":
        return await execute_browser_open_linkedin_contact_search_command(context, command)
    if action == "open_linkedin_job_search":
        return await execute_browser_open_linkedin_job_search_command(context, command)
    if action == "type_text":
        return await execute_browser_type_command(context, command)
    return {"status": "ignored", "source": "", "url": ""}


async def execute_browser_command_with_timeout(context, command: dict, timeout_seconds: float = 40.0) -> dict[str, str]:
    try:
        return await asyncio.wait_for(execute_browser_command(context, command), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        return {
            "status": "failed",
            "source": str(command.get("source") or "runtime") if isinstance(command, dict) else "runtime",
            "url": str(command.get("url") or command.get("target_url") or "") if isinstance(command, dict) else "",
            "message": "Remote browser command timed out before navigation completed.",
        }


def current_browser_page(
    context,
    preferred_source: str = "",
    fallback_source: str = "",
    allow_last_fallback: bool = True,
):
    pages = list(getattr(context, "pages", []))
    for source in [preferred_source, fallback_source]:
        normalized = (source or "").strip().lower()
        target = MANAGED_PAGE_CATALOG.get(normalized)
        if not target:
            continue
        host_fragment = target["host_fragment"]
        for page in reversed(pages):
            if host_fragment in str(getattr(page, "url", "")):
                return page
    if allow_last_fallback and pages:
        return pages[-1]
    return None


def current_manual_login_page(context, manual_source: str = ""):
    normalized = (manual_source or "").strip().lower()
    if not normalized:
        return current_browser_page(context)
    pages = list(getattr(context, "pages", []))
    for page in reversed(pages):
        if page_allowed_during_manual_login(str(getattr(page, "url", "")), normalized):
            return page
    return current_browser_page(context)


async def close_page_best_effort(page) -> None:
    try:
        await asyncio.wait_for(page.close(), timeout=CLOSE_PAGE_TIMEOUT_SECONDS)
    except Exception:
        pass


async def close_other_pages(context, keep_page) -> None:
    for page in list(getattr(context, "pages", [])):
        if page is keep_page:
            continue
        await close_page_best_effort(page)


def page_allowed_during_manual_login(url: str, source: str) -> bool:
    normalized = (source or "").strip().lower()
    parsed = urlparse(str(url or ""))
    host = parsed.netloc.lower()
    page_source = source_for_page_url(url)
    if page_source == normalized:
        return True
    if normalized in {"gmail", "calendar"} and host == "accounts.google.com":
        return True
    if normalized == "linkedin" and host in {"accounts.google.com", "www.linkedin.com", "linkedin.com"}:
        return True
    return False


async def prune_pages_to_manual_login_source(context, source: str) -> None:
    normalized = (source or "").strip().lower()
    if not normalized:
        return
    for page in list(getattr(context, "pages", [])):
        if page_allowed_during_manual_login(str(getattr(page, "url", "")), normalized):
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


async def report_browser_command_result(
    client: httpx.AsyncClient,
    command: dict,
    result: dict[str, str],
) -> None:
    command_id = str(command.get("command_id") or "").strip()
    if not command_id:
        return
    try:
        await client.post(
            f"{RUNTIME_API_URL}/api/browser/commands/{command_id}/result",
            headers=runtime_api_headers(),
            json={
                "status": str(result.get("status") or "unknown"),
                "source": str(result.get("source") or command.get("source") or "runtime"),
                "expected_event_type": str(command.get("expected_event_type") or ""),
                "details": {
                    "action": command.get("action"),
                    "target_url": result.get("url") or command.get("target_url") or command.get("url") or "",
                    "url": result.get("url") or "",
                    "message": result.get("message") or "",
                    "result": result,
                },
            },
            timeout=5,
        )
    except Exception:
        pass


async def browser_command_loop(client: httpx.AsyncClient, context) -> None:
    print("browser command loop started", flush=True)
    while True:
        try:
            command = await fetch_browser_command(client)
            if command:
                print(
                    f"browser command fetched: {command.get('action')} {command.get('command_id')}",
                    flush=True,
                )
                result = await execute_browser_command_with_timeout(resolve_browser_context(context), command)
                await report_browser_command_result(client, command, result)
                source = result.get("source") or str(command.get("source") or "runtime")
                await safe_report_health(
                    client,
                    source,
                    "healthy" if result.get("status") in {"opened", "focused", "navigated"} else "failed",
                    {
                        "browser_command": command.get("command_id"),
                        "command_result": result,
                        "message": "Remote browser has been navigated for user login.",
                    },
                )
                await asyncio.sleep(0.1)
                continue
        except Exception as exc:
            await safe_report_health(
                client,
                "runtime",
                "degraded",
                {"message": f"browser command loop error: {exc}"},
            )
        await asyncio.sleep(1)


async def ensure_managed_pages(client: httpx.AsyncClient, context, settings: dict[str, dict]) -> None:
    context = resolve_browser_context(context)
    manual_source = active_manual_browser_focus_source()
    if manual_source:
        await prune_pages_to_manual_login_source(context, manual_source)
    targets = filter_managed_targets_for_manual_login(
        managed_page_targets(settings),
        manual_source,
    )
    missing_targets = missing_managed_page_targets(targets, [page.url for page in context.pages])
    closed_context_error: Exception | None = None
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
            if is_browser_context_closed_error(exc):
                closed_context_error = exc
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
    if closed_context_error is not None:
        raise closed_context_error


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


async def run_collector_cycle(client: httpx.AsyncClient, context) -> None:
    try:
        context = resolve_browser_context(context)
        settings = await fetch_collector_settings(client)
        await ensure_managed_pages(client, context, settings)
        if collector_allowed("bookmark", settings):
            await collect_bookmarks(client)
        for page in list(context.pages):
            try:
                if await recover_google_gsi_blank_popup_if_needed(client, page):
                    continue
                page_source = source_for_page_url(page.url)
                body_lines: list[str] = []
                title = ""
                if page_source == "whatsapp":
                    try:
                        title = await page.title()
                        body_text = await page.locator("body").inner_text(timeout=5000)
                        body_lines = [line.strip() for line in body_text.splitlines() if line.strip()]
                    except Exception:
                        body_lines = []
                if should_inject_runtime_hooks(page_source, page.url, title, body_lines):
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
                if collector_allowed("linkedin", settings):
                    await collect_linkedin(client, page)
                if collector_allowed("focus", settings):
                    await collect_focus(client, page)
            except Exception as exc:
                    await report_health(
                        client,
                        "runtime",
                        "degraded",
                        {"message": f"collector loop error: {exc}"},
                    )
    except Exception as exc:
        if is_browser_context_closed_error(exc):
            raise
        await safe_report_health(
            client,
            "runtime",
            "degraded",
            {"message": f"collector loop top-level error: {exc}"},
        )


async def collector_loop(client: httpx.AsyncClient, context, playwright=None) -> None:
    if playwright is None and async_playwright is not None:
        try:
            playwright = await async_playwright().start()
        except Exception as exc:
            await safe_report_health(
                client,
                "runtime",
                "degraded",
                {"message": f"collector playwright startup failed: {exc}"},
            )
    current_browser = context.get("browser") if isinstance(context, dict) else None
    current_context = resolve_browser_context(context)
    while True:
        if playwright is not None:
            try:
                current_browser, current_context = await connect_to_visible_browser(playwright)
                if isinstance(context, dict):
                    context["browser"] = current_browser
                    context["context"] = current_context
            except Exception as exc:
                await safe_report_health(
                    client,
                    "runtime",
                    "degraded",
                    {"message": f"browser context refresh failed: {exc}"},
                )
        try:
            await run_collector_cycle(client, current_context)
        except Exception as exc:
            if is_browser_context_closed_error(exc) and playwright is not None:
                await safe_report_health(
                    client,
                    "runtime",
                    "degraded",
                    {"message": f"browser context closed; reconnecting: {exc}"},
                )
                current_browser, current_context = await connect_to_visible_browser(playwright)
                if isinstance(context, dict):
                    context["browser"] = current_browser
                    context["context"] = current_context
            else:
                await safe_report_health(
                    client,
                    "runtime",
                    "degraded",
                    {"message": f"collector loop top-level error: {exc}"},
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
    body_text = await page.locator("body").inner_text(timeout=5000)
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    title = await page.title()
    login_state = detect_browser_login_state("whatsapp", page.url, title, lines)
    if login_state.get("login_state") != "logged_in":
        message = "WhatsApp Web is not ready for collection."
        if login_state.get("login_state") == "logged_out":
            message = "WhatsApp Web is waiting for user login."
        elif login_state.get("login_state") == "syncing":
            message = "WhatsApp Web is syncing its local message database; collector is waiting without DOM injection."
        elif login_state.get("login_state") == "storage_error":
            message = "WhatsApp Web reported a local browser message database error; collector is paused."
        await report_health(
            client,
            "whatsapp",
            "degraded",
            {
                **login_state,
                "line_count": len(lines),
                "message": message,
            },
        )
        return
    await inject_whatsapp_observer(page)
    observer_records = await drain_whatsapp_observer_records(page)
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
    chat_list_lines = await whatsapp_region_lines(page, "#pane-side")
    open_chat_lines = await whatsapp_region_lines(page, "#main")
    chat_context = await extract_whatsapp_chat_context_from_page(page, lines)
    visible_messages = normalize_whatsapp_visible_message_records(
        await read_whatsapp_visible_message_records(page),
        chat_context=chat_context,
    )
    visible_message_texts = {
        str(message.get("message") or "").strip()
        for message in visible_messages
        if str(message.get("message") or "").strip()
    }
    observer_messages = [
        message
        for message in normalize_whatsapp_observer_records(observer_records, chat_context=chat_context)
        if str(message.get("message") or "").strip() not in visible_message_texts
    ]
    emitted_message_texts = set(visible_message_texts)
    for message in [*observer_messages, *visible_messages]:
        message_text = str(message.get("message") or "").strip()
        if message_text:
            emitted_message_texts.add(message_text)
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
    if chat_name and open_chat_lines and not visible_messages:
        transcript_messages = split_whatsapp_open_chat_transcript(
            open_chat_lines,
            captured_at=datetime.now(timezone.utc).isoformat(),
            chat_context=chat_context,
            capture_scope="history_scroll_sync",
            limit=120,
        )
        for message in transcript_messages:
            message_text = str(message.get("message") or "").strip()
            if message_text:
                emitted_message_texts.add(message_text)
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
    if WHATSAPP_HISTORY_SYNC and chat_name:
        await inject_whatsapp_history_sync(page)
        history_records = normalize_whatsapp_history_records(await drain_whatsapp_history_records(page), chat_context=chat_context)
        for message in history_records:
            message_text = str(message.get("message") or "").strip()
            if message_text in emitted_message_texts:
                continue
            if message_text:
                emitted_message_texts.add(message_text)
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

    await emit_whatsapp_list_previews(
        client,
        chat_list_lines,
        page.url,
        title,
        chat_context=chat_context,
        excluded_messages=emitted_message_texts,
        structured_records=await read_whatsapp_list_preview_records(page),
    )

    if WHATSAPP_HISTORY_SYNC and not chat_name and chat_list_lines:
        auto_opened = await open_latest_whatsapp_chat_for_history(page)
        if auto_opened:
            await report_health(
                client,
                "whatsapp",
                "healthy",
                {
                    **login_state,
                    "line_count": len(lines),
                    "chat_name": None,
                    "auto_opened_latest_chat": True,
                    "message": "WhatsApp chat list was visible; opened the latest chat so the next collection pass can sync full visible history.",
                },
            )
            return

    committed_open_chat_lines = whatsapp_committed_open_chat_lines(open_chat_lines)
    if chat_name:
        await emit_event(
            client,
            "whatsapp",
            "whatsapp_open_chat_snapshot",
            {
                "chat_name": chat_name,
                "source_kind": chat_context.get("source_kind"),
                "participants": chat_context.get("participants", []),
                "visible_text": "\n".join(committed_open_chat_lines)[:6000],
                "line_count": len(committed_open_chat_lines),
                "url": page.url,
                "title": title,
            },
        )

    snapshot_lines = committed_open_chat_lines if chat_name else chat_list_lines
    await emit_event(
        client,
        "whatsapp",
        "whatsapp_snapshot",
        {
            "chat_name": chat_name,
            "source_kind": chat_context.get("source_kind"),
            "participants": chat_context.get("participants", []),
            "visible_text": "\n".join(snapshot_lines)[:4000],
            "line_count": len(snapshot_lines),
            "url": page.url,
            "title": title,
        },
    )
    await report_health(
        client,
        "whatsapp",
        "healthy",
        {**login_state, "line_count": len(lines), "chat_name": chat_name},
    )


def runtime_injection_plan(source: Optional[str]) -> list[dict[str, str]]:
    if source == "whatsapp":
        return [{"hook": "whatsapp_dom", "queue": "__parWhatsAppNewMessages"}]
    plan = [
        {"hook": "network", "queue": "__parRuntimeQueues.network"},
        {"hook": "focus", "queue": "__parFocusSignals"},
    ]
    return plan


def should_inject_runtime_hooks(source: Optional[str], url: str, title: str, lines: list[str]) -> bool:
    if not source or source == "focus":
        return False
    if source == "linkedin":
        return False
    if source == "whatsapp":
        return False
    return True


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
    if not chat_name:
        for index, line in enumerate(lines):
            if index == 0 or line not in {"今天", "昨天"}:
                continue
            candidate = str(lines[index - 1] or "").strip()
            if (
                not candidate
                or len(candidate) > 80
                or candidate.isdigit()
                or is_whatsapp_ui_noise_line(candidate)
                or is_whatsapp_timestamp_label(candidate)
            ):
                continue
            lookahead = [str(item or "").strip() for item in lines[index + 1 : index + 8]]
            has_open_chat_marker = any(is_whatsapp_ui_noise_line(item) for item in lookahead) or any(
                is_whatsapp_message_time_label(item) for item in lookahead
            )
            if has_open_chat_marker:
                chat_name = candidate
                break
    source_kind = "group" if len(participants) >= 2 else "direct"
    return {
        "chat_name": chat_name,
        "source_kind": source_kind,
        "participants": participants,
    }


async def whatsapp_region_lines(page, selector: str) -> list[str]:
    try:
        text = await page.locator(selector).inner_text(timeout=2500)
    except Exception:
        return []
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


async def extract_whatsapp_chat_context_from_page(page, body_lines: list[str]) -> dict[str, object]:
    context = extract_whatsapp_chat_context(body_lines)
    title_lines = await whatsapp_region_lines(
        page,
        '#main header [data-testid="conversation-info-header-chat-title"]',
    )
    if title_lines:
        participants = context.get("participants", [])
        return {
            "chat_name": title_lines[0][:80],
            "source_kind": "group" if isinstance(participants, list) and len(participants) >= 2 else "direct",
            "participants": participants if isinstance(participants, list) else [],
        }
    if context.get("chat_name"):
        return context
    header_lines = await whatsapp_region_lines(page, "#main header")
    ignored_prefixes = (
        "last seen",
        "online",
        "typing",
        "click here for contact info",
        "点击此处查看联系人信息",
    )
    for candidate in header_lines:
        normalized = candidate.casefold()
        if (
            not candidate
            or len(candidate) > 80
            or candidate.isdigit()
            or is_whatsapp_ui_noise_line(candidate)
            or is_whatsapp_timestamp_label(candidate)
            or normalized.startswith(ignored_prefixes)
        ):
            continue
        return {
            "chat_name": candidate,
            "source_kind": "direct",
            "participants": [],
        }
    return context


def whatsapp_committed_open_chat_lines(lines: list[str]) -> list[str]:
    last_timestamp_index = -1
    for index, line in enumerate(lines):
        if is_whatsapp_message_time_label(line):
            last_timestamp_index = index
    if last_timestamp_index < 0:
        return []
    return lines[: last_timestamp_index + 1]


async def emit_whatsapp_list_previews(
    client: httpx.AsyncClient,
    lines: list[str],
    url: str,
    title: str,
    chat_context: Optional[dict[str, object]] = None,
    excluded_messages: Optional[set[str]] = None,
    structured_records: Optional[list[dict[str, str]]] = None,
) -> None:
    if is_probable_whatsapp_open_chat_transcript(lines):
        return
    excluded = WHATSAPP_UI_LINES
    excluded_messages = excluded_messages or set()
    chat_context = chat_context or {}
    active_chat_name = str(chat_context.get("chat_name") or "").strip()
    if structured_records:
        for preview in normalize_whatsapp_list_preview_records(structured_records):
            message = str(preview.get("message") or "").strip()
            if preview.get("chat_name") == active_chat_name or message in excluded_messages:
                continue
            await emit_event(
                client,
                "whatsapp",
                "whatsapp_message",
                {
                    **preview,
                    "url": url,
                    "title": title,
                },
            )
        return
    for index, line in enumerate(lines):
        if line in excluded or len(line) > 40:
            continue
        if active_chat_name and line == active_chat_name:
            continue
        if index + 2 >= len(lines):
            continue
        timestamp_label = lines[index + 1]
        message = lines[index + 2]
        if timestamp_label in excluded or message in excluded:
            continue
        if message.strip() in excluded_messages:
            continue
        if not is_whatsapp_timestamp_label(timestamp_label):
            continue
        if re.fullmatch(r"\d+", message):
            continue
        await emit_event(
            client,
            "whatsapp",
            "whatsapp_message",
            {
                "sender": line,
                "chat_name": line,
                "source_kind": "direct",
                "message_direction": "unknown",
                "message": message,
                "timestamp_label": timestamp_label,
                "capture_scope": "chat_list_preview",
                "url": url,
                "title": title,
            },
        )


def is_whatsapp_timestamp_label(label: str) -> bool:
    clean = (label or "").strip()
    if not clean:
        return False
    if clean in WHATSAPP_RELATIVE_TIME_LABELS:
        return True
    if re.fullmatch(r"\d{1,2}:\d{2}(?:\s?(?:AM|PM|am|pm))?", clean):
        return True
    if re.fullmatch(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?", clean):
        return True
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", clean):
        return True
    if re.fullmatch(r"\d{1,2}月\d{1,2}日", clean):
        return True
    return False


def is_whatsapp_message_time_label(label: str) -> bool:
    clean = (label or "").strip()
    return bool(re.fullmatch(r"\d{1,2}:\d{2}(?:\s?(?:AM|PM|am|pm))?", clean))


def is_whatsapp_ui_noise_line(line: str) -> bool:
    clean = (line or "").strip()
    if not clean:
        return True
    if clean in WHATSAPP_UI_LINES:
        return True
    return any(
        clean.startswith(prefix)
        for prefix in [
            "消息和通话已进行端到端加密",
            "Messages and calls are end-to-end encrypted",
            "只有此聊天中的成员可以查看",
        ]
    )


def is_probable_whatsapp_open_chat_transcript(lines: list[str]) -> bool:
    if any(is_whatsapp_ui_noise_line(line) and line in {"输入消息", "Type a message"} for line in lines):
        return True
    message_time_count = sum(1 for line in lines if is_whatsapp_message_time_label(line))
    has_encryption_notice = any(str(line).startswith("消息和通话已进行端到端加密") for line in lines)
    return has_encryption_notice and message_time_count >= 2


def infer_whatsapp_transcript_sender(lines: list[str], chat_context: dict[str, object]) -> str:
    chat_name = str(chat_context.get("chat_name") or "").strip()
    if chat_name:
        return chat_name[:80]
    for line in lines[:6]:
        clean = str(line or "").strip()
        if clean and len(clean) <= 80 and not is_whatsapp_ui_noise_line(clean) and not is_whatsapp_timestamp_label(clean):
            return clean[:80]
    return "unknown"


def whatsapp_open_chat_message_start_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if str(line or "").strip().startswith(("消息和通话已进行端到端加密", "Messages and calls are end-to-end encrypted")):
            return index + 1
    for index, line in enumerate(lines):
        if str(line or "").strip() in {"今天", "昨天", "Today", "Yesterday"}:
            return index + 1
    return 0


def split_whatsapp_open_chat_transcript(
    lines: list[str],
    *,
    captured_at: str,
    chat_context: dict[str, object],
    capture_scope: str,
    limit: int,
) -> list[dict[str, object]]:
    sender = infer_whatsapp_transcript_sender(lines, chat_context)
    messages: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    start_index = whatsapp_open_chat_message_start_index(lines)
    for index, line in enumerate(lines[start_index:], start=start_index):
        timestamp_label = str(line or "").strip()
        if not is_whatsapp_message_time_label(timestamp_label) or index == 0:
            continue
        message = str(lines[index - 1] or "").strip()
        if (
            not message
            or len(message) > 1500
            or is_whatsapp_ui_noise_line(message)
            or is_whatsapp_timestamp_label(message)
        ):
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
                "message_direction": "unknown",
                "timestamp_label": timestamp_label,
                "message": message,
                "captured_at": captured_at,
                "capture_scope": capture_scope,
            }
        )
        if len(messages) >= limit:
            break
    return messages


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


def build_whatsapp_visible_message_script(max_records: int = 120) -> str:
    script = r"""
    (() => {
      const containers = Array.from(
        document.querySelectorAll('#main [data-testid="msg-container"]')
      ).slice(-__MAX_RECORDS__);
      return containers.map((container) => {
        const copyable = container.querySelector('[data-pre-plain-text]');
        const fallbackTextNodes = Array.from(
          container.querySelectorAll('[data-testid="selectable-text"]')
        ).filter((node) => !node.parentElement?.closest('[data-testid="selectable-text"]'));
        const message = copyable
          ? (copyable.innerText || '').trim()
          : fallbackTextNodes
              .map((node) => (node.innerText || '').trim())
              .filter(Boolean)
              .join('\n')
              .trim();
        const prePlainText = copyable
          ? (copyable.getAttribute('data-pre-plain-text') || '')
          : '';
        const metaText = (
          (container.querySelector('[data-testid="msg-meta"]') || {}).innerText || ''
        ).trim();
        const preTime = prePlainText.match(/^\[(\d{1,2}:\d{2})/);
        const metaTime = metaText.match(/\b(\d{1,2}:\d{2})\b/);
        const afterBracket = prePlainText.includes(']')
          ? prePlainText.slice(prePlainText.indexOf(']') + 1).trim()
          : '';
        const senderDelimiter = afterBracket.lastIndexOf(':');
        const sender = senderDelimiter >= 0
          ? afterBracket.slice(0, senderDelimiter).trim()
          : '';
        const ariaLabels = Array.from(container.querySelectorAll('[aria-label]'))
          .map((node) => (node.getAttribute('aria-label') || '').trim());
        const hasOutgoingLabel = ariaLabels.some(
          (label) => /^(?:你|You)\s*[：:]?$/.test(label)
        );
        const messageDirection = container.querySelector('[data-testid="tail-out"]') || hasOutgoingLabel
          ? 'outgoing'
          : container.querySelector('[data-testid="tail-in"]')
            ? 'incoming'
            : 'unknown';
        return {
          message,
          sender,
          timestamp_label: preTime ? preTime[1] : (metaTime ? metaTime[1] : ''),
          message_direction: messageDirection
        };
      }).filter((record) => record.message && record.timestamp_label);
    })();
    """
    return script.replace("__MAX_RECORDS__", str(max(1, int(max_records))))


def build_whatsapp_list_preview_script(max_records: int = 100) -> str:
    script = r"""
    (() => {
      return Array.from(document.querySelectorAll('#pane-side [role="row"]'))
        .slice(0, __MAX_RECORDS__)
        .map((row) => {
          const chatName = (
            (row.querySelector('[data-testid="cell-frame-title"]') || {}).innerText || ''
          ).trim();
          const timestampLabel = (
            (row.querySelector('[data-testid="cell-frame-primary-detail"]') || {}).innerText || ''
          ).trim();
          const secondary = row.querySelector('[data-testid="cell-frame-secondary"]');
          const outgoingStatus = row.querySelector('[data-testid="last-msg-status"]');
          const message = (
            (outgoingStatus || secondary || {}).innerText || ''
          ).trim();
          return {
            chat_name: chatName,
            timestamp_label: timestampLabel,
            message,
            message_direction: outgoingStatus ? 'outgoing' : 'incoming'
          };
        })
        .filter((record) => record.chat_name && record.timestamp_label && record.message);
    })();
    """
    return script.replace("__MAX_RECORDS__", str(max(1, int(max_records))))


async def read_whatsapp_visible_message_records(page, max_records: int = 120) -> list[dict[str, str]]:
    try:
        records = await page.evaluate(build_whatsapp_visible_message_script(max_records=max_records))
    except Exception:
        return []
    return records if isinstance(records, list) else []


async def read_whatsapp_list_preview_records(page, max_records: int = 100) -> list[dict[str, str]]:
    try:
        records = await page.evaluate(build_whatsapp_list_preview_script(max_records=max_records))
    except Exception:
        return []
    return records if isinstance(records, list) else []


def normalize_whatsapp_visible_message_records(
    records: list[dict[str, str]],
    *,
    chat_context: Optional[dict[str, object]] = None,
    limit: int = 120,
) -> list[dict[str, object]]:
    chat_context = chat_context or {}
    messages: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for record in records:
        message = str(record.get("message") or "").strip()
        timestamp_label = str(record.get("timestamp_label") or "").strip()
        direction = str(record.get("message_direction") or "unknown").strip().lower()
        if direction not in {"incoming", "outgoing"}:
            direction = "unknown"
        sender = str(record.get("sender") or "").strip()
        if not sender:
            sender = "self" if direction == "outgoing" else str(chat_context.get("chat_name") or "unknown").strip()
        if (
            not message
            or len(message) > 1500
            or not is_whatsapp_message_time_label(timestamp_label)
            or len(sender) > 80
        ):
            continue
        key = (sender, timestamp_label, message, direction)
        if key in seen:
            continue
        seen.add(key)
        messages.append(
            {
                "sender": sender,
                "chat_name": chat_context.get("chat_name"),
                "source_kind": chat_context.get("source_kind", "unknown"),
                "participants": chat_context.get("participants", []),
                "message_direction": direction,
                "timestamp_label": timestamp_label,
                "message": message,
                "capture_scope": "visible_dom",
            }
        )
        if len(messages) >= limit:
            break
    return messages


def normalize_whatsapp_list_preview_records(
    records: list[dict[str, str]],
    *,
    limit: int = 100,
) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for record in records:
        chat_name = str(record.get("chat_name") or "").strip()
        timestamp_label = str(record.get("timestamp_label") or "").strip()
        message = str(record.get("message") or "").strip()
        direction = str(record.get("message_direction") or "unknown").strip().lower()
        if direction not in {"incoming", "outgoing"}:
            direction = "unknown"
        if (
            not chat_name
            or len(chat_name) > 80
            or not is_whatsapp_timestamp_label(timestamp_label)
            or not message
            or len(message) > 1500
            or re.fullmatch(r"\d+", message)
        ):
            continue
        sender = "self" if direction == "outgoing" else chat_name
        key = (chat_name, timestamp_label, message, direction)
        if key in seen:
            continue
        seen.add(key)
        messages.append(
            {
                "sender": sender,
                "chat_name": chat_name,
                "source_kind": "unknown",
                "message_direction": direction,
                "message": message,
                "timestamp_label": timestamp_label,
                "capture_scope": "chat_list_preview",
            }
        )
        if len(messages) >= limit:
            break
    return messages


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


def build_whatsapp_open_latest_chat_script() -> str:
    return """
    (() => {
      const now = Date.now();
      if (window.__parLastAutoOpenedWhatsAppChatAt && now - window.__parLastAutoOpenedWhatsAppChatAt < 30000) {
        return false;
      }
      const selectors = [
        '#pane-side [role="row"]',
        '[aria-label*="Chat list"] [role="row"]',
        '[aria-label*="聊天"] [role="row"]',
        '[aria-label*="chat"] [role="row"]'
      ];
      const uiNoise = /^(所有|未读|特别关注|群组|All|Unread|Favorites|Groups|输入消息|Type a message)$/;
      for (const selector of selectors) {
        const rows = Array.from(document.querySelectorAll(selector));
        for (const row of rows) {
          const text = (row.innerText || '').trim();
          if (!text || text.length < 3 || uiNoise.test(text)) continue;
          const hasLikelyPreview = /(\d{1,2}:\d{2}|今天|昨天|周[一二三四五六日天]|星期[一二三四五六日天]|Today|Yesterday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)/.test(text);
          if (!hasLikelyPreview) continue;
          row.scrollIntoView({ block: 'center', inline: 'nearest' });
          row.click();
          window.__parLastAutoOpenedWhatsAppChatAt = now;
          return true;
        }
      }
      return false;
    })();
    """


async def open_latest_whatsapp_chat_for_history(page) -> bool:
    try:
        opened = await page.evaluate(build_whatsapp_open_latest_chat_script())
        if opened:
            await page.wait_for_timeout(1200)
        return bool(opened)
    except Exception:
        return False


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
    seen: set[tuple[str, str]] = set()
    for record in records:
        text = str(record.get("text") or "").strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        message_time_count = sum(1 for line in lines if is_whatsapp_message_time_label(line))
        if is_probable_whatsapp_open_chat_transcript(lines) or message_time_count >= 2:
            for message in split_whatsapp_open_chat_transcript(
                lines,
                captured_at=str(record.get("captured_at") or ""),
                chat_context=chat_context,
                capture_scope="mutation_observer",
                limit=max(0, limit - len(messages)),
            ):
                key = (
                    str(message.get("sender") or ""),
                    str(message.get("timestamp_label") or ""),
                    str(message.get("message") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                messages.append(message)
                if len(messages) >= limit:
                    break
            if len(messages) >= limit:
                break
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
        or re.match(r"^\d{4}年\d{1,2}月\d{1,2}日.*\d{1,2}:\d{2}(?:\s*\(.+\))?$", value)
        or re.match(r"^\d{1,2}月\d{1,2}日.*\d{1,2}:\d{2}(?:\s*\(.+\))?$", value)
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
        while subject_index >= 0:
            subject_candidate = cleaned[subject_index]
            if (
                subject_candidate in GMAIL_UI_LINES
                or GMAIL_THREAD_SUBJECT_CHROME_RE.fullmatch(subject_candidate)
            ):
                subject_index -= 1
                continue
            break
        if subject_index < 0:
            continue
        subject = cleaned[subject_index]
        if not subject or subject in GMAIL_UI_LINES or subject == "-":
            continue

        body_lines: list[str] = []
        attachments: list[str] = []
        labels: list[str] = []
        for candidate in cleaned[index + 2 :]:
            if is_probable_gmail_sender_line(candidate) or is_gmail_open_thread_time(candidate):
                break
            if candidate in {"附件", "Attachments"}:
                continue
            if not body_lines and (
                candidate in GMAIL_UI_LINES
                or candidate in GMAIL_THREAD_LEADING_BODY_UI_LINES
                or candidate.startswith("发送至 ")
                or candidate.startswith("To ")
            ):
                continue
            if body_lines and (
                candidate in GMAIL_UI_LINES
                or candidate in GMAIL_THREAD_BODY_TERMINATORS
            ):
                break
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
    english_month = (
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|"
        r"January|February|March|April|June|July|August|September|October|November|December)"
    )
    return bool(
        re.match(r"^\d{1,2}:\d{2}$", value)
        or value in {"Yesterday", "Today", "昨天", "今天"}
        or value in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
        or re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", value)
        or re.match(rf"^{english_month}\s+\d{{1,2}}(?:,\s*\d{{4}})?$", value, re.IGNORECASE)
        or re.match(r"^(?:\d{4}年)?\d{1,2}月\d{1,2}日$", value)
    )


def is_telegram_message_time_label(value: str) -> bool:
    return bool(re.match(r"^\d{1,2}:\d{2}$", str(value or "").strip()))


def is_telegram_open_chat_date_label(value: str) -> bool:
    value = str(value or "").strip()
    if not value:
        return False
    english_month = (
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|"
        r"January|February|March|April|June|July|August|September|October|November|December)"
    )
    return bool(
        value in {"Yesterday", "Today", "昨天", "今天"}
        or re.match(rf"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+{english_month}\s+\d{{1,2}}(?:,\s*\d{{4}})?$", value, re.IGNORECASE)
        or re.match(rf"^{english_month}\s+\d{{1,2}}(?:,\s*\d{{4}})?$", value, re.IGNORECASE)
        or re.match(r"^(?:\d{4}年)?\d{1,2}月\d{1,2}日$", value)
    )


def is_telegram_unread_badge(value: str) -> bool:
    return bool(re.fullmatch(r"\d+\+?", value.strip()))


def is_private_use_icon_text(value: str) -> bool:
    stripped = str(value or "").strip()
    if not stripped:
        return False
    meaningful = [char for char in stripped if not char.isspace()]
    if not meaningful:
        return False
    return all(0xE000 <= ord(char) <= 0xF8FF for char in meaningful)


def is_probable_telegram_preview_message(value: str) -> bool:
    stripped = value.strip()
    if not stripped or stripped in TELEGRAM_UI_LINES:
        return False
    if is_private_use_icon_text(stripped):
        return False
    if len(stripped) > 500:
        return False
    if is_telegram_unread_badge(stripped) or is_telegram_timestamp_label(stripped):
        return False
    if stripped.lower().startswith("last seen"):
        return False
    return True


def is_probable_telegram_chat_name(value: str) -> bool:
    if not value or value in TELEGRAM_UI_LINES:
        return False
    if is_private_use_icon_text(value):
        return False
    if str(value).lower().startswith("last seen"):
        return False
    if value.isdigit():
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
        if index + 3 < len(cleaned) and is_telegram_message_time_label(cleaned[index + 3]):
            # Open Telegram chats are rendered as message, time, message, time.
            # Do not reinterpret that body sequence as sidebar previews.
            continue
        if index >= 2 and is_telegram_unread_badge(cleaned[index - 1]):
            preview_before_badge = cleaned[index - 2]
            if is_probable_telegram_preview_message(preview_before_badge):
                message = preview_before_badge
        if not is_probable_telegram_preview_message(message):
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


def find_telegram_open_chat_name(cleaned: list[str], message_index: int) -> str:
    for index in range(message_index - 1, 0, -1):
        if str(cleaned[index]).lower().startswith("last seen"):
            candidate = cleaned[index - 1]
            if is_probable_telegram_chat_name(candidate):
                return candidate[:120]
    for index in range(message_index - 1, -1, -1):
        candidate = cleaned[index]
        if is_probable_telegram_chat_name(candidate) and not is_telegram_open_chat_date_label(candidate):
            return candidate[:120]
    return ""


def parse_telegram_open_chat_messages(lines: list[str], limit: int = 20) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    cleaned = [line.strip() for line in lines if line.strip()]
    for index, line in enumerate(cleaned):
        if index + 1 >= len(cleaned):
            continue
        if not is_probable_telegram_preview_message(line):
            continue
        if not is_telegram_message_time_label(cleaned[index + 1]):
            continue
        chat_name = find_telegram_open_chat_name(cleaned, index)
        key = (chat_name, line)
        if key in seen:
            continue
        seen.add(key)
        messages.append(
            {
                "chat_name": chat_name,
                "message": line[:500],
                "capture_scope": "telegram_open_chat_message",
            }
        )
        if len(messages) >= limit:
            break
    return messages


def build_telegram_visible_snapshot(
    *,
    lines: list[str],
    body_text: str,
    url: str,
    title: str,
    login_state: dict[str, Any],
    parsed_preview_count: int,
) -> dict[str, Any]:
    return {
        **login_state,
        "capture_scope": "telegram_visible_snapshot",
        "url": url,
        "title": title,
        "line_count": len(lines),
        "visible_text": body_text.strip()[:4000],
        "parsed_preview_count": parsed_preview_count,
    }


def linkedin_page_kind(url: str, title: str) -> str:
    lowered_url = str(url or "").lower()
    lowered_title = str(title or "").lower()
    if "/search/results/people" in lowered_url:
        return "people_search"
    if "/jobs/view/" in lowered_url:
        return "job_detail"
    if "/jobs/search" in lowered_url or lowered_title.startswith("jobs"):
        return "job_search"
    if "/in/" in lowered_url:
        return "profile"
    if "/company/" in lowered_url:
        return "company"
    if "/feed" in lowered_url or "feed" in lowered_title:
        return "feed"
    return "visible_page"


def linkedin_clean_lines(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    for line in lines:
        value = str(line or "").strip()
        if not value or value in LINKEDIN_UI_LINES:
            continue
        if value.startswith("Update to our terms and data use"):
            continue
        if value.startswith("As of November"):
            continue
        if value.startswith("Chromium didn't shut down correctly"):
            continue
        if len(value) > 1000:
            value = value[:1000]
        cleaned.append(value)
    return cleaned


def linkedin_find_first_index(lines: list[str], needles: set[str], start: int = 0) -> int:
    for index in range(max(start, 0), len(lines)):
        if lines[index] in needles:
            return index
    return -1


def linkedin_is_ui_or_noise(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return True
    exact_noise = {
        "jobs search",
        "past 24 hours",
        "remote",
        "try ai job search",
        "set alert",
        "viewed",
        "within the past 24 hours",
        "are these results helpful?",
        "expand your search",
        "jump to active job details",
        "jump to active search result",
        "show more options",
        "about the job",
        "full-time",
        "part-time",
        "contract",
        "internship",
        "responses managed off linkedin",
    }
    if lowered in {item.lower() for item in LINKEDIN_UI_LINES}:
        return True
    if lowered in exact_noise:
        return True
    if re.fullmatch(r"\d+\s+results?", lowered):
        return True
    if re.fullmatch(r"\d+\s+notifications?(?:\s+total)?", lowered):
        return True
    if re.fullmatch(r"\d+\s+(applicants?|views?)", lowered):
        return True
    if lowered.startswith("set job alert"):
        return True
    if lowered.startswith("save "):
        return True
    return False


def is_probable_linkedin_headline(value: str) -> bool:
    lowered = str(value or "").lower()
    role_markers = [
        " at ",
        "manager",
        "engineer",
        "developer",
        "designer",
        "founder",
        "director",
        "recruiter",
        "product",
        "program",
        "sales",
        "marketing",
        "consultant",
        "architect",
        "student",
        "university",
        "|",
    ]
    return bool(value and len(value) <= 220 and any(marker in lowered for marker in role_markers))


def parse_linkedin_profile_snapshot(lines: list[str], url: str, title: str) -> Optional[dict[str, object]]:
    cleaned = linkedin_clean_lines(lines)
    for index, line in enumerate(cleaned[:-1]):
        if line in {"Connections", "Grow your network", "0"}:
            continue
        headline = cleaned[index + 1]
        if not is_probable_linkedin_headline(headline):
            continue
        location = cleaned[index + 2] if index + 2 < len(cleaned) and len(cleaned[index + 2]) <= 120 else ""
        company = cleaned[index + 3] if index + 3 < len(cleaned) and len(cleaned[index + 3]) <= 180 else ""
        return {
            "profile_name": line[:160],
            "headline": headline[:240],
            "location": location[:160],
            "company": company[:220],
            "url": url,
            "title": title,
            "capture_scope": "visible_profile_snapshot",
            "text": "\n".join(cleaned[index : index + 4])[:1200],
        }
    return None


def linkedin_contact_kind(headline: str, text: str) -> str:
    value = f"{headline}\n{text}".lower()
    recruiter_markers = [
        "recruiter",
        "talent acquisition",
        "talent |",
        "recruiting",
        "recruitment",
        "headhunter",
        "human resources",
        "people partner",
        "hr ",
        " hr",
        "招聘",
        "人事",
        "猎头",
    ]
    if any(marker in value for marker in recruiter_markers):
        return "recruiter"
    hiring_manager_markers = [
        "engineering manager",
        "hiring manager",
        "director",
        "head of engineering",
        "tech lead",
        "cto",
        "founder",
        "vp engineering",
        "技术负责人",
        "团队负责人",
        "创始人",
    ]
    if any(marker in value for marker in hiring_manager_markers):
        return "hiring_manager"
    return "professional_contact"


def parse_linkedin_contact_snapshot(lines: list[str], url: str, title: str) -> Optional[dict[str, object]]:
    if linkedin_page_kind(url, title) != "profile":
        return None
    profile = parse_linkedin_profile_snapshot(lines, url, title)
    if not profile:
        return None
    cleaned = linkedin_clean_lines(lines)
    visible_text = "\n".join(cleaned[:120])[:6000]
    actions: list[str] = []
    if any(line == "Message" for line in lines):
        actions.append("draft_message")
    if any(line == "Connect" for line in lines):
        actions.append("request_connection")
    if not actions:
        actions.append("draft_message")
    name = str(profile.get("profile_name") or "").strip()
    headline = str(profile.get("headline") or "").strip()
    identifier = str(url or "").strip() or f"{name}|{headline}"
    return {
        "contact_id": f"linkedin_contact_{event_key('linkedin', 'contact', identifier)[:12]}",
        "name": name[:160],
        "headline": headline[:240],
        "company": str(profile.get("company") or "").strip()[:220],
        "location": str(profile.get("location") or "").strip()[:160],
        "contact_kind": linkedin_contact_kind(headline, visible_text),
        "channel": "linkedin",
        "profile_url": url,
        "title": title,
        "available_actions": actions,
        "capture_scope": "opened_profile_contact_snapshot",
        "text": visible_text,
    }


def parse_linkedin_career_prompt(lines: list[str], url: str, title: str) -> Optional[dict[str, object]]:
    cleaned = linkedin_clean_lines(lines)
    for index, line in enumerate(cleaned):
        lowered = line.lower()
        if "looking for a job" not in lowered and "open to work" not in lowered and "求职" not in line:
            continue
        answers: list[str] = []
        for candidate in cleaned[index + 1 : index + 6]:
            if candidate in {"Yes", "No", "是", "否", "Not now"}:
                answers.append(candidate)
        return {
            "prompt": line[:500],
            "available_answers": answers,
            "url": url,
            "title": title,
            "capture_scope": "career_intent_prompt",
            "text": "\n".join([line, *answers])[:1000],
        }
    return None


LINKEDIN_RECRUITER_LINK_KEYWORDS = {
    "recruiter",
    "talent",
    "hiring",
    "sourcer",
    "people partner",
    "hr",
    "human resources",
    "招聘",
    "猎头",
    "人才",
    "人力资源",
}


def normalize_linkedin_profile_href(value: str) -> Optional[str]:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc.lower() not in {"linkedin.com", "www.linkedin.com"}:
        return None
    path = re.sub(r"/+", "/", parsed.path or "/")
    if not re.fullmatch(r"/in/[A-Za-z0-9._%-]+/?", path):
        return None
    if not path.endswith("/"):
        path += "/"
    return f"https://www.linkedin.com{path}"


def extract_linkedin_recruiter_profile_links(anchor_candidates: list[dict[str, object]], limit: int = 3) -> list[str]:
    matches: list[str] = []
    seen: set[str] = set()
    for candidate in anchor_candidates:
        if not isinstance(candidate, dict):
            continue
        profile_url = normalize_linkedin_profile_href(str(candidate.get("href") or ""))
        if not profile_url or profile_url in seen:
            continue
        text_blob = " ".join(
            [
                str(candidate.get("text") or ""),
                str(candidate.get("aria_label") or ""),
                str(candidate.get("title") or ""),
            ]
        ).lower()
        if not any(keyword in text_blob for keyword in LINKEDIN_RECRUITER_LINK_KEYWORDS):
            continue
        seen.add(profile_url)
        matches.append(profile_url)
        if len(matches) >= limit:
            break
    return matches


async def discover_linkedin_recruiter_profile_links(page) -> list[str]:
    try:
        candidates = await page.evaluate(
            """
            (() => Array.from(document.querySelectorAll('a[href*="/in/"]')).slice(0, 120).map((anchor) => {
              const container = anchor.closest('li, section, div');
              return {
                href: anchor.href || '',
                text: ((container && container.innerText) || anchor.innerText || '').trim().slice(0, 1000),
                aria_label: anchor.getAttribute('aria-label') || '',
                title: anchor.getAttribute('title') || ''
              };
            }))();
            """
        )
    except Exception:
        return []
    return extract_linkedin_recruiter_profile_links(candidates if isinstance(candidates, list) else [])


def linkedin_contact_search_candidate_count(snapshots: list[dict[str, object]]) -> int:
    for snapshot in snapshots:
        if snapshot.get("event_type") != "linkedin_contact_search_results":
            continue
        raw_data = snapshot.get("raw_data") if isinstance(snapshot.get("raw_data"), dict) else {}
        contacts = raw_data.get("contacts")
        return len(contacts) if isinstance(contacts, list) else 0
    return 0


async def auto_open_linkedin_recruiter_profile_if_needed(client: httpx.AsyncClient, page, snapshots: list[dict[str, object]]) -> dict[str, object]:
    if any(snapshot.get("event_type") == "linkedin_contact_snapshot" for snapshot in snapshots):
        return {"status": "already_on_contact_profile"}
    title = await page.title()
    page_kind = linkedin_page_kind(page.url, title)
    if page_kind not in {"job_search", "job_detail", "people_search"}:
        return {"status": "not_applicable", "source_page_kind": page_kind}
    profile_links = await discover_linkedin_recruiter_profile_links(page)
    for profile_url in profile_links:
        if profile_url in LINKEDIN_AUTO_OPENED_PROFILES:
            continue
        LINKEDIN_AUTO_OPENED_PROFILES.add(profile_url)
        new_page = await page.context.new_page()
        await new_page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        await report_health(
            client,
            "linkedin",
            "healthy",
            {
                "auto_opened_profile_url": profile_url,
                "source_url": page.url,
                "source_page_kind": page_kind,
                "expected_event_type": "linkedin_contact_snapshot",
                "message": "Opened LinkedIn recruiter profile from visible LinkedIn page for contact sampling.",
            },
        )
        return {
            "status": "opened_profile",
            "profile_url": profile_url,
            "source_page_kind": page_kind,
            "expected_event_type": "linkedin_contact_snapshot",
        }
    candidate_count = linkedin_contact_search_candidate_count(snapshots)
    if page_kind == "people_search" and candidate_count > 0 and not profile_links:
        result = {
            "status": "blocked_no_profile_links",
            "candidate_count": candidate_count,
            "source_url": page.url,
            "source_page_kind": page_kind,
            "expected_event_type": "linkedin_contact_snapshot",
        }
        await report_health(
            client,
            "linkedin",
            "degraded",
            {
                **result,
                "message": "LinkedIn people search returned recruiter candidates, but this account/search page did not expose openable profile links.",
            },
        )
        return result
    return {
        "status": "no_matching_profile_links",
        "candidate_count": candidate_count,
        "source_page_kind": page_kind,
    }


def clean_linkedin_page_title(title: str) -> str:
    value = str(title or "").strip()
    value = re.sub(r"\s*\|\s*LinkedIn.*$", "", value).strip()
    return value


def split_linkedin_title_company(page_title: str, fallback_lines: list[str]) -> tuple[str, str]:
    cleaned_title = clean_linkedin_page_title(page_title)
    if " | " in cleaned_title:
        parts = [part.strip() for part in cleaned_title.split(" | ") if part.strip()]
        if len(parts) >= 2:
            title_candidate = " | ".join(parts[:-1]).strip()
            company_candidate = parts[-1].strip()
            if (
                is_probable_linkedin_job_title(title_candidate)
                and linkedin_is_probable_company(company_candidate)
                and not is_probable_linkedin_job_title(company_candidate)
            ):
                return title_candidate[:240], company_candidate[:240]
    if " - " in cleaned_title:
        title, company = cleaned_title.split(" - ", 1)
        return title.strip(), company.strip()
    meaningful = linkedin_clean_lines(fallback_lines)
    for index, line in enumerate(meaningful):
        if not is_probable_linkedin_job_title(line):
            continue
        company = ""
        for candidate in meaningful[index + 1 : index + 5]:
            if linkedin_is_probable_company(candidate):
                company = candidate
                break
        return line[:240], company[:240]
    title = cleaned_title if cleaned_title and not linkedin_is_ui_or_noise(cleaned_title) else ""
    company = ""
    return title[:240], company[:240]


def linkedin_location_from_lines(lines: list[str]) -> str:
    for line in linkedin_clean_lines(lines):
        if "·" in line:
            return line.split("·", 1)[0].strip()[:180]
        lowered = line.lower()
        if lowered in {"remote", "hybrid", "onsite"}:
            return line
        if any(place in line for place in ["Shanghai", "Beijing", "深圳", "上海", "北京", "Remote"]):
            return line[:180]
    return ""


def linkedin_job_id_from_url(url: str, fallback: str) -> str:
    match = re.search(r"/jobs/view/(\d+)", str(url or ""))
    if match:
        return f"linkedin_job_{match.group(1)}"
    return f"linkedin_job_{event_key('linkedin', 'job', fallback)[:12]}"


def normalize_linkedin_job_detail_url(raw_url: str, data_job_id: str = "") -> str:
    value = str(raw_url or "").strip()
    if value.startswith("/"):
        value = f"https://www.linkedin.com{value}"
    parsed = urlparse(value)
    match = re.search(r"/jobs/view/(\d+)", parsed.path or "")
    if match:
        return f"https://www.linkedin.com/jobs/view/{match.group(1)}/"
    query_job_id = (parse_qs(parsed.query).get("currentJobId") or [""])[0]
    job_id = str(data_job_id or query_job_id or "").strip()
    if re.fullmatch(r"\d+", job_id):
        return f"https://www.linkedin.com/jobs/view/{job_id}/"
    return value


def normalized_match_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def linkedin_job_url_from_hints(title: str, company: str, hints: Optional[list[dict[str, Any]]] = None) -> str:
    if not hints:
        return ""
    title_key = normalized_match_text(title)
    company_key = normalized_match_text(company)
    if not title_key:
        return ""
    fallback: str = ""
    for hint in hints:
        if not isinstance(hint, dict):
            continue
        hint_text = normalized_match_text(
            "\n".join(
                [
                    str(hint.get("title") or ""),
                    str(hint.get("company") or ""),
                    str(hint.get("aria") or hint.get("aria_label") or ""),
                    str(hint.get("text") or ""),
                ]
            )
        )
        raw_url = str(hint.get("href") or hint.get("url") or "")
        detail_url = normalize_linkedin_job_detail_url(raw_url, str(hint.get("dataJobId") or hint.get("data_job_id") or ""))
        if not detail_url:
            continue
        if title_key in hint_text and (not company_key or company_key in hint_text):
            return detail_url
        if not fallback and title_key in hint_text:
            fallback = detail_url
    return fallback


def linkedin_is_probable_location(value: str) -> bool:
    text = str(value or "").strip()
    if not text or len(text) > 220 or linkedin_is_ui_or_noise(text):
        return False
    lowered = text.lower()
    location_markers = [
        "remote",
        "hybrid",
        "on-site",
        "onsite",
        "china",
        "united states",
        "singapore",
        "hong kong",
        "apac",
        "emea",
        "beijing",
        "shanghai",
        "shenzhen",
        "guangdong",
        "tokyo",
        "london",
        "new york",
        "san francisco",
        "北京",
        "上海",
        "深圳",
        "广州",
        "杭州",
        "成都",
    ]
    if "·" in text:
        return True
    if any(marker in lowered or marker in text for marker in location_markers):
        return True
    return bool(re.search(r"\([^)]+(?:Remote|Hybrid|On-site|Onsite)[^)]*\)", text, re.I))


def linkedin_is_probable_company(value: str) -> bool:
    text = str(value or "").strip()
    if not text or len(text) > 160 or linkedin_is_ui_or_noise(text):
        return False
    lowered = text.lower()
    if "results" in lowered or "applicant" in lowered or "hours ago" in lowered or "days ago" in lowered:
        return False
    if linkedin_is_probable_location(text):
        return False
    return True


def parse_linkedin_job_description_snapshot(url: str, title: str, lines: list[str]) -> Optional[dict[str, object]]:
    cleaned = linkedin_clean_lines(lines)
    if not cleaned:
        return None
    page_kind = linkedin_page_kind(url, title)
    if page_kind == "job_detail":
        job_title, company = split_linkedin_title_company(title, cleaned)
        location = linkedin_location_from_lines(cleaned)
        detail_start = 0
    elif page_kind == "job_search" and "About the job" in lines:
        about_index = linkedin_find_first_index(cleaned, {"About the job"})
        if about_index < 0:
            return None
        detail_start = max(0, about_index - 8)
        detail_prefix = cleaned[detail_start:about_index]
        job_title = ""
        company = ""
        location = ""
        for index, line in enumerate(detail_prefix):
            if not is_probable_linkedin_job_title(line):
                continue
            next_line = detail_prefix[index + 1] if index + 1 < len(detail_prefix) else ""
            if linkedin_is_probable_location(next_line):
                job_title = line
                location = next_line.split("·", 1)[0].strip()
                break
        if job_title:
            for index, line in enumerate(cleaned):
                if line != job_title:
                    continue
                candidate_company = cleaned[index + 1] if index + 1 < len(cleaned) else ""
                candidate_location = cleaned[index + 2] if index + 2 < len(cleaned) else ""
                if linkedin_is_probable_company(candidate_company) and linkedin_is_probable_location(candidate_location):
                    company = candidate_company
                    break
        if not job_title:
            return None
    else:
        return None
    text = "\n".join(cleaned[detail_start : detail_start + 140])[:8000]
    job_page = {
        "job_id": linkedin_job_id_from_url(url, job_title + company),
        "source": "linkedin_browser_observation",
        "title": job_title,
        "company": company,
        "location": location,
        "url": url,
        "text": text,
        "source_event_ids": [],
    }
    return {
        "job_pages": [job_page],
        "url": url,
        "title": title,
        "capture_scope": "opened_job_description",
        "text": text,
    }


def is_probable_linkedin_job_title(value: str) -> bool:
    lowered = str(value or "").lower()
    if len(value) < 3 or len(value) > 180:
        return False
    if linkedin_is_ui_or_noise(value):
        return False
    if lowered.endswith(" jobs") or " jobs in " in lowered:
        return False
    if lowered.startswith("ai product manager in "):
        return False
    markers = ["manager", "engineer", "designer", "developer", "product", "sales", "marketing", "analyst", "director", "intern", "产品", "工程师", "经理", "运营"]
    return any(marker in lowered or marker in value for marker in markers)


def linkedin_job_result_slices(cleaned: list[str]) -> list[list[str]]:
    slices: list[list[str]] = []
    result_start = linkedin_find_first_index(cleaned, {"Jump to active search result"})
    if result_start >= 0:
        start = result_start + 1
        end = linkedin_find_first_index(cleaned, {"Are these results helpful?", "Expand your search"}, start)
        slices.append(cleaned[start : end if end >= 0 else len(cleaned)])
    expand_start = linkedin_find_first_index(cleaned, {"Expand your search"})
    if expand_start >= 0:
        end = linkedin_find_first_index(cleaned, {"About the job"}, expand_start + 1)
        slices.append(cleaned[expand_start + 1 : end if end >= 0 else len(cleaned)])
    if not slices:
        about_index = linkedin_find_first_index(cleaned, {"About the job"})
        slices.append(cleaned[: about_index if about_index >= 0 else len(cleaned)])
    return [item for item in slices if item]


def parse_linkedin_job_search_results(
    url: str,
    title: str,
    lines: list[str],
    limit: int = 10,
    job_link_hints: Optional[list[dict[str, Any]]] = None,
) -> Optional[dict[str, object]]:
    if linkedin_page_kind(url, title) != "job_search":
        return None
    cleaned = linkedin_clean_lines(lines)
    jobs: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for result_slice in linkedin_job_result_slices(cleaned):
        index = 0
        while index < len(result_slice):
            line = result_slice[index]
            if not is_probable_linkedin_job_title(line):
                index += 1
                continue
            company = result_slice[index + 1] if index + 1 < len(result_slice) else ""
            location = result_slice[index + 2] if index + 2 < len(result_slice) else ""
            if not linkedin_is_probable_company(company) or not linkedin_is_probable_location(location):
                index += 1
                continue
            key = (line.lower(), company.lower())
            if key in seen:
                index += 1
                continue
            seen.add(key)
            job_url = linkedin_job_url_from_hints(line, company, job_link_hints) or url
            jobs.append(
                {
                    "job_id": f"linkedin_search_{event_key('linkedin', 'job_search_result', line + company + location)[:12]}",
                    "source": "linkedin_browser_observation",
                    "title": line[:220],
                    "company": company[:220],
                    "location": location[:180],
                    "url": job_url,
                    "text": "\n".join(result_slice[index : index + 8])[:2500],
                }
            )
            if len(jobs) >= limit:
                break
            index += 3
        if len(jobs) >= limit:
            break
    if not jobs:
        return None
    return {
        "job_results": jobs,
        "job_pages": jobs,
        "url": url,
        "title": title,
        "capture_scope": "visible_job_search_results",
        "text": "\n".join(cleaned[:120])[:8000],
    }


def parse_linkedin_people_search_results(url: str, title: str, lines: list[str], limit: int = 10) -> Optional[dict[str, object]]:
    if linkedin_page_kind(url, title) != "people_search":
        return None
    cleaned = linkedin_clean_lines(lines)
    contacts: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    index = 0
    while index + 2 < len(cleaned):
        name = cleaned[index]
        headline = cleaned[index + 1]
        location = cleaned[index + 2]
        company_hint = cleaned[index + 3] if index + 3 < len(cleaned) else ""
        if name == "LinkedIn Member" and is_probable_linkedin_headline(headline):
            key = (name.lower(), headline.lower(), location.lower())
            if key not in seen:
                seen.add(key)
                text = "\n".join([name, headline, location, company_hint]).strip()
                contact_kind = linkedin_contact_kind(headline, text)
                contacts.append(
                    {
                        "contact_id": f"linkedin_search_contact_{event_key('linkedin', 'people_search', text)[:12]}",
                        "name": name,
                        "is_anonymized": True,
                        "headline": headline[:240],
                        "location": location[:160],
                        "company_hint": company_hint[:240],
                        "contact_kind": contact_kind,
                        "channel": "linkedin",
                        "profile_url": "",
                        "can_open_profile": False,
                        "available_actions": ["inspect_search_result"],
                        "text": text[:1200],
                    }
                )
                if len(contacts) >= limit:
                    break
            index += 4 if company_hint.startswith(("Current:", "Past:")) else 3
            continue
        index += 1
    if not contacts:
        return None
    return {
        "contacts": contacts,
        "url": url,
        "title": title,
        "capture_scope": "visible_people_search_results",
        "profile_link_status": "links_unavailable_until_profile_href_visible",
        "text": "\n".join(cleaned[:120])[:8000],
    }


async def collect_linkedin_job_link_hints(page, limit: int = 40) -> list[dict[str, object]]:
    try:
        hints = await page.evaluate(
            """
            (limit) => {
                const nodes = Array.from(document.querySelectorAll(
                    '[data-job-id], a[href*="/jobs/view/"], a[href*="currentJobId="]'
                ));
                const results = [];
                const seen = new Set();
                for (const node of nodes) {
                    const card = node.closest('[data-job-id], li, div') || node;
                    const href = node.href || node.getAttribute('href') || '';
                    const dataJobId = node.getAttribute('data-job-id') || card.getAttribute('data-job-id') || '';
                    const textLines = (card.innerText || node.innerText || '')
                        .split('\\n')
                        .map((line) => line.trim())
                        .filter(Boolean)
                        .slice(0, 10);
                    const title = textLines[0] || node.getAttribute('aria-label') || '';
                    const company = textLines[1] || '';
                    const key = `${href}|${dataJobId}|${title}|${company}`;
                    if ((!href && !dataJobId) || seen.has(key)) continue;
                    seen.add(key);
                    results.push({
                        href,
                        dataJobId,
                        title,
                        company,
                        aria: node.getAttribute('aria-label') || '',
                        text: textLines.join('\\n'),
                    });
                    if (results.length >= limit) break;
                }
                return results;
            }
            """,
            limit,
        )
    except Exception:
        return []
    if not isinstance(hints, list):
        return []
    return [hint for hint in hints if isinstance(hint, dict)]


def parse_linkedin_visible_page(
    url: str,
    title: str,
    lines: list[str],
    job_link_hints: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, object]]:
    cleaned = linkedin_clean_lines(lines)
    if not cleaned:
        return []
    page_kind = linkedin_page_kind(url, title)
    snapshots: list[dict[str, object]] = [
        {
            "event_type": "linkedin_visible_snapshot",
            "raw_data": {
                "url": url,
                "title": title,
                "page_kind": page_kind,
                "line_count": len(lines),
                "meaningful_line_count": len(cleaned),
                "visible_text": "\n".join(cleaned[:160])[:8000],
                "text": "\n".join(cleaned[:80])[:4000],
                "capture_scope": "visible_page_snapshot",
            },
        }
    ]

    profile = parse_linkedin_profile_snapshot(lines, url, title)
    if profile:
        snapshots.append({"event_type": "linkedin_profile_snapshot", "raw_data": profile})

    contact = parse_linkedin_contact_snapshot(lines, url, title)
    if contact:
        snapshots.append({"event_type": "linkedin_contact_snapshot", "raw_data": contact})

    career_prompt = parse_linkedin_career_prompt(lines, url, title)
    if career_prompt:
        snapshots.append({"event_type": "linkedin_career_prompt", "raw_data": career_prompt})

    job_detail = parse_linkedin_job_description_snapshot(url, title, lines)
    if job_detail:
        snapshots.append({"event_type": "linkedin_job_description_snapshot", "raw_data": job_detail})

    job_search = parse_linkedin_job_search_results(url, title, lines, job_link_hints=job_link_hints)
    if job_search:
        snapshots.append({"event_type": "linkedin_job_search_results", "raw_data": job_search})

    people_search = parse_linkedin_people_search_results(url, title, lines)
    if people_search:
        snapshots.append({"event_type": "linkedin_contact_search_results", "raw_data": people_search})

    return snapshots


async def collect_linkedin(client: httpx.AsyncClient, page) -> None:
    if "linkedin.com" not in page.url:
        return
    body_text = await page.locator("body").inner_text(timeout=10000)
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    title = await page.title()
    login_state = detect_browser_login_state("linkedin", page.url, title, lines)
    if login_state.get("login_state") == "logged_out":
        await report_health(
            client,
            "linkedin",
            "degraded",
            {
                **login_state,
                "line_count": len(lines),
                "message": "LinkedIn is waiting for user login.",
            },
        )
        return
    if len(body_text.strip()) < 40:
        await report_health(
            client,
            "linkedin",
            "degraded",
            {
                **build_degraded_details("linkedin", "too_little_visible_text", lines, url=page.url, title=title, min_lines=8),
                **login_state,
            },
        )
        return

    job_link_hints: list[dict[str, Any]] = []
    if linkedin_page_kind(page.url, title) == "job_search":
        job_link_hints = await collect_linkedin_job_link_hints(page)
    snapshots = parse_linkedin_visible_page(page.url, title, lines, job_link_hints=job_link_hints)
    for snapshot in snapshots:
        event_type = str(snapshot.get("event_type") or "")
        raw_data = snapshot.get("raw_data") if isinstance(snapshot.get("raw_data"), dict) else {}
        if event_type and raw_data:
            await emit_event(client, "linkedin", event_type, raw_data)
    auto_open_result = await auto_open_linkedin_recruiter_profile_if_needed(client, page, snapshots)

    if snapshots:
        final_status = "degraded" if str(auto_open_result.get("status") or "").startswith("blocked_") else "healthy"
        await report_health(
            client,
            "linkedin",
            final_status,
            {
                "url": page.url,
                "title": title,
                "login_state": login_state.get("login_state", "unknown"),
                "confidence": login_state.get("confidence", 0.0),
                "page_kind": linkedin_page_kind(page.url, title),
                "line_count": len(lines),
                "snapshot_count": len(snapshots),
                "event_types": [str(item.get("event_type") or "") for item in snapshots],
                "auto_open_result": auto_open_result,
            },
        )
    else:
        await report_health(
            client,
            "linkedin",
            "degraded",
            build_degraded_details(
                "linkedin",
                "no_linkedin_snapshot_match",
                lines,
                url=page.url,
                title=title,
                min_lines=8,
                matched_count=0,
            )
            | login_state,
        )


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
    login_state = detect_browser_login_state("telegram", page.url, title, lines)
    if login_state.get("login_state") == "logged_out":
        await report_health(
            client,
            "telegram",
            "degraded",
            {
                **login_state,
                "line_count": len(lines),
                "message": "Telegram Web is waiting for user login.",
            },
        )
        return
    if len(body_text.strip()) < 40:
        await report_health(
            client,
            "telegram",
            "degraded",
            {
                **build_degraded_details("telegram", "too_little_visible_text", lines, url=page.url, title=title, min_lines=8),
                **login_state,
            },
        )
        return

    chats = parse_telegram_visible_chats(lines)
    open_chat_messages = parse_telegram_open_chat_messages(lines)
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
    visible_keys = {(chat.get("chat_name", ""), chat.get("message", "")) for chat in chats}
    for message in open_chat_messages:
        if (message.get("chat_name", ""), message.get("message", "")) in visible_keys:
            continue
        await emit_event(
            client,
            "telegram",
            "telegram_message_preview",
            {
                **message,
                "url": page.url,
                "title": title,
            },
        )

    if chats or open_chat_messages:
        latest = chats[0] if chats else open_chat_messages[0]
        await report_health(
            client,
            "telegram",
            "healthy",
            {
                **login_state,
                "preview_count": len(chats),
                "open_chat_message_count": len(open_chat_messages),
                "latest_chat": latest.get("chat_name", ""),
            },
        )
    else:
        snapshot = build_telegram_visible_snapshot(
            lines=lines,
            body_text=body_text,
            url=page.url,
            title=title,
            login_state=login_state,
            parsed_preview_count=0,
        )
        await emit_event(client, "telegram", "telegram_visible_snapshot", snapshot)
        await report_health(
            client,
            "telegram",
            "healthy",
            {
                **login_state,
                "preview_count": 0,
                "snapshot_collected": True,
                "line_count": len(lines),
                "message": "Telegram visible snapshot collected; no structured chat preview matched.",
            },
        )


async def collect_gmail(client: httpx.AsyncClient, page) -> None:
    if source_for_page_url(page.url) != "gmail":
        return
    body_text = await page.locator("body").inner_text(timeout=8000)
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    title = await page.title()
    login_state = detect_browser_login_state("gmail", page.url, title, lines)
    if login_state.get("login_state") == "logged_out":
        await report_health(
            client,
            "gmail",
            "degraded",
            {
                **login_state,
                "line_count": len(lines),
                "message": "Gmail browser session is waiting for Google login.",
            },
        )
        return
    if len(body_text.strip()) < 80:
        await report_health(
            client,
            "gmail",
            "degraded",
            {
                **build_degraded_details("gmail", "too_little_visible_text", lines, url=page.url, title=title, min_lines=12),
                **login_state,
            },
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
    elif open_thread:
        await report_health(
            client,
            "gmail",
            "healthy",
            {
                "preview_count": 0,
                "thread_snapshot": True,
                "latest_subject": open_thread["subject"],
            },
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
    if source_for_page_url(page.url) != "calendar":
        return
    body_text = await page.locator("body").inner_text(timeout=8000)
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    title = await page.title()
    login_state = detect_browser_login_state("calendar", page.url, title, lines)
    if login_state.get("login_state") == "logged_out":
        await report_health(
            client,
            "calendar",
            "degraded",
            {
                **login_state,
                "line_count": len(lines),
                "message": "Google Calendar browser session is waiting for Google login.",
            },
        )
        return
    if len(body_text.strip()) < 40:
        await report_health(
            client,
            "calendar",
            "degraded",
            {
                **build_degraded_details("calendar", "too_little_visible_text", lines, url=page.url, title=title, min_lines=8),
                **login_state,
            },
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
    if source_for_page_url(page.url) in FOCUS_COLLECTION_EXCLUDED_SOURCES:
        return
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
        await safe_report_health(
            client,
            collector,
            "degraded",
            {
                "runtime": "fallback",
                "message": message,
            },
        )

    while True:
        await safe_report_health(client, "runtime", "degraded", {"message": message})
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
