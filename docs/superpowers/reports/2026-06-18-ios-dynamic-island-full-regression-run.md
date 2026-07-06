# iOS Dynamic Island Full Regression Run

日期：2026-06-18
执行时间：16:30-16:43 CST
用例来源：`docs/superpowers/plans/2026-06-18-ios-dynamic-island-regression-test-cases.md`
执行设备：`iPhone 17 Pro` simulator，UDID `51B3E250-B88F-467C-8299-6EC82F98CC9F`，iOS `26.2`
工程：`/Users/wrf/Documents/background/ios_app/Nomi/Nomi.xcodeproj`
Scheme：`Nomi`
Bundle ID：`com.nomi.privatecloud`

## 总结

| 状态 | 数量 |
|---|---:|
| PASS | 13 |
| FAIL | 5 |
| GAP | 5 |
| BLOCKED | 4 |
| 合计 | 27 |

P0 结果：未阻断。工程可 build/run，app 可启动，Settings 可打开，自动 Live Activity 可创建，Home Screen 上可看到 Dynamic Island 元素。

补 gap 前原始执行的主要失败：

- `TC-IOS-030`、`TC-IOS-033`、`TC-IOS-034`：Settings 里 `Start / Preview / Stop` 同一行按钮存在 SwiftUI Form 行内按钮分发问题。点击 `Start` 或 `Preview` 后实际最终变成 `Inactive / Stopped`。
- `TC-IOS-035`：关闭 Live Activity 开关后点 `Start` 不会启动 activity，但状态文案仍是 `Stopped`，不是用例预期的 `Disabled`。
- `TC-IOS-036`：`Open app when tapping Dynamic Island` 关闭后，点击 Dynamic Island 仍打开 app。

补 gap 前原始执行的主要 GAP/BLOCKED：

- Settings 不持久化，重启后恢复默认。
- Chat 页只有输入框，没有发送按钮、消息列表、真实 WebSocket/HTTP chat 驱动 token 更新。
- App 内没有 server URL/password 配置入口，无法从 UI 完成 device/activity token registration。
- APNs Team/Key/Private Key/bridge env 全部未设置，真机 APNs 相关用例阻塞。

## 补 Gap 后复测（20:08-20:20 CST）

本轮按失败/GAP 项补实现后重新执行了自动化和关键 UI 回归。

自动化结果：

- iOS XCTest：`25 passed, 0 failed, 0 skipped`
  - build log：`/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/logs/test_sim_2026-06-18T12-18-39-285Z_pid1299_e0948f4f.log`
  - xcresult：`/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/result-bundles/test_sim_2026-06-18T12-18-39-285Z_pid1299_e5fe90da.xcresult`
- 后端 focused pytest：`163 passed in 0.90s`
  - 命令：`python3 -m pytest runtime_api/tests/test_ios_live_activity.py runtime_api/tests/test_auth_and_model.py runtime_api/tests/test_vector_and_suggestions.py runtime_api/tests/test_realtime_ws.py runtime_api/tests/test_context_pack_and_chat.py -q`
- 正常模拟器签名 build/run：`status=SUCCEEDED`，warnings/errors 为空。
  - build log：`/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/logs/build_run_sim_2026-06-18T12-19-33-100Z_pid1299_b440bdf9.log`
  - runtime log：`/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/logs/com.nomi.privatecloud_2026-06-18T12-19-54-046Z_helperpid58112_ownerpid1299_b07dc29a.log`
  - os log：`/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/logs/com.nomi.privatecloud_oslog_2026-06-18T12-19-57-334Z_helperpid58196_ownerpid1299_911ead28.log`

关键 UI 复测：

