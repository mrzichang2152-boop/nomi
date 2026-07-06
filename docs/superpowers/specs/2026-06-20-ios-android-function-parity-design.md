# iOS Android 功能完整对齐设计

日期：2026-06-20
状态：设计稿 v2，尚未进入开发
决策：功能完整对齐 Android，UI 只做简单 Nomi 工作台，不做像素级复刻。

## 背景

Android 端当前的核心体验不是一个普通聊天 App，而是“常驻 Nomi 入口 + 紧凑浮层工作台”。悬浮球负责长期入口、未读角标、主动消息气泡、拖拽吸边和长按语音；浮层工作台负责聊天、设置、账号授权、求职看板、完整工作台跳转等日常操作。

iOS 端已完成 Live Activity / Dynamic Island 的基础能力，但 App 内仍是 Chat、Suggestions、Settings 三个分散 Tab。当前 iOS 缺少 Android 已有的大量功能，包括真实建议列表、账号授权、远程浏览器、求职看板、语音输入、聊天历史恢复、实时消息 UI 消费等。

本设计的目标是：iOS 不必完全复刻 Android 悬浮窗 UI，但不能删减产品能力。所有 Android 日常功能都要在 iOS 上有等价入口和验收路径。Android 系统悬浮窗无法在 iOS 上实现时，使用 iOS 可用的替代面：App 内 Nomi 工作台、Live Activity、Dynamic Island、通知、Safari / WebView、App Intents。

## 目标

1. iOS 功能覆盖 Android 当前日常功能面。
2. iOS 首屏改为简单 Nomi 工作台，而不是把能力拆散在多个占位 Tab。
3. 灵动岛承担常驻入口、未读状态、最新主动消息和聊天状态展示，并能点击回到目标页面。
4. 后端尽量复用现有 Android 已使用的 API 和 WebSocket 协议。
5. 所有功能都有明确错误态、空态、加载态和验收标准。
6. 本文档只定义设计，不开始开发。

## 完整性判定

本项目后续不得用“UI 有入口”代替“功能完成”。一个 Android 对齐功能只有同时满足以下条件，才可以标记完成：

1. App 内有可发现入口，且未配置服务器、加载中、空态、失败态、成功态都可见。
2. iOS 调用真实后端或真实 WebSocket 协议，不能只写本地假数据。
3. 请求体、响应解析、鉴权、错误提示和重试/刷新策略都明确。
4. 与 Android 相同的关键状态在 iOS 有等价表达；iOS 做不到的系统能力必须写明平台限制和替代交互。
5. Deep link、Dynamic Island、通知、未读状态与该功能相关时必须闭环，不允许只做页面。
6. 验收必须包含 UI 结果、后端请求、状态变化、失败路径和至少一个回归测试证据。
7. 若某项 Android 代码中存在但当前 Android UI 没有暴露，不能悄悄塞进或删出范围；必须在文档中说明是否纳入本次 iOS parity。

本文以 Android 当前用户可触达的 App / 悬浮球 / 浮层 / Web 工作台入口为功能基准。`AssistantApiClient.createAssistantDraft` 等 Android API helper 当前没有被 `FloatingBallService` UI 调用，不作为本轮 iOS parity 必做项；若后续 Android UI 暴露该能力，iOS 需按同一规则补齐。

## 非目标

1. 不做 Android 悬浮球的像素级复刻。
2. 不在 iOS 上实现系统级全局悬浮窗，因为 iOS 不允许第三方 App 常驻覆盖其他 App。
3. 不在第一阶段重写后端业务逻辑，只在缺少 iOS 调用所需字段或 CORS / deep link 支持时做最小补充。
4. 不把敏感私有内容默认放入 APNs payload。敏感内容仍由用户开关决定。
5. 不以“模拟器无法验证 APNs”为理由跳过真机验收；模拟器可验证的部分和真机必验部分要分别记录。

## Android 功能基准

基准来自以下 Android 文件：

- `android_app/app/src/main/java/com/par/assistant/android/MainActivity.java`
- `android_app/app/src/main/java/com/par/assistant/android/FloatingBallService.java`
- `android_app/app/src/main/java/com/par/assistant/android/AssistantApiClient.java`
- `android_app/app/src/main/java/com/par/assistant/android/RealtimeClient.java`
- `android_app/app/src/main/java/com/par/assistant/android/StreamingAsrClient.java`
- `android_app/app/src/main/java/com/par/assistant/android/WebWorkspaceActivity.java`
- `android_app/app/src/main/java/com/par/assistant/android/CareerBoardPresenter.java`

Android 已有能力：

1. 主 App：保存服务器、测试连接、启动 Nomi、打开完整工作台。
2. 悬浮球：点按开关面板、拖拽吸边、未读角标、长按语音、主动消息气泡。
3. 浮层聊天：聊天历史恢复、上下文 delta、实时流式回复、HTTP fallback、错误显示。
4. 主动消息：WebSocket 收 `proactive_message`、`agent_task_delivery`、`agent_task_fallback`，气泡和通知提醒，点击进入建议页面或任务上下文。
5. 建议：新增建议卡片，完成、忽略，失败提示；实时通道不可用时 60 秒轮询 `/api/suggestions`，使用 dedupe 避免重复提醒。
6. 设置浮层：返回聊天、求职看板、登录账号、渠道说明。
7. 账号与身份：读取 Collector 状态、读取 Nomi 自有身份、展示 Gmail / WhatsApp / Telegram / Calendar / Search / Bookmark / Focus / Shopping 等渠道。
8. 授权与远程浏览器：Composio 授权链接、`nomi://composio/connected` 回调、远程浏览器导航请求、打开服务器 Web 工作台。
9. 求职看板：读取职业画像、岗位、简历草案、申请状态，支持“标记已投递”和“忽略”。
10. 语音：`/ws/voice` 流式 ASR，按住说话、松开发送、取消、低置信度确认，支持 `voice_cancelled` 和错误事件。
11. Web 工作台：Android WebView 打开服务器页面，并在页面完成加载后注入 `localStorage["par-password"]`。

## 当前 iOS 差距

