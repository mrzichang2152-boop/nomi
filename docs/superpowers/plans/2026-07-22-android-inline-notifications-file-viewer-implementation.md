# Android Inline Notifications and Original File Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop proactive reminders from covering active Nomi screens, render them in the floating conversation when appropriate, and make original Office artifacts previewable and downloadable on Android.

**Architecture:** A pure Android surface policy chooses between background overlay, floating-panel inline card, and foreground suppression. The file viewer resolves authoritative metadata from HTTP headers, passes a correctly named and typed `File` to Flyfish, and delegates authenticated Android downloads to a restricted native bridge writing through `MediaStore`.

**Tech Stack:** Android Java, WebView JavaScript bridge, OkHttp, Android MediaStore, vanilla JavaScript, Node test runner, Python pytest, Flyfish File Viewer.

---

## File Map

- Create `android_app/app/src/main/java/com/par/assistant/android/NomiForegroundUiState.java`: process-local foreground activity counter.
- Create `android_app/app/src/main/java/com/par/assistant/android/ProactiveSurfacePolicy.java`: pure notification-surface decision.
- Create `android_app/app/src/main/java/com/par/assistant/android/OriginalFileDownload.java`: validated authenticated download request and MediaStore writer.
- Modify `android_app/app/src/main/java/com/par/assistant/android/FloatingBallService.java`: apply policy, remove overlays, render inline proactive cards.
- Modify `android_app/app/src/main/java/com/par/assistant/android/WebWorkspaceActivity.java`: publish foreground lifecycle and clear overlay.
- Modify `android_app/app/src/main/java/com/par/assistant/android/NomiFileViewerActivity.java`: publish foreground lifecycle and expose download bridge.
- Modify `runtime_api/app/static/file-viewer-links.js`: parse and resolve filename/MIME metadata.
- Modify `runtime_api/app/static/viewer.js`: use resolved metadata and support web/native download.
- Modify `runtime_api/app/static/viewer.html`: add icon download command.
- Modify `runtime_api/app/static/viewer.css`: stable top-bar command layout.
- Test `android_app/app/src/test/java/com/par/assistant/android/ProactiveSurfacePolicyTest.java`.
- Test `android_app/app/src/test/java/com/par/assistant/android/NomiForegroundUiStateTest.java`.
- Test `android_app/app/src/test/java/com/par/assistant/android/OriginalFileDownloadTest.java`.
- Modify `android_app/app/src/test/java/com/par/assistant/android/FloatingPanelAppEntryContractTest.java`.
- Modify `android_app/app/src/test/java/com/par/assistant/android/NomiFileViewerContractTest.java`.
- Modify `android_app/app/src/test/java/com/par/assistant/android/WebWorkspaceKeyboardTest.java`.
- Modify `runtime_api/tests_js/file_viewer_links.test.cjs`.
- Modify `runtime_api/tests/test_static_file_viewer.py`.

### Task 1: Deterministic Proactive Surface Policy

- [ ] **Step 1: Write failing policy tests**

Cover these exact decisions: background -> `OVERLAY_BUBBLE`; floating panel open -> `INLINE_PANEL_CARD`; foreground Nomi activity -> `SUPPRESS_OVERLAY`; foreground activity wins if stale panel state is also true.

- [ ] **Step 2: Run the focused test and prove RED**

Run: `cd android_app && gradle :app:testDebugUnitTest --tests '*ProactiveSurfacePolicyTest'`

Expected: compilation failure because `ProactiveSurfacePolicy` does not exist.

- [ ] **Step 3: Add the minimal pure policy and foreground state**

Use an enum result and an atomic foreground counter. Counter decrement must clamp at zero so duplicate lifecycle callbacks cannot leave Nomi permanently foreground.

- [ ] **Step 4: Run focused tests and prove GREEN**

Run: `cd android_app && gradle :app:testDebugUnitTest --tests '*ProactiveSurfacePolicyTest' --tests '*NomiForegroundUiStateTest'`

Expected: all policy and counter cases pass.

### Task 2: Apply Policy to Android Surfaces

- [ ] **Step 1: Write failing source-contract tests**

Assert that both foreground activities call `NomiForegroundUiState.enter/exit`, send the service clear-overlay action on start, and that `FloatingBallService` routes through `ProactiveSurfacePolicy` without adding proactive cards to `ChatContext`.

- [ ] **Step 2: Run focused tests and prove RED**

Run: `cd android_app && gradle :app:testDebugUnitTest --tests '*FloatingPanelAppEntryContractTest' --tests '*NomiFileViewerContractTest' --tests '*WebWorkspaceKeyboardTest'`

Expected: assertions fail for missing lifecycle and policy integration.

- [ ] **Step 3: Implement foreground suppression and inline card rendering**

Add a service action that removes any existing proactive overlay. In the realtime callback, keep unread bookkeeping, then apply the pure policy. The inline card must be bounded, chronological, clickable, and must not call `chatContext.addAssistant` or persist into `LocalChatHistoryStore`.

