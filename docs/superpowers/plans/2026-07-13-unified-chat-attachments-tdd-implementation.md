# Unified Chat Attachments TDD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement one production-quality attachment system shared by Nomi's Android floating chat and full App, supporting attachment-only and text-plus-attachment turns, private durable storage, bounded asynchronous parsing, Qwen visual understanding, traceable citations, and server-authoritative cross-surface history.

**Architecture:** Upload bytes once into private storage, validate real file type before creating a durable draft, and process the draft through a bounded Redis-backed attachment worker. Commit the user turn and ordered attachment relations in one PostgreSQL transaction through a shared submission service used by HTTP and WebSocket chat. Build model evidence from full text, hybrid retrieval, or selected visual pages under the existing 256K context budget; encode images only at the Qwen adapter boundary. The server remains the source of truth, while Web and Android render the same attachment metadata returned by chat history.

**Tech Stack:** FastAPI, Pydantic, PostgreSQL/psycopg, Redis, Python 3.12, Pillow, pypdf, pypdfium2, python-docx, python-pptx, openpyxl, LibreOffice headless, Qwen OpenAI-compatible multimodal API, vanilla HTML/CSS/JavaScript, Android Java 17, Android Storage Access Framework, OkHttp, pytest, Node test runner, JUnit 4, MockWebServer, Docker Compose, adb.

**Source Specification:** `docs/superpowers/specs/2026-07-13-unified-chat-attachments-design.md`

**Research Basis:** `docs/superpowers/reports/2026-07-13-chat-attachments-research.md`

---

## Non-Negotiable Invariants

1. An upload is a `draft`; it does not belong to a conversation until a user turn and all attachment relations commit atomically.
2. `message` and `attachment_ids` may each be empty, but never both. Attachment-only turns use an internal default instruction without rewriting the user's stored empty text.
3. HTTP and WebSocket call the same submission, evidence-selection, model-content, retry, and history code paths.
4. Original bytes live outside the source tree and Web root. Database rows, logs, traces, memory, and chat history never contain base64 or absolute storage paths.
5. The server validates extension allowlist, magic bytes, container structure, archive complexity, pixel count, file size, attachment count, and aggregate message size independently of the client.
6. A model failure preserves the original user turn and attachments. Retrying reuses that turn and does not upload or insert it again.
7. Model answers may only claim evidence actually selected into the request. Every selected text chunk or visual item carries a stable locator.
8. Document text is untrusted evidence. It cannot replace system instructions or trigger tools and external side effects.
9. Full App and floating chat show the same sent messages and attachments by `message_id + attachment_id`; unsent drafts stay local to the creating surface.
10. Completion requires semantic output review on real files and a real Android device, not only status codes or green unit tests.

## File Map

### Backend Domain and Storage

- Create `runtime_api/app/attachments/__init__.py`: package exports.
- Create `runtime_api/app/attachments/models.py`: statuses, lifecycle values, limits, structured content types, public DTOs, stable error codes.
- Create `runtime_api/app/attachments/schema.py`: upgrade-safe attachment schema bootstrap.
- Create `runtime_api/app/attachments/repository.py`: attachment locking, state transitions, idempotency, binding, history, cleanup queries.
- Create `runtime_api/app/attachments/storage.py`: private relative paths, streamed writes, SHA-256, fsync, atomic move, safe deletion.
- Create `runtime_api/app/attachments/detection.py`: filename normalization, magic/container validation, complexity gates.
- Create `runtime_api/app/attachments/service.py`: upload, retry, delete, submit, assistant retry, and conversation-delete orchestration.
- Create `runtime_api/app/attachments/router.py`: authenticated attachment API router built from injected database/auth dependencies.

### Parsing and Evidence

- Create `runtime_api/app/attachments/queue.py`: bounded Redis queue and deduplication lease.
- Create `runtime_api/app/attachments/worker.py`: state machine, timeout handling, parser dispatch, derivative/chunk persistence.
- Create `runtime_api/app/attachments/worker_entrypoint.py`: worker process entrypoint.
- Create `runtime_api/app/attachments/parsers/__init__.py`: parser registry.
- Create `runtime_api/app/attachments/parsers/common.py`: parser result and locator contracts.
- Create `runtime_api/app/attachments/parsers/image.py`: Pillow validation, orientation, thumbnail, GIF frame selection.
- Create `runtime_api/app/attachments/parsers/pdf.py`: page text, density, scan markers, on-demand rendering.
- Create `runtime_api/app/attachments/parsers/docx.py`: ordered headings, paragraphs, lists, tables, links, media references.
- Create `runtime_api/app/attachments/parsers/pptx.py`: ordered slides, titles, text, notes, tables, media references.
- Create `runtime_api/app/attachments/parsers/spreadsheet.py`: XLSX/CSV bounded extraction with Sheet/cell locators.
- Create `runtime_api/app/attachments/parsers/text.py`: TXT/Markdown safe decoding and line locators.
- Create `runtime_api/app/attachments/retrieval.py`: full-text/hybrid/visual evidence planning and per-attachment quotas.
- Create `runtime_api/app/attachments/model_content.py`: structured text/image parts and adapter-boundary base64 encoding.
- Create `runtime_api/app/attachments/citations.py`: stable citation labels and evidence coverage checks.
- Create `runtime_api/app/attachments/trace.py`: privacy-safe latency and evidence traces.

### Existing Backend Integration

- Modify `runtime_api/app/main.py`: schema/router bootstrap, `ChatIn`, shared HTTP/WebSocket submission, history, retry, conversation deletion, memory provenance.
- Modify `runtime_api/app/model_client.py`: structured message content and formal-content-only streaming.
- Modify `runtime_api/app/model_gateway.py`: structured message protocol types.
- Modify `runtime_api/requirements.txt`: multipart, image, PDF rendering, spreadsheet, and encoding dependencies.
- Modify `runtime_api/Dockerfile`: LibreOffice/runtime packages and non-root attachment worker support.
- Modify `docker-compose.yml`: shared private attachment volume, runtime settings, and bounded `attachment-worker` service.
- Modify `db/init.sql`: fresh-install attachment tables, constraints, and indexes.

### Web Full App

- Create `runtime_api/app/static/chat-attachments.js`: testable attachment draft state, upload, polling, retry, rendering, and payload construction.
- Modify `runtime_api/app/static/index.html`: hidden multi-file input, attachment icon, integrated tray, retry/remove controls.
- Modify `runtime_api/app/static/app.js`: attachment-only send, WebSocket/HTTP payloads, history merge, assistant retry.
- Modify `runtime_api/app/static/styles.css`: compact responsive tray, message attachment cards, progress/error states, overflow protection.

### Android Full App and Floating Chat

- Create `android_app/app/src/main/java/com/par/assistant/android/ChatAttachment.java`: immutable public attachment metadata.
- Create `android_app/app/src/main/java/com/par/assistant/android/AttachmentDraft.java`: local draft and upload/processing state.
- Create `android_app/app/src/main/java/com/par/assistant/android/AttachmentUploadRequestBody.java`: ContentResolver-to-OkHttp streamed body.
- Create `android_app/app/src/main/java/com/par/assistant/android/AttachmentPickerActivity.java`: lightweight SAF picker bridge for the floating service.
- Create `android_app/app/src/main/java/com/par/assistant/android/FloatingAttachmentController.java`: draft restoration, polling, retry, remove, send gating.
- Modify `android_app/app/src/main/java/com/par/assistant/android/AssistantApiClient.java`: upload/status/retry/delete/chat/history attachment contracts.
- Modify `android_app/app/src/main/java/com/par/assistant/android/RealtimeClient.java`: attachment IDs in WebSocket messages and terminal events.
- Modify `android_app/app/src/main/java/com/par/assistant/android/FloatingBallService.java`: attachment icon/tray/cards and keyboard-safe layout.
- Modify `android_app/app/src/main/java/com/par/assistant/android/WebWorkspaceActivity.java`: `onShowFileChooser` and URI result handling.
- Modify `android_app/app/src/main/java/com/par/assistant/android/LocalChatHistoryStore.java`: safe attachment metadata mirror and ID-based merge.
- Modify `android_app/app/src/main/AndroidManifest.xml`: picker activity and FileProvider-safe declarations.

### Tests and Durable Evidence

- Create `runtime_api/tests/fixtures/attachments/README.md`: fixture provenance and expected facts.
- Create `runtime_api/tests/attachment_fixture_factory.py`: deterministic valid, corrupt, encrypted, oversized, and hostile fixtures.
- Create backend test modules listed in the tasks below.
- Create `runtime_api/tests_js/chat_attachments.test.cjs`: Web state and payload tests using Node's built-in runner.
- Create Android JUnit modules listed in the tasks below.
- Create `docs/superpowers/reports/2026-07-13-unified-chat-attachments-implementation-gaps.md`: implementation and environment gaps updated after every task.
- Create `docs/superpowers/reports/2026-07-13-unified-chat-attachments-real-device-results.md`: semantic real-file and device acceptance evidence.