| 功能面 | Android 状态 | 当前 iOS 状态 | 差距 |
| --- | --- | --- | --- |
| 常驻入口 | 悬浮球 + badge + 气泡 | Live Activity 基础可用 | 未读、主动消息、目标跳转尚未完整串起 |
| 聊天 | 历史、实时流、fallback、上下文 | HTTP 发送为主 | 缺历史恢复、实时 UI 消费、fallback、上下文增量 |
| 建议 | 真实列表 + done/dismiss | 占位页面 | 缺真实数据和操作 |
| 主动消息 | WebSocket 气泡 + 通知 | Parser 有，UI 未消费 | 缺 App 状态、列表注入、灵动岛状态 |
| 任务事件 | agent_task_delivery/fallback 包装成主动消息 | Parser 有部分事件 | 缺 Tasks mode、任务详情、任务操作和跳转 |
| 账号 | 账号状态和身份列表 | 缺失 | 缺模型、API、UI、授权入口 |
| 授权/浏览器 | Composio + remote browser + workbench + callback | 缺失 | 缺打开完整工作台、授权、回调和远程浏览器 |
| 求职 | 看板 + 操作 | 只有 deep link route | 缺 API、UI、操作 |
| 语音 | 长按悬浮球 ASR | 缺失 | 缺 iOS 录音、语音 WebSocket、发送链路 |
| 设置 | 主 App + 面板设置 | Settings 有 Live Activity 设置 | 缺连接测试、功能入口聚合 |
| 通知/APNs | 前台浮层 + Android 通知 | iOS 设置字段有，普通 device token 为空 | 缺通知授权、普通 APNs token 注册和 fallback 验收 |

## iOS 产品形态

### 总体结构

iOS 使用一个简单 Nomi 工作台作为 App 首屏。工作台不追求 Android 浮层视觉一致，但保留 Android 浮层的信息架构。

根结构必须落到以下形态：

- `NomiWorkbenchView`
  - Header：Nomi 名称、连接状态、未读数、打开完整工作台按钮、设置入口。
  - Mode switch：Chat、Suggestions、Tasks、Accounts、Career、Settings。
  - Content：当前 mode 内容。
  - Composer：Chat mode 显示文字输入和语音按钮；其他 mode 可隐藏或折叠。

首屏必须表现为单一 `NomiWorkbenchView`。实现内部可以继续用状态枚举或子 view 组合，但用户不能再看到分散的占位 Tab。用户打开 App 或点击灵动岛时，应直接看到 Nomi 工作台，并根据 deep link 聚焦到对应 mode。

### iOS 替代 Android 悬浮球

Android 的系统级悬浮球在 iOS 上不能实现。iOS 替代如下：

| Android | iOS 替代 |
| --- | --- |
| 悬浮球常驻入口 | Live Activity / Dynamic Island + 通知 |
| 悬浮球未读角标 | Live Activity `unreadCount`，App 内 Header badge |
| 主动消息气泡 | Dynamic Island 展开态、锁屏 Live Activity、通知 |
| 点气泡进建议 | Deep link `nomi://suggestion?id=...` |
| 长按悬浮球说话 | App 内语音按钮，支持按住说话和松开发送 |
| 打开完整工作台 | App 内按钮打开服务器 Web 工作台 |
| 关闭外部授权后回到账号状态 | iOS deep link callback 回 App 后刷新 Accounts |

## 功能设计

### 1. Server Setup

目标：iOS 对齐 Android 主 App 的“保存并测试连接、启动 Nomi、打开完整工作台”。

设计：

- `ServerConfig` 继续保存 base URL 和 password。
- 保存后执行连接测试：
  - `GET /health`
  - `GET /api/model/status`
- 成功后注册 iOS device：
  - `POST /api/ios/devices/register`
- Header 显示：
  - `Server not configured`
  - `Testing connection`
  - `Server connected`
  - `Server reachable but password invalid`
  - `Server sync failed: <reason>`
- 完整工作台按钮打开：
  - `${baseURL}#chat`
  - 建议深链打开 `${baseURL}#suggestions`
  - 远程浏览器打开 `<scheme>://<host>:6080/vnc.html?...`，与 Android `ConfigPrefs.remoteBrowserUrlFor` 规则一致。
- iOS 完整工作台必须优先使用 App 内 `WKWebView`，不要默认丢到 Safari：
  - 页面加载完成后注入 `localStorage.setItem("par-password", password)`，对齐 Android `WebWorkspaceActivity`。
  - 只允许加载当前配置服务器的 origin 和远程浏览器 URL；外部 OAuth / Composio 页面转 Safari 或 `SFSafariViewController`。
  - 如果 WebView 注入失败，UI 必须显示“工作台登录注入失败”，不能假装已打开成功。
- remote browser URL 生成规则：
  - 取 `baseURL` 的 scheme 和 host。
  - 端口固定为 `6080`。
  - path 为 `/vnc.html`。
  - query 为 `?autoconnect=1&resize=scale&quality=6&compression=2&show_dot=1`。

验收：

- 输入服务器和密码后，UI 状态从保存中变为连接成功或明确失败。
- 后端收到 iOS device registration。
- 打开完整工作台能进入服务器 Web UI。
- Web 工作台打开后不需要用户手动再输入 `par-password`。
- remote browser URL 与 Android 生成结果一致。

### 2. Chat

目标：iOS 聊天能力不低于 Android 浮层聊天。

设计：

- 新增 `NomiChatStore` 或等价状态容器，负责：
  - 当前 conversation id。
  - 消息列表。
  - pending assistant message。
  - streaming buffer。
  - client context delta。
  - loading/error/status。
- client context delta 必须对齐 Android `FloatingChatContext.snapshotDelta(12000)` 的语义：
  - 记录本地最近的 user / assistant turn。
  - 发送前生成 delta，不包含当前待发送 user message 的重复项。
  - token/字符预算上限为约 12000 字符级别，超出时保留最近上下文。
  - HTTP 请求使用 `client_context_delta`；WebSocket 流式通道当前后端不会消费该字段时，必须记录 gap，并确保 HTTP fallback 带上该字段。
- 新增或扩展 API：
  - `GET /api/chat/history?limit=80`
  - `GET /api/chat/history?conversation_id=<id>&limit=80`
  - `POST /api/chat`
- 优先使用实时 WebSocket：
  - `/ws?password=...`
  - 发送 `chat_message`
  - 字段包含 `client_type=ios`、`client_request_id`、`conversation_id`、`ios_live_activity_id`、`ios_stream_to_live_activity`
