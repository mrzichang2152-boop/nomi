# 2026-07-04 LinkedIn 真实求职链路复验记录

## 环境

- 云服务器：`http://206.119.171.141`
- API 密码：`par-dev`
- 真机：`DQYTCYFMO7VSEAJB`
- LinkedIn 状态：用户已完成登录，云端 noVNC 可打开真实 LinkedIn 岗位页。
- 外部动作策略：本次不执行真实 Apply / Submit / 加人 / 私信，只验证推荐、打开岗位和申请前确认门禁。

## 已通过

### 1. LinkedIn 岗位详情采集

操作：

1. 通过 `/api/browser/open-linkedin-job` 打开真实岗位：
   `https://www.linkedin.com/jobs/view/4388714215/`
2. Chromium Runtime 拉取命令并重新采集页面。
3. Worker 处理新事件：
   `event_id=ccc8b067-f4a3-459b-af71-fe4201a2299c`

实际结果：

- 采集事件类型：`linkedin_job_description_snapshot`
- 页面标题：`Backend Engineer, AI (Agent Systems) | BJAK | LinkedIn`
- 岗位 URL：`https://www.linkedin.com/jobs/view/4388714215/`
- JD 正文包含岗位职责、技术栈、公司介绍等真实 LinkedIn 页面内容。

判断：

- 采集链路通过。
- 该岗位确实来自真实 LinkedIn 页面，不是 mock 数据。

### 2. LinkedIn 公司字段解析修复

发现的问题：

- 修复前，岗位公司被错误解析为 `Responses managed off LinkedIn`。
- 根因是 parser 不支持 `岗位 | 公司 | LinkedIn` 标题结构，并把 LinkedIn 的响应托管说明误识别为公司名。

修复：

- `chromium_runtime/app/runtime.py`
  - 支持 `岗位 | 公司 | LinkedIn` 标题解析。
  - 将 `Responses managed off LinkedIn` 标记为 UI/噪声，不再作为公司候选。

验证：

- 新增并通过测试：
  - `chromium_runtime/tests/test_linkedin_parser.py::test_parse_linkedin_real_job_detail_prefers_title_company_over_response_noise`
- LinkedIn parser 全量测试：
  - `12 passed`
- 线上看板复验：
  - `linkedin_job_4388714215`
  - title: `Backend Engineer, AI (Agent Systems)`
  - company: `BJAK`
  - location: `Beijing, Beijing, China`
  - source_event_ids: `ccc8...` + 历史事件

判断：

- 公司字段解析已修复并部署生效。

### 3. 求职推荐回答

请求：

```text
帮我找找看有没有适合我的工作机会
```

实际输出摘要：

1. 推荐 `Backend Engineer, AI (Agent Systems)`
   - 公司/地点：`BJAK · Beijing, Beijing, China`
   - 链接：`https://www.linkedin.com/jobs/view/4388714215/`
   - 匹配度：`95%`
   - 推荐理由：匹配 `distributed systems`、`AI Agent`、`LLM product`、`workflow automation`
2. 推荐 ByteDance 岗位。
3. 推荐 Sensata Technologies 岗位。

判断：

- 能基于真实 LinkedIn 采集结果和已导入简历画像输出推荐。
- BJAK 公司名已正确进入推荐结果。
- 输出明确声明未执行投递、加人或私信。

### 4. Apply / Submit 门禁

请求：

```text
帮我申请 BJAK 这个 LinkedIn 岗位
```

实际输出摘要：

- 已定位岗位：`BJAK - Backend Engineer, AI (Agent Systems)`
- 岗位链接：`https://www.linkedin.com/jobs/view/4388714215/`
- 匹配依据：`distributed systems`、`AI Agent`、`LLM product`、`workflow automation`
- 明确提示：
  - Apply / Submit 属于外部执行动作。
  - 当前不会直接点击或提交。
  - 可以先生成定制简历、Cover Letter、申请前检查。
  - 最终点击提交前仍需再次确认。
