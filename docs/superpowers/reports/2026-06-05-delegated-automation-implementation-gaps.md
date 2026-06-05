# Delegated Automation Permission Foundation Implementation Gaps

**Date:** 2026-06-05  
**Source spec:** `docs/superpowers/specs/2026-06-05-delegated-automation-permission-foundation-design.md`  
**Implementation plan:** `docs/superpowers/plans/2026-06-05-delegated-automation-permission-foundation-implementation.md`

## Completed In This Pass

- Backend model layer:
  - `DelegationGrant`
  - `TargetManifest`
  - `ManifestTarget`
  - `AutomationDecision`
  - `ExecutionTrace`
- Policy engine:
  - denies missing grant;
  - denies missing target manifest for L4/L5;
  - denies missing grounded evidence when required;
  - denies user-owned Gmail/WhatsApp automation surfaces in V1;
  - denies expired or paused grants;
  - stops on captcha, 2FA, login challenge, account security, suspicious activity, and blocked states;
  - stops duplicate targets;
  - enforces daily, manifest, batch, and cooldown limits;
  - returns explainable `reasons`, `stop_condition`, `budget`, and target details.
- Audit trace helper:
  - creates append-only trace payloads;
  - includes grant, manifest, target, action, evidence IDs, result summary, and budget after execution.
- Runtime API:
  - `POST /api/delegated-automation/grants`
  - `GET /api/delegated-automation/grants`
  - `POST /api/delegated-automation/manifests`
  - `POST /api/delegated-automation/evaluate`
  - `POST /api/delegated-automation/traces`
  - `POST /api/delegated-automation/grants/{grant_id}/pause`
  - All new endpoints require `x-par-password`.
- Schema DDL:
  - `delegated_automation_grants`
  - `delegated_automation_manifests`
  - `delegated_automation_traces`
- Tests:
  - grant/manifest/evidence gating;
  - successful grounded L4 decision;
  - quota, duplicate, and platform challenge denial;
  - user-owned Gmail/WhatsApp out-of-scope denial;
  - in-memory store pause and trace behavior;
  - API auth, evaluate, trace, and pause flow.

## Remaining Gaps

### Gap 1: Persistent Store Adapter

Current state: API uses an in-memory store even though DDL exists.

Needed next:

- Add a Postgres-backed store implementing the same methods as `InMemoryDelegatedAutomationStore`.
- Use the Postgres store in production when `DATABASE_URL != postgresql://test`.
- Preserve in-memory store for tests.
- Verify grant, manifest, trace, and pause survive runtime restart.

### Gap 2: Job Agent Pipeline Integration

Current state: the foundation is callable through API and pure functions, but Job Agent pipelines do not yet call it before proposing high-automation actions.

Needed next:

- When the Job Agent proposes `add_connection`, `send_message`, `click_apply`, `submit_application`, `batch_apply`, or `follow_up`, call `/api/delegated-automation/evaluate` or the policy engine.
- If denied, return a user-facing explanation and do not enqueue execution.
- If allowed, enqueue execution with the decision payload attached.
- Write the resulting trace after execution observation.

### Gap 3: Playwright / Browser Executor Adapter

Current state: no real LinkedIn or ATS browser action is executed by this foundation.

Needed next:

- Add an executor interface that accepts an allowed `AutomationDecision`.
- Implement no-op/simulated executor tests first.
- Implement Playwright executor only for allowlisted action/platform pairs.
- Stop immediately on challenge pages, URL mismatch, target mismatch, or unobservable outcomes.

### Gap 4: Workbench Permission Center UI

Current state: no user-facing permission center for grants, quotas, manifests, traces, pause, revoke, or limit editing.

Needed next:

- Add a settings/workbench page for active grants and today's budget.
- Add manifest review UI for targets, reasons, draft content, and quota impact.
- Add pause/revoke/edit controls.
- Add execution log replay/read view.

### Gap 5: Scenario Policy Registry

Current state: policy rules are embedded in code-level checks and do not yet have a separate platform/scenario policy registry.

Needed next:

- Store platform policies such as LinkedIn `send_message` allowed levels and required controls.
- Use the registry to reject unsupported action/platform/surface combinations.
- Add separate scenario policies for future dating and sales agents.

### Gap 6: Assistant-Owned Channel Reuse

Current state: Nomi-owned Gmail/WhatsApp/phone identities exist elsewhere, but this foundation is not yet wired to assistant-owned outbound channels.

Needed next:

- Add assistant-owned identity surface policies.
- Keep user-owned Gmail/WhatsApp blocked for delegated batch automation in V1.
- Allow Nomi-owned channels only under grant, manifest, quota, and trace.

## Verification Notes

Focused test command used during implementation:

```bash
cd runtime_api && python3 -m pytest tests/test_delegated_automation.py -q
```

Observed result:

```text
6 passed
```
