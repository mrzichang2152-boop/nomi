import sys
from pathlib import Path


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
