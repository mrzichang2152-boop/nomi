# iOS Dynamic Island 全量回归测试用例

日期：2026-06-18
适用工程：`/Users/wrf/Documents/background/ios_app/Nomi/Nomi.xcodeproj`
Scheme：`Nomi`
Bundle ID：`com.nomi.privatecloud`
关联方案：`docs/superpowers/plans/2026-06-18-ios-dynamic-island-interaction-plan.md`

## 目标

本用例用于验证 iOS 端不是“结构上能编译”或“文件存在”而已，而是逐步确认用户真实会看到什么、点了什么、系统状态如何变化、后端是否收到正确数据、隐私开关是否真的改变行为。

每一步都必须记录实际观察结果。不能只记录“成功”“通过”“结构存在”。没有截图、UI 文本、日志路径、接口响应、数据库记录或系统快照的步骤，不算通过。

## 执行记录规则

每个步骤都必须填写：

- 实际结果：写精确 UI 文本、按钮状态、activity id 前 8 位、接口 status code、JSON 字段、日志路径或截图路径。
- 证据：截图路径、XcodeBuildMCP snapshot 元素、build log、runtime log、os log、pytest/xctest 输出、数据库查询结果。
- 结论：`PASS`、`FAIL`、`BLOCKED`、`GAP` 四选一。

判定规则：

- `PASS`：实际结果逐项匹配预期结果。
- `FAIL`：能执行但实际结果与预期不一致。
- `BLOCKED`：缺少设备、证书、APNs key、后端环境等外部条件，无法执行。
- `GAP`：当前产品能力缺失，导致该用例按产品预期必然失败；必须关联 gap 文档。

## 通用环境

测试设备分两类：

- 模拟器必跑：Dynamic Island 设备模拟器，例如 `iPhone 17 Pro`，用于本地 Live Activity、Settings、tap-to-app、deep link、UI 基础回归。
- 真机必跑：带 Dynamic Island 的 iPhone，用于真实 APNs、锁屏 Live Activity、生产签名、App Group、远程更新回归。

视觉验证必须使用正常模拟器签名运行 app。`CODE_SIGNING_ALLOWED=NO` 可以跑 XCTest，但不能作为灵动岛视觉展示验证方式。

通用测试数据：

```text
conversation_id=ios-reg-chat-001
suggestion_id=ios-reg-suggestion-001
task_id=ios-reg-task-001
device_id=ios-reg-device-001
safe_event_title=Private title should not appear in safe mode
safe_event_body=Gmail body should not appear in safe mode
sensitive_contact=Alice Sensitive
sensitive_raw_snippet=WhatsApp private snippet 2026-06-18 should appear only in sensitive mode
```

## P0 阻断项

如果以下任一步骤失败，停止执行后续功能回归，先修复阻断项：

1. iOS 工程无法 build。
2. App 无法启动到首屏。
3. Settings tab 无法打开。
4. `Show Nomi in Dynamic Island` 开启后无法创建 Live Activity。
5. 按 Home 后系统 UI 中完全没有 Dynamic Island 活动元素。

---

## TC-IOS-000 环境和签名基线

目的：确认执行环境正确，并避免用无签名包误判灵动岛不展示。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 调用 `xcodebuildmcp.session_show_defaults` | `projectPath` 是 `ios_app/Nomi/Nomi.xcodeproj`；`scheme` 是 `Nomi`；模拟器是 Dynamic Island 机型；`bundleId` 是 `com.nomi.privatecloud` | 记录完整 defaults JSON |
| 2 | 若 defaults 不正确，设置 project、scheme、`iPhone 17 Pro` 模拟器 | 再次查看 defaults 时所有字段正确 | 记录设置后的 defaults JSON |
| 3 | 调用 `xcodebuildmcp.build_run_sim`，不要传 `CODE_SIGNING_ALLOWED=NO` | `status=SUCCEEDED`；有 `appPath`、`runtimeLogPath`、`osLogPath`；diagnostics 中 warnings/errors 为空 | 记录 appPath、bundleId、runtimeLogPath、osLogPath |
| 4 | 截图首屏 | 截图顶部是 iOS app，底部有 `Chat`、`Suggestions`、`Settings` 三个 tab | 记录截图路径 |

