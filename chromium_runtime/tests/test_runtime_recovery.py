import sys
from pathlib import Path
import asyncio

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_managed_page_targets_respect_collector_settings_and_auto_open_list():
    from app.runtime import managed_page_targets

    targets = managed_page_targets(
        {
            "gmail": {"enabled": True, "paused": False},
            "whatsapp": {"enabled": True, "paused": False},
            "calendar": {"enabled": False, "paused": False},
            "telegram": {"enabled": True, "paused": True},
            "search": {"enabled": True, "paused": False},
        },
        auto_open_sources="gmail,whatsapp,calendar,telegram,search",
    )

    assert [target["source"] for target in targets] == ["gmail", "whatsapp", "search"]
    assert targets[0]["host_fragment"] == "mail.google.com"
    assert targets[0]["url"].startswith("https://accounts.google.com/ServiceLogin?service=mail")
    assert "accounts.google.com" in targets[0]["alternate_url_fragments"]
    assert targets[1]["url"] == "https://web.whatsapp.com/"
    assert targets[2]["url"] == "https://www.google.com/"


def test_default_managed_page_targets_do_not_auto_open_heavy_login_pages(monkeypatch):
    from app import runtime

    monkeypatch.setattr(runtime, "CHROMIUM_AUTO_OPEN_SOURCES", "")
    monkeypatch.setattr(runtime, "GMAIL_AUTO_OPEN", False)

    targets = runtime.managed_page_targets(
        {
            "gmail": {"enabled": True, "paused": False},
            "whatsapp": {"enabled": True, "paused": False},
            "calendar": {"enabled": True, "paused": False},
            "telegram": {"enabled": True, "paused": False},
            "linkedin": {"enabled": True, "paused": False},
            "search": {"enabled": True, "paused": False},
        },
    )

    assert targets == []


def test_prune_pages_to_manual_login_source_closes_non_target_pages():
    from app.runtime import prune_pages_to_manual_login_source

    class Page:
        def __init__(self, url):
            self.url = url
            self.closed = False

        async def close(self):
            self.closed = True

    class Context:
        def __init__(self):
            self.pages = [
                Page("https://mail.google.com/mail/u/0/#inbox"),
                Page("https://web.telegram.org/k/#5549863173"),
                Page("https://www.linkedin.com/feed/"),
                Page("https://web.telegram.org/a/#duplicate"),
            ]

    context = Context()

    asyncio.run(prune_pages_to_manual_login_source(context, "telegram"))

    assert context.pages[0].closed is True
    assert context.pages[1].closed is False
    assert context.pages[2].closed is True
    assert context.pages[3].closed is False


def test_default_managed_page_targets_can_still_be_enabled_explicitly():
    from app.runtime import managed_page_targets

    targets = managed_page_targets(
        {
            "gmail": {"enabled": True, "paused": False},
            "whatsapp": {"enabled": True, "paused": False},
            "calendar": {"enabled": True, "paused": False},
            "telegram": {"enabled": True, "paused": False},
            "linkedin": {"enabled": True, "paused": False},
            "search": {"enabled": True, "paused": False},
        },
        auto_open_sources="gmail,whatsapp,calendar,telegram,linkedin,search",
    )

    assert [target["source"] for target in targets] == [
        "gmail",
        "whatsapp",
        "calendar",
        "telegram",
        "linkedin",
        "search",
    ]


def test_collector_cycle_reports_top_level_failures(monkeypatch):
    from app import runtime

    reports = []

    async def fake_fetch_collector_settings(client):
        raise RuntimeError("settings unavailable")

    async def fake_safe_report_health(client, collector, status, details):
        reports.append((collector, status, details))

    monkeypatch.setattr(runtime, "fetch_collector_settings", fake_fetch_collector_settings)
    monkeypatch.setattr(runtime, "safe_report_health", fake_safe_report_health)

    asyncio.run(runtime.run_collector_cycle(object(), object()))

    assert reports == [
        (
            "runtime",
            "degraded",
            {"message": "collector loop top-level error: settings unavailable"},
        )
    ]


def test_collector_cycle_reraises_closed_browser_context(monkeypatch):
    from app import runtime

    reports = []

    async def fake_fetch_collector_settings(client):
        return {}

    async def fake_ensure_managed_pages(client, context, settings):
        raise RuntimeError("BrowserContext.new_page: Target page, context or browser has been closed")

    async def fake_safe_report_health(client, collector, status, details):
        reports.append((collector, status, details))

    monkeypatch.setattr(runtime, "fetch_collector_settings", fake_fetch_collector_settings)
    monkeypatch.setattr(runtime, "ensure_managed_pages", fake_ensure_managed_pages)
    monkeypatch.setattr(runtime, "safe_report_health", fake_safe_report_health)

    with pytest.raises(RuntimeError, match="Target page, context or browser has been closed"):
        asyncio.run(runtime.run_collector_cycle(object(), object()))

    assert reports == []


def test_collector_loop_reconnects_after_closed_browser_context(monkeypatch):
    from app import runtime

    stale_context = object()
    fresh_context = object()
    cycles = []
    reconnects = []

    class StopLoop(Exception):
        pass

    async def fake_run_collector_cycle(client, context):
        cycles.append(context)
        raise RuntimeError("BrowserContext.new_page: Target page, context or browser has been closed")

    async def fake_connect_to_visible_browser(playwright):
        reconnects.append(playwright)
        return object(), fresh_context

    async def fake_safe_report_health(client, collector, status, details):
        return None

    async def fake_sleep(seconds):
        raise StopLoop()

    monkeypatch.setattr(runtime, "run_collector_cycle", fake_run_collector_cycle)
    monkeypatch.setattr(runtime, "connect_to_visible_browser", fake_connect_to_visible_browser)
    monkeypatch.setattr(runtime, "safe_report_health", fake_safe_report_health)
    monkeypatch.setattr(runtime.asyncio, "sleep", fake_sleep)

    with pytest.raises(StopLoop):
        asyncio.run(runtime.collector_loop(object(), stale_context, playwright="playwright"))

    assert cycles == [fresh_context]
    assert reconnects == ["playwright", "playwright"]


