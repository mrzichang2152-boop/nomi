# 2026-06-29 Nomi 真实账号线上回归报告

## 验收范围

本次回归覆盖真实云服务器、Android 真机、真实 Gmail / WhatsApp / Telegram / LinkedIn 账号链路。验收口径不是只看接口是否返回 `200`，而是检查每一步输出是否使用真实账号数据、是否合理、是否能在真机上正确展示。

## 环境

- 云服务器：`http://206.119.171.141`
- 访问密码：`par-dev`
- SSH：`206.119.171.141:10799`
- Android 真机：`DQYTCYFMO7VSEAJB`
- 设备型号：`24094RAD4C`
- Android 包名：`com.par.assistant.android`
- 证据截图：
  - `/tmp/nomi-regression/current-device-latest.png`
  - `/tmp/nomi-regression/android-chat-pingreal29-sent.png`
  - `/tmp/nomi-regression/android-chat-pingreal29-after-hide.png`
  - `/tmp/nomi-regression/window.xml`

## 总结结论

当前不能判定为完整通过。

云端 HTTP 服务可用，Android 真机也能把消息发到线上服务并得到 `pong` 回复；但真实账号链路存在多处关键失败：

- Gmail API 已连接并能 fetch 邮件，但聊天回答没有正确取用最近真实 Gmail 邮件。
- Gmail 邮件语义处理误判严重，把收据、营销邮件、隐私政策通知等错误生成待办/日程/主动建议。
- WhatsApp / Telegram / LinkedIn 浏览器状态显示已登录，但缺少真实新消息或真实联系人/岗位采样闭环证据。
- LinkedIn 搜索接口只验证到命令排队，没有验证到实际打开搜索结果、采样 recruiter/hiring manager、推送真实结果。
- Android 真机 UI 能发送消息，但聊天展示层有严重问题：历史不一致、文本溢出、旧建议内容混入对话区、部分消息节点坐标异常。
- SSH 端口仍然不可达，导致无法直接查看线上容器日志或部署修复。

## 逐项结果

| 项目 | 结果 | 证据 | 结论 |
| --- | --- | --- | --- |
| 云端 `/health` | 通过 | 返回 `{"status":"ok"}` | HTTP 服务在线 |
| 云端 80 端口 | 通过 | `nc 206.119.171.141 80` 成功 | Web/API 可访问 |
| 云端 SSH 10799 | 阻塞 | `nc 206.119.171.141 10799` 超时 | 无法 SSH 查看日志/部署 |
| Android 真机在线 | 通过 | `adb devices -l` 显示 `DQYTCYFMO7VSEAJB device` | 真机可调试 |
| Android 真机发送消息 | 部分通过 | 发送 `pingreal29`，服务端历史出现 `pingreal29 -> pong` | 设备到云端链路可用 |
| Android 真机对话展示 | 失败 | 真机 UI 空白、旧建议长链接溢出、UI dump 中消息节点坐标异常 | 显示层未通过 |
| Qwen / 模型路由 | 通过 | `/api/model/status` 显示 `qwen3.6`，`success_count=4` | 模型可请求 |
| WebSocket 流式 | 部分通过 | `ping` 首 delta 约 3.27s，复杂问题首 delta 约 6-7s | 流式可用但复杂查询慢 |
| Gmail Composio | 通过 | `GMAIL_FETCH_EMAILS` completed，fetched 2 | Gmail API 已连接 |
| Gmail 浏览器会话 | 失败 | collector 显示 `browser_login_status=logged_out` | 云端 Gmail 浏览器未登录 |
| Gmail 问答召回 | 失败 | 问“最近真实 Gmail 邮件有什么要处理”，回答说上下文为空 | 聊天路由没有取到真实 Gmail source_context |
| Gmail 语义处理 | 失败 | 收据、营销邮件、隐私政策邮件被生成待办/日程 | 输出不合理 |
| WhatsApp 登录状态 | 部分通过 | collector 显示 `logged_in` / `healthy` | 只能说明 Web 会话已登录 |
| WhatsApp 新消息采集 | 未完成 | `last_event_at=None` | 需真实新消息配合验证 |
| Telegram 登录状态 | 部分通过 | collector 显示 `logged_in` / `healthy` | 只能说明 Web 会话已登录 |
| Telegram 结构化采集 | 失败/未闭环 | detail: `no structured chat preview matched`, `preview_count=0` | 登录后未解析出结构化聊天 |
| LinkedIn 登录状态 | 部分通过 | collector 显示 feed logged_in，snapshot_count=2 | 只能说明 feed 页面采样过 |
| LinkedIn recruiter 搜索 | 部分通过 | `/api/browser/search-linkedin-contacts` 返回 queued | 仅命令排队，未验证实际采样结果 |
| LinkedIn 求职推荐问答 | 失败 | 问真实 LinkedIn + 简历推荐岗位，回答无法访问 LinkedIn/简历 | 没走真实求职 pipeline |
| 求职看板 | 失败 | `/api/career/board` 多条 `Example AI` / `manual` 数据 | 不满足真实账号验收 |
| 主动建议 | 失败 | Gmail 收据/营销邮件触发建议 | 建议质量不合理 |
| 自动日程 | 失败 | 收据、营销邮件、LinkedIn 通知被生成日程 | 日程抽取需要过滤与置信度门禁 |

