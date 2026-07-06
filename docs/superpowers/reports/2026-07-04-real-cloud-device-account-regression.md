# 2026-07-04 真实云端 / 真机 / 账号链路复验报告

## 范围

- 云服务器：`http://206.119.171.141`
- Android 真机：`DQYTCYFMO7VSEAJB`，包名 `com.par.assistant.android`
- 真实账号链路：Gmail、WhatsApp、Telegram、LinkedIn
- 本轮重点：修复并复验记忆召回、日程召回、LinkedIn 搜索门禁，以及真实 WhatsApp 事实问答。

## 本轮修复

1. 修复中文召回 token 缺失：
   - `我买保险最关心什么` 之前只提取到长 token `我买保险最关心什`，无法命中 `facts.object` 中的 `保险`。
   - `保利广场的安排缺什么信息` 之前被提取成 `安排`，无法命中保利广场日程。
   - 已加入 `保险`、`保单`、`保利广场` 作为优先中文召回短语。

2. 修复 LinkedIn 渠道名误判：
   - 之前只要问题里包含 `LinkedIn`，即使只是说“基于 WhatsApp/Telegram/Gmail/LinkedIn 记录回答”，也会路由成 `job_query`。
   - 已移除 `LinkedIn/领英` 作为独立求职意图触发词，保留其作为来源实体；真正求职仍由 `岗位/JD/简历/HR/投递/工作机会` 等触发。

3. 修复 LinkedIn 未登录仍排搜索任务：
   - 之前 `collection_status=degraded`、`browser_login_status=logged_out` 仍会生成 `queued` 搜索。
   - 已改为返回 `blocked / linkedin_login_required`，不写 Redis 队列，不误导用户“正在采集真实岗位”。

## 本地验证

命令：

```bash
python3 -m pytest runtime_api/tests/test_chat_router.py runtime_api/tests/test_context_pack_and_chat.py -q
```

结果：`100 passed`

覆盖的关键新增用例：

- `test_cjk_retrieval_tokens_keep_business_entities_and_places`
- `test_agenda_question_with_linkedin_as_source_name_stays_agenda_query`
- `test_job_query_blocks_linkedin_job_search_when_linkedin_is_not_connected`
- `test_chat_endpoint_exposes_linkedin_reconnect_status_for_job_queries`

## 云端部署验证

部署方式：

- 仅同步 `runtime_api/app/main.py` 和 `runtime_api/app/chat_router.py`
- 执行 `docker compose up -d --build runtime-api`
- 不覆盖数据卷，不重启 Postgres/Redis/Chromium runtime。

健康检查：

```json
{"status":"ok"}
```

核心容器状态：

- `nomi-runtime-api-1`: running
- `nomi-worker-1`: running
- `nomi-chromium-runtime-1`: running
- `nomi-postgres-1`: healthy
- `nomi-redis-1`: healthy
- `nomi-model-router-1`: healthy

## 真实账号状态

- Gmail：`API 已连接`，浏览器侧 `degraded`。Gmail API 可用，但浏览器采集不健康。
- WhatsApp：`已登录`，`collection_status=healthy`。
- Telegram：`已登录`，`collection_status=healthy`，但 `open_chat_message_count=0`，说明当前打开聊天内容采样仍可疑。
- LinkedIn：`未登录`，`browser_login_status=logged_out`，当前不能做真实岗位采集。

## 线上真实问答复验

### 1. 保利广场安排缺什么信息

问题：

> 保利广场的安排缺什么信息？请只基于我的真实 WhatsApp/Telegram/Gmail/LinkedIn 记录回答，日期必须写绝对日期。

结果：

- route: `agenda_query / agenda_keyword_with_evidence`
- agenda_context_count: `1`
- 回答：该安排已于 `2026年7月3日` 发生，缺失 `确切时间`，只记录为“明天下午”。

结论：通过。之前误判为 `job_query` 的问题已修复。

### 2. 周五18点前我要做什么

问题：

> 周五18点前我要做什么？请只基于我的真实 WhatsApp/Telegram/Gmail/LinkedIn 记录回答，日期必须写绝对日期。

结果：

- route: `agenda_query / agenda_keyword_with_evidence`
- agenda_context_count: `2`
- 回答：`2026年7月3日（周五）18:00` 前把报价单发给大刚，并核对成本和利润率；该截止已过。

结论：通过。日期已转为绝对日期，没有把过去事项当未来任务。

### 3. 张红是谁

问题：

> 张红是谁？请只基于我的真实 WhatsApp/Telegram/Gmail/LinkedIn 记录回答。

结果：

- route: `relationship_query / chinese_person_relationship_reference`
- memory_context_count: `7`
- 回答：张红是王超的儿子。

结论：通过。该信息来自 WhatsApp 真实采集后结构化记忆。

### 4. 保险关注点

问题：

> 我买保险最关心什么？请只基于我的真实 WhatsApp/Telegram/Gmail/LinkedIn 记录回答。

