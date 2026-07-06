# Open Task Artifact Gap Report

Date: 2026-07-06

## Implemented

- Artifact task routing: requests such as `帮我依据刚刚王总给的资料，写一份 PPT` are classified as `artifact_creation` instead of ordinary chat.
- Scoped evidence planning: the first version extracts an entity hint such as `王总`, requests recent message/attachment/memory context, and records missing inputs such as PPT purpose, target audience, and expected page count.
- Evidence pack: source and memory context items are converted into traceable evidence items with `evidence_id`, source, actor, excerpt, confidence, and relevance reason.
- Task persistence: `/api/chat` now creates a `task_runs` record, initializes ordered `task_steps`, and stores explicit `task_evidence_links`.
- Chat handoff: artifact requests return a user-visible task response and task metadata without calling the normal model chat path.
- Task APIs:
  - `GET /api/tasks/{task_id}` returns task state, steps, and evidence links.
  - `GET /api/tasks/{task_id}/artifacts` returns the artifact list, currently empty for planning tasks.
- Regression coverage:
  - Artifact router and evidence pack tests.
  - Task schema and in-memory task factory tests.
  - `/api/chat` artifact handoff test proving the normal model gateway is not called.
  - Task detail and artifact list API tests.

## Remaining Gaps

- Real artifact generation is not implemented yet. The task can be created and tracked, but it does not currently produce a `.pptx`, `.docx`, `.xlsx`, or `.md` file.
- Slide/document verifier is not implemented yet. There is no per-slide or per-section evidence audit, hallucination check, layout validation, or final quality score.
- Attachment retrieval is not complete. The planner asks for attachments, but no worker currently fetches WhatsApp/Telegram/Gmail attachments into the artifact task.
- OpenCode/OpenClaw execution is not connected to artifact generation. The task shell does not yet delegate to a controlled file-generation worker.
- Android artifact card is not implemented. The chat response includes task metadata, but the mobile floating UI does not yet render a dedicated task card with progress and download actions.
- Web task detail page is not implemented. APIs exist, but there is no polished task detail UI for inspecting steps/evidence/artifacts.
- Download endpoint is not implemented. `GET /api/tasks/{task_id}/artifacts` lists artifact metadata, but there is not yet a `GET /api/artifacts/{artifact_id}/download` route.
- Real-source end-to-end validation is still pending. Tests use controlled evidence fixtures; a real WhatsApp/Gmail/Telegram source-to-artifact workflow has not been run.
- Worker lifecycle is pending. Steps are initialized, but there is no dedicated artifact worker that advances `interpret_request -> gather_evidence -> outline -> draft -> generate_artifact -> verify -> deliver`.

## Next Recommended Slice

1. Implement the artifact worker for `outline` only, producing a structured outline JSON with evidence references.
2. Add a task detail UI card in Android/Web that shows status, source evidence count, and missing inputs.
3. Implement PPTX generation after outline verification passes.
4. Add artifact download API only after a real file is produced and verified.