- 实时失败或超时后 fallback 到 HTTP `POST /api/chat`。
- fallback 触发条件：
  - WebSocket 未连接或发送失败。
  - 发送后在固定超时内没有收到任何 `chat_delta` 或 `chat_done`。
  - WebSocket 返回 `error`。
  - App 进入不适合继续 streaming 的状态时，可取消 streaming 并 HTTP fallback。
- fallback 不应重复添加用户消息，应该更新同一个 pending assistant bubble。
- 每次 chat stream 第一片要重置 Live Activity 累计文本，避免连续消息串联。
- HTTP 和 realtime 都要更新同一份 conversation id。
- 历史加载必须具备并发保护：
  - 进入 Chat 时记录当前本地消息数量。
  - 如果历史请求返回前用户已发送新消息，不得用远端历史覆盖本地新消息。
  - 若历史返回为空，保留本地欢迎语和现有消息。
- `client_request_id` 必须复用同一个 id 贯穿 realtime 和 HTTP fallback，用于后端幂等。

UI：

- Chat mode 默认显示历史消息。
- 空态文案接近 Android：“我在这里。你可以直接发消息，也可以打开完整工作台。”
- 用户消息和 Nomi 消息用不同背景，但不要求完全复刻。
- 输入框提示：“和 Nomi 说点什么”。
- 发送按钮使用纸飞机图标，并提供 accessibility label “发送”。
- 发送中显示“正在思考...”。
- 实时 delta 到达时逐步更新 pending bubble。

验收：

- 首次进入能加载历史。
- 发送消息后后端收到 `client_type=ios`。
- realtime 可用时 UI 逐字或逐片更新。
- realtime 超时后 fallback 到 HTTP，最终只出现一条 Nomi 回复。
- 连续发送两条消息，灵动岛和 UI 不串上一条回复。
- 服务端失败时 pending bubble 显示可读错误。
- 历史请求返回前发送新消息，不覆盖新消息。
- HTTP fallback 请求里能看到非空 `client_context_delta`，或在后端尚不支持时明确记录该 gap。

### 3. Suggestions 和 Proactive Messages

目标：iOS 真实承接 Android 的主动建议能力，而不是占位页。

设计：

- `SuggestionListView` 改为真实列表。
- 新增 `NomiSuggestionStore`，负责：
  - 初次加载。
  - 下拉或按钮刷新。
  - 轮询 fallback。
  - WebSocket 注入。
  - dedupe。
  - unread count。
  - deep link focus。
- API：
  - `GET /api/suggestions`
  - `PATCH /api/suggestions/{id}`，body `{ "status": "done" }`
  - `PATCH /api/suggestions/{id}`，body `{ "status": "dismissed" }`
- 轮询 fallback：
  - 当 `/ws` 未连接、断开、鉴权失败或持续错误时，启动 60 秒轮询。
  - 轮询调用 `GET /api/suggestions?limit=20`。
  - 使用 suggestion id dedupe，已经展示或用户已处理的建议不重复增加未读。
  - `/ws` 恢复后可以停止轮询，或保留低频轮询但不能重复提醒。
- WebSocket `proactive_message` 到达后：
  - 加入 suggestions store 顶部。
  - unread count 加一。
  - 更新 Live Activity state。
  - 如通知 fallback 开启，触发本地通知或 APNs fallback。
- WebSocket `agent_task_delivery` 和 `agent_task_fallback` 到达后：
  - 作为 task card 进入 Tasks mode。
  - 同时可在 Suggestions/Proactive inbox 中显示一条提醒卡，source 为 `long_tail_agent`。
  - unread count 加一。
  - 更新 Live Activity state。
- Deep link：
  - `nomi://suggestion?id=<id>` 打开工作台 Suggestions mode，并滚动或高亮该建议。

UI：

- 建议卡片展示 title、body、source、priority。
- 每张卡有“完成”和“忽略”操作。
- 空态：“暂无建议”。
- 错误态：“无法读取建议：<reason>”。
- 点击灵动岛主动消息后进入对应建议。

验收：

- 假后端返回建议时 UI 显示列表。
- 完成/忽略发送 PATCH，成功后卡片移除或状态更新。
- WebSocket 主动消息会出现在建议列表顶部。
- 灵动岛点击能定位到建议。
- `/ws` 不可用时，轮询发现新建议后也能进入列表、未读和通知。
- 同一 suggestion id 通过 WebSocket 和轮询同时到达时，只出现一张卡。

### 4. Dynamic Island / Live Activity

目标：iOS 常驻入口要承担 Android 悬浮球的入口、未读和主动提醒职责。

状态设计：

- `idle`：Nomi ready。
- `chat_streaming`：Nomi 正在回复。
- `proactive_message`：收到主动建议。
- `task_delivery`：长任务有交付。
- `voice_listening`：正在听。
- `voice_recognizing`：正在识别。
- `error`：需要用户打开 App 处理。

ContentState 应包含：

- phase
- title
- body
- source
- suggestionId
- taskId
- conversationId
- unreadCount
- partialAnswer
- tokenSequence
- payloadMode
- deepLink
- truncated
- privateContext

隐私策略：

- 默认 safe mode：不把 Gmail / WhatsApp 原文、联系人、私密上下文放入 APNs payload。
- 用户打开敏感内容开关后，允许在 Live Activity / APNs payload 中显示部分文本。
- token 级别 chat stream 仍由用户开关控制。
- payload 长度受 `maxSensitivePayloadChars` 限制。

点击策略：

- chat：`nomi://chat?conversation_id=<id>`
- suggestion：`nomi://suggestion?id=<id>`
- task：`nomi://task?id=<id>`
- settings：`nomi://settings/live-activity`

APNs 与通知 fallback：

- iOS 必须区分三类 token：
  - 普通 APNs device token：来自 `UIApplicationDelegate.didRegisterForRemoteNotificationsWithDeviceToken`，用于普通通知 fallback。
  - Live Activity update token：来自 ActivityKit 单个 activity，用于更新已存在的 Live Activity。
  - Live Activity push-to-start token：用于服务端启动 Live Activity，若当前工程暂不使用 push-to-start，也要保留字段并写入空值原因。
