# iOS Dynamic Island Implementation Regression Report

日期：2026-06-18 15:32 CST

关联方案：`docs/superpowers/plans/2026-06-18-ios-dynamic-island-interaction-plan.md`

## 本轮已落地范围

- 后端：新增 iOS device/live activity schema、注册接口、settings 更新接口、safe/sensitive payload builder、APNs Live Activity client、delivery audit、Redis realtime bridge、token-level `chat_delta` hook，并复用现有 `/ws`、`stream_chat_to_websocket()`、Redis realtime event 和 suggestion/action 端点。
- iOS：新增 `ios_app/Nomi` SwiftUI 工程、ActivityKit attributes/controller、WidgetKit Dynamic Island/Lock Screen UI、tap-to-app deep links、App Intents quick actions、Keychain server config、Realtime client、API client、Settings UI。
- 配置：`.env.example` 增加 iOS Live Activity/APNs 开关和凭据字段，`APNS_BUNDLE_ID` 已对齐当前 iOS app bundle id `com.nomi.privatecloud`。

## 自动化验证

- 后端 focused 回归：
  - 命令：`python3 -m pytest runtime_api/tests/test_ios_live_activity.py runtime_api/tests/test_auth_and_model.py runtime_api/tests/test_vector_and_suggestions.py runtime_api/tests/test_realtime_ws.py runtime_api/tests/test_context_pack_and_chat.py -q`
  - 结果：`160 passed in 0.71s`
- iOS XCTest：
  - 工具：`xcodebuildmcp.test_sim`
  - 项目：`/Users/wrf/Documents/background/ios_app/Nomi/Nomi.xcodeproj`
  - scheme：`Nomi`
  - 模拟器：`iPhone 17 Pro`
  - 结果：`13 passed, 0 failed, 0 skipped`
  - build log：`/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/logs/test_sim_2026-06-18T07-31-15-609Z_pid93163_353cb33e.log`
  - xcresult：`/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/result-bundles/test_sim_2026-06-18T07-31-15-609Z_pid93163_641b1e91.xcresult`

## 模拟器烟测

- 工具：`xcodebuildmcp.build_run_sim`
- 结果：build、install、launch 均成功，无 warnings/errors。
- app path：`/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/DerivedData/Nomi-6e1727b42f83/Build/Products/Debug-iphonesimulator/Nomi.app`
- bundle id：`com.nomi.privatecloud`
- build log：`/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/logs/build_run_sim_2026-06-18T07-29-57-774Z_pid93163_07ed9bd3.log`
- runtime log：`/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/logs/com.nomi.privatecloud_2026-06-18T07-30-15-173Z_helperpid49783_ownerpid93163_a71d5761.log`
- os log：`/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/logs/com.nomi.privatecloud_oslog_2026-06-18T07-30-24-324Z_helperpid49996_ownerpid93163_ecafaf50.log`
- screenshot：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_2f3a6ce6-ad5d-4e23-81c8-4a17aed359c6.jpg`
- 观察：app 首屏可渲染，Chat/Suggestions/Settings tab 存在，Chat 页标题和输入框可见。

## 灵动岛本地展示修复

- 发现：最初实现只有 ActivityKit controller 和 WidgetKit UI，但 app 没有任何入口调用 `Activity.request(...)`，所以本地模拟器不会出现灵动岛内容。
- 修复：新增 `NomiLiveActivityStartup` 启动协调器；`RootView` 在 `liveActivityEnabled=true` 时自动启动本地 Live Activity；Settings 增加 Start/Preview/Stop 和当前 activity id/status；`NomiLiveActivityController` 支持恢复已有 activity、无后端配置时本地启动、手动 end。
- RED 验证：新增 `NomiLiveActivityStartupTests` 后，`xcodebuildmcp.test_sim` 先失败于 `cannot find type 'NomiLiveActivityStarting' in scope`。
- GREEN 验证：实现后 `xcodebuildmcp.test_sim` 通过，结果 `16 passed, 0 failed, 0 skipped`。
- 模拟器展示验证：用正常模拟器签名运行 `xcodebuildmcp.build_run_sim`，Settings 显示 `Activity 00B16366` / `Active 00B16366`；按 Home 退到桌面后，Dynamic Island 显示 `N, •`。
- Tap-to-app 验证：系统 UI 快照中 Dynamic Island 元素为 `N, •`，点击该元素后成功回到 Nomi Settings。
- 展示截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_cc162049-81a2-46a3-8a9b-7de5f6ee04b9.jpg`
- 注意：用 `CODE_SIGNING_ALLOWED=NO` 构建的模拟器包可以跑测试，但不适合作为灵动岛视觉验证方式；Live Activity/Widget 展示依赖系统能力和签名/entitlements，视觉验证应使用正常模拟器签名 build/run。

## 未闭环项

详见：`docs/superpowers/reports/2026-06-18-ios-dynamic-island-implementation-gaps.md`