通过标准：步骤 1-4 全部符合预期。只看到 build 成功但没有 UI 截图，不算通过。

---

## TC-IOS-001 自动化回归基线

目的：确认 Swift 和后端契约测试仍然通过，但该用例不能替代手工 UI 回归。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 调用 `xcodebuildmcp.test_sim`，可传 `CODE_SIGNING_ALLOWED=NO` | `status=SUCCEEDED`；`passed >= 16`；`failed=0`；`skipped=0`；无 warnings/errors | 记录 passed/failed/skipped、buildLogPath、xcresultPath |
| 2 | 执行 `python3 -m pytest runtime_api/tests/test_ios_live_activity.py runtime_api/tests/test_auth_and_model.py runtime_api/tests/test_vector_and_suggestions.py runtime_api/tests/test_realtime_ws.py runtime_api/tests/test_context_pack_and_chat.py -q` | 当前期望是 `160 passed`，失败数为 0 | 记录完整测试摘要 |
| 3 | 检查测试输出中是否只说明结构存在 | 不得只依赖文件存在测试；必须包含 settings、payload、APNs、active activity、audit、chat delta 等行为测试 | 记录覆盖到的测试文件和关键测试名 |

通过标准：自动化测试全绿，并确认它们只是基线，不替代后续 UI 步骤。

---

## TC-IOS-010 首屏和基础导航

目的：确认 app 用户路径可见，不只确认进程启动。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 正常签名 build/run 后停留在首屏 | 默认打开 `Chat` tab | 记录 UI snapshot |
| 2 | 检查 Chat 页面文字 | 页面显示 `Chat` 导航标题、`Nomi` 标题、`Private-cloud assistant chat`、`Ask Nomi` 输入框 | 记录截图和 snapshot 文本 |
| 3 | 点击 `Suggestions` tab | 页面导航标题为 `Suggestions`；显示 `Current route` section；显示 `No deep link selected`；显示 `Connect to your Nomi server to load proactive suggestions.` | 记录 snapshot 文本 |
| 4 | 点击 `Settings` tab | 页面导航标题为 `Settings`；显示 `Dynamic Island`、`Token streaming`、`Private APNs payloads` 三个 section | 记录 snapshot 文本 |

通过标准：三个 tab 都能点击，且每个页面显示精确文案。

---

## TC-IOS-020 Settings 默认状态

目的：确认风险开关默认值符合保守策略，并能被用户看见。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 进入 Settings | `Show Nomi in Dynamic Island` 为开启；`Open app when tapping Dynamic Island` 为开启；`Notification fallback` 为开启 | 记录每个 switch 的值 |
| 2 | 查看 `Activity` 行 | 如果 app 已自动启动 Live Activity，右侧显示 8 位 activity id；如果系统暂不可用，状态文案必须显示 `Unavailable: ...` 而不是空白 | 记录 activity id 或错误文案 |
| 3 | 查看 `Token streaming` section | `Stream every reply token` 默认为关闭；`Delivery` 默认为 `Foreground only` | 记录 switch 和 picker 文本 |
| 4 | 查看 `Private APNs payloads` section | `Allow private content in APNs` 默认为关闭；关闭时不显示 message body/contact/raw context/stepper 子开关 | 记录可见控件列表 |

通过标准：默认状态与预期完全一致；敏感 APNs 子开关默认不可见。

---

## TC-IOS-030 自动启动 Live Activity

