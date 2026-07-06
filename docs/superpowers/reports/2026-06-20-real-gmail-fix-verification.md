# 2026-06-20 Real Gmail Fix Verification

## Scope

This report records the fixes and verification for the real Gmail E2E issues found after the user sent a test email.

## Fixed Issues

### 1. Gmail payload object-string pollution

Problem:
- Composio can return `preview` as an object with `subject` and `body`.
- The runtime previously converted non-string values with `str(value)`, producing strings such as `{'body': '...', 'subject': '...'}`.
- That polluted raw event payloads, agenda titles, proactive suggestion copy, and chat context.

Fix:
- Added `gmail_text_field(...)` to flatten string/list/dict text fields safely.
- `gmail_message_payload_from_composio(...)` now extracts `subject`, `body`, and `snippet` from nested preview/content fields without serializing dictionaries into user-visible text.

Verification:
- Local regression: `test_gmail_composio_fetch_flattens_preview_objects_before_persisting`.
- Online real Gmail fetch wrote event `42097acb-3ef4-465b-aa8b-085c718f1a81`.
- Stored event payload:
  - subject: `明天下午4点人民广场见`
  - body: `请明天下午4点在人民广场见面，带合同。`
  - snippet: `请明天下午4点在人民广场见面，带合同。`
- No `{'body'` object-string residue in event, agenda, or suggestion payload.

### 2. Exact agenda parsing should not call model

Problem:
- Worker rules already parsed exact date/time/place, but hybrid agenda parsing still called the model.
- In real validation this produced `model_parse_failed:ReadTimeout` warnings even when the rule result was already correct.

Fix:
- Added a rules-first fast path for complete exact agenda candidates.
- The fast path is only used when:
  - certainty is `exact`
  - exact time and start timestamp exist
  - appointment has a place
  - no missing fields
  - no clarification needed
  - confidence is at least `0.5`

Verification:
- Local regression: `test_hybrid_agenda_uses_rules_fast_path_for_complete_exact_candidate`.
- Online agenda for the real Gmail event:
  - parser_mode: `rules_first_exact`
  - time: `2026-06-21T16:00:00+08:00`
  - display: `2026-06-21 周日 16:00`
  - place: `人民广场`
  - validation_warnings: `[]`

### 3. Chat context missed agenda items for Gmail schedule questions

Problem:
- `/api/chat` could retrieve memory but miss agenda context for queries like “刚才 Gmail 里的人民广场日程”.
- Chinese text was tokenized too coarsely, so `人民广场` was not matched as a standalone agenda token.

Fix:
- Agenda matching now directly matches exact `place` substrings.
- If a query mentions a known source such as Gmail/WhatsApp/Telegram and uses agenda-like language, relevant agenda items from that source can be included.

Verification:
- Local regression: `test_agenda_item_matches_query_by_place_and_source_reference`.
- Online `/api/chat` query:
  - prompt: `请用一句话回复：你现在能读取刚才Gmail里的人民广场日程吗？`
  - answer: `能，我已读取到明天下午4点在人民广场与张子长见面的日程。`
  - agenda_context_count: `3`
  - total latency: about `7.18s`
  - model latency: about `5.9s`
  - parallel context retrieval latency: about `0.86s`

## Tests Run

```bash
python3 -m pytest \
  runtime_api/tests/test_auth_and_model.py::test_gmail_composio_fetch_flattens_preview_objects_before_persisting \
  runtime_api/tests/test_auth_and_model.py::test_gmail_composio_fetch_persists_messages_as_collector_events \
  runtime_api/tests/test_context_pack_and_chat.py::test_agenda_item_matches_query_by_place_and_source_reference \
  runtime_api/tests/test_context_pack_and_chat.py::test_retrieve_active_agenda_context_uses_wide_candidate_window_before_rerank \
  runtime_api/tests/test_chat_router.py \
  worker/tests/test_worker_semantics.py \
  -q
```

Result: `93 passed`.

## Online Deployment

Deployed to `206.119.171.141`:
- `/opt/nomi/runtime_api/app/main.py`
- `/opt/nomi/worker/app/worker.py`

Services rebuilt/restarted:
- `runtime-api`
- `worker`

Health:
- `GET /health` returned `{"status":"ok"}`.

## Remaining Notes

- `/api/chat` did not timeout during this run.
- The measured bottleneck is still model generation time, not database/context retrieval.
- There are duplicate agenda contexts because repeated real Gmail fetches persisted duplicate events for the same message. This is not part of this fix, but Gmail fetch deduplication should be handled separately.
