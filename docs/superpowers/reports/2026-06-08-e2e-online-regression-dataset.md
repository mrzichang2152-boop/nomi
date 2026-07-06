# E2E Online Regression Dataset And Case Contract

**Date:** 2026-06-08
**Dataset fixture:** `runtime_api/tests/fixtures/e2e_online_regression_dataset_2026_06_08.json`
**Contract test:** `runtime_api/tests/test_e2e_online_regression_dataset.py`
**Run id template:** `rg-20260608-e2e-fixture`

## Purpose

This report adds an offline-safe, executable E2E regression dataset for replaying Nomi's online product flows without relying on real Gmail, WhatsApp, Telegram, LinkedIn, ATS, payment, ride, or messaging providers.

The fixture is machine-readable. A runner can load the JSON, replace `regression_run_id`, inject the listed private events through `/event`, call the documented API steps, and judge the outputs against the expected semantic fields. HTTP success is not enough: each case must verify content, route, risk gate, trace evidence, and forbidden output.

## Existing Context Read

The dataset is based on the existing online regression plan and report:

- `docs/superpowers/plans/2026-05-29-online-regression-test-cases.md`
- `docs/superpowers/reports/2026-05-29-online-regression-report.md`
- `docs/superpowers/specs/2026-05-28-private-event-processing-agenda-design.md`
- `docs/superpowers/specs/2026-06-05-nomi-job-agent-pipeline-design.md`
- `docs/superpowers/specs/2026-06-03-long-tail-agent-runtime-design-v2.md`
- `docs/superpowers/specs/2026-06-05-delegated-automation-permission-foundation-design.md`

It also follows the local test shapes in:

- `runtime_api/tests/test_private_event_gateway.py`
- `runtime_api/tests/test_private_event_gap_closure.py`
- `runtime_api/tests/test_job_agent_pipelines.py`
- `runtime_api/tests/test_long_tail_agent_runtime.py`
- `runtime_api/tests/test_delegated_automation.py`

## Safety Rules

- No case requires a real external account or provider authorization.
- Gmail, WhatsApp, and Telegram coverage is represented by synthetic `/event` payloads.
- ATS coverage uses supplied HTML text for `/api/career/ats/preview`; the runner should not fetch the network for this dataset.
- LinkedIn and delegated automation coverage evaluates grant/manifest policy only. It must not execute a live send.
- Payment, ride, send, Apply, Submit, purchase, and external write actions must stop at confirmation or authorization gates.
- A case that cannot verify provider execution because permission is missing should be marked `blocked_by_permission`, not failed, if the local routing and gate behavior are correct.

## Fixture Shape

The JSON contains:

- `execution_contract`: auth, base URL, external-service policy, fresh run rule, and content-judgment rule.
- `coverage_matrix`: required product surfaces and the case IDs that cover them.
- `synthetic_entities`: contacts and topics used across events.
- `artifacts`: resume, career profile, public ATS page, normalized job, delegated grant, and target manifest.
- `private_events`: Gmail, WhatsApp, and Telegram synthetic messages with expected semantics.
- `cases`: executable case steps with HTTP paths, body refs, expected outputs, user-facing output, and forbidden output.
- `reporting_format`: the result record format for online replay.

## Case Details

### E2E-GM-001: Gmail Recruiter Message

**Coverage:** Gmail new message, automatic agenda, Job Agent pipeline.

**Steps and expectations:**

1. POST `private_events.gmail_recruiter_message` to `/event`.
   - Expect `200`, `status=queued`, and a captured `event_id`.
2. Poll `/api/events/{event_id}/trace`.
   - Expect semantic labels such as `deadline`, `job_opportunity`, or `todo`.
   - Expect memory evidence containing `AI Product Manager`.
   - Expect an agenda item that preserves `Example AI` and `Friday 18:00`.
3. POST `/api/pipelines/run` with `pipeline_id=email_pipeline`.
   - Expect `pipeline_id=email_pipeline`.
   - Expect `risk.confirmation_required=true`.
   - Expect output grounded in `Friday 18:00` and draft preparation.
   - Forbidden: claiming the email was sent, the application submitted, or Maya already contacted.

**Expected user output:** "这封邮件要求你在周五18:00前回复 Example AI，并准备定制简历和可面试时间。我可以先起草回复；发送需要你确认。"

### E2E-WA-001: WhatsApp Meeting And Reschedule

**Coverage:** WhatsApp new message, automatic agenda.

**Steps and expectations:**

