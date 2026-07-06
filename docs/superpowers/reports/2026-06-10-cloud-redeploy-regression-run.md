# Nomi 私有云重装后回归测试执行记录

日期：2026-06-10

测试计划：`docs/superpowers/plans/2026-06-10-cloud-redeploy-regression-test-plan.md`

## 1. 总结

本轮按专项回归计划执行了第一批预检、部分第二批功能冒烟、Android 真机基础检查、私有事件采集链路、求职看板、Composio 状态、Nomi 自有身份接口。18:47 在用户解锁真机后继续补测了 Android 悬浮球、键盘布局、线上受保护 API、Android 对话最终收敛、主动建议与日程输出质量。

结论：

- 基础设施大体可用：服务器 HTTP、noVNC 页面、Docker 服务、本地构建和单元测试通过。
- qwen3.6 上游模型可用，直接 model-router 6.11 秒返回合理内容。
- `/api/chat` 内容语义正确，但耗时仍偏高：容器内一次简单请求耗时 79.08 秒；从本地直打线上受保护 API 的一次简单请求耗时 25.92 秒；Android 真机发送 `ping` 最终返回 `pong`，但经历实时通道 fallback 和长等待，按验收标准仍判定为失败。
- 私有事件 `/event` 能入队，但 worker 游标落后，60 秒内没有写入 semantic、memory、agenda、suggestion，按验收标准判定为 P0 失败。
- 主动建议和日程存在语义污染：Gmail 页面标题 `Gmail: Secure, AI-Powered Email for Everyone | Google Workspace` 被误判为 appointment/social followup，进入 `/api/agenda` 和 `/api/suggestions`，输出不合理。
- 求职看板接口已不是 404，返回 ready 空看板，符合空状态 API 预期。
- Android 真机可连接，App 可启动。启动 Nomi 后桌面只保留一个 Nomi 小人悬浮球；点击悬浮球能打开默认对话框；输入框聚焦后键盘会弹出且输入框被顶到键盘上方。连接测试会显示“连接正常”，但它只验证公开 `/health`，不足以证明受保护接口可用。
- Composio 状态 reachable；Nomi 自有身份列表可用；预期的 outbound 查询端点 `/api/assistant-outbound` 返回 404，需要对照产品接口或补统一查询端点。

## 2. 执行环境

| 项 | 实际值 |
| --- | --- |
| 本地仓库 | `/Users/wrf/Documents/background` |
| 私有云 Web | `http://206.119.171.141` |
| noVNC | `http://206.119.171.141:6080/vnc.html` |
| Android 真机 | `24094RAD4C` |
| Android 系统 | Android 14 |
| Android 分辨率 | 1080x2400 |
| APK | `android_app/app/build/outputs/apk/debug/app-debug.apk` |

## 3. 已执行用例

### CR-PRE-001 服务器 SSH 与端口连通

- 状态：`passed`
- 实际步骤与逐步验收：
  1. 测试 SSH TCP 端口。
     - 实际输出：`Connection to 206.119.171.141 port 22 [tcp/ssh] succeeded!`
     - 合理性判断：已进入 TCP/SSH 层，网络和安全组不是阻塞点。
     - 结论：通过。
  2. 使用 BatchMode SSH 测试。
     - 实际输出：`Permission denied (password).`
     - 合理性判断：这是预期的密码登录失败，说明已到认证阶段，不是连接前断开。
     - 结论：通过。
  3. 请求 `/health`。
     - 实际输出：`{"status":"ok"}`，HTTP 200。
     - 合理性判断：响应来自 Nomi health，不是默认页面。
     - 结论：通过。
  4. 请求 noVNC 页面。
     - 实际输出：返回 noVNC HTML，HTTP 200。
     - 合理性判断：noVNC 静态入口可达。
     - 结论：通过。
  5. 18:55 复测 Web 基础入口。
     - 实际输出：`/health` HTTP 200，body 为 `{"status":"ok"}`；`/` HTTP 200，title 为 `Nomi Personal Assistant`；`:6080/vnc.html` HTTP 200，title 为 `noVNC`。
     - 合理性判断：公网 HTTP、Web 首页、noVNC 静态入口都已恢复。此前一次 Python 读取 `/`、`/health` timeout 未复现，按瞬时请求异常记录，不作为当前阻塞。
     - 结论：通过。

### CR-WEB-001 Web 首页静态结构

