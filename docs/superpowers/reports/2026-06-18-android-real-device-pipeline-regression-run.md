# Android 真机 Pipeline 验收执行报告

执行时间：2026-06-18
真机设备：`DQYTCYFMO7VSEAJB` / Redmi `24094RAD4C`
线上环境：`http://206.119.171.141`，`/health={"status":"ok"}`
验收计划：`docs/superpowers/plans/2026-06-18-android-real-device-pipeline-regression-test-plan.md`

## 结论摘要

- 线上 27 条 pipeline API 级验收：25/27 通过，2 条需要修复或优化。
- 真机悬浮对话框：发送、回复、键盘顶起、关闭后保留悬浮球通过。
- Web 完整工作台：加载、精简顶部、设置入口、关闭返回桌面通过。
- 关键失败：`agenda_pipeline` 没有把“明天下午5点”解析成绝对日期；真实 `/api/chat` 在短回复“需要”场景下没有正确继承上一轮语境。
- 部分通过：`career_profile_pipeline` 能抽取技能和证据，但目标岗位抽取不理想，把 headline 当成 target role。

原始结果：

- API 全量结果：`/tmp/nomi-20260618-online-pipeline-regression.json`
- Chat 结果：`/tmp/nomi-20260618-online-chat-regression.json`
- 真机截图：
  - `/tmp/nomi-realdevice-keyboard-focused-20260618.png`
  - `/tmp/nomi-realdevice-after-send-20260618.png`
  - `/tmp/nomi-realdevice-after-panel-close-20260618.png`
  - `/tmp/nomi-realdevice-workbench-open-20260618.png`
  - `/tmp/nomi-realdevice-workbench-closed-20260618.png`
  - `/tmp/nomi-realdevice-workbench-settings-20260618.png`

## Pipeline API 结果

| 用例 | Pipeline | 结论 | 状态 | 耗时 | 备注 |
|---|---|---|---|---:|---|
| P01 | `event_ingestion_pipeline` | 通过 | `completed_read_only` | 471ms | 事件规范化、ledger、下游 job 计划合理 |
| P02 | `memory_write_pipeline` | 通过 | `completed_read_only` | 326ms | KV/graph/RAG/embedding 写入计划合理 |
| P03 | `context_pack_pipeline` | 通过 | `completed_read_only` | 355ms | scoped evidence 合理，未混入 Bob 私密内容 |
| P04 | `personal_search_pipeline` | 通过 | `completed_read_only` | 325ms | RG_Alice/PHONE_1 作用域正确 |
| P05 | `chat_response_pipeline` | API 通过，真实 chat 失败 | `completed_read_only` | 317ms | pipeline contract 通过；真实 `/api/chat` 短回复语境失败 |
| P06 | `reply_pipeline` | 通过 | `draft_ready` | 297ms | 草稿待确认，未发送 |
| P07 | `email_pipeline` | 通过 | `draft_ready` | 305ms | 面试邮件总结/草稿待确认 |
| P08 | `agenda_pipeline` | 失败 | `confirmation_required` | 347ms | 相对时间未解析成绝对日期 |
| P09 | `task_todo_pipeline` | 通过 | `completed_read_only` | 381ms | 待办写入计划合理 |
| P10 | `proactive_suggestion_pipeline` | 通过 | `draft_ready` | 370ms | 建议卡动作合理 |
| P11 | `route_pipeline` | 通过 | `completed_read_only` | 292ms | read-only，不叫车 |
| P12 | `ride_pipeline` | 通过 | `needs_user_input` | 286ms | 缺 pickup 时停住，未叫车 |
| P13 | `shopping_pipeline` | 通过 | `completed_read_only` | 302ms | 比价计划，未下单 |
| P14 | `payment_bill_pipeline` | 通过 | `confirmation_required` | 310ms | 找到账单，未付款 |
| P15 | `contact_relationship_pipeline` | 通过 | `completed_read_only` | 355ms | 联系人作用域合理 |
| P16 | `document_file_pipeline` | 通过 | `completed_read_only` | 295ms | 文档摘要 read-only |
| P17 | `career_profile_pipeline` | 部分通过 | `completed_read_only` | 459ms | 技能/证据正确，target role 抽取不理想 |
| P18 | `job_discovery_pipeline` | 通过 | `completed_read_only` | 313ms | 岗位规范化合理 |
| P19 | `job_fit_scoring_pipeline` | 通过 | `completed_read_only` | 343ms | JD/简历匹配评分有证据 |
| P20 | `resume_tailoring_pipeline` | 通过 | `draft_ready` | 351ms | 修改建议草稿，不覆盖简历 |
| P21 | `cover_letter_pipeline` | 通过 | `draft_ready` | 347ms | Cover Letter 草稿待确认 |
| P22 | `outreach_message_pipeline` | 通过 | `draft_ready` | 351ms | LinkedIn 外联草稿待确认 |
| P23 | `job_application_pipeline` | 通过 | `blocked_until_delegated_grant` | 413ms | Apply/Submit 被授权门禁拦住 |
| P24 | `application_tracking_pipeline` | 通过 | `completed_read_only` | 325ms | 阶段与跟进计划合理 |
| P25 | `interview_prep_pipeline` | 通过 | `completed_read_only` | 412ms | 结合 JD/简历生成面试素材 |
| P26 | `account_login_pipeline` | API 通过 | `draft_ready` | 336ms | channel=telegram 时输出包含 telegram；真机账号页还需逐渠道点击复核 |
| P27 | `governance_audit_pipeline` | 通过 | `needs_user_input` | 286ms | 能解释高风险动作需要授权/确认 |

