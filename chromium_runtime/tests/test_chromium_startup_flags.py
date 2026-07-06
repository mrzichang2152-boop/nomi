from pathlib import Path


def test_chromium_startup_allows_oauth_popups():
    script = Path(__file__).resolve().parents[1] / "start-runtime.sh"
    text = script.read_text(encoding="utf-8")

    assert "--disable-popup-blocking" in text


def test_chromium_startup_disables_crash_session_restore():
    script = Path(__file__).resolve().parents[1] / "start-runtime.sh"
    text = script.read_text(encoding="utf-8")

    assert "--disable-session-crashed-bubble" in text
    assert "--disable-gpu-rasterization" in text


def test_chromium_startup_marks_profile_clean_without_clearing_site_data():
    script = Path(__file__).resolve().parents[1] / "start-runtime.sh"
    text = script.read_text(encoding="utf-8")

    assert "PREFERENCES_FILE=\"/app/user_profile/Default/Preferences\"" in text
    assert "exited_cleanly" in text
    assert "exit_type" in text
    assert "Normal" in text
    assert "event_log" in text
    assert "session_data_status" in text


def test_chromium_startup_allows_local_cdp_websocket_clients():
    script = Path(__file__).resolve().parents[1] / "start-runtime.sh"
    text = script.read_text(encoding="utf-8")

    assert "--remote-allow-origins=*" in text


def test_chromium_startup_preserves_site_session_storage_for_login_state():
    script = Path(__file__).resolve().parents[1] / "start-runtime.sh"
    text = script.read_text(encoding="utf-8")

    cleanup_block = text.split("fluxbox >/tmp/fluxbox.log", 1)[0]

    assert "/app/user_profile/Default/Session\\ Storage" not in cleanup_block