目的：确认 app 不只是有 controller 文件，而是真正调用 `Activity.request(...)`。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 终止 app 后重新 `build_run_sim` | App 启动成功 | 记录 runtimeLogPath |
| 2 | 进入 Settings | `Activity` 行显示非 `Inactive` 的 8 位 id，例如 `00B16366` | 记录 activity id |
| 3 | 查看状态文案 | 状态显示 `Active <同一个 8 位 id>`，不能只显示 `Not started` | 记录状态文案 |
| 4 | 立即再次点击 `Start` | activity id 不应换成新的；状态仍是 `Active <原 id>` | 记录点击前后 id |

通过标准：进入 Settings 前无需手动点击 Start，就能看到 Active 状态。

---

## TC-IOS-031 Home Screen Dynamic Island 展示

目的：确认用户在 iOS 系统层能看到灵动岛内容。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 确保 TC-IOS-030 中 activity 状态为 Active | Settings 显示 active id | 记录 active id |
| 2 | 按 Home 回到桌面 | App 进入后台，Home Screen 可见 | 记录截图 |
| 3 | 截图顶部灵动岛 | 灵动岛不是空黑岛；左侧至少显示 `N`，右侧显示 `•` 或 token 数字 | 记录截图路径 |
| 4 | 调用 UI snapshot | 系统 UI target 中有可点击元素，label 类似 `N, •` 或 `N, 1` | 记录 elementRef 和 label |

通过标准：必须在系统 UI 层看到 Live Activity 元素。只看 Settings 里 `Active` 不算通过。

---

## TC-IOS-032 点击灵动岛回 app

目的：验证 `widgetURL`/tap-to-app 不是只写在代码里，而是系统层实际可点击。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 在 Home Screen 上取得 Dynamic Island 元素 | snapshot 中存在 `N, •` 或 `N, 1` target | 记录 elementRef |
| 2 | 点击该 Dynamic Island 元素 | Nomi app 被拉到前台 | 记录点击后的 screenshot |
| 3 | 检查前台页面 | 回到 Nomi；如果点击前最后页面是 Settings，则仍显示 Settings；`Activity` 仍为 active | 记录 UI 文本 |
| 4 | 检查没有崩溃 | runtime log 没有 crash、fatal error、uncaught exception | 记录 runtimeLogPath 中检索结果 |

通过标准：点击系统灵动岛后 app 前台可见，并且状态没有丢失。

---

## TC-IOS-033 Preview 更新内容

目的：验证本地 Live Activity 可以更新内容，不只停留在 idle 状态。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 进入 Settings，确认 Activity active | `Activity=<id>`，状态 `Active <id>` | 记录 id |
| 2 | 点击 `Preview` | Settings 状态文案变为 `Preview sent`；activity 不应变成 `Inactive` | 记录点击后的 Activity 行和状态文案 |
| 3 | 按 Home 回桌面 | Dynamic Island 仍存在 | 记录截图 |
| 4 | 调用 UI snapshot | Dynamic Island label 应从 idle 的 `N, •` 变成能反映 chat streaming 的 `N, 1` 或同等 token 序号状态 | 记录 label |
| 5 | 点击 Dynamic Island 回 app | App 前台打开；不崩溃 | 记录截图和 runtime log |

通过标准：Preview 后 activity 仍 active，并且系统层展示发生可观察变化。若状态变为 `Inactive`，判定 FAIL。

---

## TC-IOS-034 Stop 隐藏 Live Activity

目的：确认用户能结束灵动岛常驻状态。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | Settings 中点击 `Stop` | `Activity` 行变为 `Inactive`；状态文案为 `Stopped` | 记录 UI 文本 |
| 2 | 按 Home 回桌面 | Dynamic Island 中不再显示 `N, •` 或 `N, 1` | 记录截图 |
| 3 | 调用 UI snapshot | 不存在 label 为 `N, •`、`N, 1` 的 Dynamic Island target | 记录 snapshot 检索结果 |
| 4 | 回 app 后点击 `Start` | 重新出现新的 active id；状态为 `Active <new id>` | 记录新旧 id |

通过标准：Stop 后系统层活动消失，Start 后可重新创建。

---

## TC-IOS-035 Live Activity 开关行为

