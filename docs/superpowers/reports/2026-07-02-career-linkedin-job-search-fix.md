# 2026-07-02 求职问答与 LinkedIn 岗位采集修复报告

## 背景

用户在 Android 悬浮窗中询问“帮我找找看有没有适合我的工作机会”时，Nomi 返回“没有关于职业背景技能偏好等记录”。这不合理：用户此前提供过完整简历，并且该类请求应当进入求职链路，至少触发 LinkedIn 岗位采集，而不是只做普通聊天。

## 实际原因

1. 聊天路由已能识别求职请求，但 `/api/chat` 之前只把 `career_context` 放进模型上下文，没有把“找工作机会”转成 LinkedIn Jobs 采集命令。
2. 云端职业库当时没有完整简历记录，`career_resumes=[]`，因此模型只能看到旧职业画像或旧机会。
3. 云端存在旧岗位机会，曾污染当前回答，导致后端简历问答里夹带旧 Product Manager 岗位。
4. 原始微信临时路径里的 `后端-范小刚.pdf` 已失效，但在微信文件目录中找到了同名 PDF。

## 本次修复

1. 新增聊天侧 LinkedIn Jobs 搜索排队：
   - 求职问题会从职业画像/简历提取搜索词。
   - 生成只读浏览器命令 `open_linkedin_job_search`。
   - 命令写入 `browser:commands`，带 10 分钟去重 key。
   - 不自动加人、不私信、不投递，不产生外部副作用。
2. 新增 `/api/browser/search-linkedin-jobs` 与 chromium runtime 执行适配：
   - 只允许 `https://www.linkedin.com/jobs/search/`。
   - 拒绝非 LinkedIn Jobs 搜索 URL。
   - 预期采集事件为 `linkedin_job_search_results`。
3. 修复职业上下文污染：
   - 当新简历/新职业画像晚于旧岗位机会时，聊天上下文不再注入旧岗位。
   - 目的：避免后端简历问答中出现旧的 PM 机会。
4. 导入真实简历到线上：
   - 文件：`后端-范小刚.pdf`
   - 解析结果：2 页，3797 字。
   - 写入：`career_resumes` 与 `career_profiles`。
   - 画像摘要：Java/Go 后端、JVM 调优、高并发、高可用、分布式系统、Kafka/RocketMQ/Redis/ES/MySQL、AI Agent、LLM workflow automation、技术 Leader。
5. 优化求职回答提示：
   - 不再把 `queued`、`duplicate_skipped`、`degraded` 等内部状态码原样暴露给用户。
   - 翻译成“正在采集”“相同搜索刚刚提交过”“连接不稳定”等自然语言。

## 本地验证

执行命令：

```bash
python3 -m pytest \
  runtime_api/tests/test_chat_router.py \
  runtime_api/tests/test_job_agent_pipelines.py \
  runtime_api/tests/test_context_pack_and_chat.py::test_career_context_excludes_stale_opportunities_after_new_resume \
  runtime_api/tests/test_context_pack_and_chat.py::test_job_query_can_queue_linkedin_job_search_from_career_context \
  runtime_api/tests/test_context_pack_and_chat.py::test_chat_endpoint_exposes_linkedin_job_search_status_for_job_queries \
  runtime_api/tests/test_context_pack_and_chat.py::test_chat_endpoint_adds_career_context_for_job_queries -q
```

结果：`61 passed`。

另执行 LinkedIn 浏览器命令相关测试：

```bash
python3 -m pytest \
  runtime_api/tests/test_browser_login_commands.py::test_browser_search_linkedin_jobs_queues_generated_jobs_search_command \
  runtime_api/tests/test_browser_login_commands.py::test_browser_search_linkedin_jobs_rejects_empty_query \
  chromium_runtime/tests/test_runtime_recovery.py::test_execute_browser_job_search_command_navigates_to_restricted_jobs_search \
  chromium_runtime/tests/test_runtime_recovery.py::test_execute_browser_job_search_command_rejects_untrusted_url -q
```

