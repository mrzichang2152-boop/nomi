# 2026-07-07 Open Task Artifact Follow-up

## Scope

Goal: close the remaining complex/open task gap so a true Android device can ask Nomi to complete an artifact task such as:

> 那你帮我做一个 ppt，让普通人可以理解 LLM 的工作原理

Expected behavior:

- `/api/chat` returns quickly with a clear task-accepted response.
- OpenCode artifact execution runs outside `runtime-api`.
- API container is not killed by artifact generation.
- Task state reaches `completed` / `delivered` after artifact verification.
- Android true device can see the task response and completion result.
- Every step is checked for output quality, not just exit status.

## Completed Local Fixes

### 1. Isolated OpenCode artifact worker from runtime API

Implemented a dedicated Docker Compose service:

- `opencode-artifact-worker`
- command: `python -m app.opencode_artifact_worker_entrypoint`
- `ENABLE_OPENCODE_ARTIFACT_WORKER=true`
- runtime API default: `ENABLE_OPENCODE_ARTIFACT_WORKER=false`
- shared volume: `artifact_data:/app/artifacts`
- memory/CPU limit applied to the worker, not the API container.

Reason:

- Previous cloud evidence showed `runtime-api` could be OOM-killed while generating artifacts.
- Isolating artifact execution prevents long OpenCode subprocesses from killing chat/realtime.

### 2. Fixed materialized task state sync after artifact completion

Root cause found:

- `OpenCodeArtifactWorker.run_task()` correctly completed the graph and generated a verified artifact.
- `process_due_opencode_artifact_tasks_once()` only synchronized materialized DB state on skipped tasks.
- On successful processing, it logged completion but did not write final graph state back to `long_tail_task_runs`.
- Result: artifact existed, worker log said completed, but DB/UI could still show `running`.

Fix:

- After `run_opencode_artifact_worker_once(task_id)`, reload final state with `require_long_tail_task(task_id)`.
- Call `sync_long_tail_task_run_materialized_state(task_id, final_state)`.
- Include `final_status` and `final_node` in structured worker logs.

Expected post-fix state:

- `status=completed`
- `current_node=delivered`
- `completed_at` populated

## Local Verification

Commands run:

```bash
python3 -m pytest runtime_api/tests/test_opencode_artifact_worker.py::test_process_due_opencode_artifact_tasks_once_syncs_completed_state_after_worker_success -q
```

Result:

- `1 passed`
- This test was first observed failing with `synced_states == []`, confirming the regression test caught the actual bug.

```bash
python3 -m pytest runtime_api/tests/test_opencode_artifact_worker.py -q
```

Result:

- `25 passed`

```bash
python3 -m pytest runtime_api/tests -q
```

Result:

- `713 passed`

Output quality checked:

- The prior cloud artifact test generated a valid 6-slide `.pptx`.
- Slide content was coherent:
  - explains tokenization
  - explains attention
  - explains next-token generation
  - explains why Nomi needs private context
  - explicitly states when no extra private material was used
- No private evidence was fabricated.

## Cloud Deployment Attempt

Attempted to deploy current workspace to:

- host: `206.119.171.141`
- project path: `/root/background`
- SSH port attempted: `10799`, then `22`

Deployment command attempted:

```bash
rsync -az --delete ... -e "sshpass ... -p 10799" /Users/wrf/Documents/background/ root@206.119.171.141:/root/background/
```

Observed failure:

- `ssh: connect to host 206.119.171.141 port 10799: Operation timed out`
- `rsync: error: unexpected end of file`

Further connectivity evidence:

```bash
nc -vz -w 5 206.119.171.141 22
```

Result:

- TCP port 22 accepted a connection.

```bash
sshpass ... ssh -vvv ... root@206.119.171.141 'echo ok'
```

Result:

- TCP connection established.
- SSH timed out during banner exchange.

```bash
curl -m 20 http://206.119.171.141/health
```

Result:

- HTTP timed out with no bytes received.

```bash
curl -m 12 http://206.119.171.141:6080/
```

Result:

- HTTP timed out with no bytes received.

```bash
ping -c 4 206.119.171.141
```

Result:

- 3/4 packets received.
- About 25% packet loss.
- RTT around 112-122 ms.

Conclusion:

