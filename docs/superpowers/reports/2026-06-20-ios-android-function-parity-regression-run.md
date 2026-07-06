# iOS Android Function Parity Regression Run

日期：2026-06-21

设备：
- iPhone 17 Pro Simulator，iOS 26.2，id `51B3E250-B88F-467C-8299-6EC82F98CC9F`
- iPhone 16e Simulator，iOS 26.2，id `AFA011E7-5DFD-45A3-9DBD-9DE3E1ED907D`

真实服务器：
- Base URL: `http://206.119.171.141`
- Password: `par-dev`

范围：iOS 编译、单元测试、模拟器 UI 主入口验收、真实服务器连接状态验收、Dynamic Island 模拟器展示/跳转验收、Chat/Suggestions/Tasks/Accounts/Career 真实后端内容级验收。

## 验收口径

本轮纠正上一轮不达标口径：

- 不再把 `127.0.0.1`、`localhost`、host-only 临时代理或本机 Docker compose 当作 iOS 主流程通过证据。
- HTTP 200 只证明请求被服务接收，不能单独作为通过证据；必须检查响应正文或关键字段是否和测试意图一致、是否合理正确。
- iOS UI 验收必须同时记录：配置的真实服务器、UI 状态、发送内容、服务端回复内容、用户可见状态。

## 结论

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| iOS 单元测试 | PASS，65 passed / 0 failed / 0 skipped | `test_sim_2026-06-21T13-20-44-028Z`，xcresult `/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/result-bundles/test_sim_2026-06-21T13-20-44-028Z_pid13601_f314f949.xcresult` |
| iOS ATS 真实服务器阻断 | FIXED | 初次配置 `http://206.119.171.141` 点击 `Save and test server` 失败，UI 报错 `The resource could not be loaded because the App Transport Security policy requires the use of a secure connection.`；已在 `Info.plist` 只为 `206.119.171.141` 增加最小 HTTP 例外，并由 `NomiInfoPlistTests.testPrivateCloudHttpServerIsAllowedByAppTransportSecurity` 覆盖 |
| 构建并启动 | PASS | bundle `com.nomi.privatecloud`，process `31667`，build log `/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/logs/build_run_sim_2026-06-21T08-34-39-559Z_pid22312_54ea98e2.log` |
| 真实服务器健康检查 | PASS | `curl http://206.119.171.141/health` 返回正文 `{"status":"ok"}` |
| 真实模型状态 | PASS | `GET /api/model/status` 返回 active provider `4sapi_primary`、model `qwen3.6`、`unavailable=false` |
| 真实服务器 Chat 内容级验证 | PASS | `POST /api/chat` prompt 要求返回固定 token 和算术结果；响应正文为 `NOMI_REAL_SERVER_OK_20260621 and 19+23=42.`，不是只看 HTTP 200 |
| iPhone 16e 保存并测试真实服务器 | PASS | Settings 配置 `http://206.119.171.141` / `par-dev` 后，点击 `Save and test server`，顶部和 Settings 均显示 `Server connected`；当前截图 `/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_e09a53f6-c8a2-4677-8e67-2afc84883b5e.jpg` |
| iOS Chat UI 真实服务器内容级收发 | PASS | 输入 `Regression validation on real server. Reply exactly: NOMI_IOS_REAL_SERVER_OK_20260621 and 19+23=42.`；Nomi 回复 `NOMI_IOS_REAL_SERVER_OK_20260621 and 19+23=42.`，状态 `Sent`；截图 `/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_1728a41d-3e46-4303-85a9-d6f59100edb0.jpg` |
| 首屏与功能入口交互 | PASS | 默认 Chat，其他能力收起；展开后可见 `Chat/Suggestions/Tasks/Accounts/Career/Settings`；选择二级 mode 后重新收起 |
| Suggestions 真实数据主流程 | PASS，有内容质量 gap | UI 显示真实建议标题/正文；`完成` 后 `ad3d151f-8e35-4d32-a471-06ad489a5685` 不再 open；`忽略` 后 `196bd80f-756a-4c4a-b08f-4d9e39694acf` 不再 open；截图 `/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_077d5b3b-6300-41c3-a72d-e23c9e251c9a.jpg`、`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_7c6851bc-add1-4ee5-9042-d34d4e136a9f.jpg` |
| Tasks 真实数据主流程 | PASS，有事件质量/UI gap | 真实创建 task `lta_d1216eda0d694d898d298afb32d74882`；UI 显示 task id、goal、`task.created`；Resume 后真实状态 `awaiting_executor` 且事件包含 `step.selected/step_packet.built`；Cancel 后真实状态 `cancelled` 且事件包含 `task.cancelled` reason `cancelled_from_ios`；截图 `/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_f8ebdca5-2d59-4cda-a5b5-9eff04c64b8d.jpg`、`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_344e00ed-0baf-4eb4-bfe3-af218dd8088a.jpg` |
| Accounts 真实数据主流程 | PASS | UI 显示 3 个 Nomi identities；collector/channel 显示真实状态；Gmail 经 Composio toolkit 合并后显示 `healthy` / `Already connected`；GitHub connect 接口返回 `connect.composio.dev` 授权链接；Search remote browser open 返回 `queued` 和 Google target；截图 `/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_54adcef1-d15b-4c2a-a03a-34701a57506f.jpg`、`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_0ed247e4-90e3-4ca2-923b-fe8a7e0294aa.jpg` |
| Career 真实数据主流程 | PASS，有内容质量 gap | 写入 profile token `IOS_CAREER_REAL_20260621` 后 UI 显示职业画像、`AI Agent Product Manager / Example AI` opportunity、application 状态；点击 `标记已投递` 后真实后端 `application_job_pm_001_upsert_stage` 为 `submitted/submitted/prepare_interview_if_replied`；截图 `/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_6ea4d826-9fff-4639-b6b2-7ad4a8364177.jpg`、`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_8de99f44-0d43-4254-b98e-bfcc635e3974.jpg` |
| Dynamic Island 模拟器展示和跳转 | PASS，真机 gap 仍保留 | iPhone 16e 无 Dynamic Island，不能作为通过证据；改用 iPhone 17 Pro Simulator 触发 `Preview` 后，主屏 compact 状态显示 `N` 和 unread `1`，点击灵动岛返回 Nomi Settings。展开态已修复左侧裁切和 raw source 格式问题，长按后显示 `N / 1 / Nomi / Chat / Nomi is replying / Local Dynamic Island preview`；截图 `/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_78a7448a-3dea-485f-892a-40f8da0a720c.jpg` |

