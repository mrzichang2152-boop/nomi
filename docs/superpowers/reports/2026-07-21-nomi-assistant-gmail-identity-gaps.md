# Nomi Assistant Gmail Identity Implementation Gaps

**Date:** 2026-07-22
**Scope:** Nomi-owned Gmail only
**Status:** Real Gmail OAuth, cloud identity binding, inbound synchronization, and draft confirmation gate verified; one explicitly confirmed provider send remains pending
**Design:** `docs/superpowers/specs/2026-07-21-nomi-assistant-identity-configuration-design.md`
**Plan:** `docs/superpowers/plans/2026-07-21-nomi-assistant-identity-configuration-implementation.md`

## Baseline

Command:

```bash
PYTHONPATH=runtime_api python3 -m pytest -q \
  runtime_api/tests/test_assistant_identity_schema.py \
  runtime_api/tests/test_assistant_identity_registry.py \
  runtime_api/tests/test_assistant_identity_api.py \
  runtime_api/tests/test_assistant_identity_adapters.py \
  runtime_api/tests/test_assistant_gmail_adapter.py \
  runtime_api/tests/test_assistant_outbound_pipeline.py \
  runtime_api/tests/test_assistant_trigger_routing.py \
  runtime_api/tests/test_assistant_identity_memory_scope.py
```

Result: `44 passed in 1.00s`.

Semantic interpretation: the existing test suite proves the current in-memory identity and environment-variable adapter skeleton is internally consistent. It does **not** prove provider authentication, restart persistence, account separation, real inbound email, real outbound email, confirmation integrity, or delivery audit.

## Gap Status

Legend:

- `Complete locally`: implemented and verified by payload/state/side-effect assertions.
- `Implemented, live pending`: production code exists, but cloud/provider/device evidence is still missing.
- `Open`: required behavior has not yet passed the specified acceptance environment.

| ID | Status | Evidence / remaining work |
| --- | --- | --- |
| G01 | Complete on cloud | PostgreSQL repository/schema/versioning passed locally and the deployed cloud identity/draft records survived a real `runtime-api` container restart with the same ids, revisions, and payloads. |
| G02 | Complete locally | Lifecycle tests prove clients cannot jump to `connected`; provider-derived verification and append-only health determine capabilities. |
| G03 | Complete on cloud | Assistant-scoped Composio Connect Link and bound callback replace fake connect. Real OAuth completed for the pinned Nomi account. The callback now accepts Composio's current `connectedAccountId` field as well as the snake-case form, and the cloud identity is `connected` with a provider-derived Gmail address. |
| G04 | Complete locally | Pinned connected-account tests reject user-owned, wrong-toolkit, and unpinned accounts. |
| G05 | Complete locally | Verification accepts only a valid Gmail address returned by the pinned provider profile; the client cannot set it. |
| G06 | Complete locally | Trigger/fallback event normalization, stable event ids, assistant scope, deduplication, and no-auto-reply routing are asserted. |
| G07 | Complete on cloud | A real Gmail trigger was created and persisted. A bounded real sync fetched 10 recent messages. The first run exposed a current-schema mismatch (`messageText`/`messageTimestamp`) that produced empty bodies; a failing-first regression fixed the parser, the 10 invalid rows were removed, and a clean re-sync produced 10/10 messages with non-empty body, subject, provider timestamp, and contact-scoped low-trust classification. Live trigger delivery latency remains an operational observation item, not an OAuth blocker. |
| G08 | Complete on cloud | PostgreSQL drafts, confirmations, outbound history, receipts, and audit repositories exist. A safe `.invalid` cloud draft survived a real container restart unchanged and was then cancelled without a provider send. |
| G09 | Complete locally | OpenCode manifest exposes only bounded assistant identity/contact/draft/status/cancel tools; invented/raw send tools and client-expanded scopes fail closed. |
| G10 | Complete locally | Deterministic requests and OpenCode both enter the same persisted draft/policy gateway. |
| G11 | Complete locally | Scope, evidence, protected confirmation, near-duplicate, per-contact, per-channel, daily quota, provider state, and timeout behavior are asserted. |
| G12 | Complete locally | Editing protected content persists the same draft id, invalidates old confirmations, and requires a new confirmation. |
| G13 | Complete locally | Idempotency survives pipeline recreation; timeout is `delivery_unknown`; two independent valid Web/Android confirmation tokens now compete for one revision-bound draft claim, and both in-memory and real-PostgreSQL concurrency validation prove exactly one provider call. |
| G14 | Implemented, live pending | Web has first-level `助理身份`, provider actions, inbox/draft/history/policy views, and shared chat draft cards. Browser screenshot QA was blocked because the browser tool reported `No browser is available`. |
| G15 | Implemented, live pending | Current APK was installed on real device `DQYTCYFMO7VSEAJB`; settings and assistant-identity views loaded the cloud `authorization_pending` state and exposed inbox/draft/history sections without provider tokens. Real-device OAuth callback/back/rotation/keyboard validation still requires completed Gmail authorization. |
| G16 | Implemented, live pending | Web and Android use the same draft endpoint/id/state; cards expose identity, status, recipient, subject, body, evidence, edit/send/cancel and refresh after HTTP/realtime chat. Real visual cross-surface verification remains open. |
| G17 | Complete locally | `assistant-identity-configuration-regression.py` passed 10/10 semantic cases, including provider truth, account isolation, draft-only OpenCode, immutable confirmation, concurrent send suppression, restart semantics, inbox scope, and redacted audit. |
| G18 | Complete on cloud | Cloud `.env` now has a generated persistent `NOMI_SECRET_MASTER_KEY` and assistant Gmail callback URL; runtime/worker/nginx were rebuilt, all assistant identity tables were verified in PostgreSQL, and health/restart checks passed without printing the key. |
| G19 | Partially complete on cloud | Dedicated Gmail OAuth, provider profile verification, real inbound fetch, persistent inbox events, and a real-recipient draft/confirmation card are verified. An unconfirmed send was rejected with HTTP `403`, proving no side effect occurred. One user-approved real send, provider message id, receipt/audit reconciliation, reconnect, and post-authorization restart acceptance remain open. |