## 关键证据

### 1. Gmail 已连接但问答未使用 Gmail 数据

`/api/integrations/composio/toolkits?session_kind=readonly` 显示 Gmail connected。

`POST /api/collectors/gmail/composio/fetch` 返回 completed，能通过 `GMAIL_FETCH_EMAILS` 拉到真实邮件。

但是 WebSocket 真实问题：

> 请用最近真实 Gmail 邮件告诉我最近有什么需要处理的事情，必须列出来源和判断依据。

模型回答：

> 给定的 JSON 上下文中 source_context、agenda_context、memory_context 均为空或缺乏具体邮件内容数据。

trace 证据：

- `conversation_id`: `c3817e2b-db9e-4e33-91aa-ab520ee15a8e`
- `chat_route.intent`: `task_request`
- `needs_source`: `true`
- `source_context`: `[]`
- `pipeline_executions`: `[]`

判断：路由判断到需要 source，但没有实际取到 Gmail source_context，也没有执行 Gmail/邮件处理 pipeline。

### 2. Gmail 语义处理存在明显误判

`/api/suggestions` 中出现以下不合理建议：

- ElevenLabs 收据被标为“处理邮件待办”。
- OpenAI 营销邮件里的“取消订阅”被标为“确认取消安排”。
- LinkedIn 通知邮件被标为“处理邮件待办”。

`/api/agenda` 中出现以下不合理日程：

- ElevenLabs receipt 被作为 exact schedule。
- OpenAI 营销邮件被作为 canceled appointment。
- Privacy Policy 更新邮件被作为 fuzzy schedule。
- LinkedIn 通知和页面噪声被作为 schedule。

判断：当前事件分类/日程抽取缺少营销邮件、收据、系统通知、隐私政策、unsubscribe footer 的过滤；同时 `certainty=exact` 与 `has_exact_time=false` 也存在结构不一致。

### 3. LinkedIn 搜索只排队，未闭环

请求：

```json
{
  "company": "OpenAI",
  "job_title": "Recruiter Hiring Manager AI Product Manager",
  "location": "Remote"
}
```

返回：

```json
{
  "status": "queued",
  "source": "linkedin",
  "expected_event_type": "linkedin_contact_snapshot"
}
```

10 秒后 collector 仍显示：

- LinkedIn URL 仍为 `https://www.linkedin.com/feed/`
- `last_event_at=None`
- search collector 仍 degraded

判断：命令队列接口可用，但没有证据证明云端浏览器实际执行搜索、采样候选联系人并写入事件。

### 4. Android 真机聊天 UI 和服务端历史不一致

真机实际发送 `pingreal29` 后，服务端 `/api/chat/history?limit=10` 出现：

- user: `pingreal29`
- assistant: `pong`