- 开启 Notification fallback 时，必须请求 `UNUserNotificationCenter` 权限，并调用 `UIApplication.shared.registerForRemoteNotifications()`。
- `POST /api/ios/devices/register` 不能再长期发送空 `apns_device_token`：
  - 真机授权成功后必须上传十六进制 device token。
  - 用户拒绝通知时上传空值，并在 Settings 显示“通知权限未开启，APNs fallback 不可用”。
  - 模拟器无法拿到真实 APNs token 时，测试记录必须标记为模拟器限制，不能把该项判定为完成。
- `POST /api/ios/live-activities/register` 必须上传 `activity_id` 和 update token。update token 轮换时要重新注册。
- Live Activity update 失败且后端 settings `notification_fallback_enabled=true` 时，后端只有拿到普通 `apns_device_token` 才能走 `send_alert`；iOS UI 必须暴露这个前置条件。
- 前台收到主动消息时，App 内状态必须更新；后台由 Live Activity/APNs 承接。不得只依赖通知作为数据源。

内容策略：

- `safe` 模式：
  - proactive：显示通用标题和摘要，不显示联系人、邮箱地址、手机号、原文片段。
  - chat streaming：默认只显示“Nomi 正在回复”，不逐 token 显示正文。
  - task：显示“长尾任务完成”或“任务需要处理”，不暴露外部账号细节。
- `sensitive` 模式：
  - 只在用户显式开启后允许显示正文、联系人或 raw private context。
  - 必须受 `maxSensitivePayloadChars` 截断。
  - `truncated=true` 时 UI 应用省略提示，不能让用户误以为是完整内容。
- token streaming：
  - `token_level_chat_streaming_enabled=false` 时，`chat_delta` 不推 APNs。
  - `token_level_chat_delivery=local_only` 时，只更新本机 Activity，不经 APNs。
  - `apns_best_effort` 或 `local_and_apns_best_effort` 才允许调用后端 token-level APNs 更新。

未读策略：

- 收到 `proactive_message`、`agent_task_delivery`、`agent_task_fallback` 时 unreadCount 加一。
- 用户从 deep link 进入对应 suggestion/task 并看到目标卡片后，清除该目标未读。
- 用户进入 Suggestions 或 Tasks mode 时，只清除当前列表中已展示项的未读，不清除尚未加载或加载失败的项。
- Chat stream 的未读只在 App 不在前台 Chat mode 时增加；用户进入对应 conversation 后清除。

验收：

- 后台时 Dynamic Island 紧凑态能显示 Nomi 状态。
- 展开态安全模式不泄漏敏感正文。
- 展开态敏感模式按用户设置显示文本。
- 点击进入正确 mode。
- 连续 chat stream 不重复拼接上一条内容。
- 真机授权通知后，`POST /api/ios/devices/register` payload 中有非空 `apns_device_token`。
- 关闭通知权限时，Settings 明确显示 APNs fallback 不可用。
- Live Activity update token 注册成功后，后端能通过该 token 更新 proactive/task 状态。
- 模拟器测试报告必须把普通 APNs fallback 标记为未覆盖的真机项。

### 5. Tasks

目标：iOS 不能只解析 `agent_task_delivery` / `agent_task_fallback`，还要能让用户查看任务、处理阻塞、继续或取消任务。

事件来源：

- WebSocket `/ws`：
  - `agent_task_delivery`
  - `agent_task_fallback`
- Web 工作台 pending event：
  - Android 会把 `nomi-pending-agent-event` 注入 WebView localStorage。
  - iOS 工作台打开服务器 Web UI 时也必须支持把当前 task event 以等价方式注入，字段名保持 `nomi-pending-agent-event`。

API：

- `GET /api/agent-tasks/{taskId}`
- `GET /api/agent-tasks/{taskId}/events`
- `POST /api/agent-tasks/{taskId}/resume`
- `POST /api/agent-tasks/{taskId}/cancel`
- `POST /api/agent-tasks/{taskId}/human-input`
- `POST /api/agent-tasks/{taskId}/external-effects/{effectId}/confirm`
- `POST /api/agent-tasks/{taskId}/external-effects/{effectId}/execute`
- `POST /api/agent-tasks/{taskId}/external-effects/{effectId}/rollback`
- `POST /api/agent-tasks/{taskId}/external-effects/{effectId}/compensation/confirm`

状态容器：

- 新增 `NomiTaskStore`，负责：
  - 从 WebSocket 原始事件创建或更新 task card。
  - 打开 Tasks mode 时拉取任务详情和事件时间线。
  - 保存 `taskId`、`eventId`、`eventType`、`title`、`body`、`rawJson`、`requiresUserAction`、`lastUpdatedAt`。
  - 对同一 `taskId + eventId` dedupe。
  - 将 task unread 汇总给工作台 Header 和 Live Activity。
- `agent_task_delivery`：
  - 默认标题为“长尾任务完成”。
  - body 使用 `delivery.message`；为空时用“长尾任务有新的交付结果。”。
  - 卡片主操作为“查看结果”。
- `agent_task_fallback`：
  - 优先读取顶层 `action_card`，其次读取 `fallback_decision.action_card`。
  - 默认标题为“长尾任务需要处理”。
  - body 使用 action card message；为空时用“任务已暂停，请查看下一步。”。
  - 卡片主操作为“处理下一步”。

UI：

- Tasks mode 展示任务提醒列表，按更新时间倒序。
- 每张卡显示来源 `long_tail_agent`、状态、标题、摘要和操作按钮。
- 任务详情页或详情区域显示事件时间线。
- 支持操作：
  - 查看结果。
  - 继续任务。
  - 取消任务。
  - 提交人工输入。
  - 确认或拒绝 external effect。
  - 打开完整 Web 工作台查看复杂任务。
- 复杂任务在 App 内无法完整表达时，必须提供“打开完整工作台”，并把当前 task event 注入 WebView，不能只显示“请到网页处理”。

Deep link：

- `nomi://task?id=<taskId>`
- `nomi://task?id=<taskId>&event_id=<eventId>`

验收：

- 发送 `agent_task_delivery` 后，Tasks mode 出现交付卡，Suggestions/Proactive inbox 可见提醒，Live Activity 状态为 `task_delivery`。
- 发送 `agent_task_fallback` 后，Tasks mode 出现待处理卡，卡片标题/body 来自 action card。
- 点击 Dynamic Island task deep link 进入 Tasks mode 并高亮对应 task。
- 同一 task event 通过 WebSocket 重放两次，只显示一张卡。
- 点击继续/取消/提交输入/确认 effect 时，iOS 发起对应真实 API 请求，并根据响应刷新任务详情。
- API 失败时卡片保留，显示失败原因和重试入口。
- 打开 Web 工作台处理 task 时，WebView localStorage 中存在 `nomi-pending-agent-event`。

