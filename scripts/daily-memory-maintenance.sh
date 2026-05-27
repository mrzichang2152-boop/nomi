#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
APP_PASSWORD="${APP_PASSWORD:-par-dev}"
DATE="${DATE:-$(date -u -v-1d +%F 2>/dev/null || date -u -d 'yesterday' +%F)}"
RAW_RETENTION_DAYS="${RAW_RETENTION_DAYS:-30}"
LOW_VALUE_RAW_RETENTION_DAYS="${LOW_VALUE_RAW_RETENTION_DAYS:-7}"

curl -fsS "$BASE_URL/api/maintenance/daily" \
  -H "content-type: application/json" \
  -H "x-par-password: $APP_PASSWORD" \
  -d "{
    \"date\": \"$DATE\",
    \"raw_retention_days\": $RAW_RETENTION_DAYS,
    \"low_value_retention_days\": $LOW_VALUE_RAW_RETENTION_DAYS
  }"
