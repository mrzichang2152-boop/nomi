# Open Task Artifact Gap Report

Date: 2026-07-06
Last updated: 2026-07-07 19:36 CST

## Implemented

- Artifact task routing: requests such as `帮我依据刚刚王总给的资料，写一份 PPT` are classified as `artifact_creation` instead of ordinary chat.
- Scoped evidence planning: the first version extracts an entity hint such as `王总`, requests recent message/attachment/memory context, and records missing inputs such as PPT purpose, target audience, and expected page count.
- Evidence pack: source and memory context items are converted into traceable evidence items with `evidence_id`, source, actor, excerpt, confidence, and relevance reason.
- OpenCode handoff plan: artifact requests now build a generic `long_tail_agent` plan with `executor_adapter=opencode`, including context gathering, OpenCode execution, and artifact verification steps.
- Chat handoff: `/api/chat` and WebSocket artifact requests return a user-visible OpenCode task response and task metadata without calling the normal model chat path and without directly generating `.pptx` files in the chat layer.
- Open task state: artifact handoff creates a long-tail task and advances it to an executor packet (`awaiting_executor`) so an OpenCode worker can pick it up.
- OpenCode worker adapter:
  - `OpenCodeArtifactWorker` can advance `gather_artifact_context -> opencode_execute_artifact -> verify_artifact_delivery`.
  - `SubprocessOpenCodeExecutor` runs a configured command with `NOMI_OPENCODE_STEP_PACKET`, `NOMI_ARTIFACT_WORKSPACE`, and `NOMI_ARTIFACT_MANIFEST`.
  - The worker copies generated files from the constrained workspace into artifact storage, blocks path traversal/out-of-workspace manifests, and writes compatibility rows into `task_runs` and `task_artifacts`.
  - The worker now performs artifact verification: non-empty files, valid Office archive structure for `.pptx/.docx/.xlsx`, non-empty Markdown content, PPTX slide/text/title extraction, layout quality signals, and source-evidence traceability checks.
  - `POST /api/agent-tasks/{task_id}/run-opencode-artifact-worker` dispatches the worker for an existing long-tail task.
- Full OpenCode CLI adapter:
  - `runtime_api/scripts/nomi_opencode_cli_adapter.py` builds an OpenCode prompt from the task packet, source evidence, workspace path, and manifest contract.
  - The adapter invokes the non-interactive CLI as `opencode run <prompt>` by default, or a configured `NOMI_OPENCODE_CLI_COMMAND`.
  - The adapter fails if OpenCode does not write `NOMI_ARTIFACT_MANIFEST` or if the manifest points to a missing file.
- Default OpenCode artifact command:
  - `runtime_api/scripts/nomi_opencode_artifact_command.py` is configured as the default `OPENCODE_ARTIFACT_COMMAND`.
  - The default command reads the OpenCode step packet, creates a real `.pptx` file with `python-pptx`, writes a manifest, and maps evidence IDs when present.
  - It now reads the real long-tail packet shape (`original_goal_summary`) as well as `plan_input.user_request`, so the generated content follows the user goal instead of falling back to a generic template.
- Inline artifact execution:
  - `/api/chat` and WebSocket artifact requests can run the OpenCode artifact worker inline when `ENABLE_OPENCODE_ARTIFACT_INLINE_RUN=true`.
  - The user receives a delivery answer with a real download URL after the artifact is generated and stored.
- Android artifact cards:
  - Android `/api/chat` responses now parse structured `artifacts` into `ChatArtifact`.
  - Android WebSocket `chat_done` now parses both top-level `artifacts` and nested `task.artifacts`.
  - Floating chat now renders a dedicated artifact card with filename, artifact type, verification status, and a tap-to-download action instead of relying only on long URLs inside normal chat bubbles.
