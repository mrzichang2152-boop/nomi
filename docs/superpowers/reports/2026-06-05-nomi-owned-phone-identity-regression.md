# 2026-06-05 Nomi Owned Phone Identity Regression

**Feature:** Nomi-owned phone identity V1
**Spec:** `docs/superpowers/specs/2026-06-05-nomi-owned-phone-identity-design.md`
**Plan:** `docs/superpowers/plans/2026-06-05-nomi-owned-phone-identity-implementation.md`
**Script:** `scripts/assistant-identity-regression.py`
**Environment:** Local in-process FastAPI `TestClient`, `DATABASE_URL=postgresql://test`, `REDIS_URL=redis://test`
**Result:** 13 / 13 semantic checks passed

## Cases

| Case | Result | Semantic judgment |
| --- | --- | --- |
| AI-ID-001 | Passed | Default identities include `nomi_gmail_primary`, `nomi_whatsapp_primary`, and `nomi_phone_primary`; the phone identity exposes SMS, call playback, inbound greeting, delivery receipt, and call status capabilities. |
| AI-GM-001 | Passed | Owner Gmail to Nomi remains a scoped `assistant_gmail` `user_direct_command`. |
| AI-WA-001 | Passed | Owner WhatsApp to Nomi remains a scoped `assistant_whatsapp` `user_direct_command`. |
| AI-EXT-001 | Passed | External WhatsApp message is surfaced and does not auto-send a reply. |
| AI-SMS-001 | Passed | External SMS to Nomi phone normalizes as `assistant_phone`, `assistant_sms_received`, `external_contact_message`, and does not create outbound messages. |
| AI-CALL-IN-001 | Passed | Inbound phone call records an auditable `assistant_inbound_call_received` event and returns a one-way TTS greeting instruction. |
| AI-DRAFT-001 | Passed | Email outbound still requires a confirmation draft before send. |
| AI-CALL-DRAFT-001 | Passed | Phone outbound creates a one-way playback confirmation card, blocks empty confirmation, and only queues the call after explicit confirmation. |
| AI-SCOPE-001 | Passed | WhatsApp assistant-owned private payload keeps identity and classification scope. |
| AI-SCOPE-PHONE-001 | Passed | Phone assistant-owned private payload keeps `nomi_phone_primary`, contact scope, external SMS ID, normalized text, and `assistant_identity_thread` visibility. |
| AI-ROUTE-001 | Passed | Explicit Nomi WhatsApp send remains deterministic and confirmation-gated. |
| AI-ROUTE-002 | Passed | Long-tail agent can only create an outbound draft and is forbidden from direct Gmail, WhatsApp, SMS, phone, and Twilio send/call tools. |
| AI-ROUTE-PHONE-001 | Passed | Explicit Nomi SMS and one-way call requests route to deterministic confirmation pipelines. |

## Semantic Observations

- `assistant_phone` is separate from user-owned phone/SMS state and from Nomi WhatsApp, so SMS context does not bleed into WhatsApp or Gmail threads.
- External SMS and inbound calls are stored/surfaced; neither path auto-texts nor auto-calls a third party.
- Outbound phone calls are V1 one-way playback only. The confirmation card includes the explicit limitation `电话只会播放这段语音，不会实时对话。`
- The local phone call result is still a fake/local queued provider result: `provider_call_id` starts with `local-call-`.

## Remaining Gaps

- Live Twilio/Telnyx/other phone provider credentials were not available, so real SMS delivery, real call creation, and real provider callbacks were not validated.
- No production call-instruction signing or hosted audio URL validation has been exercised against a real provider.
- Android live-device validation for the phone identity cards is still open; current Android coverage is unit-test level.
