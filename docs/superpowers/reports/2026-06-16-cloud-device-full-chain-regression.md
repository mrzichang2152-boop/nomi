# 2026-06-16 线上云服务器 / Android 真机全链路回归报告

## 结论

本轮回归不是全绿。核心链路已经可用：云服务器部署健康、真实 Android 设备可连接线上服务、浮窗服务可运行、Android 真机可发送消息并收到模型回复、WhatsApp/Gmail/Telegram 类事件可写入记忆并触发日程/建议，主动建议气泡也能在真机上展示。

仍存在需要修复的点：

1. 部分对话检索会漏用已经存在的记忆，例如已能通过 `/search` 找到 `INV-RG-1001`，但 `/api/chat` 回答“没有找到发票信息”。
2. 部分 pipeline 路由不稳定，例如路线请求有时进 `openclaw_tool` 并 blocked，而不是稳定进入路线 pipeline。
3. 主动建议气泡点击后能打开工作台，但没有把该建议上下文直接带入对话/建议详情。
4. 工作台 UI 仍有旧式顶部 tab；浮窗对话框已符合较多交互要求，但完整工作台仍需要按新的产品设计继续收敛。
5. 历史回归数据里存在旧 agenda 污染和不合理日程项，例如把用户聊天“帮我制定面试计划”错误生成日程。

## 环境

- 云服务器：`206.119.171.141`
- 项目目录：`/opt/nomi`
- Compose project：`background`
- Android 真机：Redmi / `24094RAD4C`
- Android 版本：14
- 测试时间：2026-06-16 16:55 - 17:35 Asia/Shanghai
- 线上基础地址：`http://206.119.171.141`
- Android 配置：`base_url=http://206.119.171.141`，`password=par-dev`

## 云端部署检查

命令：

```bash
docker compose -p background ps --format json
curl -fsS http://206.119.171.141/health
```

结果：

- `background-runtime-api-1`：running
- `background-worker-1`：running
- `background-model-router-1`：healthy
- `background-postgres-1`：healthy
- `background-redis-1`：healthy
- `background-nginx-1`：running，80 端口开放
- `background-chromium-runtime-1`：running，6080 端口开放
- `/health` 返回 `{"status":"ok"}`

判定：通过。

## 自动化线上回归

执行：

```bash
APP_PASSWORD=par-dev \
REGRESSION_BASE_URL=http://206.119.171.141 \
REGRESSION_WS_TIMEOUT_SECONDS=90 \
REGRESSION_HTTP_TIMEOUT_SECONDS=90 \
python3 scripts/online-regression-g2-g5-checks.py
```

结果摘要：

- 采集能力检查通过：
  - Gmail：`api_or_browser`，`composio:gmail` + `managed_browser_visible_dom`
  - WhatsApp：`managed_browser_visible_dom`
  - Telegram：`managed_browser_visible_dom`
- WebSocket streaming chat 通过：
  - 收到 11 个 `chat_delta` 和 1 个 `chat_done`
  - 答案：`Pong. Online regression streaming check: OK.`
- route pipeline smoke 通过：
  - `route_type=core_pipeline`
  - `pipeline_id=route_pipeline`
  - `status=completed_read_only`
  - `resolved_slots.destination=武康路`

判定：基础线上接口与 WS 流式通道通过。

## 数据注入到记忆 / 日程 / 建议

本轮注入 10 条测试事件，覆盖 WhatsApp、Gmail、Telegram：

- WhatsApp 约见、改期、取消、报价上下文、跨联系人隐私上下文
- Gmail 报价截止、发票付款、利润率确认
- Telegram 面试/见面安排

worker 日志确认：

```text
worker memory batch enriched count=10 latency_ms=1269
```

定性检查：

- 10 条事件均写入 `events`。
- 10 条事件均产生 `semantic_event`。
- 10 条事件均产生 `memory_vectors`。
- 关键日程可被生成。
- 搜索可以召回：
  - `INV-RG-1001 1200 USD next Tuesday`
  - `PHONE_1 quote Friday 18:00 margin`
  - `RG_Alice PHONE_1 武康路`
  - `RG_Maya 静安寺 简历版本`

发现的问题：

