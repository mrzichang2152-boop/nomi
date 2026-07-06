# Nomi 产品功能说明（基于当前实际代码）

日期：2026-06-08
范围：本说明仅基于当前仓库代码、配置模板、数据库 schema、Android 端源码、Runtime API、Worker、Chromium Runtime 与 Docker 部署文件整理。没有把尚未落到代码里的产品设想写成已实现能力。

## 1. 产品定位

Nomi 是一个部署在用户个人电脑或私有云服务器上的私人 AI 助理系统。它不是传统中心化 SaaS，而是把用户的浏览器会话、私有消息、邮件、日程、联系人、长期记忆和任务执行能力尽量放在用户自己的运行环境中。

当前代码中的 Nomi 主要包含四类能力：

1. 私有信息采集：通过受控 Chromium、Composio 连接、Webhook、Android 悬浮球等入口接收用户的私有上下文。
2. 长期记忆与关系理解：把私有事件写入事件账本、语义记忆、向量索引、KV 状态、实体关系图谱和日程。
3. 主动建议与对话：根据邮件、WhatsApp、Telegram、日程、浏览器行为等事件生成提醒、建议、行动选项，并通过 Web 工作台或 Android 悬浮球展示。
4. 任务执行基座：对高频任务走确定性 Pipeline，对长尾复杂任务走 Long-tail Agent / OpenClaw / Composio 等工具执行框架，并在外部动作前加入权限、确认、审计和回滚/补偿流程。

## 2. 部署形态

当前代码支持用 Docker Compose 在私有云或本地环境运行。

核心服务包括：

- `runtime-api`：FastAPI 后端，提供事件、记忆、搜索、聊天、日程、建议、工具、Pipeline、Composio、OpenClaw、语音、Nomi 自有身份等 API。
- `worker`：Redis Stream 消费者，负责事件脱敏、语义抽取、记忆写入、日程解析、主动建议生成。
- `chromium-runtime`：Playwright 持久化 Chromium 运行环境，用于用户登录 Gmail、WhatsApp、Telegram、Google Calendar 等网页账号并采集可见信息。
- `model-router`：模型路由服务，支持把任务路由到 Qwen、FastEmbed 等模型/嵌入能力。
- `postgres`：包含 pgvector 的数据库，用于事件、记忆、向量、日程、审计、Pipeline、Composio 等数据。
- `redis`：事件流、实时消息和 Worker 队列。
- `nginx`：Web 工作台入口和反向代理。

公开端口在当前部署设计里主要包括：

- `80`：Web 工作台和 API 入口。
- `6080`：noVNC/受控浏览器入口。
- `10799`：服务器 SSH 入口。
- `443`：未来 HTTPS 入口。

## 3. 用户入口

### 3.1 Web 工作台

当前 Web 工作台由 `runtime_api/app/static/index.html` 和 `runtime_api/app/static/app.js` 实现，具备密码保护。

工作台包含以下页面：

- 对话：与 Nomi 对话，支持 WebSocket 实时流式回复；失败时会展示超时、断连或网络错误提示。
- 日程：查看内部日程、刷新日程、按日期切换。
- 搜索：对长期记忆进行个人搜索，并展示检索计划、来源层级和证据。
- 治理：查看事件审计、长期记忆、状态记忆、任务路由记录。
- 建议：展示主动建议，并支持确认、忽略、稍后提醒等操作。
- 采集：查看采集器状态和健康情况。
- 工具：查看 Pipeline/工具状态，发起任务路由、OpenClaw field release、Composio 授权连接等。

实现状态：已实现基础 Web UI、密码鉴权、实时通道、主要仪表盘和工具面板。

### 3.2 Android 悬浮球

Android 端在 `android_app` 下实现，核心服务是 `FloatingBallService`。

当前悬浮球能力包括：