- `TC-IOS-030/033/034`：Settings 中 `Preview` 后状态为 `Preview sent`，没有误触 `Stop`；`Stop` 后显示 `Inactive / Stopped`；再次点击 `Start` 后恢复为 `Active <activityId>`。原 SwiftUI Form 行内按钮问题已通过 `.buttonStyle(.borderless)` 修复。
- `TC-IOS-035`：关闭 `Show Nomi in Dynamic Island` 后显示 `Inactive / Stopped`；在禁用状态点击 `Start` 后显示 `Disabled`；重新打开开关后自动创建新 Activity。
- `TC-IOS-043`：从 Chat 触发 `xcrun simctl openurl 51B3E250-B88F-467C-8299-6EC82F98CC9F 'nomi://settings/live-activity'` 后自动切到 Settings tab。
- `TC-IOS-050/100`：`NomiIslandSettingsStore` 已持久化 settings；复测中 `Open target page when tapping Dynamic Island=0` 在重新 build/run 后仍保持关闭。
- `TC-IOS-051`：Chat 页现在有消息列表、发送按钮和错误状态；未配置服务器时输入 `Hello Nomi` 后点击 Send，显示 `Server not configured` 并保留草稿。
- `TC-IOS-070`：Settings 新增 Server section，包含 `Base URL`、`Password`、`Save server` 和 server 状态文案；保存后会写入 Keychain 并触发 device registration。
- `TC-IOS-005`（原 gap）：后端已支持普通 APNs alert fallback；当 Live Activity update 失败、设备允许 fallback 且存在普通 APNs token 时发送 alert，并记录 `notification_fallback_sent` audit。

保留限制：

- `TC-IOS-036` 的原始“关闭开关后点击灵动岛不打开 app”预期不能按当前 ActivityKit 能力兑现。本轮已将 `deep_links_enabled=false` 贯通到后端 payload、本地 Live Activity state 和 WidgetKit `widgetURL=nil`，并把 UI 文案改为 `Open target page when tapping Dynamic Island`。但 iOS 26.2 模拟器中，点击无 `widgetURL` 的 Live Activity 仍会启动宿主 app，这是系统默认行为；当前开关只控制是否跳转到具体目标页面。
- 真机 APNs、真实灵动岛展开、生产签名和 App Group 仍需 Apple Developer Team、APNs key、真机和 provisioning profile。
- 普通 APNs alert fallback 的后端发送路径已实现并测试，但 iOS app 尚未请求通知权限和采集普通 APNs device token；真机 fallback 收到系统通知前还需要补这一段。
- Chat UI 已有 HTTP 发送和本地 token 分块更新；真实 WebSocket 增量 `chat_delta` 前台 UI 还未完整接入，详见 gap 文档。

## 基线证据

- `session_show_defaults`：projectPath `/Users/wrf/Documents/background/ios_app/Nomi/Nomi.xcodeproj`，scheme `Nomi`，simulator `iPhone 17 Pro`，bundleId `com.nomi.privatecloud`。
- `list_sims`：`iPhone 17 Pro` booted，runtime `iOS 26.2`。
- 首次正常签名 build/run：`status=SUCCEEDED`，warnings/errors 为空。
  - build log：`/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/logs/build_run_sim_2026-06-18T08-30-53-744Z_pid93163_49afd733.log`
  - runtime log：`/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/logs/com.nomi.privatecloud_2026-06-18T08-31-02-212Z_helperpid59014_ownerpid93163_e613d25c.log`
  - os log：`/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/logs/com.nomi.privatecloud_oslog_2026-06-18T08-31-03-363Z_helperpid59201_ownerpid93163_74d1277f.log`