## 已验证步骤

1. 纠正本机验证结论。
   预期：iOS 主流程不得以本机或临时代理为通过证据。
   实际：上一轮 `http://127.0.0.1:18081` 相关结论已作废；只保留为被纠正前的无效本地证据，不计入本轮 PASS。

2. 直接验证真实服务器健康状态。
   命令：`curl -sS http://206.119.171.141/health`
   预期：返回可解析 JSON，且服务状态为 ok。
   实际：返回 `{"status":"ok"}`。

3. 直接验证真实模型路由状态。
   命令：`curl -sS -H 'x-par-password: par-dev' http://206.119.171.141/api/model/status`
   预期：返回 active provider/model，且模型不可用标记不能为 true。
   实际：关键字段为 provider `4sapi_primary`、model `qwen3.6`、`unavailable=false`。

4. 直接验证真实服务器 Chat 语义输出。
   请求：`POST http://206.119.171.141/api/chat`，prompt 为 `Regression validation on real server. Reply with exactly this token and the arithmetic result, in one short sentence: NOMI_REAL_SERVER_OK_20260621 and 19+23=42.`
   预期：不能只看 HTTP 200；响应正文必须包含指定 token，且算术结果必须为 `42`。
   实际：响应正文包含 `NOMI_REAL_SERVER_OK_20260621 and 19+23=42.`，内容合理正确。

5. 在 iPhone 16e Nomi Settings 配置真实服务器。
   操作：Base URL 填 `http://206.119.171.141`，password 填 `par-dev`，点击 `Save and test server`。
   预期：若 iOS 网络栈可达真实服务器，应显示 `Server connected`。
   实际：修复前失败，UI 报错 `The resource could not be loaded because the App Transport Security policy requires the use of a secure connection.`，说明不是服务器不可达，而是 iOS ATS 拦截公网 HTTP。