- 显示 Nomi 小人形象的悬浮球。
- 点击悬浮球打开/关闭悬浮对话面板。
- 拖动悬浮球并自动贴边。
- 悬浮对话面板内展示历史对话、输入框、发送按钮、设置入口、完整工作台入口。
- 通过 WebSocket 接收主动消息，并在悬浮球旁展示消息气泡和未读角标。
- 点击主动消息气泡后进入完整对话。
- 支持账号连接列表、Nomi 自有身份状态、采集渠道状态。
- 支持长按悬浮球触发语音输入。
- 没有麦克风权限时，会打开系统权限申请 Activity。

实现状态：Android 悬浮球、悬浮对话、主动消息气泡、语音输入入口和工作台入口已实现；真实设备上的键盘遮挡、窗口闪烁等体验仍需要继续回归修复。

### 3.3 受控浏览器/noVNC

`chromium-runtime` 使用 Playwright 持久化浏览器上下文，用户可以在私有云服务器上的 Chromium 中登录自己的网页账号。noVNC 提供远程可视化访问。

这个入口用于：

- 用户手动登录 Gmail、WhatsApp Web、Telegram Web、Google Calendar 等账号。
- Nomi 采集已登录网页上的可见 DOM 信息、部分网络事件和焦点行为。
- 后续 Pipeline 或自动化任务在用户授权范围内打开浏览器页面。

实现状态：Playwright 持久化浏览器、noVNC、可见 DOM 采集和部分运行时 hook 已实现；平台登录是否成功取决于平台风控、浏览器指纹和用户账号状态。

## 4. 私有数据采集

### 4.1 Gmail

当前代码提供两条 Gmail 采集路径：

1. 受控 Chromium 可见 DOM 采集：
   - 采集收件箱预览。
   - 采集打开邮件线程的可见内容。
   - 识别发件人、主题、时间、摘要和正文片段。

2. Composio Gmail 连接：
   - 通过 Composio Connect 建立 Gmail session。
   - 支持调用 Composio Gmail 工具拉取邮件。
   - 拉取结果会转为 Nomi 私有事件并进入后续记忆处理链路。

实现状态：DOM 采集、Composio 连接入口、Gmail fetch API、结果入库逻辑已实现；完整邮箱读取依赖 Composio 授权和对应 Gmail 工具可用。

### 4.2 WhatsApp Web

当前 WhatsApp 采集能力包括：

- 聊天列表预览采集。
- 当前打开会话的上下文识别，包括聊天名称、群聊/私聊、参与者。
- MutationObserver 监听新增消息。
- 可见历史消息同步。
- 消息来源、发送者、时间标签、消息内容、采集范围写入事件。

实现状态：受控浏览器中的 WhatsApp 可见 DOM 采集和新增消息监听已实现；不是 WhatsApp 官方 API，准确性依赖 Web 页面结构和登录状态。

### 4.3 Telegram Web

当前 Telegram 采集能力主要是：

- 从 Telegram Web 可见界面读取聊天预览和文本信号。
- 把可见内容写入私有事件流，后续进入语义处理和记忆。

实现状态：基础可见 DOM 采集已实现；深层历史同步和官方 Bot/API 集成不是当前代码的主能力。

### 4.4 Google Calendar

当前 Google Calendar 采集能力包括：

- 从受控浏览器可见日历页面提取日程事件。
- 通过 Composio/Google Calendar 作为外部工具连接候选。
- 后端有日程 Pipeline 和内部日程存储。

实现状态：可见 DOM 采集、内部日程写入、外部日历确认流程基座已实现；外部日历写入依赖工具授权和确认。

### 4.5 浏览器行为与网页上下文

Chromium Runtime 具备以下浏览器行为采集：

- 当前页面 URL、标题、焦点时长。
- 点击、滚动、输入、复制等焦点事件。
- 搜索页面信号。
- Chrome bookmarks 信号。
- fetch/xhr/websocket 网络事件元信息，默认去掉 URL query 和 fragment，避免把敏感 token 直接写入普通事件。

