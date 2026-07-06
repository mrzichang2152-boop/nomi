import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_build_network_hook_script_installs_fetch_xhr_and_websocket_hooks():
    from app.runtime import build_network_hook_script

    script = build_network_hook_script()

    assert "__parRuntimeQueues" in script
    assert "__parNetworkHookInstalled" in script
    assert "window.fetch" in script
    assert "XMLHttpRequest.prototype.open" in script
    assert "window.WebSocket" in script
    assert "network" in script
    assert "websocket" in script


def test_runtime_injection_plan_keeps_whatsapp_low_disturbance():
    from app.runtime import runtime_injection_plan

    whatsapp_plan = runtime_injection_plan("whatsapp")
    gmail_plan = runtime_injection_plan("gmail")

    assert [item["hook"] for item in whatsapp_plan] == ["whatsapp_dom"]
    assert [item["hook"] for item in gmail_plan] == ["network", "focus"]


def test_should_not_inject_runtime_hooks_into_any_whatsapp_page():
    from app.runtime import should_inject_runtime_hooks

    logged_out_lines = [
        "无法关联设备。在你的设备连接时，请确保你手机上的 WhatsApp 保持打开状态。",
        "扫描登录",
        "使用电话号码登录",
        "在此浏览器上保持登录状态",
    ]
    logged_in_lines = [
        "WhatsApp",
        "搜索或开始新聊天",
        "陈子扬",
        "昨天",
        "测试",
    ]

    assert should_inject_runtime_hooks("whatsapp", "https://web.whatsapp.com/", "WhatsApp", logged_out_lines) is False
    assert should_inject_runtime_hooks("whatsapp", "https://web.whatsapp.com/", "WhatsApp", logged_in_lines) is False
    assert should_inject_runtime_hooks("telegram", "https://web.telegram.org/k/", "Telegram Web", logged_out_lines) is True


def test_whatsapp_history_sync_defaults_to_disabled_for_login_stability():
    from app.runtime import WHATSAPP_HISTORY_SYNC

    assert WHATSAPP_HISTORY_SYNC is False


def test_collect_focus_does_not_inject_into_managed_account_webapps(monkeypatch):
    import asyncio
    from app import runtime

    injected = []

    class Page:
        def __init__(self, url):
            self.url = url

        async def title(self):
            return "managed app"

    async def fake_inject_focus_observer(page):
        injected.append(page.url)

    monkeypatch.setattr(runtime, "inject_focus_observer", fake_inject_focus_observer)

    for url in [
        "https://web.whatsapp.com/",
        "https://web.telegram.org/k/",
        "https://www.linkedin.com/feed/",
        "https://mail.google.com/mail/u/0/#inbox",
        "https://calendar.google.com/calendar/u/0/r",
    ]:
        asyncio.run(runtime.collect_focus(object(), Page(url)))

    assert injected == []


def test_should_not_inject_runtime_network_hooks_into_linkedin_pages():
    from app.runtime import should_inject_runtime_hooks

    lines = [
        "Jobs search",
        "AI Agent Backend Engineer Java Go in China",
        "AI Agent开发工程师（Java方向）",
        "JD.COM",
        "Beijing, China (On-site)",
    ]

    assert (
        should_inject_runtime_hooks(
            "linkedin",
            "https://www.linkedin.com/jobs/search/?keywords=AI%20Agent%20Backend%20Engineer%20Java%20Go&location=China",
            "(19) AI Agent Backend Engineer Java Go Jobs in China | LinkedIn",
            lines,
        )
        is False
    )


