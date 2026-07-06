# Nomi 真实账号环境端到端验收记录

创建时间：2026-06-18 20:46:57 CST
线上环境：http://206.119.171.141
验收口径：只把真实登录/真实授权账号链路计为真实通过；模拟注入、dry-run、API smoke 只能记为辅助证据。

## 验收原则

- 每条链路记录前置账号状态、输入、关键中间产物、最终输出、是否合理。
- 未登录/未授权时标记为 blocked，不标记 passed。
- 外部副作用动作默认 dry-run 或停在确认卡，不真实发送、付款、投递。
- 不在报告里写入邮件正文、联系人隐私等敏感原文；只记录脱敏摘要和计数。

## 当前进度

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 环境基线 | 进行中 | 正在核对线上 health、Composio、Android 真机 |
| Gmail 真实读取 | 待验证 | Composio 显示 Gmail connected，需要真实 fetch + 持久化核对 |
| WhatsApp 真实采集 | 待验证 | 需要确认是否真实登录并能采集新消息 |
| Telegram 真实采集 | 待验证 | collector 显示登录页，需要用户配合登录 |
| 主动建议/日程 | 待验证 | 需要真实渠道消息触发 |
| Android 对话 | 待验证 | 需要真实链路后复测 |

## 详细记录

待补充。

## 2026-06-18 20:46-20:55 环境与 Gmail 真实账号探针

### 环境基线

- 线上 `/health` 返回 `{"status":"ok"}`，API 服务可达。
- Composio 配置存在且 `reachable=true`。
- Composio readonly/write session 中 Gmail 均显示 `connected=true`，connected account id 已脱敏记录为 `ca_7g...NQf7N0EJ`。
- 其他 Google Calendar / Drive / Docs / Sheets / Tasks / Maps / GitHub / Slack / Notion 显示未连接。

### Gmail 真实读取探针

输入：

- `POST /api/collectors/gmail/composio/fetch`，`query=newer_than:7d`，`limit=3`。
- `POST /api/integrations/composio/tools/execute`，tool=`GMAIL_FETCH_EMAILS`，`query=newer_than:1d`，`max_results=1`。
- `POST /api/collectors/gmail/composio/fetch`，`query=newer_than:1d`，`limit=1`。

预期：

- 60 秒内返回真实 Gmail 邮件列表或空列表。
- collector 端点应返回 `source=gmail`、`adapter=composio:gmail`、`fetched_count`、`persisted_count`。
- 如有邮件，应写入 `events` 并入队后续 memory/event processing。

实际：

- `newer_than:7d limit=3` 在 60 秒客户端超时。
- `GMAIL_FETCH_EMAILS max_results=1` 在 30 秒客户端超时。
- `collector fetch limit=1` 在 30 秒客户端超时。

结论：

- Gmail 已授权，但真实读取链路当前不能判定通过；按真实验收标准记为 `failed/blocking`。
- 失败点在同步 Composio 工具执行或其上游网络/SDK 调用阶段，尚未得到邮件输出，因此不能继续宣称 Gmail 记忆写入、日程、主动建议链路通过。

### Gmail 后续核对

补充核对：查询数据库后发现，上述超时请求在服务端最终落了 `composio_tool_invocations.status=completed`，并写入了真实 Gmail 事件。

脱敏结果：

- 最近写入的 Gmail snapshot 至少 3 条，来源为真实 Gmail account。
- 可见字段包含 subject / snippet / messageId / threadId 等真实邮件元数据。
- 但 collector API 在客户端 30-60 秒窗口内超时，用户侧会看到失败或无反馈。
- 部分 `snippet` 写入呈现为对象/字典字符串，而不是干净摘要文本，后续检索和 UI 展示可能不合理。

修正结论：

- Gmail 账号授权：`passed`。
- Gmail 真实读取：`partial`，服务端最终可读取。
- Gmail API 用户体验：`failed`，同步接口超时。
- Gmail 数据规范：`partial/failed`，摘要字段需要规范化。
- Gmail 到日程/主动建议：尚未验证，不能标记通过。

### 基础接口阻塞

在 Gmail Composio 请求客户端超时后继续检查基础读接口：