实现状态：基础浏览器行为采集和运行时 hook 已实现；页面深度理解和跨站复杂行为建模仍是后续增强方向。

### 4.6 采集器设置与健康状态

后端提供：

- `/api/collectors/settings`
- `/api/collectors/status`
- `/collectors/health`

用于查看或更新 Gmail、WhatsApp、Telegram、Calendar、Search、Bookmarks、Focus 等采集器状态。

实现状态：已实现。

## 5. 私有事件、脱敏与治理

所有采集数据会先进入私有事件链路。当前数据库和 API 支持：

- `events`：原始事件账本。
- `semantic_events`：语义事件。
- `memory_audit_log`：记忆审计。
- `task_route_traces`：任务路由审计。
- `pipeline_execution_results`：Pipeline 执行结果。
- `private_raw_event` API：受保护地读取原始私有事件。
- `memory/delete`：删除记忆。
- `api/memory/governance`：治理视图。

Worker 会对敏感字段做处理，包括但不限于：

- OAuth/token/secret。
- 验证码。
- 支付金额、订单号。
- 地址、联系方式等高敏内容。

重要边界：当前系统的设计目标不是“不在本地存敏感信息”，而是“敏感信息保留在用户本地或私有云，并在请求模型或外部服务时进行过滤/脱敏”。也就是说，本地必要时仍可以存储和使用敏感信息，但普通模型上下文和外部工具调用会尽量走过滤后的结构化内容。

实现状态：事件存储、脱敏处理、治理查询、删除和审计基座已实现；具体脱敏准确率需要持续用真实数据回归。

## 6. 长期记忆系统

当前记忆不是单一 RAG，而是多层记忆结构：

### 6.1 事件账本

所有来源事件先写入 `events`，保留 source、event_type、occurred_at、raw_data、sensitive_flags 等信息。

### 6.2 语义事件

Worker 会把原始事件解析成 `semantic_events`，识别事件类型、实体、时间、地点、重要性等信息。

### 6.3 KV/状态记忆

系统通过 `facts`、`memory_states` 等表保存用户偏好、联系人状态、任务状态、关系状态等更适合覆盖更新的内容。

适合 KV/状态记忆的内容包括：

- 某个联系人当前关系状态。
- 某个任务的当前阶段。
- 用户偏好、约束、常用地址。
- 某个目标的最新进度。

### 6.4 知识图谱

系统通过 `entities` 和 `relationships` 保存联系人、组织、地点、任务、目标之间的关系。

这用于回答：

- 用户认识谁。
- 谁和哪个公司/机会/群聊有关。
- 某个关系最近是否变冷。
- 一个事件和哪些人、地点、项目相关。

当前实现具备实体和关系表、关系抽取和更新逻辑。超级节点治理、关系权重、关系衰减等策略已有部分代码和文档基础，但仍需要真实数据持续调优。

### 6.5 向量/RAG 记忆

系统通过 `memory_vectors` 保存嵌入向量，支持个人搜索和上下文召回。

当前嵌入来源包括：

- FastEmbed/local embedding。
- 通过 `model-router` 路由的 embedding 能力。

RAG 主要用于：

- 长文本邮件/聊天记录召回。
- 语义相似问题搜索。
- 对话上下文补充证据。

### 6.6 作用域隔离

当前记忆系统特别处理了 WhatsApp 等聊天场景的作用域问题，避免“跟 A 聊天时召回 B 说 A 坏话”这类泄露。系统会根据 source、conversation、chat/contact scope 过滤记忆。

实现状态：KV + 知识图谱 + RAG 的多层记忆结构已实现；真实效果取决于语义抽取质量、实体消歧、图谱权重和作用域策略，仍需长期回归。

## 7. 上下文与对话

### 7.1 对话入口

后端提供：

- `/api/chat`
- `/api/chat/messages`
- `/api/chat/history`
- `/ws`

Web 工作台和 Android 悬浮球都可以发送用户消息。

### 7.2 流式输出