### 6. Accounts 和 Assistant Identities

目标：iOS 对齐 Android 设置中的“登录账号”。

API：

- `GET /api/collectors/status`
- `GET /api/integrations/composio/toolkits?session_kind=readonly`
- `GET /api/integrations/composio/toolkits?session_kind=write`
- `GET /api/assistant-identities`

数据模型：

- `CollectorStatus`
  - source
  - enabled
  - paused
  - healthStatus
- `AssistantIdentity`
  - identityId
  - kind
  - displayName
  - address
  - status
- `AccountChannel`
  - source
  - name
  - description
  - opensBrowser
  - route kind

渠道列表需覆盖 Android：

- Gmail
- WhatsApp Web
- Telegram Web
- Google Calendar
- Google Search
- Chrome Bookmarks
- 浏览行为
- 购物/电商

路由规则对齐 Android：

- Gmail、Google Calendar 走 Composio connect。
- iOS 路由 helper 还要覆盖 Android `AccountChannelRoute` 已支持的扩展 Composio slug：`googledrive`、`googledocs`、`googlesheets`、`googletasks`、`github`、`slack`、`notion`。这些扩展渠道未出现在当前 Android 面板时，不强制展示在首屏，但 deep link 或后端返回对应 source 时不能走错路由。
- WhatsApp、Telegram、Search、Shopping 走 remote browser。
- Bookmark、Focus 属于 local only。

状态合并规则：

- collector 状态和 Composio toolkit 状态必须合并到同一 `AccountChannel`，不能重复显示两个 Gmail。
- collector `enabled=true && paused=false && healthStatus=healthy` 时，渠道 badge 为“正常”，点击不应重复打开授权。
- collector degraded / paused / disabled 时，显示可读状态，并允许重新授权或打开修复入口。
- Composio readonly/write 两种 session 均可返回状态；UI 至少显示“读取已连接”“写入已连接”“需要授权”三类状态。
- Nomi 自有身份来自 `/api/assistant-identities`；接口不可用时 Accounts mode 仍显示渠道状态，并给身份区域显示失败态。

UI：

- Accounts mode 显示 Nomi 身份。
- 支持的登录渠道显示状态 badge：
  - 正常
  - 待登录
  - 异常
  - 暂停
  - 已停用
  - 本地
  - 间接
- 点击需要登录的渠道触发授权或远程浏览器。
- 外部授权返回 `nomi://composio/connected` 后，Accounts mode 顶部显示一次性状态消息，并自动刷新状态。

验收：

- iOS 能读取账号状态和身份。
- Gmail 正常状态不重复打开授权。
- degraded 的 Gmail 可生成授权链接并打开。
- WhatsApp / Telegram 可请求远程浏览器导航并打开浏览器页面。
- callback `nomi://composio/connected?toolkit=gmail&status=connected` 能唤起 App、切回 Accounts mode、显示连接结果并刷新 Gmail 状态。
- collector 状态和 Composio 状态合并后不重复出现同一渠道。

### 7. Auth / Remote Browser / Web Workbench

目标：iOS 保留 Android 的外部授权和服务器浏览器能力。

API：

- `POST /api/integrations/composio/connect/{slug}`
- `GET /api/integrations/composio/callback`
- `POST /api/browser/open`

设计：

- Composio 授权：
  - 请求后端 connect URL。
  - 用 `ASWebAuthenticationSession` 打开，callback scheme 为 `nomi`。
  - 如果 `ASWebAuthenticationSession` 不可用，降级为 `SFSafariViewController`，但仍必须注册并处理 `nomi://composio/connected`。
  - 返回 App 后解析 toolkit/status/message，切到 Accounts mode 并刷新。
  - 后端返回授权 URL 为空或 4xx 时，UI 显示失败原因，不打开空白浏览器。
- Remote browser：
  - 先调用 `/api/browser/open`，body `{ "source": "<source>" }`。
  - 再打开 remote browser URL：`<scheme>://<host>:6080/vnc.html?autoconnect=1&resize=scale&quality=6&compression=2&show_dot=1`。
  - remote browser 默认使用 App 内 `WKWebView`，提供 Done/Close 回到 Accounts。只有当 WebView 加载 noVNC 不可用并有明确测试证据时，才允许降级到 `SFSafariViewController`，且必须记录 gap。
  - `/api/browser/open` 失败时仍可打开 remote browser URL，并在页面上方显示“导航请求失败，浏览器已打开”。
- Web workbench：
  - 打开 `${baseURL}#chat`、`${baseURL}#suggestions` 等 hash。
  - 使用 App 内 `WKWebView`，配置 JavaScript 和 DOM storage。
  - `didFinish` 后注入 `localStorage.setItem("par-password", password)`。
  - 打开 suggestion/task deep link 时，分别注入：
    - `localStorage["nomi-pending-proactive"]`
    - `localStorage["nomi-pending-agent-event"]`
  - WebView 只允许当前服务器 origin 和 remote browser origin；其他外链转交系统浏览器。
  - WebView 注入失败时页面必须显示错误条，并提供重试注入按钮。

Deep link：

- `nomi://composio/connected`
- `nomi://composio/connected?toolkit=<slug>&status=<status>&message=<urlencoded>`
- `nomi://workbench?route=chat`
- `nomi://workbench?route=suggestions`
- `nomi://workbench?route=task&task_id=<id>`

验收：

- 生成授权链接失败时 UI 显示原因。
- 外部授权返回后 Accounts 自动刷新或提供刷新按钮。
- remote browser 导航失败时仍可打开浏览器页面，并显示导航失败提示。
- Web 工作台无需用户手动输入 `par-password`。
- suggestion/task 打开 Web 工作台后，对应 localStorage pending payload 存在。
- 外部 OAuth 页面不会被误拦在受限 WebView 中。

### 8. Career Board

目标：iOS 对齐 Android 求职看板。

API：

- `GET /api/career/board?limit=50`
- `PATCH /api/career/applications/{applicationId}`

数据模型：

- `CareerProfile`
- `JobOpportunity`
- `ResumeVersion`
- `JobApplicationState`
- `CareerBoardAction`

Presenter 对齐 Android `CareerBoardPresenter`：