def test_collector_loop_uses_fresh_context_before_each_cycle(monkeypatch):
    from app import runtime

    stale_context = object()
    fresh_context = object()
    cycles = []
    reconnects = []

    class StopLoop(Exception):
        pass

    async def fake_run_collector_cycle(client, context):
        cycles.append(context)

    async def fake_connect_to_visible_browser(playwright):
        reconnects.append(playwright)
        return object(), fresh_context

    async def fake_sleep(seconds):
        raise StopLoop()

    monkeypatch.setattr(runtime, "run_collector_cycle", fake_run_collector_cycle)
    monkeypatch.setattr(runtime, "connect_to_visible_browser", fake_connect_to_visible_browser)
    monkeypatch.setattr(runtime.asyncio, "sleep", fake_sleep)

    with pytest.raises(StopLoop):
        asyncio.run(runtime.collector_loop(object(), stale_context, playwright="playwright"))

    assert cycles == [fresh_context]
    assert reconnects == ["playwright"]


def test_collector_loop_keeps_reconnected_browser_reference(monkeypatch):
    from app import runtime

    stale_context = object()
    fresh_context = object()
    fresh_browser = object()
    context_ref = {"context": stale_context}

    class StopLoop(Exception):
        pass

    async def fake_run_collector_cycle(client, context):
        return None

    async def fake_connect_to_visible_browser(playwright):
        return fresh_browser, fresh_context

    async def fake_sleep(seconds):
        raise StopLoop()

    monkeypatch.setattr(runtime, "run_collector_cycle", fake_run_collector_cycle)
    monkeypatch.setattr(runtime, "connect_to_visible_browser", fake_connect_to_visible_browser)
    monkeypatch.setattr(runtime.asyncio, "sleep", fake_sleep)

    with pytest.raises(StopLoop):
        asyncio.run(runtime.collector_loop(object(), context_ref, playwright="playwright"))

    assert context_ref["context"] is fresh_context
    assert context_ref["browser"] is fresh_browser


def test_collector_loop_starts_owned_playwright_when_not_provided(monkeypatch):
    from app import runtime

    stale_context = object()
    fresh_context = object()
    fresh_browser = object()
    cycles = []
    reconnects = []

    class StopLoop(Exception):
        pass

    class PlaywrightFactory:
        async def start(self):
            return "owned-playwright"

    async def fake_run_collector_cycle(client, context):
        cycles.append(context)

    async def fake_connect_to_visible_browser(playwright):
        reconnects.append(playwright)
        return fresh_browser, fresh_context

    async def fake_sleep(seconds):
        raise StopLoop()

    monkeypatch.setattr(runtime, "async_playwright", lambda: PlaywrightFactory())
    monkeypatch.setattr(runtime, "run_collector_cycle", fake_run_collector_cycle)
    monkeypatch.setattr(runtime, "connect_to_visible_browser", fake_connect_to_visible_browser)
    monkeypatch.setattr(runtime.asyncio, "sleep", fake_sleep)

    with pytest.raises(StopLoop):
        asyncio.run(runtime.collector_loop(object(), {"context": stale_context}))

    assert reconnects == ["owned-playwright"]
    assert cycles == [fresh_context]


def test_initial_collector_health_uses_safe_reports(monkeypatch):
    from app import runtime

    reports = []

    async def fake_safe_report_health(client, collector, status, details):
        reports.append((collector, status, details))

    monkeypatch.setattr(runtime, "COLLECTORS", ["gmail", "linkedin"])
    monkeypatch.setattr(runtime, "safe_report_health", fake_safe_report_health)

    asyncio.run(runtime.report_initial_collector_health(object()))

    assert reports == [
        (
            "gmail",
            "degraded",
            {
                "runtime": "playwright",
                "message": "Collector scaffold loaded. Account login and DOM adapters are next.",
            },
        ),
        (
            "linkedin",
            "degraded",
            {
                "runtime": "playwright",
                "message": "Collector scaffold loaded. Account login and DOM adapters are next.",
            },
        ),
    ]


def test_ensure_managed_pages_raises_after_reporting_closed_context(monkeypatch):
    from app import runtime

    reports = []

    class Page:
        url = "https://www.google.com/"

    class Context:
        pages = [Page()]

        async def new_page(self):
            raise RuntimeError("BrowserContext.new_page: Target page, context or browser has been closed")

    async def fake_report_health(client, collector, status, details):
        reports.append((collector, status, details))

    monkeypatch.setattr(runtime, "report_health", fake_report_health)
    monkeypatch.setattr(runtime, "CHROMIUM_AUTO_OPEN_SOURCES", "linkedin")
    monkeypatch.setattr(runtime, "GMAIL_AUTO_OPEN", False)

    with pytest.raises(RuntimeError, match="Target page, context or browser has been closed"):
        asyncio.run(
            runtime.ensure_managed_pages(
                object(),
                Context(),
                {"linkedin": {"enabled": True, "paused": False}},
            )
        )

    assert reports == [
        (
            "linkedin",
            "failed",
            {
                "recovery": "page_reopen_failed",
                "url": "https://www.linkedin.com/login",
                "host_fragment": "linkedin.com",
                "message": "BrowserContext.new_page: Target page, context or browser has been closed",
            },
        )
    ]


def test_missing_managed_page_targets_detects_closed_pages_by_host_fragment():
    from app.runtime import managed_page_targets, missing_managed_page_targets

    targets = managed_page_targets(
        {
            "gmail": {"enabled": True, "paused": False},
            "whatsapp": {"enabled": True, "paused": False},
            "calendar": {"enabled": True, "paused": False},
        },
        auto_open_sources="gmail,whatsapp,calendar",
    )

    missing = missing_managed_page_targets(
        targets,
        [
            "https://mail.google.com/mail/u/0/#inbox",
            "about:blank",
        ],
    )

    assert [target["source"] for target in missing] == ["whatsapp", "calendar"]


def test_missing_managed_page_targets_reopens_gmail_after_workspace_marketing_redirect():
    from app.runtime import managed_page_targets, missing_managed_page_targets

    targets = managed_page_targets(
        {
            "gmail": {"enabled": True, "paused": False},
            "calendar": {"enabled": True, "paused": False},
        },
        auto_open_sources="gmail,calendar",
    )

    missing = missing_managed_page_targets(
        targets,
        [
            "https://workspace.google.com/intl/en-US/gmail/#inbox",
            "https://workspace.google.com/intl/en-US/products/calendar/",
        ],
    )

    assert [target["source"] for target in missing] == ["gmail"]


def test_detects_google_gsi_blank_popup_with_self_opener():
    from app.runtime import is_google_gsi_blank_popup_state

    state = {
        "url": "https://accounts.google.com/gsi/select?client_id=abc&origin=https://www.linkedin.com",
        "ready_state": "complete",
        "window_name": "g_credential_picker",
        "opener_is_self": True,
        "body_text": "",
        "visible_content_height": 0,
    }

    assert is_google_gsi_blank_popup_state(state) is True


