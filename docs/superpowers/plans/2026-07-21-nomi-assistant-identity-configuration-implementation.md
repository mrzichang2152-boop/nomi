# Nomi Assistant Identity Configuration TDD Implementation Plan

> **Required workflow:** Execute task by task. For every task, write the failing test first, run it and inspect the failure, implement the smallest correct behavior, rerun focused tests, inspect semantic output, then run the checkpoint regression set. Do not mark live-provider items complete with fake data.

**Goal:** Deliver a persistent, configurable Nomi Gmail identity with truthful provider state, a bounded OpenCode tool gateway, confirmation-gated outbound execution, Web/Android configuration surfaces, and real-account acceptance.

**Design:** `docs/superpowers/specs/2026-07-21-nomi-assistant-identity-configuration-design.md`

**Architecture:** Replace the in-memory assistant identity registry with a PostgreSQL repository and provider-derived lifecycle service. Keep provider credentials behind a local secret vault or Composio. Route deterministic pipelines and OpenCode through one Nomi-owned assistant tool gateway. OpenCode may create drafts but cannot send. Web and Android consume the same server-side identities, drafts, inbox, health, and audit records.

**Primary technology:** FastAPI, psycopg 3, PostgreSQL, Composio Python SDK, vanilla Web UI, Android Java, pytest, Android unit tests.

> **Scope decision (2026-07-21):** Checkpoint 5 and every Nomi-owned WhatsApp deliverable are deferred. They are neither required for V1 nor counted as implementation gaps. Existing user-owned WhatsApp collection must continue to work and must not be modified by this plan.

## Working Rules

- Preserve user-owned Gmail and WhatsApp collectors as a separate system.
- Never put provider secrets, OAuth codes, access tokens, or webhook secrets in model context or logs.
- Never derive `connected` from a client-supplied status.
- Every mutating endpoint and tool call must be idempotent.
- Every send must create or reuse a persisted draft before provider execution.
- All fake-provider tests are local/integration evidence only, never live acceptance.
- Record every discovered omission in a dedicated gap report before closing the implementation.
- Inspect actual payload content, lifecycle state, and audit output; `200 OK` alone is not acceptance.

## Checkpoint 0: Baseline And Gap Tracker

### Task 0.1: Capture baseline and create implementation gap report

**Files:**

- Create: `docs/superpowers/reports/2026-07-21-nomi-assistant-identity-configuration-gaps.md`
- Modify only if necessary: existing assistant identity tests

**Steps:**

1. Run existing assistant identity tests before editing code:

   ```bash
   pytest -q \
     runtime_api/tests/test_assistant_identity_schema.py \
     runtime_api/tests/test_assistant_identity_registry.py \
     runtime_api/tests/test_assistant_identity_api.py \
     runtime_api/tests/test_assistant_identity_adapters.py \
     runtime_api/tests/test_assistant_gmail_adapter.py \
     runtime_api/tests/test_assistant_outbound_pipeline.py \
     runtime_api/tests/test_assistant_trigger_routing.py \
     runtime_api/tests/test_assistant_identity_memory_scope.py
   ```

2. Record pass/fail counts and semantic baseline in the gap report.
3. Explicitly record known gaps from the design: in-memory registry, fake connect, status patching, placeholder addresses, env-only credentials, missing Web configuration, read-only Android UI, live-provider gaps.
4. Checkpoint: no production behavior changes yet.

## Checkpoint 1: Persistent Identity Source Of Truth

### Task 1.1: Extend schema and lifecycle constraints

**Files:**

- Modify: `runtime_api/app/assistant_identity/schema.py`
- Modify: `runtime_api/tests/test_assistant_identity_schema.py`

**RED:** Add schema tests requiring:

- `provider`, `version`, `last_verified_at`, and `last_error_code` on `assistant_identities`;
- lifecycle-compatible default status `unconfigured`;
- `assistant_identity_health_checks` table and useful indexes;
- credential expiry and metadata fields;
- no raw access-token column.

Run:

```bash
pytest -q runtime_api/tests/test_assistant_identity_schema.py
```