def test_whatsapp_syncing_and_storage_error_pages_are_not_treated_as_collectable():
    from app.runtime import detect_browser_login_state, should_inject_runtime_hooks

    syncing_lines = [
        "WhatsApp",
        "正在加载你的对话",
        "端到端加密",
        "退出",
        "请不要关闭此窗口，你的消息正在下载中。",
    ]
    storage_error_lines = [
        "WhatsApp",
        "你的浏览器上发生了数据库错误",
        "请重新关联你的设备",
        "退出",
    ]

    syncing_state = detect_browser_login_state("whatsapp", "https://web.whatsapp.com/", "WhatsApp", syncing_lines)
    storage_state = detect_browser_login_state("whatsapp", "https://web.whatsapp.com/", "WhatsApp", storage_error_lines)

    assert syncing_state["login_state"] == "syncing"
    assert syncing_state["failure_reason"] == "message_database_syncing"
    assert storage_state["login_state"] == "storage_error"
    assert storage_state["failure_reason"] == "browser_message_database_error"
    assert should_inject_runtime_hooks("whatsapp", "https://web.whatsapp.com/", "WhatsApp", syncing_lines) is False
    assert should_inject_runtime_hooks("whatsapp", "https://web.whatsapp.com/", "WhatsApp", storage_error_lines) is False


def test_collect_whatsapp_waits_without_dom_observer_while_message_database_is_syncing(monkeypatch):
    import asyncio
    from app import runtime

    reports = []
    injected = []

    class Locator:
        async def inner_text(self, timeout=0):
            return "\n".join(
                [
                    "WhatsApp",
                    "正在加载你的对话",
                    "端到端加密",
                    "退出",
                    "请不要关闭此窗口，你的消息正在下载中。",
                ]
            )

    class Page:
        url = "https://web.whatsapp.com/"

        def locator(self, selector):
            assert selector == "body"
            return Locator()

        async def title(self):
            return "WhatsApp"

    async def fake_report_health(client, collector, status, details):
        reports.append((collector, status, details))

    async def fake_inject_whatsapp_observer(page):
        injected.append(page)

    monkeypatch.setattr(runtime, "report_health", fake_report_health)
    monkeypatch.setattr(runtime, "inject_whatsapp_observer", fake_inject_whatsapp_observer)

    asyncio.run(runtime.collect_whatsapp(object(), Page()))

    assert injected == []
    assert reports == [
        (
            "whatsapp",
            "degraded",
            {
                "login_state": "syncing",
                "confidence": 0.9,
                "url": "https://web.whatsapp.com/",
                "title": "WhatsApp",
                "failure_reason": "message_database_syncing",
                "user_action": "保持 WhatsApp 手机端和云端浏览器在线，等待消息数据库同步完成。",
                "line_count": 5,
                "message": "WhatsApp Web is syncing its local message database; collector is waiting without DOM injection.",
            },
        )
    ]


def test_normalize_network_records_keeps_metadata_and_limits_sensitive_payload():
    from app.runtime import normalize_network_records

    records = normalize_network_records(
        [
            {
                "kind": "fetch",
                "method": "POST",
                "url": "https://example.com/api/send?token=abc123secret",
                "status": 200,
                "captured_at": "2026-05-26T10:00:00+00:00",
            },
            {
                "kind": "websocket",
                "url": "wss://web.whatsapp.com/ws?auth=super-secret",
                "direction": "open",
                "captured_at": "2026-05-26T10:01:00+00:00",
            },
        ],
        source="whatsapp",
        page_url="https://web.whatsapp.com/",
        title="WhatsApp",
    )

    assert records == [
        {
            "source": "whatsapp",
            "kind": "fetch",
            "method": "POST",
            "url": "https://example.com/api/send",
            "status": 200,
            "direction": None,
            "page_url": "https://web.whatsapp.com/",
            "title": "WhatsApp",
            "captured_at": "2026-05-26T10:00:00+00:00",
            "capture_scope": "runtime_network_hook",
        },
        {
            "source": "whatsapp",
            "kind": "websocket",
            "method": None,
            "url": "wss://web.whatsapp.com/ws",
            "status": None,
            "direction": "open",
            "page_url": "https://web.whatsapp.com/",
            "title": "WhatsApp",
            "captured_at": "2026-05-26T10:01:00+00:00",
            "capture_scope": "runtime_network_hook",
        },
    ]