def test_does_not_flag_visible_google_signin_as_blank_popup():
    from app.runtime import is_google_gsi_blank_popup_state

    state = {
        "url": "https://accounts.google.com/v3/signin/identifier",
        "ready_state": "complete",
        "window_name": "",
        "opener_is_self": False,
        "body_text": "Sign in with Google Email or phone",
        "visible_content_height": 640,
    }

    assert is_google_gsi_blank_popup_state(state) is False


def test_recovers_google_gsi_blank_popup_to_linkedin_login(monkeypatch):
    from app import runtime

    reports = []

    async def fake_report_health(client, collector, status, details):
        reports.append((collector, status, details))

    class Page:
        url = "https://accounts.google.com/gsi/select?client_id=abc&origin=https://www.linkedin.com"

        def __init__(self):
            self.gotos = []
            self.brought_to_front = False

        async def evaluate(self, script):
            return {
                "url": self.url,
                "ready_state": "complete",
                "window_name": "g_credential_picker",
                "opener_is_self": True,
                "body_text": "",
                "visible_content_height": 0,
            }

        async def goto(self, url, wait_until, timeout):
            self.gotos.append((url, wait_until, timeout))
            self.url = url

        async def bring_to_front(self):
            self.brought_to_front = True

    monkeypatch.setattr(runtime, "report_health", fake_report_health)
    page = Page()

    result = asyncio.run(runtime.recover_google_gsi_blank_popup_if_needed(None, page))

    assert result is True
    assert page.gotos == [("https://www.linkedin.com/login", "domcontentloaded", 30000)]
    assert page.brought_to_front is True
    assert reports == [
        (
            "linkedin",
            "degraded",
            {
                "recovery": "google_gsi_blank_popup",
                "url": "https://accounts.google.com/gsi/select?client_id=abc&origin=https://www.linkedin.com",
                "target_url": "https://www.linkedin.com/login",
                "message": "Google sign-in popup lost its LinkedIn opener context and was restored to LinkedIn login.",
            },
        )
    ]


def test_filter_managed_targets_keeps_only_manual_login_source_during_user_login():
    from app.runtime import filter_managed_targets_for_manual_login

    targets = [
        {"source": "gmail", "url": "https://mail.google.com/mail/u/0/#inbox"},
        {"source": "telegram", "url": "https://web.telegram.org/"},
        {"source": "whatsapp", "url": "https://web.whatsapp.com/"},
    ]

    assert filter_managed_targets_for_manual_login(targets, "telegram") == [
        {"source": "telegram", "url": "https://web.telegram.org/"}
    ]
    assert filter_managed_targets_for_manual_login(targets, "") == targets


def test_browser_command_target_returns_remote_login_pages():
    from app.runtime import browser_command_target

    assert browser_command_target("gmail") == {
        "source": "gmail",
        "host_fragment": "mail.google.com",
        "url": (
            "https://accounts.google.com/ServiceLogin?service=mail"
            "&continue=https%3A%2F%2Fmail.google.com%2Fmail%2Fu%2F0%2F%23inbox"
        ),
        "alternate_url_fragments": ["accounts.google.com"],
    }
    assert browser_command_target("whatsapp") == {
        "source": "whatsapp",
        "host_fragment": "web.whatsapp.com",
        "url": "https://web.whatsapp.com/",
    }
    assert browser_command_target("telegram") == {
        "source": "telegram",
        "host_fragment": "web.telegram.org",
        "url": "https://web.telegram.org/",
    }
    assert browser_command_target("linkedin") == {
        "source": "linkedin",
        "host_fragment": "linkedin.com",
        "url": "https://www.linkedin.com/login",
    }
    assert browser_command_target("https://evil.example") is None


def test_connect_to_visible_browser_retries_cdp_until_chromium_is_ready(monkeypatch):
    from app import runtime

    monkeypatch.setattr(runtime, "CHROMIUM_CDP_URL", "http://127.0.0.1:9222")

    class Browser:
        contexts = ["context"]

    class Chromium:
        def __init__(self):
            self.calls = 0

        async def connect_over_cdp(self, url):
            self.calls += 1
            if self.calls < 3:
                raise OSError("cdp not ready")
            assert url == "http://127.0.0.1:9222"
            return Browser()

    class Playwright:
        def __init__(self):
            self.chromium = Chromium()

    playwright = Playwright()
    browser, context = asyncio.run(runtime.connect_to_visible_browser(playwright, attempts=3, delay_seconds=0))

    assert browser.contexts == ["context"]


def test_detect_browser_login_state_identifies_whatsapp_qr_login_page():
    from app.runtime import detect_browser_login_state

    result = detect_browser_login_state(
        "whatsapp",
        "https://web.whatsapp.com/",
        "WhatsApp",
        [
            "Scan to log in",
            "Link with phone number instead.",
            "Scan the QR code with your phone's camera",
        ],
    )

    assert result["login_state"] == "logged_out"
    assert result["failure_reason"] == "login_required"
    assert "扫码" in result["user_action"]


def test_detect_browser_login_state_identifies_chinese_whatsapp_login_page():
    from app.runtime import detect_browser_login_state

    result = detect_browser_login_state(
        "whatsapp",
        "https://web.whatsapp.com/",
        "WhatsApp",
        [
            "扫描登录",
            "请改用电话号码关联。",
            "使用手机摄像头扫描二维码",
            "使用电话号码登录",
            "你的私人消息已进行端到端加密",
            "电话号码",
            "开始使用",
        ],
    )

    assert result["login_state"] == "logged_out"
    assert result["failure_reason"] == "login_required"
    assert "WhatsApp" in result["user_action"]


def test_detect_browser_login_state_identifies_telegram_logged_in_chat_list():
    from app.runtime import detect_browser_login_state

    result = detect_browser_login_state(
        "telegram",
        "https://web.telegram.org/k/",
        "Telegram Web",
        ["Search", "Contacts", "陈子扬", "last seen yesterday at 09:55"],
    )

    assert result["login_state"] == "logged_in"
    assert result["confidence"] >= 0.8


def test_detect_browser_login_state_identifies_linkedin_logged_in_people_search():
    from app.runtime import detect_browser_login_state

    result = detect_browser_login_state(
        "linkedin",
        "https://www.linkedin.com/search/results/people/?keywords=Recruiter",
        "Search | LinkedIn",
        ["Home", "My Network", "Jobs", "Messaging", "Notifications", "People", "Talent Acquisition Manager"],
    )

    assert result["login_state"] == "logged_in"
    assert result["page_kind"] == "people_search"