6. 修复并验证 ATS 配置。
   操作：在 `Info.plist` 中只为 `206.119.171.141` 增加 `NSExceptionAllowsInsecureHTTPLoads=true`，不启用全局 `NSAllowsArbitraryLoads`。
   预期：测试能证明真实私有云 HTTP 域名被允许，且例外范围不能扩大到所有 HTTP。
   实际：先新增测试并看到缺少 ATS 配置时失败；补 `Info.plist` 后 targeted test 通过；全量 iOS 测试 `55 passed / 0 failed / 0 skipped`。

7. 重新构建并运行 iOS app。
   操作：通过 XcodeBuildMCP `build_run_sim` 构建并启动。
   预期：Nomi app 在 iPhone 16e Simulator 可运行。
   实际：bundle `com.nomi.privatecloud` 启动成功，process `31667`。

8. 再次在 iPhone 16e Nomi Settings 保存并测试真实服务器。
   预期：真实服务器配置保存后健康检查通过。
   实际：UI 显示 `Server connected`，说明 iOS app 已连到真实服务器。当前截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_e09a53f6-c8a2-4677-8e67-2afc84883b5e.jpg`。

9. 在 iOS Chat UI 做真实服务器内容级收发。
   操作：发送 `Regression validation on real server. Reply exactly: NOMI_IOS_REAL_SERVER_OK_20260621 and 19+23=42.`
   预期：用户消息出现在列表中，Nomi 回复必须包含同一 token 和正确算术结果，状态为 `Sent`。
   实际：Nomi 回复 `NOMI_IOS_REAL_SERVER_OK_20260621 and 19+23=42.`，状态为 `Sent`。截图证据：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_1728a41d-3e46-4303-85a9-d6f59100edb0.jpg`。

10. 验证首屏和功能入口交互。
    预期：默认进入 Chat，其他功能入口收起；展开后可以看到 Android parity 范围内的主要入口；选择二级 mode 后重新收起。
    实际：默认 Chat；点击 `Show Nomi tools` 后可见 `Chat/Suggestions/Tasks/Accounts/Career/Settings`；选择 Settings 后入口重新收起。

11. 验证 Suggestions 真实列表加载。
    预期：`GET /api/suggestions?limit=5` 返回真实建议数组，UI 显示标题和正文，不允许只看 HTTP 200。
    实际：接口返回 `可能值得关注`、`处理邮件待办` 等真实建议；UI 显示 `可能值得关注` 和 Gmail 会议建议正文。截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_077d5b3b-6300-41c3-a72d-e23c9e251c9a.jpg`。

12. 验证 Suggestions 完成写回。
    操作：点击第一条回归建议 `完成`。
    预期：UI 移除该建议，真实服务器 open 列表不再返回该 id。
    实际：UI 移除；`GET /api/suggestions?limit=10` 返回 `contains_completed_regression=false`，`ad3d151f-8e35-4d32-a471-06ad489a5685` 不再 open。

13. 验证 Suggestions 忽略写回。
    操作：点击污染重复建议 `忽略`。
    预期：UI 移除该建议，真实服务器 open 列表不再返回该 id。
    实际：UI 移除；`GET /api/suggestions?limit=10` 返回 `contains_dismissed_polluted=false`，`196bd80f-756a-4c4a-b08f-4d9e39694acf` 不再 open。截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_7c6851bc-add1-4ee5-9042-d34d4e136a9f.jpg`。