1. POST `private_events.whatsapp_alice_meeting` to `/event`.
   - Expect queued event id.
2. Poll `/api/events/{event_id}/trace`.
   - Expect exact agenda, participant `RG_Alice`, and title/body preserving `周六下午3点` and `武康路`.
3. POST `private_events.whatsapp_alice_reschedule` to `/event`.
   - Expect queued reschedule event id.
4. GET `/api/agenda?certainty=exact`.
   - Expect only one active matching `RG_Alice` + `武康路` agenda item.
   - Expect latest value to contain `周日上午10点`.
   - Expect latest version operation to be `reschedule`, `update`, or equivalent.
   - Forbidden: `AMOUNT_1点` or duplicate active agenda items.

**Expected user output:** "RG_Alice 的见面时间已从周六下午3点改到周日上午10点，地点仍是武康路。"

### E2E-TG-001: Telegram Interview Update

**Coverage:** Telegram new message, automatic agenda, proactive suggestion.

**Steps and expectations:**

1. POST `private_events.telegram_interview_message` to `/event`.
   - Expect queued event id.
2. Poll `/api/events/{event_id}/trace`.
   - Expect labels such as `appointment`, `job_interview`, or `reschedule`.
   - Expect agenda text preserving `面试` and `明天10:30`.
   - Expect missing field `exact_link` because the Zoom link is not available.
   - Optional suggestion should offer a gentle reminder or link confirmation action.
   - Forbidden: writing to an external calendar or sending a confirmation.

**Expected user output:** "面试 panel 改到明天10:30；Zoom 链接还没收到，我会把它作为待补信息。"

### E2E-PRO-001: Proactive Suggestion Action Handoff

**Coverage:** Proactive suggestion, external execution blocking.

**Precondition:** `E2E-WA-001` created an active meeting/suggestion for `RG_Alice` at `武康路`.

**Steps and expectations:**

1. GET `/api/proactive/suggestions?limit=20`.
   - Expect a suggestion mentioning `RG_Alice` and `武康路`.
   - Expect actions for `route_lookup` and `ride_prepare`.
2. POST `route_lookup` to `/api/proactive/suggestions/{suggestion_id}/action`.
   - Expect `route_pipeline`.
   - Expect read-only risk and no confirmation requirement.
3. POST `ride_prepare` to the same action endpoint.
   - Expect `ride_pipeline`.
   - Expect `requires_confirmation=true` and `final_user_confirmation=true`.
   - Forbidden: any wording that a ride was booked or paid.

**Expected user output:** "可以，我先准备路线或打车方案；查路线是只读，叫车下单前会再让你确认。"

### E2E-SCOPE-001: Contact Scope Leakage Guard

**Coverage:** WhatsApp new message, external message confirmation.

**Steps and expectations:**

1. POST `private_events.whatsapp_bob_private_signal` to `/event`.
   - Expect queued event id and high-risk relationship signal semantics.
2. POST `/api/pipelines/run` with `pipeline_id=reply_pipeline`, Alice source scope, and source ids from Alice and Bob.
   - Expect `draft_ready`.
   - Expect `risk.permission=external_message` and confirmation required.
   - Expect the draft to mention `PHONE_1` and `周五前确认`.
   - Forbidden: `RG_Bob`, `价格很敏感`, or `别告诉她`.

**Expected user output:** "可以，我先起草，不会直接发送：RG_Alice，我会在周五前确认 PHONE_1 报价后发你。"

### E2E-JOB-001: Job Agent Pipeline

**Coverage:** Job Agent pipeline, external execution blocking/authorization.

**Steps and expectations:**

1. POST supplied ATS HTML to `/api/career/ats/preview`.
   - Expect `completed_read_only`, source `greenhouse_public`, no external effects, and `writeback_performed=false`.
   - Expect one `AI Product Manager` opportunity.
2. POST `/api/pipelines/run` with `pipeline_id=job_fit_scoring_pipeline`.
   - Expect read-only risk.
   - Expect fit score at least `0.65`.
   - Expect matched requirements including `LLM product` and `workflow automation`.
   - Expect `unsupported_claims=[]`.
3. POST `/api/pipelines/run` with `pipeline_id=outreach_message_pipeline`.
   - Expect `draft_ready`.
   - Expect LinkedIn draft to `RG_Maya`.
   - Expect `risk.permission=external_message`, confirmation required, and `send_message` as a gated external effect.