- 状态：未执行投递、未点击 Apply、未提交任何表单。

判断：

- 申请门禁通过。
- 没有真实副作用。
- 2026-07-05 真机复验：
  - 真机悬浮窗输入：`Apply to BJAK LinkedIn job`
  - 服务端历史记录中返回：
    - 已定位岗位：`BJAK - Backend Engineer, AI (Agent Systems)`
    - 岗位链接：`https://www.linkedin.com/jobs/view/4388714215/`
    - 明确说明 `Apply/Submit 属于外部执行动作，我现在不会直接点击或提交`
    - 状态：`未执行投递、未点击 Apply、未提交任何表单`
  - 真机截图：`/Users/wrf/Documents/background/tmp/real-device-linkedin-apply-gate-after-send.png`

### 5. LinkedIn 页面误入日程的云端修复

发现的问题：

- LinkedIn 岗位页事件曾被语义层误判为日程，真机日程页出现过包含 `0 notifications`、`Skip to footer`、岗位标题和 `Responses managed off LinkedIn` 的日程卡。
- 这类内容来自浏览器页面采集，不是用户约定，因此不应进入日程 pipeline。

根因：

- `linkedin_job_description_snapshot` / `visible_job_detail` 的浏览器观察事件虽然已经被规则识别为低价值页面信号，但旧链路仍可能继续落到日程表。
- 历史数据中已有两条被污染的 LinkedIn 日程。

修复与验证：

1. 将旧污染日程标记为 `dismissed`：
   - `0b1f22b3-c40d-42b5-991c-9c6fdec955d2`
   - `d7810dc9-4680-47dc-9417-e4dd678eb6d5`
2. 修复 `PATCH /api/agenda/{id}` 的 SQL 歧义问题，避免 `created_at` 在 `agenda_items` 与 `agenda_versions` 之间歧义导致 500。
3. 重新注入真实 LinkedIn 岗位页事件：
   - `event_id=6f304dda-e282-4d8f-b30d-1e71511940c5`
   - `source=linkedin`
   - `event_type=linkedin_job_description_snapshot`
   - 原始标题：`Backend Engineer, AI (Agent Systems) | BJAK | LinkedIn`
4. 线上数据库验证：
   - `job_opportunities.linkedin_job_4388714215.title = Backend Engineer, AI (Agent Systems)`
   - `company = BJAK`
   - `url = https://www.linkedin.com/jobs/view/4388714215/`
   - 新事件关联的 `agenda_items` 数量为 `0`
5. Worker 日志验证：
   - `worker linkedin opportunities persisted event_id=6f304dda-e282-4d8f-b30d-1e71511940c5 count=1`
   - `intent=generic_event`
   - 未出现 `ForeignKeyViolation` 或日程写入错误。

判断：

- 云端处理链路已不再把该 LinkedIn 岗位页写入日程。
- 岗位表标题已清洗掉 `| BJAK | LinkedIn` 后缀，推荐卡可使用干净标题。
- 真机端重新安装 APK、强停旧悬浮服务进程、重新启动 Nomi 后打开日程页，旧 LinkedIn/BJAK 污染卡不再展示。

真机证据：

- `/Users/wrf/Documents/background/tmp/real-device-agenda-clean-run.png`
- 顶部展示的是 WhatsApp 来源的真实日程项，不再出现 `0 notifications`、`BJAK`、`Responses managed off LinkedIn` 等浏览器噪声。

### 6. 主动提醒外键异常修复

发现的问题：

- Worker 日志曾反复出现：
  `insert or update on table "proactive_suggestions" violates foreign key constraint "proactive_suggestions_source_event_id_fkey"`
- 失败样例中，agenda reminder 使用了不存在于 `events` 表的 UUID 作为 `source_event_id`。

修复：