- 状态：`passed`
- 实际步骤与逐步验收：
  1. 请求 Web 首页。
     - 实际输出：HTML title 为 `Nomi Personal Assistant`。
     - 合理性判断：返回的是 Nomi 工作台，不是云厂商默认页或 nginx 错误页。
     - 结论：通过。
  2. 检查登录结构。
     - 实际输出：页面包含 `passwordInput` 和 `loginForm`。
     - 合理性判断：密码保护入口存在。
     - 结论：通过。
  3. 检查工作台导航结构。
     - 实际输出：页面包含“对话、日程、搜索、治理、建议、采集、工具”等 tab 文本。
     - 合理性判断：完整工作台静态结构存在。
     - 结论：通过。
  4. 限制说明。
     - 实际输出：本轮未在浏览器中完成登录后的可视化交互。
     - 合理性判断：静态结构通过不等价于 Web 对话、日程、建议交互通过；这些仍需依赖慢请求和事件链路修复后复测。
     - 结论：部分产品交互未覆盖。

### CR-PRE-002 Docker 服务拓扑

- 状态：`passed`
- 实际步骤与逐步验收：
  1. 执行 `docker compose ps`。
     - 实际输出：`postgres`、`redis`、`runtime-api`、`worker`、`model-router`、`nginx`、`chromium-runtime` 均为 Up，其中 `postgres`、`redis`、`model-router` healthy。
     - 合理性判断：核心拓扑完整，无关键容器缺失。
     - 结论：通过。
  2. 扫描最近日志。
     - 实际输出：未发现新的 `error|exception|traceback|502|connection refused|address already in use|/v1/v1`；只有 model-router health 访问日志。
     - 合理性判断：没有明显服务崩溃或代理错误。
     - 结论：通过。

### CR-PRE-003 Runtime API 启动不被 embedding 阻塞

- 状态：`passed`
- 实际步骤与逐步验收：
  1. 运行回归单测。
     - 命令：`python3 -m pytest runtime_api/tests/test_vector_and_suggestions.py::test_lifespan_does_not_block_or_fail_on_embedding_warmup -q`
     - 实际输出：`1 passed in 0.50s`
     - 合理性判断：测试覆盖 embedding warmup 异常不阻塞 lifespan 的核心行为。
     - 结论：通过。
  2. 线上 `/health`。
     - 实际输出：`{"status":"ok"}`。
     - 合理性判断：服务已启动且响应健康检查。
     - 结论：通过。

### CR-PRE-004 Model Router qwen3.6 调用

- 状态：`passed`
- 实际步骤与逐步验收：
  1. 运行 URL 归一化单测。
     - 命令：`python3 -m pytest model_router/tests/test_model_router.py -q`
     - 实际输出：`3 passed in 0.26s`
     - 合理性判断：覆盖 `/v1/v1/chat/completions` 回归点。
     - 结论：通过。
  2. 请求线上模型状态。
     - 实际输出：provider `qwen3.6`，base URL 以 `/v1` 结尾，`unavailable=false`，`success_count=3`。
     - 合理性判断：模型配置被 Runtime API 识别，且存在成功调用记录。
     - 结论：通过。
  3. 直接请求 model-router。
     - 实际输出：HTTP 200，耗时 6.11 秒，content 为“模型可用”。
     - 合理性判断：qwen3.6 上游可用，输出符合“请只回复：模型可用”的语义要求。
     - 结论：通过。

### CR-CHAT-001 Web/API 对话基础回复

- 状态：`failed`
- 实际步骤与逐步验收：
  1. 从 Runtime API 调用 `/api/chat`。
     - 实际输出：第一次 45 秒超时，0 字节返回。
     - 合理性判断：用户侧会看到 timeout 或空白等待，不能接受。
     - 结论：失败。
  2. 在 warm 后从容器内重试 `/api/chat`。
     - 实际输出：HTTP 200，耗时 79.08 秒，answer 为“模型可用”。
     - 合理性判断：语义正确，但性能不合理。移动端 read timeout 为 90 秒，已经接近极限，真实用户会频繁失败。
     - 结论：失败。
  3. 分段计时 chat 前置链路。
     - 实际输出：`retrieve_context` 单步耗时 28.19 秒，其余历史对话、日程、任务上下文、context pack 构建都在 0.1 秒内。
     - 合理性判断：瓶颈在长期记忆/向量检索路径，且会放大首包延迟。
     - 结论：定位到高风险瓶颈。

