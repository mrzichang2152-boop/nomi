# OpenCode Capability Packs Verification

## Scope

This report verifies the capability-pack foundation and four packs: `presentation@1.0.0`, `spreadsheet@1.0.0`, `document@1.0.0`, and `image@1.0.0`. It does not claim that a PDF generation pack exists.

## Automated regression

Command:

```bash
python3 -m pytest \
  runtime_api/tests/test_capability_packs.py \
  runtime_api/tests/test_spreadsheet_capability.py \
  runtime_api/tests/test_document_capability.py \
  runtime_api/tests/test_image_capability.py \
  runtime_api/tests/test_presentation_capability.py \
  runtime_api/tests/test_opencode_artifact_worker.py \
  runtime_api/tests/test_artifact_tasks.py \
  runtime_api/tests/test_open_task_clarification.py \
  runtime_api/tests/test_runtime_dependency_compatibility.py -q
```

Latest result on 2026-07-16: `174 passed in 6.33s`. The three modified Python entry points also pass `py_compile`.

Covered behavior:

- malformed and duplicate capability manifests are rejected;
- one artifact task selects one deterministic capability pack;
- only declared skills, agents, and tools are staged into the task workspace;
- the OpenCode Qwen provider config survives pack configuration merging;
- route, task packet, artifact manifest, and verification report retain pack id/version;
- task requirements enforce exact page count, target audience, goal coverage, and required evidence topics;
- empty, duplicated, excessively dense, misleading, evidence-free, or semantically incomplete presentations are rejected;
- OpenCode gets one bounded repair attempt when it exits without a valid verified artifact;
- early completion only occurs after a stable manifest and artifact pass verification;
- runtime and worker timeouts are compatible with a real 4C8G artifact workload;
- Docker and Compose expose the same deterministic capability-pack directory.
- spreadsheet requests preserve fields and calculations, produce formulas with calculated previews, and reject unsafe formulas or invented fields;
- document requests preserve purpose, audience, and sections, produce native editable structure, and reject placeholders or invalid heading/table structure;
- image requests preserve visual kind and canvas, produce nonblank PNG pixels, and reject low contrast, unsupported visual blocks, placeholders, or overflow;
- each non-presentation artifact is reopened with an independent format parser before delivery;
- cross-platform CJK font selection prevents generated Office files from depending on unavailable Aptos/等线 glyphs.

## Spreadsheet, document, and image sample verification

Generated artifacts:

```text
/tmp/nomi-capability-validation/spreadsheet-sample.xlsx
/tmp/nomi-capability-validation/document-sample.docx
/tmp/nomi-capability-validation/image-sample.png
```

Spreadsheet checks:

- one native worksheet with frozen header and filter;
- two evidence-grounded rows;
- four formulas with independent previews: profits `48,000` and `24,000`, margins `40%` and `30%`;
- currency and percentage number formats, visible CJK header text, alternating row styling, and evidence-to-sheet mapping.

Document checks:

- four native editable sections with valid heading levels;
- one rectangular table and three actionable numbered items;
- source evidence shown and mapped to every section;
- title, subtitle, metadata, headers, footer, bullets, table, and Chinese body text are readable in native macOS Quick Look with no visible overlap.

Image checks:

- RGB PNG at `1600x1000`;
- `928` distinct sampled colors and non-background ratio `0.4882`;
- `13` text boxes, zero overflow, valid CJK font, passing contrast, nonblank, placeholder, and evidence checks;
- manual inspection confirmed the requested three-stage workflow is visible and readable.

The bundled headless LibreOffice converter displayed CJK squares because its Fontconfig runtime could not see macOS fonts. Native Quick Look rendered the same DOCX/XLSX correctly, and the Office XML names the detected CJK font. This is recorded as a converter-environment limitation, not counted as an artifact pass by itself.

## Real Qwen/OpenCode generation

Model endpoint: `http://81.70.177.246:9161/v1`, model `qwen/qwen3.6-27b`.

Request: create a four-page Chinese presentation for a general audience explaining how an LLM generates an answer, including tokenization, context, next-token prediction, and limitations.

Final artifact:

```text
/tmp/nomi_opencode_e2e_v16.YdDfZu/work/llm_how_it_works_final.pptx
```

Observed content:

1. Title and audience framing.
2. Tokenization and numeric representation, with concrete visual-node examples.
3. A four-step generation process covering instructions/history/input, probability prediction, decoding, and iterative generation.
4. A closing slide distinguishing fluency from factual correctness, model parameters from application-supplied history, and model knowledge from retrieval/tools.

Quality result:

- slide count: `4/4`;
- roles: `title`, `concept`, `process`, `closing`;
- layout kinds: `4`;
- visual slides: `2`;
- maximum text per slide: `194` characters;
- semantic coverage: `32/32` segments (`1.0`);
- evidence mapping: `evt_pack_e2e` mapped to all four slides;
- exact page count, audience, goal terms, and required topics: all passed.