def test_detect_browser_login_state_keeps_linkedin_jobs_logged_in_despite_sign_in_footer():
    from app.runtime import detect_browser_login_state

    result = detect_browser_login_state(
        "linkedin",
        "https://www.linkedin.com/jobs/search/?currentJobId=4378789245&keywords=Backend%20Engineer%20AI%20Agent",
        "(16) Backend Engineer AI Agent Jobs | LinkedIn",
        [
            "Home",
            "My Network",
            "Jobs",
            "Messaging",
            "Notifications",
            "Me",
            "Backend Engineer AI Agent in China",
            "31 results",
            "后端开发工程师（AI Agent系统） | Backend Engineer, AI Systems",
            "Easy Apply",
            "Sign in to view more jobs",
        ],
    )

    assert result["login_state"] == "logged_in"
    assert result["page_kind"] == "job_search"


def test_google_account_pages_are_attributed_to_requested_google_product():
    from app.runtime import source_for_page_url, detect_browser_login_state

    gmail_url = "https://accounts.google.com/v3/signin/accountchooser?service=mail&continue=https%3A%2F%2Fmail.google.com%2Fmail%2Fu%2F0%2F"
    calendar_url = "https://accounts.google.com/v3/signin/accountchooser?service=cl&continue=https%3A%2F%2Fcalendar.google.com%2Fcalendar%2Fu%2F0%2Fr"

    assert source_for_page_url(gmail_url) == "gmail"
    assert source_for_page_url(calendar_url) == "calendar"
    assert detect_browser_login_state(
        "gmail",
        gmail_url,
        "Gmail",
        ["Choose an account", "Signed out", "Use another account"],
    )["login_state"] == "logged_out"


def test_execute_browser_open_command_focuses_existing_target_page():
    from app.runtime import execute_browser_open_command

    class Page:
        def __init__(self, url):
            self.url = url
            self.brought_to_front = False
            self.gotos = []
            self.assigned_urls = []

        async def bring_to_front(self):
            self.brought_to_front = True

        async def evaluate(self, script, url):
            self.assigned_urls.append(url)
            self.url = url

        async def goto(self, url, wait_until, timeout):
            self.gotos.append((url, wait_until, timeout))
            self.url = url

    class Context:
        def __init__(self):
            self.pages = [
                Page("https://web.whatsapp.com/"),
                Page("https://www.google.com/"),
            ]
            self.created = []

        async def new_page(self):
            page = Page("about:blank")
            self.pages.append(page)
            self.created.append(page)
            return page

    context = Context()
    result = asyncio.run(
        execute_browser_open_command(
            context,
            {
                "action": "open_url",
                "source": "whatsapp",
                "url": "https://web.whatsapp.com/",
                "host_fragment": "web.whatsapp.com",
            },
        )
    )

    assert result == {
        "status": "focused",
        "source": "whatsapp",
        "url": "https://web.whatsapp.com/",
    }
    assert context.pages[0].brought_to_front is True
    assert context.created == []


def test_execute_browser_open_command_reloads_matching_target_page_for_crash_recovery():
    from app.runtime import execute_browser_open_command

    class Page:
        def __init__(self, url):
            self.url = url
            self.brought_to_front = False
            self.gotos = []
            self.assigned_urls = []

        async def bring_to_front(self):
            self.brought_to_front = True

        async def evaluate(self, script, url):
            self.assigned_urls.append(url)
            self.url = url

        async def goto(self, url, wait_until, timeout):
            self.gotos.append((url, wait_until, timeout))
            self.url = url

    class Context:
        def __init__(self):
            self.pages = [Page("https://web.whatsapp.com/")]
            self.created = []

        async def new_page(self):
            page = Page("about:blank")
            self.pages.append(page)
            self.created.append(page)
            return page

    context = Context()
    result = asyncio.run(
        execute_browser_open_command(
            context,
            {
                "action": "open_url",
                "source": "whatsapp",
                "url": "https://web.whatsapp.com/",
                "host_fragment": "web.whatsapp.com",
            },
        )
    )

    assert result == {
        "status": "focused",
        "source": "whatsapp",
        "url": "https://web.whatsapp.com/",
    }
    assert context.created == []
    assert context.pages[0].gotos == [("https://web.whatsapp.com/", "domcontentloaded", 30000)]
    assert context.pages[0].brought_to_front is True


def test_execute_browser_open_command_tolerates_whatsapp_domcontentloaded_timeout():
    from app.runtime import execute_browser_open_command

    class Page:
        def __init__(self, url):
            self.url = url
            self.brought_to_front = False
            self.gotos = []
            self.assigned_urls = []

        async def bring_to_front(self):
            self.brought_to_front = True

        async def evaluate(self, script, url):
            self.assigned_urls.append(url)
            self.url = url

        async def goto(self, url, wait_until, timeout):
            self.gotos.append((url, wait_until, timeout))
            self.url = url
            raise TimeoutError(
                'Page.goto: Timeout 30000ms exceeded. Call log: navigating to "https://web.whatsapp.com/"'
            )

    class Context:
        def __init__(self):
            self.pages = [Page("https://www.google.com/")]
            self.created = []

        async def new_page(self):
            page = Page("about:blank")
            self.pages.append(page)
            self.created.append(page)
            return page

    context = Context()
    result = asyncio.run(
        execute_browser_open_command(
            context,
            {
                "action": "open_url",
                "source": "whatsapp",
                "url": "https://web.whatsapp.com/",
                "host_fragment": "web.whatsapp.com",
            },
        )
    )

    assert result["status"] == "opened"
    assert result["source"] == "whatsapp"
    assert result["url"] == "https://web.whatsapp.com/"
    assert "Page.goto" not in result.get("message", "")
    assert context.pages[0].url == "https://www.google.com/"
    assert context.pages[0].brought_to_front is False
    assert len(context.created) == 1
    assert context.created[0].url == "https://web.whatsapp.com/"
    assert context.created[0].gotos == [("https://web.whatsapp.com/", "domcontentloaded", 30000)]
    assert context.created[0].brought_to_front is True


def test_ensure_page_open_tolerates_whatsapp_domcontentloaded_timeout():
    from app.runtime import ensure_page_open

    class Page:
        def __init__(self):
            self.url = "about:blank"
            self.gotos = []

        async def goto(self, url, wait_until, timeout):
            self.gotos.append((url, wait_until, timeout))
            self.url = url
            raise TimeoutError(
                'Page.goto: Timeout 30000ms exceeded. Call log: navigating to "https://web.whatsapp.com/"'
            )

    class Context:
        def __init__(self):
            self.pages = []
            self.created = []

        async def new_page(self):
            page = Page()
            self.pages.append(page)
            self.created.append(page)
            return page

    context = Context()
    asyncio.run(ensure_page_open(context, "web.whatsapp.com", "https://web.whatsapp.com/"))

    assert len(context.created) == 1
    assert context.created[0].url == "https://web.whatsapp.com/"
    assert context.created[0].gotos == [("https://web.whatsapp.com/", "domcontentloaded", 30000)]


