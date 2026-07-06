# Nomi 回归失败点与阻塞点跟踪

日期：2026-06-09
来源报告：`docs/superpowers/reports/2026-06-08-nomi-product-regression-run.md`
测试计划：`docs/superpowers/plans/2026-06-08-nomi-product-regression-test-plan.md`

## 判定原则

- HTTP 2xx、exit 0、build success 只代表技术命令成功，不代表产品语义通过。
- 失败点必须看输出内容是否正确合理。
- 阻塞点重试后必须更新为：`passed`、`failed`、`blocked` 或 `partial`。
- Provider-gated 能力未配置时不能标为通过。

## 失败点

| ID | 对应用例 | 当前状态 | 失败内容 | 影响 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| F-001 | RG-PRV-008 | failed | Model gateway 错误 payload 可能回显 provider exception 中的 `Authorization/token/secret`。 | 日志/API 响应可能泄露敏感信息。 | 统一错误脱敏，再补 probe 测试。 |
| F-002 | RG-AGD-001 | failed | `2026-06-10 15:00 在人民广场见` 未解析出 exact `start` 和地点。 | 精确日程、提醒、路线/打车建议错误。 | 修复显式日期时间和地点解析。 |
| F-003 | RG-COL-002 | failed | `周六下午3点武康路见` 时间正确，地点 `武康路` 未识别。 | 地点缺失会影响路线、打车和日程卡片。 | 增加 `X见/在X见/路/站/店` 地点模式。 |
| F-004 | RG-COL-004 | failed | Telegram `面试 panel 改到明天10:30，Zoom 链接我稍后发。` 被归为 `generic_event`，未生成日程/待办。 | 面试改期和待补链接无法主动提醒。 | 增加面试/Zoom/改期规则与模型校验。 |
| F-005 | RG-AGD/RG-COL | failed | `今晚 7点` 被解析为 `07:00`，应为 `19:00`。 | 中文时间语义严重错误。 | 修复 `今晚/晚上/明晚/下午` 的 12/24 小时规则。 |
| F-006 | RG-PRO-004 | failed | 低置信度“可能周末聊下”仍生成“查路线/帮我打车/稍后提醒”。 | 主动建议过于激进，可能打扰用户或误触外部动作。 | 缺时间/地点时只给澄清/稍后确认类动作。 |
| F-007 | RG-MEM-004 | failed/insufficient | `RG_Maya / Example AI / AI PM role` 未形成 recruiter-company-role 关系。 | Job Agent 的关系图谱支撑不足。 | 增加求职实体关系抽取和图谱 edge。 |
| F-008 | RG-PIPE/RG-OPEN | failed_test_harness | `scripts/validate-core-pipelines-openclaw.py` 读取 `Jsonb` 参数时报 `.get()` 崩溃。 | 回归脚本不能作为完整 pipeline/OpenClaw 凭证。 | 修复验证脚本 Jsonb 解包。 |
| F-009 | RG-PIPE-001 | failed | 18 条核心 pipeline 存在，但 registry 中 `risk=null`、`description=null`。 | 前端/Agent 无法解释 pipeline 风险和用途。 | 补齐 registry 元数据并验证。 |
| F-010 | RG-COMP-002 | failed_or_blocked | Composio connect flow 出现 `already_connected` 但无 `redirect_url`、无本地 audit。 | 授权状态不可解释，用户无法理解下一步。 | 修复 connect 状态机和 audit。 |
| F-011 | RG-AND/RG-VOICE | fixed_static_check | Android lint: `URLEncoder.encode(String, Charset)` 需要 API 33，但 `minSdk 26`。已改为 minSdk 26 兼容的 UTF-8 query encoder。 | Redmi/低 API 设备 API 兼容风险已消除；仍需单独验证悬浮窗输入法和发送响应体验。 | 已通过 `:app:testDebugUnitTest`、`:app:lintDebug`、`:app:assembleDebug`，并安装到 Redmi 真机。 |

## 阻塞点

