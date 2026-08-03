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


def test_chromium_startup_uses_page_zoom_without_scaling_the_x11_window():
    script = Path(__file__).resolve().parents[1] / "start-runtime.sh"
    text = script.read_text(encoding="utf-8")

    assert 'CHROMIUM_PAGE_ZOOM_PERCENT="${CHROMIUM_PAGE_ZOOM_PERCENT:-125}"' in text
    assert 'zoom_factor = float(os.environ["CHROMIUM_PAGE_ZOOM_PERCENT"]) / 100.0' in text
    assert 'math.log(zoom_factor) / math.log(1.2)' in text
    assert 'partition["default_zoom_level"] = {"x": zoom_level}' in text
    assert "--force-device-scale-factor" not in text


def test_chromium_startup_exits_when_browser_or_collector_process_dies():
    script = Path(__file__).resolve().parents[1] / "start-runtime.sh"
    text = script.read_text(encoding="utf-8")

    assert 'CHROMIUM_PID="$!"' in text
    assert "python -m app.runtime &" in text
    assert 'RUNTIME_PID="$!"' in text
    assert 'wait -n "$CHROMIUM_PID" "$RUNTIME_PID"' in text