### CR-CHAT-003 WebSocket/流式输出

- 状态：`not_executed`
- 原因：当前 `/api/chat` 普通请求已经 79.08 秒，先记录 P0 性能失败；WebSocket 流式体验需在 chat 前置检索修复后复测。

### CR-AND-001 悬浮球默认状态

- 状态：`passed`
- 实际步骤与逐步验收：
  1. adb 检测真机。
     - 实际输出：设备 `24094RAD4C` online，Android 14，分辨率 1080x2400。
     - 合理性判断：真机连接正常。
     - 结论：设备通过。
  2. 启动 Nomi。
     - 实际输出：点击“启动 Nomi”后回到系统桌面，屏幕左侧只保留一个 Nomi 小人悬浮球。
     - 合理性判断：符合“默认只有一个悬浮球，点击后才打开页面”的产品要求。
     - 结论：通过。
  3. 点击悬浮球。
     - 实际输出：打开默认对话框，标题为 `Nomi`，顶部只有视觉/设置/关闭 icon，没有“对话/求职/设置”tab。
     - 合理性判断：符合“默认就是对话框，求职放到设置里，设置收成 icon”的最新交互要求。
     - 结论：通过。

### CR-AND-003 输入框与键盘布局

- 状态：`passed`
- 实际步骤与逐步验收：
  1. 点击悬浮对话框输入框。
     - 实际输出：系统输入法弹出，`dumpsys input_method` 显示 `mInputShown=true`。
     - 合理性判断：点击输入框能够自动弹出键盘。
     - 结论：通过。
  2. 观察输入框位置。
     - 实际输出：输入框与发送按钮整体上移，位于键盘上方，没有被键盘遮挡。
     - 合理性判断：用户能看到输入内容和发送按钮。
     - 结论：通过。

### CR-AND-004 发送状态与失败提示

- 状态：`failed`
- 实际步骤与逐步验收：
  1. 检查 Android 配置页。
     - 实际输出：服务器地址为线上 IP，访问密码栏仍显示旧配置。
     - 合理性判断：后续 `/api/chat` 会因为密码不一致失败或表现异常。
     - 结论：配置不一致。
  2. 点击“保存并测试连接”。
     - 实际输出：截图和 UI 层级中均未出现“连接正常”或“连接失败”。
     - 合理性判断：用户点击后没有明确反馈，不符合“失败时必须给出明确提示”的验收标准。
     - 结论：失败。
  3. 检查服务端 `/api/chat` 性能。
     - 实际输出：语义正确但耗时 79.08 秒。
     - 合理性判断：即使密码正确，Android 端也容易进入 timeout。
     - 结论：失败。
  4. 解锁真机后发送 `ping`。
     - 实际输出：Android 先显示 `实时通道没有返回，正在切换普通请求...`，约 75 秒后服务端历史落库 `user=ping`、`assistant=pong`，UI 最终显示 `Nomi\npong`。
     - 合理性判断：失败提示不再 silent，最终语义正确；但等待时间不可接受，不符合即时对话体验。
     - 结论：仍失败。
  5. 检查同轮服务端历史。
     - 实际输出：同一 `ping` 后出现 `pong` 和 `\n\npong` 两条 assistant 记录。
     - 合理性判断：实时通道与普通 fallback 可能双写，用户可能看到重复消息或历史污染。
     - 结论：新增失败点。

### CR-MEM-001 WhatsApp/Gmail/Telegram 事件入库

- 状态：`failed`
- 实际步骤与逐步验收：
  1. 注入 WhatsApp 测试消息。
     - 输入：`RG_20260610_EVENT_001 明天下午4点在人民广场见，带合同。`
     - 实际输出：`/event` 返回 HTTP 200，`status=queued`，event_id 已生成。
     - 合理性判断：原始事件入库和入队成功。
     - 结论：第一步通过。
  2. 轮询 `/api/events/{event_id}/trace` 60 秒。
     - 实际输出：`semantic_event=false`，`memory_vectors=0`，`agenda_items=0`，`suggestions=0`。
     - 合理性判断：事件没有进入语义、记忆、日程、主动建议；不能算采集链路通过。
     - 结论：失败。
  3. 检查 Redis stream。
     - 实际输出：`events:raw` last-entry 是该测试事件；worker last_id 停在更早的 stream id。
     - 合理性判断：事件在 stream 中，但 worker 游标落后，说明消费链路卡住或无法追上。
     - 结论：失败。
  4. 解锁真机后再次注入明确 WhatsApp 约定事件。
     - 输入：`RG_20260610_EVENT_002 明天 16:00 在人民广场见，带合同。`
     - 实际输出：`/event` 返回 HTTP 200，`status=queued`，event_id 为 `84f9aa87-a586-4b44-9575-32e9f3b37a91`。
     - 合理性判断：原始事件入队仍正常。
     - 结论：第一步通过。
  5. 轮询该事件 trace 30 秒。
     - 实际输出：15 次轮询均为 `semantic=false`、`vectors=0`、`agenda=0`、`suggestions=0`。
     - 合理性判断：明确用户消息仍未被消费到语义/记忆/日程/建议链路。
     - 结论：失败复现。

