# Nomi 产品功能完整回归测试文档

日期：2026-06-08
来源文档：`docs/superpowers/reports/2026-06-08-nomi-product-feature-description.md`

## 1. 测试目标

本回归文档用于验证当前代码中的 Nomi 产品能力是否仍然成立。测试重点不是“接口是否返回 200”，而是每一步输出是否正确、合理、可解释、可审计，并且不会把未授权、未配置或真实第三方未执行的动作伪造成已完成。

核心目标：

- 验证私有云部署、Web 工作台、Android 悬浮球、受控浏览器入口可用。
- 验证 Gmail、WhatsApp、Telegram、Calendar、浏览器行为等私有事件能进入事件账本、语义事件、长期记忆、日程、主动建议。
- 验证长期记忆的 KV、图谱、RAG、作用域隔离和治理能力。
- 验证 Web/Android 对话、流式输出、上下文包、历史恢复。
- 验证 18 条核心 Pipeline、Job Agent Pipeline、Long-tail Agent、OpenClaw、Composio、delegated automation 的路由、风险、确认和审计。
- 验证 Nomi 自有 Gmail、WhatsApp、SMS、单向电话和双工电话基座。
- 验证外部执行在未授权、缺 provider、缺证据、缺 target manifest 时必须明确阻断。
- 验证真实 provider 相关测试能区分 `passed`、`blocked_by_provider_config`、`failed`，不把配置缺口算成功。

## 2. 回归层级

| 层级 | 名称 | 执行环境 | 是否依赖外部真实账号 | 目的 |
| --- | --- | --- | --- | --- |
| L0 | 静态和单元回归 | 本地代码仓库 | 否 | 快速发现语法、单元逻辑、路由、适配器、解析错误 |
| L1 | 本地集成回归 | 本地 TestClient / fake provider | 否 | 验证 API、Pipeline、事件、记忆、日程、确认门槛 |
| L2 | Offline E2E fixture 回归 | 本地 synthetic dataset | 否 | 用固定私有事件复现端到端产品流程 |
| L3 | 私有云线上回归 | `http://206.119.171.141` 或部署域名 | 部分 | 验证真实部署、服务、WebSocket、数据库、noVNC、在线 API |
| L4 | Android 回归 | 模拟器和真实 Redmi 设备 | 部分 | 验证悬浮球、键盘、主动气泡、历史恢复、语音入口 |
| L5 | Provider-gated live 回归 | 私有云 + 已授权账号/provider | 是 | 验证 Gmail/WhatsApp/SMS/电话/Google Docs/LinkedIn/ATS 等真实 provider |

## 3. 全局执行规则

1. 每个 case 必须记录 `run_id`，格式建议：`rg-YYYYMMDD-<case_id>-<short_nonce>`。
2. 每个 case 必须记录输入事件、API 请求、实际响应、语义判断、证据 ID、失败分类。
3. HTTP 2xx 只代表传输成功，不代表产品通过。
4. 对日程、记忆、建议、回复草稿、Pipeline 输出，必须检查内容是否合理。
5. 任何真实外部动作都必须经过确认或 delegated grant；禁止自动发送、付款、购物、打车、Apply/Submit。
6. 未配置外部 provider 时，期望结果是 `misconfigured` 或 `blocked_by_provider_config`，不是 `completed`。
7. 测试数据必须带 `RG_` 或 `E2E_` 前缀，避免污染真实用户数据。
8. 测试结束后必须执行清理或标记数据为 regression record。
9. 任何响应、日志、trace、文档中不得泄露 access token、secret、cookie、authorization header、验证码。
10. 如果模型服务不可用，模型相关 case 只能标记为 `blocked_by_model_service`，不能标记为产品逻辑失败，除非系统没有给出合理错误提示。

## 4. 推荐执行命令

### 4.1 本地基础回归

```bash
git diff --check
node --check runtime_api/app/static/app.js
python3 -m pytest runtime_api/tests -q
python3 -m pytest worker/tests -q
```

期望：

- `git diff --check` 无输出，退出码 0。
- `node --check` 无语法错误。
- Runtime API 测试全部通过。
- Worker 测试全部通过。

### 4.2 Android 单元和构建回归

```bash
cd android_app
JAVA_HOME=/opt/homebrew/Cellar/openjdk@17/17.0.19/libexec/openjdk.jdk/Contents/Home gradle testDebugUnitTest :app:assembleDebug
```

期望：

- `BUILD SUCCESSFUL`。
- 不使用 JDK 26 做 Android 构建结论，因为当前 Android toolchain 对 JDK 17 更稳定。

### 4.3 Offline E2E fixture 回归

```bash
python3 -m json.tool runtime_api/tests/fixtures/e2e_online_regression_dataset_2026_06_08.json >/dev/null
python3 -m pytest runtime_api/tests/test_e2e_online_regression_dataset.py -q
```

期望：

- JSON fixture 可解析。
- Contract test 全部通过。
- fixture 中每个 case 都有 coverage、steps、expected、forbidden output。

### 4.4 线上私有云预检

```bash
curl -sS -H "x-par-password: $APP_PASSWORD" "$NOMI_BASE_URL/api/memory/status"
curl -sS -H "x-par-password: $APP_PASSWORD" "$NOMI_BASE_URL/api/collectors/status"
curl -sS -H "x-par-password: $APP_PASSWORD" "$NOMI_BASE_URL/api/pipelines/health"
curl -sS -H "x-par-password: $APP_PASSWORD" "$NOMI_BASE_URL/api/tools/composio/status"
```

期望：

- 服务返回结构化 JSON。
- 如果外部模型、Composio 或 provider 不可用，响应必须明确说明具体能力降级，而不是空白或假成功。

## 5. 覆盖矩阵

| 产品模块 | 必测 case |
| --- | --- |
| 部署和鉴权 | RG-PRE-001 至 RG-PRE-007 |
| Web 工作台 | RG-WEB-001 至 RG-WEB-008 |
| Android 悬浮球 | RG-AND-001 至 RG-AND-010 |
| 受控浏览器/noVNC | RG-BRW-001 至 RG-BRW-006 |
| Gmail/WhatsApp/Telegram/Calendar 采集 | RG-COL-001 至 RG-COL-009 |
| 私有事件、脱敏、治理 | RG-PRV-001 至 RG-PRV-008 |
| 长期记忆 | RG-MEM-001 至 RG-MEM-010 |
| 对话和上下文 | RG-CHAT-001 至 RG-CHAT-008 |
| 日程和主动建议 | RG-AGD-001 至 RG-PRO-006 |
| 18 条核心 Pipeline | RG-PIPE-001 至 RG-PIPE-022 |
| Job Agent | RG-JOB-001 至 RG-JOB-012 |
| Long-tail Agent / OpenClaw | RG-LTA-001 至 RG-OPEN-004 |
| Composio | RG-COMP-001 至 RG-COMP-006 |
| Nomi 自有通信身份 | RG-AI-001 至 RG-AI-012 |
| 语音输入和 ASR | RG-VOICE-001 至 RG-VOICE-007 |
| 分级授权和批量自动化 | RG-DA-001 至 RG-DA-010 |
| 模型与嵌入 | RG-MODEL-001 至 RG-MODEL-004 |
| 数据库、持久化、恢复 | RG-DB-001 至 RG-DB-006 |
| 安全、隐私、发布质量 | RG-SEC-001 至 RG-SEC-008 |

## 6. 通用判定格式

每条 case 的报告必须使用以下结构：

