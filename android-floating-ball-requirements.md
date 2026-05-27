# Android Floating Ball Requirements

更新日期：2026-05-27

本文档记录 Android 悬浮球交付端需求与开发进度。Android 端第一版只作为 Nomi 私有助理的移动入口和主动消息展示层，不做手机端数据采集，不读取短信、通讯录、通知、相册，也不做 Accessibility 自动操作。

## 目标

在本地 Android 模拟器中交付一个可安装的 Android 应用：

- 用户配置 Nomi 服务器地址和访问密码。
- 应用启动一个可拖拽、可吸边的系统悬浮球。
- 点击悬浮球可直接聊天、查看主动消息，并能打开完整 H5 工作台。
- 点击悬浮球可查看支持的账号登录渠道，并进入服务器 noVNC 远程浏览器完成登录。
- Android 端通过 WebSocket 接收后端主动消息，把重要建议展示在 Nomi 悬浮球气泡和系统通知中。

## 第一版范围

- [x] Android 工程骨架
  - 创建独立 Android app 目录。
  - 配置包名、最小 SDK、Manifest、权限声明。
  - 当前状态：已完成代码骨架。
  - 产物位置：`android_app/`。
  - 验证结果：`gradle :app:assembleDebug` 构建成功，生成 `android_app/app/build/outputs/apk/debug/app-debug.apk`。

- [x] 本地 Android 模拟器环境
  - 安装或确认 Android Studio / Android SDK / emulator / adb。
  - 创建一个 Pixel 规格虚拟机。
  - 当前状态：已完成。
  - 已完成：安装 OpenJDK 17、Android command line tools、Gradle、platform-tools、emulator、Android 35 platform、Android 35 Google APIs arm64 system image。
  - 已完成：创建 AVD `PAR_Pixel_API35`，路径为 `~/.android/avd/PAR_Pixel_API35.avd`。
  - 验证结果：`adb devices` 可见 `emulator-5554 device`；新 APK 可安装并启动。

- [x] 服务器配置与登录
  - 输入服务器地址。
  - 输入访问密码。
  - 调用 `/health` 测试连接。
  - 安全保存配置，后续使用 Android Keystore / EncryptedSharedPreferences。
  - 当前状态：代码初版完成，模拟器基础验收通过。
  - 已完成：`MainActivity` 提供服务器地址、访问密码输入，保存后调用 `/health` 测试连接。
  - 已完成：`ServerConfig` 对服务器地址做 http/https 校验、补全和尾部 slash 规范化。
  - 验证结果：`CoreLogicTest` 覆盖地址规范化、非法地址、空密码；测试通过。
  - 遗留问题：当前先用 `SharedPreferences` 保存密码，还没有升级到 Android Keystore / EncryptedSharedPreferences。

- [x] 悬浮球基础能力
  - 申请 `SYSTEM_ALERT_WINDOW` 权限。
  - 前台服务保活。
  - 可拖动、吸边。
  - 点击展开小面板，长按隐藏。
  - 当前状态：代码初版完成，模拟器验收通过。
  - 已完成：Manifest 声明 `SYSTEM_ALERT_WINDOW`、`FOREGROUND_SERVICE`、`POST_NOTIFICATIONS`、`INTERNET`。
  - 已完成：`FloatingBallService` 使用 `TYPE_APPLICATION_OVERLAY` 创建悬浮球，支持拖动、吸边、点击展开、长按关闭。
  - 已完成：前台服务调用 `startForeground` 并创建通知渠道。
  - 验证结果：结构验证脚本通过；Android APK 构建通过；模拟器中可见 Nomi 小人悬浮球，页面关闭后仍保留在 Launcher 上。

- [x] 悬浮小面板聊天
  - 输入文本。
  - 调用 `/api/chat`。
  - 展示回复、加载中、失败状态。
  - 当前状态：代码初版完成，模拟器验收通过。
  - 已完成：悬浮面板改为聊天浮窗，包含当前会话历史、输入框、发送按钮。
  - 已完成：完整工作台入口收为右上角图标，不再占用主聊天区。
  - 已完成：账号登录入口移动到设置二级页。
  - 已完成：`AssistantApiClient.chat` 调用 `/api/chat` 并带 `x-par-password`。
  - 验证结果：结构验证脚本确认 `x-par-password` 存在；Android APK 构建通过；模拟器中主面板只显示聊天历史、输入框和发送按钮，设置页中可展开账号登录渠道。

- [x] 主动消息展示
  - 通过 `/ws` 建立 WebSocket 实时连接。
  - Worker 生成主动建议后通过 Redis pub/sub 推送 `proactive_message`。
  - 本地去重 suggestion id。
  - 悬浮球显示红点或未读数量。
  - Nomi 悬浮球旁展示主动消息气泡。
  - 点击消息气泡进入完整工作台对话页，并把该主动消息带入对话上下文。
  - 支持完成、忽略、稍后提醒。
  - 当前状态：实时通道代码完成，待云服务器部署后做真机链路复验。
  - 已完成：`runtime_api` 提供 `/ws`，鉴权失败会关闭连接，聊天消息通过 `chat_delta` / `chat_done` 流式返回。
  - 已完成：`worker` 在持久化主动建议后发布 Redis 实时消息。
  - 已完成：Android `RealtimeClient` 接入 WebSocket，连接失败后自动重连。
  - 已完成：悬浮球未读数量增加，并在 Nomi 旁展示主动消息气泡。
  - 已完成：建议卡片支持完成、忽略，并调用 `/api/suggestions/{id}`。
  - 验证结果：`runtime_api` / `worker` 相关 70 个测试通过；Android APK 构建通过。
  - 遗留问题：完成、忽略、稍后提醒仍主要在旧建议卡片路径中，气泡直接进入对话页，后续可补气泡快捷操作。

