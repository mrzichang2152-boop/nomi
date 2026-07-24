#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:99}"
DISPLAY_NUMBER="${DISPLAY#:}"
SCREEN_WIDTH="${SCREEN_WIDTH:-1920}"
SCREEN_HEIGHT="${SCREEN_HEIGHT:-1080}"
SCREEN_DEPTH="${SCREEN_DEPTH:-24}"
CHROMIUM_WINDOW_WIDTH="${CHROMIUM_WINDOW_WIDTH:-$SCREEN_WIDTH}"
CHROMIUM_WINDOW_HEIGHT="${CHROMIUM_WINDOW_HEIGHT:-$SCREEN_HEIGHT}"
CHROMIUM_PAGE_ZOOM_PERCENT="${CHROMIUM_PAGE_ZOOM_PERCENT:-125}"
export CHROMIUM_PAGE_ZOOM_PERCENT
VNC_PASSWORD="${VNC_PASSWORD:-par-dev-vnc}"
CHROMIUM_EXECUTABLE="${CHROMIUM_EXECUTABLE:-/usr/bin/chromium}"
CHROMIUM_CDP_PORT="${CHROMIUM_CDP_PORT:-9222}"

rm -f "/tmp/.X${DISPLAY_NUMBER}-lock" "/tmp/.X11-unix/X${DISPLAY_NUMBER}"

Xvfb "$DISPLAY" -screen 0 "${SCREEN_WIDTH}x${SCREEN_HEIGHT}x${SCREEN_DEPTH}" -ac +extension RANDR &
XVFB_PID="$!"

cat >/usr/local/bin/fbsetbg <<'EOF'
#!/usr/bin/env sh
exit 0
EOF
chmod +x /usr/local/bin/fbsetbg

mkdir -p /root/.fluxbox
cat >/root/.fluxbox/overlay <<'EOF'
background: none
EOF

if ! pgrep -x chromium >/dev/null 2>&1; then
  rm -f \
    /app/user_profile/SingletonCookie \
    /app/user_profile/SingletonLock \
    /app/user_profile/SingletonSocket \
    /app/user_profile/Default/LOCK
fi

# Keep account cookies/local storage, but do not restore stale tabs after a
# container/browser crash. A restored tab storm makes the VNC workspace unusable
# and can leave the visible tab out of sync with the CDP target used by Nomi.
# Do not clear site Session Storage here: WhatsApp Web and Google account
# linking can depend on it during and after login.
rm -rf \
  /app/user_profile/Default/Sessions \
  /app/user_profile/Default/Current\ Session \
  /app/user_profile/Default/Current\ Tabs \
  /app/user_profile/Default/Last\ Session \
  /app/user_profile/Default/Last\ Tabs

mkdir -p /app/user_profile/Default
PREFERENCES_FILE="/app/user_profile/Default/Preferences"
python3 - <<'PY'
import json
import math
import os
from pathlib import Path

path = Path("/app/user_profile/Default/Preferences")
if path.exists():
    try:
        preferences = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raise SystemExit(0)
else:
    preferences = {}

profile = preferences.setdefault("profile", {})
profile["exited_cleanly"] = True
profile["exit_type"] = "Normal"
sessions = preferences.setdefault("sessions", {})
sessions["event_log"] = []
sessions["session_data_status"] = 0
zoom_factor = float(os.environ["CHROMIUM_PAGE_ZOOM_PERCENT"]) / 100.0
zoom_level = math.log(zoom_factor) / math.log(1.2)
partition = preferences.setdefault("partition", {})
partition["default_zoom_level"] = {"x": zoom_level}
path.write_text(json.dumps(preferences, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
PY

fluxbox >/tmp/fluxbox.log 2>&1 &

"$CHROMIUM_EXECUTABLE" \
  --user-data-dir=/app/user_profile \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port="$CHROMIUM_CDP_PORT" \
  --remote-allow-origins=* \
  --no-first-run \
  --no-sandbox \
  --no-default-browser-check \
  --password-store=basic \
  --disable-popup-blocking \
  --disable-dev-shm-usage \
  --disable-gpu \
  --disable-gpu-rasterization \
  --disable-session-crashed-bubble \
  --start-maximized \
  --window-size="${CHROMIUM_WINDOW_WIDTH},${CHROMIUM_WINDOW_HEIGHT}" \
  --window-position=0,0 \
  https://www.google.com \
  >/tmp/chromium.log 2>&1 &

(
  for _ in $(seq 1 80); do
    CHROMIUM_WINDOW_IDS="$(xdotool search --class chromium 2>/dev/null || true)"
    if [ -n "$CHROMIUM_WINDOW_IDS" ]; then
      for CHROMIUM_WINDOW_ID in $CHROMIUM_WINDOW_IDS; do
        xdotool windowmap "$CHROMIUM_WINDOW_ID" >/dev/null 2>&1 || true
        xdotool windowmove "$CHROMIUM_WINDOW_ID" 0 0 >/dev/null 2>&1 || true
        xdotool windowsize "$CHROMIUM_WINDOW_ID" "$CHROMIUM_WINDOW_WIDTH" "$CHROMIUM_WINDOW_HEIGHT" >/dev/null 2>&1 || true
        xdotool windowraise "$CHROMIUM_WINDOW_ID" >/dev/null 2>&1 || true
      done
      xdotool windowactivate "$(printf '%s\n' "$CHROMIUM_WINDOW_IDS" | tail -n 1)" >/dev/null 2>&1 || true
      break
    fi
    sleep 0.25
  done
) &

x11vnc \
  -display "$DISPLAY" \
  -forever \
  -shared \
  -rfbport 5900 \
  -passwd "$VNC_PASSWORD" \
  -noxdamage \
  -ncache 0 \
  -quiet \
  >/tmp/x11vnc.log 2>&1 &

websockify \
  --web=/usr/share/novnc \
  0.0.0.0:6080 \
  localhost:5900 \
  >/tmp/novnc.log 2>&1 &

cleanup() {
  kill "$XVFB_PID" 2>/dev/null || true
}
trap cleanup EXIT

python -m app.runtime