目的：确认 `Show Nomi in Dynamic Island` 开关真正控制行为，而不是只改变 UI。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 在 Settings 关闭 `Show Nomi in Dynamic Island` | 当前 activity 结束；状态显示 `Stopped` 或 `Disabled`；Activity 行为 `Inactive` | 记录 UI 文本 |
| 2 | 点击 `Start` | 不应启动 activity；状态显示 `Disabled` | 记录 UI 文本 |
| 3 | 按 Home | Dynamic Island 不显示 Nomi 元素 | 记录截图和 snapshot |
| 4 | 回 app，重新开启开关 | app 自动启动或点击 Start 后启动；Activity 行显示新 id | 记录新 id |

通过标准：开关关闭时不能创建或保留 Live Activity。

---

## TC-IOS-036 点击回 app 开关行为

目的：确认 `Open app when tapping Dynamic Island` 开关不是装饰性开关。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 开启 `Show Nomi in Dynamic Island`，关闭 `Open app when tapping Dynamic Island` | Activity 仍可显示，但点击回 app 行为应被禁用或退化为不带 deep link 的系统默认行为 | 记录 UI 状态 |
| 2 | 按 Home，确认 Dynamic Island 显示 Nomi | 系统层有 Nomi Live Activity | 记录 snapshot |
| 3 | 点击 Dynamic Island | 预期不应 deep link 到具体页面；若产品定义为完全不打开 app，则不应打开 app | 记录实际是否打开 app |
| 4 | 重新开启该开关，再点击 Dynamic Island | 应打开 Nomi app | 记录点击前后截图 |

通过标准：开关必须改变点击行为。当前如果关闭开关后仍直接打开 app，应记录为 GAP。

---

## TC-IOS-040 Deep Link：Chat

目的：验证 `nomi://chat?conversation_id=...` 能把 route 传到 Chat 页面。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 确保 app 已启动并在 Chat tab | Chat 页面显示 `Private-cloud assistant chat` | 记录截图 |
| 2 | 打开 URL `nomi://chat?conversation_id=ios-reg-chat-001` | app 保持或回到前台 | 记录打开方式和时间 |
| 3 | 查看 Chat 页面 | 副标题变为 `Conversation ios-reg-chat-001` | 记录 snapshot 文本 |
| 4 | 打开无参数 URL `nomi://chat` | Chat 页面副标题回到或保持通用聊天状态，不能崩溃 | 记录 UI 文本 |

通过标准：conversation id 精确显示，且无参数不会崩溃。

---

## TC-IOS-041 Deep Link：Suggestion

目的：验证 suggestion deep link 能保留目标 suggestion id。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 打开 URL `nomi://suggestion?id=ios-reg-suggestion-001` | app 前台打开 | 记录截图 |
| 2 | 点击 `Suggestions` tab | `Current route` section 显示 `Suggestion ios-reg-suggestion-001` | 记录 snapshot 文本 |
| 3 | 检查建议列表 placeholder | 在没有后端配置时仍显示 `Connect to your Nomi server to load proactive suggestions.` | 记录 UI 文本 |
| 4 | 打开 URL `nomi://suggestion` | 无 id 时不得把 route 更新成空 suggestion；当前 route 不应被错误覆盖 | 记录打开前后 Current route |

通过标准：有效 id 精确显示；无效 URL 不产生空白或崩溃。

---

## TC-IOS-042 Deep Link：Task

目的：验证任务类 Live Activity 可以跳到任务上下文。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 打开 URL `nomi://task?id=ios-reg-task-001` | app 前台打开 | 记录截图 |
| 2 | 点击 `Suggestions` tab | `Current route` section 显示 `Task ios-reg-task-001` | 记录 UI 文本 |
| 3 | 打开 URL `nomi://task` | 无 id 时不得崩溃，不得显示 `Task ` 空 id | 记录 Current route |

通过标准：task id 精确显示，错误 URL 安全处理。

---

## TC-IOS-043 Deep Link：Settings