但真机截图和 UI dump 显示：

- 对话区仍主要为空白。
- 旧 ElevenLabs 收据建议内容在聊天区域横向溢出。
- `pingreal29/pong` 存在于 UI 节点树，但部分节点坐标异常，例如 y 坐标贴近顶部或不可见区域。

判断：真实设备链路能到服务端，但 Android WebView/悬浮窗的消息列表渲染、滚动定位、数据源隔离有问题。

## 需要用户配合完成的真实消息测试

以下链路无法由我单方面制造真实外部消息，需要用户向当前已登录账号发送测试消息：

1. WhatsApp：
   - 发送内容：`NOMI_REG_WA_0629 明天15:30人民广场见，带合同`
   - 预期：collector `last_event_at` 更新，生成 source event，日程写入绝对日期时间，主动建议推送到真机。

2. Telegram：
   - 发送内容：`NOMI_REG_TG_0629 周五10点静安寺地铁站见 Maya`
   - 预期：collector 解析出结构化 chat preview，写入事件/日程，主动建议推送到真机。

3. LinkedIn：
   - 打开或搜索一个真实 recruiter / hiring manager 主页。
   - 预期：采样姓名、职位、公司、profile URL，并能进入求职 pipeline 推荐或联系人跟进建议。

## 当前阻塞点

1. SSH 不通：`206.119.171.141:10799` 超时，无法查看容器日志、worker 日志、浏览器执行日志。
2. WhatsApp / Telegram 新消息链路缺少用户发送的真实测试消息。
3. LinkedIn 搜索命令缺少实际执行结果查询接口或日志证据。
4. Android 真机 UI 渲染异常会影响人工验收。

## 建议修复优先级

1. 修复聊天路由与 source_context：Gmail/LinkedIn 明确问题必须走对应 pipeline 或显式数据读取，而不是只走普通记忆拼接。
2. 修复 Gmail 语义过滤：收据、营销邮件、隐私政策、unsubscribe footer、纯通知邮件默认不得生成日程/主动建议，除非有明确用户行动或明确会议/约定。
3. 修复 Android 消息列表：统一悬浮窗和完整 app 的会话数据源；消息必须换行、限制宽度、自动滚动到底部；旧 suggestion 不得混入 chat stream。
4. 补 LinkedIn command 状态/结果表：queued 之后必须能看到 running/completed/failed、最终 URL、采样结果和错误。
5. Telegram collector 需要从 logged_in 进一步做到结构化 preview/event 采集。
6. 恢复 SSH 或提供线上日志面板，否则真实链路排障会非常慢。

## 2026-06-29 本地修复进展

以下修复已经在本地代码和自动化测试中验证通过，但尚未部署到云服务器做真实账号/真机复验：

| 问题 | 本地修复状态 | 验证 |
| --- | --- | --- |
| Gmail 问答没有召回真实 Gmail source_context | 已补：聊天路由会从问题文本推断 `gmail` source，并在无 thread/source mapping 时回退读取最近 Gmail 事件。 | `test_chat_endpoint_infers_gmail_source_context_from_user_question` 通过 |
| Gmail 收据/营销/隐私政策误生成待办、日程、建议 | 已补：`filter_open_suggestions` 和 `/api/agenda` 增加 Gmail 低价值噪声过滤。 | `test_filter_open_suggestions_suppresses_gmail_receipts_marketing_and_policy_noise`、`test_agenda_list_filters_low_value_gmail_receipts_marketing_and_policy` 通过 |
| LinkedIn 搜索只停在 queued | 已补：浏览器命令创建 status 记录，worker 取走时标记 `picked`，执行后回写 `opened/navigated/failed` 和 URL/错误详情。 | `test_linkedin_contact_search_records_queue_status_and_status_endpoint`、`test_browser_command_result_updates_status_for_linkedin_validation` 通过 |
| 求职看板显示 Example/manual 数据 | 已补：`/api/career/board` 默认过滤 demo/manual/test/example 数据；需要调试时可显式 `include_demo=true`。 | `test_career_board_endpoint_filters_manual_demo_opportunities_by_default` 通过 |
| 悬浮窗旧主动建议混入聊天历史、长链接溢出 | 已补：打开悬浮窗不再把最近 proactive bubble 写入聊天历史；消息 TextView 禁止横向滚动并启用换行策略。 | `FloatingPanelAppEntryContractTest` 通过 |

