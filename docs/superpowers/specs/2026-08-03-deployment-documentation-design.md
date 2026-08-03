# Nomi Deployment Documentation Design

**Date:** 2026-08-03

## Objective

Make a fresh Git clone self-sufficient for deployment. A new operator should be able to discover the deployment guide from the repository root, configure a private single-server installation without relying on historical chat context, start it, verify it, connect mobile clients, and recover from common failures.

## Audience and Supported Path

The primary audience is an operator deploying Nomi to a private Ubuntu 22.04 or 24.04 server. The canonical path targets a single 4-vCPU/8-GB host using Docker Engine and Docker Compose v2.

Local development, Android, and iOS instructions are secondary paths. They will be included only to the extent required to connect a client to the deployed server or build the existing client projects.

## Documentation Structure

Create a root-level `DEPLOYMENT.md` as the canonical deployment guide. Keep `README.md` concise, add a prominent link to the guide, and retain a short quick-start section for experienced operators.

The guide will be organized in execution order:

1. Architecture and resource requirements.
2. Server preparation and Docker installation verification.
3. Repository clone and environment configuration.
4. Network and security-group configuration.
5. Container build and startup.
6. First login and health verification.
7. External capability configuration.
8. Android and iOS client connection/build instructions.
9. Routine operation, upgrade, backup, restore, and removal.
10. Symptom-oriented troubleshooting.

Commands will be directly runnable after replacing explicit placeholders such as `<SERVER_IP>` and `<YOUR_MODEL_API_KEY>`. No production secret, private key, access password, test account, or current server-specific credential will be copied into the repository.

## Configuration Model

The environment-variable section will distinguish three groups:

- Required for a useful base deployment: application password, VNC password, stable encryption secrets, and model endpoint/model identity settings.
- Required only when enabling a capability: Composio, web-search providers, speech recognition, assistant-owned identities, and Apple Push Notification settings.
- Advanced operational tuning: attachment limits, background-worker intervals, retention, OpenCode worker settings, and provider ordering.

The guide will explicitly explain the relationship between Nomi's normal model configuration and OpenCode artifact model configuration. Operators will be instructed to replace historical example endpoints rather than treating them as public defaults.

Stable encryption values will be generated once and preserved across rebuilds and upgrades. The guide will warn that losing or rotating those values without a migration can make stored encrypted configuration unreadable.

## External Accounts and Remote Browser

The guide will document:

- The Composio API-key requirement and the need for permissions that can create authorization sessions.
- Public callback URLs derived from the deployed server origin.
- The browser-based authorization flow for Gmail and other supported toolkits.
- noVNC access on port 6080 for accounts that require an interactive web login, including WhatsApp Web.
- The difference between a configured API key and a successfully connected external account.

The documentation will not promise that third-party authentication can be completed unattended. It will identify the steps where the account owner must authenticate, scan a QR code, or grant consent.

## Networking and Security

The canonical guide will expose only the ports needed by the selected installation:

- The operator-selected SSH port (22 by default unless changed).
- Port 80 for the current HTTP entrypoint.
- Port 443 when TLS is configured.
- Port 6080 only when interactive browser login is needed, preferably restricted to the operator's IP.

Postgres, Redis, and internal FastAPI ports remain inside the Docker network. The guide will clearly state that the current plain-HTTP setup is suitable only for a controlled private deployment and recommend TLS before transmitting credentials over untrusted networks.

## Verification Strategy

Verification will be layered so failures are easy to localize:

1. `docker compose config` validates interpolation and Compose syntax.
2. `docker compose ps` confirms container and health state.
3. `/health` confirms the public reverse-proxy path.
4. `scripts/smoke-test.sh` verifies the assistant page, authentication boundary, event ingestion, worker processing, search, and timeline.
5. Optional capability checks verify model calls, Composio connection creation, noVNC access, and mobile-client login.

The guide will call out that a green base smoke test does not prove third-party accounts are authorized.

## Operations and Data Safety

The guide will identify all named persistent volumes and provide commands for inspecting and backing up critical state. PostgreSQL backup will use `pg_dump`; configuration and environment files will be backed up separately; browser profiles and attachment/artifact data will be treated as stateful volumes.

Upgrade instructions will fetch the intended Git revision, back up first, rebuild the images, and rerun verification. Rollback instructions will restore the previous revision while preserving compatible volumes. Destructive removal will be clearly separated and warn that `docker compose down -v` deletes persistent data.

## Mobile Clients

Android instructions will reflect the repository's actual requirements: Android SDK 35, JDK 17, a local `android_app/local.properties`, debug APK construction, installation through ADB, and entering the deployed base URL plus `APP_PASSWORD` in the app.

iOS instructions will describe the existing Xcode project, signing prerequisites, server configuration in the app, and the fact that device installation requires an Apple development team. iOS-specific push and Live Activity configuration will remain optional.

## README Corrections

The README will link to `DEPLOYMENT.md`, preserve a compact local-development path, and replace server-specific or ambiguous claims with configuration-driven wording. In particular, the SSH port will not be presented as unconditionally fixed to `10799`.

## Scope Boundaries

This work changes documentation and, if needed for clarity, comments/placeholders in `.env.example`. It does not change application behavior, Compose service topology, production credentials, cloud security groups, or the currently running server.

No automated deployment script will be introduced in this iteration. The existing Compose file and smoke-test script remain the executable deployment and verification mechanisms.

## Acceptance Criteria

- A root-level deployment guide is visible from the README.
- A clean-clone operator can reach a healthy web login by following the server path in order.
- Required and optional environment values are distinguishable.
- Model, OpenCode, Composio, browser-login, and mobile-client setup are documented.
- Verification, backup, upgrade, rollback, and troubleshooting procedures are present.
- Commands and file paths match the repository.
- No real credential or server-specific secret is added.
- Markdown links, shell examples, Compose commands, and referenced paths pass a manual documentation review.