- `/api/suggestions?limit=5`：20 秒超时。
- `/api/agenda?limit=5`：20 秒超时。
- `/api/chat/history?limit=10`：20 秒超时。
- `/api/collectors/status`：90 秒超时。

结论：

- 线上 runtime API 存在被慢工具调用拖住的风险。
- 真实验收不能继续假设 Web/Android 工作台基础加载稳定。
- 需要释放卡住请求后再继续验证，并在后续修复中把 Composio/Gmail fetch 改为异步任务或强制超时/队列化。

### WhatsApp/Telegram 当前证据

- 最近 2 小时数据库中有 `whatsapp_snapshot=1` 和 `browser_network_event=1`，说明浏览器采集路径有事件进入。
- 但这些不是本次由验收方控制的新消息，因此不能证明 WhatsApp 新消息完整链路通过。
- Telegram 当前没有可控真实登录/新消息证据；此前 collector 显示 Telegram Web 登录页，按真实验收标准应等待用户登录后再测。


### runtime-api 重启后的基础 API 复测

重启 `nomi-runtime-api-1` 后：

- `/api/suggestions?limit=5`：HTTP 200，约 0.30s。
- `/api/agenda?limit=5`：HTTP 200，约 0.70s。
- `/api/chat/history?limit=10`：HTTP 200，约 0.29s。
- Redis 队列 `events:raw` / `high_priority_queue` / `memory_batch_queue` 均为 0。
- `/api/pipelines/registry` 返回 27 条 pipeline。

### Gmail 真实邮件触发建议/日程核对

现象：

- Gmail 真实 snapshot 最终触发了 `proactive_suggestions` 和 `agenda_items`。
- 示例类型为服务器续费/到期提醒邮件，系统识别为 deadline/todo。

合理性检查：

- 正向：把“产品即将到期/续费”识别为待办/提醒是合理的。
- 问题 1：建议 body 和日程 title 混入了 `{'body': ..., 'subject': ...}` 这样的对象字符串，不是干净的人类可读摘要。
- 问题 2：日程 title 过长，含邮件模板噪声和脱敏占位符，不适合直接给用户展示。
- 问题 3：metadata 中有 `validation_warnings=["model_parse_failed:ReadTimeout"]`，说明模型解析失败后走了规则回退；结果可用但质量不稳定。
- 问题 4：真实 Gmail fetch 客户端超时，用户侧体验仍是失败/无反馈。

结论：

- Gmail -> event -> semantic/agenda/suggestion：`partial`。
- 输出合理性：`failed`，需要修摘要规范化、噪声清洗、模型超时兜底质量。
- 性能体验：`failed`，需要异步化或明确返回任务状态。

## 2026-06-20 继续验收：可控 token 查询

### 输入

检查以下可控测试 token 是否进入真实账号链路：

- `NOMI_E2E_GMAIL_0618`
- `NOMI_E2E_WA_0618`
- `NOMI_E2E_TG_0618`

### 实际结果

- 线上 `/health` 正常。
- Android 真机 `DQYTCYFMO7VSEAJB` 在线。
- 数据库 `events` 中未查询到任何 `NOMI_E2E_*` 事件。
- 精确 Gmail 拉取：`query=NOMI_E2E_GMAIL_0618 newer_than:3d`，HTTP 200，约 1.95s，`fetched_count=0`，`persisted_count=0`。
- `agenda_items` / `proactive_suggestions` 中能查到旧的“人民广场”历史测试记录，但不是本次可控 token，不计入本次真实验收通过证据。

### 结论

- 当前不能继续验证 Gmail/WhatsApp/Telegram 新消息端到端链路，因为没有本次可控真实输入进入系统。
- 下一步需要用户发送或登录真实账号后发出唯一测试消息。

## 2026-06-20 Gmail 真实账号端到端验收

### 用户输入

用户已发送真实 Gmail 邮件：

- 主题：`明天下午4点人民广场见`
- 正文：`请明天下午4点在人民广场见面，带合同。`

注：用户原计划标题中的 `NOMI_E2E_GMAIL_0618` 未出现在最终邮件主题/正文里，因此精确 token 查询返回 0 是合理的。

### Gmail 拉取