| ID | 对应用例 | 之前状态 | 阻塞内容 | 影响 | 本轮重试状态 |
| --- | --- | --- | --- | --- | --- |
| B-001 | RG-PRE-002/RG-PRE-007 | blocked_by_local_environment | 本机 Docker daemon 未运行，无法验证 Docker 拓扑。 | 本地 compose 服务状态无法确认。 | partial：Docker daemon 已可用，但 compose 仍未启动成功，卡在 Docker Hub 拉取 `python:3.12-slim` EOF。 |
| B-002 | RG-PRE-007/RG-WEB/RG-BRW | blocked_by_online_environment | `http://206.119.171.141` 80/6080 请求 connection reset。 | 线上 Web/API/noVNC 不能验证。 | blocked：TCP 端口可连，但 HTTP 应用层仍 reset；SSH 端口连接后立即关闭。 |
| B-003 | RG-MODEL-001/RG-MODEL live | blocked_by_model_service | `http://81.70.177.246:9161` `/v1/models` 和 chat connection reset。 | Qwen live、真实聊天、模型 slot live 不能验证。 | blocked：TCP 端口可连，但 `/`、`/v1/models`、`/v1/chat/completions` 均未返回有效 HTTP。 |
| B-004 | RG-AND/RG-VOICE L4 | blocked_by_device_tooling | 之前本机无 `adb`，无法验证真机悬浮球/键盘/权限/录音。 | Android UI 和真机语音不能标通过。 | partial：adb 可用，Redmi 真机已识别，新 debug APK 已构建、安装并启动；悬浮窗闪烁、键盘顶起、发送响应仍需业务修复后复测。 |
| B-005 | RG-LIVE-* | blocked_by_provider_config | 真实 Gmail/WhatsApp/SMS/电话/Docs/LinkedIn/ATS provider 未配置或未授权。 | Provider live case 不能标通过。 | pending |

## 本轮阻塞点重试计划

1. Docker：执行 `docker compose ps`、必要时查看服务健康。
2. 真机：定位 `adb`，执行 `adb devices -l`，确认设备授权状态。
3. 线上入口：重试 `http://206.119.171.141/health`、`/api/memory/status`、`:6080/vnc.html`。
4. Qwen：重试 `http://81.70.177.246:9161/v1/models` 和最小 chat completion。
5. Android：如果 `adb` 可用，安装 debug APK 并确认设备可启动应用。

## 本轮重试结果

### B-001 Docker / Compose

执行结果：

- `docker info --format '{{json .ServerVersion}}'` 返回 `29.1.3`，daemon 已经启动。
- `docker compose ps -a` 只返回表头，没有运行中的 compose service。
- `docker compose up -d` 过程中已经拉到 `pgvector/pgvector:pg16`、`redis:7-alpine`、`nginx` 相关镜像，但构建本地服务时需要 `python:3.12-slim`。
- 单独执行 `docker pull python:3.12-slim` 仍失败：Docker daemon 从 `registry-1.docker.io` 读取 manifest 时 EOF。
- 尝试 `m.daocloud.io/docker.io/python:3.12-slim` 和 `docker.m.daocloud.io/library/python:3.12-slim` 后仍失败，失败点是镜像层 blob 下载 EOF。

语义判断：

- 之前“Docker daemon 没开”的阻塞已解除。
- 当前不是 Nomi 业务逻辑失败，而是 Docker Hub 镜像拉取链路不稳定，导致本地 compose 不能完整启动。
- 因为服务没有起来，不能把本地 Docker 拓扑、API 健康检查、worker 调度标为通过。

下一步：

- 换 Docker registry mirror 或手动预拉/导入 `python:3.12-slim` 后重试 compose。
- compose 正常启动后再执行 `health`、队列、worker、model-router、nginx 路由验证。

### B-002 线上私有云入口

执行结果：

- `curl -i http://206.119.171.141/health` 仍为 `Recv failure: Connection reset by peer`。
- 之前 `nc` 验证过 `80`、`6080`、`10799` TCP 端口可连，但 SSH 连接到 `10799` 后会被远端立即关闭。

语义判断：

- 安全组/端口连通不是主要问题。
- 线上服务在应用层主动断开连接，可能是 nginx/runtime 未运行、监听服务异常、或防火墙/代理策略只接受特定来源。
- 不能验证线上 Web/API/noVNC，也不能作为回归通过证据。

下一步：

- 需要恢复 SSH 或通过云厂商控制台进入服务器，检查 `docker compose ps`、nginx/runtime 日志和监听进程。

### B-003 Qwen 线上模型服务

执行结果：

- `curl -i http://81.70.177.246:9161/`：connection reset。
- 用户补充的 `curl -i http://81.70.177.246:9161/v1`：connection reset。
- `curl -i http://81.70.177.246:9161/v1/`：connection reset。
- `curl -i http://81.70.177.246:9161/v1/models`：connection reset。
- `curl -i -H 'Content-Type: application/json' -d ... http://81.70.177.246:9161/v1/chat/completions`：connection reset。
- `curl -k -i https://81.70.177.246:9161/v1/models`：SSL syscall failure。
- `nc -vz -w 5 81.70.177.246 9161` 验证 `9161` TCP 端口可连。
- `curl -v http://81.70.177.246:9161/v1` 显示请求已完整发出，随后对端 `Recv failure: Connection reset by peer`，没有 HTTP status/body。

