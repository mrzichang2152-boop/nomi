# iOS Dynamic Island 完整验收矩阵

日期：2026-06-18
工程：`/Users/wrf/Documents/background/ios_app/Nomi/Nomi.xcodeproj`
Scheme：`Nomi`
Bundle ID：`com.nomi.privatecloud`
执行设备：优先 `iPhone 17 Pro` simulator；真机/APNs 项单独标记。

## 验收原则

这份文档用于补齐“只验证结构、没有验证真实行为”的缺口。每个用例都必须记录：

- 操作过程：精确到点击哪个 tab、哪个按钮、输入什么文本、触发哪个 URL 或接口。
- 预期结果：精确到 UI 文案、Dynamic Island label、Lock Screen 文案、接口字段、日志路径。
- 实际结果：截图路径、snapshot 文本、接口响应、测试输出或 BLOCKED/GAP 原因。
- 状态：`PASS`、`FAIL`、`BLOCKED`、`GAP`。

## 覆盖范围

### A. 构建和基础导航

`ACC-IOS-001` 环境基线
步骤：
1. 调用 `xcodebuildmcp.session_show_defaults`。
2. 若 defaults 为空，设置 project、scheme、simulator、bundleId。
3. 调用正常签名 `xcodebuildmcp.build_run_sim`。
4. 获取首屏 snapshot。

预期：
- project 为 `ios_app/Nomi/Nomi.xcodeproj`。
- scheme 为 `Nomi`。
- simulator 为 Dynamic Island 机型。
- build/run 成功且 diagnostics 无 errors。
- 首屏显示 `Nomi`、`Private-cloud assistant chat`、`Chat/Suggestions/Settings` 三个 tab。

`ACC-IOS-002` 自动化基线
步骤：
1. 执行 `xcodebuildmcp.test_sim` with `CODE_SIGNING_ALLOWED=NO`。
2. 执行后端 focused pytest。

预期：
- XCTest 失败数为 0。
- 后端 focused pytest 失败数为 0。
- 覆盖 settings、deep link、Live Activity state、APNs payload、fallback、Chat send pipeline。

`ACC-IOS-003` 三个 tab 导航
步骤：
1. 从 Chat 点击 Suggestions。
2. 从 Suggestions 点击 Settings。
3. 从 Settings 点击 Chat。

预期：
- Suggestions 显示 `No deep link selected` 和 server placeholder。
- Settings 显示 Server、Dynamic Island、Token streaming、Private APNs payloads。
- Chat 回到输入和消息区域。

### B. Settings 和持久化

`ACC-IOS-010` Settings 默认值和文案
步骤：
1. 打开 Settings。
2. 记录 Server section。
3. 记录 Dynamic Island section。
4. 记录 Token streaming section。
5. 记录 Private APNs payloads section。

预期：
- Server section 有 `Base URL`、`Password`、`Save server`、server 状态。
- `Show Nomi in Dynamic Island` 开启。
- `Open target page when tapping Dynamic Island` 可见。
- `Notification fallback` 开启。
- `Stream every reply token` 默认关闭，Delivery 默认 `Foreground only`。
- `Allow private content in APNs` 默认关闭，敏感子项隐藏。

`ACC-IOS-011` Settings 持久化
步骤：
1. 修改 `Open target page when tapping Dynamic Island`。
2. 修改 `Stream every reply token` 和 Delivery。
3. 修改 sensitive APNs 子开关和 payload limit。
4. 终止并重启 app。
5. 重新进入 Settings。

预期：
- 重启后所有可持久化开关保持修改值。
- 如果某项因 UI 自动化限制未改，必须记录未覆盖。

`ACC-IOS-012` Server config 保存和注册尝试
步骤：
1. 启动本地假后端。
2. Settings 中输入 `Base URL` 和 `Password`。
3. 点击 `Save server`。
4. 观察 app 状态和假后端请求。

预期：
- app server 状态从 `Server not configured` 变为保存/连接相关文案。
- 假后端收到 `/api/ios/devices/register` 请求。
- 请求包含 `device_id`、`settings`、`apns_environment`。

### C. 基础消息收发

`ACC-IOS-020` 未配置服务器时发送失败可见
步骤：
1. 确保没有 server config 或配置不可用服务器。
2. Chat 输入 `Hello Nomi no server`。
3. 点击 Send。

预期：
- 输入框保留原文。
- 页面显示 `Server not configured` 或明确网络错误。
- 不出现假成功的 assistant 回复。

`ACC-IOS-021` 本地假后端基础消息收发
步骤：
1. 启动本地假后端，提供 `/api/chat`、`/api/ios/devices/register`、`/api/ios/devices/{id}/settings`。
2. 在 app 保存假后端 URL 和 password。
3. Chat 输入 `Hello Nomi acceptance`。
4. 点击 Send。
5. 查看 Chat UI 和假后端日志。

预期：
- 假后端收到 `POST /api/chat`。
- 请求 header 包含 `x-par-password`。
- 请求 body 中 `message=Hello Nomi acceptance`、`client_type=ios`、`client_request_id` 非空。
- Chat UI 出现用户消息 `Hello Nomi acceptance`。
- Chat UI 出现 assistant 回复，例如 `Acceptance reply from local server`。
- 状态显示 `Sent`。

`ACC-IOS-022` token streaming 驱动灵动岛
步骤：
1. Settings 开启 `Stream every reply token`。
2. Delivery 选择 `Foreground and APNs` 或保持本地前台可更新模式。
3. 确保 Live Activity active。
4. 发送一条可返回多词回复的消息。
5. 发送后按 Home 查看 Dynamic Island。

