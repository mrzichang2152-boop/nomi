# Nomi Chat Attachments Research

**Date:** 2026-07-13
**Status:** Research complete; product decisions confirmed and incorporated into the design specification
**Scope:** Images and common document attachments in the Android floating chat and full application chat

## 1. Research Question

Nomi needs more than a file picker. A correct implementation must answer six separate questions:

1. How are original bytes uploaded and persisted without corrupt or partial records?
2. How is an attachment bound to one exact user message and synchronized across both Android chat surfaces?
3. Which document formats can be understood reliably on a 2-core/4-GB private server?
4. When should content be injected in full, retrieved by relevance, or sent to Qwen as images?
5. How are processing failures, retries, large files, and scanned documents represented to the user?
6. How can the system prove that a response actually used the intended attachment?

The research therefore covered the current Nomi implementation, three mature open-source chat/RAG products, Docling, Android platform behavior, upload security guidance, local parser benchmarks, and the configured Qwen endpoint.

## 2. Repositories and Versions Reviewed

| Project | Commit reviewed | Relevant area |
| --- | --- | --- |
| Open WebUI | `ecd48e2f718220a6400ecf49eafd4867a38feb10` | File records, processing states, message/file relations, image content parts, full-context vs RAG |
| LibreChat | `cf9a426d29b23b34dd1a7e8d52e4e646916aeffb` | Message attachments, file status, document extraction, token limits, resume/history bugs |
| AnythingLLM | `4482fd625f74f093bf80e198af19d16598ec23b6` | Document parsing, workspace embedding worker, attachment injection |
| Docling | `0bdc78dbcc3b447fcb3af0e8c32560669cba2359` | Unified document model, Office/PDF parsing, OCR and layout pipeline dependencies |

Primary source links:

