# OpenCode Capability Packs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Nomi's OpenCode artifact executor into a capability-pack system and ship presentation, spreadsheet, document, and image packs that produce evidence-grounded, format-native, verifiable artifacts.

**Architecture:** A small Python registry discovers versioned manifests under `runtime_api/opencode_capabilities/`, selects exactly one pack for the requested artifact type, and stages only that pack's skills, agents, tools, templates, and validators into the per-task OpenCode workspace. The existing worker remains responsible for task state, storage, and final verification; presentation-specific quality requirements are declared by the pack and enforced by deterministic verification rather than trusting process exit status.

**Tech Stack:** Python 3.12, OpenCode 1.17.14, `SKILL.md`, OpenCode custom tools/agents, python-pptx, pytest, Docker Compose.

---

### Task 1: Capability Pack Registry

**Files:**
- Create: `runtime_api/app/capability_packs.py`
- Create: `runtime_api/opencode_capabilities/presentation/manifest.json`
- Test: `runtime_api/tests/test_capability_packs.py`

- [x] **Step 1: Write failing registry tests**

Test that the registry rejects malformed manifests and duplicate artifact ownership, discovers the `presentation` pack, and deterministically selects it for `pptx` while returning no pack for an unsupported type.

- [x] **Step 2: Verify RED**

Run: `python3 -m pytest runtime_api/tests/test_capability_packs.py -q`

Expected: FAIL because `app.capability_packs` and the presentation manifest do not exist.

- [x] **Step 3: Implement the minimum registry**

Implement immutable `CapabilityPack`, manifest schema validation, directory boundary checks, deterministic discovery order, and `select_capability_pack(artifact_type)`.

- [x] **Step 4: Verify GREEN**

Run: `python3 -m pytest runtime_api/tests/test_capability_packs.py -q`

Expected: all registry tests pass.

### Task 2: Per-Task OpenCode Pack Staging

**Files:**
- Modify: `runtime_api/scripts/nomi_opencode_cli_adapter.py`
- Create: `runtime_api/opencode_capabilities/presentation/skills/presentation-quality/SKILL.md`
- Create: `runtime_api/opencode_capabilities/presentation/agents/presentation-producer.md`
- Create: `runtime_api/opencode_capabilities/presentation/tools/create_presentation.ts`
- Test: `runtime_api/tests/test_opencode_artifact_worker.py`

- [x] **Step 1: Write failing staging tests**

Test that a PPTX packet selects `presentation`, copies only its declared OpenCode resources under `<workspace>/.opencode`, injects the skill path/default agent/permissions into `OPENCODE_CONFIG_CONTENT`, and records pack id/version in the prompt. Test that path traversal and undeclared files are rejected.

- [x] **Step 2: Verify RED**

Run the focused adapter tests and confirm failure on missing staging behavior.

- [x] **Step 3: Implement pack staging**

Stage resources before `opencode run`, merge pack configuration without dropping the Qwen provider, and preserve one-pack-per-task isolation. OpenCode starts once per artifact task, so newly enabled packs take effect on the next task without restarting the Nomi API.

- [x] **Step 4: Verify GREEN**

Run focused adapter and registry tests; inspect the staged directory and resolved JSON config.

### Task 3: Presentation Pack Generation Contract

**Files:**
- Create: `runtime_api/scripts/nomi_presentation_tool.py`
- Modify: `runtime_api/scripts/nomi_opencode_artifact_command.py`
- Test: `runtime_api/tests/test_presentation_capability.py`

- [x] **Step 1: Write failing content and layout tests**

Define a presentation specification containing audience, purpose, narrative, slide roles, evidence ids, and visual intent. Require varied layouts, bounded text density, editable native shapes, source mapping, and at least one explanatory visual when the deck has four or more slides.

- [x] **Step 2: Verify RED**

Run: `python3 -m pytest runtime_api/tests/test_presentation_capability.py -q`

Expected: FAIL because the presentation tool and quality manifest fields are absent.

- [x] **Step 3: Implement deterministic PPTX rendering**

Build a reusable renderer with title, section, concept-diagram, comparison, process, and closing layouts; use restrained design tokens, native PowerPoint shapes, safe typography, and evidence metadata. Make the existing fallback call the same renderer so degraded execution remains visually acceptable.