```json
{
  "case_id": "RG-XXX-000",
  "run_id": "rg-20260608-example",
  "status": "passed | failed | blocked_by_provider_config | blocked_by_model_service | skipped_by_scope",
  "steps": [
    {
      "name": "step name",
      "request": "method/path or command",
      "actual_summary": "observed output",
      "semantic_judgment": "reasonable | unreasonable | blocked",
      "evidence_ids": ["event_id", "trace_id"],
      "notes": "specific finding"
    }
  ],
  "forbidden_output_found": false,
  "cleanup_done": true
}
```

## 7. Preflight 用例

### RG-PRE-001: 鉴权门槛

优先级：P0
层级：L1/L3

步骤：

1. 不带 `x-par-password` 调用 `/api/memory/status`。
2. 带错误密码调用 `/api/memory/status`。
3. 带正确密码调用 `/api/memory/status`。

期望：

- 前两步返回 401。
- 正确密码返回 200 和结构化状态。
- 响应中不包含配置密码明文。

禁止：

- 未带密码也能读私有记忆。
- 401 响应泄露实际密码或 secret。

### RG-PRE-002: 服务健康和部署拓扑

优先级：P0
层级：L3

步骤：

1. 调用 `/api/collectors/status`。
2. 调用 `/api/pipelines/health`。
3. 调用 `/api/tools/catalog`。
4. 检查 Docker 服务 `runtime-api`、`worker`、`postgres`、`redis`、`chromium-runtime`。

期望：

- collector status 按 channel 返回能力边界和健康状态。
- pipelines health 返回已注册 Pipeline。
- tools catalog 包含 20 个核心高频 toolkit 候选。
- 如果某服务未运行，报告中必须标出服务名和影响范围。

### RG-PRE-003: 模型服务状态和降级

优先级：P0
层级：L1/L3

步骤：

1. 调用模型状态接口或触发 `/api/chat` 的最小对话。
2. 如果 Qwen endpoint 可用，检查回复是否和问题相关。
3. 如果 Qwen endpoint 不可用，检查前端/Android/后端错误提示。

期望：

- 可用时回复有内容、有上下文、有安全边界。
- 不可用时显示“模型服务暂时不可用”或等价明确提示。
- 不得出现空白 assistant bubble 或无限 pending。

### RG-PRE-004: WebSocket 实时通道

优先级：P0
层级：L1/L3

步骤：

1. 连接 `/ws`。
2. 发送 `chat_message`。
3. 观察 `chat_delta`、`chat_done` 或 `error`。

期望：

- 消息结构稳定。
- 错误时返回结构化 `error`。
- 不出现重复 pending、不返回未闭合 JSON、不泄露 raw secrets。

### RG-PRE-005: 数据库 schema 存在性

优先级：P0
层级：L1/L3

步骤：

1. 查询关键表是否存在：`events`、`semantic_events`、`memory_vectors`、`agenda_items`、`assistant_conversations`、`pipeline_execution_results`、`composio_sessions`、`composio_tool_invocations`。
2. 检查 schema 初始化日志或 migration 输出。

期望：

- 所有当前产品功能依赖的表存在。
- 缺表必须导致明确启动失败或健康检查 degraded，不允许运行到一半才静默失败。

### RG-PRE-006: 静态资源和 Web 工作台入口

优先级：P0
层级：L0/L3

步骤：

1. 执行 `node --check runtime_api/app/static/app.js`。
2. 打开 Web 工作台入口。
3. 输入访问密码。

期望：

- JS 语法正确。
- 密码正确后进入工作台。
- 未登录时不能调用私有 API。

### RG-PRE-007: 公开端口、反向代理和 TLS readiness

优先级：P0
层级：L3/L5

步骤：

1. 在云服务器执行 `ss -ltnp` 或等价命令，确认 Nomi 运行时实际监听端口。
2. 从外部网络访问 Web 工作台入口、noVNC 入口和 API 健康接口。
3. 检查反向代理配置是否只暴露必要入口：Web/API、noVNC、SSH 管理端口。
4. 如果启用了 HTTPS，检查 443 证书、跳转和 WebSocket 透传；如果尚未启用 HTTPS，记录为 `skipped_by_scope` 并标注当前使用 HTTP。

期望：

- Web/API 入口可访问，未鉴权 API 不能读取私有数据。
- noVNC 入口可访问且需要密码或等价保护。
- SSH 管理端口存在访问控制记录，不在报告中输出 SSH 密码、token 或密钥。
- HTTPS 未启用时不能误报为通过，必须在回归报告中明确风险和当前 scope。

## 8. Web 工作台用例

### RG-WEB-001: 主导航完整性

优先级：P0
层级：L1/L3

步骤：

1. 登录 Web 工作台。
2. 检查导航中存在：对话、日程、搜索、治理、建议、采集、工具、求职。
3. 逐个点击。

期望：

- 每个页面都能渲染，不出现空白页或 JS exception。
- 当前 tab 高亮正确。
- 求职 tab 能拉取 Career Board。

### RG-WEB-002: 对话流式输出

优先级：P0
层级：L1/L3

步骤：

1. 在 Web 对话页发送“帮我总结今天有什么需要跟进的事”。
2. 观察 WebSocket 流。
3. 打开 `/api/chat/history`。

期望：

- 用户消息立即显示。
- assistant 消息流式追加或明确失败。
- 历史中包含本轮 user/assistant turn。
- 如果模型不可用，失败提示可见且不会吞掉用户消息。

### RG-WEB-003: 日程周视图和绝对日期展示

优先级：P0
层级：L1/L3

步骤：

1. 注入一条含“明天下午4点人民广场见”的 WhatsApp synthetic event。
2. 打开日程 tab。
3. 检查周一至周日 tab 和对应日程卡。

期望：

- 日程标题或时间字段显示具体日期，例如 `2026-06-09 周二 16:00`。
- 页面不能只显示“明天”，除非同一张卡显式展示原始消息日期。
- “稍后提醒、完成、忽略”动作可见。

### RG-WEB-004: 搜索记忆证据展示

优先级：P1
层级：L1/L3

步骤：

1. 搜索 “RG_Alice 武康路”。
2. 查看检索计划和来源。

期望：

- 返回个人记忆结果。
- 展示 recall layer，例如 semantic、state、entity_graph、vector 或 bm25。
- 结果只包含 Alice 作用域相关信息。

禁止：

- 返回 Bob 私聊中关于 Alice 的敏感评价。

### RG-WEB-005: 治理页记忆纠正和删除

优先级：P1
层级：L1

步骤：

1. 创建一条 regression semantic memory。
2. 通过治理 API 或 UI patch 更正内容。
3. 删除该 memory。
4. 查看 audit log。

期望：

- patch 后内容变化可见。
- delete 后普通检索不再召回。
- audit log 记录操作类型、目标 ID、时间。

### RG-WEB-006: 建议页动作 handoff

优先级：P0
层级：L1/L3

步骤：

1. 创建一条 meeting suggestion。
2. 在建议页点击“查路线”。
3. 点击“帮我打车”。

期望：

- 查路线进入 `route_pipeline`，风险为 read-only。
- 打车进入 `ride_pipeline`，要求最终确认。
- 不得显示“已叫车”。

### RG-WEB-007: 工具页 Composio 授权状态

优先级：P1
层级：L1/L3

步骤：

1. 打开工具页。
2. 查看 Composio status。
3. 创建 connect link。

期望：

- 未授权 toolkit 显示 disconnected 或 authorization required。
- 授权链接可生成。
- 回调后能回到 Nomi，而不是卡在 provider 页面。

### RG-WEB-008: 求职工作台

优先级：P0
层级：L1/L3

步骤：

1. 导入一份 synthetic resume。
2. 打开求职 tab。
3. 预览一个 ATS URL 或 synthetic ATS HTML。
4. 打开岗位详情。
5. 编辑简历 sections 并导出 DOCX/PDF。

