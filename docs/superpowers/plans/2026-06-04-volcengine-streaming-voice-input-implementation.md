# Volcengine Streaming Voice Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Nomi Android long-press streaming voice input backed by Volcengine streaming ASR.

**Architecture:** Android captures PCM16 mono audio in 200ms chunks while the user holds the floating Nomi avatar, streams chunks over `/ws/voice`, receives ASR partial/final events, and sends high-confidence final transcripts into the existing `/ws` chat flow. The server owns all Volcengine credentials and adapts Nomi JSON voice events to Volcengine's binary WebSocket protocol.

**Tech Stack:** Android Java, OkHttp WebSocket, `AudioRecord`, FastAPI WebSocket, Python asyncio, `websockets`, gzip/binary frame parsing, pytest, JUnit.

---

### Task 1: Server Voice Protocol and Fake ASR

**Files:**
- Create: `runtime_api/app/voice/__init__.py`
- Create: `runtime_api/app/voice/asr_provider.py`
- Create: `runtime_api/app/voice/fake_provider.py`
- Create: `runtime_api/app/voice/voice_ws.py`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_voice_ws.py`

- [x] **Step 1: Write failing tests**

Create tests that connect to `/ws/voice`, verify password rejection, `voice_start -> voice_ready`, `audio_chunk -> asr_partial`, `voice_end -> asr_final`, chunk-size rejection, and `voice_cancel`.

- [x] **Step 2: Verify red**

Run: `cd runtime_api && pytest tests/test_voice_ws.py -q`
Expected: fail because `/ws/voice` and `app.voice` do not exist.

- [x] **Step 3: Implement minimal fake provider and voice websocket**

Implement `StreamingAsrProvider`, `StreamingAsrSession`, `FakeStreamingAsrProvider`, `handle_voice_websocket`, and register `/ws/voice` in `main.py`.

- [x] **Step 4: Verify green**

Run: `cd runtime_api && pytest tests/test_voice_ws.py -q`
Expected: all tests pass.

### Task 2: Volcengine Binary Provider

**Files:**
- Create: `runtime_api/app/voice/volcengine_provider.py`
- Modify: `runtime_api/requirements.txt`
- Test: `runtime_api/tests/test_volcengine_asr_provider.py`

- [x] **Step 1: Write failing tests**

Test request header construction, full-client-request frame encode/decode, audio-only frame construction, server response parsing, error response mapping, and confidence estimation.

- [x] **Step 2: Verify red**

Run: `cd runtime_api && pytest tests/test_volcengine_asr_provider.py -q`
Expected: fail because Volcengine provider does not exist.

- [x] **Step 3: Implement provider**

Implement Volcengine binary protocol helpers and `VolcengineStreamingAsrProvider`. Add `websockets` to requirements. Credentials are read from env only.

- [x] **Step 4: Verify green**

Run: `cd runtime_api && pytest tests/test_volcengine_asr_provider.py -q`
Expected: all tests pass.

### Task 3: Android ASR WebSocket Client

**Files:**
- Create: `android_app/app/src/main/java/com/par/assistant/android/StreamingAsrClient.java`
- Test: `android_app/app/src/test/java/com/par/assistant/android/StreamingAsrClientTest.java`

- [x] **Step 1: Write failing tests**

Test `/ws/voice` URL construction, `voice_start`, `audio_chunk`, `voice_end`, `voice_cancel` payloads, and parsing `voice_ready`, `asr_partial`, `asr_final`, and `voice_error`.

- [x] **Step 2: Verify red**

Run: `JAVA_HOME=/opt/homebrew/opt/openjdk@17 gradle :app:testDebugUnitTest --tests com.par.assistant.android.StreamingAsrClientTest`
Expected: fail because `StreamingAsrClient` does not exist.

- [x] **Step 3: Implement client**

Implement OkHttp WebSocket client with callbacks and JSON event helpers.

- [x] **Step 4: Verify green**

Run the same Gradle test command.
Expected: all tests pass.

### Task 4: Android Long-Press Gesture and Recorder

**Files:**
- Create: `android_app/app/src/main/java/com/par/assistant/android/VoicePressController.java`
- Create: `android_app/app/src/main/java/com/par/assistant/android/StreamingVoiceRecorder.java`
- Test: `android_app/app/src/test/java/com/par/assistant/android/VoicePressControllerTest.java`

- [x] **Step 1: Write failing tests**

Test tap, drag-before-threshold, long-press voice start, slide-to-cancel, voice end, and action cancel cleanup.

- [x] **Step 2: Verify red**

Run: `JAVA_HOME=/opt/homebrew/opt/openjdk@17 gradle :app:testDebugUnitTest --tests com.par.assistant.android.VoicePressControllerTest`
Expected: fail because gesture controller does not exist.

- [x] **Step 3: Implement controller and recorder shell**

Implement testable gesture logic and an `AudioRecord` recorder that emits 200ms PCM chunks.

- [x] **Step 4: Verify green**

Run the same Gradle test command.
Expected: all tests pass.

### Task 5: Wire Voice into FloatingBallService

**Files:**
- Modify: `android_app/app/src/main/AndroidManifest.xml`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/MainActivity.java`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/FloatingBallService.java`
- Test: existing Android unit suite.

- [x] **Step 1: Add permissions and permission request flow**

Add `RECORD_AUDIO`, `FOREGROUND_SERVICE_MICROPHONE`, and microphone foreground service type. Add MainActivity request flow.

- [x] **Step 2: Replace long-click behavior**

Replace old long-click open-MainActivity behavior with `VoicePressController`.

- [x] **Step 3: Implement voice UI**

Show listening bubble, partial transcript, final transcript, error state, and low-confidence confirmation without rebuilding the whole panel.

- [x] **Step 4: Send final transcript to existing chat**

High-confidence final calls existing `sendMessage(text)` so it enters current context, history, memory, pipelines, and model streaming.

- [x] **Step 5: Verify Android build**

Run: `JAVA_HOME=/opt/homebrew/opt/openjdk@17 gradle :app:testDebugUnitTest :app:assembleDebug`
Expected: tests and build pass.

### Task 6: Smoke and Regression

**Files:**
- Modify: `.env.example`
- Modify: `docs/superpowers/reports/2026-06-04-android-device-regression.md`

- [x] **Step 1: Document env**

Add non-secret `VOLC_ASR_*` examples. Do not write real token or secret.

- [x] **Step 2: Server test suite**

Run focused runtime tests for voice and realtime websocket.

- [x] **Step 3: Android install smoke**

APK build is verified. A usable adb binary was found at `/Applications/wechatwebdevtools.app/Contents/Resources/bin/adb-macos/adb`; physical Redmi `24094RAD4C` was visible, `adb install -r android_app/app/build/outputs/apk/debug/app-debug.apk` returned `Success`, and `MainActivity` was started. Actual hold-to-talk behavior still requires the user to grant overlay/microphone permissions and perform a microphone smoke test on the phone.

Build APK and, if a device is connected, install it with ADB.

- [x] **Step 4: Record gaps**

Document any remaining gap that depends on a real Volcengine account state or device permission behavior.

## Self-Review

- The plan covers Android long press, recording, ASR streaming, Volcengine provider, existing chat handoff, permissions, tests, and docs.
- Secrets must remain outside git. The provided access token and secret key are only for local/remote environment configuration.
- The implementation deliberately keeps `/ws/voice` separate from `/ws` so model chat streaming and proactive messages are not destabilized.
