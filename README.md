# Personal AI Runtime

Private-cloud personal context runtime based on Managed Chromium, event collectors, semantic memory, and personal search.

## Local Development

```bash
docker compose up --build
```

API:

```bash
curl http://localhost:8080/health
curl http://localhost:8080/collectors/health
```

Create a test event:

```bash
curl -X POST http://localhost:8080/event \
  -H 'content-type: application/json' \
  -d '{"source":"search","event_type":"search","raw_data":{"query":"东京酒店"}}'
```

## Server Deployment

The server entrypoint is nginx on port `80`.

```bash
cd /opt/par
docker compose up -d --build
```

This compose file is tuned for a single-user 4C/8G private server:

* FastEmbed cache is persisted at `/models/fastembed` in the `model_cache` Docker volume.
* Postgres, Redis, Chromium profile, and model cache are persistent volumes.
* Service logs use Docker JSON log rotation: 20 MB x 5 files per service.
* Containers use conservative CPU and memory limits so Chromium or embedding cannot consume the whole machine.
* Services use `restart: unless-stopped` for unattended private-cloud use.

Run smoke tests:

```bash
BASE_URL=http://your-server.example.com bash scripts/smoke-test.sh
```

Import a small public long-term-memory seed set from LoCoMo:

```bash
python3 scripts/import-locomo-seed.py --base-url http://your-server.example.com --limit 12
```

Only expose these ports in the security group:

* `10799/tcp` for SSH.
* `80/tcp` for the current API.
* `443/tcp` for future HTTPS.
* `6080/tcp` for browser login through noVNC.

Postgres, Redis, and the FastAPI container stay inside Docker networking.

Routine maintenance:

```bash
cd /opt/par
bash scripts/db-maintenance.sh
```

For single-user usage, running maintenance weekly is enough at the current scale. If memory grows into hundreds of thousands of events or vectors, add scheduled pruning/consolidation before increasing worker concurrency.

Remote browser login:

```text
http://your-server.example.com:6080/vnc.html
```

Default VNC password is configured through `VNC_PASSWORD`.

## Services

* `runtime-api`: FastAPI event, search, timeline, reasoning, memory governance API.
* `worker`: Redis Stream consumer for desensitization and semantic extraction.
* `chromium-runtime`: Playwright persistent Chromium runtime scaffold.
* `postgres`: PostgreSQL with pgvector.
* `redis`: Redis Stream queue.
* `nginx`: Public HTTP proxy.