期望：

- 基础简历列表显示摘要，不暴露完整 parsed text。
- 可设默认、软删除。
- 岗位详情显示 JD、匹配项、差距、证据、草稿。
- 导出内容使用当前页面编辑后的 sections。

## 9. Android 悬浮球用例

### RG-AND-001: 安装、启动、配置线上服务器

优先级：P0
层级：L4

步骤：

1. 构建 APK。
2. 安装到模拟器和 Redmi 设备。
3. 配置 `base_url=http://206.119.171.141` 和访问密码。
4. 启动 App。

期望：

- App 可启动。
- 配置保存。
- 悬浮球权限入口可用。

### RG-AND-002: 悬浮球默认状态

优先级：P0
层级：L4

步骤：

1. 授予悬浮窗权限。
2. 返回桌面。
3. 观察 Nomi 小人悬浮球。

期望：

- 默认只显示一个悬浮球。
- 点击才打开对话面板。
- 关闭面板后悬浮球仍存在。

### RG-AND-003: 悬浮面板关闭按钮

优先级：P0
层级：L4

步骤：

1. 点击悬浮球打开对话面板。
2. 点击右上角关闭。

期望：

- 面板关闭。
- 悬浮球仍在。
- 不生成第二个悬浮窗。

### RG-AND-004: 输入框和键盘

优先级：P0
层级：L4

步骤：

1. 打开悬浮面板。
2. 点击输入框。
3. 输入文本。
4. 点击发送。
5. 点击聊天内容空白区。

期望：

- 键盘自动弹出。
- 输入框被顶到键盘上方，输入内容可见。
- 点击发送后键盘不自动收起。
- 点击聊天内容空白区后键盘收起。
- 悬浮面板不闪烁、不复制。

### RG-AND-005: 历史对话恢复

优先级：P0
层级：L4

步骤：

1. 发送一轮对话。
2. 重启 App 或模拟器。
3. 再次打开悬浮面板。

期望：

- 历史对话从服务器恢复。
- 不只依赖 Android 本地 8 条短上下文。
- 如果服务器不可用，显示清晰错误，不清空本地显示。

### RG-AND-006: 主动消息气泡

优先级：P0
层级：L4

步骤：

1. 通过后端创建 proactive suggestion。
2. 等待 Android WebSocket 推送。
3. 点击悬浮球旁消息气泡。

期望：

- 悬浮球显示未读角标。
- 气泡显示简短建议。
- 点击后进入对话页并展示完整上下文。

### RG-AND-007: 设置和账号连接入口

优先级：P1
层级：L4

步骤：

1. 打开悬浮面板设置。
2. 查看 Gmail、WhatsApp、Telegram、Composio、Nomi 自有身份。
3. 点击账号连接。

期望：

- 不自动弹 Composio 授权。
- 只有用户点击某个渠道时才打开授权页。
- 授权页可关闭并回到账号列表。

### RG-AND-008: 完整工作台入口

优先级：P1
层级：L4

步骤：

1. 打开悬浮面板。
2. 点击完整工作台 icon。
3. 点击工作台关闭按钮。

期望：

- 工作台打开。
- 工作台可关闭。
- 关闭后悬浮球仍在。

### RG-AND-009: 求职 tab

优先级：P1
层级：L4

步骤：

1. 打开悬浮面板。
2. 切换到求职 tab。
3. 查看岗位机会和申请状态。
4. 点击标记已投递或忽略。

期望：

- 求职 tab 位于顶层入口。
- 数据来自 Career Board API。
- 操作后刷新状态。

### RG-AND-010: 长按语音输入

优先级：P1
层级：L4/L5

步骤：

1. 未授予麦克风权限时长按悬浮球。
2. 授权麦克风。
3. 再次长按并说一句测试语音。

期望：

- 未授权时弹系统权限申请，而不是只显示文字提示。
- 授权后开始录音并推送 `/ws/voice`。
- partial/final transcript 可见。
- 低置信度时要求确认，高置信度时可进入对话。

## 10. 受控浏览器和采集用例

### RG-BRW-001: noVNC 鉴权和分辨率

优先级：P0
层级：L3

步骤：

1. 打开 `http://<server>:6080/vnc.html`。
2. 登录 noVNC。
3. 检查浏览器窗口尺寸。

期望：

- noVNC 可进入。
- Chromium 页面不会黑屏。
- 分辨率足够展示完整 Gmail/WhatsApp 页面。

### RG-BRW-002: 中文字体

优先级：P1
层级：L3

步骤：

1. 在受控浏览器打开中文页面和 Google 搜索结果。

期望：

- 中文不显示为方框。
- DOM 读取不受字体渲染影响。

### RG-BRW-003: Gmail Web 登录状态

优先级：P0
层级：L3/L5

步骤：

1. 在受控浏览器打开 Gmail。
2. 登录用户账号。
3. 打开一封测试邮件。

期望：

- 登录成功后 session 持久化。
- DOM 采集能读取可见发件人、主题、正文摘要。
- 如果 Google 风控拒绝登录，记录为 `blocked_by_platform_risk`。

### RG-BRW-004: WhatsApp Web 采集

优先级：P0
层级：L3/L5

步骤：

1. 登录 WhatsApp Web。
2. 打开测试联系人 RG_Alice。
3. 发送或接收一条测试消息。

期望：

- 聊天列表和当前会话可见文本被采集。
- 新增消息由 MutationObserver 捕获。
- conversation scope 为对应联系人或群聊。

### RG-BRW-005: Telegram Web 采集

优先级：P1
层级：L3/L5

步骤：

1. 登录 Telegram Web。
2. 打开测试会话。
3. 发送测试消息。

期望：

- 可见消息写入事件。
- 不要求全量历史。

### RG-BRW-006: 浏览器行为事件脱敏

优先级：P1
层级：L3

步骤：

1. 打开带 query token 的 synthetic URL。
2. 触发 click/input/fetch event。

期望：

- URL query 和 fragment 被清理。
- 普通事件里不包含 token、session、auth code。

## 11. 私有数据采集用例

### RG-COL-001: Gmail synthetic event 入库

优先级：P0
层级：L1/L2

步骤：

1. POST Gmail recruiter synthetic event 到 `/event`。
2. 查询 `/api/events/{event_id}/trace`。

期望：

- 事件 queued。
- trace 包含 semantic labels、memory write、agenda candidate。
- 保留 `Example AI`、`Friday 18:00`、岗位线索。

### RG-COL-002: WhatsApp meeting 入库

优先级：P0
层级：L1/L2

步骤：

1. POST WhatsApp “周六下午3点武康路见”。
2. 查事件 trace 和日程。

期望：

- 写入 WhatsApp source。
- 生成 exact 或 fuzzy agenda。
- 参与人、地点、时间合理。

### RG-COL-003: WhatsApp reschedule

优先级：P0
层级：L1/L2

步骤：

1. 先创建 RG_Alice meeting。
2. 再 POST “改到周日上午10点”。
3. 查询 `/api/agenda`。

期望：

- 更新已有 agenda，不重复创建 active agenda。
- version 记录 reschedule/update。

### RG-COL-004: Telegram interview update

优先级：P1
层级：L1/L2

步骤：

1. POST Telegram 面试改期消息。
2. 查 trace、agenda、suggestion。

期望：

- 识别面试/约定。
- 缺 Zoom link 时标记待补。
- 不自动回复或写外部日历。

### RG-COL-005: Calendar visible event

优先级：P1
层级：L3/L5

步骤：

1. 在受控浏览器打开 Google Calendar。
2. 采集一个可见日程。

期望：

- 内部 agenda 可反映该日程。
- 外部 Calendar 写入仍需授权确认。