- The cloud host is reachable at the network level, but user-space services are not responding reliably.
- SSH reaches TCP connection but `sshd` does not emit a banner.
- HTTP and noVNC ports also time out.
- This was a temporary server responsiveness blocker. The server later recovered and deployment continued.

## Cloud Deployment Completed

Deployment retried through SSH port `22` after the server recovered.

```bash
rsync -az --delete ... /Users/wrf/Documents/background/ root@206.119.171.141:/root/background/
docker compose -p nomi up -d --build runtime-api opencode-artifact-worker
```

Service verification:

```text
nomi-runtime-api-1 RestartCount=0 OOMKilled=false ExitCode=0
nomi-opencode-artifact-worker-1 RestartCount=0 OOMKilled=false ExitCode=0
```

Runtime API environment:

```text
ENABLE_OPENCODE_ARTIFACT_INLINE_RUN=false
ENABLE_OPENCODE_ARTIFACT_WORKER=false
OPENCODE_ARTIFACT_WORKER_LEASE_SECONDS=300
```

Artifact worker environment:

```text
ENABLE_OPENCODE_ARTIFACT_WORKER=true
OPENCODE_ARTIFACT_COMMAND=python /app/scripts/nomi_opencode_cli_adapter.py
OPENCODE_ARTIFACT_FALLBACK_COMMAND=python /app/scripts/nomi_opencode_artifact_command.py
OPENCODE_ARTIFACT_WORKER_LEASE_SECONDS=300
```

Health check:

```text
GET /health -> 200
```

## Cloud API Artifact Regression

Request:

```text
请用 OpenCode 帮我生成一个 PPT，让普通人理解 LLM 怎么工作，最多 6 页，语言通俗，并给出可下载文件。
```

Result:

- `/api/chat` returned `200`.
- Elapsed time: `5.823s`.
- Task id: `lta_26421492e35544cca951278f75a6729b`.
- Response correctly said the task was handed to OpenCode.
- Response also correctly stated missing traceable materials instead of pretending to have private evidence.

Worker evidence:

```json
{
  "event": "opencode_artifact_worker_task_processed",
  "task_id": "lta_26421492e35544cca951278f75a6729b",
  "status": "completed",
  "final_status": "completed",
  "final_node": "delivered",
  "elapsed_ms": 183590
}
```

DB evidence:

```text
id=lta_26421492e35544cca951278f75a6729b
status=completed
current_node=delivered
current_step_id=verify_artifact_delivery
executor_adapter=opencode
```

Artifact evidence:

```text
artifact_id=artifact_27a4266232d34e8baf4e82568bf8f5bf
artifact_type=pptx
verification_status=verified
download_url=http://206.119.171.141/api/artifacts/artifact_27a4266232d34e8baf4e82568bf8f5bf/download
```

Polling evidence:

- 22 polls.
- All artifact polls returned HTTP 200.
- No 502 observed in this regression.

Container stability:

```text
nomi-runtime-api-1 RestartCount=0 OOMKilled=false
nomi-opencode-artifact-worker-1 RestartCount=0 OOMKilled=false
```

PPT quality check:

- File type: Microsoft OOXML.
- Slide count: 6.
- Content summary:
  1. LLM as context-based text prediction, not a database or conscious person.
  2. Tokenization and vectors.
  3. Attention and context lookup.
  4. Step-by-step token generation.
  5. Why Nomi needs private context.
  6. Explicitly says no extra private material was found and the deck is based on the current request.
- Output is coherent and aligned with the user request.
- It does not fabricate private evidence.

## True Android Device Status

Expected device:

- `DQYTCYFMO7VSEAJB`

Observed earlier in the session:

- Device was online.
- Nomi floating panel accepted a PPT request and showed:
  - user message in the conversation
  - `Nomi 正在思考...`
  - then a task-accepted response saying the task was handed to OpenCode.

Current evidence:

```bash
adb devices -l
```

Result:

- no devices listed.

```bash
adb kill-server && adb start-server && adb devices -l
```

Result:

- ADB restarted successfully.
- no devices listed.

Conclusion:

- True-device verification cannot continue until the device is reconnected/authorized.
- No simulator or fake device was used as a substitute.

## Remaining Gaps

### Blocked by true device ADB disconnect

- Reconnect Android device.
- Trigger a fresh complex task from the floating panel.
- Track:
  - UI submit result
  - realtime/fallback behavior
  - task id
  - artifact generation status
  - final UI download/result message