- [Open WebUI file model](https://github.com/open-webui/open-webui/blob/ecd48e2f718220a6400ecf49eafd4867a38feb10/backend/open_webui/models/files.py)
- [Open WebUI file router](https://github.com/open-webui/open-webui/blob/ecd48e2f718220a6400ecf49eafd4867a38feb10/backend/open_webui/routers/files.py)
- [Open WebUI chat/file relation](https://github.com/open-webui/open-webui/blob/ecd48e2f718220a6400ecf49eafd4867a38feb10/backend/open_webui/models/chats.py)
- [Open WebUI attachment middleware](https://github.com/open-webui/open-webui/blob/ecd48e2f718220a6400ecf49eafd4867a38feb10/backend/open_webui/utils/middleware.py)
- [LibreChat file types](https://github.com/danny-avila/LibreChat/blob/cf9a426d29b23b34dd1a7e8d52e4e646916aeffb/packages/data-provider/src/types/files.ts)
- [LibreChat file processing](https://github.com/danny-avila/LibreChat/blob/cf9a426d29b23b34dd1a7e8d52e4e646916aeffb/api/server/services/Files/process.js)
- [LibreChat attachment context](https://github.com/danny-avila/LibreChat/blob/cf9a426d29b23b34dd1a7e8d52e4e646916aeffb/packages/api/src/files/context.ts)
- [AnythingLLM document model](https://github.com/Mintplex-Labs/anything-llm/blob/4482fd625f74f093bf80e198af19d16598ec23b6/server/models/documents.js)
- [AnythingLLM embedding worker](https://github.com/Mintplex-Labs/anything-llm/blob/4482fd625f74f093bf80e198af19d16598ec23b6/server/jobs/embedding-worker.js)
- [Docling supported formats](https://docling-project.github.io/docling/usage/supported_formats/)
- [Docling installation](https://docling-project.github.io/docling/getting_started/installation/)

## 3. Current Nomi Findings

### 3.1 Chat is text-only

`ChatIn` currently accepts a required string `message` and has no attachment IDs. The HTTP and WebSocket paths carry text and recent client context only. The model interfaces are annotated as `list[dict[str, str]]`, and provider conversion utilities coerce message content to strings. This means adding an `image_url` in one route would still be lost or stringified elsewhere.

### 3.2 History has message identity but no attachment relation

Nomi already persists `assistant_conversations` and `assistant_turns` and synchronizes the same conversation between Android surfaces. That is a useful base. However, `assistant_turns` has no normalized relation to uploaded originals. Reusing `private_events.attachments` would be incorrect because event-source attachments and chat-message attachments have different ownership, lifecycle, and rendering rules.

### 3.3 The two Android surfaces need different picker integrations

The full application is a web workspace inside `WebWorkspaceActivity`. Its current `WebChromeClient` does not override `onShowFileChooser`; Android's default behavior cancels file requests. Android explicitly requires the app to implement this callback and return selected URIs to the WebView. See [Android `WebChromeClient.onShowFileChooser`](https://developer.android.com/reference/android/webkit/WebChromeClient.html#onShowFileChooser(android.webkit.WebView,android.webkit.ValueCallback,android.webkit.WebChromeClient.FileChooserParams)).

The floating chat is built natively inside `FloatingBallService`. A foreground service cannot own a normal activity-result lifecycle. It therefore needs a small picker activity or equivalent launcher that returns selected URI grants to the service. Both surfaces can share the server protocol and rendering model, but they cannot share the same UI picker implementation.

### 3.4 Existing parsers cover the common baseline

The runtime already depends on `python-docx`, `python-pptx`, and `pypdf`. It also has an artifact/file flow for generated outputs, but that flow is download-oriented and is not a safe substitute for user input attachments.

## 4. Mature Project Patterns

### 4.1 Open WebUI

Open WebUI separates file identity from chat identity. A file row holds the original filename, randomized storage path, hash, metadata, and processing data. A separate relational table binds files to chat messages. Processing is stateful and can finish after the upload request returns.

Important lessons:

- A successful upload is not the same as a ready attachment.
- The client needs an authoritative processing status before sending or querying a file.
- Message/file binding must be explicit. Positional matching is fragile; Open WebUI contains a source comment documenting a bug where naive message/image matching caused later messages to lose file context.
- Images are converted to structured `image_url` content parts at the model boundary.
- Documents can use full context or retrieval. One policy for every file size is not sufficient.

Open WebUI documentation also warns that upload processing is asynchronous and clients must wait for completion before depending on extracted content: [Open WebUI RAG troubleshooting](https://docs.openwebui.com/troubleshooting/rag/).

### 4.2 LibreChat

LibreChat models message attachments explicitly and gives files durable states such as `pending`, `ready`, and `failed`. It separates images, documents, video, and audio before processing and performs independent work in parallel.

Important lessons:

- Attachment identity must be the immutable file ID plus exact message ID. Filename is display metadata only.
- Resume and history reconstruction must restore persisted attachment metadata. Otherwise the user bubble loses files even though the original upload succeeded.
- A file token limit is required before injecting extracted text.
- File processing can succeed technically while returning no meaningful text. Image-only PDFs need an explicit fallback or a clear failure state.
- Cross-turn references to files must not reuse a stale message ID.

Real failure reports support these findings. LibreChat has had cases where upload succeeded but processing was not invoked, so the model never received the file: [LibreChat issue #10493](https://github.com/danny-avila/LibreChat/issues/10493).

### 4.3 AnythingLLM

AnythingLLM treats embedded workspace documents and one-message API attachments as different paths. Its embedding worker is isolated from the main server so an out-of-memory failure in native embedding code does not kill the API process. It reports batch, per-document, and terminal progress events.

Important lessons:

- Heavy parsing or embedding should not execute inline in the chat request.
- Worker failures need document-level status and must not make the whole API unavailable.
- Persisting the workspace relation only after vectorization avoids claiming that a failed document is usable, but a production attachment system also needs an original-file record before processing so retries do not require re-upload.
- “Uploaded” and “attached to the active conversation/workspace” are separate operations. AnythingLLM users have reported successful uploads that were never actually attached: [AnythingLLM issue #5271](https://github.com/Mintplex-Labs/anything-llm/issues/5271).

## 5. Document Parsing Benchmark

### 5.1 Method

Fixtures and expected outputs came from the reviewed Docling repository. The lightweight benchmark used in-memory `python-docx`, `python-pptx`, `pypdf`, and `openpyxl` extraction. Recall is a simple token-set comparison against Docling's checked-in ground truth; it is not a complete layout-quality metric.

### 5.2 Results

| Fixture | Size | Time | Extracted characters | Ground-truth token recall | Peak RSS reported by process |
| --- | ---: | ---: | ---: | ---: | ---: |
| DOCX `lorem_ipsum.docx` | 14,817 B | 0.0538 s | 3,482 | 1.0000 | 28.4 MB |
| PPTX `powerpoint_sample.pptx` | 45,849 B | 0.0853 s | 597 | 1.0000 | 39.0 MB |
| PDF `normal_4pages.pdf` | 359,233 B | 0.0910 s | 7,906 | 0.9818 | 34.0 MB |
| XLSX `xlsx_01.xlsx` | 170,934 B | 0.1048 s | 958 | 0.8571 | 42.4 MB |
| Scanned PDF `ocr_test.pdf` | 93,549 B | 0.0333 s | 9 | 0.0000 | 31.5 MB |

Interpretation:

- Lightweight libraries are fast and sufficiently faithful for ordinary digital Office files and PDFs.
- Spreadsheet charts, formatting, merged regions, and formulas need richer structural handling than raw visible values, as reflected by the lower XLSX recall.
- Text extraction alone completely fails on scanned PDFs. A deterministic low-text-density check is therefore necessary.

### 5.3 Docling feasibility on 2-core/4-GB

Docling supports a broad unified format and advanced PDF layout understanding, but its model pipelines depend on PyTorch and additional model packages. In the test environment, attempting to initialize the converter for a DOCX first required `torch`, then `transformers`, then `docling_ibm_models`; the temporary environment exceeded roughly 986 MB before a successful document conversion was reached.

This does not mean Docling is a poor project. It means full Docling is a poor default inside Nomi's primary API container on a 2-core/4-GB private server. It remains viable as an optional isolated worker for users with more resources. Docling's official installation guide confirms the PyTorch dependency and separate CPU/GPU installation considerations.

## 6. Qwen Multimodal Verification

The configured endpoint `http://81.70.177.246:9161/v1` exposes `qwen/qwen3.6-27b` and accepts OpenAI-compatible structured content containing text plus a base64 `image_url`.

### 6.1 UI screenshot test

The model was asked to read four labels in a real screenshot. It correctly returned:

1. `Web Search API`
2. `Model API`
3. `Agent Search API`
4. `Semantic Reranker API`

### 6.2 Scanned PDF fallback test

The scanned PDF that produced zero meaningful characters with `pypdf` was rendered to a 1012 x 1432 PNG and sent to Qwen. Qwen correctly transcribed:

`Docling bundles PDF document conversion to JSON and Markdown in an easy self contained package`

This verifies the proposed fallback principle: render only pages that require visual understanding instead of running every document through a heavyweight local OCR/layout stack.

### 6.3 Latency and non-thinking caveat

For the screenshot stream test:

- First upstream delta: 1.573 s
- First visible answer token: 8.296 s
- Total: 8.815 s
- Hidden `reasoning_content`: 365 characters

For the scanned-page non-streaming test:

- Total: 9.238 s
- Reported reasoning tokens: 97

The request included both `enable_thinking=false` and `chat_template_kwargs.enable_thinking=false`, yet this endpoint still emitted reasoning for vision requests. Therefore the feature can rely on Qwen's visual accuracy, but it must not assume that the deployed multimodal server currently honors non-thinking mode. Hidden reasoning must not be streamed to the UI, and vision latency needs a separate trace from normal text-chat latency.

## 7. Upload and Storage Safety

OWASP recommends extension allowlists, content/signature validation, generated storage names, size limits, authenticated access, and storage outside the web root. See the [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html).

For Nomi, this means:

- Stream bytes to a temporary file while hashing; do not load large files into Android or Python heap.
- Detect actual type from bytes and archive structure instead of trusting Android's MIME string.
- Store originals outside `runtime_api/app/static` under generated IDs.
- Keep the original filename only as metadata.
- Reject archives, executables, malformed Office ZIPs, excessive decompressed size, encrypted documents, and unsupported legacy binary Office formats in the first release.
- Resolve previews/downloads through authenticated attachment IDs rather than filesystem paths.
- Treat text inside uploaded documents as untrusted evidence, not instructions that may invoke tools.

Android further warns that a WebView may receive URIs from untrusted providers and the host app must validate them before passing access onward. The WebView itself does not enforce the HTML accept filter.

## 8. What Not to Copy

The reviewed systems are useful references but should not be transplanted wholesale.

1. Do not use Open WebUI's extra model call to generate retrieval queries for every small attachment. It adds avoidable latency to Nomi's chat path.
2. Do not adopt LibreChat's very large default limits. A 2-core/4-GB private server needs conservative byte, page, cell, and token caps.
3. Do not use AnythingLLM's direct base64 attachment body as Nomi's durable protocol. It prevents efficient retries and cross-surface synchronization.
4. Do not put full Docling in the main API container by default.
5. Do not store base64 image data in PostgreSQL, chat history, long-term memory, or traces.
6. Do not infer attachment-message relationships by array position or filename.
7. Do not report `ready` merely because the original upload returned HTTP 200.

## 9. Research Conclusions

The evidence supports the hybrid architecture adopted by the approved design:

- **Identity and persistence:** upload once, return an immutable attachment ID, and bind it explicitly to an exact `assistant_turns.id`.
- **Processing:** persist the original first, then parse asynchronously with observable states.
- **Ordinary documents:** use lightweight local parsers already compatible with Nomi's resource budget.
- **Images:** send bounded, normalized image content to Qwen vision at the model-adapter boundary.
- **Scanned or visual pages:** detect low text density or explicit visual need, render selected pages/slides, and use Qwen as a targeted fallback.
- **Large documents:** use size-aware policy: small files may enter bounded full context; larger files need chunking and retrieval with citations.
- **Cross-surface UI:** share the server protocol and history schema, but implement WebView file selection and floating-service file selection separately.
- **Reliability:** use explicit upload/processing/message states and make the chat send atomic with attachment validation.
- **Observability:** trace exactly which text chunks and images reached the model and how long each stage took.

## 10. Confirmed Product Decisions

The product review resolved the policy questions left open by the research:

1. Sent attachments live with the conversation and are deleted with it.
2. Unsent attachment drafts expire after 24 hours.
3. File-only messages are valid; their default intent is to identify and summarize the attachment.
4. Attachment-plus-text messages treat the text as the user's instruction and the attachment as evidence.
5. For PDFs over 20 pages and PPTX files over 30 slides, Nomi indexes the whole document with lightweight parsing and visually inspects only question-relevant pages by default.
6. Full page-by-page visual inspection is an explicit asynchronous operation.
7. Full Docling is not part of the default 2-core/4-GB deployment; it remains a future optional worker for stronger machines.

The resulting implementation contract is documented in `docs/superpowers/specs/2026-07-13-unified-chat-attachments-design.md`.