目的：验证设置类 deep link 能被解析，并暴露当前实现是否自动切到 Settings。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 打开 URL `nomi://settings/live-activity` | app 前台打开且 route 被解析为 live activity settings | 记录打开后页面 |
| 2 | 如果当前页面不是 Settings，手动点击 Settings tab | Settings 页面可见，Dynamic Island section 可见 | 记录 UI 文本 |
| 3 | 记录是否自动切 tab | 产品期望应自动进入 Settings；若当前只是前台打开但不切 tab，记录为 GAP 或待增强 | 记录实际行为 |

通过标准：至少不能崩溃；产品级通过要求自动到 Settings。

---

## TC-IOS-050 Token streaming 设置

目的：验证 token 级回复开关和 delivery picker 的用户可见行为。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | Settings 中打开 `Stream every reply token` | switch 变为开启 | 记录 switch 状态 |
| 2 | 点击 `Delivery` picker | 可选择 `Foreground only`、`APNs best effort`、`Foreground and APNs` | 记录选项列表截图 |
| 3 | 选择 `APNs best effort` | picker 显示 `APNs best effort` | 记录 UI 文本 |
| 4 | 选择 `Foreground and APNs` | picker 显示 `Foreground and APNs` | 记录 UI 文本 |
| 5 | 关闭并重开 app | 产品预期：设置应保持上次选择；若恢复默认值，记录为 GAP | 记录重启前后设置 |

通过标准：选择即时生效且重启后不丢失。当前若不持久化，不能判 PASS。

---

## TC-IOS-051 Chat 输入和 token 级本地更新

目的：验证 token streaming 不只是设置项，而能在真实聊天中更新 Live Activity。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 打开 Chat tab | 显示输入框 `Ask Nomi` | 记录截图 |
| 2 | 输入 `请用一句话回复：iOS token streaming regression` | 输入框显示完整文本 | 记录输入后截图 |
| 3 | 查找并点击发送按钮或提交动作 | 产品预期应能发送消息到后端；如果没有发送按钮或 return 不发送，记录为 GAP | 记录可用动作 |
| 4 | 发送后观察 Chat UI | 应出现用户消息和 Nomi 回复流式文本 | 记录逐步截图 |
| 5 | 同时按 Home 查看 Dynamic Island | token 级更新时 compact trailing 数字应递增，或 expanded 内容显示最新片段 | 记录每次 snapshot label |

通过标准：真实聊天能触发 Live Activity token 更新。当前如果 ChatView 只有输入框没有发送链路，判定 GAP。

---

## TC-IOS-060 Sensitive APNs UI 开关

目的：验证敏感内容开关默认隐藏，用户显式打开后才出现子选项和风险提示。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 确认 `Allow private content in APNs` 关闭 | 不显示 `Include message body`、`Include contact names`、`Include raw private context`、`Payload limit` | 记录可见控件 |
| 2 | 打开 `Allow private content in APNs` | 出现风险提示：`Private message text may pass through Apple Push Notification service...` | 记录完整提示文本 |
| 3 | 打开 `Include message body` | switch 为开启 | 记录状态 |
| 4 | 打开 `Include contact names` | switch 为开启 | 记录状态 |
| 5 | 打开 `Include raw private context` | switch 为开启 | 记录状态 |
| 6 | 调整 `Payload limit` stepper | 文本中的数字按 100 步进变化，且范围不超过 0...3400 | 记录调整前后数值 |
| 7 | 关闭 `Allow private content in APNs` | 子选项全部隐藏；再次打开时产品预期应保留或明确重置，实际行为必须记录 | 记录再次打开后的子选项状态 |

通过标准：敏感选项必须由父开关显式控制，并且风险提示可见。

---

## TC-IOS-061 Safe mode 后端 payload