## Implementation Progress

### Checkpoint 1: Persistent Identity Source Of Truth

- [x] Schema now includes provider, lifecycle diagnostics, optimistic versioning, credential expiry, and append-only health checks without a raw token column.
- [x] In-memory and PostgreSQL repositories implement add-if-missing, read, list, versioned update, and stale-write rejection.
- [x] Production application wiring selects PostgreSQL; `postgresql://test` remains database-free for unit tests.
- [x] Default bootstrap no longer writes placeholder Gmail addresses and cannot overwrite an existing verified identity.
- [x] Lifecycle service enforces authorization and verification before `connected`; client status patches are rejected.
- [x] Verification failures keep only a stable redacted error code.
- [x] Focused and baseline regression result: `57 passed in 0.91s`.
- [x] Real local PostgreSQL validation result: five semantic checks passed and the transaction was rolled back.
- [x] Cloud container restart persistence was verified with a safe persisted draft and unchanged identity source of truth.

### Checkpoint 2: Secret Vault And Redaction

- [x] AES-256-GCM envelopes use a fresh nonce and bind identity, provider, credential name, and schema version as authenticated data.
- [x] Tampering, wrong keys, wrong identity, and wrong credential names fail closed.
- [x] In-memory and PostgreSQL credential repositories expose only a redacted public representation.
- [x] Missing master key blocks only local-secret operations with `secret_vault_unavailable` and preserves existing ciphertext.
- [x] Identity read APIs remain available without a vault key.
- [x] Real local PostgreSQL validation proved ciphertext-at-rest and successful authenticated round trip inside a rolled-back transaction.

### Checkpoints 3-7: Provider Lifecycle, Gateway, And Outbound Safety

- [x] Fake status patching is rejected; explicit connect/verify/reconnect/disable/disconnect lifecycle APIs are present.
- [x] Composio session/account binding is assistant-scoped and pins the connected account id.
- [x] Provider profile verification owns the displayed Gmail address.
- [x] Trigger setup, idempotent inbound normalization, bounded fallback sync, and degraded health are implemented.
- [x] OpenCode receives bounded high-level tools only and cannot call provider send or credentials directly.
- [x] Deterministic routing and OpenCode use one persisted draft gateway.
- [x] Confirmation binds protected content; edits invalidate stale confirmation.
- [x] Near-duplicate and quota policies return actionable blocked states.
- [x] Timeout becomes `delivery_unknown` and is not blindly retried.
- [x] Stale `sending` attempts are reconciled conservatively to `delivery_unknown`; recovery never performs an automatic provider retry.
- [x] Server-side revision-bound draft claiming prevents concurrent Web/Android provider duplication even when each surface holds a different valid confirmation token.
- [x] Editing a blocked draft reruns policy, and only a policy-passing edit returns to confirmation-required state.
- [x] Append-only audit records redact recipient/body/token/provider secrets.

### Checkpoints 8-9: Web And Android