- 有职业画像时显示 headline、目标、技能。
- 每个 opportunity 显示岗位、公司、状态、地点、要求、简历草案、申请状态、下一步。
- 无岗位但有 applications 时显示申请状态。
- 空态：“还没有求职数据...”。
- 可执行操作：
  - 标记已投递
  - 忽略

Deep link：

- `nomi://career/opportunity?id=<id>` 打开 Career mode 并聚焦岗位或申请。

操作请求：

- 标记已投递：
  - `PATCH /api/career/applications/{applicationId}`
  - body 包含 `status` 或 `stage` 的已投递状态，以及必要的 `user_note`。
- 忽略：
  - `PATCH /api/career/applications/{applicationId}`
  - body 标记 ignored / dismissed，并保留必要原因。
- iOS 不确定后端字段枚举时，不得猜测提交；实现前必须以 Android `CareerBoardPresenter` / `AssistantApiClient` 当前请求体为准写测试。

验收：

- 加载中、空态、失败态都可见。
- 返回数据后展示 cards。
- 点击“标记已投递”发送 PATCH 并刷新看板。
- 点击“忽略”发送 PATCH 并刷新看板。
- deep link 进入后能聚焦目标 opportunity/application。
- PATCH 失败时原卡片不消失，并显示失败原因。

### 9. Voice

目标：iOS 不删除 Android 的语音功能。

iOS 替代交互：

- App 内 Chat composer 右侧提供麦克风按钮。
- 支持两种交互：
  - 按住说话，松开发送。
  - 点按进入录音，再点按结束。这个作为辅助以适配 iOS 可访问性。
- 录音期间工作台显示：
  - 正在连接语音识别
  - 正在听
  - 识别中
  - 我听到的是：<text>，确认发送
  - 已取消语音输入

协议复用 Android：

- WebSocket：`/ws/voice?password=<password>`
- start payload：
  - type: `voice_start`
  - session_id
  - client_type: `ios_workbench_voice`
  - language_hint: `zh-CN`
  - audio: `pcm_s16le`、16000 Hz、1 channel、200 ms frame
  - conversation_id 可选
- audio payload：
  - type: `audio_chunk`
  - session_id
  - seq
  - captured_at_ms
  - audio_base64
- end payload：
  - type: `voice_end`
  - session_id
  - last_seq
- cancel payload：
  - type: `voice_cancel`
  - session_id
  - reason
- server events：
  - `voice_ready`
  - `asr_partial`
  - `asr_final`
  - `voice_cancelled`
  - `voice_error`

音频约束：

- iOS 必须用 `AVAudioEngine` 或等价方案采集麦克风。
- 发送给后端前必须转换为：
  - PCM signed 16-bit little-endian。
  - 16000 Hz。
  - mono。
  - 约 200 ms 一帧。
- 不允许直接发送 AAC、m4a、float32 或设备原始采样率给 `/ws/voice`。
- `seq` 从 1 开始单调递增；重连或新 session 重新从 1 开始。
- 单帧 base64 长度不得超过后端限制，默认上限约 24576 chars；decoded chunk 默认不超过 16384 bytes。
- 默认最长录音 60 秒；超时必须自动结束或提示用户重试。
- `voice_cancelled` 到达时 UI 状态变为“已取消语音输入”，并且不得发送 chat。
- `voice_error` 需区分 microphone、network、server、format、out_of_order、chunk_too_large、session_mismatch 等用户可理解错误。

置信度策略：

- `confidence >= 0.78`：自动进入 Chat 发送链路。
- `0.55 <= confidence < 0.78`：展示确认发送。
- `confidence < 0.55`：不发送，提示重新说一遍。
- 最终文本必须通过 Chat 的同一发送函数发送，复用 conversation id、context delta、realtime/fallback 和 Live Activity 逻辑。

Live Activity：

- 录音时 phase 为 `voice_listening`。
- 松手后 phase 为 `voice_recognizing`。
- 低置信度时不自动发送，App 内展示确认。

验收：

- 未授权麦克风时提示授权。
- 授权后能发起 `/ws/voice`。
- partial 文本实时显示。
- high confidence final 自动进入 chat send。
- medium confidence final 显示确认发送。
- cancel 不发送 chat。
- 后端返回 `voice_cancelled` 时 UI 不残留“识别中”。
- 发送的 audio payload 可被测试断言为 16k mono pcm_s16le，且 seq 连续。
- 超过最大时长会自动结束或提示，不会无限录音。

### 10. Settings

目标：保留当前 iOS Live Activity / 隐私设置，并补足 Android 主 App 配置能力。

Settings mode 分区：

- Server
  - Base URL
  - Password
  - Save and test connection
  - Server status
- Assistant
  - Start / Stop Live Activity
  - Open Web Workbench
  - Refresh data
- Dynamic Island
  - Show Nomi in Dynamic Island
  - Open target page when tapping Dynamic Island
  - Notification fallback
  - Notification permission status
  - APNs device token registration status
  - Live Activity update token registration status
- Token streaming
  - Stream every reply token
  - Delivery mode
- Private APNs payloads
  - Allow private content in APNs
  - Include message body
  - Include contact names
  - Include raw private context
  - Payload limit
- Diagnostics
  - Test health
  - Test model status
  - Test Web workbench injection
  - Test remote browser URL
  - Re-register iOS device
  - Re-register Live Activity

验收：

- Settings 保存后 device registration 和 settings sync 都发生。
- 重启 App 后设置持久化。
- 关闭 Live Activity 后灵动岛消失或进入停止态。
- 开启 deep link 后点击灵动岛进入目标 mode。
- 通知权限、APNs token、Live Activity token 三个状态可分别看到。
- Web workbench injection test 能显示成功或具体失败原因。

## 组件与模块边界

建议新增或整理以下 iOS 模块：

1. `NomiWorkbenchView`
   - 根 UI shell。
   - mode 状态和页面切换。
   - 只负责布局和交互转发，不直接发网络请求。

2. `NomiWorkbenchStore`
   - 聚合 chat、suggestions、tasks、accounts、career、connection、unread 状态。
   - 可以内部组合多个 feature store，但根 view 不应直接写任何网络逻辑。
   - 负责 mode 切换、deep link focus、Header badge 汇总。

3. `NomiChatStore`
   - 聊天历史、发送、streaming、fallback、context delta。
   - 管理 conversation id、client request id、pending assistant bubble、历史加载并发保护。