目的：确认安全模式不会把 Gmail/WhatsApp 正文、联系人、raw private context 放进 APNs payload。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 后端注册 iOS device，settings 中 `sensitive_apns_payload_enabled=false` | 注册接口返回 2xx；数据库 `ios_devices.settings` 中敏感开关为 false | 记录请求、响应、DB 行 |
| 2 | 注册 live activity update token | 注册接口返回 2xx；`ios_live_activities.status=active` | 记录 activity_id/update_token 前后缀 |
| 3 | 发送 proactive event，包含 `safe_event_title`、`safe_event_body`、`sensitive_contact`、`sensitive_raw_snippet` | APNs content-state 中 `payloadMode=safe`；title 为 `Nomi has a new suggestion`；body 为 `Open Nomi to review it.` | 记录 payload JSON |
| 4 | 检查 payload | 不得出现 `safe_event_title`、`safe_event_body`、`sensitive_contact`、`sensitive_raw_snippet` | 记录检索结果 |
| 5 | 检查 delivery audit | `ios_live_activity_events.payload_mode=safe`；`source_id` 是 suggestion id | 记录 DB 查询 |

通过标准：安全模式 payload 中没有任何私密正文或联系人。

---

## TC-IOS-062 Sensitive mode 后端 payload

目的：确认用户显式开启后，敏感 payload 才包含允许字段，并受长度限制。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 后端更新 device settings：`sensitive_apns_payload_enabled=true`、`include_private_message_body=true`、`include_contact_names=true`、`include_raw_private_context=true`、`max_sensitive_payload_chars=2400` | 更新接口返回 2xx；DB settings 与请求一致 | 记录请求/响应/DB 行 |
| 2 | 发送包含私密正文和联系人上下文的 proactive event | content-state 中 `payloadMode=sensitive` | 记录 payload |
| 3 | 检查 title/body | title/body 可以包含用户允许的私密摘要 | 记录实际 title/body |
| 4 | 检查 privateContext | 可包含 `contact`、`channel`、`rawSnippet`，且只在敏感模式出现 | 记录 privateContext |
| 5 | 发送超长 raw snippet | payload `truncated=true` 或 body/rawSnippet 被裁剪到预算内 | 记录 payload 字节数和截断字段 |

通过标准：敏感内容只在显式允许后出现，且长度受控。

---

## TC-IOS-070 Server config 和设备注册

目的：验证 iOS app 能把设备、settings、activity token 注册给后端。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 在 app 中查找 server URL/password 配置入口 | 产品预期应能输入后端 URL 和 `x-par-password` | 记录是否存在入口 |
| 2 | 配置本地或私有云后端 | AppState 中应产生 `serverConfig`，后续 API client 可用 | 记录 UI 和 Keychain 状态 |
| 3 | 启动 Live Activity | 若 serverConfig 存在，app 应注册 update token 到 `/api/ios/live-activities/register` | 记录后端请求或 DB 行 |
| 4 | 更新 Settings | app 应调用 `/api/ios/devices/{device_id}/settings` 同步设置 | 记录后端请求或 DB 行 |

通过标准：从 iOS UI 到后端 DB 有完整链路。当前如果 app 没有 server config UI，记录为 GAP。

---

## TC-IOS-080 Proactive suggestion 远程更新

目的：验证 worker/Redis/APNs bridge 可以把主动建议推到 iOS Live Activity。

前置条件：需要真实 APNs 配置或可替代的 fake APNs 观测环境。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 设置 `ENABLE_IOS_LIVE_ACTIVITY_BRIDGE=true` 并启动后端 | 后端 lifespan 启动 iOS bridge loop | 记录启动日志 |
| 2 | iOS 设备注册 active live activity | DB 中 `ios_live_activities.status=active` | 记录 DB 行 |
| 3 | 向 Redis realtime channel 发布 `proactive_message` | bridge 收到事件并构造 APNs payload | 记录 Redis event 和后端日志 |
| 4 | 查看 iOS Dynamic Island | 显示 Nomi suggestion 状态；expanded bottom 显示 safe/sensitive 对应文案 | 记录截图 |
| 5 | 查看 delivery audit | `ios_live_activity_events` 新增一行，event_type=`proactive_message`，delivery_status 为 `sent` 或 fake client 指定状态 | 记录 DB 行 |