---

## Task 0: Protect the Existing Worktree and Record the Baseline

**Files:**
- Create: `docs/superpowers/reports/2026-07-13-unified-chat-attachments-implementation-gaps.md`

- [ ] **Step 1: Inspect rather than clean the current worktree**

Run:

```bash
git status --short
git diff --stat
git log -5 --oneline
```

Expected: the executor records all pre-existing modified and untracked files. Do not reset, restore, stash, or overwrite changes that were not created by the attachment implementation.

- [ ] **Step 2: Record the baseline test state**

Run:

```bash
python3 -m pytest -q runtime_api/tests
gradle -p android_app :app:testDebugUnitTest
docker compose config --quiet
```

Record command, exit code, failing test names, and whether each failure reproduces before attachment work. Existing failures remain visible; they are not converted into skips or weakened assertions.

- [ ] **Step 3: Create the gap report before production edits**

The report begins with one row per specification area and these fields: `status`, `automated evidence`, `real-environment evidence`, `known gap`, `blocker`, `next action`. After every task, update only the affected rows.

- [ ] **Step 4: Apply commit hygiene throughout this plan**

The commit commands below name the intended files. If any named file already contains unrelated local changes, stage only attachment-related hunks with `git add -p <file>` and inspect `git diff --cached` before committing. Never stage a whole pre-existing dirty file merely because it appears in a task command.

- [ ] **Step 5: Commit the baseline report only**

```bash
git add docs/superpowers/reports/2026-07-13-unified-chat-attachments-implementation-gaps.md
git diff --cached --check
git commit -m "docs: record attachment implementation baseline"
```

## Task 1: Freeze Public Contracts, Limits, and Database Schema

**Files:**
- Create: `runtime_api/app/attachments/__init__.py`
- Create: `runtime_api/app/attachments/models.py`
- Create: `runtime_api/app/attachments/schema.py`
- Modify: `db/init.sql`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_attachment_schema.py`
- Test: `runtime_api/tests/test_attachment_models.py`

- [ ] **Step 1: Write failing domain-contract tests**

```python
from app.attachments.models import (
    AttachmentErrorCode,
    AttachmentLimits,
    AttachmentStatus,
    validate_chat_input,
)


def test_attachment_limits_match_approved_spec():
    limits = AttachmentLimits()
    # The product labels are 25 MB/file and 64 MB/message; runtime limits use binary byte values.
    assert limits.max_file_bytes == 25 * 1024 * 1024
    assert limits.max_attachments_per_message == 8
    assert limits.max_message_attachment_bytes == 64 * 1024 * 1024
    assert limits.max_pdf_pages == 200
    assert limits.max_pptx_slides == 150
    assert limits.max_xlsx_nonempty_cells == 100_000
    assert limits.max_visual_items_per_request == 6


def test_message_or_attachment_is_required_but_either_may_be_empty():
    validate_chat_input("", ["a64ccead-38f5-4cb0-bbe7-e3f9177cd6d2"])
    validate_chat_input("请总结", [])
    with pytest.raises(ValueError, match="message_or_attachment_required"):
        validate_chat_input("  ", [])


def test_status_values_are_stable():
    assert {item.value for item in AttachmentStatus} == {
        "receiving", "stored", "processing", "ready", "rejected", "failed"
    }


def test_error_codes_are_stable_and_complete():
    assert {item.value for item in AttachmentErrorCode} == {
        "unsupported_type", "too_large", "complexity_limit", "encrypted", "corrupt",
        "storage_failed", "parse_failed", "parse_timeout", "vision_unavailable",
        "attachment_not_ready", "attachment_expired", "attachment_already_attached",
    }
```

- [ ] **Step 2: Write failing schema tests**

Assert that both `attachment_schema_sql()` and `db/init.sql` define all four tables, foreign-key cascades, status/lifecycle checks, `(turn_id, ordinal)` uniqueness, `client_upload_id` uniqueness, expiration indexes, chunk locator JSONB, and vector-compatible embedding storage.

- [ ] **Step 3: Run RED tests**

Run:

```bash
python3 -m pytest -q \
  runtime_api/tests/test_attachment_models.py \
  runtime_api/tests/test_attachment_schema.py
```

Expected: FAIL with `ModuleNotFoundError: app.attachments` and missing schema assertions.

- [ ] **Step 4: Implement the domain types and transition map**

Use exact constants:

```python
ALLOWED_TRANSITIONS = {
    AttachmentStatus.RECEIVING: {AttachmentStatus.STORED, AttachmentStatus.REJECTED, AttachmentStatus.FAILED},
    AttachmentStatus.STORED: {AttachmentStatus.PROCESSING, AttachmentStatus.REJECTED, AttachmentStatus.FAILED},
    AttachmentStatus.PROCESSING: {AttachmentStatus.READY, AttachmentStatus.REJECTED, AttachmentStatus.FAILED},
    AttachmentStatus.READY: {AttachmentStatus.PROCESSING},
    AttachmentStatus.REJECTED: set(),
    AttachmentStatus.FAILED: {AttachmentStatus.PROCESSING},
}

DEFAULT_ATTACHMENT_ONLY_INSTRUCTION = "请识别并概括这些附件的内容，并标明关键信息来自哪个文件和位置。"
```

Define `TextPart`, `ImageUrlPart`, `ChatContent`, `AttachmentPublic`, and `AttachmentTraceSummary` so content cannot regress to `dict[str, str]`.

- [ ] **Step 5: Implement upgrade-safe and fresh-install schemas**

`chat_attachments` must include `client_upload_id`, `status`, `lifecycle`, processing/error timestamps, and only relative paths. Add `chat_attachment_derivatives`, `chat_attachment_chunks`, and `assistant_turn_attachments` exactly as specified. `ensure_attachment_schema()` runs during FastAPI lifespan after assistant context schema creation.

- [ ] **Step 6: Run GREEN tests**

Run the Task 1 pytest command. Expected: PASS with all schema and contract assertions.

- [ ] **Step 7: Commit Task 1**

```bash
git add runtime_api/app/attachments/__init__.py \
  runtime_api/app/attachments/models.py \
  runtime_api/app/attachments/schema.py \
  runtime_api/tests/test_attachment_models.py \
  runtime_api/tests/test_attachment_schema.py \
  runtime_api/app/main.py db/init.sql
git commit -m "feat: define chat attachment contracts and schema"
```

## Task 2: Streamed Private Storage and Hostile-File Detection

**Files:**
- Create: `runtime_api/app/attachments/storage.py`
- Create: `runtime_api/app/attachments/detection.py`
- Create: `runtime_api/tests/test_attachment_storage.py`
- Create: `runtime_api/tests/test_attachment_detection.py`
- Create: `runtime_api/tests/attachment_fixture_factory.py`
- Modify: `runtime_api/requirements.txt`

- [ ] **Step 1: Write failing storage tests**

Cover chunked writes, immediate size abort, SHA-256 correctness, `.part` cleanup on disconnect, `fsync` plus same-filesystem atomic rename, randomized server filename, relative path persistence, and refusal to resolve a path outside `NOMI_ATTACHMENT_ROOT`.

```python
def test_stream_writer_aborts_before_consuming_bytes_after_limit(tmp_path):
    source = CountingStream([b"a" * 8, b"b" * 8, b"c" * 8])
    with pytest.raises(AttachmentRejected) as error:
        write_streamed_original(source, tmp_path, uuid.uuid4(), max_bytes=16)
    assert error.value.code == "too_large"
    assert source.read_count == 3
    assert list((tmp_path / "temporary").glob("*.part")) == []
```

- [ ] **Step 2: Write failing detection/security tests**

Use generated fixtures to verify PNG/JPEG/WebP/GIF, PDF, DOCX, PPTX, XLSX, CSV, TXT, and MD acceptance; reject renamed executables, `.doc/.ppt/.xls`, ZIP traversal, ZIP bombs, encrypted Office/PDF, corrupt containers, decompression limit breaches, oversized image dimensions, and unsupported scripts with stable Chinese-safe errors.

- [ ] **Step 3: Run RED tests**

```bash
python3 -m pytest -q \
  runtime_api/tests/test_attachment_storage.py \
  runtime_api/tests/test_attachment_detection.py