语义判断：

- 当前不能证明 Qwen 模型可用。
- 不是模型内容质量问题，而是客户端无法拿到任何有效 HTTP 响应。
- 不能执行真实聊天、slot live parse、长尾 agent live 模型链路验证。

下一步：

- 需要确认该服务是否要求内网访问、来源 IP 白名单、特定 Host/header、鉴权 header、或非 OpenAI-compatible path。
- 拿到可用调用方式后再做最小 ping、非流式 chat、流式 chat 三段验证。

### B-004 Android 真机 / ADB

执行结果：

- `/opt/homebrew/share/android-commandlinetools/platform-tools/adb version` 可用。
- `adb devices -l` 现在能识别真机：`model:24094RAD4C device:beryl`。
- `adb shell getprop ro.product.model` 返回 `24094RAD4C`。
- `adb shell pm list packages | rg -i 'nomi|par|background'` 显示 `com.par.assistant.android` 已安装。
- `adb shell dumpsys window ...` 显示当前焦点为 `com.par.assistant.android/.MainActivity`。
- 首次 `gradle :app:assembleDebug` 使用 JDK 26 时失败，根因是 Android JDK image transform 调用 JDK 26 `jlink` 失败。
- 切换到 JDK 17 后，`gradle :app:assembleDebug` 构建成功。
- `gradle :app:lintDebug` 首次失败，根因是 4 个 `URLEncoder.encode(String, Charset)` 调用要求 API 33；已改为 `UrlEncoding.queryComponent(...)`。
- 修复后 `gradle :app:testDebugUnitTest` 通过。
- 修复后 `gradle :app:lintDebug` 通过。
- 修复后 `gradle :app:assembleDebug` 通过，APK 路径为 `android_app/app/build/outputs/apk/debug/app-debug.apk`。
- `adb install -r android_app/app/build/outputs/apk/debug/app-debug.apk` 返回 `Success`。
- `adb shell dumpsys package com.par.assistant.android` 显示 `versionName=0.1.0`，`lastUpdateTime=2026-06-09 14:24:30`。
- `adb shell monkey -p com.par.assistant.android -c android.intent.category.LAUNCHER 1` 可启动应用。
- 真机截图 `/tmp/nomi-redmi-after-install.png` 显示配置页正常渲染：服务器地址、访问密码、保存并测试连接、启动 Nomi、打开完整工作台均可见。
- `brew install android-platform-tools` 备用安装失败，原因是 `dl.google.com` DNS 解析失败；但已有 adb 可用，所以不再阻塞 ADB 本身。

语义判断：

- 真机工具链阻塞已大幅缓解：设备已连上，Nomi 已安装、可启动、配置页可渲染。
- F-011 API 兼容静态检查已修复，有单测、lint、构建和真机安装证据。
- 仍不能把 Android UI 回归标为通过，因为用户实际反馈仍包括悬浮窗闪烁、键盘顶起、发送无响应等 UI/业务缺陷。
- 后续需要先修复 Android 代码，再重新构建 APK、安装到该 Redmi 真机，并用截图/logcat 验证每一步交互。

下一步：

- 修复 Android UI/输入法/发送状态缺陷。
- 生成新的 debug APK 后执行 `adb install -r`，再进行真机手动与日志联动验证。

### B-005 Provider Live

本轮未解除。

语义判断：

- Composio、Gmail、WhatsApp、Telegram、LinkedIn、SMS、电话、ATS、Google Docs 等真实 provider 的 live case 仍不能标通过。
- 这类用例需要可用 provider 授权、明确账号状态、以及防误操作的测试沙箱。

## 2026-06-09 18:20 继续修复与复测记录

### 已修复失败点

