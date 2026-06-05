# Nomi Production Release Checklist

Status: draft for the single-user private-cloud release.

This checklist is intentionally operational. A release is not considered ready until each item has either a fresh verification artifact or an explicit remaining gap.

## HTTPS/TLS

- Put nginx or an upstream reverse proxy behind a real domain.
- Terminate HTTPS/TLS before exposing the workbench, `/ws`, and noVNC.
- Keep `80/tcp` open only for ACME challenge or redirect.
- Verify WebSocket upgrade still works after TLS termination.

Evidence to collect:

- `curl -I https://<domain>/health`
- WebSocket chat smoke through `wss://<domain>/ws`

Remaining gap:

- The current compose exposes plain HTTP on port `80`; TLS is a deployment step, not yet encoded in compose.

## Backups

- Back up `postgres_data`, `redis_data`, and `chromium_profile`.
- Keep `model_cache` optional because it can be rebuilt.
- Run a restore drill before public release notes are published.

Evidence to collect:

- Backup archive path and timestamp.
- Restore drill result against a clean compose stack.

Remaining gap:

- There is maintenance but no checked-in backup/restore script yet.

## Secrets

- Rotate `APP_PASSWORD`, `VNC_PASSWORD`, `RAW_DATA_ENCRYPTION_KEY`, and external API keys before release.
- Never commit real `COMPOSIO_API_KEY`, model credentials, cookies, profile archives, or Android signing keys.
- Use `.env` on the private server and keep `.env.example` non-secret.

Evidence to collect:

- `git status --short` confirms no generated secrets are staged.
- `rg -n "ak_|AIza|sk-|password"` is reviewed before push.

Remaining gap:

- Secret scanning is still manual; add an automated pre-push check later.

## Android APK

- Build with JDK 17 and Android SDK 35.
- Verify the floating Nomi panel can open, close, reconnect WebSocket, and preserve chat history.
- Confirm the APK points to the intended private-cloud base URL before distribution.

Evidence to collect:

- `JAVA_HOME=/opt/homebrew/opt/openjdk@17 gradle :app:testDebugUnitTest`
- `JAVA_HOME=/opt/homebrew/opt/openjdk@17 gradle :app:assembleDebug`
- Emulator screenshot or manual verification note.

Remaining gap:

- Release signing and Play/App Store distribution are out of scope for the current private-cloud build.

## Online regression

- Run the online regression plan after deployment, using the live server rather than localhost.
- Cover collector capability reporting, Gmail/WhatsApp/Telegram ingestion paths, proactive suggestions, streaming chat, core pipelines, and long-tail fallback.
- Inspect the returned content for correctness, especially dates, participants, and action recommendations.

Evidence to collect:

- `REGRESSION_BASE_URL=<server> APP_PASSWORD=<password> python3 scripts/online-regression-g2-g5-checks.py`
- Optional Gmail Composio fetch after a connected Gmail account is healthy:
  `REGRESSION_RUN_GMAIL_COMPOSIO_FETCH=1 ...`

Remaining gap:

- A fresh live run still needs to be recorded after the next server deployment.

## Rollback

- Keep the previous Docker image or git commit available before deploying a new build.
- Snapshot Postgres before schema-affecting changes.
- Roll back by restoring the previous commit and restarting compose.

Evidence to collect:

- Previous commit hash.
- Database snapshot timestamp.
- `docker compose ps` after rollback drill.

Remaining gap:

- No automated one-command rollback script exists yet.
