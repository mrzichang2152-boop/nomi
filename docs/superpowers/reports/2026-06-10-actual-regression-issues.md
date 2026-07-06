# Nomi 当前实际问题清单

日期：2026-06-10

来源：

- `docs/superpowers/reports/2026-06-10-cloud-redeploy-regression-run.md`
- `docs/superpowers/plans/2026-06-10-cloud-redeploy-regression-test-plan.md`

说明：本文只记录本轮已经通过实际测试暴露的问题，以及尚未完成真实验收的风险项。通过项不放在这里，避免后续修复时混淆优先级。

## 1. P0 问题

## 2026-06-12 线上真实链路复测更新

本次复测环境：

- 云服务器：`206.119.171.141`
- Runtime API / Web 工作台：`http://206.119.171.141`
- Android 真机：Redmi `24094RAD4C`，设备 id `DQYTCYFMO7VSEAJB`
- 回归 run id：`rg-cloud-20260612-fix6`

本次实际修复：

- 修复 runtime-api 入队脱敏把 `2026-06-15 18:00`、`2026-06-13 10:30，` 误脱敏成 `PHONE_1:00` / `PHONE_1:30` 的问题。
- 修复 worker 同类日期时间保护问题，补充中文标点边界测试。
- 修复 WhatsApp/Telegram 可见摘要、日程标题、主动建议正文暴露 raw JSON 的问题，改为优先使用用户可读的 `text/message/body`。
- 修复 `fix5：` 这类测试/业务编号被误识别为 5 点的问题。
- 修复“地点还是武康路咖啡店”这类口语改期消息无法抽取地点的问题。
- 修复 `/api/chat` 重复 `client_request_id` 仍重复调用模型的问题；现在重复请求会直接返回 cached assistant answer，且返回 `duplicate=true`。

已验证通过：

- Gmail 注入：`before 2026-06-15 18:00` 保留为具体时间，语义为 `deadline/todo`，日程 start 为 `2026-06-15T18:00:00+08:00`。
- WhatsApp 注入：`2026-06-13 15:00在武康路咖啡店见` 识别为 appointment，并生成主动建议，动作包含“查路线 / 帮我打车 / 稍后提醒”。
- WhatsApp 改期：`改到2026-06-14 10:00，地点还是武康路咖啡店` 与原 appointment 合并到同一 dedupe key，最终日程为 `2026-06-14T10:00:00+08:00`，地点为 `武康路咖啡店`，不再缺地点。
- Telegram 注入：`面试安排在2026-06-13 10:30...Zoom链接稍后发` 识别为 appointment，日程 start 为 `2026-06-13T10:30:00+08:00`，metadata 标记 `pending_artifacts=["zoom_link"]`，因为 Zoom 未给出所以仍需要补充信息，这个判断合理。
- 主动建议 API：`/api/suggestions` 返回用户可读内容，不再出现 raw JSON 文本。
- Web 工作台：`/`、`/api/suggestions`、`/api/agenda?limit=10`、`/api/career/board?limit=5` 均返回 200；求职看板不再是 404。
- Android 真机：APK 构建、安装、启动成功；真机配置写入线上服务器 `http://206.119.171.141` 和访问密码。
- Android 连续发送幂等：同一 `client_request_id=android-real-dedupe-20260612-002` 连续请求两次，第一次 57.7 秒返回，第二次 0.5 秒 cached 返回，`duplicate=true`；聊天历史只有 1 条 user 和 1 条 assistant，没有重复 assistant turn。

仍然存在的风险：

- `/api/chat` 首次回答仍慢，本轮线上简单请求耗时约 57.7 秒。重复请求已经能秒回，但首个请求的体验仍未达到“10 秒内可用”的验收标准。
- worker 每条事件处理耗时偏长，fix6 四条事件全部处理完成，但每条之间有 1-3 分钟级等待；核心链路正确性已过，但实时性还没有达标。
- 本轮 WhatsApp/Gmail/Telegram 是通过 `/event` 注入验证服务端处理链路，不等同于真实第三方账号收到新消息后的采集器端到端验证。

