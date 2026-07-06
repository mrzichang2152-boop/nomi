# iOS Dynamic Island Implementation Gaps

日期：2026-06-18

本文件记录执行 `docs/superpowers/plans/2026-06-18-ios-dynamic-island-interaction-plan.md` 期间所有偏离计划、未完成项、外部阻塞和已知风险。任何为了继续推进而留下的缺口都必须写在这里。

## 未闭环 Gap

- `gap-001-worktree-isolation`：计划要求按任务开发并提交，但当前仓库不是 linked worktree，且已有大量未提交改动，包含本次必须修改的 `runtime_api/app/main.py`、`runtime_api/requirements.txt`、`.env.example` 等文件；`.worktrees` 也尚未被 `.gitignore` 忽略。为了避免误提交或破坏既有用户改动，本轮先在当前分支 `codex/volcengine-streaming-voice-input` 上开发，不按任务自动 commit。完成后需要人工或后续任务把本轮改动与既有改动拆分审查。
- `gap-003-real-apns-and-dynamic-island-device-verification`：本轮已经实现 APNs Live Activity payload/client、iOS ActivityKit controller、WidgetKit Dynamic Island UI、`widgetURL` tap-to-app deep link、后端 Redis bridge 和 token-level chat hook；模拟器本地 Live Activity 展示和点击回 app 已验证。但没有 Apple Developer Team、真实 APNs key、真实 iPhone 设备和正式 bundle provisioning，无法验证真实 APNs 到达、真实灵动岛展开、锁屏 Live Activity 远程更新。
- `gap-004-production-signing-and-app-groups`：Xcode 工程已配置 bundle id `com.nomi.privatecloud`、widget bundle id `com.nomi.privatecloud.widgets`、Live Activity entitlement 和 app group 字段，但 `DEVELOPMENT_TEAM` 为空，App Group 也还不是 Apple Developer Portal 中真实创建并授权的 group。上真机前必须填入团队、重新生成 provisioning profile，并确认 app 与 widget extension 共享 group 可用。
- `gap-005b-ios-standard-notification-device-token`：后端普通 APNs alert fallback 已实现，但 iOS app 还没有请求通知权限、注册 remote notifications、采集普通 APNs device token 并传给 `registerDevice(apnsDeviceToken:)`。因此即使后端 fallback 逻辑可测，真机上普通通知 fallback 仍需要补 iOS device token 注册和用户授权流程。
- `gap-006-manual-safe-sensitive-token-regression-on-device`：safe mode、sensitive mode、token-level chat delta 已有自动化测试覆盖，模拟器本地 Live Activity 展示和点击回 app 已验证；但计划中的真实手工回归（安全模式不泄露正文、敏感模式显示正文/联系人、token 级更新在灵动岛节流表现、远程 APNs 更新后点击进入对应页面）仍需在真机+APNs 凭据环境完成。
- `gap-009b-ios-true-websocket-token-streaming-ui`：本轮已补 Chat 发送按钮、消息列表、HTTP `/api/chat` 调用，以及在 token streaming 开关打开时把完整回复按词分块推给本地 Live Activity；但 Chat UI 还没有接入 `NomiRealtimeClient.connect()` 的真实 WebSocket 增量 `chat_delta` 消费，因此“边生成边展示/边更新灵动岛”的前台 UI 仍不是完整端到端流式体验。后端 token-level APNs hook 和 WebSocket payload 已有测试覆盖。
- `gap-010b-ios-live-activity-tap-launch-platform-limit`：本轮已让 `deep_links_enabled=false` 时后端 payload、本地初始 state、本地 chat delta state 都输出空 `deepLink`，WidgetKit `widgetURL` 也会收到 `nil`；Settings 文案已改为 `Open target page when tapping Dynamic Island`。但在 iOS 26.2 模拟器上，点击没有 `widgetURL` 的 Live Activity/Dynamic Island 仍会启动宿主 app，这是系统默认行为，当前没有发现 ActivityKit API 可以阻止宿主 app 被拉起。开关当前能控制“是否跳到目标页面/route”，不能控制“是否启动宿主 app”。

## 过程偏离和已处理说明

- `gap-002-ios-project-scaffold-before-tests`：iOS `.xcodeproj`、target、Info.plist、entitlements 这类工程骨架必须先存在，XCTest target 才能编译运行。该部分作为配置/生成骨架先落地；之后所有可测试的 Swift 业务逻辑（URL 解析、Realtime 解析、settings 编码和持久化、API request 构造、Live Activity state/deep link、Chat send pipeline、AppState route selection 等）已继续按 RED-GREEN 执行，并由 `xcodebuildmcp.test_sim` 25 个测试覆盖。

## 已关闭 Gap

- `gap-005-standard-notification-fallback`：已补普通 APNs alert fallback。`APNsConfig.alert_topic`、`build_alert_apns_payload()`、`APNsLiveActivityClient.send_alert()` 已实现；`push_realtime_event_to_ios_live_activities()` 在 Live Activity update 非 `sent` 且设备允许 `notification_fallback_enabled`、存在普通 APNs token 时发送 alert，并写入 `notification_fallback_sent` audit。覆盖测试：`runtime_api/tests/test_ios_live_activity.py`。
- `gap-007-ios-server-config-ui-and-registration`：Settings 已新增 Server section，支持 Base URL/password 输入、保存到 Keychain、`AppState.serverConfig` 写入、保存后触发 `registerDevice()`。没有真实可达服务器时 UI 会显示同步失败，不再是“无入口”。
- `gap-008-ios-settings-persistence-and-sync`：已新增 `NomiIslandSettingsStore` 使用 `UserDefaults` 持久化 settings；`RootView` 监听 settings 变化后本地保存并在 server 已配置时调用后端 settings sync。覆盖测试：`NomiIslandSettingsTests.testSettingsStorePersistsUserChoices()` 和 `AppStateTests.testLoadsPersistedIslandSettingsOnLaunch()`。
- `gap-009-ios-chat-send-and-token-streaming-ui`：已补 Chat 消息列表、发送按钮、未配置服务器错误状态、`NomiChatSendPipeline`、HTTP chat 请求，以及本地 token-level Live Activity delta 分块。真实 WebSocket 增量 UI 另记为 `gap-009b-ios-true-websocket-token-streaming-ui`。
- `gap-010-ios-deep-link-toggle-enforcement`：已补后端和本地 Live Activity state 的 deep link 开关，关闭后不再写入具体 route URL；同时 WidgetKit 使用 `ContentState.deepLinkURL`，空 deepLink 转为 nil。系统仍启动宿主 app 的平台行为另记为 `gap-010b-ios-live-activity-tap-launch-platform-limit`。
- `gap-011-ios-live-activity-manual-button-row`：已给 Settings 中 `Start / Preview / Stop` 行设置 `.buttonStyle(.borderless)`，模拟器 UI 回归确认 `Preview` 后保持 `Preview sent`，`Stop` 后为 `Inactive / Stopped`，再点 `Start` 可重新创建 activity。
- `gap-012-ios-settings-deep-link-tab-selection`：已新增 `NomiTab` 和 route-driven tab selection；`nomi://settings/live-activity` 会自动选中 Settings tab。覆盖测试：`AppStateTests.testDeepLinkToSettingsSelectsSettingsTab()`，模拟器用 `xcrun simctl openurl ... 'nomi://settings/live-activity'` 验证通过。