14. 验证 Tasks 真实任务创建和 UI 加载。
    操作：通过真实服务器创建 `IOS_TASK_REAL_20260621` 任务，打开 `nomi://task?id=lta_d1216eda0d694d898d298afb32d74882`。
    预期：UI 显示 task id、可读 goal、事件列表；接口返回 state/events 关键字段合理。
    实际：UI 显示 `Task lta_d1216eda0d694d898d298afb32d74882`、`iOS Tasks real-server validation IOS_TASK_REAL_20260621...`、事件 `task.created`；接口 state 为 `running/select_step`，事件包含 `task.created/route.decided/plan.proposed/plan.validated/memory.initialized/checkpoint.saved`。截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_f8ebdca5-2d59-4cda-a5b5-9eff04c64b8d.jpg`。

15. 验证 Tasks Resume。
    操作：点击 `Resume`。
    预期：真实服务器进入下一步执行等待状态，事件流包含下一步事件。
    实际：`GET /api/agent-tasks/lta_d1216eda0d694d898d298afb32d74882` 返回 `status=running`、`current_node=awaiting_executor`；events 包含 `step.selected` 和 `step_packet.built`，packet 中 `forbidden_actions=["browser.submit"]`，符合“不提交”的任务约束。

16. 验证 Tasks Cancel。
    操作：点击 `Cancel`。
    预期：真实服务器状态变为 cancelled，事件包含取消原因。
    实际：state 为 `cancelled/cancelled`，events 包含 `task.cancelled`，payload reason 为 `cancelled_from_ios`。截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_344e00ed-0baf-4eb4-bfe3-af218dd8088a.jpg`。

17. 验证 Accounts identities 和 collectors。
    预期：`/api/assistant-identities` 返回可读 identities，`/api/collectors/status` 和 Composio toolkit 状态能合并成 Android 一致的渠道状态。
    实际：接口返回 3 个 identities：`nomi_gmail_primary`、`nomi_whatsapp_primary`、`nomi_phone_primary`；UI 显示 Nomi 邮箱和两个手机号身份。collector 接口返回 8 个渠道；Composio readonly/write 都显示 `gmail connected=true`；iOS 修复后 Gmail UI 显示 `healthy` / `Already connected`。截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_54adcef1-d15b-4c2a-a03a-34701a57506f.jpg`、`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_0ed247e4-90e3-4ca2-923b-fe8a7e0294aa.jpg`。

18. 验证 Accounts 连接入口。
    预期：未连接 Composio 渠道能拿到授权链接，remote browser 渠道能排队打开真实目标。
    实际：`POST /api/integrations/composio/connect/github` 返回 `status=link_created` 且 redirect host 为 `connect.composio.dev`；`POST /api/browser/open` body `{"source":"search"}` 返回 `status=queued`、`target_url=https://www.google.com/`、`host_fragment=google.`。

19. 验证 Career board 真实数据加载。
    预期：`GET /api/career/board?limit=10` 返回 profile/opportunity/application，UI 显示可读内容。
    实际：先通过 `/api/career/profile/ingest` 写入 `IOS_CAREER_REAL_20260621` profile，响应 `writeback_performed=true`、`failed_count=0`；UI 显示该 profile、`AI Agent Product Manager`、`Example AI · upsert`、application 状态。截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_6ea4d826-9fff-4639-b6b2-7ad4a8364177.jpg`。

20. 验证 Career application patch。
    操作：点击 `application_job_pm_001_upsert_stage` 的 `标记已投递`。
    预期：UI 更新 application 状态，真实服务器写入 Android 同款字段 `status/stage/next_step/user_note`。
    实际：UI 显示 `submitted · submitted · prepare_interview_if_replied`；接口返回该 application `status=submitted`、`stage=submitted`、`next_step=prepare_interview_if_replied`、payload.user_note=`用户在 iOS 求职看板中标记已投递`。截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_8de99f44-0d43-4254-b98e-bfcc635e3974.jpg`。

21. 更换到支持 Dynamic Island 的模拟器。
    操作：确认当前 iPhone 16e Simulator 无 Dynamic Island，不再用它作为灵动岛展示证据；将 XcodeBuildMCP session defaults 切到 iPhone 17 Pro Simulator `51B3E250-B88F-467C-8299-6EC82F98CC9F`，重新 `build_run_sim`。
    预期：Nomi app 在支持 Dynamic Island 的模拟器上启动成功。
    实际：bundle `com.nomi.privatecloud` 启动成功，process `22877`，build log `/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/logs/build_run_sim_2026-06-21T13-02-50-021Z_pid13601_565eafc8.log`。