4. `NomiSuggestionStore`
   - 建议加载、done/dismiss、proactive 注入、focus。
   - 管理 60 秒轮询 fallback、dedupe、unread。

5. `NomiTaskStore`
   - task delivery/fallback 事件入库。
   - task 详情、事件时间线、继续/取消/人工输入/external effect 操作。
   - 管理 task deep link、unread、Web 工作台 pending event 注入数据。

6. `NomiAccountsStore`
   - 身份、渠道状态、授权入口。
   - 合并 collectors、Composio readonly/write toolkits、assistant identities。

7. `NomiAccountChannelRouter`
   - 对齐 Android `AccountChannelRoute`。
   - 负责 source 到 Composio / remote browser / local only 的映射。

8. `NomiCareerStore`
   - 求职看板加载和操作。
   - PATCH 请求体必须由测试锁定，不允许凭 UI 文案猜字段。

9. `NomiVoiceController`
   - AVAudioSession、PCM 转换、`/ws/voice` 协议。
   - 负责 16k mono pcm_s16le、seq、时长限制、置信度策略。

10. `NomiApiClient`
   - 继续作为 HTTP API 层。
   - 补齐 Android 已用接口。
   - 每个方法要有单元测试覆盖 path、method、auth header、body。

11. `NomiRealtimeClient`
   - 连接 `/ws`。
   - 输出 proactive、task、chat delta、chat done、error。
   - 支持 3 秒 reconnect 或明确失败态。
   - 连接失败时通知 `NomiSuggestionStore` 启动轮询 fallback。

12. `NomiLiveActivityController`
    - 更新 chat、proactive、task、voice、unread 状态。
    - 控制 safe/sensitive payload。
    - 管理 ActivityKit activity id、update token、点击 deep link。

13. `NomiNotificationRegistrar`
    - 请求通知权限。
    - 注册普通 APNs device token。
    - 同步 `/api/ios/devices/register` 和 settings。
    - 暴露权限/token/fallback 可用性给 Settings。

14. `NomiWebWorkspaceView`
    - `WKWebView` 容器。
    - 注入 `par-password`、`nomi-pending-proactive`、`nomi-pending-agent-event`。
    - 限制可加载 origin，外链转系统浏览器。

15. `NomiDeepLinkRouter`
    - 统一解析 `nomi://...`。
    - 只改变目标 mode/focus，不清空当前工作台状态。
    - 处理 `nomi://composio/connected` callback。

## 后端复用清单

优先复用现有后端：

- `GET /health`
- `GET /api/model/status`
- `POST /api/chat`
- `GET /api/chat/messages`
- `GET /api/chat/history`
- `GET /api/suggestions`
- `GET /api/proactive/suggestions`
- `PATCH /api/suggestions/{id}`
- `POST /api/proactive/suggestions/{suggestionId}/action`
- `GET /api/collectors/status`
- `GET /api/integrations/composio/toolkits`
- `POST /api/integrations/composio/connect/{slug}`
- `GET /api/integrations/composio/status`
- `GET /api/integrations/composio/callback`
- `GET /api/assistant-identities`
- `POST /api/browser/open`
- `GET /api/agent-tasks/{taskId}`
- `GET /api/agent-tasks/{taskId}/events`
- `POST /api/agent-tasks/{taskId}/resume`
- `POST /api/agent-tasks/{taskId}/cancel`
- `POST /api/agent-tasks/{taskId}/human-input`
- `POST /api/agent-tasks/{taskId}/external-effects/{effectId}/confirm`
- `POST /api/agent-tasks/{taskId}/external-effects/{effectId}/execute`
- `POST /api/agent-tasks/{taskId}/external-effects/{effectId}/rollback`
- `POST /api/agent-tasks/{taskId}/external-effects/{effectId}/compensation/confirm`
- `GET /api/career/board`
- `PATCH /api/career/applications/{id}`
- `POST /api/ios/devices/register`
- `PATCH /api/ios/devices/{deviceId}/settings`
- `POST /api/ios/live-activities/register`
- `/ws`
- `/ws/voice`

如发现后端缺字段，按最小改动补齐，不为 iOS 重建平行接口。

## Deep Link 设计

支持：

- `nomi://chat`
- `nomi://chat?conversation_id=<id>`
- `nomi://suggestion?id=<id>`
- `nomi://task?id=<id>`
- `nomi://task?id=<id>&event_id=<eventId>`
- `nomi://career/opportunity?id=<id>`
- `nomi://settings/live-activity`
- `nomi://accounts`
- `nomi://composio/connected`
- `nomi://composio/connected?toolkit=<slug>&status=<status>&message=<urlencoded>`
- `nomi://workbench?route=chat`
- `nomi://workbench?route=suggestions`
- `nomi://workbench?route=task&task_id=<id>`
- `nomi://voice`

路由行为：

- Deep link 只改变工作台 mode 和 focus target。
- 不应丢失当前聊天消息。
- 如果目标数据尚未加载，先显示 loading，再滚动或高亮。
- 如果目标数据加载失败，保留 deep link target，并显示可重试错误。
- 如果用户通过 Dynamic Island 点击进入，必须带上能定位目标的 id；不能只打开 App 首页。

## 验收标准

本节是后续开发和回归测试的最低标准。每个验收项必须记录实际结果、预期结果、证据和 gap。证据可以是 XCTest 断言、模拟后端请求日志、真机截图、Simulator 截图、APNs delivery log、WebSocket 事件日志或手工测试录屏。

不可接受的完成方式：

- 只做 UI 壳，不发真实请求。
- 只验证结构存在，不验证内容展示。
- 只在模拟器验证 APNs fallback。
- 只测试成功路径，不测试失败、空态、权限拒绝、断线重连。
- 后端请求失败时静默吞错。
- 用固定假数据代替 Android 已有真实功能。

### 基础

- App 首屏是 Nomi 工作台，不再有占位 Suggestions。
- 未配置服务器时，所有需要后端的 mode 显示配置入口和明确提示。
- 配置服务器后，Chat、Suggestions、Accounts、Career 都能发起真实请求。
- `GET /health`、`GET /api/model/status`、`POST /api/ios/devices/register` 的请求和响应结果需要可观察。
- 断网、密码错误、base URL 错误分别有不同提示。
- 打开 Web 工作台后无需手动输入 `par-password`。