- 首屏截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_abf85b02-666d-4540-af90-07de56118478.jpg`

## 自动化基线

- iOS XCTest：`xcodebuildmcp.test_sim` with `CODE_SIGNING_ALLOWED=NO`
  - 结果：`16 passed, 0 failed, 0 skipped`
  - build log：`/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/logs/test_sim_2026-06-18T08-31-25-199Z_pid93163_f92ef49c.log`
  - xcresult：`/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/result-bundles/test_sim_2026-06-18T08-31-25-199Z_pid93163_61888298.xcresult`
  - 覆盖到的关键测试：`NomiLiveActivityStartupTests`、`NomiRealtimeClientTests`、`NomiIslandSettingsTests`、`DeepLinkRouterTests`、`NomiApiClientTests`。
- 后端 focused pytest：
  - 命令：`python3 -m pytest runtime_api/tests/test_ios_live_activity.py runtime_api/tests/test_auth_and_model.py runtime_api/tests/test_vector_and_suggestions.py runtime_api/tests/test_realtime_ws.py runtime_api/tests/test_context_pack_and_chat.py -q`
  - 结果：`160 passed in 1.56s`

## 用例执行结果

### TC-IOS-000 环境和签名基线：PASS

实际过程：

1. `session_show_defaults` 返回工程、scheme、simulator、bundleId 均符合预期。
2. `list_sims` 显示 `iPhone 17 Pro` booted。
3. 正常签名 `build_run_sim` 成功，返回 appPath、runtimeLogPath、osLogPath。
4. 截图显示 Chat 首屏，底部有 `Chat`、`Suggestions`、`Settings`。

证据：首屏截图 `screenshot_optimized_abf85b02-666d-4540-af90-07de56118478.jpg`。

### TC-IOS-001 自动化回归基线：PASS

实际过程：

1. XCTest `16 passed, 0 failed, 0 skipped`。
2. 后端 focused pytest `160 passed in 1.56s`。
3. 测试覆盖 settings 编码、payload safe/sensitive、APNs payload/client、active activity、delivery audit、chat delta、deep link parser、realtime parser、startup coordinator。

### TC-IOS-010 首屏和基础导航：PASS

实际过程：

1. Chat tab 默认选中，snapshot 有 `Nomi` 和 `Private-cloud assistant chat`，输入框为 `Ask Nomi`。
2. 点击 Suggestions 后显示 `No deep link selected` 和 `Connect to your Nomi server to load proactive suggestions.`。
3. 点击 Settings 后显示 `Show Nomi in Dynamic Island`、`Open app when tapping Dynamic Island`、`Notification fallback`、`Stream every reply token`、`Allow private content in APNs`。

### TC-IOS-020 Settings 默认状态：PASS

实际过程：

1. `Show Nomi in Dynamic Island=1`，`Open app when tapping Dynamic Island=1`，`Notification fallback=1`。
2. Activity 行显示 `D253B121`，状态为 `Active D253B121`。
3. `Stream every reply token=0`，`Delivery=Foreground only`。
4. `Allow private content in APNs=0`，未显示 message body/contact/raw context/stepper 子项。

证据：Settings 截图 `screenshot_optimized_c6c8127c-54c4-4448-8ae0-b9dbec6a3e6d.jpg`。

### TC-IOS-030 自动启动 Live Activity：FAIL

实际过程：

1. 重启后进入 Settings，Activity 自动显示 `D253B121 / Active D253B121`，自动启动路径通过。
2. 点击 `Start`，预期 activity id 不变且仍 active。
3. 实际变为 `Activity=Inactive`，状态 `Stopped`。
4. 再次在 `Inactive / Stopped` 状态点击 `Start`，仍保持 `Inactive / Stopped`，没有重新启动。

结论：FAIL。自动启动可用，但手动 `Start` 按钮行为失败。

### TC-IOS-031 Home Screen Dynamic Island 展示：PASS

实际过程：

1. 重启恢复 active，Settings 显示 `A0B20AC1 / Active A0B20AC1`。
2. 按 Home 回桌面。
3. Home Screen snapshot 中出现可点击元素 `e165|tap|other|N, •||regular.view`。
4. 截图顶部 Dynamic Island 显示 Nomi compact 元素。

证据：Home Screen 截图 `screenshot_optimized_91be1220-8c82-47b0-80b6-10ee40ef807f.jpg`。

### TC-IOS-032 点击灵动岛回 app：PASS

实际过程：

1. 在 Home Screen 中点击 `e165`，label 为 `N, •`。
2. Nomi app 被拉回前台。
3. Settings 仍显示 `A0B20AC1 / Active A0B20AC1`。
4. runtime log 未发现 crash/fatal/uncaught；只在后一轮日志中出现一条 CFRunLoop invalid mode 系统提示。

### TC-IOS-033 Preview 更新内容：FAIL

实际过程：

1. Settings 中 activity active。
2. 点击 `Preview`。
3. 预期：状态变 `Preview sent`，activity 仍 active，Home Screen Dynamic Island 从 `N, •` 变成 token 序号状态。
4. 实际：Settings 直接变成 `Activity=Inactive`，状态 `Stopped`。

结论：FAIL。与 Start/Stop 同行按钮问题同源。

### TC-IOS-034 Stop 隐藏 Live Activity：FAIL

实际过程：

1. 重启后 activity 为 `0FB33ED3 / Active 0FB33ED3`。
2. 点击 `Stop` 后 Settings 显示 `Inactive / Stopped`。
3. 按 Home 后 snapshot 不再包含 `N, •` 或 `N, 1`，系统层活动消失。
4. 用例要求随后点击 `Start` 可重新创建；实际 Start 不能重新创建，仍保持 `Inactive / Stopped`。

结论：FAIL。Stop 本身通过，但恢复步骤失败。

证据：Stop 后 Home Screen 截图 `screenshot_optimized_d8954b5d-392a-4a83-a83b-15c90519c7ba.jpg`。

### TC-IOS-035 Live Activity 开关行为：FAIL

实际过程：

1. activity 为 `4BDF03EB / Active 4BDF03EB`。
2. 关闭 `Show Nomi in Dynamic Island` 后，Settings 变为 `Inactive / Stopped`，Home Screen 不再显示 Nomi Dynamic Island。
3. 关闭状态下点击 `Start` 没有启动 activity，但状态仍为 `Stopped`，不是预期 `Disabled`。
4. 重新开启开关后自动启动新 activity：`636A3962 / Active 636A3962`。

结论：FAIL。核心开关能结束和恢复 activity，但 disabled 状态下的手动启动反馈不符合用例预期。

证据：关闭后 Home Screen 截图 `screenshot_optimized_dfdffc32-e19b-4366-a3bf-bd1b8380b5cb.jpg`。

### TC-IOS-036 点击回 app 开关行为：FAIL

实际过程：

1. activity 为 `636A3962 / Active 636A3962`。
2. 关闭 `Open app when tapping Dynamic Island`，switch 值为 `0`。
3. 按 Home 后 Dynamic Island 仍显示 `N, •`。
4. 点击 `N, •` 后 Nomi app 仍被拉回前台，Settings 仍显示 `636A3962 / Active 636A3962`。

结论：FAIL。开关没有约束当前本地 Live Activity 的 `widgetURL`/tap behavior。

### TC-IOS-040 Deep Link：Chat：PASS

实际过程：

1. Chat 默认显示 `Private-cloud assistant chat`。
2. `xcrun simctl openurl ... 'nomi://chat?conversation_id=ios-reg-chat-001'` 首次触发系统确认框 `在“Nomi”中打开？`，点击 `打开`。
3. Chat 文案变为 `Conversation ios-reg-chat-001`。
4. 打开 `nomi://chat` 后恢复 `Private-cloud assistant chat`。

