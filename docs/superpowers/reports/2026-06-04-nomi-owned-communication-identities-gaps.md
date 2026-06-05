# Nomi Owned Communication Identities Gap Tracker

**Feature:** Nomi-owned Gmail, WhatsApp, and phone identities
**Design:** `docs/superpowers/specs/2026-06-04-nomi-owned-communication-identities-design.md`
**Implementation plan:** `docs/superpowers/plans/2026-06-04-nomi-owned-communication-identities-implementation.md`
**Started:** 2026-06-04

## Working Rules

- Every code change must follow the design and implementation plan.
- Any incomplete behavior, mocked provider, missing live credential path, or semantic uncertainty must be recorded here.
- A task is not considered complete only because tests pass; the output shape and behavior must also be reasonable.

## Current Gaps

| Gap | Status | Notes |
| --- | --- | --- |
| Live Nomi Gmail provider send/watch validation | Open | Implementation will include adapter interfaces and fake/local validation first. Real Gmail account credentials are not available in this session. |
| Live Nomi WhatsApp Cloud API send/webhook validation | Open | Implementation will include webhook verification and fake/local send validation first. Meta app/phone-number credentials are not available in this session. |
| Live Nomi phone SMS provider validation | Open | V1 provider-neutral contracts, webhook token verification, local fake SMS send, and semantic regression are implemented. Real SMS delivery and delivery callbacks still require Twilio/Telnyx credentials and a public callback URL. |
| Live Nomi phone outbound call validation | Open | V1 one-way playback draft/confirmation flow and fake queued call result are implemented. Real call creation, signed call instruction URL, TTS/audio playback, and provider status callbacks still require a live provider setup. |
| Android live UI validation for Nomi identity/draft cards | Open | Unit tests can validate model/client text. Device validation requires a later install/run cycle. |
| Spec API surface wider than implementation plan Task 8 | Closed | Added and tested local endpoints for identity connect/update/health, Gmail sync, Gmail Pub/Sub notification intake, WhatsApp webhook intake, assistant inbox detail/list, and draft/send/cancel/list. |

## Completed Items

- Backend assistant identity schema and bootstrap are implemented and covered by schema tests.
- Backend default identity registry supports Nomi Gmail and Nomi WhatsApp, rejects non-assistant identity kinds, and preserves identity state across the API process.
- Assistant inbox gateway normalizes Nomi-owned Gmail and WhatsApp inbound messages into scoped assistant events with classification and suggestion channel metadata.
- Private event source handling recognizes `assistant_gmail` and `assistant_whatsapp` and scopes assistant-owned messages away from unrelated user-account threads.
- Assistant event to private-event payload helper preserves `assistant_identity_id`, classification, visibility scope, conversation ID, external message ID, counterparty scope, and normalized text before storage.
- Trigger routing sends known assistant-owned communication actions through deterministic pipelines, blocks third-party direct outbound by default, and restricts long-tail agent outbound to draft creation.
- Outbound draft pipeline creates confirmation cards, blocks empty confirmation sends, supports edit/cancel, and records fake/local sent results for regression validation.
- Gmail MIME builder and fake Gmail adapter validate base64url MIME output and local send audit shape.
- WhatsApp webhook verifier and fake WhatsApp adapter validate webhook token behavior and local send audit shape.
- Shared adapter contracts now exist in `runtime_api/app/assistant_identity/adapters.py`.
- Android client/model/UI unit tests cover assistant identity list parsing, Nomi-owned identity account rows, and local outbound draft card text.
- Local assistant-owned identity regression script and report were added. The script validated 8 semantic cases covering identity listing, Gmail/WhatsApp inbound classification, no auto-reply for external contacts, confirmation-only drafts, scoped private payloads, deterministic routing, and long-tail agent restrictions.
- Nomi phone identity is now bootstrapped as `nomi_phone_primary` with SMS receive/send, outbound call playback, inbound greeting, delivery receipt, and call status capabilities.
- Assistant inbox gateway normalizes external SMS and inbound call callbacks into `assistant_phone` scoped events.
- Private event source handling recognizes `assistant_phone` and preserves phone identity, contact scope, provider IDs, normalized text, and call status fields.
- Provider-neutral phone adapter contracts, fake SMS adapter, fake call adapter, phone webhook verifier, and one-way playback script validator are implemented and unit tested.
- Outbound drafts now support `assistant_sms_confirmation` and `assistant_call_playback_confirmation` cards. Phone calls require explicit confirmation before local queued call state is recorded.
- Trigger routing and tool registry now recognize `assistant.sms.send` and `assistant.phone.call_playback`; long-tail agents are forbidden from direct SMS/phone/Twilio provider send/call tools.
- API endpoints now cover phone SMS webhooks, inbound/status call webhooks, one-way call instruction retrieval, and confirmed outbound call queueing.
- Android unit tests now cover `Nomi Phone` identity rows and phone-call draft cards with V1 one-way playback wording.
- The assistant identity regression script now validates 13 semantic cases, including phone identity, SMS intake, inbound calls, call drafts, phone private-event scope, and phone routing.