通过标准：不是只看到 Redis publish 成功，而是 iOS UI 和 delivery audit 都有结果。

---

## TC-IOS-081 App Intents：Done/Dismiss

目的：验证 expanded Dynamic Island 上的快捷按钮能调用后端更新 suggestion。

前置条件：Dynamic Island 当前 state 中有非空 `suggestionId`，并且 app/server config 可用。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 触发 suggestion Live Activity | expanded Dynamic Island 中出现 suggestion title/body | 记录截图 |
| 2 | 长按或展开 Dynamic Island | 展开区域显示 `Done`、`Dismiss` 按钮 | 记录截图 |
| 3 | 点击 `Done` | App Intent 调用 `PATCH /api/suggestions/{id}`，status=`done` | 记录后端请求和 DB 行 |
| 4 | 重新触发 suggestion，点击 `Dismiss` | App Intent 调用同一接口，status=`dismissed` | 记录后端请求和 DB 行 |

通过标准：按钮不只是显示，必须产生后端状态变更。若无 serverConfig 或按钮不出现，记录 GAP。

---

## TC-IOS-090 Lock Screen Live Activity

目的：验证锁屏形态，不只看 Home Screen compact island。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 确保 Live Activity active | Settings 显示 active id | 记录 id |
| 2 | 按 Home 后按 Lock/Side button | 设备进入锁屏 | 记录截图 |
| 3 | 点亮锁屏 | 锁屏 Live Activity 卡片显示 Nomi 图标/标题和 body | 记录截图 |
| 4 | 点击锁屏 Live Activity | app 打开或系统要求解锁后打开 app | 记录行为 |

通过标准：锁屏卡片内容可见且可跳回 app。模拟器无法稳定验证时记录 BLOCKED，并在真机执行。

---

## TC-IOS-100 设置持久化和重启恢复

目的：确认用户设置不是临时内存状态。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 修改所有 Settings：关闭/开启不同开关，选择 `Foreground and APNs`，调整 payload limit | UI 立即显示新值 | 记录修改后的所有值 |
| 2 | 终止 app | app 退出 | 记录时间 |
| 3 | 重新启动 app | Settings 保持步骤 1 的值；Live Activity 根据 `liveActivityEnabled` 恢复正确状态 | 记录重启后所有值 |
| 4 | 若配置了后端，查询 device settings | 后端 settings 与 app UI 一致 | 记录 DB 行 |

通过标准：重启后设置不丢失，且本地/后端一致。当前如果重启后恢复默认值，记录 GAP。

---

## TC-IOS-110 APNs 真机远程更新

目的：验证真实 APNs、真实设备、真实灵动岛远程更新链路。

前置条件：

- Apple Developer Team 已配置。
- App 与 widget extension bundle id/provisioning 正确。
- App Group 已在 Developer Portal 创建并授权。
- `APNS_TEAM_ID`、`APNS_KEY_ID`、`APNS_BUNDLE_ID`、`APNS_PRIVATE_KEY_P8`、`APNS_ENVIRONMENT` 已配置。
- 真机安装的是相同 bundle id 的开发或 TestFlight 包。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 真机启动 Nomi | Settings 中 Activity active | 记录真机截图 |
| 2 | 后端确认 live activity update token 已注册 | DB 中有该真机 device_id 和 update_token | 记录 DB 行，token 只记录前后 6 位 |
| 3 | 发送 safe proactive event | APNs 返回 2xx；delivery audit 记录 `sent` | 记录 APNs status 和 DB 行 |
| 4 | 真机 Home Screen 查看 Dynamic Island | 显示 Nomi safe 文案，不显示私密正文 | 记录真机照片或截图 |
| 5 | 打开 sensitive settings 后再次发送事件 | Dynamic Island 显示允许的私密字段 | 记录截图和 payload |
| 6 | 点击 Dynamic Island | app 打开到相关上下文 | 记录截图 |