def test_execute_browser_open_command_opens_exact_source_page_when_target_missing():
    from app import runtime

    class Page:
        def __init__(self, url):
            self.url = url
            self.brought_to_front = False
            self.gotos = []
            self.closed = False

        async def bring_to_front(self):
            self.brought_to_front = True

        async def goto(self, url, wait_until, timeout):
            self.gotos.append((url, wait_until, timeout))
            self.url = url

        async def close(self):
            self.closed = True

    class Context:
        def __init__(self):
            self.pages = [
                Page("https://workspace.google.com/intl/en-US/products/calendar/"),
                Page("https://web.whatsapp.com/"),
            ]
            self.created = []

        async def new_page(self):
            page = Page("about:blank")
            self.pages.append(page)
            self.created.append(page)
            return page

    context = Context()
    runtime.mark_manual_browser_focus("whatsapp", ttl_seconds=600)
    result = asyncio.run(
        runtime.execute_browser_open_command(
            context,
            {
                "action": "open_url",
                "source": "linkedin",
                "url": "https://www.linkedin.com/login",
                "host_fragment": "linkedin.com",
            },
        )
    )

    assert result == {
        "status": "opened",
        "source": "linkedin",
        "url": "https://www.linkedin.com/login",
    }
    assert len(context.created) == 1
    assert context.pages[0].closed is True
    assert context.pages[0].url == "https://workspace.google.com/intl/en-US/products/calendar/"
    assert context.pages[1].closed is True
    assert context.pages[1].url == "https://web.whatsapp.com/"
    assert context.created[0].url == "https://www.linkedin.com/login"
    assert context.created[0].gotos == [("https://www.linkedin.com/login", "domcontentloaded", 30000)]
    assert context.created[0].brought_to_front is True


def test_execute_browser_open_command_does_not_block_on_stale_page_close(monkeypatch):
    from app import runtime

    monkeypatch.setattr(runtime, "CLOSE_PAGE_TIMEOUT_SECONDS", 0.01)

    class Page:
        def __init__(self, url, close_hangs=False):
            self.url = url
            self.close_hangs = close_hangs
            self.brought_to_front = False
            self.gotos = []
            self.close_attempted = False

        async def bring_to_front(self):
            self.brought_to_front = True

        async def goto(self, url, wait_until, timeout):
            self.gotos.append((url, wait_until, timeout))
            self.url = url

        async def close(self):
            self.close_attempted = True
            if self.close_hangs:
                await asyncio.sleep(3600)

    class Context:
        def __init__(self):
            self.pages = [
                Page("https://web.telegram.org/k/", close_hangs=True),
                Page("https://web.whatsapp.com/"),
            ]
            self.created = []

        async def new_page(self):
            page = Page("about:blank")
            self.pages.append(page)
            self.created.append(page)
            return page

    context = Context()
    runtime.mark_manual_browser_focus("telegram", ttl_seconds=600)

    result = asyncio.run(
        runtime.execute_browser_open_command(
            context,
            {
                "action": "open_url",
                "source": "linkedin",
                "url": "https://www.linkedin.com/login",
                "host_fragment": "linkedin.com",
            },
        )
    )

    assert result == {
        "status": "opened",
        "source": "linkedin",
        "url": "https://www.linkedin.com/login",
    }
    assert len(context.created) == 1
    assert context.pages[0].close_attempted is True
    assert context.pages[1].close_attempted is True
    assert context.created[0].url == "https://www.linkedin.com/login"
    assert context.created[0].gotos == [("https://www.linkedin.com/login", "domcontentloaded", 30000)]
    assert context.created[0].brought_to_front is True


def test_execute_browser_open_command_navigates_current_visible_page_even_when_target_exists_elsewhere():
    from app.runtime import execute_browser_open_command

    class Page:
        def __init__(self, url):
            self.url = url
            self.brought_to_front = False
            self.gotos = []

        async def bring_to_front(self):
            self.brought_to_front = True

        async def goto(self, url, wait_until, timeout):
            self.gotos.append((url, wait_until, timeout))
            self.url = url

    class Context:
        def __init__(self):
            self.pages = [
                Page("https://accounts.google.com/v3/signin/accountchooser"),
                Page("https://web.telegram.org/a/"),
                Page("https://web.whatsapp.com/"),
            ]
            self.created = []

        async def new_page(self):
            page = Page("about:blank")
            self.pages.append(page)
            self.created.append(page)
            return page

    context = Context()
    result = asyncio.run(
        execute_browser_open_command(
            context,
            {
                "action": "open_url",
                "source": "telegram",
                "url": "https://web.telegram.org/",
                "host_fragment": "web.telegram.org",
            },
        )
    )

    assert result == {
        "status": "focused",
        "source": "telegram",
        "url": "https://web.telegram.org/",
    }
    assert context.pages[0].url == "https://accounts.google.com/v3/signin/accountchooser"
    assert context.pages[0].brought_to_front is False
    assert context.pages[1].url == "https://web.telegram.org/"
    assert context.pages[1].gotos == [("https://web.telegram.org/", "domcontentloaded", 30000)]
    assert context.pages[1].brought_to_front is True
    assert context.created == []


def test_execute_browser_open_command_closes_duplicate_target_pages_before_login():
    from app.runtime import execute_browser_open_command

    class Page:
        def __init__(self, url):
            self.url = url
            self.brought_to_front = False
            self.gotos = []
            self.closed = False

        async def bring_to_front(self):
            self.brought_to_front = True

        async def goto(self, url, wait_until, timeout):
            self.gotos.append((url, wait_until, timeout))
            self.url = url

        async def close(self):
            self.closed = True

    class Context:
        def __init__(self):
            self.pages = [
                Page("https://web.whatsapp.com/"),
                Page("https://web.telegram.org/a/"),
                Page("https://web.telegram.org/a/#duplicate"),
            ]

        async def new_page(self):
            page = Page("about:blank")
            self.pages.append(page)
            return page

    context = Context()
    result = asyncio.run(
        execute_browser_open_command(
            context,
            {
                "action": "open_url",
                "source": "telegram",
                "url": "https://web.telegram.org/",
                "host_fragment": "web.telegram.org",
            },
        )
    )

    assert result["status"] == "focused"
    assert context.pages[0].closed is True
    assert context.pages[1].closed is True
    assert context.pages[2].closed is False
    assert context.pages[2].brought_to_front is True


