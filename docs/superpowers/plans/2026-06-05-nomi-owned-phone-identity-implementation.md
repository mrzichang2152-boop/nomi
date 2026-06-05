# Nomi Owned Phone Identity V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Nomi-owned phone identity that can receive SMS, send confirmed SMS, and place confirmed one-way playback calls.

**Architecture:** Extend the existing `assistant_identity` layer used by Nomi Gmail and WhatsApp. Reuse identity registry, inbox normalization, scoped private-event payloads, outbound draft confirmation, trigger routing, API endpoints, Android identity UI, and semantic regression. Provider integrations are adapter-based with fake/local providers for V1 regression; live Twilio/Telnyx validation remains a tracked gap until credentials are available.

**Tech Stack:** FastAPI, Python dataclasses/protocols, pytest, Android Java model/client/UI tests, existing Nomi runtime APIs.

---

## Design Source

Implement against:

- `docs/superpowers/specs/2026-06-05-nomi-owned-phone-identity-design.md`
- `docs/superpowers/specs/2026-06-04-nomi-owned-communication-identities-design.md`

## File Map

### Server Files

- Modify: `runtime_api/app/assistant_identity/registry.py`
- Modify: `runtime_api/app/assistant_identity/inbox_gateway.py`
- Modify: `runtime_api/app/assistant_identity/adapters.py`
- Create: `runtime_api/app/assistant_identity/phone_adapter.py`
- Modify: `runtime_api/app/assistant_identity/outbound.py`
- Modify: `runtime_api/app/assistant_identity/routing.py`
- Modify: `runtime_api/app/private_events.py`
- Modify: `runtime_api/app/tool_registry.py`
- Modify: `runtime_api/app/main.py`
- Modify: `.env.example`

### Android Files