## OpenCode CLI installation and new-pack verification (2026-07-16)

Installed runtime:

```text
OpenCode 1.17.14
Node.js v22.23.1
npm 10.9.8
/Users/wrf/.local/bin/opencode
```

The installed CLI version exactly matches `runtime_api/Dockerfile`. A real minimal OpenCode request against `http://81.70.177.246:9161/v1` returned exactly `NOMI_FINAL_OK`. The JSON event reported `reasoning=0`, with `7,257` input tokens and `6` output tokens, confirming that the configured `reasoningEffort=none` is active.

A direct OpenAI-compatible tool-call control request to the same model returned one `create_image` tool call in `7.972s`, with `358` prompt tokens, `142` completion tokens, and `0` reasoning tokens. The capability tools now expose flat, strongly typed arguments instead of a JSON document embedded in a `specification` string, so OpenCode can validate individual fields before invoking a renderer.

The artifact-agent prompt was also reduced from approximately `1,979` characters (`~600` estimated tokens) to `1,363` characters (`~413` estimated tokens). It contains the task evidence once, forbids runtime skill loading, requires the renderer as the first action, and limits each agent to eight steps. This removes the duplicated packet and skill-loading round observed in the earlier stalled runs.

### Spreadsheet end-to-end result

The real OpenCode/Qwen spreadsheet task completed and wrote:

```text
/tmp/nomi-opencode-real-validation/spreadsheet/workspace/Q2利润分析.xlsx
```

The output contains two native worksheets, frozen headers, filters, three evidence-grounded project rows, and six formulas. Independent `openpyxl` checks confirmed:

- Alpha profit `45,000`, margin `35.15625%`;
- Beta profit `24,500`, margin `25.520833%`;
- Gamma profit `53,000`, margin `34.415584%`;
- formulas are native A1 formulas (`=B2-C2`, `=IFERROR(D2/B2,0)`, and row equivalents), not pasted results;
- all three ledger evidence ids map to both the analysis and provenance sheets.

This is a current real OpenCode/Qwen end-to-end pass.

### Document end-to-end result

A clean real OpenCode/Qwen document task completed in approximately `27.8s` and wrote:

```text
/tmp/nomi-opencode-real-validation/document-flat-v3/workspace/Q2_客户支持复盘报告.docx
```

The first assistant output arrived after approximately `10.5s`; the deterministic renderer completed in `164ms`. The model used `4,030` input tokens, `347` output tokens, and `0` reasoning tokens. Independent inspection of the emitted specification and DOCX confirmed:

- the observed metrics remain observations: first response median `12` minutes, average resolution time `4.2` hours, and escalation rate `0.9%`;
- findings remain attributed to supplied evidence rather than presented as invented root causes;
- the three suggestions are explicitly described as pending evaluation, not commitments;
- all three sections map to `evt_q2_metrics` or `evt_q2_findings`;
- the file contains native editable headings, paragraphs, and bullets and passes the document quality report.

The exact accepted specification was replayed through the current causal-inference gate and produced `/tmp/nomi-opencode-real-validation/document-flat-v3/replay.docx`. A separate regression proves that unsupported causal explanations are rejected rather than silently included.

### Image end-to-end result

A clean current-code OpenCode/Qwen image task ultimately wrote:

```text
/tmp/nomi-opencode-real-validation/image-flat-v4/workspace/nomy-memory-infographic.png
```

The accepted image is a portrait `1200x1600` RGB PNG with three full-width cards, `15` text boxes, zero overflow, `1,279` sampled colors, and a `0.6326` non-background ratio. The evidence map covers both memory blocks with `evt_memory` and the privacy block with `evt_privacy`. Manual inspection of `/tmp/nomi-opencode-real-validation/image-flat-v4/preview.jpg` confirmed that Chinese text is readable, each process uses evenly spaced horizontal steps inside a full-width card, no emoji tofu is visible, and content remains inside the canvas.

This real run required three tool attempts over approximately `113s`: the first contained a malformed field name, the second used an unsupported protection claim, and the third passed. The first two were correctly rejected and did not leave a stale passing manifest. The final text stays within the evidence: session/participant isolation, fact/event/relation extraction, KV/graph/vector retrieval, pre-request desensitization, and local/private-cloud retention.

The renderer now owns the verified canvas and palette defaults, strips redundant process numbering, rejects emoji unsupported by the selected font, uses vertical process layouts in narrow regions, and rejects unknown evidence ids, unsupported strong claims, and unsupported process claims. This is a real end-to-end pass, but the multi-attempt latency and first-call reliability remain operational gaps.

## Visual verification