def test_execute_browser_open_command_opens_target_page_for_missing_target():
    from app.runtime import execute_browser_open_command

    class Page:
        def __init__(self, url):
            self.url = url
            self.brought_to_front = False
            self.gotos = []

        async def bring_to_front(self):
            self.brought_to_front = True

        async def goto(self, url, wait_until, timeout):
            self.gotos.append((url, wait_until, timeout))
            self.url = url

    class Context:
        def __init__(self):
            self.pages = [Page("https://web.whatsapp.com/")]
            self.created = []

        async def new_page(self):
            page = Page("about:blank")
            self.pages.append(page)
            self.created.append(page)
            return page

    context = Context()
    result = asyncio.run(
        execute_browser_open_command(
            context,
            {
                "action": "open_url",
                "source": "telegram",
                "url": "https://web.telegram.org/",
                "host_fragment": "web.telegram.org",
            },
        )
    )

    assert result == {
        "status": "opened",
        "source": "telegram",
        "url": "https://web.telegram.org/",
    }
    assert len(context.created) == 1
    assert context.pages[0].url == "https://web.whatsapp.com/"
    assert context.pages[0].gotos == []
    assert context.pages[0].brought_to_front is False
    assert context.created[0].url == "https://web.telegram.org/"
    assert context.created[0].gotos == [("https://web.telegram.org/", "domcontentloaded", 30000)]
    assert context.created[0].brought_to_front is True


def test_execute_browser_type_command_types_into_current_page_without_submitting():
    from app.runtime import execute_browser_command

    class Keyboard:
        def __init__(self):
            self.typed = []
            self.pressed = []

        async def type(self, text, delay=None):
            self.typed.append((text, delay))

        async def press(self, key):
            self.pressed.append(key)

    class Page:
        def __init__(self):
            self.url = "https://www.linkedin.com/login"
            self.keyboard = Keyboard()
            self.brought_to_front = False

        async def bring_to_front(self):
            self.brought_to_front = True

    class Context:
        pages = [Page()]

    context = Context()
    result = asyncio.run(
        execute_browser_command(
            context,
            {
                "action": "type_text",
                "text": "hello@example.com",
                "submit": False,
            },
        )
    )

    page = context.pages[0]
    assert result == {"status": "typed", "source": "manual", "url": page.url}
    assert page.brought_to_front is True
    assert page.keyboard.typed == [("hello@example.com", 1)]
    assert page.keyboard.pressed == []


def test_execute_browser_open_direct_command_navigates_to_restricted_linkedin_profile():
    from app.runtime import execute_browser_command

    class Page:
        def __init__(self, url):
            self.url = url
            self.brought_to_front = False
            self.gotos = []

        async def bring_to_front(self):
            self.brought_to_front = True

        async def goto(self, url, wait_until, timeout):
            self.gotos.append((url, wait_until, timeout))
            self.url = url

    class Context:
        def __init__(self):
            self.pages = [Page("https://www.linkedin.com/jobs/search/?keywords=backend")]
            self.created = []

        async def new_page(self):
            page = Page("about:blank")
            self.pages.append(page)
            self.created.append(page)
            return page

    context = Context()
    result = asyncio.run(
        execute_browser_command(
            context,
            {
                "action": "open_url_direct",
                "source": "linkedin",
                "url": "https://www.linkedin.com/in/jane-chen-recruiter/",
                "host_fragment": "linkedin.com",
            },
        )
    )

    page = context.pages[0]
    assert result == {
        "status": "navigated",
        "source": "linkedin",
        "url": "https://www.linkedin.com/in/jane-chen-recruiter/",
    }
    assert page.url == "https://www.linkedin.com/in/jane-chen-recruiter/"
    assert page.gotos == [("https://www.linkedin.com/in/jane-chen-recruiter/", "domcontentloaded", 30000)]
    assert page.brought_to_front is True
    assert context.created == []


def test_execute_browser_open_direct_command_rejects_untrusted_url():
    from app.runtime import execute_browser_command

    class Context:
        pages = []

    result = asyncio.run(
        execute_browser_command(
            Context(),
            {
                "action": "open_url_direct",
                "source": "linkedin",
                "url": "https://evil.example/in/jane-chen-recruiter/",
                "host_fragment": "linkedin.com",
            },
        )
    )

    assert result == {
        "status": "ignored",
        "source": "linkedin",
        "url": "https://evil.example/in/jane-chen-recruiter/",
        "message": "URL is not allowed for direct browser navigation.",
    }


def test_execute_browser_contact_search_command_navigates_to_restricted_people_search():
    from app.runtime import execute_browser_command

    class Page:
        def __init__(self, url):
            self.url = url
            self.brought_to_front = False
            self.gotos = []
            self.assigned_urls = []

        async def bring_to_front(self):
            self.brought_to_front = True

        async def evaluate(self, script, url):
            self.assigned_urls.append(url)
            self.url = url

        async def goto(self, url, wait_until, timeout):
            self.gotos.append((url, wait_until, timeout))
            self.url = url

    class Context:
        def __init__(self):
            self.pages = [Page("https://www.linkedin.com/jobs/search/?keywords=backend")]
            self.created = []

        async def new_page(self):
            page = Page("about:blank")
            self.pages.append(page)
            self.created.append(page)
            return page

    search_url = (
        "https://www.linkedin.com/search/results/people/"
        "?keywords=Example%20AI%20Backend%20Engineer%20recruiter"
    )
    expected_url = "https://www.linkedin.com/search/results/people/?keywords=Example+AI+Backend+Engineer+recruiter"
    context = Context()
    result = asyncio.run(
        execute_browser_command(
            context,
            {
                "action": "open_linkedin_contact_search",
                "source": "linkedin",
                "url": search_url,
                "host_fragment": "linkedin.com",
            },
        )
    )

    page = context.pages[0]
    assert result == {"status": "navigated", "source": "linkedin", "url": expected_url}
    assert page.url == expected_url
    assert page.assigned_urls == []
    assert page.gotos == [(expected_url, "commit", 8000)]
    assert page.brought_to_front is True
    assert context.created == []