- Attachment evidence preservation:
  - Artifact evidence pack now preserves real attachment metadata from source context (`attachment_id`, `filename`, `mime_type`, `local_path`, optional `url`).
  - Attachment-only source items are no longer dropped when the actor/entity matches the user request.
  - Evidence coverage marks real attachment evidence as `has_file_attachments=true`.
  - The OpenCode subprocess executor now stages local attachment files into the constrained workspace under `evidence_attachments/` and annotates each attachment with `staged_path`, so OpenCode can use local files without reading arbitrary source paths.
- Artifact grounding verification:
  - Verification now checks not only that every `source_evidence_id` has an `evidence_to_content_map` entry, but also that extracted artifact text has keyword overlap with the mapped source evidence.
  - The check blocks obviously unrelated artifacts, for example a PPT about LLMs mapped to a quotation/invoice evidence item.
- Web task detail UI:
  - `/tasks/{task_id}` now serves a dedicated task detail page.
  - The page loads `/api/tasks/{task_id}` and `/api/tasks/{task_id}/artifacts`, and renders task summary, steps, evidence links, artifact status, and download links.
- Worker lifecycle automation:
  - `PostgresOpenCodeArtifactTaskScanner` now scans only due long-tail tasks whose `route_decision.executor_adapter=opencode` and whose node is executable (`select_step` or `awaiting_executor`).
  - `process_due_opencode_artifact_tasks_once` claims a lease, recovers the task from the event log when needed, runs the OpenCode artifact worker, and releases the lease.
  - The worker re-checks recovered task state before execution and skips/synchronizes stale materialized rows such as DB says `awaiting_executor` but the event log has already reached `delivered`.
  - `opencode_artifact_worker_loop` is wired into FastAPI startup behind `ENABLE_OPENCODE_ARTIFACT_WORKER`.
  - Docker Compose exposes worker interval, batch size, and lease timeout environment settings.
- Multilingual artifact routing:
  - English requests such as `Make a PPT for ordinary people explaining how LLM works` now route to `artifact_creation`.
  - URL-encoded input such as ADB-produced `%20` text is decoded before routing.
- Artifact title normalization:
  - URL-encoded goals are decoded inside the default artifact command before filename generation.
  - English goals such as `Make a PPT for ordinary people explaining how LLM works` are normalized to the real topic rather than `Make_a_PPT...`.
  - The generated filename now remains human-readable, e.g. `ordinary_people_explaining_how_LLM_works.pptx`.
- Task APIs:
  - `GET /api/tasks/{task_id}` returns task state, steps, and evidence links.
  - `GET /api/tasks/{task_id}/artifacts` returns the artifact list, currently empty for planning tasks.
  - `GET /api/artifacts/{artifact_id}/download` can return verified files already present in artifact storage.
- Regression coverage:
  - Artifact router and evidence pack tests.
  - OpenCode artifact plan tests.
  - OpenCode artifact worker tests for successful manifest persistence, unsafe path blocking, and invalid PPTX blocking.
  - OpenCode worker endpoint authentication/dispatch test.
  - Long-tail agent runtime tests.
  - `/api/chat` and WebSocket artifact handoff tests proving the normal model gateway and legacy PPT generator are not called.
  - `/api/chat` and WebSocket inline worker tests proving artifact delivery returns a download link after generation.
  - Default command tests proving both `plan_input.user_request` and real `original_goal_summary` packets generate LLM-specific PPT content.
  - OpenCode background worker tests proving due tasks are scanned with the correct executor/node filters, lease-protected batch processing runs only acquired tasks, and stale delivered tasks are not re-run.
  - OpenCode CLI adapter test proving a non-interactive CLI command receives the manifest contract and writes a real PPTX manifest.
  - PPTX verifier tests proving slide count, text samples, title candidates, layout signals, empty-deck blocking, and source-evidence mapping blocking.
  - Grounding verifier tests proving unrelated artifact text is blocked when it does not overlap mapped evidence.
  - Android artifact response/card tests proving HTTP and WebSocket artifact metadata can be parsed and rendered as cards.
  - Attachment evidence tests proving attachment-only source context is preserved for artifact tasks.
  - Attachment staging tests proving local attachment paths are copied into the OpenCode workspace before execution.
  - Task detail and artifact list API tests.
  - Web task detail page tests proving `/tasks/{task_id}` serves a UI shell with steps/evidence/artifact sections.