- [x] Web first-level `助理身份` view and Gmail operations are implemented.
- [x] Web chat renders authoritative draft cards and later send/delivery/failure states.
- [x] Android full app reads the same identity lifecycle and returns from OAuth to the assistant identity page.
- [x] Android floating chat reads the same server drafts, shows identity/status/evidence, supports edit/confirm/cancel, and refreshes after both realtime and HTTP chat completion.
- [x] Android uses the persisted outbound status for success/failure wording; `delivery_unknown` explicitly requires provider verification and blocked/terminal cards cannot be reconfirmed.
- [x] Web blocked cards expose edit/cancel only and do not present a misleading retry/send action.
- [x] Repeated taps have client guards; the authoritative duplicate-send guarantee is server-side.
- [ ] Browser visual QA is pending because no controllable browser was available.
- [x] Android real-device settings and assistant-identity visual loading were verified on `DQYTCYFMO7VSEAJB` with the current APK.
- [ ] Android callback return, connected-account state, and live draft-card interaction remain part of G15/G19; OAuth itself completed in a real browser session.

### Checkpoint 10: Regression

- [x] Complete runtime API suite: `1480 passed, 2 skipped in 12.97s`; both PostgreSQL-dependent semantics were additionally exercised against the real local Docker PostgreSQL instance.
- [x] Android unit tests and debug APK assembly: `BUILD SUCCESSFUL in 2s`.
- [x] Web JavaScript syntax check: `node --check runtime_api/app/static/app.js` exited `0`.
- [x] Semantic acceptance script: `10/10 passed` in `3582 ms`; each case asserts a product payload, state transition, or side-effect count.
- [x] Real PostgreSQL concurrent-send validation: final status `sent`, revision `3`, provider call count `1`.
- [x] Real PostgreSQL identity/vault validation: all seven persistence, versioning, encryption-at-rest, and authenticated round-trip checks passed inside a rolled-back transaction.
- [x] Cloud deployment, schema presence, health, stable secret configuration, and restart persistence passed.
- [x] Real dedicated Gmail OAuth and inbound synchronization acceptance passed.
- [ ] One explicitly confirmed provider send and receipt/audit reconciliation remain pending.

## Deferred And Not Counted As V1 Gaps

- Nomi-owned WhatsApp Business/Cloud API identity.
- WhatsApp webhook, template, service-window, send, and receipt behavior.
- Bulk marketing or unrestricted automatic replies.

User-owned WhatsApp collection remains an existing independent subsystem and must not regress.

## Change Log

- 2026-07-21: Captured 44-test baseline and created Gmail-only gap tracker before production changes.
- 2026-07-21: Completed Checkpoint 1 locally; deliberately left cloud restart acceptance open.
- 2026-07-22: Completed local Gmail V1 implementation through Web/Android shared draft state and added server-side atomic confirmation claiming after a review reproduced two concurrent provider calls.
- 2026-07-22: Added reproducible 10-case semantic regression; first run truthfully failed 2 cases because the subprocess lacked `PYTHONPATH`, then passed 10/10 after fixing the runner.
- 2026-07-22: Full runtime API regression passed `1473 passed, 1 skipped`; Android tests and APK assembly passed. Cloud, real Gmail, browser visual, and real-device visual acceptance remain open.
- 2026-07-22: Re-ran the expanded suite after recovery and concurrency hardening: `1480 passed, 2 skipped`; both skipped PostgreSQL semantics passed separately against the real local Docker database. Added stale-send recovery, revision-bound dual-token claiming, truthful Android result wording, and blocked-card action guards. Cloud and real Gmail acceptance remain open.
- 2026-07-22: Deployed Gmail V1 to the cloud, generated the persistent secret/callback configuration, verified PostgreSQL migrations and container restart persistence, and installed the current APK on the real Android device. Reproduced the abandoned-OAuth-link 500 (`authorization_pending -> authorization_pending`), added a failing-first refresh test, passed `46` focused tests, redeployed the fix, and generated a fresh real Composio link. Dedicated Gmail authorization and real inbound/outbound acceptance remain open.
- 2026-07-22: Completed the real Composio Gmail authorization. Diagnosed and fixed two production-only compatibility gaps: callback account ids arrive as `connectedAccountId`, and manual Composio Gmail tools require a fixed toolkit version. Related regression passed `72 tests` before the real callback returned `Nomi Gmail 授权成功` and the identity became `connected` with `draft/send/thread_reply/receive` capabilities.
- 2026-07-22: Real inbound sync initially fetched 10 provider messages but stored empty bodies. Inspection of the current provider payload identified `messageText` and `messageTimestamp`; a failing-first integration test reproduced it, the parser was fixed, and the Gmail regression suite passed `73 tests`. After removing exactly 10 invalid empty events and re-syncing, all 10 real events had non-empty text, subject, timestamp, and low-trust unknown-sender scope. A real-recipient draft was created without sending, and an empty confirmation token was rejected with HTTP `403`.