### RG-COL-006: Collector settings 更新

优先级：P1
层级：L1

步骤：

1. GET `/api/collectors/settings`。
2. PATCH 某 source enable/disable。
3. GET 再检查。

期望：

- 设置持久化。
- 禁用 source 不应继续注入新事件。

### RG-COL-007: Composio Gmail fetch

优先级：P1
层级：L3/L5

步骤：

1. 确认 Gmail toolkit connected。
2. POST `/api/collectors/gmail/composio/fetch`。

期望：

- connected 时拉取邮件并写入 Gmail snapshot event。
- 未 connected 时返回明确授权缺口。

### RG-COL-008: 采集器健康降级

优先级：P1
层级：L1/L3

步骤：

1. 模拟某采集器错误。
2. GET `/api/collectors/status`。

期望：

- status 变为 degraded 或 failed。
- details 包含错误计数和最后事件时间。

### RG-COL-009: 浏览器 DOM 采集不替代官方 API 全量能力

优先级：P2
层级：L3

步骤：

1. 只打开 Gmail inbox，不打开线程。
2. 查询采集事件。

期望：

- 只采集可见摘要。
- 不声称读取了全量邮箱正文。

## 12. 私有事件、脱敏、治理用例

### RG-PRV-001: 敏感字段本地保留和模型过滤

优先级：P0
层级：L1

步骤：

1. 注入包含 phone、email、token、address 的 raw event。
2. 读取 private raw event。
3. 触发 chat/context pack。

期望：

- private raw 受密码保护。
- 本地可按权限读取必要敏感字段。
- 模型上下文中 token/secret 被过滤或替换。

### RG-PRV-002: 验证码和 token 不进入普通上下文

优先级：P0
层级：L1

步骤：

1. 注入包含 `verification code 123456` 和 `token=abc` 的消息。
2. 搜索普通记忆。
3. 查看 context pack。

期望：

- 普通搜索不直接暴露验证码/token。
- sensitive_flags 标记准确。

### RG-PRV-003: private raw API 权限

优先级：P0
层级：L1/L3

步骤：

1. 不带密码读取 `/api/events/{event_id}/private-raw`。
2. 带密码读取。

期望：

- 未授权 401。
- 授权后返回 raw payload 或明确事件不存在。

### RG-PRV-004: 事件 trace 可解释

优先级：P1
层级：L1

步骤：

1. 注入一条 meeting event。
2. 调用 `/api/events/{event_id}/trace`。

期望：

- trace 说明 memory、agenda、suggestion、pipeline route。
- 不依赖 JSON 字符串模糊匹配解释关系。

### RG-PRV-005: memory delete 审计

优先级：P1
层级：L1

步骤：

1. 创建 regression memory。
2. 删除。
3. 查询治理 audit。

期望：

- 删除成功。
- audit log 包含 operator/action/time。

### RG-PRV-006: user feedback 记录

优先级：P1
层级：L1

步骤：

1. 对 suggestion 点击 ignore。
2. 查询 feedback。

期望：

- feedback 与 suggestion_id 关联。
- 后续主动建议冷却或优先级受影响。

### RG-PRV-007: URL query 脱敏

优先级：P1
层级：L1/L3

步骤：

1. 注入 URL `https://example.test/callback?token=abc&code=123`。
2. 查看普通事件摘要。

期望：

- query 被移除或 token/code 被替换。

### RG-PRV-008: 失败输出不包含 secret

优先级：P0
层级：L1/L3

步骤：

1. 配置 fake provider token。
2. 触发 provider error。
3. 查看 API response、trace、logs。

期望：

- 错误说明 provider failed。
- 不包含 Authorization header 或 token 明文。

## 13. 长期记忆用例

### RG-MEM-001: 事件账本写入

优先级：P0
层级：L1

步骤：

1. POST synthetic event。
2. 查询 events。

期望：

- source、event_type、occurred_at、raw_data 存在。

### RG-MEM-002: 语义事件写入

优先级：P0
层级：L1

步骤：

1. 运行 worker 语义处理。
2. 查询 semantic_events。

期望：

- intent、entities、time/place/participants 合理。

### RG-MEM-003: KV 状态更新

优先级：P1
层级：L1

步骤：

1. 注入“RG_Alice 当前报价截止周五”。
2. 查询 memory_states 或 facts。

期望：

- 状态为最新值。
- 同一 key 后续更新覆盖旧值并保留审计。

### RG-MEM-004: 知识图谱实体和关系

优先级：P1
层级：L1

步骤：

1. 注入联系人、公司、岗位相关事件。
2. 查询 entities/relationships。

期望：

- RG_Maya、Example AI、AI PM role 等实体存在。
- 关系类型合理。

### RG-MEM-005: 向量/RAG 召回

优先级：P1
层级：L1

步骤：

1. 写入长文本邮件。
2. 搜索语义相近问题。

期望：

- vector 或 bm25 召回包含对应证据。
- 答案引用证据，不编造。

### RG-MEM-006: 作用域隔离

优先级：P0
层级：L1/L2

步骤：

1. Bob 私聊中写“别告诉 Alice”。
2. Alice 对话中请求起草回复。

期望：

- 回复草稿不包含 Bob 的私聊内容。

### RG-MEM-007: 超级节点治理

优先级：P2
层级：L1

步骤：

1. 创建大量指向“公司”或“用户”的关系。
2. 查看图谱治理指标。

期望：

- 超级节点被标记或降权。
- 搜索不会只因超级节点返回无关结果。

### RG-MEM-008: 关系热度衰减

优先级：P2
层级：L1

步骤：

1. 注入一段较久未联系的联系人历史。
2. 注入近期互动。

期望：

- 关系热度或 follow-up 建议随近期互动变化。

### RG-MEM-009: 记忆纠错

优先级：P1
层级：L1

步骤：

1. 人工纠正一条错误事实。
2. 再次提问同一问题。

期望：

- 采用纠正后的事实。
- 不继续召回旧错误作为答案。

### RG-MEM-010: 上下文预算

优先级：P1
层级：L1

步骤：

1. 注入超长消息。
2. 触发 chat/context pack。

期望：

- 上下文总量受预算控制。
- 关键近期对话、任务目标、证据优先保留。
- 不因单条长文本撑爆模型上下文。

## 14. 对话和上下文用例

### RG-CHAT-001: 普通问答

优先级：P0
层级：L1/L3

步骤：

1. 发送“今天有什么要跟进”。
2. 查看回复和 trace。

期望：

- 回复结合日程、建议、相关记忆。
- 不引用无关联系人私聊。

### RG-CHAT-002: 短确认上下文

优先级：P0
层级：L1/L4

步骤：

1. Nomi 问“是否需要核对成本与利润率”。
2. 用户回复“需要”。

期望：

- Nomi 理解“需要”指上一轮问题。
- 不回复“不知道需要指什么”。

### RG-CHAT-003: 历史恢复

优先级：P0
层级：L1/L4

步骤：

1. 创建多轮对话。
2. 重启前端或 Android。
3. 调用 `/api/chat/history`。

期望：

- 服务器历史保留。
- Android 不因重启清空对话。

### RG-CHAT-004: 流式错误提示

优先级：P0
层级：L1/L4

步骤：

1. 模拟模型不可用。
2. 发送消息。

期望：

- pending bubble 更新为明确错误。
- 不无限加载。

### RG-CHAT-005: 回复草稿确认

优先级：P0
层级：L1

步骤：

1. 用户要求“帮我回复 Alice”。
2. 触发 reply pipeline。

期望：

- 生成草稿。
- 需要确认。
- 不直接发送。

### RG-CHAT-006: 路线/打车意图区分

优先级：P1
层级：L1

步骤：