22. 验证 Dynamic Island compact 展示。
    操作：进入 Settings，确认 `Show Nomi in Dynamic Island` 和 `Open target page when tapping Dynamic Island` 均为开启；点击 `Preview`。
    预期：Settings 状态变为预览已发送；退到主屏后灵动岛 compact 区域展示 Nomi 活动。
    实际：Settings 显示 `Preview sent`；主屏灵动岛 compact 状态显示左侧 `N`、右侧 unread `1`。截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_469d1e60-5b4b-48a0-9e85-2c00e4f3f175.jpg`、`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_a7585faa-415c-444c-89c1-d875539a925b.jpg`。

23. 验证 Dynamic Island 点击跳转。
    操作：在主屏点击系统 snapshot 识别出的灵动岛目标 `N, 1`。
    预期：点击后回到 Nomi app，并进入对应 deep link 目标页面。
    实际：点击后回到 Nomi Settings，页面仍显示 Dynamic Island 设置和 `Preview sent`；截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_7b0550cb-3fb2-4656-85af-62f870cf6b6c.jpg`。

24. 验证 Dynamic Island 展开态内容。
    操作：回到主屏后长按灵动岛目标。
    预期：展开态应显示 Nomi 来源、阶段和预览正文，而不是空白或系统默认占位。
    实际：runtime snapshot 识别展开态为 `Nomi, chat, Nomi is replying, Local Dynamic Island preview`；截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_e3e04874-e22c-467b-8d87-3e432fe78095.jpg`。

25. 修复并复测 Dynamic Island 展开态排版。
    操作：将展开态 leading 区从 `Nomi/chat` 文本改为 20pt `N` 徽标，trailing 使用计数胶囊，bottom 统一展示 `Nomi`、格式化来源标签、标题和正文；重新 Stop/Start/Preview Live Activity。
    预期：左侧不再出现 `.Nomi` 这类被裁切文本；source 不再直接展示 raw `chat`，正文应能完整显示预览短句；点击展开态仍能回到 Nomi。
    实际：runtime snapshot 识别展开态为 `N, 1, Nomi, Chat, Nomi is replying, Local Dynamic Island preview`；视觉截图中左侧为圆形 `N`，右侧为 `1`，正文完整显示 `Local Dynamic Island preview`；点击展开态后回到 Nomi Settings，状态仍为 `Preview sent`。截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_78a7448a-3dea-485f-892a-40f8da0a720c.jpg`。

26. 验证 iOS 客户端可打开 Gmail/Google 登录页。
    操作：在 iPhone 17 Pro Simulator 的 Nomi Accounts 中，Gmail 已连接状态显示 `Already connected` 和新增 `Reconnect`；点击 `Reconnect`。
    预期：即便 Gmail 当前已连接，用户也能仅通过 iOS 客户端重新打开授权登录页，不需要登录服务器后台。
    实际：Safari 打开 `accounts.google.com`，页面显示 `使用 Google 账号登录`、`继续前往 Composio`、邮箱或电话号码输入框和 `下一步`。截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_1a61310b-3fed-4ed2-bfc4-de337f45b608.jpg`。

27. 验证 iOS 客户端可打开未连接 Google Calendar 授权页。
    操作：在 Nomi Accounts 中点击 `calendar` 行的 `Connect`。
    预期：未连接的 Google/Calendar Composio 账号能从 iOS 客户端打开授权登录页。
    实际：Safari 打开 `accounts.google.com`，页面显示 `使用 Google 账号登录`、`继续前往 Composio`、邮箱或电话号码输入框和 `下一步`。截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_c40d7565-e98f-41b8-8aa5-39893f5a3f95.jpg`。

28. 验证 iOS 客户端可打开 GitHub 授权页。
    操作：在 Nomi Accounts 中滚动到 `github` 行，点击 `Connect`。
    预期：非 Google 的 Composio 账号也能从 iOS 客户端打开对应登录/授权页。
    实际：Safari 打开 `github.com`，页面显示 `Sign in to GitHub to continue to Composio`、用户名/邮箱输入框、密码输入框和 `Sign in`。截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_868d6d9d-c0d8-48b7-b869-53f25a33331e.jpg`。

29. 验证 iOS 客户端可打开云主机 WhatsApp Web 登录页。
    操作：在 Nomi Accounts 中滚动到 `whatsapp` 行，点击 `Open browser`。
    预期：iOS 客户端打开内置 WKWebView/noVNC，连接云主机 Chromium，并导航到 `https://web.whatsapp.com/` 的登录或已登录会话页面。
    实际：首次打开进入云主机 Chromium 的 `web.whatsapp.com`，但页面显示 Chrome `Aw, Snap!` 崩溃页；点击远程页面的 `Reload` 后恢复为 WhatsApp Web 二维码登录页，页面显示 `Scan to log in`、二维码和 `Stay logged in on this browser`。截图：首次异常 `/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_6d630b42-883f-4caa-9b47-e3c6e143f16f.jpg`，Reload 后通过 `/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_5fc8826c-1f89-4e1f-913e-49fdc983e1f8.jpg`。