| ID | 状态 | 修复内容 | 验证结果 | 语义判断 |
| --- | --- | --- | --- | --- |
| F-001 | fixed | `runtime_api/app/model_gateway.py` 增加模型 provider 错误脱敏，统一处理 `Authorization: Bearer ...`、`token=...`、`secret=...`、`password=...`。 | `python3 -m pytest runtime_api/tests/test_model_gateway.py -q`：`6 passed`。 | API payload 不再回显原始 token/secret/password，同时仍保留 provider id、错误类型和结构化 unavailable message，合理。 |
| F-002 | fixed | `worker/app/worker.py` 支持显式日期 `2026-06-10 15:00`，并将日程时间解析为 `2026-06-10T15:00:00+08:00`。 | `worker/tests/test_worker_semantics.py::test_agenda_candidate_resolves_explicit_date_time_and_square_place` 通过。 | 页面不再显示“明天”这种依赖创建时间的模糊表达，输出绝对日期和周几，合理。 |
| F-003 | fixed | 地点抽取支持 `X见/在X见/去X见`，并清洗掉人物、日期和时间前缀。 | `test_agenda_candidate_extracts_place_before_meet_without_at_marker` 通过。 | `周六下午3点武康路见` 输出地点 `武康路`，不会误把整句当地点，合理。 |
| F-004 | fixed | 面试/Zoom/改期文本进入 appointment/reschedule，`Zoom 链接稍后发` 记录 `pending_artifacts=["zoom_link"]`。 | `test_agenda_candidate_handles_interview_reschedule_and_pending_zoom_link` 通过。 | 面试改期会生成日程，并保留待补 Zoom 链接，不会当普通事件丢掉，合理。 |
| F-005 | fixed | 中文 `今晚/明晚/晚上` 隐含晚间语义，`今晚 7点` 解析为 19:00。 | `test_agenda_candidate_for_exact_meeting_has_no_missing_fields` 通过，`start=2026-05-28T19:00:00+08:00`。 | 中文时间符合用户常识，合理。 |
| F-006 | fixed | 低置信度且缺地点的模糊约定不再给“查路线/帮我打车”，只给“补充时间地点/稍后提醒/查看原消息”。 | `test_low_confidence_fuzzy_social_plan_only_asks_for_clarification_actions` 通过。 | 主动建议变得保守，不会过早诱导外部动作，合理。 |
| F-007 | fixed | 求职事件额外写入 recruiter-company-role 关系边：`recruits_for_company`、`recruits_for_role`、`company_hiring_role`。 | `test_job_recruiter_company_role_relationships_are_persisted` 通过；`worker/tests` 全量 `61 passed`。 | Job Agent 可以利用关系图谱知道 recruiter、公司和岗位三者关系，不再只是泛化事实，合理。 |
| F-008 | fixed | `scripts/validate-core-pipelines-openclaw.py` 增加 `Jsonb` unwrap，trace payload 不再因 `.get()` 崩溃。 | `python3 scripts/validate-core-pipelines-openclaw.py` exit 0；关键 stage 均 `reasonable: true`。 | 验证脚本现在能完整检查路由、OpenClaw packet、trace、实时事件和敏感字段脱敏，合理。 |
| F-009 | fixed | `core_pipeline_registry()` 每条 pipeline 统一补 `description` 和结构化 `risk` 元数据。 | `test_pipeline_registry_endpoint_exposes_core_pipeline_contract`、`test_core_pipeline_registry_matches_design_pipeline_set` 通过。 | 前端/Agent 可解释 pipeline 用途、权限、确认门槛和外部副作用，合理。 |
| F-010 | fixed_for_local_state_machine | `already_connected` 的 Composio 分支也写 `composio_connect_requests` 和 `account_connections` 审计；验证脚本改为接受 `link_created` 或 `already_connected`，但都必须可审计。 | `python3 scripts/validate-composio-connect.py` exit 0；三段报告均 `reasonable: true`。 | 已连接账号不会卡在“无 redirect、无审计”的不可解释状态，合理。真实 Composio live 仍依赖 provider 授权。 |
| F-011 | fixed_static_and_installed | Android lint/API 兼容保持通过，并重新构建安装到 Redmi 真机。 | `gradle :app:lintDebug --rerun-tasks`、`:app:assembleDebug` 均 `BUILD SUCCESSFUL`；`adb install -r` 成功，`lastUpdateTime=2026-06-09 18:20:23`。 | 静态兼容和安装链路正常；悬浮窗闪烁/输入法顶起/发送响应仍需单独真机交互复测。 |

### 本轮附加验证

- `python3 -m pytest worker/tests -q`：`61 passed`。
- `python3 -m pytest runtime_api/tests/test_model_gateway.py -q`：`6 passed`。
- `python3 -m pytest runtime_api/tests/test_core_pipeline_engine.py runtime_api/tests/test_auth_and_model.py::test_core_pipeline_registry_matches_design_pipeline_set runtime_api/tests/test_model_gateway.py -q`：`42 passed`。
- `python3 -m pytest runtime_api/tests/test_pipeline_actions.py runtime_api/tests/test_pipeline_communication.py runtime_api/tests/test_job_agent_pipelines.py -q`：`53 passed`。
- `python3 scripts/validate-core-pipelines-openclaw.py`：exit 0，所有关键 OpenClaw/pipeline/trace stage 均 `reasonable: true`。
- `python3 scripts/validate-composio-connect.py`：exit 0，缺 key 阻断、已连接审计、toolkit sync 脱敏均合理。