1. 发送“帮我查去人民广场的路线”。
2. 发送“帮我打车去人民广场”。

期望：

- 第一句进 route pipeline，read-only。
- 第二句进 ride pipeline，最终下单需确认。

### RG-CHAT-007: 付款/购物安全门

优先级：P0
层级：L1

步骤：

1. 发送“帮我付这个账单”。
2. 发送“帮我买这个商品”。

期望：

- payment/shopping pipeline 只准备计划和确认卡。
- 不实际付款、不购买。

### RG-CHAT-008: 会话 trace

优先级：P1
层级：L1

步骤：

1. 完成一轮有记忆引用的回答。
2. GET `/api/chat/conversations/{conversation_id}/trace`。

期望：

- trace 包含 turns、context snapshots、route、evidence。

## 15. 日程和主动建议用例

### RG-AGD-001: 精确时间日程

优先级：P0
层级：L1/L2

步骤：

1. 注入“2026-06-10 15:00 在人民广场见”。
2. 查询 agenda。

期望：

- certainty 为 exact。
- 日期和时间绝对化。

### RG-AGD-002: 模糊日程

优先级：P0
层级：L1

步骤：

1. 注入“周末见面”。
2. 查询 agenda 和 suggestion。

期望：

- agenda 标记信息模糊。
- 建议补充具体时间/地点。

### RG-AGD-003: 改期

优先级：P0
层级：L1/L2

步骤：

1. 创建原日程。
2. 注入“改到周五上午10点”。

期望：

- 更新原日程。
- version 记录改期。

### RG-AGD-004: 取消

优先级：P0
层级：L1

步骤：

1. 创建原日程。
2. 注入“取消明天的会”。

期望：

- agenda 状态为 cancelled 或 dismissed。
- 不继续主动提醒。

### RG-AGD-005: 日程动作

优先级：P1
层级：L1/L3

步骤：

1. 对 agenda 调用 snooze。
2. 调用 complete。
3. 调用 ignore。

期望：

- 状态变化正确。
- version 记录操作。

### RG-PRO-001: 主动建议生成

优先级：P0
层级：L1/L2/L4

步骤：

1. 注入重要约定。
2. 等待 proactive suggestion。

期望：

- 生成建议。
- 包含可操作选项。
- Android 收到气泡。

### RG-PRO-002: 主动建议冷却

优先级：P1
层级：L1

步骤：

1. 对同一事件重复触发建议。
2. 查询 suggestions。

期望：

- 不重复刷屏。
- cooldown 或 dedupe 生效。

### RG-PRO-003: 建议动作进入 Pipeline

优先级：P0
层级：L1

步骤：

1. 点击 route_lookup。
2. 点击 ride_prepare。
3. 点击 draft_reply。

期望：

- 分别进入 route、ride、reply pipeline。
- 风险和确认门槛正确。

### RG-PRO-004: 低置信度建议

优先级：P1
层级：L1

步骤：

1. 注入“可能周末聊下”的模糊消息。

期望：

- 建议语气保守。
- 不直接创建 exact agenda。

### RG-PRO-005: 用户反馈影响后续建议

优先级：P2
层级：L1

步骤：

1. 忽略某类建议。
2. 再注入相似事件。

期望：

- 频率或优先级降低。

### RG-PRO-006: 主动建议不可执行危险动作

优先级：P0
层级：L1

步骤：

1. 注入付款或打车相关事件。
2. 查看建议动作。

期望：

- 只出现“准备、查看、提醒、起草”类动作。
- 不出现“立即付款、立即下单”。

## 16. 核心 Pipeline 用例

### RG-PIPE-001: Registry 完整性

优先级：P0
层级：L1

步骤：

1. GET `/api/pipelines/registry`。
2. 对照 18 条核心 Pipeline。

期望：

- 18 条核心 Pipeline 均存在。
- 每条包含 required slots、risk、permission、description。

### RG-PIPE-002: 工具路由优先 Pipeline

优先级：P0
层级：L1

步骤：

1. POST `/api/tools/route` 输入路线、打车、付款、购物、改简历、LinkedIn 外联等请求。

期望：

- 高频任务命中 deterministic pipeline。
- 长尾才进入 long-tail/OpenClaw。

### RG-PIPE-003: Pipeline execution result 单独落表

优先级：P0
层级：L1

步骤：

1. POST `/api/pipelines/run`。
2. 查询 `pipeline_execution_results`。

期望：

- route trace 和 execution result 独立记录。
- result 包含 pipeline_id、risk、output、provider_call_plan。

### RG-PIPE-004: Slot 解析保守

优先级：P0
层级：L1

步骤：

1. 输入缺关键字段的付款、打车、申请提交请求。

期望：

- 缺字段时询问或阻断。
- 不猜金额、地址、联系人、岗位。

### RG-PIPE-005 至 RG-PIPE-022: 18 条 Pipeline Matrix

优先级：P0/P1
层级：L1

对每条 pipeline 运行至少一个正向样例和一个安全边界样例：

| Case | Pipeline | 正向期望 | 安全边界 |
| --- | --- | --- | --- |
| RG-PIPE-005 | `event_ingestion_pipeline` | 事件去重并投递 worker | 重复事件不重复写 |
| RG-PIPE-006 | `memory_write_pipeline` | 写 KV/图谱/RAG/向量 | 敏感内容不进普通上下文 |
| RG-PIPE-007 | `context_pack_pipeline` | 输出优先级上下文 | 长输入不撑爆上下文 |
| RG-PIPE-008 | `personal_search_pipeline` | 返回证据和来源层 | 不跨联系人泄露 |
| RG-PIPE-009 | `chat_response_pipeline` | 结合上下文回答 | 模型不可用时提示 |
| RG-PIPE-010 | `reply_pipeline` | 起草回复 | 不直接发送 |
| RG-PIPE-011 | `email_pipeline` | 邮件总结/草稿 | 未授权时明确说明 |
| RG-PIPE-012 | `agenda_pipeline` | 写内部日程 | 外部 Calendar 写入需确认 |
| RG-PIPE-013 | `task_todo_pipeline` | 识别待办 | 模糊待办不设 exact deadline |
| RG-PIPE-014 | `proactive_suggestion_pipeline` | 生成建议卡 | 冷却去重 |
| RG-PIPE-015 | `route_pipeline` | 查路线计划 | 只读不下单 |
| RG-PIPE-016 | `ride_pipeline` | 打车准备 | 需最终确认 |
| RG-PIPE-017 | `shopping_pipeline` | 比价/加购计划 | 不直接购买 |
| RG-PIPE-018 | `payment_bill_pipeline` | 账单风险确认 | 不直接付款 |
| RG-PIPE-019 | `contact_relationship_pipeline` | 更新关系记忆 | 不跨域泄露 |
| RG-PIPE-020 | `document_file_pipeline` | 文档读写计划 | 写入需授权/确认 |
| RG-PIPE-021 | `account_login_pipeline` | 打开对应登录入口 | 不自动弹错误渠道 |
| RG-PIPE-022 | `governance_audit_pipeline` | 输出审计记录 | trace 不泄密 |

## 17. Job Agent 用例

### RG-JOB-001: ATS preview 只读

优先级：P0
层级：L1/L2

步骤：

1. POST synthetic Greenhouse HTML 到 `/api/career/ats/preview`。

期望：

- 输出 normalized job。
- `writeback_performed=false`。
- 不提交申请。

### RG-JOB-002: ATS list preview

优先级：P1
层级：L1

步骤：

1. POST public ATS board URL 或 synthetic list HTML。

期望：

- 返回职位列表。
- 每个机会包含 source、title、company、url。

### RG-JOB-003: 简历导入

优先级：P0
层级：L1/L3