- [ ] **Step 4: Run focused tests and prove GREEN**

Run the same focused Android tests and require all assertions to pass.

### Task 3: Resolve Viewer Metadata from HTTP Headers

- [ ] **Step 1: Write failing JavaScript tests**

Cover quoted `filename=`, UTF-8 `filename*=UTF-8''...`, MIME parameters, malicious path separators, caller metadata precedence, response-header fallback, and blob-type fallback.

- [ ] **Step 2: Run the focused test and prove RED**

Run: `node --test runtime_api/tests_js/file_viewer_links.test.cjs`

Expected: failures for missing `parseContentDispositionFilename` and `resolveFileMetadata`.

- [ ] **Step 3: Implement pure metadata helpers**

Export `parseContentDispositionFilename`, `normalizeMimeType`, `sanitizeFilename`, and `resolveFileMetadata`. Never accept directory components or control characters in a resolved filename.

- [ ] **Step 4: Run JavaScript tests and prove GREEN**

Run the same Node command and require all cases to pass.

### Task 4: Correct Original Preview and Add Download Command

- [ ] **Step 1: Write failing static viewer tests**

Assert that the page contains a named icon download button, `viewer.js` reads `Content-Disposition` and `Content-Type`, constructs `File` with resolved metadata, retains the authenticated blob, and exposes both web and Android download paths.

- [ ] **Step 2: Run focused pytest and prove RED**

Run: `python3 -m pytest -q runtime_api/tests/test_static_file_viewer.py`

Expected: failures for missing command and metadata/download behavior.

- [ ] **Step 3: Implement preview and web download**

After a successful fetch, resolve metadata from query plus response headers, update title/status, construct the `File`, and retain the blob for download. Browser download uses a temporary object URL and revokes it after the click. Unsupported preview keeps download enabled.

- [ ] **Step 4: Run viewer tests and prove GREEN**

Run the Node and pytest viewer suites together; all must pass.

### Task 5: Authenticated Android Original Download

- [ ] **Step 1: Write failing Android tests**

Cover same-origin source validation, artifact and attachment URL construction, safe filename fallback, native bridge presence, `x-par-password`, `MediaStore.Downloads`, `Download/Nomi`, pending-row finalization, failure cleanup, and repeated-tap guard.

- [ ] **Step 2: Run focused tests and prove RED**

Run: `cd android_app && gradle :app:testDebugUnitTest --tests '*OriginalFileDownloadTest' --tests '*NomiFileViewerContractTest'`

Expected: missing implementation and bridge assertions fail.

- [ ] **Step 3: Implement native streaming download**

Validate source through `FileViewerUrls`, resolve against configured private-cloud base URL, fetch with the existing private-cloud OkHttp client and password header, stream into `MediaStore.Downloads` on Android 10+, use app-scoped external downloads on Android 8/9, finalize or delete pending records, and report concise success/failure on the UI thread.

- [ ] **Step 4: Run focused tests and prove GREEN**

Run the same Android tests and require all cases to pass.

### Task 6: Regression, Deploy, and Real-Device Acceptance

- [x] **Step 1: Run local regression**

Run:

```bash
node --test runtime_api/tests_js/file_viewer_links.test.cjs
python3 -m pytest -q runtime_api/tests/test_static_file_viewer.py
cd android_app && gradle :app:testDebugUnitTest :app:assembleDebug
```

Expected: all focused tests pass and the debug APK builds.

- [x] **Step 2: Deploy without clearing user state**

Deploy runtime static assets to `/opt/nomi`, rebuild/restart only affected cloud services, and install the APK with `adb install -r` so account sessions and chat history are preserved.

- [x] **Step 3: Verify cloud health**

Run `/health` and artifact HEAD/GET checks. Expected artifact headers are PPTX MIME and `Nomi_auto_delivery_visual_20260720.pptx`; downloaded bytes remain a valid OOXML archive.

- [x] **Step 4: Verify notification surfaces on device**

Inject one harmless proactive event in each state: background, floating chat open, full app open, file viewer open. Expected respectively: one compact overlay; one inline card and no overlay; no overlay with workspace inline handling; no overlay over viewer.

- [x] **Step 5: Verify PPTX preview and download on device**

Open `artifact_033a8a150b574b9f8bd6f6b7b4309dda`. Expected: exact filename in title, slides visible, download command works, `/sdcard/Download/Nomi/Nomi_auto_delivery_visual_20260720.pptx` exists, byte size is 30,728, and pulled file passes `file` plus `unzip -t`.

- [x] **Step 6: Record evidence and remaining gaps**

Update the implementation report with commands, screenshots, trace IDs, byte/hash evidence, and any unresolved behavior. Do not mark an item complete from HTTP success alone.

## Self-Review

- Spec coverage: every goal, non-goal, security rule, and real-device acceptance criterion maps to a task above.
- Placeholder scan: no deferred implementation placeholders are present.
- Type consistency: surface policy values, foreground lifecycle calls, metadata helper names, and bridge method names are used consistently.
