import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_parse_gmail_inbox_previews_extracts_sender_subject_snippet_and_time():
    from app.runtime import parse_gmail_inbox_previews

    lines = [
        "主要",
        "50 个新会话",
        "Google",
        "安全提醒",
        "-",
        "在 Linux 设备上有新的登录活动 mrzichang2152@gmail.com 我们发现您的 Google 账号在一部 Linux 设备上有新的登录活动。",
        "13:21",
        "customer moclaw",
        "Subject: 【MoClaw】We'd love your feedback – 15 mins, earn up to 2,000 free credits",
        "-",
        "Hi there, Hope you're doing well! You recently tried MoClaw as one of our early users.",
        "5月25日",
    ]

    previews = parse_gmail_inbox_previews(lines, limit=5)

    assert previews[0]["sender"] == "Google"
    assert previews[0]["subject"] == "安全提醒"
    assert "Linux 设备" in previews[0]["snippet"]
    assert previews[0]["timestamp_label"] == "13:21"
    assert previews[1]["sender"] == "customer moclaw"
    assert "MoClaw" in previews[1]["subject"]
    assert previews[1]["timestamp_label"] == "5月25日"


def test_parse_gmail_inbox_previews_skips_ui_lines_and_duplicate_threads():
    from app.runtime import parse_gmail_inbox_previews

    lines = [
        "写邮件",
        "收件箱",
        "703",
        "Google",
        "安全提醒",
        "-",
        "在 Linux 设备上有新的登录活动",
        "13:21",
        "Google",
        "安全提醒",
        "-",
        "在 Linux 设备上有新的登录活动",
        "13:21",
    ]

    previews = parse_gmail_inbox_previews(lines, limit=10)

    assert len(previews) == 1
    assert previews[0]["sender"] == "Google"


def test_collector_allowed_respects_disabled_and_paused_settings():
    from app.runtime import collector_allowed

    assert collector_allowed("gmail", {"gmail": {"enabled": False}}) is False
    assert collector_allowed("gmail", {"gmail": {"enabled": True, "paused": True}}) is False
    assert collector_allowed("gmail", {"gmail": {"enabled": True, "paused": False}}) is True
    assert collector_allowed("gmail", {}) is True


def test_build_degraded_details_includes_quality_selector_hints_and_dom_sample():
    from app.runtime import build_degraded_details

    details = build_degraded_details(
        "gmail",
        "no_inbox_preview_match",
        [
            "Gmail",
            "收件箱",
            "Google",
            "安全提醒",
            "页面结构疑似变化",
            "新的不可识别按钮",
        ],
        url="https://mail.google.com/mail/u/0/#inbox",
        title="Inbox - Gmail",
        min_lines=10,
        matched_count=0,
    )

    assert details["failure_reason"] == "no_inbox_preview_match"
    assert details["line_count"] == 6
    assert details["matched_count"] == 0
    assert 0 < details["quality_score"] < 1
    assert "Gmail visible text" in details["message"]
    assert "div[role='main']" in details["selector_hints"]
    assert "页面结构疑似变化" in details["dom_sample"]
    assert "收件箱" not in details["dom_sample"]
    assert details["url"] == "https://mail.google.com/mail/u/0/#inbox"
    assert details["title"] == "Inbox - Gmail"


def test_parse_gmail_open_thread_extracts_subject_sender_time_and_body():
    from app.runtime import parse_gmail_open_thread

    lines = [
        "Gmail",
        "返回",
        "安全提醒",
        "Google <no-reply@accounts.google.com>",
        "13:21 (3小时前)",
        "在 Linux 设备上有新的登录活动",
        "您好，我们发现您的 Google 账号在一部 Linux 设备上有新的登录活动。",
        "如果这是您本人操作，则无需采取任何措施。",
        "回复",
        "转发",
    ]

    thread = parse_gmail_open_thread(lines)

    assert thread == {
        "subject": "安全提醒",
        "sender": "Google <no-reply@accounts.google.com>",
        "timestamp_label": "13:21 (3小时前)",
        "body": "在 Linux 设备上有新的登录活动\n您好，我们发现您的 Google 账号在一部 Linux 设备上有新的登录活动。\n如果这是您本人操作，则无需采取任何措施。",
        "capture_scope": "open_thread_visible_body",
    }


def test_parse_gmail_open_thread_returns_none_for_inbox_preview_only():
    from app.runtime import parse_gmail_open_thread

    lines = [
        "主要",
        "Google",
        "安全提醒",
        "-",
        "在 Linux 设备上有新的登录活动",
        "13:21",
    ]

    assert parse_gmail_open_thread(lines) is None


def test_parse_gmail_open_thread_extracts_visible_attachments_and_labels():
    from app.runtime import parse_gmail_open_thread

    lines = [
        "Gmail",
        "项目资料",
        "Alice <alice@example.com>",
        "2026年5月26日 09:30",
        "这里是本周项目资料，请查看附件。",
        "附件",
        "requirements.pdf",
        "meeting-notes.docx",
        "标签: 工作 项目",
        "回复",
    ]

    thread = parse_gmail_open_thread(lines)

    assert thread["attachments"] == ["requirements.pdf", "meeting-notes.docx"]
    assert thread["labels"] == ["工作", "项目"]
    assert "这里是本周项目资料" in thread["body"]


def test_protect_gmail_payload_redacts_sensitive_body_values_and_flags_reason():
    from app.runtime import protect_gmail_payload

    protected = protect_gmail_payload(
        {
            "subject": "账户验证",
            "sender": "security@example.com",
            "timestamp_label": "09:30",
            "body": "您的验证码是 839201，请点击 https://example.com/reset?token=abc123secret 完成验证。订单号 498397 金额 199.00 元。",
            "capture_scope": "open_thread_visible_body",
        }
    )

    rendered = str(protected)
    assert protected["sensitive"] is True
    assert "verification_code" in protected["sensitive_reasons"]
    assert "secret_link" in protected["sensitive_reasons"]
    assert "order_or_payment" in protected["sensitive_reasons"]
    assert "839201" not in rendered
    assert "abc123secret" not in rendered
    assert "498397" not in rendered
    assert "199.00" not in rendered
    assert "验证码" in rendered
    assert "订单号" in rendered