- 发票记忆存在且 `/search` 可召回，但 `/api/chat` 的付款处理问题仍回答“未找到发票信息”。这是 chat context packing / retrieval routing 问题，不是记忆存储失败。
- 取消类事件仍可能生成“跟进日程安排”主动建议，需要更严格地区分取消、完成、忽略和待跟进。
- 部分历史旧数据存在 raw JSON 片段进入 agenda title 的问题，说明旧解析或清洗逻辑仍污染当前看板。

判定：记忆存储和基础召回通过；对话使用记忆存在失败点。

## 实时主动建议链路

注入事件：

```json
{
  "source": "whatsapp",
  "event_type": "message",
  "raw_data": {
    "run_id": "rg-live-android-20260616",
    "sender": "RG_LiveAlice",
    "chat_id": "rg-live-android-wa-alice",
    "text": "今天18:30在人民广场见，带上合同和PHONE_2报价单。到前请提醒我查路线。"
  }
}
```

实际服务端 event_id：

```text
4983d421-af22-4c65-b60c-265410e03d11
```

解析结果：

- intent：`social_plan`
- labels：`appointment`、`travel`、`todo`
- 日程：
  - title：`今天18:30在人民广场见，带上合同和PHONE_2报价单。到前请提醒我查路线。`
  - date：`2026-06-16`
  - start：`2026-06-16T18:30:00+08:00`
  - display：`2026-06-16 周二 18:30`
  - place：`人民广场`
  - participants：`RG_LiveAlice`
  - missing_fields：`[]`
- 主动建议：
  - title：`跟进近期安排`
  - body：`这条信息可能需要跟进：今天18:30在人民广场见，带上合同和PHONE_2报价单。到前请提醒我查路线。`
  - actions：
    - `查路线`
    - `帮我打车`，需要确认
    - `稍后提醒`

真机表现：

- 设备睡眠后唤醒，Nomi 浮窗出现红点 `1`。
- 展示气泡：`跟进近期安排：这条信息可能需要跟进：今天18:30在人民广场见，带上合同和...`

判定：主动建议服务端链路和真机气泡展示通过。

遗留体验问题：

- 点击气泡后进入完整工作台，但没有直接带入该建议详情或把建议上下文放入对话区。

## Android 真机浮窗 / 对话链路

安装与配置：

```bash
gradle :app:assembleDebug
adb -s DQYTCYFMO7VSEAJB install -r android_app/app/build/outputs/apk/debug/app-debug.apk
```

权限状态：

- `SYSTEM_ALERT_WINDOW: allow`
- `RECORD_AUDIO: allow`
- `POST_NOTIFICATIONS` 已授权
- `FloatingBallService` 是前台服务：

```text
isForeground=true foregroundId=1001
```

连接测试：

- Android 配置页显示：`服务器可达，访问密码正确，受保护 API 可用。`

真机发送消息：

输入内容：

```text
real%20device%20ping%20please%20reply%20pong
```

说明：这是 ADB `input text` 在该设备上的转义限制，`%20` 被作为字面文本输入，不代表用户真实键盘会这样。

UI 结果：

- 用户气泡出现。
- Nomi 气泡先显示 `正在思考...`。
- 随后返回：

```text
pong
```

交互检查：

- 点击发送后键盘没有自动收起：通过。
- 输入框在键盘上方：通过。
- 无 Android 崩溃日志：通过。

判定：Android 真机对话闭环通过。

## Chat / Pipeline 结果质量

通过项：

- `帮我回复 RG_Alice，说 PHONE_1 报价我会尽快确认。`
  - 能生成给 RG_Alice 的回复草稿。
  - 没有泄露 Bob 对 Alice 的私下评价。
  - 判定：通过。
- `帮我制定一个明天准备产品经理面试的三步计划。`
  - 能把“明天”标准化为 `2026-06-17`。
  - 能结合日程冲突给出准备计划。
  - 判定：基本通过。

失败 / 不完整项：

- `帮我处理 INV-RG-1001，但不要付款，只告诉我你找到了什么。`
  - `/search` 能找到发票。
  - `/api/chat` 回答没有找到发票信息。
  - 判定：失败，需修 context packing / chat retrieval。
- `帮我查去武康路的路线`
  - pipeline smoke 能通过。
  - 但某些自然表达会进入 `openclaw_tool` 并 blocked。
  - 判定：路由稳定性不足。
- `帮我回复这封邮件...`
  - 能进入 `reply_pipeline`。
  - 但 recipient 解析出 `"这封"`，说明 slot parser 对指代仍弱。
  - 判定：可用但不完整。