Web 工作台通过 WebSocket 接收：

- `chat_delta`
- `chat_done`
- `error`

Android 端通过 `RealtimeClient` 连接同一个实时通道，支持流式展示。

如果 WebSocket 不可用，Android 端有 HTTP fallback。

### 7.3 上下文包

`context_pack_pipeline` 会组合：

- 与当前请求相关的作用域记忆。
- 活跃日程。
- 最近对话轮次。
- 相关长期记忆证据。

项目已经按大上下文思路设计，目标上下文上限按 256K 规划。实际代码中 Android 端会维护本地悬浮窗对话上下文快照，后端也有 `context_snapshots`。

实现状态：对话、历史、实时流、上下文包和来源证据展示已实现；超长上下文的 token 精确预算和极端长输入保护仍需要持续完善。

## 8. 日程、待办与主动建议

### 8.1 日程管理

系统通过 `agenda_items` 和 `agenda_item_versions` 保存日程和版本。

当前能力包括：

- 从 WhatsApp、Telegram、Gmail 等消息中解析约定、待办、截止日期、改期、取消。
- 把“明天”“周五”等相对时间解析成具体日期。
- 标记时间/地点/参与人是否明确。
- 写入内部日程。
- 支持稍后提醒、完成、忽略等操作。
- 支持日程版本记录。

实现状态：内部日程系统已实现；外部 Google Calendar 写入需要授权和确认。

### 8.2 主动建议

系统会对新事件进行处理，判断是否需要主动给用户发消息。

主动建议流程包括：

1. 事件进入。
2. 语义抽取。
3. 重要性评分。
4. 冷却检查。
5. 生成建议。
6. 通过 WebSocket 推送给 Web 工作台或 Android 悬浮球。

建议可以包含行动选项，例如：

- 查看路线。
- 帮我打车。
- 稍后提醒。
- 起草回复。
- 忽略。

实现状态：主动建议生成、存储、查询、操作和 Android 气泡展示已实现；建议质量依赖事件解析、重要性评分和真实用户反馈调优。

## 9. 高频确定性 Pipeline

当前代码定义了 18 条核心 Pipeline。它们用于高频、可结构化、需要稳定执行边界的任务。

| Pipeline | 产品能力 | 当前状态 |
| --- | --- | --- |
| `event_ingestion_pipeline` | 私有事件入库、去重、任务投递 | 已实现 |
| `memory_write_pipeline` | 长期记忆写入 KV/图谱/RAG/向量 | 已实现 |
| `context_pack_pipeline` | 构建模型上下文包 | 已实现 |
| `personal_search_pipeline` | 个人记忆搜索 | 已实现 |
| `chat_response_pipeline` | Nomi 对话回复 | 已实现 |
| `reply_pipeline` | 起草消息/邮件回复，发送前确认 | 已实现基座 |
| `email_pipeline` | 邮件搜索、总结、待办、草稿 | 已实现基座，依赖邮箱授权 |
| `agenda_pipeline` | 日程识别、冲突检查、内部日程写入 | 已实现内部能力，外部日历依赖授权 |
| `task_todo_pipeline` | 待办识别、提醒计划 | 已实现 |
| `proactive_suggestion_pipeline` | 主动建议 | 已实现 |
| `route_pipeline` | 路线查询 | 基座已实现，真实地图工具依赖适配器 |
| `ride_pipeline` | 打车估价/下单前确认 | 基座已实现，真实 Uber/地图工具依赖适配器 |
| `shopping_pipeline` | 商品搜索/比价/确认后加购 | 基座已实现，真实电商工具依赖适配器 |
| `payment_bill_pipeline` | 账单识别、付款前风险确认 | 基座已实现，真实支付工具依赖适配器 |
| `contact_relationship_pipeline` | 联系人事实和关系图谱更新 | 已实现 |
| `document_file_pipeline` | 文档定位、读取、总结、写入前确认 | 基座已实现，依赖 Drive/Docs/Sheets 授权 |
| `account_login_pipeline` | 打开受控浏览器让用户登录账号 | 已实现 |
| `governance_audit_pipeline` | 路由、风险、确认、输出、反馈审计 | 已实现 |