Confirm failures identify missing columns/table, not unrelated import errors.

**GREEN:** Extend idempotent schema SQL and backward-compatible `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements.

**REFACTOR:** Centralize allowed lifecycle states and provider names in a small constants module if duplication appears.

**Semantic verification:** Inspect generated SQL and prove an old database can be migrated without dropping existing inbox/draft/audit rows.

### Task 1.2: Implement repository contracts and restart persistence

**Files:**

- Create: `runtime_api/app/assistant_identity/repository.py`
- Create: `runtime_api/tests/test_assistant_identity_repository.py`
- Modify: `runtime_api/app/assistant_identity/models.py`
- Modify: `runtime_api/app/assistant_identity/registry.py`
- Modify: `runtime_api/app/main.py`

**RED:** Add tests for both in-memory test repository and PostgreSQL contract behavior:

- bootstrap creates the stable Nomi Gmail identity once while preserving unrelated legacy identities;
- Gmail starts `unconfigured` when no verified provider exists;
- provider/address/status/version persist;
- restart/reinstantiation returns the same identity state;
- optimistic version conflict is rejected;
- unknown or user-owned identity kind is rejected.

**GREEN:** Implement `AssistantIdentityRepository`, `InMemoryAssistantIdentityRepository`, and `PostgresAssistantIdentityRepository`. Rework registry into a thin domain service over the repository.

**REFACTOR:** Move database mapping and JSON normalization out of API handlers.

**Semantic verification:** A process restart must not convert a configured identity back to placeholder values or overwrite it from environment variables.

### Task 1.3: Enforce lifecycle transitions

**Files:**

- Create: `runtime_api/app/assistant_identity/lifecycle.py`
- Create: `runtime_api/tests/test_assistant_identity_lifecycle.py`
- Modify: `runtime_api/app/assistant_identity/registry.py`

**RED:** Test valid and invalid transitions, including:

- `unconfigured -> authorization_pending -> verifying -> connected`;
- `connected -> degraded/expired/disabled`;
- `disabled -> verifying/connected` only through enable/verify;
- client cannot jump `unconfigured -> connected`;
- failed verification records a stable redacted error code.

**GREEN:** Implement transition service and replace direct status updates.

**Checkpoint 1 regression:** Run schema, repository, registry, lifecycle, and original identity API tests. Update tests that encoded fake-connect behavior only after proving the new behavior is semantically correct.

## Checkpoint 2: Secret Vault And Redaction

### Task 2.1: Implement authenticated local secret storage

**Files:**

- Create: `runtime_api/app/assistant_identity/secret_vault.py`
- Create: `runtime_api/tests/test_assistant_identity_secret_vault.py`
- Modify: `runtime_api/app/assistant_identity/repository.py`
- Modify: deployment environment examples, without real keys

**RED:** Test:

- AES-GCM encrypt/decrypt round trip;
- fresh nonce on every write;
- identity/provider/credential-name bound as authenticated data;
- tampering and wrong master key fail closed;
- secret rotation preserves newly encrypted value;
- API-safe representation says only `stored=true`;
- logs and dataclass repr do not contain secret values.

**GREEN:** Use `cryptography` AES-GCM with a validated 32-byte master key. Store only encrypted envelopes/references.

**REFACTOR:** Keep cryptographic primitives isolated; business code only calls `put`, `get`, `replace`, and `delete`.

**Semantic verification:** Search test output and serialized API responses for known test secrets; zero occurrences are required.

### Task 2.2: Fail safely when the master key is absent

**Files:**

- Modify: `runtime_api/app/main.py`
- Modify: `runtime_api/app/assistant_identity/secret_vault.py`
- Add tests to secret vault/API suites

**RED:** Require identity read APIs to remain available while configuration/send operations return a stable `secret_vault_unavailable` error. Existing encrypted rows must not be erased or replaced.

**GREEN:** Add blocked capability state without taking down unrelated Nomi features.

**Checkpoint 2 regression:** Run identity schema/repository/lifecycle/vault/API tests.

## Checkpoint 3: Truthful Configuration API

### Task 3.1: Replace generic fake connect and status patch semantics

**Files:**

- Modify: `runtime_api/app/main.py`
- Modify: request/response models in the appropriate API model section
- Modify: `runtime_api/tests/test_assistant_identity_api.py`

**RED:** Require:

- identity list/detail returns lifecycle, provider, verified capabilities, last verification, and secret-presence booleans;
- generic status patch is rejected;
- profile patch can update display name/style but not provider status/address;
- disable/enable/disconnect have explicit endpoints;
- all responses redact credentials;
- mutation responses include audit/trace ids and versions.

**GREEN:** Add the design API surface and deprecate fake connect behavior.

**Semantic verification:** A caller sending `{status: "healthy"}` must never make health true.

### Task 3.2: Add health history and capability derivation

**Files:**

- Create: `runtime_api/app/assistant_identity/health.py`
- Create: `runtime_api/tests/test_assistant_identity_health.py`
- Modify: repository/API/main wiring

**RED:** Test that:

- credentials, profile, inbound, and outbound checks are independent;
- Gmail may be connected but degraded when inbound trigger is stale;
- `healthy` is derived from current checks, not stored UI text;
- health history is append-only and redacted.

**GREEN:** Implement `AssistantIdentityHealthService` and read models.

## Checkpoint 4: Nomi Gmail Via Composio

### Task 4.1: Assistant-scoped Composio connection service

**Files:**

- Create: `runtime_api/app/assistant_identity/composio_gmail.py`
- Create: `runtime_api/tests/test_assistant_identity_composio_gmail.py`
- Modify: `runtime_api/app/main.py`
- Reuse: existing Composio session persistence helpers

**RED:** Test with a fake Composio client:

- stable user id `nomi-owned::nomi_gmail_primary`;
- stable alias `nomi-gmail-primary`;
- Connect Link callback targets the assistant identity page;
- connection request moves state to `authorization_pending`;
- callback validates state/identity binding;
- only an ACTIVE Gmail connected account can pass verification;
- authenticated Gmail profile determines the address;
- user-owned Gmail connected account is never selected;
- expired/revoked status maps truthfully.

**GREEN:** Implement session/link/callback lifecycle using current Composio APIs and persist connected account metadata.

**REFACTOR:** Hide SDK differences behind an injectable client protocol.

### Task 4.2: Gmail provider execution and inbound trigger strategy

**Files:**

- Modify: `runtime_api/app/assistant_identity/gmail_adapter.py`
- Create or modify: Gmail assistant sync/trigger worker module
- Modify: `runtime_api/tests/test_assistant_gmail_adapter.py`
- Add integration tests

**RED:** Require:

- adapter receives a pinned assistant connected-account reference, not a model-selected account;
- read-only verify/profile check succeeds before capability is exposed;
- send uses only confirmed draft fields;
- provider request/response is redacted in audit;
- trigger setup is attempted when supported;
- unavailable trigger enables bounded incremental sync and marks health accurately;
- duplicate inbound history/message ids are suppressed.

**GREEN:** Implement provider-neutral Composio Gmail adapter and inbound worker.

**Checkpoint 4 regression:** Run all assistant identity, Composio, Gmail, inbox, outbound, and memory-scope tests.

## Checkpoint 5: Reserved For Deferred Nomi WhatsApp

Skip this checkpoint in V1. Any future WhatsApp implementation requires a separate policy review, specification, TDD plan, and explicit user approval.

## Checkpoint 6: Unified Nomi Tool Gateway

### Task 6.1: Define high-level assistant tool schemas

**Files:**

- Create: `runtime_api/app/assistant_identity/tool_gateway.py`
- Create: `runtime_api/tests/test_assistant_identity_tool_gateway.py`
- Modify: `runtime_api/app/tool_registry.py`
- Modify: tool registry tests

**RED:** Require exact allowlist:

- `assistant.identity.get_status`;
- `assistant.contacts.resolve`;
- `assistant.email.create_draft`;
- `assistant.outbound.get_status`;
- `assistant.outbound.cancel_draft`.

Require raw Gmail, Composio send, confirmation token, and `send_confirmed_draft` to be absent from OpenCode-visible schemas.

**GREEN:** Implement schema-constrained tool gateway and task/evidence scope checks.

**Semantic verification:** Dump the actual OpenCode tool manifest and inspect every mutating effect.

### Task 6.2: Wire bounded tools into OpenCode runtime

**Files:**

- Modify: OpenCode task packet/prompt/tool bridge modules
- Modify: `runtime_api/tests/test_opencode_artifact_worker.py` or create a focused communication-tool bridge test

**RED:** Test:

- OpenCode can create a draft during an open-ended task;
- it receives confirmation-required result;
- direct provider tool names are rejected even if the model invents them;
- repeated step execution returns the same draft;
- task cannot resolve contacts outside its permitted scope;
- task checkpoint records the draft id, not credentials.

**GREEN:** Register only the Nomi gateway tools in the OpenCode capability layer.

### Task 6.3: Route deterministic pipelines through the same gateway

**Files:**

- Modify: `runtime_api/app/pipelines/communication.py`
- Modify: assistant routing/outbound modules
- Modify: pipeline and trigger routing tests

**RED:** Require known email requests and OpenCode-created email drafts to produce the same persisted draft contract, policy checks, confirmation card, and audit shape.

**GREEN:** Remove bypasses that call provider adapters directly.

**Checkpoint 6 regression:** Run tool registry, routing, pipeline, long-tail/OpenCode, outbound, and governance audit tests.

## Checkpoint 7: Confirmation, Dedupe, Quotas, And Audit

### Task 7.1: Bind confirmation to immutable draft content

**Files:**

- Modify: `runtime_api/app/assistant_identity/outbound.py`
- Modify: schema/repository as needed
- Modify: `runtime_api/tests/test_assistant_outbound_pipeline.py`

**RED:** Require confirmation to bind draft id, identity, recipient, subject, body hash, actor, and expiry. Editing any protected field invalidates it.

**GREEN:** Implement persisted confirmation records or equivalent signed server-side state.

### Task 7.2: Enforce idempotency and quotas

**Files:**

- Modify: outbound/tool gateway/policy modules
- Add focused tests

**RED:** Test duplicate OpenCode calls, duplicate taps, provider timeout retries, near-duplicate body detection, per-contact quota, per-channel quota, and daily quota.

**GREEN:** Add database uniqueness/idempotency handling and policy results with actionable reasons.

### Task 7.3: Append complete audit trace

**Files:**

- Modify: governance audit integration
- Add assistant identity audit tests

**RED:** Require every configure, verify, reconnect, disable, draft, edit, confirm, send, receipt, failure, and blocked direct-tool attempt to have trace id, actor, identity, policy result, and redacted provider result.

**Checkpoint 7 regression:** Run assistant identity plus governance, duplicate suppression, suggestions, and pipeline tests.

## Checkpoint 8: Web Assistant Identity UI

### Task 8.1: Add first-level navigation and identity overview

**Files:**

- Modify: `runtime_api/app/static/index.html`
- Modify: `runtime_api/app/static/app.js`
- Modify: `runtime_api/app/static/styles.css`
- Create or modify: static UI tests

**RED:** Add tests requiring:

- first-level `助理身份` navigation separate from `账号`;
- identity view with the Gmail row;
- actual address/status/last verification rendering;
- no placeholder address shown as connected;
- no secret values rendered or retained;
- responsive layout with no horizontal overflow.

**GREEN:** Build compact operational view and wire read APIs.

**Visual verification:** Use browser screenshots at desktop and mobile widths. Check navigation placement, long addresses, error states, secret inputs, and no card nesting.

### Task 8.2: Implement Gmail connection flow

**Files:** Same Web files plus callback route handling tests.

**RED:** Test connect, pending, callback success/failure, reconnect, verify, disable, and disconnect states.

**GREEN:** Open the Connect Link and restore the assistant identity view after callback.

### Task 8.3: Add inbox, pending drafts, send history, and policies

**RED:** Test that Web and API states match, confirmation updates the same draft, and provider failures remain visible.

**Checkpoint 8:** Run static UI tests, API tests, browser interaction checks, and screenshots.

## Checkpoint 9: Android Full-App UI

### Task 9.1: Add assistant identity API models and destination

**Files:**

- Modify: `android_app/app/src/main/java/com/par/assistant/android/AssistantApiClient.java`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/AssistantIdentity.java`
- Modify: Android full-app navigation/view files
- Add or modify Android unit tests