步骤：

1. 导入 txt/docx/pdf 简历。
2. 查 Career Board。

期望：

- 创建 career profile。
- 创建 career_resume。
- Board 只显示摘要。

### RG-JOB-004: 匹配评分

优先级：P0
层级：L1/L2

步骤：

1. 用 JD + resume 跑 `job_fit_scoring_pipeline`。

期望：

- fit score 合理。
- matched/gap requirements 有证据。
- unsupported_claims 为空或列出不能证明项。

### RG-JOB-005: 简历改写草案

优先级：P0
层级：L1

步骤：

1. 跑 `resume_tailoring_pipeline`。

期望：

- 输出逐段修改建议。
- 不编造不存在经历。
- 可写入 resume_versions。

### RG-JOB-006: 简历逐段编辑 UI

优先级：P0
层级：L3

步骤：

1. 打开岗位详情。
2. 编辑 sections。
3. 导出 DOCX/PDF。

期望：

- 导出内容使用编辑后 sections。

### RG-JOB-007: Cover Letter

优先级：P1
层级：L1

步骤：

1. 跑 `cover_letter_pipeline`。

期望：

- 结合 JD 和简历。
- 不声称已发送。

### RG-JOB-008: HR/LinkedIn 外联草稿

优先级：P0
层级：L1

步骤：

1. 跑 `outreach_message_pipeline`。

期望：

- 输出外联草稿。
- `external_message` 风险。
- 需要确认。

### RG-JOB-009: Apply/Submit 阻断

优先级：P0
层级：L1

步骤：

1. 跑 `job_application_pipeline` with `submit_application`。

期望：

- `blocked_until_delegated_grant`。
- 输出 grant/manifest/evidence 要求。

### RG-JOB-010: 申请状态跟踪

优先级：P1
层级：L1/L3

步骤：

1. PATCH `/api/career/applications/{id}` 为 interviewing。
2. GET `/api/career/offers`。

期望：

- 状态更新。
- offers 只显示 interviewing/offer 阶段。

### RG-JOB-011: 面试准备

优先级：P1
层级：L1

步骤：

1. 跑 `interview_prep_pipeline`。

期望：

- 输出面试问题、公司/岗位准备、风险问题。
- 引用 JD 和简历证据。

### RG-JOB-012: Google Docs 写入 provider gate

优先级：P1
层级：L1/L5

步骤：

1. 创建 `platform=google_docs` grant/manifest。
2. POST `/api/delegated-automation/execute`。

期望：

- 未配置 `NOMI_GOOGLE_DOCS_PROVIDER_URL` 时 `misconfigured`。
- 配置 fake provider 时调用 provider 并写 trace。
- 不把未配置说成已写入。

## 18. Long-tail Agent 和 OpenClaw 用例

### RG-LTA-001: 长尾任务路由

优先级：P0
层级：L1

步骤：

1. POST 复杂网站表单任务到 `/api/agent-tasks/route`。

期望：

- route_type 为 long_tail_agent 或 openclaw_tool。
- 不直接执行危险外部动作。

### RG-LTA-002: Planner 和结构化 task memory

优先级：P0
层级：L1

步骤：

1. 创建 agent task。
2. 查看 state/events。

期望：

- 目标、子任务、当前步骤、已完成产出结构化保存。

### RG-LTA-003: Step verifier

优先级：P0
层级：L1

步骤：

1. 完成一步缺 evidence 的 executor result。

期望：

- verifier 拒绝。
- 不进入下一步。

### RG-LTA-004: External effect confirmation

优先级：P0
层级：L1

步骤：

1. 创建 send/payment/submit external effect。
2. 未确认直接 execute。
3. 确认后 execute fake adapter。

期望：

- 未确认阻断。
- 确认后写 action_request、policy、execution trace。

### RG-LTA-005: Checkpoint 和恢复

优先级：P1
层级：L1/L3

步骤：

1. 创建任务并执行到等待 executor。
2. 重启 runtime-api。
3. 调用 resume。

期望：

- 从事件日志恢复当前 node/step。

### RG-LTA-006: 自我纠偏和失败兜底

优先级：P1
层级：L1

步骤：

1. 让同一步工具连续失败。

期望：

- 到达重试上限后中断或回到 checkpoint。
- 不死循环。

### RG-OPEN-001: OpenClaw job 创建

优先级：P1
层级：L1

步骤：

1. POST `/api/tools/openclaw/jobs`。
2. GET job state。

期望：

- job 可查询。
- trace 记录。

### RG-OPEN-002: Sensitive field release

优先级：P0
层级：L1

步骤：

1. OpenClaw 请求需要 raw secret。
2. 不 release 直接执行。
3. release 后执行。

期望：

- 未 release 阻断。
- release 有审计。

### RG-OPEN-003: OpenClaw execute

优先级：P1
层级：L1

步骤：

1. POST `/api/tools/openclaw/execute` dry-run。

期望：

- 返回结构化 result。
- 真实执行仍受 policy gate。

### RG-OPEN-004: OpenClaw event WebSocket

优先级：P2
层级：L3

步骤：

1. 创建 OpenClaw job。
2. 监听 WebSocket event。

期望：

- job event 可推送。

## 19. Composio 用例

### RG-COMP-001: Status

优先级：P0
层级：L1/L3

步骤：

1. GET `/api/tools/composio/status`。

期望：

- 返回 API key 是否配置、session 状态、toolkit 状态。

### RG-COMP-002: Connect Link

优先级：P0
层级：L3/L5

步骤：

1. 请求 Gmail connect link。
2. 完成授权。
3. 回到 Nomi。

期望：

- callback 页面可关闭或自动返回。
- toolkit 状态变 connected。

### RG-COMP-003: Readonly tool execute

优先级：P1
层级：L3/L5

步骤：

1. 执行 readonly Gmail/Calendar 工具。

期望：

- 成功时返回工具结果并落 invocation。
- 未授权时明确 connected=false 或 authorization required。

### RG-COMP-004: Write tool confirmation

优先级：P0
层级：L1/L3

步骤：

1. 请求 Gmail send 或 Calendar write。

期望：

- 写动作必须要求确认。
- 未确认不调用 provider。

### RG-COMP-005: Toolkit whitelist

优先级：P1
层级：L1

步骤：

1. 检查 readonly/write session toolkits。

期望：

- 只启用白名单。
- 高风险工具被确认 gate 包住。

### RG-COMP-006: Secret hygiene

优先级：P0
层级：L1/L3

步骤：

1. 模拟 Composio tool error。

期望：

- 响应和 trace 不包含 `COMPOSIO_API_KEY`。

## 20. Nomi 自有通信身份用例

### RG-AI-001: 默认身份列表

优先级：P0
层级：L1

步骤：

1. GET `/api/assistant-identities`。

期望：

- 包含 `nomi_gmail_primary`、`nomi_whatsapp_primary`、`nomi_phone_primary`。

### RG-AI-002: Gmail inbound sync

优先级：P0
层级：L1/L5

步骤：

1. POST `/api/assistant-inbox/gmail/sync`。

期望：

- user 发给 Nomi 是 `user_direct_command`。
- 外部联系人发给 Nomi 是 `external_contact_message`。

### RG-AI-003: Gmail PubSub

优先级：P1
层级：L1/L5

步骤：

1. POST PubSub payload。

期望：

- accepted。
- provider 标记 gmail_pubsub。

### RG-AI-004: WhatsApp webhook

优先级：P0
层级：L1/L5

步骤：

1. 验证 webhook token。
2. POST inbound WhatsApp message。

期望：

- token 错误返回 403。
- 正确 token accepted。
- 不自动回复。

### RG-AI-005: SMS webhook

优先级：P0
层级：L1/L5