- [x] Android 系统通知
  - 高优先级建议触发通知栏提醒。
  - 通知点击打开悬浮面板或完整工作台。
  - 当前状态：代码初版完成，模拟器验收待完成。
  - 已完成：主动建议到达时调用系统通知。
  - 已完成：通知点击打开完整 H5 工作台。
  - 验证结果：Android APK 构建通过。

- [x] H5 工作台 WebView
  - 打开现有 PAR H5 页面。
  - 复用服务器地址和访问密码。
  - 提供对话、搜索、治理、建议、采集状态完整入口。
  - 当前状态：代码初版完成，模拟器验收待完成。
  - 已完成：`WebWorkspaceActivity` 使用 WebView 加载配置的服务器地址。
  - 已完成：WebView 开启 JavaScript 和 DOM storage，并在页面加载后写入 `localStorage.par-password`。
  - 已完成：完整工作台右上角新增原生关闭按钮，关闭后 Android 页面退到后台，Nomi 悬浮球保持存在。
  - 已完成：H5 工作台接入 `/ws`，对话页优先使用 WebSocket 流式输出，失败时回退 `/api/chat`。
  - 已完成：从 Android 主动消息气泡进入工作台时自动切到对话页，并展示该主动消息。
  - 验证结果：后端 WebSocket 流式测试通过；结构验证脚本通过；Android APK 构建通过；模拟器中打开完整工作台后可见右上角 `×`，点击后 `WebWorkspaceActivity` 消失，焦点回到 Launcher，仍保留 `SYSTEM_ALERT_WINDOW` 悬浮球。
  - 遗留问题：服务器当前部署的 H5 静态页面仍显示 PAR，本地 `runtime_api/app/static/index.html` 已改为 Nomi，需后续部署到服务器生效。

- [x] 账号登录入口
  - 在悬浮面板中展示支持的登录/采集渠道。
  - 渠道列表需要让用户理解当前第一版实际支持范围。
  - 点击需要网页登录的渠道，打开服务器 noVNC 远程浏览器，由用户自己完成账号密码、扫码和二次验证。
  - 当前状态：代码初版完成，模拟器验收待完成。
  - 已完成：悬浮面板新增“登录账号”入口。
  - 已完成：列表展示 Gmail、WhatsApp Web、Telegram Web、Google Calendar、Google Search、Chrome Bookmarks、浏览行为、购物/电商。
  - 已完成：Gmail、WhatsApp Web、Telegram Web、Google Calendar、Google Search、购物/电商点击后打开 `:6080/vnc.html`。
  - 已完成：通过 `/api/collectors/status` 读取 collector 状态，并显示“正常、待登录、异常、已停用、暂停”等状态。
  - 已完成：购物/电商标注为通过 Gmail 订单邮件和浏览器页面间接支持，不冒充独立 collector。
  - 验证结果：`gradle :app:assembleDebug` 构建成功；模拟器安装成功；悬浮球打开账号清单后可见 Gmail、WhatsApp Web、Telegram Web、Google Calendar、Google Search，列表可滚动到底部并显示 Chrome Bookmarks、浏览行为、购物/电商；点击 Gmail 行会收起面板并打开 noVNC 远程浏览器连接页。
  - 遗留问题：还没有直接控制服务器浏览器自动切换到对应登录网址；当前打开 noVNC 后需要用户在远程浏览器中确认或选择站点页面。

- [ ] 设置页
  - 悬浮球开关。
  - 主动消息开关。
  - WebSocket 重连策略。
  - 系统通知开关。
  - 安静模式。
  - 当前状态：未开始。
  - 遗留问题：目前只有主配置页，没有单独的设置页；轮询间隔、通知开关、安静模式仍需开发。

## 暂不做

- 不做 Android 本机采集。
- 不读取通知、短信、通讯录、相册。
- 不做 Accessibility Service。
- 不做屏幕 OCR。
- 不自动操作其他 App。
- 不做完整语音助手。

## 技术方案

- 推荐形态：原生 Android 壳 + Overlay Foreground Service + WebView。
- Android 原生负责权限、悬浮窗、通知、配置保存和主动消息 WebSocket 连接。
- 业务能力复用现有后端 API 和 H5 工作台。

## 验收标准

- 模拟器中可以安装并启动应用。
- 可以配置服务器并通过 `/health`。
- 悬浮球能显示、拖动、吸边、展开和隐藏。
- 小面板可以向 `/api/chat` 发消息并展示结果。
- Worker 产生的新建议能通过 `/ws` 实时出现在 Nomi 悬浮球气泡中，点击后进入完整工作台对话页。
- WebView 可以打开 H5 工作台。
- H5 工作台对话页使用流式输出。
- 每完成一项，本文件对应条目必须更新状态和验证结果。