### CR-AGD-001 相对时间必须归一为具体日期

- 状态：`failed`
- 实际步骤与逐步验收：
  1. 请求 `/api/agenda`。
     - 实际输出：HTTP 200，返回 1 条 item，标题为 `Gmail: Secure, AI-Powered Email for Everyone | Google Workspace`，type 为 `appointment`，certainty 为 `fuzzy`。
     - 合理性判断：Gmail 页面标题不应该被写入日程，更不应该作为 appointment。
     - 结论：失败。
  2. 检查 time_window。
     - 实际输出：`raw_text` 为 Gmail 页面标题重复文本，`has_exact_time=false`，`has_fuzzy_time=false`，missing_fields 包含 `exact_time`、`exact_place`。
     - 合理性判断：该记录没有可执行时间地点，不应作为可跟进日程展示；如果必须保留，也应作为低价值浏览/focus 事件而非约定。
     - 结论：失败。
  3. 注入明确 WhatsApp `明天 16:00` 事件。
     - 实际输出：事件 30 秒内没有生成 agenda，因此无法验证相对日期归一。
     - 合理性判断：真约定不处理，噪声却入日程，日程链路整体不合理。
     - 结论：失败。

### CR-AGD-002 周视图 Tab

- 状态：`not_executed`
- 原因：本轮只验证 API `/api/agenda`，返回空 items；Android 日程 UI 需在悬浮窗启动并有 agenda 数据后复测。

### CR-PRO-001 主动建议语义合理

- 状态：`failed`
- 实际步骤与逐步验收：
  1. 请求 `/api/suggestions?limit=10`。
     - 实际输出：返回 1 条 open suggestion，title 为 `跟进近期安排`，body 为 `这条信息可能需要跟进：Gmail: Secure, AI-Powered Email for Everyone | Google Workspace。`
     - 合理性判断：页面标题不是用户关系、待办、约定或可行动消息；该建议会打扰用户。
     - 结论：失败。
  2. 查看 Android 主动气泡。
     - 实际输出：悬浮对话框上方气泡显示“跟进近期安排 / 这条信息可能需要跟进：Gmail: Secure, AI-Powered Email for...”
     - 合理性判断：用户看不懂且不可操作，属于低质量主动消息。
     - 结论：失败。
  3. 与 CR-MEM-001 对照。
     - 实际输出：明确 WhatsApp 约定没有生成建议。
     - 合理性判断：主动建议链路方向反了：噪声被推送，真消息未处理。
     - 结论：失败。

### CR-JOB-001 求职看板不 404

- 状态：`passed`
- 实际步骤与逐步验收：
  1. 请求 `/api/career/board`。
     - 实际输出：HTTP 200，`status=ready`，profiles/opportunities/resume_versions/career_resumes/applications 均为空数组。
     - 合理性判断：已修复 404；空状态结构化，前端可以展示“还没有求职数据”的空状态。
     - 结论：通过。

### CR-COMP-001 Session 与 toolkit 列表/状态

- 状态：`partial_passed`
- 实际步骤与逐步验收：
  1. 请求 `/api/tools/composio/status`。
     - 实际输出：`configured=true`，`reachable=true`，`mcp_server_count=0`。
     - 合理性判断：Composio 后端可达；但还没有验证具体 session toolkits 列表和连接状态。
     - 结论：部分通过。

### CR-AI-001 Nomi 自有 Gmail/WhatsApp/Phone 身份