- `帮我处理 INV-RG-1001` payment pipeline
  - 未正确从记忆中找到发票上下文。
  - 判定：失败。

## 性能观察

本轮非 Android 自动化 chat latency：

| 用例 | 总耗时 | 上下文检索 | 模型 |
|---|---:|---:|---:|
| 回复 RG_Alice 报价 | 约 27.3s | 0.5s | 26.7s |
| 查询 INV-RG-1001 | 约 10.2s | 0.4s | 9.7s |
| 面试三步计划 | 约 27.1s | 0.6s | 26.5s |

结论：

- 当前瓶颈主要仍在模型生成，不在 DB 检索。
- Android 真机 “ping -> pong” 可返回，但仍需要继续采集首 token / 首字 latency，不只看最终响应。

## API 健壮性问题

用非 UUID 的 `conversation_id` 调 `/api/chat` 后，再访问：

```text
/api/chat/conversations/{conversation_id}/trace
```

会触发 500：

```text
invalid input syntax for type uuid
```

判定：需要在 `/api/chat` 入口校验或标准化 conversation_id，trace endpoint 不应把客户端输入导致的类型错误暴露成 500。

## 本轮证据文件

- `/tmp/nomi_device_panel_open.png`
- `/tmp/nomi_device_after_send2_sent.png`
- `/tmp/nomi_device_after_send2_35s.png`
- `/tmp/nomi_device_after_wake_live_event.png`
- `/tmp/nomi_device_after_bubble_tap.png`
- `/tmp/nomi_full_chain_regression.json`

## 下一步建议

优先级从高到低：

1. 修复 chat retrieval/context packing：确保 `/search` 能找到的发票、报价、日程，在 `/api/chat` 中也能被稳定使用。
2. 修复 payment/route pipeline 的路由和 slot 解析稳定性。
3. 修复取消/改期事件对主动建议和 agenda 状态的处理，避免取消事件继续提示“跟进日程”。
4. 修复 `/api/chat/conversations/{conversation_id}/trace` 的 UUID 健壮性。
5. 优化主动建议点击后的落点：点击气泡应进入建议详情或带着该建议上下文打开对话。
6. 清理旧回归数据污染，或为回归环境提供隔离用户 / 隔离 workspace。
7. 继续采集流式首 token / 首字耗时，按模型生成瓶颈继续优化。

## 2026-06-17 云端复测补充

本次复测范围：

- 云服务器：`206.119.171.141`
- Runtime API：`http://206.119.171.141`
- 回归 run id：`rg-20260616-live-e2e-c4`

### Chat Retrieval / 发票强标识符

复测请求：

```text
帮我处理 INV-LIVE-1601，但不要付款，只告诉我你找到了什么。
```

结果：

- 回答包含金额：`1200 美元`。
- 回答包含绝对到期日：`2026年6月23日（周二）`。
- 回答把状态表述为：`待付款（需确认）`。
- 回答明确：`未执行付款操作`。
- `sources[0]` 是 Gmail 原始事件，不再是旧 `nomi_chat` 问答。

判定：通过。之前“/search 能找到但 /api/chat 找不到或被旧回答污染”的问题已经修复。

### Web / API 可用性

实测：

| 入口 | 状态 | 耗时 |
|---|---:|---:|
| `/` | 200 | 约 0.13s |
| `/api/agenda?limit=10` | 200 | 约 0.17s |
| `/api/suggestions?limit=10` | 200 | 约 0.26s |
| `/api/career/board?limit=5` | 200 | 约 0.16s |

判定：通过。求职看板接口不再 404。

### 简单 Chat 延迟

复测请求：

```text
请只回复：pong
```

结果：

- 返回内容：`pong`。
- `latency_trace.total_ms`：约 `3068ms`。
- `context_retrieval_ms`：约 `43ms`。
- `model_ms`：约 `2900ms`。
- 外层 curl 总耗时：约 `5.3s`。

判定：通过当前“简单对话 5-10 秒内返回”的验收线。外层耗时仍高于内部 trace，后续可继续采集网络/反代/客户端渲染开销。

### Gmail / WhatsApp / Telegram 注入链路

注入事件：

- Gmail recruiter deadline：`822db2e4-45b6-403a-b808-062d1a87c1b0`
- WhatsApp meeting：`c4f22d93-aee2-464c-803f-4721d2983021`
- Telegram interview：`6492370b-23d8-4c7b-a690-4350a2275c11`

