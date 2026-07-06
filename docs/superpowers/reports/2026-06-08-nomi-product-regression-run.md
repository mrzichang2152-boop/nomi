# Nomi 产品回归执行报告

日期：2026-06-08 21:46 CST
测试计划：`docs/superpowers/plans/2026-06-08-nomi-product-regression-test-plan.md`
执行原则：HTTP/exit code 成功不等于通过；每个关键输出需要语义判断。

## Summary

本次执行覆盖了 L0/L1/L2 的大部分本地回归、Android 单元和构建、offline E2E fixture、语义验证脚本，以及 L3 线上入口预检。

结论：

- 本地静态、Runtime API、Worker、Chromium parser、model-router、Android 单元和构建均通过。
- 多数事件、记忆、上下文、Pipeline、Job Agent、Long-tail Agent、delegated automation 基座测试通过。
- 线上私有云入口当前不可用：80、6080、模型 9161 请求均出现 `Recv failure: Connection reset by peer`。
- 本机 Docker daemon 未运行，无法在本机完成 Docker 拓扑预检。
- 发现若干语义失败，不能用“单测通过”覆盖。
- Android lint、Pipeline registry 元数据、Composio connect 状态脚本均存在真实失败或测试阻塞。

## Commands

| Command | Result | Semantic Judgment |
| --- | --- | --- |
| `git diff --check` | exit 0 | 工作区 diff 没有 whitespace 错误。 |
| `node --check runtime_api/app/static/app.js` | exit 0 | Web 静态 JS 语法可解析。 |
| `python3 -m pytest runtime_api/tests -q` | `430 passed` | Runtime API 大量单元/集成测试通过，但不覆盖全部 live/provider 语义。 |
| `python3 -m pytest worker/tests -q` | `56 passed` | Worker 语义抽取基础测试通过。 |
| `python3 -m pytest chromium_runtime/tests model_router/tests -q` | `39 passed` | 采集 parser 和 model-router 协议测试通过。 |
| `python3 -m json.tool runtime_api/tests/fixtures/e2e_online_regression_dataset_2026_06_08.json` | exit 0 | Fixture JSON 可解析，内容包含 Gmail/WhatsApp/Telegram/Job/Long-tail/外部阻断等场景。 |
| `python3 -m pytest runtime_api/tests/test_e2e_online_regression_dataset.py -q` | `5 passed` | E2E fixture contract 通过。 |
| `JAVA_HOME=... gradle -p android_app testDebugUnitTest :app:assembleDebug` | `BUILD SUCCESSFUL` | Android 单元和 APK 构建通过；未代表真机 UI 行为全部通过。 |
| `JAVA_HOME=... gradle :app:lintDebug --rerun-tasks` | failed | Android lint 有 4 个 hard errors，不能被 build success 抵消。 |
| `docker compose ps` | failed | 本机 Docker daemon 未运行，Docker 拓扑用例本地阻塞。 |
| `python3 scripts/validate-private-event-processing.py` | exit 0 | 脚本逐 stage 输出 `reasonable: true`，但子代理补充探针发现若干额外语义缺陷。 |
| `python3 scripts/validate-core-pipelines-openclaw.py` | failed | 验证脚本因 `Jsonb` 参数 `.get()` 崩溃；产品相关 pytest 通过，脚本需修。 |
| `python3 scripts/assistant-identity-regression.py` | exit 1 | 13 个 case 中 11 个通过；Gmail/电话发送因 provider env 缺失被 blocked，按测试计划应归类为 provider 阻塞。 |
| `python3 -m pytest runtime_api/tests/test_context_pack_and_chat.py runtime_api/tests/test_vector_and_suggestions.py runtime_api/tests/test_pipeline_agenda.py -q` | `67 passed` | 上下文包、向量/建议、日程 pipeline 基础测试通过。 |
| `python3 -m pytest runtime_api/tests/test_core_pipeline_engine.py ... test_delegated_automation.py -q` | `143 passed` | Core pipeline、Job、Long-tail、delegated automation 基座测试通过。 |
| `python3 -m pytest runtime_api/tests/test_model_gateway.py ... -q` | `74 passed` | 模型网关、工具注册、任务编排协议测试通过。 |
| `python3 -m pytest runtime_api/tests/test_core_pipeline_engine.py -q` | `35 passed` | Core pipeline 单测通过，但 registry 元数据语义仍有缺口。 |
| `python3 -m pytest runtime_api/tests/test_job_agent_pipelines.py -q` | `21 passed` | Job Agent 主要 pipeline 本地通过；真实 L3 UI/Provider 未跑。 |
| `python3 -m pytest runtime_api/tests/test_long_tail_agent_runtime.py -q` | `45 passed` | Long-tail 状态机、checkpoint、外部动作门槛通过。 |
| `python3 -m pytest runtime_api/tests/test_delegated_automation.py -q` | `10 passed` | Delegated automation 策略和阻断逻辑通过。 |
| `python3 scripts/validate-long-tail-agent-runtime-v2.py` | passed | Long-tail runtime 验证脚本通过。 |
| `python3 scripts/validate-composio-connect.py` | failed | Composio connect 状态不一致：缺 API key/或 already_connected 无 redirect link/audit。 |
| `curl http://206.119.171.141/...` | connection reset | L3 线上 Web/API 当前不可达。 |
| `curl http://206.119.171.141:6080/vnc.html` | connection reset | noVNC 当前公网不可达。 |
| `curl http://81.70.177.246:9161/v1/models` | connection reset | Qwen live endpoint 当前不可达。 |
| `curl http://81.70.177.246:9161/v1/chat/completions` | connection reset | Qwen live chat 当前不可达，不能判定模型 live 可用。 |