```

Expected: FAIL because storage and detection modules do not exist.

- [ ] **Step 4: Implement storage and detection**

Read and hash in 256 KiB chunks. Store under `originals/<first-two-id-chars>/<attachment-id>/<generated-name>`. Normalize display names with Unicode NFC, remove separators/control characters, preserve a safe final extension, and cap display length without using it for identity.

Validate Office ZIP entries before parser dispatch:

```python
ZIP_LIMITS = ZipLimits(
    max_entries=10_000,
    max_entry_uncompressed_bytes=64 * 1024 * 1024,
    max_total_uncompressed_bytes=256 * 1024 * 1024,
    max_compression_ratio=200.0,
)
```

- [ ] **Step 5: Add exact dependencies**

Add `python-multipart`, `Pillow`, `pypdfium2`, `openpyxl`, and `charset-normalizer` with pinned compatible versions. Do not add full Docling.

- [ ] **Step 6: Run GREEN tests and dependency import smoke test**

```bash
python3 -m pytest -q runtime_api/tests/test_attachment_storage.py runtime_api/tests/test_attachment_detection.py
python3 -c "from PIL import Image; import pypdfium2, openpyxl, multipart, charset_normalizer"
```

Expected: both commands exit 0; no original fixture bytes appear in pytest output.

- [ ] **Step 7: Commit Task 2**

```bash
git add runtime_api/app/attachments/storage.py \
  runtime_api/app/attachments/detection.py \
  runtime_api/tests/test_attachment_storage.py \
  runtime_api/tests/test_attachment_detection.py \
  runtime_api/tests/attachment_fixture_factory.py \
  runtime_api/requirements.txt
git commit -m "feat: add private streamed attachment storage"
```

## Task 3: Upload API, Draft Idempotency, Authentication, and Progress

**Files:**
- Create: `runtime_api/app/attachments/repository.py`
- Create: `runtime_api/app/attachments/service.py`
- Create: `runtime_api/app/attachments/router.py`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_attachment_api.py`

- [ ] **Step 1: Write failing API tests**

Test `POST /api/chat/attachments` with and without `X-Par-Password`, valid multipart upload, attachment-only metadata, oversized upload, interrupted upload, duplicate `client_upload_id`, reused upload ID with different bytes, rejected file, and response redaction.

```python
def test_repeated_client_upload_id_returns_same_draft(client, png_bytes):
    headers = {"X-Par-Password": "par-dev"}
    first = client.post(
        "/api/chat/attachments",
        headers=headers,
        files={"file": ("图.png", png_bytes, "image/png")},
        data={"client_upload_id": "android-7f9d"},
    )
    second = client.post(
        "/api/chat/attachments",
        headers=headers,
        files={"file": ("图.png", png_bytes, "image/png")},
        data={"client_upload_id": "android-7f9d"},
    )
    assert first.status_code == second.status_code == 202
    assert first.json()["attachment_id"] == second.json()["attachment_id"]
    assert "storage_relative_path" not in first.text
```

- [ ] **Step 2: Run RED test**

```bash
python3 -m pytest -q runtime_api/tests/test_attachment_api.py -k upload
```

Expected: FAIL with 404 for `/api/chat/attachments`.

- [ ] **Step 3: Implement the injected router and upload transaction**

`create_attachment_router(connection_factory, password_guard, storage, queue)` owns only attachment routes. The service inserts `receiving`, streams and validates bytes, atomically stores the original, updates `stored`, sets `expires_at = now() + interval '24 hours'`, and queues parsing. A duplicate `client_upload_id` returns the existing safe DTO only when upload identity matches; a conflicting retry returns `409 client_upload_id_conflict`.

- [ ] **Step 4: Verify RED becomes GREEN**

Run the Task 3 pytest command. Expected: PASS and zero absolute paths/base64 values in responses.

- [ ] **Step 5: Commit Task 3**

```bash
git add runtime_api/app/attachments/repository.py \
  runtime_api/app/attachments/service.py \
  runtime_api/app/attachments/router.py \
  runtime_api/tests/test_attachment_api.py \
  runtime_api/app/main.py
git commit -m "feat: expose authenticated attachment drafts"
```

## Task 4: Bounded Queue, Worker State Machine, and Draft Cleanup

**Files:**
- Create: `runtime_api/app/attachments/queue.py`
- Create: `runtime_api/app/attachments/worker.py`
- Create: `runtime_api/app/attachments/worker_entrypoint.py`
- Create: `runtime_api/tests/test_attachment_worker.py`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Write failing worker tests**

Verify one queue item per attachment/processing version, `stored -> processing -> ready`, parser rejection, safe failure, timeout, retry lease, worker crash recovery, expired draft cleanup, orphan `.part` cleanup, and attached-file exclusion from draft cleanup.

```python
def test_worker_failure_isolated_and_next_job_runs(worker, repo):
    first = repo.seed_stored("corrupt.pdf")
    second = repo.seed_stored("valid.txt")
    worker.run_once(first.id)
    worker.run_once(second.id)
    assert repo.get(first.id).status == "failed"
    assert repo.get(second.id).status == "ready"
    assert repo.get(first.id).error_detail_safe == "文件解析失败，可重试或重新选择文件。"
```

- [ ] **Step 2: Run RED test**

```bash
python3 -m pytest -q runtime_api/tests/test_attachment_worker.py
```

Expected: FAIL because queue/worker modules are absent.

- [ ] **Step 3: Implement bounded worker semantics**

Use Redis lists/leases and database row locks. Set defaults through environment variables:

```text
ATTACHMENT_LIGHTWEIGHT_CONCURRENCY=2
ATTACHMENT_OFFICE_CONCURRENCY=1
ATTACHMENT_VISION_CONCURRENCY=1
ATTACHMENT_PARSE_TIMEOUT_SECONDS=120
ATTACHMENT_DRAFT_TTL_SECONDS=86400
```

The worker process must be stateless. Its periodic maintenance deletes expired drafts and stale receiving files, first marking lifecycle `deleted`, then removing physical files, then recording completion.

- [ ] **Step 4: Add the Compose worker without starving chat**

Add an `attachment-worker` service built from `runtime_api/Dockerfile`, command `python -m app.attachments.worker_entrypoint`, shared `attachment_data` volume, `mem_limit: 768m`, `cpus: 0.75`, non-root user, read-only application directory, writable attachment/temp mounts, and health-independent restart policy. Mount the same attachment volume read-only in runtime API except for its upload paths where writes are required.

- [ ] **Step 5: Run GREEN tests and Compose validation**

```bash
python3 -m pytest -q runtime_api/tests/test_attachment_worker.py
docker compose config --quiet
```

Expected: PASS; Compose resolves one shared named attachment volume and does not expose it through nginx.

- [ ] **Step 6: Commit Task 4**

```bash
git add runtime_api/app/attachments/queue.py \
  runtime_api/app/attachments/worker.py \
  runtime_api/app/attachments/worker_entrypoint.py \
  runtime_api/tests/test_attachment_worker.py \
  docker-compose.yml
git commit -m "feat: process attachment drafts in bounded worker"
```

## Task 5: Implement and Semantically Verify Every V1 Parser

**Files:**
- Create: `runtime_api/app/attachments/parsers/__init__.py`
- Create: `runtime_api/app/attachments/parsers/common.py`
- Create: `runtime_api/app/attachments/parsers/image.py`
- Create: `runtime_api/app/attachments/parsers/pdf.py`
- Create: `runtime_api/app/attachments/parsers/docx.py`
- Create: `runtime_api/app/attachments/parsers/pptx.py`
- Create: `runtime_api/app/attachments/parsers/spreadsheet.py`
- Create: `runtime_api/app/attachments/parsers/text.py`
- Create: `runtime_api/tests/test_attachment_parsers.py`
- Create: `runtime_api/tests/fixtures/attachments/README.md`
- Modify: `runtime_api/app/attachments/worker.py`

- [ ] **Step 1: Generate deterministic fixtures with known facts and locators**

Generate fixtures in pytest temporary directories, including rotated JPEG, animated GIF, digital PDF, scanned PDF page, 21-page PDF, DOCX headings/table/link, 31-slide PPTX with notes, XLSX formula/value/sheets, long CSV, UTF-8/GB18030 text, Markdown code block, corrupt and encrypted examples. Record expected facts in the fixture README without storing personal data.

- [ ] **Step 2: Write failing semantic parser tests**

Assertions must check content and location, not only non-empty output:

```python
def test_pptx_preserves_slide_and_notes_locator(pptx_fixture):
    result = parse_pptx(pptx_fixture)
    revenue = next(chunk for chunk in result.chunks if "42%" in chunk.text)
    assert revenue.locator == {"slide": 12, "section": "notes"}
    assert result.manifest["slide_count"] == 31
    assert result.requires_default_visual_sweep is False


def test_xlsx_formula_and_value_keep_sheet_range(xlsx_fixture):
    result = parse_xlsx(xlsx_fixture)
    budget = next(chunk for chunk in result.chunks if "125000" in chunk.text)
    assert budget.locator["sheet"] == "预算"
    assert budget.locator["range"] == "A2:D18"
```

- [ ] **Step 3: Run RED test**

```bash
python3 -m pytest -q runtime_api/tests/test_attachment_parsers.py
```

Expected: FAIL because parser registry and implementations are missing.

- [ ] **Step 4: Implement parsers with bounded outputs**