- [x] **Step 4: Verify GREEN**

Open the generated PPTX with python-pptx, inspect slide roles/shapes/text/evidence mapping, and ensure the file is a valid Office archive.

### Task 4: Pack-Aware Quality Gate

**Files:**
- Modify: `runtime_api/app/opencode_artifact_worker.py`
- Modify: `runtime_api/app/artifact_tasks.py`
- Test: `runtime_api/tests/test_opencode_artifact_worker.py`
- Test: `runtime_api/tests/test_artifact_tasks.py`

- [x] **Step 1: Write failing quality-gate tests**

Test that route and plan metadata include pack id/version; presentation verification rejects empty slides, excessive text, duplicate titles, missing source mapping, and decks that claim the pack without its minimum layout diversity. Verify a compliant deck reports content, structure, layout, and traceability checks separately.

- [x] **Step 2: Verify RED**

Run focused worker and router tests and confirm each new assertion fails for the intended missing behavior.

- [x] **Step 3: Implement pack-aware verification**

Propagate pack metadata through route, step packet, manifest, storage, and verification report. Keep generic Office validation for other formats, while applying presentation rules only when the selected pack declares them.

- [x] **Step 4: Verify GREEN**

Run all artifact tests and inspect generated reports for correct counts and human-readable rejection reasons.

### Task 5: Container Packaging and Regression

**Files:**
- Modify: `runtime_api/Dockerfile`
- Modify: `docker-compose.yml`
- Create: `docs/superpowers/reports/2026-07-15-opencode-capability-packs-gaps.md`
- Test: `runtime_api/tests/test_runtime_dependency_compatibility.py`

- [x] **Step 1: Write failing packaging test**

Require the runtime image to copy capability packs and expose `NOMI_CAPABILITY_PACKS_DIR`; require Compose to pass the same deterministic path to both runtime and artifact-worker services.

- [x] **Step 2: Verify RED, then implement packaging**

Update Docker and Compose only after the contract test fails for the expected missing path.

- [x] **Step 3: Run regression**

Run capability, artifact-worker, artifact-router, clarification, and runtime compatibility suites. Generate a real sample PPTX and inspect its content and layout metrics rather than only its exit code.

- [x] **Step 4: Record honest gaps**

Document any unimplemented visual screenshot review, external image-generation provider, additional Word/Excel/PDF/image packs, or cloud/device verification as explicit gaps with evidence and next action.

### Task 6: Spreadsheet Capability Pack

**Files:**
- Create: `runtime_api/app/spreadsheet_capability.py`
- Create: `runtime_api/scripts/nomi_spreadsheet_tool.py`
- Create: `runtime_api/opencode_capabilities/spreadsheet/`
- Test: `runtime_api/tests/test_spreadsheet_capability.py`

- [x] **Step 1: Define and test the workbook contract**

Require typed columns, bounded rows/sheets, safe formulas, formula previews, filters, frozen headers, readable formatting, and evidence-to-sheet mapping. Reject unknown fields, unsafe functions, and malformed formulas.

- [x] **Step 2: Implement native XLSX rendering and validation**

Generate editable workbooks with formulas rather than pasted values, recalculate on open, and record independently calculated formula previews in the manifest.

- [x] **Step 3: Integrate routing, staging, fallback, repair, and quality gates**

Route Excel requests to `spreadsheet@1.0.0`, stage only its resources, preserve columns/calculations in the task contract, and use the same renderer in degraded fallback execution.

- [x] **Step 4: Verify actual content**

Open the generated workbook with `openpyxl`, verify formulas and calculated previews, and inspect a rendered thumbnail for CJK text and visible headers.

### Task 7: Document Capability Pack

**Files:**
- Create: `runtime_api/app/document_capability.py`
- Create: `runtime_api/scripts/nomi_document_tool.py`
- Create: `runtime_api/opencode_capabilities/document/`
- Test: `runtime_api/tests/test_document_capability.py`

- [x] **Step 1: Define and test the document contract**

Require purpose, audience, substantive sections, valid heading hierarchy, rectangular tables, native editable content, action items, and evidence mapping. Reject placeholders and broken structure.

- [x] **Step 2: Implement native DOCX rendering and validation**

Generate editable paragraphs, headings, lists, tables, headers, footers, document metadata, and visible evidence notes.