### 仍阻塞或待 live 复测

| ID | 状态 | 最新证据 | 当前判断 | 下一步 |
| --- | --- | --- | --- | --- |
| B-001 | blocked_by_registry_dns | Docker Desktop 已启动，`docker info` 返回 `29.1.3`；`docker compose up -d --build` 失败于 `auth.docker.io` DNS/i/o timeout，无法拉 `python:3.12-slim`。 | 不是业务失败，是本机到 Docker Hub 鉴权/镜像服务链路不稳定；compose 拓扑仍不能标通过。 | 配置可用 Docker mirror、手动导入 `python:3.12-slim`，或在网络恢复后重跑 compose。 |
| B-002 | blocked_by_online_environment | 本轮未恢复线上私有云入口；之前记录仍是 HTTP 应用层 reset/SSH 连接立即关闭。 | 线上 Web/API/noVNC 仍不能作为通过证据。 | 需要恢复 SSH 或云控制台进入服务器检查 nginx/runtime/docker。 |
| B-003 | blocked_by_model_service_from_this_client | 重新按 `http://81.70.177.246:9161/v1` 测 `/v1/models`、`/v1/chat/completions`、`/v1/responses`、`/v1/completions`、`/health`，均 `Recv failure: Connection reset by peer`；`nc` 仍显示 TCP 9161 可连。 | 从本机链路不能证明 Qwen live 可用；当前是应用层 reset，不是模型内容质量失败。 | 需要确认服务是否要求来源 IP 白名单、特定 Host/header、鉴权、内网访问或非 OpenAI-compatible path。 |
| B-004 | partial | Redmi 真机已连接：`model:24094RAD4C device:beryl`；新 APK 已安装。 | 工具链和安装通过，但真实 UI 缺陷还需交互复测。 | 继续复测悬浮窗闪烁、键盘顶起、发送后响应、主动气泡、账号授权 overlay。 |
| B-005 | blocked_by_provider_config | 真实 Gmail/WhatsApp/Telegram/LinkedIn/SMS/电话/Docs/ATS provider live 仍依赖授权和 provider 配置。 | 不能把真实外部动作标为通过。 | 逐个配置 provider，并用沙箱账号或受控额度做 live case。 |

## 2026-06-09 18:45 全量回归失败修复与复测记录

### 新增修复点

| ID | 状态 | 根因 | 修复内容 | 验证结果 | 语义判断 |
| --- | --- | --- | --- | --- | --- |
| F-012 | fixed | OpenAI-compatible/Qwen 无 API key 请求被无条件附加默认 `headers`，旧 mock 与私有模型网关调用契约都不需要它。 | `runtime_api/app/model_client.py` 改为只有存在 API key 时才携带 `Accept`、`Content-Type`、`Authorization`；无 key 时让 `httpx json=` 自行处理。 | 定点 3 个 Qwen client 测试通过；`runtime_api/tests` 全量通过。 | 私有 Qwen `/v1` 网关请求更贴近实际调用形态；不影响 4sapi/Anthropic/Google 等需要 headers 的 provider。 |
| F-013 | fixed | `already_connected` 的 Composio 分支写本地审计时会在无测试 DB 的环境直接连接 `postgresql://test` 并崩溃。 | 抽出 `persist_already_connected_composio_state(...)`；真实 DB 可用时写 `composio_connect_requests` 和 `account_connections`，DB 不可用时不阻塞已连接状态返回。 | `test_composio_connect_does_not_reauthorize_already_connected_toolkit` 通过；`validate-composio-connect.py` 仍验证本地审计可写时必须写入。 | UI 不会因为本地审计临时不可写而反复弹授权；可写环境仍保留审计，合理。 |
| F-014 | fixed | 模型配置 API 只有测试设想，没有路由、保存函数和本地密钥信封。 | 新增 `/api/model/config` GET/PUT、`save_user_model_config`、`encrypt_model_api_key`、`decrypt_model_api_key`、`reset_model_gateway`；API 只返回 `api_key_hint`，不回显原文。 | `runtime_api/tests/test_model_config_api.py` 通过；`runtime_api/tests` 全量通过。 | 用户可配置模型 provider，密钥在本地加密存储，响应不泄露密钥，符合产品需求。 |

### 全量验证