**RED:** Require real lifecycle fields, capabilities, last verification, errors, and version parsing. Require a full-app `助理身份` destination separate from user account connections.

**GREEN:** Implement shared server-backed identity overview.

### Task 9.2: Add provider setup actions and callback return

**RED:** Test Gmail connect/reconnect return to the identity page, back navigation, error recovery, and no local token persistence.

**GREEN:** Implement full-app provider flows. Keep credential forms out of the floating panel.

### Task 9.3: Share confirmation cards between floating and full chat

**RED:** Test the same draft id/state appears in both surfaces and only one send occurs after repeated taps.

**GREEN:** Reuse server-side draft history and state refresh.

**Checkpoint 9:** Run Android unit tests, build APK, install on device, verify navigation/input/back/rotation/keyboard, and inspect screenshots.

## Checkpoint 10: End-To-End Regression

### Task 10.1: Local semantic regression

**Files:**

- Create: `runtime_api/scripts/assistant-identity-configuration-regression.py`
- Create: local regression report

Validate stage outputs for:

- unconfigured identities;
- truthful mocked provider verification;
- separate user/assistant Gmail connections;
- OpenCode draft-only behavior;
- deterministic pipeline draft behavior;
- confirmation binding;
- duplicate suppression;
- restart persistence;
- inbound classification and memory scope;
- redacted audit.