def test_execute_browser_contact_search_command_rejects_untrusted_url():
    from app.runtime import execute_browser_command

    class Context:
        pages = []

    result = asyncio.run(
        execute_browser_command(
            Context(),
            {
                "action": "open_linkedin_contact_search",
                "source": "linkedin",
                "url": "https://www.linkedin.com/jobs/search/?keywords=recruiter",
                "host_fragment": "linkedin.com",
            },
        )
    )

    assert result == {
        "status": "ignored",
        "source": "linkedin",
        "url": "https://www.linkedin.com/jobs/search/?keywords=recruiter",
        "message": "URL is not allowed for LinkedIn contact search.",
    }


def test_execute_browser_job_search_command_navigates_to_restricted_jobs_search():
    from app.runtime import execute_browser_command

    class Page:
        def __init__(self, url):
            self.url = url
            self.brought_to_front = False
            self.gotos = []
            self.assigned_urls = []

        async def bring_to_front(self):
            self.brought_to_front = True

        async def evaluate(self, script, url):
            self.assigned_urls.append(url)
            self.url = url

        async def goto(self, url, wait_until, timeout):
            self.gotos.append((url, wait_until, timeout))
            self.url = url

    class Context:
        def __init__(self):
            self.pages = [Page("https://www.linkedin.com/feed/")]
            self.created = []

        async def new_page(self):
            page = Page("about:blank")
            self.pages.append(page)
            self.created.append(page)
            return page

    search_url = "https://www.linkedin.com/jobs/search/?keywords=Backend%20Engineer&location=Singapore"
    expected_url = "https://www.linkedin.com/jobs/search/?keywords=Backend+Engineer&location=Singapore"
    context = Context()
    result = asyncio.run(
        execute_browser_command(
            context,
            {
                "action": "open_linkedin_job_search",
                "source": "linkedin",
                "url": search_url,
                "host_fragment": "linkedin.com",
            },
        )
    )

    page = context.pages[0]
    assert result == {"status": "navigated", "source": "linkedin", "url": expected_url}
    assert page.url == expected_url
    assert page.assigned_urls == []
    assert page.gotos == [(expected_url, "commit", 8000)]
    assert page.brought_to_front is True
    assert context.created == []


def test_execute_browser_job_search_command_does_not_use_location_assign(monkeypatch):
    from app import runtime

    class Page:
        def __init__(self, url):
            self.url = url
            self.brought_to_front = False
            self.gotos = []
            self.assigned_urls = []

        async def bring_to_front(self):
            self.brought_to_front = True

        async def evaluate(self, script, url):
            self.assigned_urls.append(url)
            await asyncio.sleep(60)

        async def goto(self, url, wait_until, timeout):
            self.gotos.append((url, wait_until, timeout))
            self.url = url

    class Context:
        def __init__(self):
            self.pages = [Page("https://www.linkedin.com/jobs/search/?keywords=old")]

        async def new_page(self):
            raise AssertionError("existing LinkedIn page should be reused")

    search_url = "https://www.linkedin.com/jobs/search/?keywords=Backend%20Engineer&location=Remote"
    expected_url = "https://www.linkedin.com/jobs/search/?keywords=Backend+Engineer&location=Remote"
    context = Context()

    result = asyncio.run(
        asyncio.wait_for(
            runtime.execute_browser_command(
                context,
                {
                    "action": "open_linkedin_job_search",
                    "source": "linkedin",
                    "url": search_url,
                    "host_fragment": "linkedin.com",
                },
            ),
            timeout=0.5,
        )
    )

    page = context.pages[0]
    assert result == {"status": "navigated", "source": "linkedin", "url": expected_url}
    assert page.assigned_urls == []
    assert page.gotos == [(expected_url, "commit", 8000)]
    assert page.url == expected_url
    assert page.brought_to_front is True


def test_execute_browser_job_search_command_returns_when_linkedin_goto_stalls():
    from app import runtime

    class Page:
        def __init__(self, url):
            self.url = url
            self.brought_to_front = False
            self.gotos = []

        async def bring_to_front(self):
            self.brought_to_front = True

        async def goto(self, url, wait_until, timeout):
            self.gotos.append((url, wait_until, timeout))
            await asyncio.sleep(60)

    class Context:
        def __init__(self):
            self.pages = [Page("https://www.linkedin.com/jobs/view/4388714215/")]

        async def new_page(self):
            raise AssertionError("existing LinkedIn page should be reused")

    search_url = "https://www.linkedin.com/jobs/search/?keywords=Backend%20Engineer&location=China"
    expected_url = "https://www.linkedin.com/jobs/search/?keywords=Backend+Engineer&location=China"
    context = Context()

    result = asyncio.run(
        asyncio.wait_for(
            runtime.execute_browser_command(
                context,
                {
                    "action": "open_linkedin_job_search",
                    "source": "linkedin",
                    "url": search_url,
                    "host_fragment": "linkedin.com",
                },
            ),
            timeout=0.5,
        )
    )

    page = context.pages[0]
    assert result == {"status": "navigated", "source": "linkedin", "url": expected_url}
    assert page.gotos == [(expected_url, "commit", 8000)]
    assert page.brought_to_front is True


def test_execute_browser_job_search_command_rejects_untrusted_url():
    from app.runtime import execute_browser_command

    class Context:
        pages = []

    result = asyncio.run(
        execute_browser_command(
            Context(),
            {
                "action": "open_linkedin_job_search",
                "source": "linkedin",
                "url": "https://www.linkedin.com/search/results/people/?keywords=recruiter",
                "host_fragment": "linkedin.com",
            },
        )
    )

    assert result == {
        "status": "ignored",
        "source": "linkedin",
        "url": "https://www.linkedin.com/search/results/people/?keywords=recruiter",
        "message": "URL is not allowed for LinkedIn job search.",
    }


def test_execute_browser_job_detail_command_navigates_to_restricted_job_detail():
    from app.runtime import execute_browser_command

    class Page:
        def __init__(self, url):
            self.url = url
            self.brought_to_front = False
            self.gotos = []

        async def bring_to_front(self):
            self.brought_to_front = True

        async def goto(self, url, wait_until, timeout):
            self.gotos.append((url, wait_until, timeout))
            self.url = url

    class Context:
        def __init__(self):
            self.pages = [Page("https://www.linkedin.com/feed/")]

        async def new_page(self):
            raise AssertionError("existing LinkedIn page should be reused")

    context = Context()
    result = asyncio.run(
        execute_browser_command(
            context,
            {
                "action": "open_linkedin_job_detail",
                "source": "linkedin",
                "url": "https://www.linkedin.com/jobs/view/4378789245/?trackingId=abc",
                "host_fragment": "linkedin.com",
            },
        )
    )

    page = context.pages[0]
    assert result == {
        "status": "navigated",
        "source": "linkedin",
        "url": "https://www.linkedin.com/jobs/view/4378789245/",
    }
    assert page.gotos == [("https://www.linkedin.com/jobs/view/4378789245/", "domcontentloaded", 30000)]
    assert page.brought_to_front is True