## Passed Areas

- RG-PRE-001/RG-PRE-005/RG-PRE-006：本地鉴权相关测试、schema/静态资源测试通过。
- RG-WEB 静态/聊天/日程相关基础测试：通过 `test_static_workbench_agenda_tab.py`、`test_context_pack_and_chat.py` 间接覆盖；线上 Web 未执行。
- RG-AND 基础单元与构建：Android 单元和 APK build 通过；真机 UI 需要后续 live 操作。
- RG-BRW parser/injection：Gmail、WhatsApp、Telegram、Calendar parser 和 runtime injection 单测通过。
- RG-PRV 多数隐私治理：raw 加密、脱敏、授权读取、trace、governance audit、URL token 脱敏通过。
- RG-MEM 多数长期记忆：事件账本、semantic event、KV upsert、作用域隔离、supernode SQL、治理更正、context budget 通过。
- RG-CHAT：对话上下文、模型不可用提示、历史持久化相关测试通过。
- RG-PIPE/RG-JOB/RG-LTA/RG-DA：产品单测通过；高风险外部动作需要确认/授权的门槛存在。
- RG-AI：Nomi 自有 Gmail/WhatsApp/SMS/phone 事件归一化、作用域、草稿确认基本合理。
- RG-VOICE：ASR fake provider、Volcengine frame、Android 语音单元测试在全量/Android 测试中覆盖通过。
- RG-DB：schema/持久化相关单元测试通过；线上数据库重启恢复未执行。

## Failed Semantic Cases

### RG-PRV-008: Model Gateway 错误 payload 可能泄露 secret

状态：failed

观察：

- 子代理探针构造 provider 异常字符串包含 `Authorization: Bearer secret-token token=abc123`。
- model gateway 的 `reason/failures.error` 原样返回异常字符串。

判断：

- 这是明确语义失败。错误 payload 不能回显 token、Authorization header、secret。

### RG-AGD-001: 精确日程未正确解析

状态：failed

观察：

- 输入 `2026-06-10 15:00 在人民广场见`。
- 输出仍是 `certainty=fuzzy`，没有 `start`，`place=""`。

判断：