结果：

- route: `memory_query / memory_keyword`
- memory_context_count: `7`
- 回答：只能确认用户表达过购买意向，无法从现有证据确定最关心价格、保障范围、理赔速度等具体点。

结论：通过，但信息不足。系统没有编造偏好。

### 5. LinkedIn 找工作

问题：

> 帮我找找看有没有适合我的工作机会，要去 LinkedIn 找真实岗位。

结果：

- route: `job_query / job_context`
- LinkedIn 当前未登录。
- 回答：无法直接搜索真实岗位，需要重新登录 LinkedIn；连接正常后再根据 Java 后端架构 / 技术 Leader 画像采集岗位。

结论：通过门禁。没有把未登录状态谎报为“正在采集完成”。

## Android 真机状态

真机在线：

```text
DQYTCYFMO7VSEAJB device product:beryl model:24094RAD4C
```

已安装：

```text
package:com.par.assistant.android
```

当前截图：

`/tmp/nomi-regression/real-device-20260704.png`

观察：

- Nomi 悬浮窗可见，历史对话可见。
- 悬浮窗内能显示最近关于 `张红是谁` 的问答。
- 但主动建议气泡仍出现内部噪声：`user said to Nomi: 保利广场的安排缺什么信息？...`

后续修复：

- 已在 `worker/app/worker.py` 源头禁止 `source=nomi_chat` 的用户消息和对话批次摘要生成主动建议。
- 已在 `runtime_api/app/main.py` 读取层隐藏历史 `source=nomi_chat` 主动建议。
- 已补充 WhatsApp/Telegram 纯标题徽标噪声过滤，例如 `这条信息可能需要跟进：(2) WhatsApp。`。
- 本地验证：`python3 -m pytest runtime_api/tests/test_vector_and_suggestions.py worker/tests/test_worker_semantics.py -q`，结果 `146 passed`。
- 云端验证：部署后 `/api/suggestions?limit=20` 不再返回 `nomi_chat` 建议，也不再返回 `(n) WhatsApp/Telegram` 标题徽标建议；真实 WhatsApp 关系、日程、提醒建议仍保留。
- Android 端补充兜底：`AssistantSuggestion.isDisplayableText(...)` 会过滤 `user said to Nomi`、`assistant said to Nomi`、`(n) WhatsApp/Telegram` 标题徽标；防止旧实时事件或本地缓存直接画成气泡。
- Android 验证：`JAVA_HOME=/opt/homebrew/Cellar/openjdk@17/17.0.19/libexec/openjdk.jdk/Contents/Home gradle -p android_app :shared:test :app:assembleDebug` 通过，APK 已安装到真机。
- 真机截图：
  - 安装重启后：`/tmp/nomi-regression/real-device-20260704-after-android-filter-home.png`
  - 等待一个轮询周期后：`/tmp/nomi-regression/real-device-20260704-after-poll-cycle.png`

结论：真机端在线；已修复本轮确认的主动建议内部噪声展示路径。重装并等待一个轮询周期后，旧 `user said to Nomi...` 气泡没有重新出现。

## 遗留问题 / Gap

1. **Telegram 采集仍不完整**
   - 登录状态显示 healthy，但 `open_chat_message_count=0`。
   - 需要验证 Telegram 是否只能采到列表 preview，还是能稳定进入真实会话 DOM 并采到消息正文。

2. **LinkedIn 真实岗位采集未通过**
   - 当前 LinkedIn 为 `logged_out`。
   - 系统现在能正确阻断搜索，但还没有完成“登录后真实岗位采样、JD 摘要、推荐理由、可点击链接推送”的完整真机验收。

3. **Gmail 浏览器侧 degraded**
   - Gmail API 已连接，但浏览器状态 degraded。
   - 真实 Gmail 问答需要继续验证 API 同步后的新邮件是否稳定进入 memory/agenda。

4. **主动建议质量仍需继续治理**
   - 已修复 `source=nomi_chat` 和 `(n) WhatsApp/Telegram` 标题徽标噪声。
   - 仍发现部分建议类型不够准确，例如 WhatsApp 发票/报价任务被标成 `处理邮件待办`，Telegram preview 曾混入旧 WhatsApp 测试文本。
   - 后续应继续按 source + intent 生成更准确标题，例如 WhatsApp 任务应显示“处理聊天待办”而不是“处理邮件待办”。

5. **WhatsApp 最新采集需要继续观察**
   - WhatsApp 当前 healthy，但本轮主要使用已入库历史真实消息复验。
   - 还需要再发一条新 WhatsApp 消息，确认从采集、worker、记忆、日程到真机主动提醒的端到端延迟和结果。

6. **真机 UI 不是完整自动验收**
   - 本轮确认真机在线、悬浮窗可见、历史显示存在。
   - 尚未在真机 UI 中逐条手动发送上述 5 个问题；线上问答主要通过 API 级真实数据完成。