下一步建议：

- 给 chat 前置上下文检索和模型调用增加更强的超时降级，首包先基于最近对话/少量上下文返回。
- 给 worker 单条事件处理增加硬超时和失败隔离，避免慢模型调用拖住后续用户消息。
- 对真实 Gmail/WhatsApp/Telegram collector 做一次账号级端到端采集验证。

### P0-1 `/api/chat` 响应耗时不可接受

修复状态：已补首包检索预算修复，待线上端到端复测。

本次修复：

- Runtime `/api/chat` 不再强制 `max(limit, 80)` 拉取长期记忆候选。
- 新增 `chat_context_candidate_limit()`：默认 `limit=12` 时只取 24 条候选，最高不超过 50。
- WebSocket 实时聊天同样使用该预算，避免 Android 实时路径继续触发 80 条检索。
- 已用单元测试验证请求作用域仍会传入，且候选数被限制为 24。

现象：

- 简单模型请求在 model-router 直连时约 6.11 秒返回，语义正确。
- 经过 Runtime API `/api/chat` 后，同类简单请求出现 25.92 秒、79.08 秒级耗时。
- Android 真机发送 `ping` 最终能返回 `pong`，但约 75 秒后才落库并显示。

为什么这是问题：

- 用户在悬浮球里发消息时会看到长时间等待。
- Android 虽然有 fallback 提示，但这不是正常交互体验。
- 这个问题不是 qwen3.6 本身不可用，而是 Runtime API 前置上下文/记忆检索链路太慢。

已定位线索：

- `retrieve_context` 单步曾耗时 28.19 秒。
- 直接 model-router 请求明显快于 Runtime API。
- Android 先走实时通道，随后 fallback 到普通请求。

预期结果：

- 简单对话应在 5-10 秒内返回。
- 即使长期记忆检索慢，也不能阻塞首个可用回答。
- 超时必须有明确、可恢复的用户提示。

建议修复：

- 给 chat 前置检索加超时和降级策略。
- 首包路径优先使用当前对话、本地 client_context、少量 BM25。
- 向量/RAG、重型长期记忆检索异步补充，不阻塞简单回复。
- 对 embedding 首次加载做真正 warmup，并确保 chat 不等待首次加载。

验收标准：

- 本地和线上 `/api/chat` 对“请只回复：模型可用”类请求均在 10 秒内返回。
- Android 真机发送 `ping` 后 10 秒内显示最终 `pong` 或明确失败原因。
- 服务端日志能证明慢路径被降级而不是悄悄阻塞。

### P0-2 WebSocket 实时通道与 HTTP fallback 可能双写

修复状态：已补服务端和 Android 客户端幂等，待真机连续发送回归。

本次修复：

- `ChatIn` 增加 `client_request_id`。
- Android 每次发送生成一个 `android-<uuid>`，WebSocket 与 HTTP fallback 共用同一个请求 ID。
- 服务端用 `assistant_turns.tool_call_id + role` 存储 `client_request_id` 派生幂等键。
- 新增唯一索引 `assistant_turns_tool_call_id_role_idx`，防止同一请求重复 assistant turn。
- WebSocket `chat_done` 和 HTTP `/api/chat` 都返回规范化后的 `client_request_id`。
- 已用单元测试验证已有 turn 会被复用，不会重复入队。

现象：

- Android 真机发送一次 `ping` 后，服务端历史中出现两条 assistant 记录：
  - `pong`
  - 带前置换行的 `pong`

为什么这是问题：

- 同一用户输入只能产生一个最终 assistant turn。
- 重复 assistant 记录会污染上下文，后续模型可能召回重复内容。
- 用户可能在界面上看到重复回复，或刷新后历史变脏。

已定位线索：

- Android 先显示“实时通道没有返回，正在切换普通请求...”。
- 后续服务端历史出现重复 assistant turn。
- 说明实时通道和 fallback 缺少同一个请求的幂等标识。

预期结果：

- 同一条用户消息只允许落一条最终 assistant 回复。
- WebSocket 和 HTTP fallback 即使都完成，也必须合并或忽略后到结果。