## 真机 UI 验收

### 通过项

- 悬浮球常驻：关闭原生对话框和关闭 Web 工作台后，桌面仍能看到 Nomi 悬浮球。
- 键盘交互：点击输入框后键盘自动弹出，输入框被顶到键盘上方，输入内容可见。
- 发送链路：真机输入 `realdevice_pipeline_ping` 后，Nomi 返回 `pong`；发送后键盘没有自动收起。
- 历史持久化：`/api/chat/history` 能查到刚才 3 轮用户/助手消息。
- Web 工作台：右上角关闭按钮可返回桌面；顶部已压缩为 `Nomi + 设置 + 关闭`，旧 tab 行没有出现。
- 设置入口：设置抽屉可见，包含“日程管理、求职助手、主动建议、账号连接、完整工作台、记忆治理、采集状态、个人搜索”等入口。

### 需继续复核

- 账号连接页首屏未完成逐渠道点击验证。本次误点进入“工具目录”，因此只能确认设置页存在“账号连接”入口，以及 API 级 `account_login_pipeline` 可按 channel 路由。
- 原生悬浮对话框顶部仍显示“打开完整工作台”和“设置”两个 icon，虽然都具备功能，但视觉上仍偏工具化，不如 Web 工作台简洁。

## 失败点与修复建议

### F1：`agenda_pipeline` 相对时间未解析为绝对日期

复现输入：

```json
{
  "request": "明天下午5点在上海博物馆见，带上合同和 PHONE_8 报价单。",
  "context": {
    "pipeline_id": "agenda_pipeline",
    "time_window": {
      "raw_text": "明天下午5点",
      "anchor_time": "2026-06-18T10:00:00+08:00"
    }
  }
}
```

实际输出：

- `status=confirmation_required`
- `time_window.raw_text=明天下午5点`
- `time_window.anchor_time=2026-06-18T10:00:00+08:00`
- `notification_plan.time_precision=fuzzy`
- 没有 `2026-06-19 17:00`

判断：失败。页面/输出不能只显示“明天”，因为用户之后无法知道“明天”相对哪一天。

修复建议：

- 在 agenda slot normalization 中增加 `anchor_time + raw_text` 的 deterministic resolver。
- 输出 `start_at=2026-06-19T17:00:00+08:00`、`display_date=2026-06-19`、`display_time=17:00`。
- 只有“周末/下午/有空时”这种不可确定表达才标记 fuzzy。

### F2：真实 `/api/chat` 短回复没有继承上一轮语境

复现 conversation：`eacf41cf-5a3b-48f4-a7b3-75cd436f2f2a`

对话：

1. 用户：`刚才 RG_Alice 的 PHONE_1 报价需要我做什么？`
2. Nomi：`不确定...没有包含 RG_Alice 关于 PHONE_1 报价的具体内容...`
3. 用户：`需要`
4. Nomi：再次回答 `不确定...`

判断：失败。至少应该识别“需要”是在延续上一轮话题，若上下文证据不足，也应说“你是指需要我帮你核对 PHONE_1 报价的成本和利润率吗？”而不是完全断上下文。

修复建议：

- 在 chat route/context assembly 前增加 short-reply resolver：对 `需要/好的/可以/继续/是的` 这类短回复强制绑定上一轮 assistant/user 的可执行意图。
- `retrieve_assistant_dialogue_context` 的最近轮次要优先进入模型上下文；如果长期记忆缺证据，也不能覆盖会话上下文。
- 对无法执行的短回复，返回澄清问题并保留上一轮对象。

### F3：`career_profile_pipeline` 目标岗位抽取不理想

实际输出：

```json
{
  "headline": "Product manager building AI workflow products",
  "target_roles": ["Product manager building AI workflow products"],
  "skills": ["LLM product", "workflow automation", "data analysis", "B2B SaaS", "customer discovery"],
  "evidence_ids": ["resume_evt_1", "mail_job_1", "resume_exp_1"]
}
```

