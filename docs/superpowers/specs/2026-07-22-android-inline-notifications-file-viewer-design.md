# Android Inline Notifications and Original File Viewer Design

## Status

Approved direction: Option A.

## Problem Statement

Two production defects were reproduced on Android device `DQYTCYFMO7VSEAJB`:

1. A proactive reminder was rendered both as an in-conversation card and as a system overlay bubble. The overlay covered chat and file-viewer content.
2. A valid generated PPTX opened as an unsupported file. The viewer URL contained only the artifact source, so the viewer constructed a file named `Nomi 文件` with `application/octet-stream` even though the download response supplied the correct filename and PPTX MIME type.

The same artifact endpoint returned a valid 30,728-byte Microsoft OOXML archive with no ZIP integrity errors. The defect is in client metadata and interaction handling, not artifact generation.

## Goals

- Keep proactive and confirmation content inside the active Nomi conversation surface.
- Show a floating proactive bubble only while every Nomi UI surface is in the background.
- Prevent an existing bubble from covering the workspace or file viewer.
- Preview original PPTX, DOCX, XLSX, PDF, image, and supported text files without converting them to PDF.
- Let Android users explicitly download the original authenticated file to the device.
- Preserve the private-cloud authentication boundary and same-origin file-source allowlist.

## Non-Goals

- Changing proactive suggestion generation, ranking, or deduplication.
- Writing proactive cards into long-term memory or chat context.
- Opening artifacts in third-party viewers.
- Converting Office files to PDF or images for preview.

## Notification Surface Policy

### Background

When no Nomi activity and no floating chat panel is visible, a new proactive event may show the existing compact bubble next to the Nomi avatar. The bubble remains an entry point rather than a second persistent message surface.

### Floating Chat Open

When the floating chat panel is open:

- Do not create a `TYPE_APPLICATION_OVERLAY` message bubble.
- Render the proactive event as a bounded card inside `chatHistoryView`.
- Do not append the event to `ChatContext` or local conversational history; it is UI state backed by the proactive-suggestion record.
- Keep the card in chronological visual order and scroll it into view without covering the composer.

### Full App or File Viewer Open

When `WebWorkspaceActivity` or `NomiFileViewerActivity` is foreground:

- Remove any existing proactive overlay bubble immediately.
- Suppress new overlay bubbles.
- Keep unread state/badge bookkeeping.
- Let the Web workspace render its own realtime proactive card. The file viewer does not render notifications; the event remains available when returning to chat.

Foreground visibility is process-local state shared by Nomi activities and `FloatingBallService`. Activity start/stop updates the state. Service decisions must be deterministic and testable independently from Android window APIs.

## Original File Metadata Resolution

The viewer resolves metadata in this order:

1. Explicit `filename` and `mime_type` query parameters, when valid.
2. Same-origin download response headers:
   - `Content-Disposition` filename or RFC 5987 `filename*`.
   - `Content-Type` without parameters.
3. Blob type.
4. Safe fallback `Nomi 文件` and `application/octet-stream`.

The resolved filename and MIME type are used for:

- The viewer title and top bar.
- The browser `File` object passed to Flyfish File Viewer.
- The Android download filename and media type.

Header metadata is authoritative when the caller supplied no useful metadata. A filename without an extension is not considered useful for renderer selection when the response provides a filename with an extension.

## Download Interaction

The file-viewer top bar contains familiar close and download icon buttons.

### Android

- JavaScript requests a download through the restricted `NomiViewer` bridge.
- `NomiFileViewerActivity` validates that the source is one of the existing same-origin attachment/artifact endpoints.
- The activity streams the original bytes with `x-par-password` using the existing private-cloud HTTP client configuration.
- The file is stored through `MediaStore.Downloads` under `Download/Nomi` with the resolved filename and MIME type.
- Success and failure produce explicit user-visible feedback.
- No broad storage permission and no external `ACTION_VIEW` are used.

### Web

- The already authenticated response blob is downloaded using a temporary object URL and the resolved filename.
- The object URL is revoked after the click.

Preview and download are separate commands. Opening a file never silently downloads it, and downloading never leaves the viewer.

## Error Handling

- HTTP 401: tell the user the local access credential is stale.
- HTTP 404: tell the user the artifact was removed or expired.
- Unsupported renderer after valid metadata resolution: show the existing retry panel while keeping download available.
- Android write failure: preserve the viewer and show a concise failure message.
- Repeated download taps: disable the download control while one transfer is active.

## Security Constraints

- Continue accepting only current same-origin attachment-content and artifact-download paths.
- Never put the password in a URL, filename, local-storage export, or download metadata.
- Reject traversal, cross-origin URLs, and unsupported endpoint paths before preview or download.
- Keep the Android file viewer internal and do not delegate to third-party apps.

## Verification

### Automated

- Red/green unit tests for foreground notification surface decisions.
- Android contract tests for activity visibility updates, bubble removal, inline card rendering, and authenticated MediaStore download.
- JavaScript tests for `Content-Disposition`, `filename*`, MIME fallback, and safe filename handling.
- Static viewer tests for the download control and resolved metadata passed to `File`.
- Existing Android, viewer, attachment, realtime, and assistant-draft tests remain green.

### Cloud and Real Device

1. Deploy runtime API and install the new APK without clearing app data.
2. Open floating chat and inject one proactive event: exactly one inline card, no overlay.
3. Open full app and file viewer, then inject an event: no overlay covers either screen.
4. Open artifact `artifact_033a8a150b574b9f8bd6f6b7b4309dda`: filename is `Nomi_auto_delivery_visual_20260720.pptx` and slides render directly.
5. Tap download: file appears in `Download/Nomi`, keeps `.pptx`, is 30,728 bytes, and remains a valid OOXML archive.

## Acceptance Criteria

- No proactive overlay is visible while a Nomi conversation or viewer is foreground.
- Floating chat displays proactive content as an in-flow card without polluting model context.
- The reproduced PPTX renders using its original format.
- The same PPTX downloads successfully with correct name, MIME, byte size, and archive validity.
- No external application is required for viewing.
- No real outbound email or other external side effect is triggered during verification.