建议修复：

- Android 发送消息时生成 `client_request_id`。
- WebSocket payload 和 HTTP fallback 共用同一个 `client_request_id`。
- 服务端以 `conversation_id + client_request_id` 做幂等。
- late `chat_done` 到达时只更新已有 turn，不新增重复 turn。

验收标准：

- 连续 10 次 Android 发送短消息，每次最多产生 1 条 assistant 回复。
- 刷新历史后没有重复 assistant 消息。

### P0-3 私有事件入队后 worker 没有及时处理

修复状态：已补 worker 噪声降级和批内优先级，待线上注入真实 WhatsApp/Gmail/Telegram 事件复测。

本次修复：

- 低价值 `focus/browser` 遥测事件只落 `semantic_events`，不再进入图谱、向量、日程、建议、timeline 等重处理链路。
- 同一批 Redis stream 内优先处理 `whatsapp/gmail/telegram/calendar` 用户消息，再处理普通事件，最后处理低价值遥测。
- checkpoint 仍按原始批次最大 stream id 推进，避免排序后重复消费。
- 原有 bad payload dead-letter 与 checkpoint 测试保持通过。

现象：

- 明确 WhatsApp 测试事件可以 `/event` 入队并返回 `queued`。
- 事件 trace 在 30-60 秒内仍然没有：
  - semantic event
  - memory vector
  - agenda item
  - proactive suggestion
- 第二次明确事件 `明天 16:00 在人民广场见，带合同` 也复现同样问题。

为什么这是问题：

- 这是 Nomi 的核心链路：私有消息 -> 记忆 -> 日程 -> 主动建议。
- 如果 worker 不处理真实用户消息，WhatsApp/Gmail/Telegram 的采集就只是“存原始日志”，不能产生产品价值。

已定位线索：

- 原始事件在 stream 中。
- worker 游标曾落后于最新测试事件。
- 噪声事件能进入建议/日程，而明确用户消息没有及时处理，说明队列优先级或消费隔离也有问题。

预期结果：

- 明确聊天消息入队后，应在合理时间内生成 semantic event。
- 对包含明确时间地点的约定，应生成 agenda item。
- 对需要跟进的事项，应生成 proactive suggestion。

建议修复：

- 检查 worker stream 消费循环是否被某条事件阻塞。
- 单条事件处理增加超时、失败隔离、dead-letter。
- 用户消息与浏览器/focus/network 噪声拆队列或加优先级。
- 增加 worker lag 指标和 `/api/worker/status`。

验收标准：

- 注入明确 WhatsApp 约定消息后 30 秒内 trace 出现 semantic event。
- 60 秒内生成合理 agenda item，时间必须归一到具体日期。
- 同期 worker lag 不持续增长。

### P0-4 主动建议和日程被低价值 focus/browser 事件污染

修复状态：已修复并通过反例测试。

本次修复：

- 新增低价值遥测识别：`focus`、`browser`、`browser_network_event`、`deep_focus`、`runtime_network_hook` 等默认不能生成用户可见日程或主动建议。
- 页面标题类信息即使被模型/规则误标为 `appointment`，也会在 agenda/suggestion 候选入口被拦截。
- 保留真实用户消息保护：raw payload 中有 `message/body/text/content/subject` 时不会被该规则误杀。
- 已验证 Gmail 页面标题不会生成 agenda/suggestion，真实 WhatsApp 约定仍能生成“查路线/帮我打车/稍后提醒”动作。

现象：

- `/api/suggestions` 返回“跟进近期安排”，内容来自 Gmail 页面标题。
- `/api/agenda` 把 Gmail 页面标题写成 `appointment`。
- 该记录没有具体时间、地点、参与人，却进入用户可见日程/建议。

为什么这是问题：

- Nomi 会主动打扰用户，但内容并不是用户真正需要处理的事项。
- 页面标题类信息不能等同于聊天约定、待办或关系动作。
- 这会快速破坏用户对主动提醒的信任。

已定位线索：