- 这不是“模型没开”的可接受降级。规则路径也应识别显式日期时间和地点。

### RG-COL-002: WhatsApp 地点识别不完整

状态：failed

观察：

- 输入 `周六下午3点武康路见`。
- 时间解析为 `2026-06-13T15:00:00+08:00`，合理。
- 地点未识别，仍缺 `exact_place`。

判断：

- 时间正确但地点缺失，会影响路线、打车、日程提醒动作。

### RG-COL-004: Telegram 面试改期未进入日程

状态：failed

观察：

- 输入 `面试 panel 改到明天10:30，Zoom 链接我稍后发。`。
- 规则路径变成 `generic_event`，agenda/suggestion 为 `null`。

判断：

- 该消息应至少生成面试改期/待补 Zoom 链接的日程或待办。

### 中文时间语义：`今晚 7点` 被解析为 07:00

状态：failed

观察：

- `今晚 7点` 输出 `2026-05-28T07:00:00+08:00`。

判断：

- 中文语境里“今晚 7点”应是 19:00。这会直接造成提醒/日程严重错误。

### RG-PRO-004: 低置信度建议过于激进

状态：failed

观察：

- 低置信度文本“可能周末聊下”仍生成“查路线/帮我打车/稍后提醒”。

判断：

- 低置信度/缺地点的关系或聊天信号不应直接给路线/打车动作，最多应给“补充时间/地点”或“稍后确认”。

### RG-MEM-004: 实体关系抽取不够具体

状态：failed/insufficient

观察：

- `RG_Maya / Example AI / AI PM role` 未形成明确实体关系，只落为 Gmail generic_event 泛化事实。

判断：

- Job Agent 场景需要 recruiter-company-role 关系，否则后续外联和岗位推进缺乏关系图谱支撑。

### Core Pipeline/OpenClaw 验证脚本崩溃

状态：failed_test_harness

观察：

- `scripts/validate-core-pipelines-openclaw.py` 在 `task_route_trace_persistence_payload_is_reasonable` 阶段崩溃：
  `AttributeError: 'Jsonb' object has no attribute 'get'`。

判断：

- 根因是验证脚本把 DB 参数中的 `Jsonb` 当 dict 读。产品相关 pytest 已通过，但回归脚本需要修复，否则不能作为完整 RG-PIPE/RG-OPEN 执行凭证。

### RG-PIPE-001: Pipeline Registry 元数据不完整

状态：failed

观察：

- 18 条核心 pipeline 均存在。
- 但 registry 样例里 `risk=null`、`description=null`。

判断：

- 这不满足回归文档对 `required_slots`、`risk`、`permission`、`description` 的要求。
- 这会影响前端/Agent 对 pipeline 风险和用途的解释，也会降低用户确认动作的可理解性。

### RG-COMP-002: Composio connect flow 状态不一致

状态：failed_or_blocked_by_provider_config

观察：

- 当前环境无 `COMPOSIO_API_KEY` 时，connect API 返回 `503 composio_api_key_missing`，这是合理阻塞。
- 但 `validate-composio-connect.py` 还观察到 `already_connected`、`redirect_url=""`、`local_audit_written=false` 的状态组合。

判断：

- 如果已连接，应有可审计状态；如果需要授权，应返回 redirect/connect link。
- 空 redirect 且无 audit 不够可解释，不能作为 RG-COMP-002 通过凭证。

### RG-AND/RG-VOICE: Android lint NewApi 硬失败

状态：failed_static_check

观察：

- `gradle :app:lintDebug --rerun-tasks` 报 4 个 error。
- `AssistantApiClient.java` 使用 `URLEncoder.encode(String, Charset)`，该 API 需要 API 33，但 app `minSdk 26`。
- `RealtimeClient.java` 和 `StreamingAsrClient.java` 也有同类 URL encoding NewApi 风险。

判断：