- [x] **Step 3: Integrate routing, staging, fallback, repair, and quality gates**

Preserve audience, purpose, and requested sections through clarification and into the OpenCode execution prompt.

- [x] **Step 4: Verify actual content and layout**

Parse the DOCX independently with `python-docx` and visually inspect the native macOS Quick Look render for readable Chinese, hierarchy, table content, and non-overlap.

### Task 8: Image Capability Pack

**Files:**
- Create: `runtime_api/app/image_capability.py`
- Create: `runtime_api/scripts/nomi_image_tool.py`
- Create: `runtime_api/opencode_capabilities/image/`
- Test: `runtime_api/tests/test_image_capability.py`

- [x] **Step 1: Define and test the visual contract**

Support deterministic PNG information graphics, diagrams, posters, and social cards. Require dimensions, readable contrast, bounded text, nonblank pixels, source mapping, and no placeholders.

- [x] **Step 2: Implement deterministic PNG rendering and pixel validation**

Render with Pillow using available CJK fonts, then check dimensions, color diversity, non-background ratio, contrast, and overflow before writing a passing manifest.

- [x] **Step 3: Integrate natural-language routing and repair**

Recognize requests including `生成一张`, `画一张`, and `绘制`, preserve visual kind/canvas/output format, and constrain the pack to the PNG formats it actually supports.

- [x] **Step 4: Verify actual pixels and readability**

Open the generated PNG independently and manually inspect its visible content rather than relying only on process success.

### Task 9: Multi-Format Contract and Regression

**Files:**
- Modify: `runtime_api/app/open_task_clarification.py`
- Modify: `runtime_api/scripts/nomi_opencode_artifact_command.py`
- Modify: `runtime_api/scripts/nomi_opencode_cli_adapter.py`
- Modify: `runtime_api/app/opencode_artifact_worker.py`
- Create: `runtime_api/app/font_support.py`
- Test: artifact, clarification, capability, and packaging suites

- [x] **Step 1: Add format-specific clarification contracts**

Spreadsheet asks for purpose and columns; document asks for purpose and audience; image asks for purpose and audience. Optional safe defaults remain explicit and do not silently invent source data.

- [x] **Step 2: Preserve the contract through execution**

Pass fields/formulas, sections, visual kind/canvas, editability, and no-invention rules to the selected capability pack and repair checkpoint.

- [x] **Step 3: Add format-specific independent verification**

Re-open XLSX, DOCX, and PNG outputs with independent parsers and reject artifacts that merely have the correct extension.

- [x] **Step 4: Fix cross-platform CJK output and run regression**

Select an installed CJK font at generation time (Noto CJK in Docker; PingFang/Hiragino on macOS; Microsoft YaHei on Windows) and verify native Quick Look rendering. Latest full capability/artifact regression result: `174 passed in 6.33s`.

## Self Review

- Spec coverage: discovery, selection, staging, presentation generation, quality enforcement, packaging, and gap reporting are each owned by a task.
- Placeholder scan: implementation behavior and exact verification commands are specified; no silent follow-up scope is treated as complete.
- Type consistency: `capability_pack_id`, `capability_pack_version`, `artifact_types`, `quality_profile`, and `resource_paths` are the shared names across registry, route, manifest, and verifier.

### Task 10: Install OpenCode CLI and Validate New Packs

- [x] Install OpenCode `1.17.14`, matching the runtime container version.
- [x] Verify a real Qwen request through OpenCode and confirm `reasoning=0`.
- [x] Run and independently inspect a real OpenCode/Qwen spreadsheet artifact.
- [x] Add bounded attempt timeouts, local runtime-path repair, visible renderer errors, and stale-manifest protection uncovered by real runs.
- [x] Add current semantic gates for observed document metrics and unsupported image claims.
- [x] Reduce duplicate agent context, remove runtime skill loading, and replace JSON-in-string tool arguments with flat typed schemas.
- [x] Produce a real OpenCode DOCX that passes the current semantic and causal-inference gates, then replay its accepted specification independently.
- [x] Produce a real OpenCode PNG that passes the current evidence and visual gates, then inspect the rendered pixels independently.
- [ ] Deploy and verify PPTX/XLSX/DOCX/PNG through the 4C8G server and Android download/open flow.