def test_execute_browser_job_detail_command_rejects_untrusted_url():
    from app.runtime import execute_browser_command

    class Context:
        pages = []

    result = asyncio.run(
        execute_browser_command(
            Context(),
            {
                "action": "open_linkedin_job_detail",
                "source": "linkedin",
                "url": "https://www.linkedin.com/jobs/search/?currentJobId=4378789245",
                "host_fragment": "linkedin.com",
            },
        )
    )

    assert result == {
        "status": "ignored",
        "source": "linkedin",
        "url": "https://www.linkedin.com/jobs/search/?currentJobId=4378789245",
        "message": "URL is not allowed for LinkedIn job detail.",
    }


def test_execute_browser_type_command_can_submit_when_explicitly_requested():
    from app.runtime import execute_browser_command

    class Keyboard:
        def __init__(self):
            self.typed = []
            self.pressed = []

        async def type(self, text, delay=None):
            self.typed.append((text, delay))

        async def press(self, key):
            self.pressed.append(key)

    class Page:
        def __init__(self):
            self.url = "https://www.linkedin.com/login"
            self.keyboard = Keyboard()

        async def bring_to_front(self):
            pass

    class Context:
        pages = [Page()]

    context = Context()
    asyncio.run(
        execute_browser_command(
            context,
            {
                "action": "type_text",
                "text": "hello@example.com",
                "submit": True,
            },
        )
    )

    assert context.pages[0].keyboard.typed == [("hello@example.com", 1)]
    assert context.pages[0].keyboard.pressed == ["Enter"]


def test_execute_browser_type_command_uses_active_manual_login_page_over_stale_first_page():
    from app import runtime

    class Keyboard:
        def __init__(self):
            self.typed = []

        async def type(self, text, delay=None):
            self.typed.append((text, delay))

        async def press(self, key):
            raise AssertionError("submit should not be pressed")

    class Page:
        def __init__(self, url):
            self.url = url
            self.keyboard = Keyboard()
            self.brought_to_front = False

        async def bring_to_front(self):
            self.brought_to_front = True

    class Context:
        def __init__(self):
            self.pages = [
                Page("https://workspace.google.com/intl/en-US/products/calendar/"),
                Page("https://www.linkedin.com/login"),
            ]

    context = Context()
    runtime.mark_manual_browser_focus("linkedin", ttl_seconds=600)
    result = asyncio.run(
        runtime.execute_browser_command(
            context,
            {
                "action": "type_text",
                "text": "nomitest",
                "submit": False,
            },
        )
    )

    assert result == {"status": "typed", "source": "manual", "url": "https://www.linkedin.com/login"}
    assert context.pages[0].keyboard.typed == []
    assert context.pages[0].brought_to_front is False
    assert context.pages[1].keyboard.typed == [("nomitest", 1)]
    assert context.pages[1].brought_to_front is True


def test_execute_browser_type_command_prefers_google_oauth_page_for_linkedin_login():
    from app import runtime

    class Keyboard:
        def __init__(self):
            self.typed = []

        async def type(self, text, delay=None):
            self.typed.append((text, delay))

        async def press(self, key):
            raise AssertionError("submit should not be pressed")

    class Page:
        def __init__(self, url):
            self.url = url
            self.keyboard = Keyboard()
            self.brought_to_front = False

        async def bring_to_front(self):
            self.brought_to_front = True

    class Context:
        def __init__(self):
            self.pages = [
                Page("https://www.linkedin.com/login/"),
                Page("https://accounts.google.com/v3/signin/challenge/pwd?TL=ABCD1234&cid=1"),
            ]

    context = Context()
    runtime.mark_manual_browser_focus("linkedin", ttl_seconds=600)
    result = asyncio.run(
        runtime.execute_browser_command(
            context,
            {
                "action": "type_text",
                "text": "google-password",
                "submit": False,
            },
        )
    )

    assert result == {
        "status": "typed",
        "source": "manual",
        "url": "https://accounts.google.com/v3/signin/challenge/pwd?TL=ABCD1234&cid=1",
    }
    assert context.pages[0].keyboard.typed == []
    assert context.pages[0].brought_to_front is False
    assert context.pages[1].keyboard.typed == [("google-password", 1)]
    assert context.pages[1].brought_to_front is True


def test_execute_browser_command_with_timeout_returns_failed_status_for_stuck_navigation(monkeypatch):
    from app import runtime

    async def slow_execute(context, command):
        await asyncio.sleep(0.05)
        return {"status": "navigated", "source": "whatsapp", "url": "https://web.whatsapp.com/"}

    monkeypatch.setattr(runtime, "execute_browser_command", slow_execute)

    result = asyncio.run(
        runtime.execute_browser_command_with_timeout(
            object(),
            {
                "action": "open_url",
                "source": "whatsapp",
                "url": "https://web.whatsapp.com/",
            },
            timeout_seconds=0.001,
        )
    )

    assert result["status"] == "failed"
    assert result["source"] == "whatsapp"
    assert result["url"] == "https://web.whatsapp.com/"
    assert "timed out" in result["message"]


def test_safe_report_health_swallows_runtime_api_outage(monkeypatch):
    from app import runtime

    calls = []

    async def failing_report_health(client, collector, status, payload):
        calls.append((collector, status, payload))
        raise RuntimeError("runtime api temporarily unavailable")

    monkeypatch.setattr(runtime, "report_health", failing_report_health)

    asyncio.run(runtime.safe_report_health(object(), "runtime", "degraded", {"message": "boom"}))

    assert calls == [("runtime", "degraded", {"message": "boom"})]


def test_run_degraded_loop_uses_safe_health_reporting(monkeypatch):
    from app import runtime

    calls = []

    async def safe_report(client, collector, status, payload):
        calls.append((collector, status, payload))
        if collector == "runtime":
            raise asyncio.CancelledError()

    monkeypatch.setattr(runtime, "safe_report_health", safe_report)
    monkeypatch.setattr(runtime.asyncio, "sleep", lambda seconds: (_ for _ in ()).throw(asyncio.CancelledError()))

    try:
        asyncio.run(runtime.run_degraded_loop(object(), "startup race"))
    except asyncio.CancelledError:
        pass

    assert calls[0][0] == "search"
    assert any(call[0] == "runtime" for call in calls)