- Verify the generated artifact content is coherent and grounded.

### Residual item to re-check after deployment

- One prior cloud artifact polling run had a transient `502` while the artifact later completed and API containers were not OOM-killed.
- Fresh cloud artifact task after this deployment had 22 HTTP 200 artifact polls and no observed 502.
- This should still be watched during true-device testing because Android uses realtime/fallback paths in addition to artifact polling.

## Next Required Actions

1. Reconnect the true Android device and confirm `adb devices -l` lists it.
2. Run true-device artifact task from the floating panel.
3. Track Android UI message, realtime/fallback result, task id, artifact id, and download link.
4. Take screenshots of the accepted-task response and final artifact result.
5. Update this report with true-device task ids, screenshots, and pass/fail conclusions.

## 2026-07-08 Follow-up: Async Artifact Delivery and True Device Download

### Root Causes Closed

1. Android only rendered artifacts returned synchronously from `/api/chat`.
   - OpenCode artifact tasks usually complete asynchronously after the initial chat response.
   - Fix: Android now tracks `taskRunId`, polls `/api/tasks/{taskRunId}/artifacts`, and renders verified artifact cards once.

2. External browser artifact download was fragile on the Redmi true device.
   - Previous behavior: artifact card opened `ACTION_VIEW` with a raw `http://206.119.171.141/...` URL.
   - True-device evidence: Xiaomi browser showed a "境外可疑 IP" interstitial and a separate download sheet; after continuing, the file did not reliably appear in `/sdcard/Download`.
   - Fix: artifact card now downloads inside the Nomi app through Android `DownloadManager`, sends `x-par-password` as a request header, and writes directly to `Environment.DIRECTORY_DOWNLOADS`.

3. PPT quality did not strictly obey requested slide count.
   - Failed evidence: task `NOMI_REAL_PPT_0708D_make_4_slide_PPT_about_agent_memory_for_founders` produced a downloadable PPT, but it had 5 slides and generic content.
   - Fix: artifact command extracts explicit slide counts and has a specific "agent memory" outline. Worker verification now blocks PPTX artifacts whose actual slide count does not match an explicit requested count.

### Code / Test Coverage Added

- Android:
  - `AssistantApiClient` parses `taskRunId` and exposes `taskArtifacts(taskRunId)`.
  - `RealtimeClient` passes `taskRunId` through `onChatDone(...)`.
  - `FloatingBallService` polls async task artifacts and renders deduped artifact cards.
  - `ArtifactDownloadUrls` resolves artifact URLs for external browser and app-internal download paths.
  - Artifact cards now use app-internal `DownloadManager` instead of external browser `ACTION_VIEW`.

- Backend:
  - `/api/artifacts/{artifact_id}/download` accepts either `x-par-password` or query `password` for compatibility.
  - OpenCode artifact command respects explicit requested slide count.
  - OpenCode worker validates explicit PPTX slide count during verification.

Automated verification:

```text
python3 -m pytest runtime_api/tests/test_opencode_artifact_worker.py runtime_api/tests/test_artifact_tasks.py -q
41 passed
```

```text
gradle :app:testDebugUnitTest
BUILD SUCCESSFUL
```

Specific TDD evidence:

- `FloatingPanelAppEntryContractTest.floatingPanelDownloadsArtifactsInsideAppInsteadOfExternalBrowser`
  - First failed because the code still used external `ACTION_VIEW`.
  - Passed after switching artifact card clicks to `DownloadManager`.

### Cloud Verification

Cloud health:

```text
GET http://206.119.171.141/health -> {"status":"ok"}
```

Containers:

```text
nomi-runtime-api-1                running
nomi-opencode-artifact-worker-1   running
nomi-postgres-1                   running (healthy)
nomi-redis-1                      running (healthy)
nomi-model-router-1               running (healthy)
```

Quality-fixed cloud task:

```text
task_id: lta_4bb126e473a64ceea2cc833b860c8285
artifact_id: artifact_f67d6911ae154af7a76cc465f14d0f26
request: NOMI_REAL_PPT_0708E_make_4_slide_PPT_about_agent_memory_for_founders
status: completed / delivered
artifact: verified
```

Downloaded PPTX verification:

```text
bytes: 33783
slides: 4
```

