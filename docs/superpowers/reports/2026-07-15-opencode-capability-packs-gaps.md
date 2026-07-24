# OpenCode Capability Packs Gaps

## Completed in this iteration

- Versioned capability-pack discovery and manifest validation.
- Deterministic artifact-type routing with duplicate ownership rejection.
- Per-task staging of only the selected pack's skills, agents, tools, and config.
- OpenCode provider-config merging without dropping the existing Qwen endpoint.
- Pack metadata propagation through routing, execution, storage manifest, and verification.
- `presentation@1.0.0` with an artifact-specific skill, producer agent, custom tool, deterministic editable PPTX renderer, and quality gate.
- `spreadsheet@1.0.0` with typed native XLSX output, safe formulas, calculated previews, formatting, evidence mapping, and independent workbook verification.
- `document@1.0.0` with editable native DOCX paragraphs, headings, lists, tables, metadata, evidence notes, and independent document verification.
- `image@1.0.0` for deterministic PNG infographics, diagrams, posters, and social cards with pixel, contrast, bounds, font, and evidence checks.
- Artifact-specific clarification and execution contracts for spreadsheet columns/calculations, document audience/sections, and image visual kind/canvas.
- Artifact-specific fallback generation and bounded repair checkpoints for XLSX, DOCX, and PNG.
- Cross-platform CJK font selection for macOS, Docker/Linux, and Windows output.
- Exact request-contract enforcement for page count, audience, goal terms, and evidence topics.
- Technical-claim checks for common misleading LLM explanations.
- Bounded repair, attempt limit, worker lease, process timeout, and stable-artifact early completion.
- Docker/Compose packaging for the capability directory.
- Real Qwen/OpenCode PPTX generation plus rendered-slide and semantic-output verification.
- OpenCode CLI `1.17.14` installed locally at `/Users/wrf/.local/bin/opencode` and verified against the configured Qwen endpoint with `reasoning=0`.
- Real Qwen/OpenCode XLSX generation with independently checked formulas and values.
- Hard per-attempt process timeout and process-group cleanup for stalled OpenCode runs.
- Structured renderer failures returned to the agent instead of hidden tool exceptions.
- Stale-manifest protection for every pack tool; each render removes the previous manifest and output before writing a new specification.
- Image evidence-id validation and unsupported strong-claim rejection across titles, subtitles, blocks, and footers.
- Flat, strongly typed renderer arguments for all four OpenCode tools; JSON-in-string specifications are no longer part of the tool contract.
- Reduced artifact-agent prompt with evidence included once, renderer-first execution, no runtime skill-loading round, and an eight-step ceiling.
- Real Qwen/OpenCode DOCX generation through the current causal-inference gate, followed by an independent specification replay.
- Real Qwen/OpenCode PNG generation through the current evidence gate, followed by machine checks and human visual inspection.
- Image renderer-owned canvas/palette defaults, vertical narrow-process layout, process-number normalization, unsupported-emoji rejection, and unsupported-process-claim rejection.
- Private-cloud presentation execution through OpenCode with persisted task, artifact, delivery turn, and delivery event evidence.
- Android real-device presentation delivery through synchronized full-app and floating-panel history, one deduplicated file card, authenticated download, built-in two-slide rendering, and close/restore behavior.
- Floating-panel remote-history redraw now settles on the latest message after final layout.
- Artifact-card deduplication state is rebuilt with each complete history-view rebuild, so a remote sync no longer removes a valid card.

## Remaining product gaps

### Remaining artifact formats

PDF generation does not yet have a dedicated capability pack. Spreadsheet, document, and image packs now exist, but they must not be described as covering PDF generation.

The image pack intentionally supports deterministic PNG information graphics, diagrams, posters, and social cards. It does not yet generate photorealistic images, free-form illustrations, or JPEG output, and it does not call an external diffusion/image-generation model.

### Capability management UI

There is no user-facing page to install, enable, disable, pin, update, or inspect capability-pack versions. Packs are currently shipped with the runtime image and discovered from a configured directory.

### MCP and external plugin resources

The manifest currently stages local skills, agents, tools, and plugin configuration. It does not yet declare or provision external MCP servers, credentials, health checks, or per-pack network permissions.

### Rich presentation assets

The presentation pack currently uses editable native PowerPoint shapes. It does not yet perform image search, image generation, brand-template import, chart-data binding, or automatic asset-license attribution.

### General factual verification

The current claim gate catches known misleading LLM-explainer patterns and enforces supplied evidence coverage. It is not a general citation or factual-consistency engine for arbitrary presentation topics.

### Screenshot critique loop

The current samples were rendered or previewed and manually inspected. OpenCode itself does not yet render each PPTX/DOCX/XLSX draft or run an automated multimodal visual-critique/repair loop before finalization. PNG has deterministic pixel checks but no model-based aesthetic critique.

### Renderer maturity

The pack currently uses `python-pptx`. It produces editable and verified output, but richer template fidelity, chart support, and advanced layout composition should be evaluated against an artifact-tool or TypeScript renderer before calling the presentation system feature-complete.

### Legacy artifacts

Artifacts created before pack metadata was introduced still use generic Office checks and cannot be retroactively guaranteed to satisfy a pack-specific quality profile.

## Remaining operational gaps

- Real Qwen/OpenCode PPTX, XLSX, DOCX, and PNG have each passed locally under their current gates. PPTX additionally passed one production cloud and Android real-device run; XLSX, DOCX, and PNG have not yet received equivalent real-device download/open acceptance.
- The real DOCX task completed in approximately `27.8s`, while the accepted PNG task required three tool attempts and approximately `113s`. The image renderer itself completed in well under a second; most latency remains in model/OpenCode turns and invalid first-attempt arguments.
- The PNG model first emitted a malformed field name and then an evidence-unsupported protection claim. Deterministic validation prevented both from crossing the quality gate, but more real-run samples are required before claiming first-attempt production reliability.
- Image semantic validation is deliberately conservative and heuristic. It catches unknown evidence ids, unsupported strong claims, and a defined set of process claims, but it is not a general natural-language-inference engine. The accepted PNG therefore still received human content review.
- The target capacity is 4C8G. This iteration did not benchmark 2C4G and makes no claim that the same artifact workload is reliable there.
- A fresh Docker image pull/build can still be affected by previously observed transient Docker Hub metadata EOF errors. The final local verification used the current source and available local runtime dependencies.

## Recommended next order

1. Run equivalent production cloud and Android download/open acceptance for XLSX, DOCX, and PNG.
2. Collect repeated real-run first-tool latency and first-attempt pass-rate data, then reduce image-agent repair turns without weakening evidence gates.
3. Add a general entailment/citation verifier for arbitrary generated claims rather than expanding phrase lists indefinitely.
4. Add a PDF capability pack with native structure and visual verification.
5. Add per-pack MCP declarations, credential references, health checks, and least-privilege permissions.
6. Add the capability management page and version pinning.
7. Add rendered-draft multimodal critique and repair for PPTX, DOCX, XLSX, and PNG.