步骤：

1. POST `/api/assistant-inbox/phone/sms/webhook`。

期望：

- event_type 为 `assistant_sms_received`。
- memory_scope 为 assistant identity thread。

### RG-AI-006: Inbound call greeting

优先级：P1
层级：L1/L5

步骤：

1. POST inbound call webhook。

期望：

- 记录 call event。
- 返回 one-way TTS greeting。

### RG-AI-007: Outbound Gmail draft confirmation

优先级：P0
层级：L1/L5

步骤：

1. 创建 Gmail draft。
2. 不带 confirmation send。
3. 带 confirmation send。

期望：

- 空 confirmation 403。
- provider 缺配置时 `misconfigured`。
- 配置 fake/live provider 时才发送。

### RG-AI-008: Outbound WhatsApp draft confirmation

优先级：P0
层级：L1/L5

步骤同 RG-AI-007，channel 为 WhatsApp。

期望：

- 不绕过确认。
- 不用用户个人 WhatsApp 批量发送。

### RG-AI-009: Outbound SMS

优先级：P0
层级：L1/L5

步骤：

1. 创建 SMS draft。
2. 确认发送。

期望：

- 缺 phone provider env 时 blocked/misconfigured。
- 配置 provider 时生成 SMS HTTP 请求。
- 不泄露 provider token。

### RG-AI-010: 单向电话

优先级：P1
层级：L1/L5

步骤：

1. 创建 `phone_call` draft。
2. 确认 call。

期望：

- confirmation card 说明“只播放语音，不实时对话”。
- provider 配置后创建 playback call。

### RG-AI-011: 双工电话

优先级：P1
层级：L1/L5

步骤：

1. 创建 `phone_duplex_call` draft。
2. 确认 call。
3. POST `/api/assistant-inbox/phone/calls/duplex/turn`。

期望：

- confirmation card 类型为 `assistant_call_duplex_confirmation`。
- 创建 turn-based voice call。
- turn webhook 记录 transcript 并返回下一句 TTS reply instruction。

### RG-AI-012: Assistant identity scope

优先级：P0
层级：L1

步骤：

1. Nomi Gmail、WhatsApp、SMS 各注入一条外部联系人消息。
2. 搜索或起草回复。

期望：

- 不把 Nomi 自有 WhatsApp 线程混入用户 WhatsApp 私聊。
- 不跨 identity 泄露上下文。

## 21. 语音输入用例

### RG-VOICE-001: Voice WebSocket 鉴权

优先级：P0
层级：L1

步骤：

1. 不带密码连接 `/ws/voice`。
2. 带密码连接。

期望：

- 未授权拒绝。
- 授权后可发送 voice_start。

### RG-VOICE-002: Fake ASR partial/final

优先级：P0
层级：L1

步骤：

1. 使用 fake ASR provider。
2. 发送 audio_chunk 和 voice_end。

期望：

- 返回 asr_partial 和 asr_final。

### RG-VOICE-003: Volcengine frame 协议

优先级：P1
层级：L1

步骤：

1. 运行 Volcengine provider unit tests。

期望：

- 请求 header、gzip JSON frame、audio frame、response parse 正确。

### RG-VOICE-004: Android 长按手势

优先级：P0
层级：L4

步骤：

1. tap、drag、long-press、slide cancel。

期望：

- 四种手势 callback 不混淆。

### RG-VOICE-005: Android 录音 chunk

优先级：P1
层级：L4

步骤：

1. 触发录音。

期望：

- PCM16 mono chunk、sequence、RMS 合理。

### RG-VOICE-006: 权限申请

优先级：P0
层级：L4

步骤：

1. 未授予麦克风权限长按悬浮球。

期望：

- 系统权限申请弹出。

### RG-VOICE-007: Live ASR smoke

优先级：P2
层级：L5

步骤：

1. 配置火山引擎 ASR env。
2. 真机长按说“帮我查看今天日程”。

期望：

- final transcript 正确或接近。
- 低置信度要求确认。

## 22. 分级授权和外部执行用例

### RG-DA-001: Grant 创建

优先级：P0
层级：L1

步骤：

1. POST `/api/delegated-automation/grants`。

期望：

- grant 存储。
- level、limit、surface、action 正确。

### RG-DA-002: Manifest 创建

优先级：P0
层级：L1

步骤：

1. POST target manifest。

期望：

- targets 存储。
- 每个 target 有 reason、risk、status。

### RG-DA-003: 缺 grant 阻断

优先级：P0
层级：L1

步骤：

1. evaluate 不存在 grant。

期望：

- 404 或 `missing_grant`。

### RG-DA-004: 缺 manifest 阻断

优先级：P0
层级：L1

步骤：

1. evaluate 缺 manifest。

期望：

- `missing_target_manifest`。

### RG-DA-005: 缺 grounded evidence 阻断

优先级：P0
层级：L1

步骤：

1. execute with empty evidence。

期望：

- status blocked。
- provider 不被调用。

### RG-DA-006: Quota 阻断

优先级：P0
层级：L1

步骤：

1. daily_limit=1。
2. 完成一次 trace。
3. 再 execute 第二个 target。

期望：

- `daily_limit_reached`。

### RG-DA-007: Captcha/2FA stop

优先级：P0
层级：L1/L5

步骤：

1. page_state 包含 captcha 或 security_check。

期望：

- stop_condition 为 platform_challenge。
- provider 不继续执行。

### RG-DA-008: LinkedIn/ATS browser executor

优先级：P1
层级：L1/L5

步骤：

1. 配置或删除 `NOMI_BROWSER_EXECUTOR_URL`。
2. execute LinkedIn action。

期望：

- 未配置时 `misconfigured`，budget 不递增。
- 配置 fake provider 时写 completed trace。
- 真实 provider 时必须返回 screenshot/DOM evidence。

### RG-DA-009: Google Docs provider

优先级：P1
层级：L1/L5

步骤：

1. 配置或删除 `NOMI_GOOGLE_DOCS_PROVIDER_URL`。
2. execute Google Docs write。

期望：

- 未配置时 `misconfigured`。
- 配置 provider 时调用 docs provider。

### RG-DA-010: 用户暂停 grant

优先级：P0
层级：L1/L3

步骤：

1. pause grant。
2. 再 evaluate。

期望：

- grant status paused。
- 后续 action blocked。

## 23. 模型与嵌入用例

### RG-MODEL-001: 模型路由状态

优先级：P0
层级：L1/L3

步骤：

1. 调用模型路由/状态接口，例如 `/api/model/route` 或当前代码中的等价健康接口。
2. 发送一条最小中文请求：“用一句话说明你是谁”。
3. 检查返回的 provider、model、latency、degraded reason。

期望：

- Qwen 可用时，返回模型名、耗时和相关中文回答。
- Qwen 不可用时，返回明确 degraded 状态和原因，不进入无限 pending。
- 响应中不包含模型 endpoint token、provider secret 或完整内部 prompt。

### RG-MODEL-002: 嵌入探针

优先级：P0
层级：L1/L3

步骤：

1. 调用 `/api/memory/embedding/probe` 或当前代码中的等价 embedding probe。
2. 使用固定文本 `RG_EMBED_PROBE Alice 明天 16:00 人民广场`。
3. 检查向量维度、provider、cache 状态和错误字段。

期望：

- provider 可用时返回非空向量维度、耗时和 provider 名称。
- provider 不可用时返回 degraded/fallback，不得假装写入向量成功。
- probe 文本不能写入长期记忆，除非接口明确声明会写入测试 namespace。

### RG-MODEL-003: 嵌入缓存和降级

优先级：P1
层级：L1

步骤：