Commands:

```bash
render_slides.py llm_how_it_works_final.pptx --output_dir rendered-final
slides_test.py llm_how_it_works_final.pptx
create_montage.py --input_dir rendered-final --output_file montage-final.png --label_mode filename
```

Result: `Test passed. No overflow detected.`

Manual inspection confirmed:

- all four slides are nonblank and use distinct layouts;
- titles, body copy, source labels, diagrams, and process cards do not overlap;
- agent-authored visual node details are visible rather than silently discarded;
- content stays within slide bounds and remains readable at normal presentation scale;
- the deck uses editable PowerPoint text and native shapes.

## Cloud and Android real-device verification (2026-07-21)

The current runtime was deployed to the private cloud server and exercised from the connected Redmi device `DQYTCYFMO7VSEAJB` against the production base URL `http://206.119.171.141`.

Real execution identifiers:

```text
conversation_id: 9ab96d2f-04f4-44a6-921b-c43c77d23082
task_id: lta_87f3323088a547d791c2d4b61b5e5807
artifact_id: artifact_34a667b190af41bcb86d6ab0c36dc0ab
delivery_turn_id: 243e8202-d39d-4218-8631-0230f1698762
delivery_event_id: 3fa1b0e8-ffad-45b8-bfea-f901118a9bba
filename: Nomi_context_release_v2_20260720.pptx
```

The request required exactly two slides and exact content constraints. The cloud task routed to the OpenCode presentation capability, generated a `31,001` byte PPTX, passed the artifact gates, persisted one final delivery turn, and emitted one delivery event. The final message contains the authenticated artifact endpoint and was independently found exactly once in the Android local cache.

The Android verification checked actual output rather than only HTTP status:

- the full app displayed the request, handoff, final delivery, and a clickable file card;
- the floating panel fetched `80` server turns through `okhttp/4.12.0`, reconciled stable message ids, and displayed the same latest delivery;
- the latest file card appeared exactly once after closing and reopening the panel;
- tapping the card opened `com.par.assistant.android/.NomiFileViewerActivity`;
- the viewer rendered both slides in place, including `Release Context Contract`, `No private retrieval`, `Verified Release`, `Current request retained`, and `Irrelevant history excluded`;
- closing the viewer returned to the same full-app conversation and restored the floating ball.

Cloud access evidence for the production-device path:

```text
GET /api/chat/history?...                    200 46173  okhttp/4.12.0
GET /viewer?...artifact_34a667b...           200 1554   Android WebView
GET /api/artifacts/artifact_34a667b...       200 31001  Android WebView
```

Two Android defects were reproduced and fixed with regression coverage during this run:

1. A remote-history redraw could finish at an old scroll position, making a successful sync look stale. The panel now scrolls after the final layout and performs one delayed layout correction.
2. A remote-history redraw removed all message views without rebuilding `displayedArtifactKeys`. The file card was therefore removed and then incorrectly skipped as a duplicate. A full redraw now clears the view-scoped deduplication set before rebuilding cards.

The device temporarily used an SSH/ADB USB tunnel while its network was unavailable. That tunnel was removed before final acceptance; the final history, viewer, and artifact requests all came directly from the device public network to the production base URL.

Final regression commands executed after the Android fixes:

```text
gradle -p android_app :app:testDebugUnitTest --rerun-tasks
  BUILD SUCCESSFUL; 22 tasks executed

python3 -m pytest runtime_api/tests -q
  1306 passed in 12.94s

python3 -m pytest worker/tests -q
  135 passed in 0.27s

GET http://206.119.171.141/health
  HTTP 200; {"status":"ok"}
```

## Failed attempts observed during development

Real executions also exposed failure modes before the final pass:

- one-page English placeholder decks;
- a process exit without a manifest;
- unsupported claims about persistent model memory, context behavior, and knowledge cutoff;
- descriptions of token generation as word-by-word or half-word generation;
- visual node details present in the specification but omitted from the deck.

These were not counted as successful runs. They led to the explicit request contract, technical-claim gate, bounded repair, stable-artifact completion gate, and visual-node semantic coverage tests now in the implementation.

## Conclusion

All four capability packs now have real local Qwen/OpenCode artifacts that passed their current deterministic gates and independent content inspection. OpenCode `1.17.14`, the Qwen endpoint, typed tool calling, and non-thinking mode are operational. The presentation path additionally passed a production cloud task and Android real-device history-sync, delivery-card, download, built-in-viewer, and close/restore workflow. The DOCX run completed in one accepted attempt; the PNG run was accepted only after two invalid attempts were rejected, so first-attempt reliability and agent-loop latency remain explicit gaps. Cloud/Android acceptance in this report applies to the presentation path and must not be generalized to untested real-device XLSX, DOCX, PNG, or future PDF generation.