All parsers return `ParseResult(manifest, derivatives, chunks, warnings, metrics)`. Use locators exactly suited to each format. PDF sets per-page text density and `suspected_scan`; image parser applies EXIF orientation and creates max-edge-2048 previews; GIF keeps at most four visually distinct frames; XLSX uses read-only mode and stops at 100,000 non-empty cells; CSV caps row and field length; Markdown preserves line/title/code-block boundaries but does not render raw HTML as trusted UI.

- [ ] **Step 5: Integrate parser dispatch and processing version**

Worker dispatches by detected type, stores derivative metadata and chunks in one transaction, then marks `ready`. Reprocessing writes a new processing version and never silently mutates old provenance.

Cache `visual_result` derivatives by original SHA-256, selected locator set, user-question hash, model identity, and processing version. A cache hit may avoid a repeated visual model call but must retain the current turn/attachment provenance in trace output.

- [ ] **Step 6: Run GREEN semantic tests**

Run the Task 5 pytest command. Expected: every known fixture fact and stable locator matches; rejected fixtures have the approved safe error code.

- [ ] **Step 7: Commit Task 5**

```bash
git add runtime_api/app/attachments/parsers \
  runtime_api/tests/test_attachment_parsers.py \
  runtime_api/tests/fixtures/attachments/README.md \
  runtime_api/app/attachments/worker.py
git commit -m "feat: parse supported chat attachment formats"
```

## Task 6: Status, Preview, Content, Retry, and Physical Lifecycle APIs

**Files:**
- Modify: `runtime_api/app/attachments/router.py`
- Modify: `runtime_api/app/attachments/service.py`
- Modify: `runtime_api/app/attachments/repository.py`
- Test: `runtime_api/tests/test_attachment_lifecycle_api.py`

- [ ] **Step 1: Write failing lifecycle API tests**

Cover authenticated metadata polling, image thumbnail preview, non-image generic metadata, original download, RFC-safe Chinese filenames, range-independent streaming, retry from failed original, refusal to retry missing/corrupt original, draft deletion, attached deletion refusal, expired draft, and missing ID.

- [ ] **Step 2: Run RED test**

```bash
python3 -m pytest -q runtime_api/tests/test_attachment_lifecycle_api.py
```

Expected: FAIL with 404/method-not-allowed responses.

- [ ] **Step 3: Implement all lifecycle endpoints**

Implement:

```text
GET    /api/chat/attachments/{id}
GET    /api/chat/attachments/{id}/preview
GET    /api/chat/attachments/{id}/content
POST   /api/chat/attachments/{id}/retry
DELETE /api/chat/attachments/{id}
```

Set `Content-Disposition`, `X-Content-Type-Options: nosniff`, private cache headers, and no absolute-path response fields. Retry transitions `failed -> processing` from the durable original using one deduplicated queue job.

- [ ] **Step 4: Run GREEN test**

Run the Task 6 pytest command. Expected: PASS; unauthorized preview/content requests return 401 and no file bytes.

- [ ] **Step 5: Commit Task 6**

```bash
git add runtime_api/app/attachments/router.py \
  runtime_api/app/attachments/service.py \
  runtime_api/app/attachments/repository.py \
  runtime_api/tests/test_attachment_lifecycle_api.py
git commit -m "feat: manage attachment lifecycle and downloads"
```

## Task 7: Atomic User-Turn Binding and Shared HTTP/WebSocket Submission

**Files:**
- Modify: `runtime_api/app/attachments/service.py`
- Create: `runtime_api/tests/test_attachment_chat_binding.py`
- Modify: `runtime_api/app/main.py`
- Modify: `runtime_api/tests/test_realtime_ws.py`

- [ ] **Step 1: Write failing transaction and idempotency tests**

Test attachment-only, mixed text/attachments, order preservation, duplicate IDs, count/aggregate limits, not-ready/expired/deleted/attached drafts, one invalid attachment among valid attachments, concurrent submission of the same draft, and stable `client_request_id` reuse.

```python
def test_one_invalid_attachment_rolls_back_turn_and_all_bindings(repo, submission):
    ready = repo.seed_ready_draft(byte_size=100)
    failed = repo.seed_failed_draft(byte_size=100)
    with pytest.raises(AttachmentSubmissionError) as error:
        submission.commit_user_turn("分析", [ready.id, failed.id], "request-1")
    assert error.value.code == "attachment_not_ready"
    assert repo.count_turns() == 0
    assert repo.count_bindings() == 0
    assert repo.get(ready.id).lifecycle == "draft"
```

- [ ] **Step 2: Write failing transport-parity tests**

Send the same valid payload through `/api/chat` and `/ws`; assert both persist an ordered relation and both reject the same invalid payload with the same error code. Assert blank text plus ready attachment succeeds on both transports.

- [ ] **Step 3: Run RED tests**

```bash
python3 -m pytest -q \
  runtime_api/tests/test_attachment_chat_binding.py \
  runtime_api/tests/test_realtime_ws.py -k attachment
```

Expected: FAIL because `ChatIn.message` still has `min_length=1`, attachment IDs are absent, and WebSocket ignores them.

- [ ] **Step 4: Implement one shared submission service**

Change `ChatIn.message` to allow an empty string, add a unique ordered `attachment_ids: list[UUID]`, and make both transports call:

```python
submission = attachment_service.submit_user_turn(
    conn=conn,
    redis_obj=redis_obj,
    message=body.message,
    attachment_ids=body.attachment_ids,
    conversation_id=body.conversation_id,
    client_type=body.client_type,
    client_request_id=body.client_request_id,
)
```

Inside one transaction: lock drafts with `FOR UPDATE`, validate all, call `persist_assistant_turn`, insert ordered relations, mark lifecycle attached, clear expiration, commit. Preserve the existing tool-call idempotency key and return the existing user turn on repeated `client_request_id`.

- [ ] **Step 5: Run GREEN parity tests**

Run the Task 7 pytest command. Expected: PASS; HTTP and WebSocket produce identical persisted attachment relations and stable errors.

- [ ] **Step 6: Commit Task 7**

```bash
git add runtime_api/app/attachments/service.py \
  runtime_api/tests/test_attachment_chat_binding.py \
  runtime_api/app/main.py \
  runtime_api/tests/test_realtime_ws.py
git commit -m "feat: atomically bind attachments to chat turns"
```

## Task 8: History, Retry Without Duplicate User Turns, and Conversation Deletion

**Files:**
- Modify: `runtime_api/app/attachments/repository.py`
- Modify: `runtime_api/app/attachments/service.py`
- Modify: `runtime_api/app/main.py`
- Create: `runtime_api/tests/test_attachment_history_and_retry.py`

- [ ] **Step 1: Write failing history/retry/deletion tests**

Verify ordered public attachment metadata on user messages, no attachment list on unrelated assistant messages, message IDs unchanged across history requests, model failure preserving the user turn, retry by original user turn ID, no second user turn/binding, conversation deletion cascading database rows and scheduling physical cleanup, and another conversation remaining intact.

- [ ] **Step 2: Run RED test**

```bash
python3 -m pytest -q runtime_api/tests/test_attachment_history_and_retry.py
```

Expected: FAIL because history omits attachments and assistant retry cannot target an existing user turn.

- [ ] **Step 3: Implement server-authoritative history and retry**

Batch-load attachment metadata for returned turn IDs to avoid N+1 queries. Add an authenticated assistant retry endpoint that accepts the existing user turn ID, rebuilds evidence from its bound attachments, and creates only the assistant result/error. The retry response contains the same `conversation_id`, `user_turn_id`, and attachment IDs.

- [ ] **Step 4: Implement eventual physical cleanup after conversation deletion**

Database cascades remove relation/chunk/derivative rows. Before commit, enqueue relative file keys into a cleanup outbox so worker deletion survives process failure. Never construct deletion paths from user filenames.

- [ ] **Step 5: Run GREEN test**

Run the Task 8 pytest command. Expected: PASS and no duplicate user turn after two model retries.

- [ ] **Step 6: Commit Task 8**

```bash
git add runtime_api/app/attachments/repository.py \
  runtime_api/app/attachments/service.py \
  runtime_api/app/main.py \
  runtime_api/tests/test_attachment_history_and_retry.py
git commit -m "feat: synchronize attachment history and retries"
```

## Task 9: Evidence Planning, Hybrid Retrieval, Visual Escalation, and Citations

**Files:**
- Create: `runtime_api/app/attachments/retrieval.py`
- Create: `runtime_api/app/attachments/citations.py`
- Create: `runtime_api/tests/test_attachment_retrieval.py`
- Modify: `runtime_api/app/main.py`

- [ ] **Step 1: Write failing evidence-plan tests**