- reminder 发送主动建议前会逐个校验 `source_event_ids` 是否真实存在于 `events` 表。
- 找不到真实事件时，`proactive_suggestions.source_event_id` 写入 `NULL`，而不是写入 reminder 自身 ID 或失效事件 ID。
- 实时推送 payload 中缺少事件来源时使用空字符串，避免客户端误认为存在可追溯事件。

验证：

- 本地 worker 单测：`113 passed`
- 线上 worker 重启后日志：
  - `worker agenda reminders dispatched count=3`
  - 未再出现同类 FK 错误。
- 线上数据库验证：
  - 失败过的 reminder 已变为 `sent`
  - 对应 proactive suggestion 的 `source_event_id` 为空，符合无真实事件来源的处理规则。

判断：

- 外键异常已按根因修复，不是简单吞错。
- 仍需后续真机验收提醒气泡展示是否符合用户预期。

### 7. Gmail 营销邮件误入日程的过滤修复

发现的问题：

- 真机日程页在 LinkedIn 污染卡消失后，仍显示一条 Gmail/Kajabi 营销邮件：
  `He was offered six figures to leave Kajabi...`
- 该内容是营销/newsletter，不是会议、约定、截止日期或提醒，不应进入日程展示。

修复：

- 扩展 Gmail 低价值日程过滤规则，只针对该类营销文案命中特征过滤：
  - `offered six figures to leave`
  - `platforms tried to buy`
  - `zero temptation to switch platforms`
  - `pricing question every expert`
  - `course wrong`
- 保持规则窄化，避免把真实用户发来的 Kajabi 业务安排一概屏蔽。

验证：

- 本地 targeted tests：
  - `runtime_api/tests/test_private_event_gap_closure.py::test_agenda_list_filters_low_value_browser_ui_noise`
  - `runtime_api/tests/test_private_event_gap_closure.py::test_agenda_list_filters_low_value_gmail_receipts_marketing_and_policy`
  - `runtime_api/tests/test_private_event_gap_closure.py::test_agenda_list_filters_real_world_gmail_and_telegram_noise`
  - `runtime_api/tests/test_private_event_gap_closure.py::test_agenda_list_filters_current_cloud_gmail_noise_without_hiding_useful_reminders`
  - 结果：`4 passed`
- 云端 `/api/agenda?status=scheduled&limit=50` 复验：
  - `noise_hits=[]`
  - 不再返回 `Kajabi`、`BJAK`、`notifications`、`Responses managed` 等噪声。
- 真机重新启动悬浮服务后打开日程页：
  - `/Users/wrf/Documents/background/tmp/real-device-agenda-clean-run.png`
  - Kajabi 营销卡不再出现。

判断：

- Gmail 营销邮件误入日程的问题已按真实样本修复。
- 该问题暴露出一个产品级风险：低价值邮件过滤仍偏规则化，后续需要结合更强的分类器与用户反馈闭环，避免靠逐条样本补规则。

## 未通过 / 仍需修复

### 1. 真机悬浮窗输入与内容展示仍不够稳定

现象：

- 强停旧悬浮服务并重新启动后，日程入口可以打开，聊天输入也可以发送。
- 但输入/查看仍有明显交互问题：
  - ADB 初次输入时容易因为输入框未获得焦点而失败，需要重新打开面板并点击输入框。
  - 发送后键盘保持打开，符合“不因发送自动收起”的设计，但实际会遮挡 assistant 的长回复。
  - 浮窗内部长回复滚动体验不稳定，真机上不容易查看完整岗位推荐列表，只能结合服务端历史核对完整内容。

结论：

- 真机 LinkedIn 推荐与申请门禁链路已能发起并返回，但 UI 可读性/滚动仍不能算通过。
- 需要把长回复拆成更适合浮窗的短卡片，或在浮窗里提供“展开详情/打开完整对话”的稳定入口。

### 2. 记忆治理页面暴露原始敏感事件字段

现象：