执行：

- `POST /api/collectors/gmail/composio/fetch`
- 查询：`newer_than:1d`
- 结果：HTTP 200，约 2.05s。
- `fetched_count=1`，`persisted_count=1`。
- 新事件：`87b2410f-4946-474f-9e1a-5a7bba06799d`。

合理性检查：

- 正确拉取到用户刚发送的真实 Gmail。
- 事件 source 为 `gmail`，event_type 为 `gmail_message_snapshot`。
- subject/body 内容与用户邮件一致。
- 问题：`snippet/body` 展示仍是 `{'body': ..., 'subject': ...}` 字典字符串形态，后续 UI/日程/建议被污染。

### 事件处理、日程和主动建议

worker 处理：

- `worker processed ... event_id=87b2410f... source=gmail event_type=gmail_message_snapshot intent=social_plan`

日程结果：

- 类型：`appointment`
- 地点：`人民广场`
- 时间：`2026-06-21T16:00:00+08:00`
- 显示：`2026-06-21 周日 16:00`
- 依据：邮件进入时间 `2026-06-20T21:06:15+08:00`，所以“明天下午4点”解析为 2026-06-21 16:00，合理。
- 参与人：发件人被脱敏为 `"张子长" <EMAIL_1>`。

主动建议结果：

- title：`处理邮件待办`
- actions：`查路线`、`帮我打车`、`稍后提醒`
- `帮我打车` 标记为 `external_execution` 且 `requires_confirmation=true`，风险门禁合理。

问题：

- 日程 title 混入 `{'body': '请明天下午4点在人民广场见面，带合同。', 'subject': '明天下午4点人民广场见'}`。
- 建议 body 也混入字典字符串。
- metadata 中 `validation_warnings=["model_parse_failed:ReadTimeout"]`，说明模型解析超时后规则兜底；时间/地点结果正确，但质量链路仍不稳定。

结论：

- Gmail 真实拉取：`passed`。
- 私有事件入库：`passed`，但展示字段规范 `failed`。
- 日程创建：`partial`，核心时间/地点正确，title 不合格。
- 主动建议：`partial`，动作和风控合理，文案不合格。

### 工作台 / Android 展示

API：

- `/api/suggestions?limit=10` HTTP 200，约 1.07s，包含该 Gmail 建议。
- `/api/agenda?limit=10` HTTP 200，约 0.24s，包含该 Gmail 日程。

Android 真机 UI dump：

- 设备：`DQYTCYFMO7VSEAJB`。
- 页面显示 `处理邮件待办`。
- 页面显示建议正文，但同样包含字典字符串污染。

结论：

- 工作台/Android 能看到真实 Gmail 触发的建议：`passed`。
- UI 文案质量：`failed`。

### 对话回答

问题：

> 我刚收到的 Gmail 里，明天下午4点人民广场见这件事是什么时候？需要带什么？请只基于你已经记录的真实邮件回答。

结果：

- HTTP 200，约 8.04s。
- 回答：时间为 2026-06-21 16:00，地点人民广场，需要携带合同。
- context_pack 包含该 Gmail event id `87b2410f-4946-474f-9e1a-5a7bba06799d` 和日程 id `67986e7e-2901-423a-9e7e-b478d9256cb2`。
- latency_trace：total 7781ms，context retrieval 725ms，model 6885ms。

合理性检查：

- 回答内容正确，没有编造额外信息。
- 能结合真实 Gmail 记录和自动创建的日程回答。
- 延迟偏高，但本轮没有超时。

结论：

- Gmail 真实事件 -> 对话问答：`passed`。
- 性能：`partial`，首轮约 8 秒，仍需继续优化流式首 token 和模型耗时。

## 本轮总评

本轮真实账号 Gmail 链路不是全通过，也不是全失败：

- 已通过：真实 Gmail 拉取、事件入库、日程绝对时间解析、主动建议动作生成、Android/工作台可见、对话能正确回答。
- 未通过：邮件 payload 规范化和 UI 文案质量；模型解析超时后规则兜底；对话整体耗时偏高。
- 未覆盖：WhatsApp/Telegram 真实新消息链路仍未由本轮可控消息验证。