- 这会影响 chat history、career application PATCH、普通 `/ws`、`/ws/voice` URL 生成。
- Android unit/build 成功不能抵消该风险，因为真实 Redmi 设备 API 版本低于 33 时可能崩溃或行为异常。

## Blocked Cases

### 本机 Docker 拓扑

状态：blocked_by_local_environment

证据：

- `docker compose ps` 返回：`Cannot connect to the Docker daemon at unix:///Users/wrf/.docker/run/docker.sock. Is the docker daemon running?`

影响：

- 本机无法验证 `runtime-api`、`worker`、`postgres`、`redis`、`chromium-runtime` 的 Docker 拓扑。

### 线上私有云入口

状态：blocked_by_online_environment

证据：

- `curl http://206.119.171.141/health`：connection reset。
- `curl http://206.119.171.141/api/memory/status`：connection reset。
- `curl http://206.119.171.141:6080/vnc.html`：connection reset。
- SSH 10799 端口可连，但登录连接立即关闭。

影响：

- L3 Web/API/noVNC/线上 collector/pipeline/model/DB 预检无法完成。

### Qwen Live Endpoint

状态：blocked_by_model_service

证据：

- `curl http://81.70.177.246:9161/v1/models`：connection reset。
- `curl http://81.70.177.246:9161/v1/chat/completions`：connection reset。
- Qwen 客户端协议层单测通过，但真实模型服务不可达。

影响：

- RG-MODEL live、真实聊天流式输出、模型 slot 解析 live 不能判通过。
- RG-MODEL-002 目前只在 hash fallback 层返回 `dimensions=384,norm=1.0`，不接受固定 probe 文本，也缺少 cache/error 字段；只能算 partial。

### Provider-gated Live

状态：blocked_by_provider_config

范围：

- 真实 Gmail send。
- 真实 WhatsApp send/webhook。
- 真实 SMS。
- 真实 phone call。
- Google Docs write。
- LinkedIn/ATS browser executor。
- Live ASR。

证据：

- `assistant-identity-regression.py` 中 Gmail/phone outbound draft 在用户确认后仍因 provider env 缺失返回 `misconfigured`，没有伪造发送成功。

判断：

- 这符合安全预期，但不能算 live provider 通过。

### Android 真机/模拟器 UI

状态：blocked_by_device_tooling

证据：

- 子代理执行 `command -v adb` 无输出，本机当前无法通过 adb 安装、启动和操作设备。

影响：

- 悬浮球视觉、键盘顶起、关闭按钮、系统麦克风权限弹窗、真实录音 chunk、主动气泡点击进入对话等 L4 用例不能标为通过。

## Semantic Output Review

- 好的部分：上下文包能排除其他会话内容，Bob 私聊不会混入 Alice reply；模糊日程能保留缺失字段；外部动作绝大多数停在草稿/确认/授权门槛；Nomi 自有身份事件有独立作用域。
- 主要问题：中文时间/地点解析仍不稳，低置信度主动建议太激进，关系图谱对求职 recruiter/company/role 的结构化不足，错误脱敏不够严格。

## Recommended Fix Order

1. 修复 RG-PRV-008：统一错误 payload 脱敏，尤其是 model gateway/provider exceptions。
2. 修复中文时间解析：`今晚/明晚/下午/晚上` 的 12/24 小时转换。
3. 修复地点抽取：`在X见`、`X见`、`X咖啡店/地铁站/路` 等模式。
4. 修复 Telegram 面试/Zoom/改期识别。
5. 修复低置信度主动建议策略，缺时间/地点时不要给打车/路线动作。
6. 增强 Job Agent 关系图谱：recruiter-company-role-job edge。
7. 修复 `scripts/validate-core-pipelines-openclaw.py` 的 `Jsonb` 解析。
8. 修复 Android URL encoding NewApi lint errors，确保 minSdk 26 可运行。
9. 恢复线上私有云和 Qwen endpoint 后，重新跑 L3/L5。
10. 接入 adb 或手动真机流程后，重跑 RG-AND/RG-VOICE L4。