### TC-IOS-041 Deep Link：Suggestion：PASS

实际过程：

1. 打开 `nomi://suggestion?id=ios-reg-suggestion-001`。
2. 点击 Suggestions tab 后显示 `Suggestion ios-reg-suggestion-001`。
3. placeholder 仍为 `Connect to your Nomi server to load proactive suggestions.`。
4. 打开 `nomi://suggestion` 后显示 `No deep link selected`，没有空 id 或崩溃。

### TC-IOS-042 Deep Link：Task：PASS

实际过程：

1. 打开 `nomi://task?id=ios-reg-task-001`。
2. Suggestions tab 显示 `Task ios-reg-task-001`。
3. 打开 `nomi://task` 后显示 `No deep link selected`，没有 `Task ` 空 id 或崩溃。

### TC-IOS-043 Deep Link：Settings：GAP

实际过程：

1. 从 Suggestions 页面打开 `nomi://settings/live-activity`。
2. app 没有自动切到 Settings，仍停留在 Suggestions 页面，显示 `No deep link selected`。
3. 手动点击 Settings 后能看到 Dynamic Island section。

结论：GAP。DeepLinkRouter 能解析 settings route，但 RootView 没有基于 route 自动切 tab。

### TC-IOS-050 Token streaming 设置：GAP

