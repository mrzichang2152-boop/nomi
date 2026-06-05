# 2026-06-04 Assistant Owned Identities Regression

**Feature:** Nomi-owned Gmail and WhatsApp identities
**Script:** `scripts/assistant-identity-regression.py`
**Environment:** Local in-process FastAPI `TestClient`, `DATABASE_URL=postgresql://test`, `REDIS_URL=redis://test`
**Result:** 8 / 8 semantic checks passed

## Cases

| Case | Result | Semantic judgment |
| --- | --- | --- |
| AI-ID-001 | Passed | Default `nomi_gmail_primary` and `nomi_whatsapp_primary` identities are listed with receive/send capabilities and configured status. |
| AI-GM-001 | Passed | Email from the owner to Nomi normalizes as `assistant_gmail`, `user_direct_command`, `assistant_identity_thread`, and keeps the Gmail thread/message IDs. |
| AI-WA-001 | Passed | WhatsApp message from the owner to Nomi normalizes as `assistant_whatsapp`, `user_direct_command`, and keeps a separate WhatsApp conversation scope. |
| AI-EXT-001 | Passed | WhatsApp message from known external contact normalizes as `external_contact_message`, uses `assistant_channel_external_contact`, and does not create an outbound reply. |
| AI-DRAFT-001 | Passed | Third-party outbound creates a draft card with `send/edit/cancel`, blocks empty confirmation, and only marks sent after explicit confirmation. |
| AI-SCOPE-001 | Passed | Assistant-owned private payload keeps `assistant_identity_id`, classification, conversation ID, external message ID, counterparty scope, and normalized text. |
| AI-ROUTE-001 | Passed | Explicit Nomi WhatsApp send request routes to deterministic `reply_pipeline`, not agent, with confirmation required. |
| AI-ROUTE-002 | Passed | Long-tail communication task may use agent planning, but agent is restricted to `assistant.outbound.create_draft` and forbidden provider send tools. |

## Important Observations

- The normalized assistant-owned events are intentionally distinct from user-owned `gmail` and `whatsapp` collector events.
- The external-contact path stores/surfaces the message but does not auto-reply.
- The outbound path is confirmation-first. Local fake send marks `send_called=true` only after a non-empty confirmation token.
- The long-tail route correctly avoids giving the agent direct Gmail/WhatsApp provider send tools.

## Open Provider Gaps

- Real Nomi Gmail watch/send was not validated because live Nomi Gmail credentials were not available in this session.
- Real WhatsApp Cloud API webhook/send was not validated because Meta app, phone-number ID, and production access token were not available in this session.
- Android live device validation for the new Nomi identity/draft rows remains open; current validation is unit-test level.