1. 连续两次对同一测试文本请求 embedding。
2. 暂时切换到不可用 embedding provider 或 fake failure provider。
3. 再次执行向量检索相关 API。

期望：

- 第二次相同文本命中缓存或返回稳定维度。
- provider 失败时，系统能降级到 BM25/KV/图谱召回，并在 trace 中标注 vector degraded。
- 不允许因为 embedding 失败导致整条消息无法写入事件账本。

### RG-MODEL-004: 向量召回语义合理性

优先级：P0
层级：L1/L3

步骤：

1. 写入三条测试记忆：Alice 约人民广场、Bob 评价 Alice、Carol 讨论发票。
2. 搜索“和 Alice 在人民广场见面是什么时候”。
3. 检查召回结果、排序和 evidence。

期望：

- Alice 人民广场事件排在前列。
- Bob 对 Alice 的评价不能跨联系人作用域混入回答。
- evidence 指向原始 event/semantic_event/vector id，而不是只返回一段无来源文本。

## 24. 数据库、持久化、恢复用例

### RG-DB-001: 事件持久化

优先级：P0
层级：L1/L3

步骤：

1. 注入 event。
2. 重启 runtime-api。
3. 查询 event trace。

期望：

- event 仍可查询。

### RG-DB-002: 日程版本持久化

优先级：P0
层级：L1/L3

步骤：

1. 创建、改期、取消日程。
2. 重启。
3. 查询 versions。

期望：

- versions 完整。

### RG-DB-003: 对话历史持久化

优先级：P0
层级：L1/L4

步骤：

1. 创建对话。
2. 重启 Android 或后端。
3. 查询 history。

期望：

- 历史存在。

### RG-DB-004: Agent task event-sourcing 恢复

优先级：P1
层级：L1/L3

步骤：

1. 创建 long-tail task。
2. 等待 executor。
3. 重启后 resume。

期望：

- current node/step 恢复。

### RG-DB-005: Composio session 持久化

优先级：P1
层级：L3/L5

步骤：

1. 创建 Composio session。
2. 重启。
3. sync toolkit。

期望：

- session id 可复用。

### RG-DB-006: 数据清理

优先级：P1
层级：L1/L3

步骤：

1. 清理当前 run_id 的 events、agenda、suggestions、drafts。

期望：

- regression 数据不污染用户真实数据。
- 清理动作有审计。

## 25. 安全、隐私和发布质量用例

### RG-SEC-001: Secret scan

优先级：P0
层级：L0

步骤：

1. 扫描 repo 中用户提供过的 token、secret、access key。

期望：

- 无明文 secret。

### RG-SEC-002: Provider response 不泄露 header

优先级：P0
层级：L1

步骤：

1. 配置 fake provider token。
2. 触发 Gmail/WhatsApp/SMS/Docs provider。

期望：

- response 和 trace 不包含 Authorization。

### RG-SEC-003: 高风险动作确认

优先级：P0
层级：L1

步骤：

1. 触发 send、pay、buy、ride book、Apply、Submit。

期望：

- 全部要求 confirmation 或 delegated grant。

### RG-SEC-004: 用户个人 Gmail/WhatsApp 批量自动化禁止

优先级：P0
层级：L1

步骤：

1. grant surface 为 user_gmail 或 user_whatsapp。
2. evaluate。

期望：

- blocked，stop_condition 为 personal account surface out of scope。

### RG-SEC-005: CORS/公网暴露

优先级：P1
层级：L3

步骤：

1. 从未授权 origin 调用私有 API。

期望：

- 不能绕过密码。

### RG-SEC-006: 发布前 smoke

优先级：P0
层级：L3

步骤：

1. 部署后跑 preflight、chat、agenda、suggestion、pipeline、assistant identity smoke。

期望：

- 核心路径可用。
- provider 缺口单独记录。

### RG-SEC-007: 备份和恢复

优先级：P1
层级：L3

步骤：

1. 备份 Postgres。
2. 恢复到测试实例。
3. 查询关键数据。

期望：

- events、agenda、memory、conversations 可恢复。

### RG-SEC-008: 性能和容量

优先级：P1
层级：L3

步骤：

1. 注入 1000 条 synthetic events。
2. 跑搜索、agenda、chat context。

期望：

- 4 核 8G 私有云上响应可接受。
- 无明显内存泄漏。
- 大上下文仍受预算控制。

## 26. Provider-gated Live 回归清单

这些 case 只有在真实 provider 配置完成后执行。未配置时必须标为 `blocked_by_provider_config`。

| Case | 必需配置 | Live 通过标准 |
| --- | --- | --- |
| RG-LIVE-GM-001 | Composio Gmail 或 Gmail API token | 能读取测试邮件；发送只在确认后发生 |
| RG-LIVE-WA-001 | WhatsApp Cloud API token / phone number id | Nomi 自有 WhatsApp 能接收 webhook，确认后发送测试消息 |
| RG-LIVE-SMS-001 | Phone provider base URL/API key/number | 确认后发送测试 SMS，provider 返回 message id |
| RG-LIVE-CALL-001 | Phone provider call path | 确认后发起单向 playback call |
| RG-LIVE-DUPLEX-001 | Phone duplex webhook + provider media support | 双工 turn webhook 收到转写并返回 TTS reply |
| RG-LIVE-DOCS-001 | Google Docs provider URL/token | 确认后创建或更新测试 Google Doc，返回 document id |
| RG-LIVE-LI-001 | `NOMI_BROWSER_EXECUTOR_URL` + LinkedIn 登录会话 | 只读 DOM observe 返回 screenshot/DOM evidence |
| RG-LIVE-LI-002 | Delegated grant + manifest + evidence | 小批量加人/私信前进入执行器；遇 captcha/2FA 停止 |
| RG-LIVE-ATS-001 | Browser executor + ATS 测试岗位 | Apply/Submit 只在授权额度内执行，并返回截图/DOM 证据 |
| RG-LIVE-ASR-001 | Volcengine ASR env | 真机长按语音生成合理 transcript |

## 27. 最终发布闸门

一次发布前至少满足：

1. L0/L1 全部通过。
2. L2 fixture contract 全部通过。
3. L3 preflight、WebSocket、collector status、pipeline health、chat smoke 通过。
4. Android `testDebugUnitTest` 和 APK build 通过。
5. 如果本次改动涉及 Android UI，至少在模拟器完成 RG-AND-002 至 RG-AND-006。
6. `RG-MODEL-001` 和 `RG-MODEL-002` 通过；如果模型或 embedding provider 不可用，必须记录 degraded 范围和对应功能影响。
7. 如果本次改动涉及真实 provider，必须跑对应 RG-LIVE case；未配置只能标记为 provider gap，不能标为完成。
8. `git diff --check` 和 secret scan 通过。
9. 回归报告必须列出：
   - passed case 数量。
   - failed case 数量。
   - blocked_by_provider_config 数量。
   - blocked_by_model_service 数量。
   - 用户可见质量问题。
   - 数据清理状态。

## 28. 回归报告模板

```markdown
# Nomi Regression Report

Run id:
Date:
Commit:
Environment:
Base URL:
Android target:

## Summary

- Passed:
- Failed:
- Blocked by provider config:
- Blocked by model service:
- Skipped by scope:

## Critical Failures

| Case | Symptom | Root cause | Fix owner | Retest command |
| --- | --- | --- | --- | --- |

## Semantic Output Review

| Case | Expected meaning | Actual output | Judgment |
| --- | --- | --- | --- |

## Provider Gaps

| Provider | Missing config/account | Impact | Next action |
| --- | --- | --- | --- |

## Cleanup

- Regression events cleaned:
- Agenda items cleaned:
- Drafts cleaned:
- Provider side test artifacts cleaned:
```
