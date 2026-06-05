import sys
from pathlib import Path
import asyncio


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
    assert targets[1]["url"] == "https://web.whatsapp.com/"
    assert targets[2]["url"] == "https://www.google.com/"


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


def test_browser_command_target_returns_whatsapp_and_telegram_login_pages():
    from app.runtime import browser_command_target

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
    assert browser_command_target("https://evil.example") is None


def test_execute_browser_open_command_focuses_existing_target_page():
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
        "status": "navigated",
        "source": "telegram",
        "url": "https://web.telegram.org/",
    }
    assert context.pages[0].url == "https://web.telegram.org/"
    assert context.pages[0].brought_to_front is True
    assert context.pages[1].url == "https://web.telegram.org/a/"
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

    assert result["status"] == "navigated"
    assert context.pages[0].url == "https://web.telegram.org/"
    assert context.pages[1].closed is True
    assert context.pages[2].closed is True


def test_execute_browser_open_command_reuses_visible_page_for_missing_target():
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
        "status": "navigated",
        "source": "telegram",
        "url": "https://web.telegram.org/",
    }
    assert context.created == []
    assert context.pages[0].url == "https://web.telegram.org/"
    assert context.pages[0].gotos == [("https://web.telegram.org/", "domcontentloaded", 30000)]
    assert context.pages[0].brought_to_front is True