- 真机背景页为“记忆治理”。
- 页面直接展示了 `browser_network_event` JSON。
- 可见字段包含：
  - `capture_scope`
  - `runtime_network_hook`
  - `sensitive_reasons`
  - `url_secret`

判断：

- 普通用户 UI 不应暴露原始网络事件和敏感原因细节。
- 需要改成摘要/脱敏视图，原始 JSON 只允许调试模式查看。

### 3. 历史浮窗内容未与新看板完全同步

现象：

- 后端看板已把岗位公司修正为 `BJAK`。
- 真机浮窗历史里仍显示旧的 `A1` 推荐片段。

判断：

- 服务端状态已修复，但本地浮窗历史/旧消息不会自动改写。
- 可以接受为历史消息，但新推荐必须使用 BJAK。
- 如果产品要求历史消息也一致，需要增加“推荐卡引用岗位 ID，渲染时从最新岗位表取字段”的机制。

### 4. LinkedIn 推荐质量仍有弱项

现象：

- 2026-07-05 真机请求：
  `Find suitable LinkedIn jobs for my resume`
- 服务端历史完整返回中，前两条较合理：
  - `Backend Engineer, AI (Agent Systems)` / `BJAK`
  - `AI知识管理产品经理（用户产品）-火山方舟MaaS` / `ByteDance`
- 第三条为：
  - `Program Manager` / `Sensata Technologies`
  - 匹配度 `78%`
  - 推荐理由只写了“匹配你的 AI Agent”，但岗位名称与简历核心方向的相关性偏弱。

判断：

- 推荐链路可用，但排序/解释质量还不稳定。
- 后续应要求 Job Agent 对每条岗位输出 `必须匹配项`、`缺口`、`不推荐原因/降权原因`，不能只给泛化的“匹配 AI Agent”。

## 关键测试命令

```bash
python3 -m pytest chromium_runtime/tests/test_linkedin_parser.py -q
python3 -m pytest worker/tests/test_worker_semantics.py -q
python3 -m pytest \
  runtime_api/tests/test_private_event_gap_closure.py::test_agenda_patch_fetch_query_qualifies_agenda_timestamps \
  runtime_api/tests/test_private_event_gap_closure.py::test_agenda_patch_writes_user_correction_version \
  runtime_api/tests/test_private_event_gap_closure.py::test_agenda_snooze_updates_metadata_and_version \
  -q
python3 -m pytest \
  runtime_api/tests/test_context_pack_and_chat.py::test_deterministic_career_application_answer_blocks_submit_and_resolves_target \
  runtime_api/tests/test_context_pack_and_chat.py::test_career_application_answer_uses_recent_dialogue_linkedin_job_when_board_omits_target \
  runtime_api/tests/test_job_agent_pipelines.py::test_job_application_pipeline_blocks_apply_submit_without_delegated_grant \
  -q
```

## 结论

- 云端 LinkedIn 采集、岗位推荐、申请前确认门禁：通过。
- LinkedIn 岗位页误入日程：云端与真机均已验证，新事件关联日程数为 `0`，旧污染卡不再展示。
- Gmail/Kajabi 营销邮件误入日程：已修复并在云端 + 真机验证不再展示。
- Agenda PATCH 500 与 reminder FK 异常：已修复并完成线上验证。
- 真机 LinkedIn 推荐与申请门禁：已完成真实设备链路验证，未执行真实投递/私信/加人。
- 真机悬浮窗 UI 可读性：仍未通过，长回复查看和滚动体验不够稳定。
- 下一步应优先修/验：
  1. 将 LinkedIn 推荐结果改成短卡片/分页，避免长文本在悬浮窗里不可读。
  2. 记忆治理 UI 不展示原始敏感 JSON。
  3. 强化 Job Agent 推荐解释和降权逻辑，避免弱相关岗位被高分推荐。
  4. 继续验证“打开岗位页”按钮/链接能在真机中稳定打开正确 LinkedIn 页面。
