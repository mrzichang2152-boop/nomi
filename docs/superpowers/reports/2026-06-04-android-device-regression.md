# 2026-06-04 Android Device Regression

## Scope

Validate the current Nomi Android floating assistant against the live private-cloud server at `http://206.119.171.141`.

## Device Availability

- Earlier in the day, `adb devices -l` only listed `emulator-5554`.
- During the streaming voice-input follow-up, the standard `adb` binary was not on PATH, but a usable adb binary was found at `/Applications/wechatwebdevtools.app/Contents/Resources/bin/adb-macos/adb`.
- Current physical device visibility:
  - Device id: `DQYTCYFMO7VSEAJB`
  - Model: `24094RAD4C`
  - Product/device: `beryl`
  - State: `device`
- Result: physical Redmi phone is now visible to adb. Installation/startup was verified; long-press voice UX still needs on-device permission and microphone interaction verification.

## Build And Install

- Command: `JAVA_HOME=/opt/homebrew/opt/openjdk@17 gradle :app:testDebugUnitTest --tests com.par.assistant.android.WebWorkspaceKeyboardTest :app:assembleDebug`
- Result: `BUILD SUCCESSFUL`.
- APK install result on `emulator-5554`: `Success`.
- Streaming voice-input APK install result on physical Redmi via `adb install -r android_app/app/build/outputs/apk/debug/app-debug.apk`: `Success`.
- Physical Redmi startup command `adb shell am start -n com.par.assistant.android/.MainActivity`: started `com.par.assistant.android/.MainActivity`.
- Runtime config confirmed in Android app SharedPreferences:
  - `base_url`: `http://206.119.171.141`
  - password configured locally.

## Verified Behaviors

### G1 Chat History Restore

- Evidence: `/tmp/nomi-android-floating.png`, `/tmp/nomi-workbench-open-realcoords.png`.
- Observed output: previously sent chat messages and assistant messages were restored after reinstall/restart.
- Assessment: reasonable and correct for emulator. Physical phone still pending because adb does not see it.

### G2 Chat Pending, Keyboard, And Error Feedback

- Evidence: `/tmp/nomi-android-keyboard.png`, `/tmp/nomi-android-after-send-1s.png`, `/tmp/nomi-android-after-send-13s.png`.
- Observed output:
  - Keyboard appears when input is focused.
  - Composer stays above the keyboard.
  - Send does not immediately dismiss the keyboard.
  - Pending message shows `正在结合本地记忆思考...`.
  - When the model is unavailable, the assistant bubble shows `模型服务暂时不可用，请稍后重试。`.
- Model status: `/api/model/status` reported `qwen36_primary` closed/unreachable; direct curl to `http://81.70.177.246:9161` failed.
- Assessment: UI behavior is correct; final answer streaming is blocked by the external model endpoint.

### WebWorkspaceActivity ANR Risk

- Initial evidence: `/tmp/nomi-android-agenda-after-fix-3.png` was black and `dumpsys window` showed `Application Not Responding: com.par.assistant.android`.
- Fix: removed UI-thread `webView.clearCache(true)` and retained `WebSettings.LOAD_NO_CACHE`.
- Verification:
  - Unit/build command passed.
  - Reopened workbench through floating panel with actual 1080x2400 tap coordinates.
  - `dumpsys window` showed focus on `com.par.assistant.android/.WebWorkspaceActivity` and no ANR.
- Assessment: fixed for emulator repro.

### G7 Agenda Absolute Date UI

- Evidence before fix: `/tmp/nomi-agenda-absolute-title-after-fix.png` showed title `明天下午4点人民广场见面` while time field showed `2026-06-02 周二 16:00`.
- Root cause: `time_window.raw_text` was `明天下午4点在人民广场见，带合同。`, while model title was summarized as `明天下午4点人民广场见面`; exact replacement did not match.
- Fix: `formatAgendaTitle` now falls back to extracting relative title phrases such as `明天...点` and `周五...点`.
- Verification:
  - `python3 -m pytest -q runtime_api/tests/test_static_workbench_agenda_tab.py` -> `13 passed`.
  - Live server health returned `{"status":"ok"}`.
  - Served JS contained `agendaRelativeTitleTimeText`.
  - Android WebView after close/reopen showed `2026-06-02 周二 16:00 人民广场见面`.
- Evidence after fix: `/tmp/nomi-agenda-title-after-reopen.png`.
- Assessment: fixed and visually verified on emulator.

## Additional Data-Quality Fix