Pipeline 的共同特点：

- 有明确 required slots。
- 有 permission/risk 等级。
- 写入 `task_trace`、`pipeline_execution_results` 等审计记录。
- 对外部动作保留确认机制。
- 能被工具路由器选择，也能按指定 pipeline 执行。

## 10. 长尾 Agent 与 OpenClaw

对于不能稳定落到某条确定性 Pipeline 的复杂任务，当前代码提供 Long-tail Agent 和 OpenClaw 基座。

### 10.1 Long-tail Agent

后端支持：

- 创建 agent task。
- 拆解计划。
- 保存结构化任务 memory。
- 逐步执行。
- 每步校验。
- 暂停、恢复、取消。
- 请求用户输入。
- 最终评估和交付。
- 外部效果提案、确认、执行、回滚、补偿。

这对应用户之前提出的“planner、结构化 memory、自我纠偏、兜底、最终评估、最终交付”思路。

实现状态：API 和运行时框架已实现；具体任务质量依赖 planner、verifier、工具适配器和真实场景数据。

### 10.2 OpenClaw

OpenClaw 在当前代码中被作为特殊工具/长尾工具使用，支持：

- 创建 job。
- 查询 job 状态。
- 单步运行。
- 执行 OpenClaw 请求。
- Field release，带敏感字段释放审计。
- WebSocket 推送 OpenClaw job event。

实现状态：工具接口和事件流已实现；真实外部自动化能力依赖 OpenClaw 本身和具体任务适配。

## 11. Composio 集成

当前代码已经接入 Composio 作为主要外部工具平台。

实现能力包括：

- 配置 `COMPOSIO_API_KEY`、`COMPOSIO_USER_ID`、`COMPOSIO_CALLBACK_URL`。
- 按 readonly/write session 创建 Composio session。
- 默认只启用白名单 toolkits。
- 创建 Composio Connect Link。
- 授权回调页支持 Android deep link 返回 Nomi。
- 同步 toolkit 连接状态。
- 执行 Composio tool。
- 记录 tool invocation。
- 按工具风险决定是否需要确认。

默认 readonly toolkits 包括 Gmail、Google Calendar、Drive、Docs、Sheets、Tasks、Maps、GitHub、Slack、Notion 等。默认 write toolkits 包括 Gmail、Calendar、Drive、Docs、Sheets、Tasks、GitHub、Slack、Notion、Todoist、Linear、Jira 等。

实现状态：Composio session、connect、toolkit sync、tool execute 和审计已实现；真实可用性依赖 Composio SDK、API Key、用户授权和 toolkit 权限。

## 12. Nomi 自有 Gmail、WhatsApp 和手机号

当前代码支持给 Nomi 配置自己的通信身份，而不是只使用用户的个人账号。

默认身份包括：

- `nomi_gmail_primary`：Nomi 自有 Gmail。
- `nomi_whatsapp_primary`：Nomi 自有 WhatsApp。
- `nomi_phone_primary`：Nomi 自有手机号。

### 12.1 自有 Gmail/WhatsApp

当前能力包括：

- 查看 Nomi 自有身份列表。
- 连接身份。
- 健康检查。
- 接收 Gmail sync/PubSub 事件。
- 接收 WhatsApp webhook 事件。
- 生成 outbound draft。
- 修改、发送、取消 draft。
- 所有发送动作默认进入草稿确认流程。

触发后路由规则：

- 外部联系人发给 Nomi 的消息：先存储和通知用户，不自动回复。
- 用户明确要求 Nomi 发消息/邮件：进入确定性 `reply_pipeline` / outbound draft pipeline。
- 复杂规划类请求：允许进入 Long-tail Agent，但最终发送仍回到草稿确认。