- 状态：`partial_passed`
- 实际步骤与逐步验收：
  1. 请求 `/api/assistant-identities`。
     - 实际输出：返回 3 个身份：Nomi Gmail、Nomi WhatsApp、Nomi Phone，状态均为 configured。
     - 合理性判断：身份基座存在。
     - 结论：通过。
  2. 请求 `/api/assistant-inbox`。
     - 实际输出：HTTP 200，空 items。
     - 合理性判断：空状态结构化。
     - 结论：通过。
  3. 请求 `/api/assistant-outbound`。
     - 实际输出：HTTP 404。
     - 合理性判断：如果产品需要查看 Nomi 代发记录，这是缺口；如果真实接口另有名称，需要文档和客户端统一。
     - 结论：失败/待确认。

### CR-SEC-001 敏感信息不泄露

- 状态：`passed`
- 实际步骤与逐步验收：
  1. 扫描本轮新增回归计划文档。
     - 实际输出：未发现已知真实密码、token、secret、API key。
     - 合理性判断：安全检查通过。
     - 结论：通过。
  2. 本轮报告编写。
     - 实际输出：不记录真实访问密码、token、secret。
     - 合理性判断：可分享给开发排查。
     - 结论：通过。

## 4. 本地自动化测试结果

| 命令 | 结果 | 合理性判断 |
| --- | --- | --- |
| `git diff --check` | 退出码 0，无输出 | 当前 diff 无空白错误 |
| `node --check runtime_api/app/static/app.js` | 退出码 0，无输出 | 前端 JS 语法通过 |
| `python3 -m pytest model_router/tests/test_model_router.py -q` | 3 passed | 模型路由路径归一化相关测试通过 |
| `python3 -m pytest runtime_api/tests/test_vector_and_suggestions.py::test_lifespan_does_not_block_or_fail_on_embedding_warmup -q` | 1 passed | embedding warmup 不阻塞 lifespan 测试通过 |
| `python3 -m pytest runtime_api/tests -q` | 441 passed | Runtime API 单元/契约测试通过 |
| `python3 -m pytest worker/tests/test_worker_semantics.py -q` | 61 passed | Worker 语义规则单元测试通过 |
| `JAVA_HOME=<JDK17> gradle testDebugUnitTest :app:assembleDebug --no-daemon` | BUILD SUCCESSFUL | Android debug 构建和单元测试通过 |

## 5. 失败点与阻塞点

### P0-1 `/api/chat` 语义正确但耗时不可接受

- 证据：同一简单请求返回“模型可用”，但耗时 79.08 秒；本地直打线上受保护 API 的 `请只回复：快测` 返回“快测”，但耗时 25.92 秒；Android `ping` 最终返回 `pong`，但约 75 秒才落库。
- 进一步定位：直接 model-router 仅 6.11 秒；Runtime `retrieve_context` 单步耗时 28.19 秒。Android 先走实时通道，随后 fallback 到普通请求，说明实时通道首包也不稳定。
- 用户影响：Android 端会出现 timeout、空白气泡或极长等待。
- 建议修复：
  - 给 chat 前置检索加分阶段超时和降级策略。
  - 首包路径优先返回当前对话和少量 BM25，向量/RAG 慢路径异步补充。
  - 对 FastEmbed 首次加载做真正启动 warmup，并确保 chat 不等待首次加载。
  - 在 Android 端保留明确 loading 和可重试，但根因应优先在服务端性能修复。

### P0-1b 实时通道 fallback 与普通请求可能双写

- 证据：服务端 `/api/chat/history?limit=3` 中，`ping` 后出现两条 assistant 记录：`pong` 与 `\n\npong`。
- 合理性判断：同一用户输入只能产生一条最终 assistant turn；如果实时通道失败后 fallback，必须有 request id / turn id 去重。
- 用户影响：历史对话重复、上下文污染、后续模型召回重复内容。
- 建议修复：
  - Android 发送 chat 时生成 `client_request_id`。
  - WebSocket 和 HTTP fallback 使用同一个 `client_request_id`，服务端对同一 conversation/user turn 做幂等。
  - fallback 启动后如果实时通道晚到 `chat_done`，应忽略或合并，不应再落一条 assistant。

### P0-2 私有事件入队后 worker 没有及时处理