- source 为 `focus`。
- `parser_mode` 或 fallback 规则把低价值事件归成 appointment。
- metadata 中已有 model parse timeout warning，说明模型失败后规则 fallback 过于激进。

预期结果：

- Gmail/Google/LinkedIn 等页面标题默认只能作为浏览上下文或短期状态。
- 没有明确联系人、动作、时间、地点、截止日期、金额等证据时，不应生成日程或主动建议。

建议修复：

- `focus`、`browser_network_event`、页面标题类事件默认禁止生成 appointment/proactive suggestion。
- fallback 规则应更保守：宁可不提醒，也不能乱提醒。
- 为 Gmail/Google/LinkedIn 页面标题增加反例测试。
- 对 model parse timeout 后的 fallback 结果增加低置信拦截。

验收标准：

- Gmail 页面标题不会出现在 `/api/agenda`。
- Gmail 页面标题不会生成用户可见 proactive suggestion。
- 明确 WhatsApp 约定仍能生成正确日程，不能被整体禁用。

### P0-5 Android 连接测试反馈语义不足

修复状态：已修复并通过 Android 单元测试。

本次修复：

- Android 新增 `AssistantApiClient.connectionStatus()`。
- 连接测试现在先查公开 `/health`，再查带密码的 `/api/model/status`。
- 密码错误会显示“服务器可达，但访问密码不正确。”，不再显示“连接正常”。
- 受保护 API 不可用时会显示具体失败原因。

现象：

- 点击“保存并测试连接”后显示“连接正常”。
- 但当前测试只证明公开 `/health` 可访问。
- 它不能证明：
  - 访问密码正确
  - 受保护 API 可用
  - `/api/chat` 可用
  - WebSocket 可用

为什么这是问题：

- 用户看到“连接正常”后会以为对话、建议、日程都可用。
- 实际上对话仍可能慢、失败或 fallback。

预期结果：

- 连接测试应区分：
  - 服务器可达
  - 访问密码正确
  - 受保护 API 可用
  - 对话服务可用
  - 实时通道可用

建议修复：

- 保存配置后依次测试 `/health`、受保护轻量接口、WebSocket 握手。
- UI 显示分项状态，而不是笼统“连接正常”。
- 密码错误时明确显示“访问密码不正确”。

验收标准：

- 密码错误时不能显示“连接正常”。
- 服务器可达但受保护 API 失败时，应显示“服务器可达，访问密码或权限失败”。
- WebSocket 不通但 HTTP 可用时，应显示“实时通道不可用，已切换普通请求”。

## 2. P1 问题

### P1-1 Nomi outbound 查询端点返回 404

修复状态：已修复并通过 API 测试。

本次修复：

- 新增 `/api/assistant-outbound`，作为 `/api/assistant-outbound/messages` 的兼容别名。
- 查询返回结构保持 `{count, items}`。
- 已验证草稿发送失败/blocked 记录能从统一 outbound 查询接口读到。

现象：

- `/api/assistant-identities` 可用。
- `/api/assistant-inbox` 可用。
- `/api/assistant-outbound` 返回 404。

为什么这是问题：

- 如果产品要支持 Nomi 自有 Gmail/WhatsApp/SMS/电话身份，用户应该能查看 Nomi 代发记录、草稿、发送状态。
- 缺少统一 outbound 查询接口，会导致 Web/Android 展示和排错困难。

预期结果：

- 应存在统一的 outbound 查询接口，或文档明确真实接口名称。
- 返回应包含 draft、pending、sent、failed 等状态。

建议修复：

- 对照现有路由，确认是否已有等价接口。
- 如果没有，补 `/api/assistant-outbound`。
- Web/Android 统一使用同一接口。

验收标准：

- 空状态返回 HTTP 200 和结构化空数组。
- 发送草稿/待确认/失败记录能被查询到。

### P1-2 Web 工作台只完成静态结构验证，未完成登录后交互验证

现象：

- Web 首页、登录表单、tab 静态结构可达。
- 本轮没有完成浏览器中登录后的真实对话、日程、建议、求职看板交互验收。