### Chat

- 加载历史。
- 发送文本消息。
- realtime streaming 可用时优先使用。
- realtime 不返回时 fallback 到 HTTP。
- 上下文 delta 随请求发送。
- 连续消息不串内容。
- 历史加载过程中发送新消息，不被历史响应覆盖。
- WebSocket `error` 会更新 pending bubble 的错误态。
- HTTP fallback 复用同一个 `client_request_id`，最终 UI 只出现一条用户消息和一条 Nomi 回复。
- token-level Live Activity streaming 关闭时，聊天正文不进入 APNs payload。

### Suggestions / Proactive

- 能加载建议。
- 能完成和忽略建议。
- WebSocket proactive message 能进入列表、未读、Live Activity。
- 点击 Live Activity 进入建议。
- `/ws` 断开后 60 秒轮询 `/api/suggestions?limit=20`，发现新建议并 dedupe。
- 同一 suggestion id 经 WebSocket 和轮询重复到达时只显示一次。
- 完成/忽略失败时卡片不消失，显示错误和重试。
- safe mode 下 Dynamic Island 不显示私密原文。

### Tasks

- WebSocket `agent_task_delivery` 创建交付卡。
- WebSocket `agent_task_fallback` 创建待处理卡，并展示 action card 标题/body。
- Tasks mode 能拉取 task detail 和 events。
- 继续、取消、人工输入、external effect confirm/execute/rollback 至少覆盖一个成功和一个失败路径。
- Dynamic Island task 点击进入对应 task，并清除该 task 未读。
- Web 工作台打开 task 时注入 `nomi-pending-agent-event`。

### Accounts / Auth

- 展示身份和渠道。
- 渠道状态和 Android 标签一致。
- Gmail / Calendar 走 Composio。
- WhatsApp / Telegram / Search / Shopping 走 remote browser。
- healthy 渠道不重复打开授权。
- degraded/paused 渠道可重新授权或显示修复入口。
- `nomi://composio/connected` callback 后自动刷新 Accounts。
- collectors 和 Composio 状态合并，不重复展示同一渠道。
- remote browser URL 与 Android `ConfigPrefs.remoteBrowserUrlFor` 生成结果逐字符一致。

### Career

- 加载看板。
- 展示职业画像、岗位、简历、申请状态。
- 能标记已投递和忽略。
- deep link 能聚焦 opportunity/application。
- PATCH 请求体与 Android 当前实现一致。
- 操作失败时卡片保留并提示错误。

### Voice

- 麦克风授权提示。
- `/ws/voice` 连接。
- partial / final UI 更新。
- 自动发送和确认发送路径都可用。
- 取消不会发送。
- 发送音频为 16k mono pcm_s16le，seq 连续。
- `voice_cancelled`、`voice_error` 都有 UI 状态。
- 低置信度不自动发 chat。
- high confidence final 进入同一 Chat send pipeline。

### Dynamic Island

- idle、chat、proactive、task、voice 状态可展示。
- 未读数可见。
- safe mode 不泄漏敏感正文。
- sensitive mode 尊重用户开关。
- 点击进入对应 mode。
- 普通 APNs device token 真机注册成功。
- Live Activity update token 注册成功。
- Live Activity 更新失败时，在有普通 APNs token 的真机上触发通知 fallback。
- 模拟器报告明确列出不能覆盖的 APNs 项。
- 打开对应 mode 后，相关 unread 清除策略正确。

### Regression Evidence

每次完整回归验收必须产出一份本地测试记录，至少包含：

- 测试设备：Simulator 型号、iOS 版本、真机型号、iOS 版本。
- 后端版本：git commit、运行命令、base URL。
- 配置：password 是否正确、通知权限、Live Activity 开关、敏感内容开关、token streaming 开关。
- 每个功能项的步骤、预期、实际、证据路径、结论。
- 所有 gap：
  - gap id。
  - 影响功能。
  - 是平台限制、后端缺口、实现未完成还是测试环境限制。
  - 临时替代方案。
  - 关闭条件。

## 风险与平台限制

1. iOS 无法实现 Android 那样覆盖其他 App 的悬浮窗。只能用 Dynamic Island、Live Activity、通知和 App 内工作台替代。
2. Dynamic Island 可显示内容有限，长文本需要截断。
3. 真正 APNs、Live Activity push token 和普通 device token 需要真机验证，模拟器只能验本地 Live Activity。
4. 普通 APNs device token、Live Activity update token、push-to-start token 容易混淆；实现和测试必须分别记录。
5. Safari 无法像 Android WebView 那样直接注入 localStorage 密码；因此默认使用 App 内 `WKWebView` 承载 Web 工作台。
6. `ASWebAuthenticationSession` callback scheme、Composio redirect URL、iOS URL scheme 三者必须一致，否则外部授权无法回 App。
7. 语音录音需要处理 iOS 音频权限、采样率转换和后台限制。
8. WebSocket 重连和 suggestions 轮询可能造成重复提醒，必须用 id dedupe。
9. 如果后端接口返回结构和 Android 假设不同，iOS 模型需要兼容解析，但不应静默吞错。
10. Career PATCH 字段必须以 Android 当前请求体和后端 schema 为准，不能由文案反推。

## 文档后续

本设计获得确认后，下一步应单独产出实施计划，按 TDD 开发并分阶段验收。建议拆分顺序：

1. Workbench shell + server setup + notification/APNs registration + open Web workbench。
2. Chat history + realtime streaming + HTTP fallback + context delta。
3. Suggestions + proactive + 60 秒 polling fallback + Dynamic Island deep link。
4. Tasks mode + agent task delivery/fallback + task operations + Web task injection。
5. Accounts + auth callback + account channel router + remote browser。
6. Career board + action PATCH + deep link focus。
7. Voice + PCM conversion + `/ws/voice` + confidence gating。
8. Full iOS regression + real-device APNs gap report。

## 自检

- 无未定占位。
- 范围明确：功能完整对齐 Android，UI 简化。
- 平台限制已列出。
- 后端复用点已列出。
- 验收标准覆盖 UI、真实请求、失败路径、deep link、Dynamic Island、通知和真机限制。
- Android 不能在 iOS 原样实现的悬浮窗能力均有替代路径。
- 所有已知 gap 都有关闭条件，后续开发不能用“差不多”跳过验收。