实际过程：

1. 打开 `Stream every reply token`，switch 变为 `1`。
2. Delivery picker 展示 `Foreground only`、`APNs best effort`、`Foreground and APNs` 三个选项。
3. 选择 `APNs best effort` 后显示 `APNs best effort`。
4. 再选择 `Foreground and APNs` 后显示 `Foreground and APNs`。
5. 重启 app 后 Settings 恢复默认：`Stream every reply token=0`，`Delivery=Foreground only`，之前关闭过的 `Open app when tapping Dynamic Island` 也恢复为 `1`。

结论：GAP。即时 UI 可用，但 settings 没有本地持久化/后端同步。

### TC-IOS-051 Chat 输入和 token 级本地更新：GAP

实际过程：

1. Chat 页面显示输入框 `Ask Nomi`。
2. 中文测试串无法由 UI 自动化工具输入，工具限制为 US keyboard；改用英文 `iOS token streaming regression one sentence`。
3. 输入成功，text-field value 变为 `IOS token streaming regression one sentence`。
4. snapshot 中只有输入框和 tab，没有发送按钮。
5. 按 Return 后没有消息列表、用户消息、Nomi 回复或 Dynamic Island token 更新。

结论：GAP。当前 ChatView 只有输入框，没有真实发送和 token streaming UI 链路。

### TC-IOS-060 Sensitive APNs UI 开关：PASS

实际过程：

1. 默认 `Allow private content in APNs=0`，子项不可见。
2. 打开父开关后显示风险提示：`Private message text may pass through Apple Push Notification service. Enable only if you accept that tradeoff.`
3. 滚动后可见 `Include message body`、`Include contact names`、`Include raw private context`、`Payload limit: 2,400`。
4. 批量打开三个子开关后，它们均为 `1`。
5. 点击 Increment 后 payload limit 从 `2,400` 变成 `2,500`。
6. 关闭父开关后子项隐藏。

### TC-IOS-061 Safe mode 后端 payload：PASS

实际过程：

1. 直接调用 `build_live_activity_content_state()` 构造 safe proactive event。
2. 输出 `payloadMode=safe`。
3. 输出 title 为 `Nomi has a new suggestion`，body 为 `Open Nomi to review it.`。
4. safe state 不包含 `Private title should not appear in safe mode`、`Gmail body should not appear in safe mode`、`Alice Sensitive`、`WhatsApp private snippet...`。

实际 safe JSON：

```json
{"body":"Open Nomi to review it.","conversationId":"","deepLink":"nomi://suggestion?id=ios-reg-suggestion-001","partialAnswer":"","payloadMode":"safe","phase":"suggestion","source":"whatsapp","suggestionId":"ios-reg-suggestion-001","taskId":"","title":"Nomi has a new suggestion","tokenSequence":0,"truncated":false,"unreadCount":1}
```

### TC-IOS-062 Sensitive mode 后端 payload：PASS

实际过程：

1. settings 设置 `sensitive_apns_payload_enabled=true`、`include_private_message_body=true`、`include_contact_names=true`、`include_raw_private_context=true`。
2. 输出 `payloadMode=sensitive`。
3. title/body 包含允许的私密摘要。
4. `privateContext` 包含 `channel=whatsapp`、`contact=Alice Sensitive`、`rawSnippet=WhatsApp private snippet 2026-06-18...`。
5. 超长 rawSnippet 测试输出 `LONG_STATE_TRUNCATED=True`，`LONG_RAW_LEN=360`。
6. APNs payload keys 为 `["content-state", "event", "stale-date", "timestamp"]`。