仍需线上复验：

- 部署后用真实 Gmail 问答确认 trace 中 `source_context` 不再为空，回答必须引用真实邮件摘要/来源。
- 部署后确认 Gmail receipt / marketing / privacy policy 不再出现在 `/api/suggestions` 和 `/api/agenda`。
- 在云端 noVNC 执行 LinkedIn recruiter 搜索，确认状态从 `queued -> picked -> opened/navigated/failed`，并能看到实际 URL 或失败原因。
- 真机安装新 APK 后确认悬浮窗聊天历史与服务端一致，旧建议不再插入对话区，长链接不会横向溢出。

## 2026-06-29 云服务器 + 真机复验记录

用户已发送真实外部测试消息：

- WhatsApp：`NOMI_REG_WA_0629 明天15:30人民广场见，带合同`
- Telegram：`NOMI_REG_TG_0629 周五10点静安寺地铁站见 Maya`

### 部署状态

- 已通过 SSH 连接 `206.119.171.141:22`。
- 已将本地代码同步到 `/opt/nomi`。
- 已重建并启动 `runtime-api`、`chromium-runtime`。
- 云端服务状态：`/health -> {"status":"ok"}`。
- Docker 服务状态：`runtime-api`、`chromium-runtime`、`worker`、`model-router`、`postgres`、`redis`、`nginx` 均为 running/healthy。
- 已在真机 `DQYTCYFMO7VSEAJB` 上启动 Nomi，悬浮球可显示、悬浮对话框可打开。

### 本轮新增修复

1. WhatsApp 中文登录页误判修复。
   - 根因：登录态检测只识别英文登录页；中文登录页包含“你的私人消息已进行端到端加密”，误命中 logged_in。
   - 修复：增加中文登录标记，包括“扫描登录”“扫描二维码”“使用电话号码登录”“电话号码”“开始使用”“创建账户”“关联到你的账户”。
   - 本地验证：`test_detect_browser_login_state_identifies_chinese_whatsapp_login_page` 与相邻登录态测试通过。

2. Gmail/Telegram/LinkedIn 低价值噪声过滤补强。
   - 修复：过滤 Gmail HTML 邮件、营销标题、订单支付类通知、收据/隐私政策/安全钓鱼类 Telegram 噪声。
   - 保留：腾讯会议、云服务器到期提醒这类可能真实需要用户行动的事项不会被该规则过滤。
   - 本地验证：新增 `test_agenda_list_filters_current_cloud_gmail_noise_without_hiding_useful_reminders`，相关 5 条过滤测试通过。

### 真实账号采集状态

| 渠道 | 实际状态 | 结论 |
| --- | --- | --- |
| Gmail | 云端浏览器在 Google 登录页，`login_state=logged_out`。 | 未能采集新邮件；需要重新在云端 Gmail 登录。 |
| WhatsApp | 云端浏览器在 WhatsApp 扫码/电话号码登录页，修复后 `login_state=logged_out`。 | 用户发送的 WhatsApp 测试消息未进入事件表；需要重新登录云端 WhatsApp Web 后重发或等待同步。 |
| Telegram | 云端账号为 logged_in，但当前可见会话列表最新为 `Ricardo Logan`，搜索 `Maya` 未命中。 | 用户发送的 Telegram 测试消息未出现在云端可见会话，未进入事件表。 |
| LinkedIn | 云端账号 logged_in，停留在 feed。 | 本轮未继续执行 recruiter 采样。 |

事件表查询结果：

- `NOMI_REG_WA_0629`：0 条。
- `NOMI_REG_TG_0629`：0 条。
- `人民广场见，带合同`：0 条。
- `静安寺地铁站见 Maya`：0 条。

### API 与内容验收