- Cloud and real-device validation:
  - Cloud `/api/chat` generated and downloaded a 6-slide PPT for `那你帮我做一个ppt 让普通人可以理解llm的工作原理`; parsed slides contained LLM, token, attention, and private-context explanations.
  - Cloud `/api/chat` generated and downloaded a 6-slide PPT for URL-encoded English input after deployment on 2026-07-07; the returned filename was `ordinary_people_explaining_how_LLM_works.pptx`, not a `%20`-polluted filename.
  - Android real device `DQYTCYFMO7VSEAJB` sent the same encoded English task through the floating chat; Nomi returned `已生成 PPT 文件` plus a download URL.
  - The latest real-device-triggered server artifact was parsed in the cloud container and confirmed to contain 6 slides with LLM, token, attention, and private-context content.
  - Cloud background worker validation: a new OpenCode long-tail artifact task was created through `/api/agent-tasks` without `/api/chat` inline execution; the worker loop advanced it to `completed/delivered`, produced a verified PPTX artifact, and parsed slide text contained LLM, token, attention, and private-context explanations.
  - Android floating service was re-verified on the real device. The earlier apparent launch failure was caused by using the wrong 920px-height tap coordinate against a 1080x2400 real screen; tapping the actual `启动 Nomi` button center started the foreground service, displayed the floating Nomi avatar, and opened the floating chat.

## Remaining Gaps

- Production cloud is still configured to use the default artifact command unless `OPENCODE_ARTIFACT_COMMAND` is switched to `python /app/scripts/nomi_opencode_cli_adapter.py` and the cloud image/runtime has a working `opencode` CLI plus any browser/tool permissions it needs.
- Real artifact generation quality through a full OpenCode CLI is not soak-tested yet. The adapter exists and is covered with a fake CLI, but complex multi-file workspaces, tool-using OpenCode runs, and iterative self-correction still need validation against the actual configured OpenCode runtime.
- Real-device text input automation is still imperfect. ADB `input text` on the Redmi device can emit `%20`-encoded spaces or leave IME residue; this is now tolerated by the backend, but it is not a substitute for a human natural-input UX test.
- Slide/document verifier is stronger but still not a full semantic fact checker. It now checks PPTX structure, slide text, titles, layout signals, source evidence mapping, and coarse keyword grounding, but it does not yet prove every factual claim in a slide is entailed by evidence.
- Attachment retrieval is still incomplete at the collector layer. Artifact tasks preserve attachment metadata and stage already-local files when source context provides `local_path`, but no verified collector currently downloads WhatsApp/Telegram/Gmail attachments from live browser sessions into local artifact workspace paths.
- Real-source-to-artifact validation is still partial. Real Android chat-to-artifact is verified; real WhatsApp/Gmail/Telegram attachment-to-artifact and recent-source-context-to-artifact workflows still require live account messages and downloadable attachments.
- Worker lifecycle automation still lacks production soak testing with long-running full OpenCode CLI tasks. The queue/lease loop exists, but only the default artifact command path and fake CLI adapter path have been validated.

## Next Recommended Slice

1. Install/configure actual `opencode` CLI in the cloud image and switch `OPENCODE_ARTIFACT_COMMAND` to the CLI adapter for a controlled dry-run.
2. Add semantic artifact fact checking against evidence snippets for generated slides/docs beyond coarse keyword grounding.
3. Implement live attachment download from Gmail/WhatsApp/Telegram collectors into local source paths that can then be staged for artifact tasks.
4. Run production soak testing for the background OpenCode artifact worker with inline execution disabled and real OpenCode CLI enabled.
5. Run real-source WhatsApp/Gmail/Telegram-to-artifact validation with actual source messages and attachments.