判断：部分通过。技能和证据合理，但 `target_roles` 应抽成 `AI Agent Product Manager` / `Product Manager` 等岗位，不应直接把 headline 当岗位。

修复建议：

- 优先从用户显式求职目标、求职邮件岗位名、JD title、简历 headline 中抽取 role。
- headline 只能作为画像描述，不应直接写入 `target_roles`。

### F4：账号连接真机逐渠道验证未完成

实际情况：

- 设置页存在“账号连接 Gmail、WhatsApp、Telegram、工具授权”入口。
- 本次点击坐标进入了“工具目录”，未完成 Gmail/WhatsApp/Telegram/LinkedIn 的逐项打开和关闭验证。
- API 级 `account_login_pipeline` 对 `channel=telegram` 输出包含 telegram，未出现“Telegram 打开 WhatsApp”的 API 级错误。

判断：阻塞/待复测。

修复建议：

- 为账号连接页关键按钮增加稳定 content-desc/test id。
- 真机复测每个渠道：点击入口 -> 页面标题/URL/channel 正确 -> 可关闭 -> 返回账号列表。

## Latency 观察

`/api/chat` 三次真实请求：

- `pipeline_ping`：总耗时约 3.2s，模型约 2.9s，回复 `pong`。
- `RG_Alice PHONE_1` 问题：总耗时约 4.5s，模型约 3.9s，回复内容不合理。
- `需要`：总耗时约 4.2s，模型约 4.0s，回复内容不合理。

判断：

- 首轮耗时可接受但仍偏慢，主要耗时在模型。
- 当前更严重的问题不是耗时，而是短回复上下文绑定失败。

## 下一步建议

1. 先修 `agenda_pipeline` 绝对日期解析，这是明确功能失败。
2. 修 `/api/chat` short-reply context resolver，避免“需要/好的/继续”断上下文。
3. 优化 `career_profile_pipeline` 的 target role 抽取。
4. 给账号连接页加稳定测试标识，并重新做 P26 真机逐渠道验收。
5. 修完后重跑本报告中的 `/tmp` 验收脚本和真机截图流程。

## 修复后复测

时间：2026-06-18

### 本地回归

命令：

```bash
python3 -m pytest runtime_api/tests/test_pipeline_agenda.py::test_agenda_resolves_clear_relative_datetime_against_anchor_time runtime_api/tests/test_context_pack_and_chat.py::test_short_reply_resolution_is_visible_in_model_context runtime_api/tests/test_job_agent_pipelines.py::test_career_profile_pipeline_normalizes_target_role_from_resume_headline -q
python3 -m pytest runtime_api/tests/test_pipeline_agenda.py runtime_api/tests/test_context_pack_and_chat.py runtime_api/tests/test_assistant_memory.py runtime_api/tests/test_job_agent_pipelines.py runtime_api/tests/test_core_pipeline_engine.py -q
```

结果：

- 新增 3 条回归测试：`3 passed in 0.54s`。
- 相关测试集：`118 passed in 0.71s`。

### 线上部署

- 同步文件：`runtime_api/app/pipelines/agenda.py`、`runtime_api/app/assistant_memory.py`、`runtime_api/app/main.py`、`runtime_api/app/pipelines/career.py`。
- 服务器目录：`/opt/nomi`。
- 重建命令：`docker compose up -d --build runtime-api`。
- 健康检查：`GET /health -> {"status":"ok"}`。

### 线上语义复测

| 项 | 结果 | 输出核对 |
|---|---|---|
| P08 `agenda_pipeline` | fixed | `明天下午5点` + `anchor_time=2026-06-18T10:00:00+08:00` 被解析为 `2026-06-19T17:00:00+08:00`，`time_precision=exact`，不是模糊时间。 |
| P05 `chat_response_pipeline` | fixed | 发送短回复 `需要` 时，模型结合上一轮 “需要我帮你核对成本与利润率吗？” 回答“正在为您核对 PHONE_1 的成本与利润率...”，没有再把 `需要` 当孤立问题。 |
| P17 `career_profile_pipeline` | fixed | resume headline `Product manager building AI workflow products` 被归一为 `target_roles=["Product Manager"]`，skills 仍保留 `LLM product/workflow automation/data analysis/B2B SaaS`。 |

仍需继续跟进：

- P26 账号连接逐渠道真机 UI 复测还未完全闭环，需要继续按设置入口逐个验证 Gmail/WhatsApp/Telegram/LinkedIn 的打开页面、关闭和返回账号列表。

## P26 账号入口修复与复测

时间：2026-06-18

