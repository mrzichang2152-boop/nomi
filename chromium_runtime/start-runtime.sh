#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:99}"
DISPLAY_NUMBER="${DISPLAY#:}"
SCREEN_WIDTH="${SCREEN_WIDTH:-1920}"
SCREEN_HEIGHT="${SCREEN_HEIGHT:-1080}"
SCREEN_DEPTH="${SCREEN_DEPTH:-24}"
CHROMIUM_WINDOW_WIDTH="${CHROMIUM_WINDOW_WIDTH:-$SCREEN_WIDTH}"
CHROMIUM_WINDOW_HEIGHT="${CHROMIUM_WINDOW_HEIGHT:-$SCREEN_HEIGHT}"
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

fluxbox >/tmp/fluxbox.log 2>&1 &

"$CHROMIUM_EXECUTABLE" \
  --user-data-dir=/app/user_profile \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port="$CHROMIUM_CDP_PORT" \
  --no-first-run \
  --no-sandbox \
  --no-default-browser-check \
  --password-store=basic \
  --disable-dev-shm-usage \
  --disable-gpu \
  --start-maximized \
  --window-size="${CHROMIUM_WINDOW_WIDTH},${CHROMIUM_WINDOW_HEIGHT}" \
  https://www.google.com \
  >/tmp/chromium.log 2>&1 &

x11vnc \
  -display "$DISPLAY" \
  -forever \
  -shared \
  -rfbport 5900 \
  -passwd "$VNC_PASSWORD" \
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