结果：通过。

## 线上验证

部署到云服务器 `206.119.171.141`：

- `runtime-api` 已重建并重启。
- `chromium-runtime` 已重建并重启。
- SSH 当前可用端口是 `22`；`10799` 当前超时。

线上导入简历结果：

- `status=completed_read_only`
- `file_type=pdf`
- `writeback.failed_count=0`
- `writeback.applied_count=2`
- `writeback_performed=true`

线上再次询问：

> 帮我找找看有没有适合我的工作机会

实际回复：

> 正在为您采集岗位信息。由于系统检测到相同的搜索请求刚刚提交过，目前正处于后台抓取阶段。
> 一旦采集到具体的职位描述（JD），我将立即结合您的简历（Java/Go 后端架构、技术 Leader 背景）进行筛选和推荐。

结果判断：

- 不再回答“没有职业背景”。
- 能识别为 `job_query`。
- 能使用真实导入的后端简历。
- 能触发 LinkedIn Jobs 搜索任务。
- 不再混入旧 Product Manager 岗位。
- 不暴露内部状态码。

Redis 证据：

```json
{
  "action": "open_linkedin_job_search",
  "source": "linkedin",
  "url": "https://www.linkedin.com/jobs/search/?keywords=Backend+Engineer&location=Remote",
  "query": "Backend Engineer",
  "location": "Remote",
  "expected_event_type": "linkedin_job_search_results",
  "external_side_effect": false
}
```

## 仍未关闭的 Gap

1. 真实 LinkedIn Jobs 搜索结果回流尚未在本轮完成确认：
   - 已确认命令生成和排队。
   - 还需要等待/验证 chromium-runtime 打开页面后是否成功采集 `linkedin_job_search_results` 并写入 `job_opportunities`。
2. LinkedIn 当前采集状态仍可能不稳定：
   - 如果账号登录态、页面崩溃或平台限制导致采集失败，Nomi 会继续提示需要重新连接或继续执行。
3. 目前只实现“找岗位/采集 JD”的只读链路：
   - 自动加人、私信、Apply/Submit 仍受授权门禁限制。
   - 本轮没有执行任何真实外部副作用。
4. 求职看板仍保留历史手工岗位：
   - `/api/career/board` 仍会展示 2026-06-24 的旧 Product Manager 手工岗位。
   - 本轮只在聊天上下文中过滤旧机会，避免污染当前求职回答。
   - 后续需要给看板增加“按当前默认简历/画像过滤”“归档历史测试岗位”或“用户手动清理”能力。

## 2026-07-02 继续真实验证

### LinkedIn Jobs 采集链路

再次通过线上 API 发起只读 LinkedIn Jobs 搜索：

- 请求：`POST /api/browser/search-linkedin-jobs`
- 搜索词：`Java Backend Engineer 45e8c6`
- 地点：`Remote`
- 命令 ID：`7159692f-9d68-40aa-b56a-959ba2b17c9e`
- 命令状态：`navigated`
- 目标 URL：`https://www.linkedin.com/jobs/search/?keywords=Java+Backend+Engineer+45e8c6&location=Remote`

结果判断：

- 浏览器命令队列和 chromium-runtime 执行是通的。
- 但 collector 没有写入 `linkedin_job_search_results`。
- `job_opportunities` 没有新增真实 LinkedIn 岗位。

线上 `collector_health` 证据：

```json
{
  "collector": "linkedin",
  "status": "degraded",
  "browser_login_status": "logged_out",
  "failure_reason": "login_required",
  "message": "LinkedIn is waiting for user login.",
  "user_action": "请在云端浏览器登录 LinkedIn。"
}
```

因此当前真实结论是：LinkedIn 搜索 pipeline 已能触发云端浏览器打开 Jobs 页面，但云端 LinkedIn profile 未登录，真实岗位采集闭环未通过。需要用户在云端浏览器完成 LinkedIn 登录后，再重新执行岗位搜索和采集验收。

已进一步调用登录入口：

