#!/usr/bin/env bash
set -euo pipefail

COMPOSE_PROJECT_DIR="${COMPOSE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

cd "$COMPOSE_PROJECT_DIR"

docker compose exec -T postgres psql -U par -d par <<'SQL'
VACUUM (ANALYZE) events;
VACUUM (ANALYZE) semantic_events;
VACUUM (ANALYZE) facts;
VACUUM (ANALYZE) memory_states;
VACUUM (ANALYZE) memory_vectors;
VACUUM (ANALYZE) timeline;
VACUUM (ANALYZE) proactive_suggestions;
ANALYZE;
SQL

docker compose exec -T postgres psql -U par -d par -tAc "
SELECT
  'events=' || (SELECT count(*) FROM events) || ' ' ||
  'facts=' || (SELECT count(*) FROM facts) || ' ' ||
  'vectors=' || (SELECT count(*) FROM memory_vectors) || ' ' ||
  'states=' || (SELECT count(*) FROM memory_states);
"