- `python3 -m pytest runtime_api/tests -q`：`438 passed in 117.24s`。
- `python3 -m pytest worker/tests -q`：`61 passed`。
- `python3 scripts/validate-core-pipelines-openclaw.py`：exit 0；所有核心 pipeline、OpenClaw packet、trace、敏感字段释放、后台 job/realtime stage 均 `reasonable: true`。
- `python3 scripts/validate-composio-connect.py`：exit 0；缺 API key 阻断、已连接审计、toolkit sync 脱敏均 `reasonable: true`。
- 线上 Qwen：`http://81.70.177.246:9161/v1/chat/completions` 返回 HTTP 200；项目内 `QwenClient('http://81.70.177.246:9161/v1').chat(...)` 返回 `'pong'`。

### 阻塞点状态更新

| ID | 新状态 | 最新证据 | 当前判断 | 下一步 |
| --- | --- | --- | --- | --- |
| B-001 | blocked_by_registry_network | Docker daemon 可用；compose 仍卡在 Docker Hub `python:3.12-slim` 拉取/鉴权网络。 | 本地 Docker 拓扑仍不能标通过。 | 配置 mirror 或预导入镜像后重跑 compose。 |
| B-002 | blocked_by_online_environment | 本轮未恢复 `206.119.171.141` 私有云 HTTP/SSH。 | 线上私有云 Web/API/noVNC 仍不能作为通过证据。 | 需要通过 SSH 或云控制台检查远端 nginx/runtime/docker。 |
| B-003 | passed_live | `urllib` 最小 chat completion HTTP 200；项目 `QwenClient` 读取 `message.content` 得到 `'pong'`。返回体包含 `reasoning_content`，但客户端只取 `message.content`。 | Qwen3.6 live 基础链路可用；之前 connection reset 不是当前稳定状态。 | 后续做真实聊天/流式/slot live 时继续用 `/v1` base URL，并确认不把 `reasoning_content` 展示给用户。 |
| B-004 | partial | Redmi 真机已连接且 APK 已安装；本轮没有完成悬浮窗/键盘/发送响应手动复测。 | Android 工具链通过，UI 交互仍需专项复测。 | 继续处理悬浮窗闪烁、键盘顶起、发送无响应、主动消息气泡。 |
| B-005 | blocked_by_provider_config | 外部真实 Gmail/WhatsApp/Telegram/LinkedIn/SMS/电话/Docs/ATS provider 仍依赖授权和沙箱账号。 | 真实外部动作不能标通过。 | 配置 provider 后逐个跑受控 live case。 |

## 2026-06-09 18:58 Android 悬浮窗输入与发送 fallback 修复记录

### 新增修复点

| ID | 状态 | 根因 | 修复内容 | 验证结果 | 语义判断 |
| --- | --- | --- | --- | --- | --- |
| F-015 | fixed_static_installed | 输入框聚焦时布局计算总是丢弃真实 IME 可见底部，只使用固定键盘高度估算；在真机上容易造成面板跳动或输入框仍被遮挡。 | `FloatingPanelLayout.visibleBottomForInputFocus(...)` 改为优先使用看起来可信的真实 IME inset；检测值疑似来自 overlay 自身收缩时才回退估算。 | 新增/更新 `FloatingPanelLayoutTest`；`:app:testDebugUnitTest` 通过。 | 面板会更贴近真实键盘顶部，同时避免 overlay 自身 relayout 造成反馈回路，合理。 |
| F-016 | fixed_static_installed | 发送按钮可能抢走输入框焦点，导致键盘收起；聊天内容区也没有明确的“点击收键盘”行为边界。 | 发送按钮设为不可聚焦；发送后重新聚焦输入框并请求键盘；点击聊天内容区才清焦点并收键盘。 | `:app:testDebugUnitTest`、`:app:lintDebug`、`:app:assembleDebug` 均通过；新 APK 已安装到 Redmi。 | 符合“点发送不收键盘，点聊天内容区才收键盘”的交互要求。 |
| F-017 | fixed_static_installed | WebSocket `send()` 一旦返回 true，就不会走 HTTP fallback；如果服务端没有回 `chat_delta/chat_done/error`，UI 会长期卡在“正在思考...”。 | 新增 `StreamingChatFallbackPolicy`；WebSocket 发送 12 秒内无任何 delta 时自动切换普通 `/api/chat` 请求，并在气泡中提示“实时通道没有返回，正在切换普通请求...”。 | 新增 `StreamingChatFallbackPolicyTest`；`:app:testDebugUnitTest`、`:app:lintDebug`、`:app:assembleDebug` 均通过。 | 用户不会再看到无响应且无失败提示的空状态；如果已有流式增量则不抢跑 fallback，避免重复回复，合理。 |

### Android 验证状态