1. `/api/suggestions?limit=30`
   - 实际结果：`suggestion count 0`。
   - 结论：本轮没有继续推送低价值主动建议。

2. `/api/agenda?limit=30`
   - 修复后已去除本轮看到的 Gmail 营销/HTML/订单噪声。
   - 仍存在历史测试/旧数据：
     - `明天3点记得在腾讯会议上开线上会议`
     - `明天下午4点人民广场见`
     - 历史 WhatsApp/Telegram 测试样本
     - `[live-e2e] Example AI recruiter follow-up`
   - 结论：显示层低价值噪声改善，但历史示例/测试数据隔离仍未彻底完成；相对时间历史项仍可能以“明天”展示。

3. `/api/chat`
   - 问：“最近有要开的会吗？请只根据我的邮件、聊天和日程回答。”
     - HTTP 200，耗时约 28.78s。
     - 回答：最近没有即将召开的会议，并解释已知会议均已过去。
     - 结论：回答逻辑可解释，但由于云端 Gmail logged_out，不能验证用户刚发送的真实邮件/会议采集。
   - 问：“人民广场会面的时间是几点？请给具体日期时间，不要说‘明天’。”
     - HTTP 200，耗时约 6.54s。
     - 回答：`2026年6月19日（周五）17:00`，并说明已过去。
     - 结论：回答层能输出绝对日期；但底层日程列表仍有历史相对标题，需要继续治理历史数据/展示字段。

### 真机验收

- 真机悬浮球可启动。
- 悬浮对话框可打开。
- 真机发送 `Nomi0629e2e` 后收到 `pong`。
- 键盘弹出后输入框保持在键盘上方，发送后键盘未自动收起，符合当前交互要求。

仍需继续验证：

- 真机主动建议气泡必须基于真实新消息触发；本轮因 WhatsApp/Gmail 未登录、Telegram 测试消息不可见，未能验证。
- 悬浮窗与完整 App 历史完全一致仍需在真实长对话下复验。

### 本轮阻塞/失败项

1. WhatsApp 真实消息链路失败。
   - 原因：云端 WhatsApp Web 未登录。
   - 当前状态已从误报 healthy 修正为明确 `login_required`。

2. Telegram 真实消息链路失败。
   - 原因：云端 Telegram 登录态正常，但 `NOMI_REG_TG_0629` / `Maya` / `静安寺` 在当前账号可见 DOM 和搜索结果中均不存在。
   - 需要确认测试消息是否发到了云端登录的同一个 Telegram 账号、同一个会话。

3. Gmail 真实邮件/会议链路失败。
   - 原因：云端 Gmail 处于 Google 登录页。
   - 需要重新完成云端 Gmail 登录，之后再发送真实会议邮件复验。

4. 日程数据仍混有历史测试/示例数据。
   - 影响：真实验收时会干扰用户判断。
   - 建议：增加环境/来源标签过滤，线上默认隐藏 `demo/manual/live-e2e/example/test` 数据；或者提供“清理测试数据”维护入口。

5. 部分历史日程标题仍含“明天/周五”等相对时间。
   - 影响：列表层不满足“必须展示绝对日期”的产品要求。
   - 建议：列表展示使用 `parsed.start_at/end_at` 或 canonical title，而不是原始抽取标题。

## 2026-06-29 16:46 真实 WhatsApp / Telegram 登录后复验

用户重新完成云端 WhatsApp 与 Telegram 登录，并分别用其他账号发送：

- WhatsApp：`NOMI_REG_WA_0629 明天15:30人民广场见，带合同`
- Telegram：`NOMI_REG_TG_0629 周五10点静安寺地铁站见 Maya`

### 登录状态

`/collectors/health` 内容级检查：

| 渠道 | 状态 | 证据 | 结论 |
| --- | --- | --- | --- |
| WhatsApp | `healthy` / `logged_in` | URL `https://web.whatsapp.com/`，title `(1) WhatsApp` | 已登录，可继续验收采集链路 |
| Telegram | `healthy` / `logged_in` | URL `https://web.telegram.org/k/`，title `Telegram Web` | 已登录，但仍需确认目标消息是否进入可见会话 |
| LinkedIn | `healthy` / `logged_in` | URL `https://www.linkedin.com/feed/` | 本轮未测试 LinkedIn |
| Gmail | `degraded` / `logged_out` | Google account chooser | 本轮未测试 Gmail |