通过标准：真实 APNs 2xx、delivery audit、真机 UI 三者都通过。

---

## TC-IOS-120 失败和降级行为

目的：确认出错时用户能看到失败，不静默。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 在无 APNs key 环境启动后端 bridge | APNs client 返回 `misconfigured`，delivery audit 记录错误，不应崩溃后端 | 记录 audit 行和日志 |
| 2 | iOS 上关闭 Live Activity 开关 | 后端 bridge 不应给该 device 的 active activity 推送 | 记录 DB/audit 是否无新增 |
| 3 | 发送不支持的 event type | bridge 忽略该事件，不新增 audit | 记录 event 和 DB 查询 |
| 4 | update token 失效 | delivery_status=`failed`，error 有 APNs 返回文本前 500 字符 | 记录 audit error |

通过标准：失败路径可观测、可审计、不静默。

---

## TC-IOS-130 回归收尾记录

目的：保证执行结果可复盘。

| 步骤 | 操作 | 预期结果 | 实际结果记录 |
|---|---|---|---|
| 1 | 汇总所有用例状态 | 每个用例都有 `PASS/FAIL/BLOCKED/GAP` | 记录汇总表 |
| 2 | 汇总所有截图和日志 | 每个视觉验证至少一张截图；每次 build/run/test 有 log path | 记录证据路径 |
| 3 | 对 FAIL/GAP 建 issue 或更新 gap 文档 | 每个失败都有原因、影响、下一步 | 记录 gap id |
| 4 | 标出本轮不可验证项 | 真机/APNs/Developer Team 等外部阻塞必须写明 | 记录 BLOCKED 原因 |

通过标准：任何一个失败或 gap 都不能只写“待修”，必须写到具体步骤和证据。

---

## 执行汇总模板

| 用例 | 状态 | 关键证据 | 失败/GAP 原因 | 下一步 |
|---|---|---|---|---|
| TC-IOS-000 |  |  |  |  |
| TC-IOS-001 |  |  |  |  |
| TC-IOS-010 |  |  |  |  |
| TC-IOS-020 |  |  |  |  |
| TC-IOS-030 |  |  |  |  |
| TC-IOS-031 |  |  |  |  |
| TC-IOS-032 |  |  |  |  |
| TC-IOS-033 |  |  |  |  |
| TC-IOS-034 |  |  |  |  |
| TC-IOS-035 |  |  |  |  |
| TC-IOS-036 |  |  |  |  |
| TC-IOS-040 |  |  |  |  |
| TC-IOS-041 |  |  |  |  |
| TC-IOS-042 |  |  |  |  |
| TC-IOS-043 |  |  |  |  |
| TC-IOS-050 |  |  |  |  |
| TC-IOS-051 |  |  |  |  |
| TC-IOS-060 |  |  |  |  |
| TC-IOS-061 |  |  |  |  |
| TC-IOS-062 |  |  |  |  |
| TC-IOS-070 |  |  |  |  |
| TC-IOS-080 |  |  |  |  |
| TC-IOS-081 |  |  |  |  |
| TC-IOS-090 |  |  |  |  |
| TC-IOS-100 |  |  |  |  |
| TC-IOS-110 |  |  |  |  |
| TC-IOS-120 |  |  |  |  |
| TC-IOS-130 |  |  |  |  |

## 当前已知 GAP 检查点

以下检查点不允许跳过。执行时如果仍未实现，必须记录为 `GAP`：

- App 内 server URL/password 配置入口。
- iOS device registration 和 live activity token registration 的完整 UI 到后端链路。
- Settings 本地持久化和后端同步。
- Chat 页真实发送消息、展示回复、驱动 token-level Live Activity 更新。
- `Open app when tapping Dynamic Island` 开关是否真的影响 widgetURL/deep link 行为。
- 普通 APNs notification fallback。
- 真机 APNs、锁屏 Live Activity、生产签名、App Group。