实现状态：身份注册、收件入口、草稿、发送前确认和路由规则已实现；真实 Gmail/WhatsApp 发送依赖具体 provider adapter。

### 12.2 自有手机号

当前 V1 电话/短信身份能力包括：

- Nomi 自有手机号配置。
- 接收短信 webhook。
- 接收入站电话 webhook。
- 出站短信草稿。
- 出站电话草稿。
- V1 电话只支持单向语音播放指令，不支持双工实时通话。
- 电话状态回调。
- 电话播放内容 API。

实现状态：V1 代码基座已实现；真实短信和电话依赖 Twilio/其他电话 provider 配置。

## 13. 语音输入

当前 Android 悬浮球支持长按触发流式语音输入。

流程：

1. 用户长按悬浮球。
2. 如果没有麦克风权限，打开系统权限申请。
3. 权限通过后启动录音。
4. Android 端把音频 chunk 通过 `/ws/voice` 发送给后端。
5. 后端转发到 ASR provider。
6. 默认 provider 是火山引擎流式 ASR，也支持 fake/test provider。
7. 后端返回 partial/final transcript。
8. Android 根据置信度决定直接发送、展示确认气泡或提示没听清。

实现状态：Android 长按、权限申请、录音、WebSocket、后端 ASR 协议、火山引擎 provider 基座已实现；真实识别质量依赖火山引擎配置和设备录音稳定性。

## 14. 分级授权与批量自动化基座

当前代码中存在 `delegated_automation` 模块，用于未来让用户分级授权 Nomi 做批量外部动作，例如找工作场景中的加人、私信、点击 Apply/Submit、批量投递等。

当前实现包括：

- Delegation grant。
- Target manifest。
- Evaluation policy。
- Execution trace。
- 暂停 grant。
- 每日额度、批次额度。
- 去重。
- challenge/captcha/2FA/security check 停止条件。
- 目标必须来自 manifest。
- 内容必须有 evidence。
- 用户暂停后停止。

当前策略明确禁止在 V1 对用户个人 Gmail/WhatsApp 表面做批量自动化。

实现状态：授权策略和评估 API 已实现为基座；真实浏览器执行器、UI 授权中心、持久化完整状态和找工作专用投递流程还不是完整产品化状态。

## 15. 工具路由

当前代码有工具注册表和路由 API：

- `/api/tools/catalog`
- `/api/tools/route`
- `/api/tools/route/traces`
- `/api/model/route`
- `/api/pipelines/run`

路由逻辑会先判断是否命中高频核心 Pipeline。若命中，则走确定性 Pipeline；否则进入 agent/openclaw/composio 等长尾工具路径。

实现状态：核心路由、trace 和 pipeline 执行结果记录已实现；更复杂的工具选择质量仍依赖实际评测。

## 16. 模型与嵌入

当前项目通过 `model-router` 抽象模型调用。

配置项包括：

- 模型 API base URL。
- Qwen 模型名。
- Embedding provider。
- FastEmbed cache。

模型用于：

- 对话回复。
- 语义抽取。
- 记忆整理。
- Agent 计划/校验。
- 搜索答案生成。

嵌入用于：

- `memory_vectors` 向量索引。
- 语义检索。
- 上下文召回。

实现状态：模型路由和 embedding 基座已实现；真实可用性依赖外部模型服务是否在线。

## 17. 数据库能力

当前数据库支持以下关键表：

- `events`
- `semantic_events`
- `timeline`
- `working_memory`
- `semantic_memory`
- `facts`
- `memory_states`
- `memory_vectors`
- `proactive_suggestions`
- `proactive_candidates`
- `user_feedback`
- `assistant_conversations`
- `assistant_turns`
- `context_snapshots`
- `agenda_items`
- `agenda_item_versions`
- `entities`
- `relationships`
- `collector_health`
- `collector_settings`
- `memory_audit_log`
- `task_route_traces`
- `pipeline_execution_results`
- `composio_sessions`
- `composio_connect_requests`
- `composio_toolkits`
- `composio_tool_invocations`
- `composio_triggers`