Slide content was checked, not just file existence:

1. `Agent Memory 是什么`
2. `三类核心记忆` including KV, relationship graph, and RAG
3. `记忆生命周期`
4. `落地建议`

The output is aligned with the requested agent-memory topic and no longer violates the requested 4-slide count.

### True Android Device Verification

Device:

```text
DQYTCYFMO7VSEAJB
```

New true-device task after installing the DownloadManager build:

```text
task_id: lta_69e92554d2024701b45f9753085e8e81
artifact_id: artifact_e50b62febcb5485abd014c4285df4d14
request from floating panel: NOMI_REAL_PPT_0708F_make_4_slide_PPT_about_agent_memory
status: completed / delivered
artifact: verified
```

True-device UI result:

- Nomi floating panel accepted the message.
- Nomi returned the OpenCode handoff message.
- After async polling, the floating panel rendered:

```text
文件已准备好
NOMI_REAL_PPT_0708F_make_4_slide_PPT_about_agent.pptx
PPTX · 已校验
点击下载
```

True-device download result after clicking the card:

```text
/sdcard/Download/NOMI_REAL_PPT_0708F_make_4_slide_PPT_about_agent.pptx
```

Pulled back from the phone and parsed locally:

```text
bytes: 33783
slides: 4
```

Slide content again matched the requested topic:

1. `Agent Memory 是什么`
2. `三类核心记忆` with KV, relationship graph, and RAG
3. `记忆生命周期`
4. `落地建议`

Conclusion:

- The true-device complex task path is now verified end to end:
  - Android floating panel message
  - cloud `/api/chat`
  - long-tail task creation
  - OpenCode artifact worker execution
  - artifact verification
  - Android async polling
  - artifact card rendering
  - app-internal device download
  - pulled PPTX content validation

### 2026-07-08 Download Feedback Fix

User-reported issue:

```text
真机最近一条回复里有“点击下载”，点击后用户看起来没有下载。
```

Root cause verified on the true device:

- The file was actually being enqueued into Android `DownloadManager`.
- However, the artifact card kept showing `点击下载` after tap, so the UI gave no visible confirmation.
- Repeated taps could enqueue duplicate downloads before the user saw any result.

Device evidence before the fix:

```text
/sdcard/Download/NOMI_REAL_PPT_0708F_make_4_slide_PPT_about_agent.pptx
/sdcard/Download/NOMI_REAL_PPT_0708F_make_4_slide_PPT_about_agent-1.pptx
/sdcard/Download/NOMI_REAL_PPT_0708F_make_4_slide_PPT_about_agent-2.pptx
/sdcard/Download/NOMI_REAL_PPT_0708F_make_4_slide_PPT_about_agent-3.pptx
/sdcard/Download/NOMI_REAL_PPT_0708F_make_4_slide_PPT_about_agent-4.pptx
```

Code fix:

- `FloatingBallService` now tracks `startedArtifactDownloadKeys`.
- On card tap, the card immediately changes to:

```text
已开始下载
<filename>
已保存到系统下载目录
```

- The card is disabled after the first tap, so the same artifact cannot be queued repeatedly from repeated taps.

Tests:

```text
gradle :app:testDebugUnitTest --tests com.par.assistant.android.FloatingPanelAppEntryContractTest.floatingPanelShowsArtifactDownloadStateAndPreventsDuplicateEnqueue
gradle :app:testDebugUnitTest
```

Both passed.

True-device validation after installing the fixed APK:

```text
Device: DQYTCYFMO7VSEAJB
Generated artifact card: download_feedback.pptx
Card after click:
  已开始下载
  download_feedback.pptx
  已保存到系统下载目录
Download path:
  /sdcard/Download/download_feedback.pptx
Downloaded file:
  bytes: 28741
  slides: 1
Duplicate check:
  /sdcard/Download/download_feedback*.pptx count = 1
```

Conclusion:

- The click now gives immediate visible feedback.
- The file lands in the Android system download directory.
- Repeated tapping on the same card no longer creates duplicate files.

### Remaining Follow-up

- The app-internal download fixes the immediate true-device blocker.
- A future production hardening item remains: serve artifacts through HTTPS/domain rather than raw `http://206.119.171.141`, so external browsers and other apps do not flag the host as suspicious when a user manually opens copied links.