- 证据：第一次 WhatsApp 测试事件是 `events:raw` last-entry；60 秒内 trace 无 semantic/memory/agenda/suggestion；worker last_id 停在更早 stream id。第二次明确 WhatsApp 约定事件 `84f9aa87-a586-4b44-9575-32e9f3b37a91` 入队成功，但 30 秒内 trace 仍为 semantic=false、vectors=0、agenda=0、suggestions=0。
- 用户影响：WhatsApp/Gmail/Telegram 新消息无法变成长期记忆、日程或主动建议。
- 建议修复：
  - 检查 worker stream 消费循环是否被某条事件阻塞。
  - 对单条事件处理增加超时、失败隔离和 dead-letter。
  - 增加 worker lag 指标和 `/api/worker/status`。
  - 浏览器网络噪音事件过多，应考虑降采样或低优先级队列，避免阻塞用户消息。

### P0-3 Android 连接测试反馈语义不足

- 证据：解锁真机后点击“保存并测试连接”会显示“连接正常”，但本质只证明公开 `/health` 可访问；不能证明访问密码、受保护 API、对话接口、WebSocket 可用。
- 用户影响：用户可能看到“连接正常”后继续发送消息，但真实对话仍慢或失败。
- 建议修复：
  - health 请求期间按钮显示 loading。
  - 成功/失败状态写入明显文本，并至少保留数秒。
  - 测试连接应同时验证 `/health` 和受保护 API，避免公开 health 成功但密码错误。

### P0-4 主动建议和日程被低价值 focus/browser 事件污染

- 证据：`/api/suggestions?limit=10` 返回 “Gmail: Secure, AI-Powered Email for Everyone | Google Workspace” 的跟进建议；`/api/agenda` 也把该页面标题写成 appointment。
- 用户影响：Nomi 会主动打扰用户，且内容像页面标题噪声，不是私人助理该主动提醒的事项。
- 建议修复：
  - `focus`、`browser_network_event`、页面标题类事件默认不允许生成 appointment/proactive suggestion。
  - 只有出现明确消息来源、联系人、动作、时间/地点/截止日期/金额等高置信证据时，才进入日程/主动建议。
  - 对低置信事件保留为浏览上下文或短期状态，不进入用户可见主动提醒。
  - 为 semantic parser 增加反例测试：Gmail/Google/LinkedIn 页面标题不能生成日程或主动建议。

### P1-1 Nomi outbound 查询端点 404

- 证据：`/api/assistant-identities` 和 `/api/assistant-inbox` 可用；`/api/assistant-outbound` 返回 404。
- 用户影响：如果产品需要展示 Nomi 代发记录，当前无法统一查询。
- 建议修复：
  - 对照真实路由名；如果没有，补 `/api/assistant-outbound` 或修改 Android/Web 调用。

## 6. 未执行或需要复测

| 用例 | 状态 | 原因 |
| --- | --- | --- |
| CR-CHAT-003 WebSocket/流式输出 | 未执行 | `/api/chat` 普通路径已 P0 失败，需修复后复测 |
| CR-AND-001 完整悬浮球默认状态 | 阻塞 | 当前真机在配置页，需确认悬浮窗权限和正确密码 |
| CR-AND-003 键盘布局 | 阻塞 | 还未进入悬浮对话框 |
| CR-AND-006 主动消息气泡 | 阻塞 | worker 未生成 proactive suggestion |
| CR-BRW-001 noVNC 交互 | 部分执行 | 仅验证页面 HTTP 200，未做完整视觉交互 |
| CR-BRW-002 登录渠道正确页面 | 未执行 | 需要在 noVNC/Android 账号页交互验证 |
| CR-AGD-001 相对时间归一 | 阻塞 | worker 未生成 agenda |
| CR-AGD-002 周视图 Tab | 未执行 | 需要 agenda 数据和 Android/Web UI 交互 |
| CR-LTA-001 Long-tail Agent | 未执行 | 本轮先停在 P0 基础链路失败 |
| CR-VOICE-001/002 语音输入 | 未执行 | 需要 Android 悬浮球进入可用状态并授权麦克风 |

## 7. 下一步建议

1. 先修 `/api/chat` 慢请求：让简单对话在 5-10 秒内返回，超时必须可见。
2. 修 worker 消费滞后：保证用户消息优先于浏览器网络噪音事件处理，且单条事件失败不阻塞队列。
3. 修 Android 连接测试：同时测公开 health 和受保护 API，并显示明确反馈。
4. 修 Android 配置导入/密码错误提示：避免用户看不见根因。
5. 修或确认 Nomi outbound 查询接口。
6. 复测 CR-MEM-001、CR-AGD-001、CR-PRO-001、CR-AND-004。
