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


def test_runtime_injection_plan_lists_expected_hooks_for_whatsapp_and_gmail():
    from app.runtime import runtime_injection_plan

    whatsapp_plan = runtime_injection_plan("whatsapp")
    gmail_plan = runtime_injection_plan("gmail")

    assert [item["hook"] for item in whatsapp_plan] == ["network", "focus", "whatsapp_dom"]
    assert [item["hook"] for item in gmail_plan] == ["network", "focus"]


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