预期：
- Chat 消息发送成功。
- Dynamic Island compact trailing 从 `•` 变为 token 序号，例如 `N, 4` 或更高。
- 该数字与本地分块更新次数一致或可解释。

### D. 灵动岛内容展示

`ACC-IOS-030` idle compact 内容
步骤：
1. Settings 中确认 Live Activity active。
2. 按 Home。
3. 获取 Home Screen snapshot 和截图。

预期：
- Dynamic Island target 存在。
- compact label 至少包含 `N`。
- idle 状态 trailing 为 `•`。

`ACC-IOS-031` preview compact 内容
步骤：
1. 回到 Settings。
2. 点击 `Preview`。
3. 按 Home。
4. 获取 Home Screen snapshot 和截图。

预期：
- Settings 状态为 `Preview sent`。
- Dynamic Island compact label 显示 token 序号，例如 `N, 1`。
- 不得变成 `Inactive` 或 `Stopped`。

`ACC-IOS-032` expanded Dynamic Island 内容
步骤：
1. Home Screen 上找到 Dynamic Island elementRef。
2. 对该 elementRef 执行 long press。
3. 获取 snapshot 和截图。

预期：
- expanded 区域显示 `Nomi`。
- expanded bottom 显示 `Nomi is replying` 或当前 state title。
- expanded body 显示 preview/chat 片段，或 safe body。
- 如果模拟器不暴露 expanded 文本到 accessibility，必须用截图记录视觉证据。

`ACC-IOS-033` Lock Screen 内容
步骤：
1. Live Activity active。
2. 按 Lock/Side button。
3. 点亮锁屏。
4. 获取截图或 snapshot。

预期：
- Lock Screen card 显示 `N` 图标。
- title 为 `Nomi` 或当前 state title。
- body 为 `Ready`、`Generating response` 或 preview/chat 内容。

`ACC-IOS-034` 点击行为和 deep link 语义
步骤：
1. 开启 `Open target page when tapping Dynamic Island`。
2. 点击 Dynamic Island。
3. 关闭该开关。
4. 点击 Dynamic Island。

预期：
- 开启时应进入目标页面或默认 Chat。
- 关闭时不应携带具体 route；如果系统仍拉起宿主 app，记录为平台行为，不判实现 bug。

### E. 深链和路由

`ACC-IOS-040` Chat deep link
步骤：打开 `nomi://chat?conversation_id=ios-reg-chat-001`。
预期：Chat 显示 `Conversation ios-reg-chat-001`。

`ACC-IOS-041` Suggestion deep link
步骤：打开 `nomi://suggestion?id=ios-reg-suggestion-001`。
预期：自动或手动进入 Suggestions 后显示 `Suggestion ios-reg-suggestion-001`。

`ACC-IOS-042` Task deep link
步骤：打开 `nomi://task?id=ios-reg-task-001`。
预期：Suggestions 显示 `Task ios-reg-task-001`。

`ACC-IOS-043` Settings deep link
步骤：打开 `nomi://settings/live-activity`。
预期：自动切到 Settings。

### F. 后端契约和隐私

`ACC-IOS-050` safe payload
步骤：调用后端 payload builder 或 focused pytest。
预期：safe state 不包含私密 title/body/contact/raw context。

`ACC-IOS-051` sensitive payload
步骤：开启 sensitive settings 后构造 payload。
预期：只包含用户允许的字段，并受长度限制。

`ACC-IOS-052` APNs alert fallback
步骤：模拟 Live Activity update 失败。
预期：后端调用普通 alert fallback，并记录 `notification_fallback_sent`。

`ACC-IOS-053` settings sync contract
步骤：本地假后端接收 settings PATCH。
预期：收到 snake_case settings，包含 token streaming、deep link、sensitive flags。

### G. 系统限制和真机项

`ACC-IOS-060` 真机 APNs Live Activity
预期：需要 Apple Developer Team、APNs key、真实 Dynamic Island iPhone、provisioning profile。缺失时 `BLOCKED`。

`ACC-IOS-061` 普通 APNs device token
预期：iOS app 需要请求通知权限并注册 APNs device token。未实现时 `GAP`。

`ACC-IOS-062` App Intents Done/Dismiss
预期：需要 suggestion Live Activity state 和 server config。未能构造真实 suggestion state 时 `GAP/BLOCKED`。

## 汇总模板

| 用例 | 状态 | 关键证据 | 失败/GAP/BLOCKED 原因 | 下一步 |
|---|---|---|---|---|
| ACC-IOS-001 |  |  |  |  |
| ACC-IOS-002 |  |  |  |  |
| ACC-IOS-003 |  |  |  |  |
| ACC-IOS-010 |  |  |  |  |
| ACC-IOS-011 |  |  |  |  |
| ACC-IOS-012 |  |  |  |  |
| ACC-IOS-020 |  |  |  |  |
| ACC-IOS-021 |  |  |  |  |
| ACC-IOS-022 |  |  |  |  |
| ACC-IOS-030 |  |  |  |  |
| ACC-IOS-031 |  |  |  |  |
| ACC-IOS-032 |  |  |  |  |
| ACC-IOS-033 |  |  |  |  |
| ACC-IOS-034 |  |  |  |  |
| ACC-IOS-040 |  |  |  |  |
| ACC-IOS-041 |  |  |  |  |
| ACC-IOS-042 |  |  |  |  |
| ACC-IOS-043 |  |  |  |  |
| ACC-IOS-050 |  |  |  |  |
| ACC-IOS-051 |  |  |  |  |
| ACC-IOS-052 |  |  |  |  |
| ACC-IOS-053 |  |  |  |  |
| ACC-IOS-060 |  |  |  |  |
| ACC-IOS-061 |  |  |  |  |
| ACC-IOS-062 |  |  |  |  |