- 请求：`POST /api/browser/open`
- source：`linkedin`
- 命令 ID：`4ebfa825-7846-486c-ac6d-2b6e102e551e`
- 命令状态：`focused`
- 当前云端浏览器 URL：`https://www.linkedin.com/login/`
- 当前页面标题：`LinkedIn Login, Sign in | LinkedIn`
- collector 状态：`logged_out`

也就是说，云端浏览器已准备在 LinkedIn 登录页，后续需要用户完成账号登录，之后才能继续验证真实岗位采集、写入和推荐闭环。

### WhatsApp / Telegram / Gmail 账号状态

`/api/collectors/status` 验证结果：

- Gmail：`api_connected`，浏览器采集 `degraded`，Gmail API 可用。
- WhatsApp：`healthy` / `logged_in`，可采集当前可见页面。
- Telegram：`healthy` / `logged_in`，可采集当前可见页面。
- LinkedIn：`degraded` / `logged_out`，需要云端浏览器登录。

### WhatsApp 真实消息写入

已在 `events` 表中确认 WhatsApp 真实消息进入系统：

- `请记住：我的测试暗号是海盐拿铁。 测试码P1`
- `明天下午3点半在人民广场见，带合同。 测试码M1`
- `周五18点前把报价单发我，记得核对成本和利润率。 测试码T1`
- `哈哈哈今天太阳真大。 测试码N1`

这些消息的采集来源包括 `whatsapp_message`、`whatsapp_snapshot` 和 `whatsapp_open_chat_snapshot`。

### 日程与提醒验证

`agenda_items` 中确认：

- 人民广场会面已落为绝对时间：`2026-07-02 周四 15:30`，地点 `人民广场`，参与人 `大刚`。
- 报价单截止已落为绝对时间：`2026-07-03 周五 18:00`。

`agenda_reminders` 中确认：

- 人民广场线下会面生成了提前 40 分钟提醒。
- `2026-07-02 15:30` 的提醒对应 `2026-07-02 14:50`，状态为 `sent`。

### 问答验证

线上 `/api/chat` 验证结果：

1. 问：`人民广场见面的具体时间是哪年哪月哪天几点？请只根据我的聊天和日程回答。`
   - 实际回答：`2026年7月2日（周四）15:30`
   - 结论：通过。回答使用了 `agenda_context`，没有把“明天”原样输出。
2. 问：`我的测试暗号是什么？`
   - 实际回答：`海盐拿铁`
   - 结论：通过。回答使用了 WhatsApp 长期记忆和知识图谱证据。
3. 问：`周五18点前我要处理什么？`
   - 实际回答：发送报价单，并核对成本和利润率。
   - 结论：通过。内容合理，但 sources 中仍混入较长 daily_summary，后续可优化证据摘要。
4. 问：`帮我找找看有没有适合我的工作机会`
   - 实际回答：正在采集岗位信息，已根据职业画像在 LinkedIn 提交搜索请求。
   - 结论：不通过。回答没有暴露 LinkedIn 当前 `logged_out` 的真实阻塞，会让用户误以为采集已在后台正常进行。

### 新发现问题

1. LinkedIn 未登录时，求职回答应明确提示“需要先登录云端 LinkedIn”，而不是只说“正在采集”。
2. 当前 open 主动建议中仍有历史重复和误触发：
   - 多条 `NOMI_REG_WA_0629` / `NOMI_REG_TG_0629` 旧建议仍为 `open`。
   - 用户问句本身也被生成了“跟进近期安排”建议。
   - 说明主动建议去重维护有效但不完整，需要继续限制 `nomi_chat` 问句进入 social followup。
3. `agenda_reminders` 仍有旧错误 pending 提醒：
   - 旧的 `15:00` 误解析提醒。
   - 由 WhatsApp 整页快照噪声生成的 `07:53` 错误提醒。
   - 正确的 `15:30 / 14:50` 提醒已发送，但旧脏数据需要清理或在 UI/API 层过滤。