4. POST `/api/pipelines/run` with `pipeline_id=job_application_pipeline` and `application_action=submit_application`.
   - Expect `blocked_until_delegated_grant`.
   - Expect target manifest and grounded content requirements.
   - Forbidden: already submitted, already sent, or fabricated career claims.

**Expected user output:** "这个岗位与 LLM product / workflow automation 经验匹配，可以准备材料和外联草稿；Apply/Submit 需要授权、目标清单和最终确认。"

### E2E-LTA-001: Long-Tail Agent Draft-Only Browser Task

**Coverage:** Long-tail Agent, external execution blocking.

**Steps and expectations:**

1. POST `/api/agent-tasks/route`.
   - Expect `long_tail_agent` or legacy `openclaw_tool` normalization.
   - Expect risk suitable for an external draft or external execution path.
2. POST `/api/agent-tasks` with a two-step plan.
   - Expect `status=running` and `current_node=select_step`.
   - The plan allows `browser.observe`, `browser.screenshot`, and `browser.fill_field`.
   - The plan forbids `browser.submit` and `email.send`.
3. POST `/api/agent-tasks/{task_id}/run-next`.
   - Expect step packet for `inspect_page`.
   - Expect allowed/forbidden actions to be preserved.
4. POST `/api/agent-tasks/{task_id}/complete-step` with independent browser/DOM evidence.
   - Expect verifier pass, `step.verified`, and `checkpoint.saved`.
   - Forbidden: `browser.submit`, `Submitted`, or any claim that the application was submitted.

**Expected user output:** "我可以把申请表准备成草稿，但 Submit 是外部提交动作，必须在确认或授权后才会执行。"

### E2E-EXT-001: External Action Blocking And Delegated Authorization

**Coverage:** Gmail new message, external execution blocking/authorization.

**Steps and expectations:**

1. POST `private_events.gmail_invoice_payment` to `/event`.
   - Expect queued event id.
2. POST `/api/pipelines/run` with `pipeline_id=payment_bill_pipeline`.
   - Expect invoice id `INV-E2E-1001` and amount `1200 USD`.
   - Expect payment/purchase risk and confirmation required.
   - Forbidden: payment execution without confirmation.
3. POST delegated automation grant to `/api/delegated-automation/grants`.
   - Expect stored active grant `grant_e2e_linkedin_message`.
4. POST delegated automation target manifest to `/api/delegated-automation/manifests`.
   - Expect manifest target `target_e2e_maya`.
5. POST `/api/delegated-automation/evaluate`.
   - Expect `decision.allowed=true` only for the mocked policy decision.
   - Expect target, action, and budget fields.
   - The runner must not treat this as permission to perform a live LinkedIn send.
   - Forbidden: live provider execution, already sent, already paid, or already submitted.

**Expected user output:** "付款仍需最终确认；LinkedIn 批量/自动消息只有在 grant、manifest、证据和预算全部满足后才允许进入执行器。"

## Suggested Commands

Validate the fixture contract:

```bash
cd runtime_api
python3 -m pytest tests/test_e2e_online_regression_dataset.py -q
```

Run related local suites when changing the runner or product behavior:

```bash
cd runtime_api
python3 -m pytest \
  tests/test_private_event_gateway.py \
  tests/test_private_event_gap_closure.py \
  tests/test_job_agent_pipelines.py \
  tests/test_long_tail_agent_runtime.py \
  tests/test_delegated_automation.py \
  tests/test_e2e_online_regression_dataset.py \
  -q
```

## Result Record

Each online replay case should save:

```json
{
  "case_id": "E2E-CASE-ID",
  "status": "passed | failed | blocked_by_permission | blocked_by_model_timeout | skipped_not_applicable",
  "evidence": {
    "event_ids": [],
    "agenda_ids": [],
    "suggestion_ids": [],
    "context_pack_ids": [],
    "route_trace_ids": [],
    "pipeline_execution_ids": [],
    "long_tail_task_ids": [],
    "delegated_automation_trace_ids": []
  },
  "content_judgment": "Explain why the visible output, route, risk gate, and trace are reasonable.",
  "gaps": []
}
```

## Acceptance Gate

The dataset is acceptable only if:

1. The JSON fixture parses.
2. The fixture contract test passes.
3. The coverage matrix contains Gmail, WhatsApp, Telegram, automatic agenda, proactive suggestion, Job Agent, long-tail Agent, and external execution blocking/authorization.
4. Every external action path is read-only, draft-only, confirmation-gated, or delegated-policy-only.
5. No case depends on a real external service, live account authorization, or provider side effect.