Cover full content at `<= 24K` tokens, hybrid retrieval above threshold, multiple-attachment minimum quotas, PDF >20/PPTX >30 behavior, scan/diagram/layout visual escalation, maximum six visuals, 64K attachment evidence budget, 256K total budget integration, excluded-evidence reasons, and explicit page-by-page task routing.

```python
def test_large_attachment_cannot_starve_smaller_attachment():
    plan = plan_attachment_evidence(
        question="比较两份预算的风险",
        attachments=[large_budget_fixture(), small_budget_fixture()],
        total_attachment_budget=64_000,
    )
    assert {item.attachment_id for item in plan.text_items} == {"large", "small"}
    assert plan.tokens_by_attachment["small"] > 0
    assert plan.total_tokens <= 64_000
```

- [ ] **Step 2: Write failing citation tests**

Check exact labels for PDF page, PPTX slide, DOCX section, XLSX range, image filename, and partial coverage statements. Reject a generated citation whose evidence ID was not selected.

- [ ] **Step 3: Run RED tests**

```bash
python3 -m pytest -q \
  runtime_api/tests/test_attachment_retrieval.py
```

Expected: FAIL because attachment evidence planner and citations are absent.

- [ ] **Step 4: Implement deterministic evidence selection**

Use existing embeddings plus keyword scoring for hybrid retrieval. Deduplicate by content hash, diversify by locator, assign each attachment a minimum quota, then globally rerank. Return `EvidencePlan` with selected text items, requested rendered pages, exclusions, coverage, token counts, and stable evidence IDs.

- [ ] **Step 5: Integrate with the existing parallel context plan**

Only retrieve attachment evidence when the current user turn has attachments, explicitly references a prior attachment, or the route requires file evidence. Preserve recent 15 rounds and existing memory/agenda/task decisions. Run independent attachment, memory, agenda, task, and source retrieval in parallel after route planning.

For an explicit request to inspect every page/slide, create an `attachment_full_inspection` run in the existing durable task system. Process bounded page batches through the attachment worker, persist completed/failed locators and progress, expose the existing task-status contract to both clients, and synthesize the final answer only after the requested coverage reaches a terminal state. A partial terminal result must list unprocessed or failed locators.

- [ ] **Step 6: Run GREEN semantic tests**

Run Task 9 tests. Expected: PASS; traces identify selected and excluded locators, and no answer can cite an unselected page.

- [ ] **Step 7: Commit Task 9**

```bash
git add runtime_api/app/attachments/retrieval.py \
  runtime_api/app/attachments/citations.py \
  runtime_api/tests/test_attachment_retrieval.py \
  runtime_api/app/main.py
git commit -m "feat: select traceable attachment evidence"
```

## Task 10: Structured Qwen Multimodal Content and Formal-Content Streaming

**Files:**
- Create: `runtime_api/app/attachments/model_content.py`
- Create: `runtime_api/tests/test_attachment_model_content.py`
- Modify: `runtime_api/app/model_client.py`
- Modify: `runtime_api/app/model_gateway.py`
- Modify: `runtime_api/app/main.py`

- [ ] **Step 1: Write failing structured-content tests**

Verify plain text remains a string, visual messages become ordered `text`/`image_url` parts, private image bytes are base64-encoded only in the final provider request, input objects are not stringified, reasoning content is ignored, `enable_thinking=False` is passed using the provider-supported request parameter, and no base64 enters traces/history/log captures.

```python
def test_visual_content_stays_structured_until_provider_boundary(tmp_path):
    image = tmp_path / "page.png"
    image.write_bytes(valid_png_bytes())
    content = build_chat_content("说明图表", [visual_evidence(image, "architecture.png")])
    assert content[0] == {"type": "text", "text": "说明图表"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["private_path"] == image
    request = qwen_provider_content(content)
    assert request[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "base64" not in json.dumps(attachment_trace(content))
```

- [ ] **Step 2: Run RED tests**

```bash
python3 -m pytest -q runtime_api/tests/test_attachment_model_content.py
```

Expected: FAIL because model clients currently type/string-coerce every `content` value.

- [ ] **Step 3: Upgrade gateway/client protocols**

Replace `list[dict[str, str]]` with shared `ChatMessage`/`ChatContent` types. `split_system_messages` must preserve list content instead of calling `str(content)`. Only Qwen adapter boundary opens selected private images, checks they are still under the attachment root, enforces six-item limit, and emits data URLs.

- [ ] **Step 4: Enforce untrusted-evidence wrapping**

Every document text block is nested under a fixed system instruction stating it is untrusted evidence and cannot invoke tools, alter policy, or authorize side effects. Add a prompt-injection fixture that asks the model to reveal secrets and call a tool; expected route contains no tool call and answer treats it as quoted document text.

- [ ] **Step 5: Run GREEN tests and Qwen contract smoke test**

```bash
python3 -m pytest -q runtime_api/tests/test_attachment_model_content.py runtime_api/tests/test_model_non_thinking.py
```

Expected: PASS; only formal `content` chunks are emitted and stored.

- [ ] **Step 6: Commit Task 10**

```bash
git add runtime_api/app/attachments/model_content.py \
  runtime_api/tests/test_attachment_model_content.py \
  runtime_api/app/model_client.py \
  runtime_api/app/model_gateway.py \
  runtime_api/app/main.py
git commit -m "feat: send structured multimodal qwen requests"
```

## Task 11: Web Full-App Attachment Experience

**Files:**
- Create: `runtime_api/app/static/chat-attachments.js`
- Create: `runtime_api/tests_js/chat_attachments.test.cjs`
- Modify: `runtime_api/app/static/index.html`
- Modify: `runtime_api/app/static/app.js`
- Modify: `runtime_api/app/static/styles.css`
- Create: `runtime_api/tests/test_static_chat_attachments.py`

- [ ] **Step 1: Write failing pure-JavaScript state tests**

Test attachment-only send eligibility, disabled send during upload/processing, 8/64MB client limits, polling stop at terminal state, retry/remove, payload order, stable `client_upload_id`, no duplicate send after transport fallback, and history merge by message/attachment IDs.

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');
const attachments = require('../app/static/chat-attachments.js');

test('attachment-only draft becomes sendable only when every item is ready', () => {
  const draft = attachments.createDraftState();
  attachments.addSelectedFile(draft, { name: '图.png', size: 120, type: 'image/png' });
  assert.equal(attachments.canSend('', draft), false);
  attachments.markReady(draft, 0, { attachment_id: 'a-1' });
  assert.equal(attachments.canSend('', draft), true);
  assert.deepEqual(attachments.buildChatPayload('', draft).attachment_ids, ['a-1']);
});
```

- [ ] **Step 2: Write failing static contract tests**

Assert a familiar icon-only attachment button with tooltip/accessibility label, hidden `multiple` file input with approved accept list, integrated tray above composer, retry/remove controls, progress semantics, message attachment cards, and no visible instructional feature copy.

- [ ] **Step 3: Run RED tests**

```bash
node --test runtime_api/tests_js/chat_attachments.test.cjs
python3 -m pytest -q runtime_api/tests/test_static_chat_attachments.py
```

Expected: FAIL because the module and UI elements are absent.

- [ ] **Step 4: Implement upload and draft state**

Stream multipart through browser `FormData`, create one stable `client_upload_id` per selected file, poll each draft once per second only while visible and non-terminal, support retry/remove, preserve text when a file fails, and disable send until all drafts are ready. On send success, clear the local tray only after the server returns the committed user turn.

- [ ] **Step 5: Implement history and message cards**

Render image thumbnails and document cards inside their owning user message. Constrain filename to two lines, wrap URLs/content, show type/size/status, and render assistant retry after model failure without duplicating the user card. Fetch previews with `X-Par-Password`, create short-lived object URLs, revoke them when cards leave the DOM, and never place the password in preview/content query strings.

- [ ] **Step 6: Run GREEN tests and responsive browser checks**

Run Task 11 test commands, then use the existing local workbench at desktop and mobile widths. Expected: no horizontal overflow; keyboard/composer area remains stable; attachment-only and mixed payloads match API contracts.

- [ ] **Step 7: Commit Task 11**

```bash
git add runtime_api/app/static/chat-attachments.js \
  runtime_api/tests_js/chat_attachments.test.cjs \
  runtime_api/app/static/index.html \
  runtime_api/app/static/app.js \
  runtime_api/app/static/styles.css \
  runtime_api/tests/test_static_chat_attachments.py