### WhatsApp 链路结果

结论：通过核心链路，但仍有一个 parser 噪声行需要后续治理。

证据：

- `events` 中存在真实 WhatsApp message：
  - `event_id=4961302e-7ba2-491a-91a5-404fc35f98af`
  - `source=whatsapp`
  - `event_type=whatsapp_message`
  - `sender=PHONE_1`
  - `message=NOMI_REG_WA_0629 明天15:30人民广场见，带合同`
  - `timestamp_label=07:36`
- worker 日志：
  - `worker processed ... source=whatsapp event_type=whatsapp_message intent=social_plan`
- `agenda_items` 中存在日程：
  - `id=977c5a12-4022-468a-a173-1a532257080c`
  - `title=NOMI_REG_WA_0629 明天15:30人民广场见，带合同`
  - `time_window.display=2026-06-30 周二 15:30`
  - `time_window.start=2026-06-30T15:30:00+08:00`
  - `place=人民广场`
  - `participants=["PHONE_1"]`
  - `source_event_ids=["4961302e-7ba2-491a-91a5-404fc35f98af"]`
- `/api/chat` 问答：
  - 问题：`NOMI_REG_WA_0629 这条 WhatsApp 里约的人民广场会面具体是什么时候？请只根据我的聊天和日程回答，必须写具体年月日和时间。`
  - 回答：`2026年6月30日（周二）15:30`
  - `context_pack.included_agenda_ids` 包含 `977c5a12-4022-468a-a173-1a532257080c`
  - `source_context` 包含 WhatsApp 原始事件。
- `proactive_suggestions` 中存在主动建议：
  - `id=8175f1c2-f55f-4105-9ce0-e3cc285c2e39`
  - `source_event_id=4961302e-7ba2-491a-91a5-404fc35f98af`
  - `body=这条信息可能需要跟进：NOMI_REG_WA_0629 明天15:30人民广场见，带合同。`
  - actions：`查路线`、`帮我打车`、`稍后提醒`

发现的问题：

- WhatsApp chat-list preview 仍额外生成了一条错误解析事件：
  - `event_id=2cece90f-640b-442d-8d81-fa83e8b6fecf`
  - `sender=07:36`
  - `message=1`
  - `timestamp_label=NOMI_REG_WA_0629 明天15:30人民广场见，带合同`
- 该错误事件没有影响当前日程创建，因为日程引用的是正确事件 `4961302e-7ba2-491a-91a5-404fc35f98af`，但后续需要收紧 WhatsApp preview parser：`timestamp_label` 必须匹配时间/日期格式，不得把正文当 timestamp。

### 主动建议 API 修复与复验

本轮发现 `/api/suggestions` 存在接口层 bug：

- DB 中已生成 WhatsApp 主动建议，但接口先按 SQL `LIMIT` 取前 N 条，再做低价值过滤。
- 高优先级噪声会先占满名额，导致低优先级但真实的 WhatsApp 建议无法返回给 Android 端。
- 同时，Nomi 对话里的 regression 问句会被误生成主动建议，污染建议列表。

已修复并部署：

- `/api/suggestions` 现在会预取更多 open 建议，过滤后再按用户请求的 `limit` 返回。
- `filter_open_suggestions` 会过滤 `source=nomi_chat`、`event_type=user_message` 且正文包含 `user said to Nomi:` 的自我回声建议。

验证：

- 本地测试：
  - `runtime_api/tests/test_vector_and_suggestions.py::test_suggestions_endpoint_prefetches_past_filtered_noise` 先红后绿。
  - `runtime_api/tests/test_vector_and_suggestions.py::test_filter_open_suggestions_suppresses_nomi_chat_question_noise` 先红后绿。
  - `python3 -m pytest -q runtime_api/tests/test_vector_and_suggestions.py`：`41 passed`。