为什么这是问题：

- 静态 HTML 存在不等于产品可用。
- 慢请求和事件链路问题可能在 Web 端同样影响体验。

预期结果：

- 登录后各 tab 能正常加载。
- 失败状态有明确提示。
- 对话、日程、建议与 API 输出一致。

建议修复：

- 在 P0 chat 和 worker 修复后，用浏览器完成 Web 可视化回归。

验收标准：

- 登录成功。
- 对话有流式或明确等待状态。
- 日程/建议不展示噪声。
- 求职看板空状态合理，不 404。

## 3. 未完成真实验收的风险项

### R1 noVNC 只验证静态入口，未验证实际远程桌面操作

已验证：

- `:6080/vnc.html` HTTP 200。

未验证：

- noVNC 登录后画面是否稳定。
- Chrome 是否可操作。
- Gmail/WhatsApp/Telegram/LinkedIn 登录页是否正确。
- 登录授权完成后能否返回 Nomi 授权列表。

后续验收：

- 用 noVNC 打开各渠道。
- 验证关闭按钮、页面尺寸、输入框、二维码/账号登录流程。

### R2 Composio 只验证 reachable，未验证具体 toolkit/session 权限

已验证：

- `/api/tools/composio/status` 显示 configured/reachable。

未验证：

- session toolkits 列表。
- Gmail/Google Docs/Calendar/LinkedIn 等具体工具授权状态。
- 真正执行工具调用。

后续验收：

- 查询已连接 toolkits。
- 对 read-only 工具做一次无副作用调用。
- 对写操作只做 dry-run 或用户确认后的测试。

### R3 语音输入未在本轮回归执行

未验证：

- 长按悬浮球是否触发麦克风授权。
- 火山 ASR 流式链路是否正常。
- ASR partial/final 文本是否合理进入输入框或发送流程。

后续验收：

- 真机权限流程。
- 录音短句测试。
- provider 错误提示不能泄露密钥。

### R4 求职 Agent 产品闭环未在本轮验证

已验证：

- `/api/career/board` 不再 404，返回 ready 空状态。

未验证：

- 岗位解析。
- JD 与简历匹配。
- 简历改写。
- cover letter/自我介绍生成。
- LinkedIn/ATS 自动化执行。
- 求职看板阶段流转。

后续验收：

- 用固定求职测试数据跑完整 pipeline。
- 每一步检查输出是否与 JD 和简历一致，不能只看接口成功。

### R5 Long-tail Agent 未在本轮验证

未验证：

- Planner 拆解。
- 结构化任务 memory。
- checkpoint。
- 自我纠偏。
- 最终评估。
- 失败兜底。

后续验收：

- 用一个非 pipeline 的复杂任务跑 dry-run。
- 检查每一步是否仍围绕原始目标。

## 4. 当前已确认通过的关键点

这些不是问题，但记录在这里用于避免重复排查：

- 私有云 HTTP 基础入口可用。
- Web 首页返回 Nomi 工作台，不是默认错误页。
- noVNC 静态页面可达。
- Docker 核心服务运行。
- qwen3.6 上游模型可用。
- model-router 没有 `/v1/v1` 路径错误。
- Android 真机能启动 Nomi。
- 默认悬浮球形态基本符合要求。
- Android 输入框与键盘布局本轮验证通过。
- 求职看板接口不再 404。

## 5. 建议修复顺序

1. 修 worker 消费和队列隔离：先让真实 WhatsApp/Gmail/Telegram 消息进入 semantic/memory/agenda/suggestion。
2. 修主动建议/日程噪声过滤：先阻止页面标题类事件污染用户可见提醒。
3. 修 `/api/chat` 慢请求：让简单对话稳定在 5-10 秒内返回。
4. 修 WebSocket/HTTP fallback 幂等：避免重复 assistant 记录。
5. 修 Android 连接测试语义：分项显示服务器、密码、API、实时通道状态。
6. 补 Nomi outbound 查询接口或统一路由文档。
7. 回头补 Web/noVNC/Composio/语音/求职/Long-tail 的端到端验收。