git commit -m "feat: add attachments to web chat composer"
```

## Task 12: Android Full-App WebView File Chooser

**Files:**
- Modify: `android_app/app/src/main/java/com/par/assistant/android/WebWorkspaceActivity.java`
- Modify: `android_app/app/src/main/AndroidManifest.xml`
- Create: `android_app/app/src/test/java/com/par/assistant/android/WebWorkspaceAttachmentChooserTest.java`

- [ ] **Step 1: Write failing WebView chooser contract tests**

Test multiple selection, MIME/extension accept mapping, camera-free SAF intent, URI grant flags, cancellation callback, rotation/recreation callback cleanup, and delivery of one or many URIs to `ValueCallback<Uri[]>`.

- [ ] **Step 2: Run RED Android test**

```bash
gradle -p android_app :app:testDebugUnitTest --tests '*WebWorkspaceAttachmentChooserTest'
```

Expected: FAIL because `onShowFileChooser` is not implemented.

- [ ] **Step 3: Implement chooser lifecycle**

Use `WebChromeClient.onShowFileChooser`, `ACTION_OPEN_DOCUMENT`, `CATEGORY_OPENABLE`, and `EXTRA_ALLOW_MULTIPLE`. Cancel any stale callback before launching a new chooser. Convert clip data and single data URI to a stable ordered array, retain read permission for the active upload, and restore WebView without a white screen after picker return.

- [ ] **Step 4: Run GREEN Android test**

Run Task 12 command. Expected: PASS.

- [ ] **Step 5: Commit Task 12**

```bash
git add android_app/app/src/main/java/com/par/assistant/android/WebWorkspaceActivity.java \
  android_app/app/src/main/AndroidManifest.xml \
  android_app/app/src/test/java/com/par/assistant/android/WebWorkspaceAttachmentChooserTest.java
git commit -m "feat: bridge web attachment picker on android"
```

## Task 13: Native Floating-Chat Picker, Stream Upload, and Integrated Tray

**Files:**
- Create: `android_app/app/src/main/java/com/par/assistant/android/ChatAttachment.java`
- Create: `android_app/app/src/main/java/com/par/assistant/android/AttachmentDraft.java`
- Create: `android_app/app/src/main/java/com/par/assistant/android/AttachmentUploadRequestBody.java`
- Create: `android_app/app/src/main/java/com/par/assistant/android/AttachmentPickerActivity.java`
- Create: `android_app/app/src/main/java/com/par/assistant/android/FloatingAttachmentController.java`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/AssistantApiClient.java`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/RealtimeClient.java`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/FloatingBallService.java`
- Modify: `android_app/app/src/main/AndroidManifest.xml`
- Create: `android_app/app/src/test/java/com/par/assistant/android/AttachmentUploadRequestBodyTest.java`
- Create: `android_app/app/src/test/java/com/par/assistant/android/AssistantApiClientAttachmentTest.java`
- Create: `android_app/app/src/test/java/com/par/assistant/android/FloatingAttachmentControllerTest.java`
- Modify: `android_app/app/src/test/java/com/par/assistant/android/RealtimeClientTest.java`

- [ ] **Step 1: Write failing streamed-body tests**

Use a fake ContentResolver/input stream larger than the test buffer. Assert OkHttp writes incrementally, reports progress, closes the stream, supports cancellation, does not call a read-all helper, and preserves byte-for-byte SHA-256 at MockWebServer.

- [ ] **Step 2: Write failing API and controller tests**

Test upload/status/retry/delete DTOs, Chinese filenames, attachment-only chat payload, attachment IDs over WebSocket, HTTP fallback with the same `client_request_id`, no duplicate upload, picker cancellation, service recreation with the same local draft, processing polling, send gating, failure retry, remove, and keyboard visibility retention.

- [ ] **Step 3: Run RED Android tests**

```bash
gradle -p android_app :app:testDebugUnitTest \
  --tests '*AttachmentUploadRequestBodyTest' \
  --tests '*AssistantApiClientAttachmentTest' \
  --tests '*FloatingAttachmentControllerTest' \
  --tests '*RealtimeClientTest'
```

Expected: FAIL because the native attachment types and API fields are absent.

- [ ] **Step 4: Implement the lightweight Picker Activity**

Launch `ACTION_OPEN_DOCUMENT` with approved types and multiple selection. Return persistable URI grants plus display metadata to the service, then finish immediately. The service must retain the existing message text, tray state, panel position, and keyboard intent while the picker is open.

- [ ] **Step 5: Implement streamed upload and polling**

`AttachmentUploadRequestBody` reads a bounded byte array buffer from `ContentResolver`. `FloatingAttachmentController` owns local draft state and stable IDs; `AssistantApiClient` sends multipart and polls status; `RealtimeClient` includes ordered attachment IDs. HTTP fallback reuses IDs and never reuploads ready drafts.

- [ ] **Step 6: Implement compact floating UI**

Add an icon-only attachment button beside the composer, an integrated tray above the input, two-line ellipsized filenames, thumbnails/document icons, progress, retry/remove icons with tooltips/content descriptions, and sent attachment cards. Keep the tray/input/send row above IME and hide IME only when the user taps the message region.

- [ ] **Step 7: Run GREEN Android tests**

Run Task 13 command. Expected: PASS and MockWebServer receives exactly one upload per local draft.

- [ ] **Step 8: Commit Task 13**

```bash
git add android_app/app/src/main/java/com/par/assistant/android/ChatAttachment.java \
  android_app/app/src/main/java/com/par/assistant/android/AttachmentDraft.java \
  android_app/app/src/main/java/com/par/assistant/android/AttachmentUploadRequestBody.java \
  android_app/app/src/main/java/com/par/assistant/android/AttachmentPickerActivity.java \
  android_app/app/src/main/java/com/par/assistant/android/FloatingAttachmentController.java \
  android_app/app/src/main/java/com/par/assistant/android/AssistantApiClient.java \
  android_app/app/src/main/java/com/par/assistant/android/RealtimeClient.java \
  android_app/app/src/main/java/com/par/assistant/android/FloatingBallService.java \
  android_app/app/src/main/AndroidManifest.xml \
  android_app/app/src/test/java/com/par/assistant/android/AttachmentUploadRequestBodyTest.java \
  android_app/app/src/test/java/com/par/assistant/android/AssistantApiClientAttachmentTest.java \
  android_app/app/src/test/java/com/par/assistant/android/FloatingAttachmentControllerTest.java \
  android_app/app/src/test/java/com/par/assistant/android/RealtimeClientTest.java
git commit -m "feat: upload attachments from floating chat"
```

## Task 14: Local History Mirror and Cross-Surface Reconciliation

**Files:**
- Modify: `android_app/app/src/main/java/com/par/assistant/android/LocalChatHistoryStore.java`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/FloatingBallService.java`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/AssistantApiClient.java`
- Create: `android_app/app/src/test/java/com/par/assistant/android/LocalChatAttachmentHistoryTest.java`
- Create: `runtime_api/tests/test_attachment_history_contract.py`

- [ ] **Step 1: Write failing reconciliation tests**

Seed server messages `1..6` with attachments and local messages `2..4`. Assert reconciliation keeps local pending data, downloads `5..6`, merges attachment metadata only by `(message_id, attachment_id)`, does not infer by filename, removes server-deleted messages, and stores no original bytes/base64 locally.

- [ ] **Step 2: Run RED tests**

```bash
gradle -p android_app :app:testDebugUnitTest --tests '*LocalChatAttachmentHistoryTest'
python3 -m pytest -q runtime_api/tests/test_attachment_history_contract.py
```

Expected: FAIL because local history models have no attachment metadata.

- [ ] **Step 3: Implement safe local metadata and server-authoritative merge**

Persist only attachment ID, filename, MIME, byte size, status, kind, preview/content URL, ordinal, and owning message ID. Sent messages are reconciled from server; unsent attachment drafts remain in the originating controller and are not copied into full App WebView state.

- [ ] **Step 4: Run GREEN tests**

Run Task 14 commands. Expected: PASS; Web and floating history DTOs serialize the same ordered attachment list.

- [ ] **Step 5: Commit Task 14**

```bash
git add android_app/app/src/main/java/com/par/assistant/android/LocalChatHistoryStore.java \
  android_app/app/src/main/java/com/par/assistant/android/FloatingBallService.java \
  android_app/app/src/main/java/com/par/assistant/android/AssistantApiClient.java \
  android_app/app/src/test/java/com/par/assistant/android/LocalChatAttachmentHistoryTest.java \
  runtime_api/tests/test_attachment_history_contract.py
git commit -m "feat: reconcile attachment history across chat surfaces"
```

## Task 15: Memory Provenance, Security Regression, and Privacy-Safe Tracing

**Files:**
- Create: `runtime_api/app/attachments/trace.py`
- Modify: `runtime_api/app/main.py`
- Create: `runtime_api/tests/test_attachment_memory_provenance.py`
- Create: `runtime_api/tests/test_attachment_security.py`
- Create: `runtime_api/tests/test_attachment_trace.py`

- [x] **Step 1: Write failing memory provenance tests**

Verify upload/parse does not directly create long-term memory; a normal 15-round batch may create a durable fact; every fact derived from an attachment contains `attachment_id`, `turn_id`, locator, and processing version; reprocessing does not silently rewrite old provenance.

- [x] **Step 2: Write failing security and privacy tests**