- 云端部署：
  - 已 `docker compose up -d --build runtime-api`。
  - `/health -> {"status":"ok"}`。
  - `/api/suggestions?limit=10` 返回 `count=4`。
  - `has_real_wa=True`。
  - `has_chat_echo=False`。
  - 返回的 WhatsApp 建议包含 actions：`查路线`、`帮我打车`、`稍后提醒`。

### Telegram 链路结果

结论：未通过。登录状态正常，但测试消息没有进入云端可见 DOM / 事件库。

证据：

- `events` 中没有 `NOMI_REG_TG_0629`、`静安寺地铁站见 Maya`。
- 最近 Telegram 事件仅包含：
  - `Ricardo Logan` / `RL`
  - `Michael Koch` / 官方安全中心提醒
  - `SecurityCenter` / Telegram gift
  - 一条 `telegram_visible_snapshot`，visible text 只有 `Search / Chats / Apps / Posts / Media / Links / Files / Music / Voice / UPDATE`
- worker 日志里出现 Telegram preview 被处理，但没有目标 token：
  - `source=telegram event_type=telegram_message_preview intent=普通聊天`
  - `source=telegram event_type=telegram_message_preview intent=task_request`
  - `source=telegram event_type=telegram_visible_snapshot intent=系统状态同步`
- 通过 `/api/browser/open` 重新打开 Telegram 后，后续查询仍未出现目标 token。

判断：

- 这不是“worker 处理失败后没生成日程”，而是更前一层：云端 Telegram Web 当前没有采到用户刚发送的测试消息。
- 需要确认测试消息是否发到了云端登录的同一个 Telegram 账号，或目标会话是否在云端 Telegram Web 中可见。

下一步建议：

1. 在云端 noVNC Telegram Web 中手动打开接收该消息的会话，然后让用户重发 `NOMI_REG_TG_0629_RETRY 周五10点静安寺地铁站见 Maya`。
2. 或让用户发到当前云端 Telegram Web 明确可见的最新会话，再复验采集、日程、主动建议。
3. 后续需要增强 Telegram collector：不仅采首页可见 previews，还要支持搜索目标联系人/会话并采样打开后的 chat history。

### 当前状态结论

| 链路 | 结论 |
| --- | --- |
| WhatsApp 登录 | 通过 |
| WhatsApp 真实消息入库 | 通过 |
| WhatsApp 日程创建 | 通过，且相对“明天”已解析为 `2026-06-30 周二 15:30` |
| WhatsApp 对话问答召回 | 通过 |
| WhatsApp 主动建议 DB 生成 | 通过 |
| WhatsApp 主动建议 API 展示 | 通过，已修复部署 |
| Telegram 登录 | 通过 |
| Telegram 真实消息入库 | 未通过 |
| Telegram 日程/建议 | 未通过，因为源消息未采到 |

当前不能把 Telegram 真实链路算作完成验收；WhatsApp 这条真实链路可以算作核心链路通过，但 parser 噪声仍需单独修复。

## 2026-06-29 18:06 重发后复验

用户确认已重新发送：

- WhatsApp：`NOMI_REG_WA_0629 明天15:30人民广场见，带合同`
- Telegram：`NOMI_REG_TG_0629 周五10点静安寺地铁站见 Maya`

### Collector 状态

| 渠道 | 状态 | 证据 |
| --- | --- | --- |
| WhatsApp | `healthy` / `logged_in` | `url=https://web.whatsapp.com/`，title=`(1) WhatsApp` |
| Telegram | `healthy` / `logged_in` | `url=https://web.telegram.org/k/`，title=`Telegram Web`，`latest_chat=Ricardo Logan`，`preview_count=3` |

### WhatsApp 重发链路

结论：通过。

证据：

- 新入库事件：
  - `event_id=b47672d7-6c7f-4282-bfdc-ac26e9fe2a5a`
  - `source=whatsapp`
  - `event_type=whatsapp_message`
  - `sender=PHONE_1`
  - `message=NOMI_REG_WA_0629 明天15:30人民广场见，带合同`
  - `timestamp=2026-06-29 09:48:53.862292+00`