### Task 10.2: Cloud deployment regression

Deploy only after local suites pass. Verify:

- schema migration;
- secret master key mounted and stable across restart;
- Web `助理身份` page loads;
- API does not expose secrets;
- workers remain healthy;
- restart preserves identity rows and drafts.

### Task 10.3: Real Gmail acceptance

Requires user OAuth participation.

1. Connect a dedicated Nomi Gmail account.
2. Verify actual provider-derived address.
3. Send a real inbound email from another account.
4. Inspect normalized event, memory scope, suggestion, and inbox UI.
5. Ask a deterministic request to reply and inspect the draft.
6. Ask an open-ended OpenCode task that needs an email and inspect its draft-only result.
7. Confirm one real send and verify provider message id and received email.
8. Restart and verify lifecycle state.

### Task 10.4: Final gap audit

Compare actual code and live evidence against every acceptance criterion in the design. Update the gap report with:

- completed items and evidence;
- incomplete provider behavior;
- untested failure modes;
- any fake-only coverage;
- exact next action and owner.

No item may be marked complete solely because a unit test or endpoint returned success.

## Final Regression Commands

Run focused suites first, then broader regression:

```bash
pytest -q runtime_api/tests/test_assistant_identity_*.py
pytest -q runtime_api/tests/test_assistant_gmail_adapter.py
pytest -q runtime_api/tests/test_assistant_outbound_pipeline.py runtime_api/tests/test_assistant_trigger_routing.py
pytest -q runtime_api/tests/test_tool_registry.py runtime_api/tests/test_opencode_artifact_worker.py
pytest -q runtime_api/tests/test_static_workbench_agenda_tab.py runtime_api/tests/test_static_web_search_settings.py
gradle -p android_app :app:testDebugUnitTest :app:assembleDebug
```

Run repository-wide tests appropriate to the changed blast radius before deployment.

## Delivery Definition

The feature is delivered only when:

1. persistent configuration survives restart;
2. Web and Android expose the assistant identity flows;
3. identity health is provider-derived;
4. secrets are protected and redacted;
5. OpenCode cannot send directly;
6. deterministic pipelines and OpenCode share the same draft gateway;
7. confirmation, dedupe, quotas, and audit are enforced;
8. a real dedicated Gmail account passes live inbound and outbound acceptance;
9. remaining gaps are explicitly documented.