- `JAVA_HOME=/opt/homebrew/Cellar/openjdk@17/17.0.19/libexec/openjdk.jdk/Contents/Home gradle -p android_app :app:testDebugUnitTest`：`BUILD SUCCESSFUL`。
- `JAVA_HOME=/opt/homebrew/Cellar/openjdk@17/17.0.19/libexec/openjdk.jdk/Contents/Home gradle -p android_app :app:lintDebug`：`BUILD SUCCESSFUL`。
- `JAVA_HOME=/opt/homebrew/Cellar/openjdk@17/17.0.19/libexec/openjdk.jdk/Contents/Home gradle -p android_app :app:assembleDebug`：`BUILD SUCCESSFUL`。
- `adb install -r android_app/app/build/outputs/apk/debug/app-debug.apk`：`Success`。
- `adb shell dumpsys package com.par.assistant.android`：`lastUpdateTime=2026-06-09 18:54:43`。

### 仍需真机交互复测

| 项目 | 当前状态 | 原因 | 下一步 |
| --- | --- | --- | --- |
| 悬浮窗输入框是否仍闪烁 | blocked_by_locked_device | ADB 截图显示设备处于锁屏/息屏状态，无法捕获应用 UI。 | 设备保持解锁后重新点击悬浮球、点输入框、截图确认。 |
| 键盘是否把输入框顶到键盘上方 | blocked_by_locked_device | 同上。 | 解锁后用真机输入一段文本，确认输入框和发送按钮完整可见。 |
| 发送后是否返回内容或 fallback 提示 | blocked_by_locked_device | 代码层已补 fallback，但需要服务端/真机交互验证。 | 解锁后发送 `ping`，观察是否流式返回、HTTP fallback、或明确失败提示。 |

## 2026-06-09 21:05 Android UI 重构、后端契约修复与线上阻塞记录

### 新增修复点

| ID | 状态 | 根因 | 修复内容 | 验证结果 | 语义判断 |
| --- | --- | --- | --- | --- | --- |
| F-018 | fixed_static_installed | 悬浮对话框把“对话/求职/设置”作为顶层 tab，和最新交互要求不符；默认对话框不应像完整工作台。 | 移除顶层 tab 行；标题栏保留 Nomi，并将完整工作台、设置、关闭收成 icon；设置页增加“求职看板”和“登录账号”入口；求职看板页增加返回设置按钮。 | `FloatingPanelTabsTest` 先红后绿；`:app:testDebugUnitTest`、`:app:lintDebug` 均通过；此前新 APK 已 `adb install -r` 到 Redmi。 | 顶层悬浮窗回到“默认就是对话”的轻量形态；求职不再挤占第一层 UI，符合用户要求。 |
| F-019 | fixed_static_and_sampled | 红米真机上系统 IME inset 会低报键盘高度，导致输入框仍落在键盘区域，并可能触发布局反复重算。 | `FloatingPanelLayout.visibleBottomForInputFocus(...)` 增加“低报 IME inset”保护；服务端估算键盘高度调整到更贴近 Redmi 真机。 | 新增 `ignoresUnderreportedImeInsetWhenInputIsFocused` 测试，先失败后通过；安装后真机连续 10 次 UI 树采样中 panel bounds 固定为 `[68,172][1024,1252]`，输入框固定为 `[102,1031][753,1166]`。 | 不是只看截图：连续 bounds 无跳动，说明闪烁主因的 relayout 反馈回路被压住。仍需用户解锁后肉眼复核。 |
| F-020 | fixed_local_contract | Android 请求 `/api/career/board?limit=50`，线上旧服务返回 reset/404；本地代码在求职表未部署时也可能因 schema 缺失返回 500。 | 新增 Android runtime API 契约测试；`/api/career/board` 在缺表/缺列时返回语义化空看板：`status=schema_missing`、`profiles/opportunities/resume_versions/career_resumes/applications=[]`、`next_actions`。 | `python3 -m pytest -q runtime_api/tests/test_android_runtime_api_contract.py runtime_api/tests/test_job_agent_pipelines.py runtime_api/tests/test_context_pack_and_chat.py runtime_api/tests/test_auth_and_model.py`：`108 passed`。 | Android 求职页不应再因为本地 schema 尚未落完而显示 HTTP 404/500；输出会明确提示需要部署 schema 和写回数据，合理。 |
| F-021 | fixed_local_contract | Android `/api/chat` 超时表现为“发送失败：timeout”；本地 API 需要保证上游模型异常时返回可诊断 JSON，而不是路由缺失或断连。 | 新增契约测试覆盖模型上游 timeout；本地 `/api/chat` 路由存在，模型异常应返回可诊断错误。 | 同上 108 个 runtime API 契约/相关测试通过。 | 本地应用层不应吞掉错误；线上仍 reset 说明是部署/进程/反代层问题，不是 Android 路径或本地路由缺失。 |
| F-022 | fixed_config | `docker-compose.yml` 默认 `MODEL_BASE_URL` 为 `http://localhost:9161`，在容器内会指向容器自身，线上即使 runtime 恢复也可能打错模型地址。 | 将 compose 和 `.env.example` 默认模型地址改为用户指定的 `http://81.70.177.246:9161/v1`，仍允许通过环境变量覆盖。 | `docker compose config` 展开后 runtime-api、worker、model-router 均显示 `MODEL_BASE_URL: http://81.70.177.246:9161/v1`、`MODEL_NAME: qwen3.6`。 | 部署默认值与当前产品配置一致；不会再因为容器内 localhost 造成隐性模型 timeout，合理。 |