- worker 处理：
  - `worker processed ... event_id=b47672d7-6c7f-4282-bfdc-ac26e9fe2a5a source=whatsapp event_type=whatsapp_message intent=social_plan`
- 日程写入：
  - 没有新建重复日程，而是更新既有日程 `977c5a12-4022-468a-a173-1a532257080c`。
  - `updated_at=2026-06-29 09:48:53.9227+00`
  - `source_event_ids={4961302e-7ba2-491a-91a5-404fc35f98af,b47672d7-6c7f-4282-bfdc-ac26e9fe2a5a}`
  - `time_window.display=2026-06-30 周二 15:30`
  - `time_window.start=2026-06-30T15:30:00+08:00`
  - `place=人民广场`
- 主动建议：
  - `id=c4045050-265a-4d1a-81dd-e3a35299c45b`
  - `source_event_id=b47672d7-6c7f-4282-bfdc-ac26e9fe2a5a`
  - `body=这条信息可能需要跟进：NOMI_REG_WA_0629 明天15:30人民广场见，带合同。`
  - actions：`查路线`、`帮我打车`、`稍后提醒`
- `/api/suggestions?limit=10`：
  - 返回 `count=4`
  - 包含上述 WhatsApp 主动建议。
- `/api/chat`：
  - 问题：`NOMI_REG_WA_0629 这条 WhatsApp 里人民广场见面的具体时间是什么？请只根据我的聊天和日程回答，必须写具体年月日和时间。`
  - 回答：`根据日程记录，NOMI_REG_WA_0629 对应的人民广场见面时间是 **2026年6月30日 15:30**。`

仍存在的非阻塞问题：

- WhatsApp list preview 仍额外产生了噪声事件：
  - `event_id=964f5c08-7df1-48a8-b11a-db87d6b0578f`
  - `sender=09:48`
  - `message=2`
  - 这次没有影响日程，因为正确事件 `b47672d7-6c7f-4282-bfdc-ac26e9fe2a5a` 被识别为 `social_plan` 并写入日程。

### Telegram 重发链路

结论：未通过，原因在采集入口之前：云端 Telegram Web 当前账号/页面没有看到这条消息。

证据：

- Collector 状态为已登录，但 `latest_chat=Ricardo Logan`，不是目标测试会话。
- 事件表最近 2 小时 Telegram 事件仅包含：
  - `Ricardo Logan / RL`
  - `Michael Koch / 官方安全中心提醒`
  - `SecurityCenter / Telegram sent you a gift`
  - `telegram_visible_snapshot`
  - 若干 `browser_network_event`
- 事件表没有：
  - `NOMI_REG_TG_0629`
  - `静安寺地铁站见 Maya`
- 直接通过 CDP 读取云端 Telegram 页面 DOM：
  - 当前页面共有 50 行可见文本。
  - 包含 `Ricardo Logan`、`Michael Koch`、`SecurityCenter`、联系人列表等。
  - `contains_target=False`。
- 在云端 Telegram Web 顶部搜索框中输入 `NOMI_REG_TG_0629` 后：
  - 页面显示 `No results / Try a different search term`。
  - `found_target=False`。

判断：

- Telegram 不是 worker 未处理，也不是日程解析失败；当前失败点是云端 Telegram Web 没有收到或搜到该测试消息。
- 在目标消息进入云端 Telegram 可见 DOM 之前，无法验证 Telegram 的真实消息入库、日程创建和主动建议。

下一步：

1. 需要在云端 noVNC 的 Telegram Web 中确认接收测试消息的具体会话是否存在。
2. 最好让用户向云端 Telegram Web 当前可见、可搜索到的会话发送一次新的唯一 token，例如 `NOMI_REG_TG_0629_RETRY2 周五10点静安寺地铁站见 Maya`。
3. 长期需要补强 Telegram collector：当前只解析可见聊天列表 preview，后续应支持搜索会话、打开会话并采集 chat history。