Test prompt injection, path traversal, malicious Markdown HTML, unauthorized preview/content, logs/traces without content/base64/absolute paths/API keys, safe error messages, parser timeout isolation, and no tool route caused only by document instructions.

- [x] **Step 3: Write failing trace tests**

Assert upload/hash/store/parse/chunk/embed/retrieve/render timings; selected/excluded locators; visual count; upstream first chunk, formal first character, total latency; request/client/turn IDs; retry count; and no raw private content.

- [x] **Step 4: Run RED tests**

```bash
python3 -m pytest -q \
  runtime_api/tests/test_attachment_memory_provenance.py \
  runtime_api/tests/test_attachment_security.py \
  runtime_api/tests/test_attachment_trace.py
```

Expected: FAIL because provenance/trace integration is incomplete.

- [x] **Step 5: Implement provenance and trace integration**

Add attachment provenance to existing 15-round memory batch inputs only when a selected durable fact depends on it. Emit IDs, types, counts, locators, hashes, versions, statuses, timing, and exclusion reasons; never emit extracted text, original filenames when unnecessary, base64, credentials, or paths.

- [x] **Step 6: Run GREEN tests**

Run Task 15 command. Expected: PASS; privacy scan finds no forbidden material.

- [x] **Step 7: Commit Task 15**

```bash
git add runtime_api/app/attachments/trace.py \
  runtime_api/app/main.py \
  runtime_api/tests/test_attachment_memory_provenance.py \
  runtime_api/tests/test_attachment_security.py \
  runtime_api/tests/test_attachment_trace.py
git commit -m "feat: trace attachment evidence and memory provenance"
```

## Task 16: Docker Runtime, Resource Limits, and Full Automated Regression

**Files:**
- Modify: `runtime_api/Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Create: `runtime_api/tests/test_attachment_deployment_contract.py`
- Create: `runtime_api/tests/test_attachment_e2e.py`
- Create: `docs/superpowers/reports/2026-07-13-unified-chat-attachments-implementation-gaps.md`

- [ ] **Step 1: Write failing deployment contract tests**

Assert non-root worker, LibreOffice present only where needed, attachment root outside static/source directories, shared named volume, concurrency settings, no nginx volume exposure, health checks, and 4-core/8GB production resource ceilings. A 2-core/4GB host may be documented as a non-acceptance compatibility profile, but tests must not remove core capabilities to fit it.

- [ ] **Step 2: Write failing backend E2E tests**

For every supported type, execute upload -> poll -> send -> context -> model stub -> cited answer -> history -> retry/delete. Include pure attachment, text plus attachment, multiple attachments, scan visual fallback, large PDF/PPTX retrieval, table locator, prompt injection, model failure, network retry, and conversation deletion.

- [ ] **Step 3: Run RED tests**

```bash
python3 -m pytest -q \
  runtime_api/tests/test_attachment_deployment_contract.py \
  runtime_api/tests/test_attachment_e2e.py
```

Expected: FAIL until Docker/runtime integration and all preceding tasks are complete.

- [ ] **Step 4: Complete Docker runtime**

Install LibreOffice headless and required fonts/render libraries, run API/worker as non-root, create only required writable directories, and document these settings in `.env.example`:

```text
NOMI_ATTACHMENT_ROOT=/app/attachments
ATTACHMENT_MAX_FILE_BYTES=26214400
ATTACHMENT_MAX_MESSAGE_BYTES=67108864
ATTACHMENT_MAX_PER_MESSAGE=8
ATTACHMENT_DRAFT_TTL_SECONDS=86400
ATTACHMENT_LIGHTWEIGHT_CONCURRENCY=2
ATTACHMENT_OFFICE_CONCURRENCY=1
ATTACHMENT_VISION_CONCURRENCY=1
ATTACHMENT_PARSE_TIMEOUT_SECONDS=120
```

- [ ] **Step 5: Run full automated suite**

```bash
python3 -m pytest -q runtime_api/tests
node --test runtime_api/tests_js/chat_attachments.test.cjs
gradle -p android_app :app:testDebugUnitTest
docker compose config --quiet
docker compose build runtime-api attachment-worker
```

Expected: every command exits 0. Record unrelated pre-existing failures separately rather than weakening attachment assertions.

- [ ] **Step 6: Maintain the implementation gap report**

For every unmet real-provider, cloud, or device condition, record requirement, code status, exact blocker, reproduction command, evidence, owner, and next action. The report must not mark an item complete because only a mock passed.

- [ ] **Step 7: Commit Task 16**

```bash
git add runtime_api/Dockerfile docker-compose.yml .env.example \
  runtime_api/tests/test_attachment_deployment_contract.py \
  runtime_api/tests/test_attachment_e2e.py \
  docs/superpowers/reports/2026-07-13-unified-chat-attachments-implementation-gaps.md
git commit -m "test: cover attachment deployment and e2e flow"
```

## Task 17: Cloud, Qwen, and Android Real-Device Acceptance

**Files:**
- Create: `docs/superpowers/reports/2026-07-13-unified-chat-attachments-real-device-results.md`
- Modify when evidence requires a fix: only the file and test owning that failed behavior

- [ ] **Step 1: Prepare a privacy-safe real-file matrix**

Use at least one non-sensitive real PNG/JPEG, PDF, scanned PDF, DOCX, PPTX, XLSX, CSV, TXT, and MD. Record filename hash, byte size, page/slide/sheet count, known expected facts, expected locators, and whether visual escalation is required.

- [ ] **Step 2: Deploy to the private cloud and verify health**

Build and start `postgres`, `redis`, `runtime-api`, `attachment-worker`, `chromium-runtime`, and `nginx`. Verify API health during a 25MB upload and a 31-slide parse. Confirm no API restart/OOM and no high-priority chat starvation.

- [ ] **Step 3: Verify Qwen semantic quality and latency**

For image, scan, diagram, table, and mixed-document questions, inspect the actual provider request trace and answer. Confirm selected evidence/visual count, factual correctness, stable citations, stated partial coverage, hidden reasoning, `enable_thinking=False`, first upstream chunk, first formal character, and total latency. Acceptance targets:

```text
small digital document parse P95 <= 5s
image/scanned-page first formal answer character P95 <= 12s
visual items per request <= 6
attachment evidence <= 64K tokens
```

- [ ] **Step 4: Verify full App on a real Android device**

Select one/many files and images, pure attachment and mixed text, upload/processing progress, failure/retry/remove, Chinese/long filenames, keyboard movement, message cards, preview/download, app restart, offline/reconnect, model failure/retry, and no duplicate upload/send.

- [ ] **Step 5: Verify floating chat on the same device**

Repeat the full App matrix through the native picker. Switch to full App and confirm the same committed message/attachments appear. Switch back, restart the app/service, and confirm server history wins while unsent drafts never leak between surfaces.

- [ ] **Step 6: Verify destructive lifecycle**

Delete a draft and confirm immediate inaccessibility plus physical cleanup. Delete a test conversation and confirm attachment relations/chunks/derivatives disappear and originals are eventually removed, while unrelated conversation files remain available.

- [ ] **Step 7: Record output correctness, not only completion**

For every case record input, expected fact, actual selected evidence, actual model content type, answer, citations, UI screenshot, trace ID, timing, and verdict. A case fails if the answer is generic, invents a fact, cites an unselected location, silently drops an attachment, overflows UI, or only returns a successful status without useful content.

- [ ] **Step 8: Fix failures with a new RED test before code changes**

For each failure, add the smallest reproducing automated test, observe it fail, apply the minimal fix, rerun focused and full suites, then update both gap and real-device reports.

- [ ] **Step 9: Commit real-environment evidence**

```bash
git add docs/superpowers/reports/2026-07-13-unified-chat-attachments-real-device-results.md \
  docs/superpowers/reports/2026-07-13-unified-chat-attachments-implementation-gaps.md