### TC-IOS-070 Server config 和设备注册：GAP

实际过程：

1. Settings 和其它 tab 中没有 server URL/password 配置入口。
2. `AppState.serverConfig` 没有用户可见写入路径。
3. 因此无法从 iOS UI 完成 `/api/ios/devices/register`、`/api/ios/live-activities/register`、`/api/ios/devices/{device_id}/settings` 的端到端注册和同步。

结论：GAP，对应 `gap-007-ios-server-config-ui-and-registration`。

### TC-IOS-080 Proactive suggestion 远程更新：BLOCKED

阻塞条件：

- `ENABLE_IOS_LIVE_ACTIVITY_BRIDGE=UNSET`
- `APNS_TEAM_ID=UNSET`
- `APNS_KEY_ID=UNSET`
- `APNS_BUNDLE_ID=UNSET`
- `APNS_PRIVATE_KEY_P8=UNSET`
- iOS UI 也没有 server config/registration 入口。

结论：BLOCKED。后端 payload builder 已通过 TC-IOS-061/062 和 pytest 验证，但真实 Redis/APNs/iOS UI 远程更新链路未执行。

### TC-IOS-081 App Intents：Done/Dismiss：BLOCKED

阻塞条件：

- 需要 suggestion state 中有非空 `suggestionId`。
- 当前没有 server config UI，App Intent 无法从 Keychain 拿到后端配置。
- 没有远程 proactive suggestion Live Activity 展开态。

结论：BLOCKED。

### TC-IOS-090 Lock Screen Live Activity：PASS

实际过程：

1. 当前 activity active：`D008ED99 / Active D008ED99`。
2. 按 Home，再按 Lock。
3. 锁屏截图显示 Nomi Live Activity 卡片，标题 `Nomi`，body `Ready`。
4. snapshot 中有 `activity-content-view`，elementRef `e160`。
5. 点击 `e160` 后回到 Nomi Settings，仍显示 `D008ED99 / Active D008ED99`。

证据：锁屏截图 `screenshot_optimized_4dd3e796-6ebd-43da-89f7-b9f5beaad8a8.jpg`。

### TC-IOS-100 设置持久化和重启恢复：GAP

实际过程：

1. 修改 `Stream every reply token=1`、`Delivery=Foreground and APNs`，并曾关闭 `Open app when tapping Dynamic Island`。
2. 重启 app。
3. Settings 恢复默认：`Stream every reply token=0`、`Delivery=Foreground only`、`Open app when tapping Dynamic Island=1`。
4. 没有 server config，因此无法验证后端 settings 同步。

结论：GAP，对应 `gap-008-ios-settings-persistence-and-sync`。

### TC-IOS-110 APNs 真机远程更新：BLOCKED

阻塞条件：

- `DEVELOPMENT_TEAM=""`。
- APNs env 全部 unset。
- 没有真实 Dynamic Island iPhone 设备接入。
- App Group 仅在 entitlements 文件中声明，未验证 Developer Portal/provisioning。

结论：BLOCKED。

### TC-IOS-120 失败和降级行为：BLOCKED

已执行部分：

- 直接调用 `APNsLiveActivityClient` 空配置发送 update，返回：

```json
{"error": "APNs configuration missing", "status": "misconfigured", "status_code": 0}
```

未执行部分：

- 未启动真实 bridge loop。
- 未写入真实 `ios_live_activity_events` audit 行。
- 未执行 update token 失效 APNs 远程失败路径。

结论：BLOCKED，局部 misconfigured contract 通过。

### TC-IOS-130 回归收尾记录：PASS

实际过程：

1. 每个用例均给出 `PASS/FAIL/BLOCKED/GAP`。
2. 关键截图、build log、runtime log、os log、pytest/XCTest 输出均记录。
3. 新发现问题已同步到 gap 清单。

## 汇总表