- Finding: historical Nomi assistant replies had been written as agenda items, including ordinary replies such as asking what task to run next.
- Root cause: rules fallback could create agenda candidates from `nomi_chat` assistant turns, and `is_agenda=false` model results were still allowed to fall back to rule candidates.
- Fix:
  - `role=assistant` Nomi chat turns now skip agenda candidate generation.
  - Explicit model `is_agenda=false` now vetoes rule fallback agenda writes.
- Verification:
  - `python3 -m pytest -q worker/tests/test_worker_semantics.py` -> `56 passed`.
  - Live injected `nomi_chat` assistant test event produced semantic intent `assistant_response`.
  - Live DB agenda association count for that event was `0`.
  - Cleaned 13 historical assistant-response agenda noise items by marking them `dismissed` and writing version records.
  - Rechecked active assistant-response agenda noise count: `0`.

## G8 Streaming Voice Input

### Scope

Validate the new long-press Nomi floating-ball voice input implementation:

- Android long-press starts a voice session instead of opening `MainActivity`.
- Android records PCM16 mono audio in 200ms chunks and streams it to `/ws/voice`.
- Server adapts Nomi JSON voice events to the Volcengine `bigmodel_async` streaming ASR protocol.
- ASR partial/final events return to Android.
- High-confidence final transcripts are sent into the existing realtime chat flow.

### Implemented Components

- Server:
  - `/ws/voice` route registered in `runtime_api/app/main.py`.
  - Provider abstraction in `runtime_api/app/voice/asr_provider.py`.
  - Fake provider in `runtime_api/app/voice/fake_provider.py` for deterministic tests.
  - Volcengine provider in `runtime_api/app/voice/volcengine_provider.py`.
  - Voice WebSocket bridge in `runtime_api/app/voice/voice_ws.py`.
- Android:
  - `VoicePressController` for tap/drag/long-press/cancel gesture separation.
  - `StreamingVoiceRecorder` for `AudioRecord` PCM16 capture.
  - `StreamingAsrClient` for `/ws/voice` JSON events.
  - `FloatingBallService` integration for voice bubble, partial text, confidence handling, and final transcript handoff to chat.
  - `RECORD_AUDIO` and Android 14+ microphone foreground service permission/type.

### Verification

- Android build and unit tests:
  - Command: `JAVA_HOME=/opt/homebrew/opt/openjdk@17 gradle :app:testDebugUnitTest :app:assembleDebug`
  - Result: `BUILD SUCCESSFUL`.
- Server voice/realtime tests:
  - Command: `python3 -m pytest tests/test_voice_ws.py tests/test_volcengine_asr_provider.py tests/test_realtime_ws.py -q`
  - Result: `14 passed`.
- Secret scan:
  - Command: `rg -n "<provided access token>|<provided secret key>" . || true`
  - Result: no matches.

### Output Reasonableness Check

- `/ws/voice` password rejection, `voice_start -> voice_ready`, `audio_chunk -> asr_partial`, `voice_end -> asr_final`, chunk-size rejection, and `voice_cancel` are covered by tests and produce structured user-visible events.
- Volcengine frame tests verify request header construction, gzip JSON payload frames, audio-only frames, server response parsing, error mapping, and confidence estimation. These are protocol-level checks rather than only import/compile checks.
- Android gesture tests verify that tap, drag, long-press voice start, slide-to-cancel, voice end, and action cancel resolve to distinct callbacks, reducing the risk of reopening the panel or duplicating floating windows during voice input.
- Android recorder tests verify PCM chunk sizing, sequence increments, and RMS level calculation without requiring a live microphone.
- Android ASR client tests verify outbound event JSON and inbound `voice_ready`, `asr_partial`, `asr_final`, and error parsing.

### Remaining Gaps

- Real Volcengine audio smoke has not been run in this report. The code reads credentials from environment variables only; the provided access token and secret key were intentionally not written into repo files.
- Real phone long-press UX still needs device verification after granting overlay plus microphone permissions. The APK is installed and the app starts on the Redmi, but this report cannot claim microphone-streaming behavior until the user grants permissions and performs a hold-to-talk smoke.
- If Volcengine returns a response shape not covered by the official sample protocol or current tests, the provider may need an additional parser branch after first live capture.

## Remaining Gaps

- Physical Android phone is visible to adb and the APK was installed. Remaining phone-side gap is granting/confirming overlay plus microphone permissions and running an actual hold-to-talk smoke.
- `qwen36_primary` at `http://81.70.177.246:9161` is unreachable, so live final answer streaming cannot be fully verified until the model service is restored.
- Historical agenda cleanup covered obvious Nomi assistant-response noise. Additional parser quality work may still be needed for subtler ambiguous user messages.
- Streaming voice input is implemented and locally verified by server/Android tests plus APK build, but still needs real Volcengine ASR and real-device long-press smoke before it should be called fully production-verified.