结果检查：

- Gmail：
  - semantic label：`deadline/todo`，合理。
  - agenda：`2026-06-19 周五 18:00`，标题包含 `Example AI`、`AI Product Manager`。
  - suggestion：提示处理邮件待办，动作包含“稍后提醒 / 查看原邮件”。
- WhatsApp：
  - semantic label：`appointment`，合理。
  - agenda：`2026-06-20 周六 15:00`，地点 `武康路`，参与人 `RG_Alice`。
  - suggestion：动作包含“查路线 / 帮我打车 / 稍后提醒”，打车仍需确认。
- Telegram：
  - semantic label：`reschedule/appointment`，合理。
  - agenda：`2026-06-17 周三 10:30`，标题包含“面试 / Zoom”。
  - missing fields：当前标记 `exact_place`，需要澄清。

二次检查：

- 三条事件在约 20 秒后均出现 `memory_vectors=1`、`facts=1`、`agenda=1`、`suggestions=1`。
- 说明 memory/vector 写入是异步完成，不是缺失。

判定：通过。每一步输出内容与原始消息一致且合理，不只是 HTTP 成功。

### 真机状态

本次复测时 `adb devices -l` 未发现设备：

```text
List of devices attached
```

判定：真机 UI 连续发送和真实界面回归暂时阻塞。需要重新连接/授权 Android 设备后继续执行。

### 服务端连续发送幂等

复测请求：

```text
message=请只回复：dedupe-ok
client_request_id=cloud-dedupe-check-20260617-001
```

结果：

- 第一次请求：约 `4.7s`，回答 `dedupe-ok`。
- 第二次同 `client_request_id` 请求：约 `0.26s`，返回 `duplicate=true`，回答仍为 `dedupe-ok`。
- conversation trace 显示只有 1 条 user turn 和 1 条 assistant turn。

判定：服务端 WebSocket/HTTP fallback 共享幂等键的核心机制通过。真机 UI 层连续发送仍需设备恢复后补测。

### Telegram Zoom 链接缺失字段修正

复测事件：

```text
面试 panel 改到明天10:30，Zoom 链接我稍后发。
```

事件 id：

```text
84a08c2b-c924-4f3a-9c0c-03a9e88a7aab
```

修复前问题：

- 系统能生成面试日程，但 `missing_fields` 标成 `exact_place`。
- 这不够合理，因为原消息已经说明是 Zoom 线上面试，真正缺的是会议链接。

修复后结果：

- agenda 时间：`2026-06-18 周四 10:30`。
- `metadata.pending_artifacts=["zoom_link"]`。
- `missing_fields=["exact_link"]`。
- `needs_clarification=true`。
- 二次查询确认异步落库完整：`memory_vectors=1`、`facts=1`、`agenda=1`、`suggestions=1`。

判定：通过。该用例现在符合 fixture 中“缺 exact_link”的验收要求。

### Composio Gmail 真实抓取链路

复测入口：

```text
POST /api/collectors/gmail/composio/fetch
query=newer_than:1d
limit=1
```

结果：

- Composio Gmail toolkit 已连接，真实抓取返回 1 封邮件。
- 返回事件 id：`6f46b382-447b-4235-988c-a2f02ba20101`。
- fetch 接口返回 `status=completed`、`fetched_count=1`、`persisted_count=1`。
- worker 日志显示该事件进入 `events:raw` 并被消费：

```text
worker processed ... event_id=6f46b382-447b-4235-988c-a2f02ba20101 source=gmail event_type=gmail_message_snapshot intent=generic_event
```

数据库复核：

- `semantic_events` 已生成，`intent=generic_event`。
- `memory_vectors` 已生成 1 条。
- semantic summary 识别到邮件主题为 `Stop picking coding models.`。
- 该邮件是普通营销/产品邮件，semantic entities 标为 `low_value`，未生成日程和主动建议。

合理性判断：

- 真实 Gmail -> Composio -> Runtime 入库 -> Redis 队列 -> worker semantic/memory 的链路通过。
- 该样本未生成 agenda/suggestion 是合理输出，不是失败；因为原邮件不包含约定、截止日期、付款、出行、购物、关系信号等需要主动处理的信息。
- 本地测试 `test_gmail_composio_fetch_persists_messages_as_collector_events` 通过，覆盖 fetch 后必须写入 `events:raw` 队列。