git commit -m "test: verify chat attachments on cloud and android"
```

## Task 18: Nomi Built-In Direct File Viewer

**Files:**
- Create: `runtime_api/file_viewer/package.json`
- Create: `runtime_api/file_viewer/package-lock.json`
- Create: `runtime_api/file_viewer/build-assets.mjs`
- Create: `runtime_api/app/static/file-viewer-links.js`
- Create: `runtime_api/app/static/viewer.html`
- Create: `runtime_api/app/static/viewer.css`
- Create: `runtime_api/app/static/viewer.js`
- Create: `runtime_api/tests/test_static_file_viewer.py`
- Create: `runtime_api/tests_js/file_viewer_links.test.cjs`
- Create: `android_app/app/src/main/java/com/par/assistant/android/FileViewerUrls.java`
- Create: `android_app/app/src/main/java/com/par/assistant/android/NomiFileViewerActivity.java`
- Create: `android_app/app/src/test/java/com/par/assistant/android/FileViewerUrlsTest.java`
- Create: `android_app/app/src/test/java/com/par/assistant/android/NomiFileViewerContractTest.java`
- Modify: `runtime_api/Dockerfile`
- Modify: `runtime_api/app/main.py`
- Modify: `runtime_api/app/static/index.html`
- Modify: `runtime_api/app/static/app.js`
- Modify: `android_app/app/src/main/AndroidManifest.xml`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/FloatingBallService.java`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/WebWorkspaceActivity.java`
- Modify: existing static and Android contract tests that require external download/open behavior

- [x] **Step 1: Write failing source and viewer URL tests**

Test that only the two approved relative API forms are accepted, UUID/artifact IDs are canonicalized, query values are encoded, external/protocol-relative/traversal/arbitrary API paths are rejected, and passwords never appear in the viewer URL.

- [x] **Step 2: Write failing Web/API deployment tests**

Assert `/viewer` exists; HTML loads only self-hosted assets; JS fetches the original with `X-Par-Password`, constructs a `File`, mounts Flyfish, destroys it on unload, exposes Chinese loading/error/retry states, and never converts to PDF or calls a CDN. Assert Docker pins `@file-viewer/web-full@2.1.29` and copies only the six approved renderer groups and four vendor groups.

- [x] **Step 3: Write failing Android contract tests**

Assert `NomiFileViewerActivity` is registered, uses `adjustResize`, exposes password/close bridges only to the trusted origin, blocks external navigation, restores the floating service on close, and accepts both attachment and artifact source URLs. Assert default artifact/attachment clicks no longer use `Intent.ACTION_VIEW` or `ArtifactOpenActivity`.

- [x] **Step 4: Run RED tests**

```bash
python3 -m pytest -q runtime_api/tests/test_static_file_viewer.py runtime_api/tests/test_static_workbench_agenda_tab.py -k 'viewer or artifact'
node --test runtime_api/tests_js/file_viewer_links.test.cjs
gradle -p android_app :app:testDebugUnitTest --tests '*FileViewer*' --tests '*FloatingPanelAppEntryContractTest*'
```

Expected: failures identify every missing viewer route, asset, URL helper, Android Activity, bridge, and click integration. No production implementation is written before these failures are observed.

- [x] **Step 5: Implement the self-hosted viewer asset build**

Pin the exact Flyfish package and generate a reproducible npm lock. The asset script copies only `flyfish-file-viewer-web-full.iife.js`, image/pdf/word/presentation/spreadsheet/text renderers, and docx/pdf/pptx/xlsx vendor assets into `/static/vendor/file-viewer`. Docker performs this at image build time; generated vendor files are not committed.

- [x] **Step 6: Implement the authenticated viewer page**

Add `/viewer`, strict CSP, source allowlisting, Blob-to-File handoff, Flyfish lifecycle cleanup, and deterministic loading/error/retry/close UI. Run Step 4 Web tests to GREEN, then inspect actual renderer network requests to confirm all assets stay same-origin.

- [x] **Step 7: Replace Web download-first interactions**

Attachment cards and generated artifact links open the internal viewer. Preserve a separately named download action only where explicitly offered; viewing must never imply downloading. Fix the attachment size helper so it is a normal callable declaration.

- [x] **Step 8: Implement Android internal viewing**

Add the URL helper and dedicated Activity/WebView. Wire WebWorkspace bridge, floating generated-artifact cards, floating historical attachment cards, system back, viewer close, and floating-ball restoration. Remove the external-viewer default path and its manifest registration after references reach zero.

- [x] **Step 9: Run GREEN and regression suites**

```bash
python3 -m pytest -q runtime_api/tests/test_static_file_viewer.py runtime_api/tests/test_static_chat_attachments.py runtime_api/tests/test_static_workbench_agenda_tab.py
node --test runtime_api/tests_js/file_viewer_links.test.cjs runtime_api/tests_js/chat_attachments.test.cjs
gradle -p android_app clean testDebugUnitTest assembleDebug
docker compose config --quiet
docker compose build runtime-api
git diff --check
```

Review actual outputs: viewer URLs, auth headers, error text, rendered filenames, page/slide/sheet navigation, close behavior, and absence of external viewer intents. A green status without correct content does not pass.

- [ ] **Step 10: Deploy and run cloud/real-device format acceptance**

Use the existing real-file matrix on the private cloud and Android device. Verify every V1 format, content fidelity, sheet/slide/page navigation, repeated open/close, rotation, offline/error states, Web/full App/floating consistency, no CDN calls, and no WPS/Xiaomi/system chooser. Record screenshots, source IDs, actual facts inspected, timing, memory/restart observations, and every residual gap.

**2026-07-15 执行记录：** 查看器代码已部署至私有云，云端真实 PNG、PDF、DOCX、PPTX、
XLSX 原件均完成上传、解析和原件读取；本地移动端 Chromium 已逐一直接渲染五种格式。
Android 真机已从真实聊天产物卡打开 PPTX、滚动查看多张幻灯片、关闭返回完整 App，且未
出现系统文件选择器或小米文档查看器。Step 10 暂不勾选，因为 CSV/TXT/MD、旋转、离线错误、
十次连续打开以及其余格式的真机 UI 矩阵尚未全部执行。最终 fresh Docker 构建也已通过；
镜像核对为六个 renderer、四个格式 vendor 加 libarchive 共享 runtime，不含 EPUB 或
`node_modules`。后端全量为 `1094 passed`，Web/JS 为 `11 passed`，Android clean build
成功。

---

## Specification Coverage Matrix

| Specification area | Primary tasks | Required evidence |
| --- | --- | --- |
| Attachment-only and mixed messages | 1, 7, 11, 13 | HTTP/WS parity plus both Android surfaces |
| Supported/rejected formats and limits | 2, 5 | Semantic parser fixtures and safe rejection messages |
| Private streamed storage | 2, 3, 15 | Hash/atomic-write tests and privacy scan |
| Four-table data model | 1 | Fresh-install and upgrade schema tests |
| Upload/status/preview/content/retry/delete API | 3, 6 | Authenticated API integration tests |
| Atomic turn binding and idempotency | 7, 8 | Rollback/concurrency/retry tests |
| Bounded async parsing | 4, 5, 16 | Worker isolation, resource, and queue tests |
| Large-file retrieval and visual escalation | 9, 10 | Selected locator/visual trace and factual answers |
| 256K budget and recent 15 rounds | 9 | Budget assertions and context trace |
| Structured Qwen input/non-thinking | 10 | Provider payload contract and live trace |
| Citations and coverage claims | 9, 17 | Expected locator versus actual answer |
| Long-term memory provenance | 15 | 15-round batch test with immutable source version |
| Web full App interaction | 11, 12 | Node tests, responsive inspection, real device |
| Native floating interaction | 13 | JUnit/MockWebServer and real device |
| Server-authoritative history | 8, 14 | Cross-surface restart/reconciliation test |
| Error/retry behavior | 4, 6, 8, 11, 13 | Failure injection without duplicates |
| Security | 2, 10, 15, 16 | Hostile fixtures, prompt injection, auth/path tests |
| Observability | 15, 17 | Privacy-safe trace with evidence and latency |
| 4-core/8GB performance | 4, 16, 17 | Resource metrics and P95 measurements without removing core capabilities |
| Real output correctness | 5, 9, 17 | Known facts, citations, screenshots, and trace IDs |

## Definition of Done

- [ ] Every task completed in RED -> GREEN -> refactor order; no production code precedes its failing test.
- [ ] All supported types produce semantically correct extracted facts and stable locators.
- [ ] HTTP and WebSocket behavior, error codes, idempotency, and persistence are equivalent.
- [ ] Pure attachments and text-plus-attachments work in full App and floating chat.
- [ ] Model receives the expected structured text/image evidence, not stringified content.
- [ ] Responses identify evidence locations and never claim unread coverage.
- [ ] Local/server history and both Android surfaces converge without filename-based guesses.
- [ ] Upload, parse, model, network, and restart failures do not duplicate files or turns.
- [ ] Security and privacy scans show no base64, secrets, raw private content, or absolute paths in durable stores or traces.
- [ ] Cloud load on the target 4-core/8GB production profile meets health and latency targets without disabling core parsing, browser collection, or background processing; otherwise the gap report states the measured residual limitation.
- [ ] Real-device report contains actual outputs and verdicts for every acceptance case.
- [ ] Gap report explicitly lists every skipped, mocked-only, provider-blocked, performance-missed, or partially implemented item.

## Final Verification Commands

```bash
python3 -m pytest -q runtime_api/tests
node --test runtime_api/tests_js/chat_attachments.test.cjs
gradle -p android_app :app:testDebugUnitTest
docker compose config --quiet
docker compose build runtime-api attachment-worker
git diff --check
```

The implementation is not complete until automated verification, private-cloud deployment, live Qwen evidence inspection, and Android real-device acceptance all pass or remaining gaps are explicitly documented.