30. 跑完整 iOS 单元/集成测试。
    命令：XcodeBuildMCP `test_sim`，工程 `/Users/wrf/Documents/background/ios_app/Nomi/Nomi.xcodeproj`，scheme `Nomi`，模拟器 iPhone 17 Pro `51B3E250-B88F-467C-8299-6EC82F98CC9F`。
    预期：账号登录入口、noVNC URL、Composio 重连和既有 iOS parity 行为不能引入回归。
    实际：`67 passed / 0 failed / 0 skipped`；xcresult：`/Users/wrf/Library/Developer/XcodeBuildMCP/workspaces/background-c85850252be3/result-bundles/test_sim_2026-06-22T08-47-04-044Z_pid47618_2ee224a7.xcresult`。

31. 补测 iOS 客户端 LinkedIn 云主机登录页入口。
    操作：重新 build/run Nomi，进入 Accounts，点击 `Refresh` 后确认 `linkedin` 行显示 `Remote browser linkedin`；滚动使该行完整可见，点击 `Open browser`。
    预期：iOS 客户端打开内置 WKWebView/noVNC，云主机 Chromium 导航到 `https://www.linkedin.com/login` 并显示 LinkedIn 登录页。
    实际：iOS 客户端能打开 noVNC 云主机浏览器；真实服务器 `POST /api/browser/open` body `{"source":"linkedin"}` 返回 `status=queued`、`target_url=https://www.linkedin.com/login`、`host_fragment=linkedin.com`。但可视 Chrome 未切到 LinkedIn，仍停在 `web.whatsapp.com` 的崩溃/恢复页面；点击 Reload 后显示 WhatsApp QR 登录页，重新发送 LinkedIn open 命令后仍未切到 LinkedIn。截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_28412df1-e5d7-45f7-b7d0-fbe6b38b81aa.jpg`、`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_2cd93bf8-1961-4e9f-91d2-34e1f5f59265.jpg`。结论：LinkedIn 后端排队入口存在，但 iOS 可视登录页未通过，已记录 `GAP-IOS-ACCOUNT-LINKEDIN-NAV-013`。

32. 修复云主机浏览器切源和崩溃页恢复逻辑。
    操作：在 `chromium_runtime/app/runtime.py` 中调整 `execute_browser_open_command`：执行 open command 前保留上一次手动聚焦来源；当目标页不存在时优先复用上一手动来源对应的可视页；同 host 显式打开也重新 `goto` 目标 URL，以恢复 `Aw, Snap!` 这类崩溃页。
    预期：WhatsApp 首次打开遇到崩溃页时，下一次 `Open browser` 会重新导航恢复；从 WhatsApp 切 LinkedIn 时，不应导航隐藏的旧页，而应切换用户正在看的 noVNC 页面。
    实际：新增红灯测试先失败，修复后 `python3 -m pytest chromium_runtime/tests/test_runtime_recovery.py runtime_api/tests/test_browser_login_commands.py` 通过 `22 passed`。

33. 修复 iOS noVNC 顶部遮挡和客户端内切源问题。
    操作：将裸 `WKWebView` sheet 改为带本地控制栏的 `NomiWebWorkspaceSheetView`，顶部固定保留 `52pt` 控制区，提供关闭、刷新和来源菜单；来源菜单包含 WhatsApp、LinkedIn、Telegram、Search、Shopping。
    预期：云服务器浏览器标签/工具栏不再被 iOS 灵动岛/安全区压住；即使远端标签难点，用户也能直接在 iOS 客户端内切换云端浏览器来源。
    实际：新增 `NomiWorkbenchPresentationTests.testWebWorkspaceChromeKeepsRemoteTabsBelowLocalControls` 先编译失败，修复后 targeted test 通过；全量 iOS 测试通过 `68 passed / 0 failed / 0 skipped`。模拟器视觉验证显示顶部本地栏有 `LinkedIn`、`Cloud browser`、关闭、切换和刷新按钮；来源菜单可见 `WhatsApp/LinkedIn/Telegram/Search/Shopping`，LinkedIn 当前带 checkmark。截图：`/var/folders/1d/p162zt9n76q6wlz2jrk4hnxw0000gn/T/screenshot_optimized_ba287080-9343-4147-b4f4-26da42c783b4.jpg`。

34. 尝试将 runtime 修复部署到真实云主机。
    操作：尝试非交互 SSH 到 `root@206.119.171.141` 默认端口和 `10799` 端口，准备同步 `/opt/nomi` 并重建 `chromium-runtime`。
    预期：能进入服务器后执行最小服务级部署，使第 32 步 runtime 修复在线生效。
    实际：默认端口返回 `Permission denied (password).`，`10799` 返回 `Connection closed by 206.119.171.141 port 10799`；当前环境无法输入 SSH 密码或完成云端部署。因此 `GAP-IOS-ACCOUNT-WHATSAPP-RELOAD-012` 和 `GAP-IOS-ACCOUNT-LINKEDIN-NAV-013` 已有本地代码修复和测试证据，但线上关闭仍等待云端部署后复测。

## 未通过/未执行

- Suggestions 存量内容质量：仍有 `fa9f55a1-027b-4d9a-97dd-d2ffab38207c` 正文包含 `{'body': ..., 'subject': ...}` 字典字符串，已记录 `GAP-IOS-SUGGESTION-CONTENT-008`。
- Tasks 事件流质量：只读/恢复过程中出现大量 `checkpoint.restored`，已记录 `GAP-IOS-TASK-READ-SIDE-EFFECT-009`。
- Tasks UI 状态反馈：Resume/Cancel 写回成功，但 UI 不够明确展示最新 `status/current_node`，已记录 `GAP-IOS-TASK-STATUS-UI-010`。
- Career 存量内容质量：`job_pm_001` title/company 为空导致 UI 显示 `· update_fit_score`，已记录 `GAP-IOS-CAREER-CONTENT-011`。
- Dynamic Island 真机展示：iPhone 17 Pro Simulator 已通过 compact/expanded/tap 回跳验收，但仍不能替代支持灵动岛的真实 iPhone 录屏验收，`GAP-IOS-DYNAMIC-ISLAND-REALDEVICE-002` 保持未关闭。
- WhatsApp 云主机浏览器稳定性：本地 runtime 已实现同 host 显式重新导航以恢复 `Aw, Snap!`，测试通过；真实云主机未部署，`GAP-IOS-ACCOUNT-WHATSAPP-RELOAD-012` 暂不关闭。
- LinkedIn 云主机登录页可视切源：本地 runtime 已实现从上一手动可视页切到 LinkedIn，测试通过；真实云主机未部署，`GAP-IOS-ACCOUNT-LINKEDIN-NAV-013` 暂不关闭。

结论：`GAP-IOS-BACKEND-E2E-007` 已关闭，四个 tab 已完成真实服务器内容级验收；剩余问题已拆成更具体的内容质量或交互 gap。

## 当前未关闭 gap

- `GAP-IOS-APNS-REALDEVICE-001`
- `GAP-IOS-DYNAMIC-ISLAND-REALDEVICE-002`
- `GAP-IOS-TASK-EFFECTS-004`
- `GAP-IOS-VOICE-STREAMING-005`
- `GAP-IOS-CHAT-STREAMING-006`
- `GAP-IOS-SUGGESTION-CONTENT-008`
- `GAP-IOS-TASK-READ-SIDE-EFFECT-009`
- `GAP-IOS-TASK-STATUS-UI-010`
- `GAP-IOS-CAREER-CONTENT-011`
- `GAP-IOS-ACCOUNT-WHATSAPP-RELOAD-012`
- `GAP-IOS-ACCOUNT-LINKEDIN-NAV-013`