实现状态：核心数据模型已覆盖当前产品功能。

## 18. 用户可以完成的典型任务

基于当前代码，用户可以做以下事情：

1. 在私有云服务器上登录 Gmail、WhatsApp Web、Telegram Web、Google Calendar。
2. 让 Nomi 自动采集这些页面上的可见消息、邮件、日程和浏览器行为。
3. 在 Web 工作台或 Android 悬浮球里和 Nomi 对话。
4. 搜索自己的长期记忆，例如某个客户、朋友、邮件、约定或聊天内容。
5. 让 Nomi 根据聊天记录或邮件自动创建内部日程和待办。
6. 收到 Nomi 主动推送的重要提醒，例如约定、报价、待跟进事项。
7. 点击建议选项，例如稍后提醒、忽略、起草回复、查看路线。
8. 连接 Composio toolkits，让 Nomi 具备 Gmail、Calendar、Drive 等外部工具能力。
9. 给 Nomi 配置自己的 Gmail、WhatsApp 和手机号，让 Nomi 以助理身份收消息、起草消息、发短信或发起 V1 单向语音电话。
10. 长按 Android 悬浮球语音输入。
11. 通过 Long-tail Agent/OpenClaw 执行不适合固定 Pipeline 的复杂任务，但外部动作仍要走确认和审计。

## 19. 当前代码中的主要边界和未完成点

以下不是产品愿景缺失，而是基于代码现状必须如实说明的边界：

1. WhatsApp、Telegram、LinkedIn 等网页采集依赖可见 DOM 和平台页面结构，不是官方全量 API。
2. Gmail 全量能力更适合走 Composio；如果只用网页 DOM，只能采集可见页面和打开线程。
3. 外部发送、打车、购物、支付、地图、文档写入等动作多为 Pipeline/适配器基座，真实执行依赖授权和 provider。
4. Nomi 自有 WhatsApp、Gmail、手机号具备身份、Webhook、草稿和路由基座，但真实发送/接收依赖具体第三方服务配置。
5. Android 端真实设备体验仍存在需要继续打磨的地方，例如键盘遮挡、窗口闪烁、不同厂商系统的悬浮窗兼容。
6. 长尾 Agent 框架已实现，但稳定完成复杂任务需要更多真实工具、真实数据集和端到端评测。
7. 分级授权和批量自动化目前是策略和 API 基座，不是完整的浏览器执行产品。
8. 记忆质量依赖语义抽取、实体消歧、关系权重和上下文作用域策略，仍需要持续回归。
9. 模型、ASR、Composio 等外部能力必须正确配置，否则相关功能会降级或不可用。

## 20. 产品总结

当前代码里的 Nomi 已经不是一个单纯聊天 UI，而是一个具备私有信息采集、长期记忆、日程处理、主动建议、Android 常驻入口、Web 工作台、Composio 工具连接、Nomi 自有通信身份、语音输入和长尾任务执行基座的私人助理系统。

它当前最完整的产品闭环是：

1. 用户在私有云受控浏览器或 Composio 中连接个人账号。
2. Nomi 采集私有事件。
3. Worker 做脱敏、语义抽取、记忆写入、日程解析和主动建议判断。
4. 用户通过 Android 悬浮球或 Web 工作台收到提醒/建议。
5. 用户可以继续对话、搜索记忆、查看日程、确认行动。
6. 高频任务进入确定性 Pipeline；长尾任务进入 Agent/OpenClaw；外部动作进入确认和审计。

换句话说，当前实现已经搭起了“私人上下文 + 关系/任务记忆 + 主动建议 + 工具执行”的基础系统。下一阶段如果要把它变成更强的垂类产品，重点不应再只是增加入口，而应围绕一个高价值场景把 Pipeline、数据采集、关系图谱、行动工具和端到端评测打穿。
