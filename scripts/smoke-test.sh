#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost}"

echo "Checking health..."
curl -fsS "$BASE_URL/health"
echo

echo "Checking assistant page..."
curl -fsS "$BASE_URL/" | grep -q "PAR"
echo "ok"

echo "Checking chat auth..."
if curl -fsS -X POST "$BASE_URL/api/chat" \
  -H 'content-type: application/json' \
  -d '{"message":"hello"}'; then
  echo "chat endpoint should require a password" >&2
  exit 1
else
  echo "unauthorized as expected"
fi

echo "Creating event..."
EVENT_RESPONSE="$(
  curl -fsS -X POST "$BASE_URL/event" \
    -H 'content-type: application/json' \
    -d '{"source":"search","event_type":"search","raw_data":{"query":"东京酒店","url":"https://google.com/search?q=tokyo+hotel"}}'
)"
echo "$EVENT_RESPONSE"

echo "Waiting for worker..."
sleep 2

echo "Searching memory..."
curl -fsS -X POST "$BASE_URL/search" \
  -H 'content-type: application/json' \
  -d '{"query":"东京酒店","limit":5}'
echo

echo "Reading timeline..."
curl -fsS "$BASE_URL/timeline"
echo

if [[ -n "${APP_PASSWORD:-}" ]]; then
  echo "Reading suggestions..."
  curl -fsS "$BASE_URL/api/suggestions" \
    -H "x-par-password: $APP_PASSWORD"
  echo
fi

echo "Done."