### 本地 TDD 回归

新增/调整测试：

- `runtime_api/tests/test_auth_and_model.py::test_tool_catalog_returns_high_frequency_tools_with_permission_levels`
- `runtime_api/tests/test_pipeline_actions.py::test_account_login_pipeline_resolves_social_browser_login_urls`

先红后绿：

- 修复前：工具目录只有 20 项，缺 `telegram`；`account_login_pipeline` 对 WhatsApp/Telegram/LinkedIn 退化成 Google 搜索页。
- 修复后：相关用例通过。

验证命令：

```bash
python3 -m pytest runtime_api/tests/test_auth_and_model.py::test_tool_catalog_requires_password runtime_api/tests/test_auth_and_model.py::test_tool_catalog_returns_high_frequency_tools_with_permission_levels runtime_api/tests/test_pipeline_actions.py runtime_api/tests/test_browser_login_commands.py -q
```

结果：`25 passed in 0.47s`。

### 修复内容

- `default_tool_catalog()` 增加 `telegram` core 工具，权限为 `read_only/draft/external_message`，风险等级 `high`，适配方式 `managed_browser_first`。
- `account_login_pipeline` 增加 WhatsApp/Telegram/LinkedIn provider 解析。
- 默认登录页修正为：
  - Gmail/Google: `https://accounts.google.com/`
  - WhatsApp: `https://web.whatsapp.com/`
  - Telegram: `https://web.telegram.org/`
  - LinkedIn: `https://www.linkedin.com/login`
- 凭据门禁保持不变：`blocked_effects=["submit_credentials", "read_credentials"]`，系统只准备登录页面，不读取或提交密码。

### 线上部署

- 当前可用 SSH 端口：`22`。此前 `10799` 已超时，本次部署改用 22。
- 部署文件：
  - `runtime_api/app/main.py`
  - `runtime_api/app/pipelines/actions.py`
  - `runtime_api/app/ios_apns.py`
  - `runtime_api/app/ios_live_activity.py`
- 额外修复：runtime-api 重建后曾因缺 `app.ios_apns` 启动失败并导致 nginx `502`，已同步缺失模块后恢复。
- 健康检查：`GET /health -> {"status":"ok"}`。

### 线上 API 复测

`/api/tools/catalog`：

- `tool_count=21`
- 渠道包含：`gmail`、`whatsapp`、`telegram`、`linkedin_browser`
- `telegram` 输出为 core communication 工具，`recommended_adapter=managed_browser_first`

`/api/pipelines/run`：

| 请求 | pipeline | slots | login_url | 门禁 |
|---|---|---|---|---|
| 登录 Gmail 账号 | `account_login_pipeline` | `Google` | `https://accounts.google.com/` | 阻止读取/提交凭据 |
| 登录 WhatsApp 账号 | `account_login_pipeline` | `WhatsApp` | `https://web.whatsapp.com/` | 阻止读取/提交凭据 |
| 登录 Telegram 账号 | `account_login_pipeline` | `Telegram` | `https://web.telegram.org/` | 阻止读取/提交凭据 |
| 登录 LinkedIn 账号 | `account_login_pipeline` | `LinkedIn` | `https://www.linkedin.com/login` | 阻止读取/提交凭据 |

结论：API 级 P26 修复通过，之前“Telegram/WhatsApp/LinkedIn 退化到 Google 搜索页”的问题已修复。

### 真机 UI 复测

设备：`DQYTCYFMO7VSEAJB`

步骤：

1. 解锁真机并恢复竖屏。
2. 打开 Nomi Web 工作台。
3. 点击右上角设置。
4. 点击“账号连接”。
5. 点击“刷新”。
6. 通过截图和 UI dump 核对工具/账号列表。

实际结果：

- 设置入口正常打开，入口已从顶部 tab 收到设置页。
- “账号连接”进入的是“工具目录/连接外部账号”页，功能可用，但标题仍偏工具化。
- UI dump 确认账号页包含：`Gmail`、`WhatsApp`、`Telegram`、`LinkedIn`、`Google Calendar`、`Google Drive`、`Google Maps`、`GitHub`、`Slack`、`Notion`。
- Gmail 显示已连接；其余渠道按真实授权状态显示“连接/未连接”。
- 截图证据：
  - `/tmp/nomi-p26-final-ui.png`
  - `/tmp/nomi-p26-account-page.png`
  - `/tmp/nomi-p26-account-scrolled.png`

判断：P26 账号入口“可打开正确账号/工具连接列表”通过；但仍有一个产品体验遗留：页面标题应改成“账号连接”，并把 Composio 工具授权与 WhatsApp/Telegram/LinkedIn 浏览器登录入口分区展示，避免用户误以为只进入了工具目录。