| 用例 | 状态 | 关键证据 | 原因/下一步 |
|---|---|---|---|
| TC-IOS-000 | PASS | defaults、build/run、首屏截图 | 环境正确 |
| TC-IOS-001 | PASS | XCTest 16 passed；pytest 160 passed | 自动化基线通过 |
| TC-IOS-010 | PASS | Chat/Suggestions/Settings snapshot | 三 tab 可见 |
| TC-IOS-020 | PASS | Settings snapshot `D253B121 / Active D253B121` | 默认开关符合预期 |
| TC-IOS-030 | FAIL | `Start` 后变 `Inactive / Stopped` | 修复 Form 行内按钮分发 |
| TC-IOS-031 | PASS | Home snapshot `N, •` | 系统层显示 |
| TC-IOS-032 | PASS | 点击 `N, •` 回 Settings | tap-to-app 可用 |
| TC-IOS-033 | FAIL | `Preview` 后变 `Inactive / Stopped` | 修复按钮组 |
| TC-IOS-034 | FAIL | Stop 隐藏通过，Start 恢复失败 | 修复 Start |
| TC-IOS-035 | FAIL | 关闭开关结束 activity，但 disabled Start 文案不对 | 修复 disabled 状态反馈 |
| TC-IOS-036 | FAIL | deep link 开关关闭后仍打开 app | 让 local state 遵守 `deepLinksEnabled` |
| TC-IOS-040 | PASS | `Conversation ios-reg-chat-001` | Chat deep link 可用 |
| TC-IOS-041 | PASS | `Suggestion ios-reg-suggestion-001` | Suggestion deep link 可用 |
| TC-IOS-042 | PASS | `Task ios-reg-task-001` | Task deep link 可用 |
| TC-IOS-043 | GAP | settings URL 不切 tab | 增加 route-driven tab selection |
| TC-IOS-050 | GAP | 重启后设置恢复默认 | 增加 settings persistence |
| TC-IOS-051 | GAP | 无发送按钮/消息列表 | 实现 Chat UI 发送链路 |
| TC-IOS-060 | PASS | 风险提示、子开关、stepper | Sensitive UI 可用 |
| TC-IOS-061 | PASS | safe JSON 无私密内容 | safe payload 通过 |
| TC-IOS-062 | PASS | sensitive JSON 和 truncation | sensitive payload 通过 |
| TC-IOS-070 | GAP | 无 server config UI | 实现配置/注册 UI |
| TC-IOS-080 | BLOCKED | APNs/bridge env unset | 配置 APNs + bridge |
| TC-IOS-081 | BLOCKED | 无 suggestion state/server config | 先实现注册和远程 suggestion |
| TC-IOS-090 | PASS | 锁屏截图和点击 `activity-content-view` | 锁屏本地 Live Activity 可用 |
| TC-IOS-100 | GAP | 重启后设置丢失 | settings 持久化 |
| TC-IOS-110 | BLOCKED | Team/APNs/真机缺失 | 配置 Apple Developer/真机 |
| TC-IOS-120 | BLOCKED | misconfigured contract 通过，audit/remote 未执行 | 需要真实 bridge/APNs/DB |
| TC-IOS-130 | PASS | 本报告 | 已记录 |

## 新发现问题

1. Settings 的 `Start / Preview / Stop` 放在同一个 `Form` row 的 `HStack` 中，实际点击 `Start` 或 `Preview` 后最终状态变成 `Stopped`。疑似 SwiftUI `Form/List` 默认 button style 行内分发问题。建议改成独立 row 或给按钮加 `.buttonStyle(.borderless)` 并增加 UI 测试。
2. `Open app when tapping Dynamic Island` 关闭后，Dynamic Island 仍然可点击并打开 app。本地 Live Activity state 构造没有使用 `deepLinksEnabled`。
3. `nomi://settings/live-activity` 不会自动切换到 Settings tab。
4. Settings 没有持久化，重启恢复默认。
5. Chat 页没有真实发送链路。