### 真机验证状态

- `python3 -m pytest runtime_api/tests -q`：`440 passed in 116.97s`。
- `:app:testDebugUnitTest`：`BUILD SUCCESSFUL`。
- `:app:lintDebug`：`BUILD SUCCESSFUL`。
- `:app:assembleDebug`：`BUILD SUCCESSFUL`。
- 新 APK 已在本轮安装到 Redmi，`lastUpdateTime=2026-06-09 21:40:53`；随后真机进入锁屏/休眠。
- `adb shell dumpsys power` 显示 `mWakefulness=Asleep`，`adb shell dumpsys window` 显示 `mDreamingLockscreen=true`。
- ADB 唤醒后仍为锁屏；上滑后再次进入休眠，因此当前无法完成肉眼 UI 复核。

语义判断：

- Android UI/输入法/发送状态的静态与单测证据已经成立。
- 视觉结果仍需用户保持真机解锁后复核：标题栏 icon、无顶层 tab、设置页中的“求职看板”、输入框键盘顶起、发送状态。

### 线上私有云阻塞状态

| ID | 状态 | 最新证据 | 当前判断 | 下一步 |
| --- | --- | --- | --- | --- |
| B-006 | blocked_by_remote_ssh_kex_reset | `nc` 显示 `206.119.171.141:22/10799/80` 均可连；但 `ssh -vvv -p 22/10799` 都停在 `Local version string SSH-2.0-OpenSSH_9.9` 后收到 `kex_exchange_identification: Connection closed by remote host`。 | 远端在 SSH 握手阶段即关闭连接，尚未进入密码认证；无法通过 SSH/rsync 部署新代码。 | 需要在云控制台重启实例或检查 sshd/安全软件/hosts.deny/fail2ban/iptables；恢复 SSH 后重新部署。 |
| B-007 | blocked_by_remote_http_reset | `curl -v http://206.119.171.141/health` 连接成功，请求发出后 `Recv failure: Connection reset by peer`；`/api/chat`、`/api/career/board` 同样 reset。 | HTTP reset 位于线上 nginx/runtime/docker 层，本地 FastAPI 测试不能复现；线上服务很可能旧镜像、nginx 异常、runtime 崩溃或系统防火墙 reset。 | 恢复 SSH 后执行 `docker compose ps`、`docker compose logs --tail=200 runtime-api nginx`，并在服务器内测 `curl 127.0.0.1:8080/health`。 |
| B-008 | blocked_by_dns | 本地 Docker daemon 已启动，且 `docker pull python:3.12-slim` 成功；复测 `docker compose build runtime-api model-router worker` 仍在容器内 `pip install` 阶段报 `Temporary failure in name resolution`，最终显示 `No matching distribution found for fastapi==0.115.6/psycopg==3.2.3`。进一步用宿主机 `curl https://pypi.org/simple/fastapi/` 和 `https://mirrors.aliyun.com/pypi/simple/fastapi/` 均解析超时；容器内默认 DNS 与 `--dns 8.8.8.8` 也均解析失败。 | 这是当前机器/网络 DNS 层阻塞，错误里的“找不到版本”是 DNS 失败后的 pip 表象，不是依赖版本真的不存在。 | 恢复本机 DNS/网络、配置可用代理或 mirror；也可在恢复 SSH 后优先在服务器侧构建部署。 |
| B-009 | blocked_by_qwen_reset_from_this_client | `curl -v http://81.70.177.246:9161/v1/chat/completions` 请求体完整发出后 `Recv failure: Connection reset by peer`；`/v1/models` 和 `/health` 同样 reset。 | 当前从本机不能证明 Qwen live 可用；这与早先一次 `pong` 结果矛盾，说明链路或服务状态不稳定。 | 若服务器 runtime 恢复，优先在私有云服务器内测 Qwen；同时确认是否存在来源 IP 白名单、请求 header、并发限制或服务重启。 |