判定：通过。之前“Composio Gmail fetch 只入库但不进入 worker”的疑点已排除。

### Pipeline 路由与 slot 修复复验

路线请求：

- `帮我查去武康路的路线`
- `怎么去人民广场`
- `导航到静安寺地铁站`

结果：

- 三条请求均进入 `route_pipeline`。
- 状态均为 `completed_read_only`。
- 目的地分别解析为 `武康路`、`人民广场`、`静安寺地铁站`。

打车请求：

- `帮我打车去武康路`
- 结果进入 `ride_pipeline`。
- 状态为 `needs_user_input`，缺少 `pickup`，并保留最终确认。

付款请求：

- `帮我处理 INV-LIVE-1601`
- 结果进入 `payment_bill_pipeline`。
- `resolved_slots.amount_or_bill=INV-LIVE-1601`。
- 来源上下文中的 `counterparty=RG_CFO` 被正确带入。
- 风险门禁为 `confirmation_required`，未执行付款。

回复指代请求：

- `帮我回复这封邮件，说我周五八点可以`
- active source scope 提供 `source=gmail`、`sender/from=alice@example.com`。
- 结果为 `draft_ready`。
- `resolved_slots.recipient=alice@example.com`，`channel=gmail`，`message_intent=我周五八点可以`。

判定：通过。路线、打车、付款、回复四类 pipeline 的路由、slot 和安全门禁输出均与原始输入一致。

### 取消事件主动建议修正复验

注入事件：

```text
周日下午的武康路见面取消了，不用查路线，也不要帮我打车。
```

结果：

- semantic labels 包含 `cancel/appointment/travel/todo`。
- `entities.primary_label=cancel`。
- agenda 状态为 `canceled`，`missing_fields=[]`。
- suggestion title 为 `确认取消安排`。
- suggestion body 明确说明该消息是在取消或停止安排。
- suggestion actions 仅保留 `snooze` 和 `open_source`。
- 没有 `route_lookup` 或 `ride_prepare`。

判定：通过。取消类事件现在不会再被解释成普通跟进，也不会继续建议路线或打车。

### Trace API 非 UUID 健壮性复验

请求：

```text
GET /api/chat/conversations/not-a-uuid/trace
```

结果：

```json
{"detail":"conversation_id must be a UUID"}
```

HTTP 状态为 `400`。

判定：通过。非法 conversation id 不再触发 PostgreSQL UUID cast 500。

### F5 主动建议动作真机复验

复测目标：

- 验证主动建议页中的动作按钮不是只调用接口成功，而是能进入正确 pipeline，并把可读结果展示回 Android 真机对话页。

修复后线上行为：

- `/api/proactive/suggestions/{suggestion_id}/action` 返回 `chat_summary`。
- 后端将动作结果以 assistant turn 形式写入当前 `conversation_id`。
- Web 工作台动作请求携带 `conversation_id`，动作完成后切换到对话页并刷新历史；如果历史刷新暂时失败，再使用临时消息兜底。

服务端验证：

- 输入 suggestion action：`route_lookup`。
- 返回结果：
  - `pipeline_id=route_pipeline`。
  - `status=completed_read_only`。
  - `chat_turn_persisted=True`。
  - `resolved_slots.destination=上海博物馆`。
- 随后调用 `/api/chat/history?conversation_id=<same>`，可读到同一条 assistant 消息：

```text
已按建议进入：路线查询 Pipeline
目的地：上海博物馆
执行状态：completed_read_only
```

真机验证：

- 设备：Redmi `24094RAD4C`。
- 操作：打开 Nomi 工作台 -> 进入主动建议 -> 点击目标建议的 `查路线` 按钮。
- UI dump 结果包含：
  - `已按建议进入`
  - `路线查询 Pipeline`
  - `目的地：上海博物馆`
  - `执行状态：completed_read_only`
- UI dump 不包含：
  - `动作处理失败`
  - `处理中`
- 截图证据：`/tmp/nomi_after_route_fixed.png`。

合理性判断：

- 输出结果与源建议中的地点一致，进入的是路线查询 pipeline，不是错误进入打车、日程或长尾 agent。
- `completed_read_only` 表明该动作只做路线准备/查询语义处理，没有替用户执行不可逆操作。
- 结果来自服务端持久化的 assistant turn，刷新后仍可通过 chat history 读取，不是一次性前端提示。

判定：通过。