- Modify: `android_app/app/src/main/java/com/par/assistant/android/AssistantIdentity.java`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/AssistantDraft.java`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/AssistantApiClient.java`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/FloatingBallService.java`

### Test And Report Files

- Modify: `runtime_api/tests/test_assistant_identity_registry.py`
- Modify: `runtime_api/tests/test_assistant_inbox_gateway.py`
- Modify: `runtime_api/tests/test_assistant_identity_adapters.py`
- Create: `runtime_api/tests/test_assistant_phone_adapter.py`
- Modify: `runtime_api/tests/test_assistant_outbound_pipeline.py`
- Modify: `runtime_api/tests/test_assistant_trigger_routing.py`
- Modify: `runtime_api/tests/test_assistant_identity_memory_scope.py`
- Modify: `runtime_api/tests/test_assistant_identity_api.py`
- Modify: `runtime_api/tests/test_tool_registry.py`
- Modify: `android_app/app/src/test/java/com/par/assistant/android/AssistantIdentityUiTest.java`
- Modify: `android_app/app/src/test/java/com/par/assistant/android/AssistantApiClientTest.java`
- Modify: `scripts/assistant-identity-regression.py`
- Modify: `docs/superpowers/reports/2026-06-04-nomi-owned-communication-identities-gaps.md`
- Create: `docs/superpowers/reports/2026-06-05-nomi-owned-phone-identity-regression.md`

## Task 1: Identity Registry

- [ ] Write failing tests that default identities include `nomi_phone_primary`, `assistant_phone` can connect, and unsupported kinds still fail.
- [ ] Run `python3 -m pytest tests/test_assistant_identity_registry.py tests/test_assistant_identity_api.py -q` and verify failures mention missing phone identity/kind.
- [ ] Add `assistant_phone` to allowed kinds and bootstrap `nomi_phone_primary` with `receive_sms`, `send_sms`, `outbound_call_playback`, `inbound_call_greeting`, `delivery_receipt`, and `call_status`.
- [ ] Add `.env.example` values for `ASSISTANT_PHONE_NUMBER`, `ASSISTANT_PHONE_STATUS`, `ASSISTANT_PHONE_WEBHOOK_TOKEN`, and optional provider account values.
- [ ] Re-run the registry/API tests and verify phone identity output is semantically correct.

## Task 2: Inbound SMS And Call Normalization

- [ ] Write failing tests for `AssistantInboxGateway.normalize_sms` and `normalize_phone_call`.
- [ ] Verify SMS from owner becomes `user_direct_command`, SMS from known contact becomes `external_contact_message`, inbound call becomes `provider_status` or auditable `assistant_inbound_call_received`.
- [ ] Implement `normalize_sms` and `normalize_phone_call` with `source_type="assistant_phone"`, `identity_id="nomi_phone_primary"`, `sms:` / `phone:` conversation scopes, redacted/hash sender data, suggestion channels, and memory scope.
- [ ] Add `assistant_phone` to private-event source handling.
- [ ] Add tests that `normalized_assistant_event_to_private_payload` preserves phone identity, classification, call/SMS status, and conversation ID.
- [ ] Re-run inbox and memory-scope tests.

## Task 3: Phone Provider Adapter Contracts

- [ ] Write failing tests for `AssistantSmsAdapter`, `AssistantPhoneCallAdapter`, `FakeAssistantSmsAdapter`, `FakeAssistantPhoneCallAdapter`, and `PhoneCallInstructionBuilder`.
- [ ] Implement protocol contracts in `adapters.py`.
- [ ] Create `phone_adapter.py` with fake SMS send, fake playback call creation, webhook-token verifier, one-way script validator, duration estimator, and provider instruction builder.
- [ ] Verify fake adapters record local sends/calls and reject empty/unsupported one-way call scripts.

## Task 4: Outbound SMS And Playback Call Drafts

- [ ] Write failing tests that `prepare_draft(channel="sms")` creates `assistant_sms_confirmation` with `send/edit/cancel`.
- [ ] Write failing tests that `prepare_draft(channel="phone_call")` creates `assistant_call_playback_confirmation` with `call/edit/cancel`, estimated duration, and V1 limitation text.
- [ ] Write failing tests that empty confirmation blocks SMS send/call, and confirmed call uses separate call action state.
- [ ] Extend `OutboundMessagePipeline` to choose confirmation card type/actions by channel and add `confirm_and_call`.
- [ ] Preserve generic `confirm_and_send` for SMS/email/WhatsApp and return provider-shaped local audit fields.
- [ ] Re-run outbound tests.

## Task 5: Routing And Tool Registry

- [ ] Write failing tests that explicit SMS request routes to `assistant.sms.send`.
- [ ] Write failing tests that explicit call request routes to `assistant.phone.call_playback`.
- [ ] Write failing tests that long-tail phone task can only use `assistant.outbound.create_draft` and provider SMS/call tools are forbidden.
- [ ] Extend `AssistantCommunicationTriggerRouter` channel/capability detection for `sms`, `短信`, `phone_call`, `打电话`, `电话通知`.
- [ ] Register `assistant.sms.send` and `assistant.phone.call_playback` in `tool_registry.py`.
- [ ] Re-run routing and registry tests.

## Task 6: API Endpoints

- [ ] Write failing API tests for:
  - `POST /api/assistant-inbox/phone/sms/webhook`
  - `POST /api/assistant-inbox/phone/sms/status`
  - `POST /api/assistant-inbox/phone/calls/inbound`
  - `POST /api/assistant-inbox/phone/calls/status`
  - `GET /api/assistant-inbox/phone/calls/{call_instruction_id}`
  - `POST /api/assistant-outbound/drafts/{draft_id}/call`
- [ ] Implement request models in `main.py`.
- [ ] Implement webhook token validation via `x-assistant-webhook-token`.
- [ ] Normalize inbound SMS/call/status events and append them to local assistant inbox events.
- [ ] Implement call instruction response for V1 one-way playback.
- [ ] Wire confirmed call continuation to `OutboundMessagePipeline.confirm_and_call`.
- [ ] Re-run API tests.

## Task 7: Android UI Models

- [ ] Write failing Android tests that `AssistantIdentity.subtitle()` labels `assistant_phone` as `Nomi Phone`.
- [ ] Write failing Android tests that SMS and call draft cards show correct action wording and V1 call limitation.
- [ ] Update Java models/client/UI row generation.
- [ ] Re-run targeted Android tests with JDK 17.

## Task 8: Semantic Regression And Gap Tracking

- [ ] Extend `scripts/assistant-identity-regression.py` with cases:
  - phone identity listed
  - inbound owner SMS becomes `user_direct_command`
  - inbound known-contact SMS does not auto-reply
  - inbound call produces greeting/status event
  - SMS draft blocks provider before confirmation
  - call draft blocks dialing before confirmation
  - confirmed call records provider call ID
  - long-tail phone task cannot call provider tools
- [ ] Run the regression script and inspect each observed output for semantic correctness.
- [ ] Create `docs/superpowers/reports/2026-06-05-nomi-owned-phone-identity-regression.md`.
- [ ] Update gap tracker with live provider validation gaps for Twilio/Telnyx SMS/calls and Android live device validation.

## Verification Commands

Run all of these before claiming completion:

```bash
cd /Users/wrf/Documents/background/runtime_api
python3 -m pytest -q

cd /Users/wrf/Documents/background
python3 scripts/assistant-identity-regression.py

cd /Users/wrf/Documents/background/android_app
JAVA_HOME=/opt/homebrew/opt/openjdk@17 gradle :app:testDebugUnitTest

cd /Users/wrf/Documents/background
git diff --check
```

## Expected Remaining Gaps

- Live Twilio/Telnyx SMS send and delivery callback validation requires provider credentials and a reachable webhook URL.
- Live Twilio/Telnyx call playback validation requires provider credentials, a phone number, and a reachable call instruction endpoint.
- Android live UI validation requires installing the app on a device/emulator after implementation.
