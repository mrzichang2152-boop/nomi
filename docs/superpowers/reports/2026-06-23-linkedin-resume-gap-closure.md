# 2026-06-23 LinkedIn / Resume Gap Closure Report

## Scope

本次针对真实求职链路剩余 gap 做补齐：

1. 使用真实完整简历验证岗位匹配评分质量。
2. 补 LinkedIn recruiter / HR 主页联系人识别。
3. 补加人、批量私信、Apply / Submit 的可验收执行路径。
4. 修复 Android 真机 noVNC 页面断线后的重连体验。
5. 过滤 Android 主动气泡中的 `0 notifications total` UI 噪声。

## Results

### 1. 真实完整简历

状态：已完成。

实现：
- PDF 简历通过 `pypdf` 解析。
- 简历噪声行会被过滤，`姓名 / 性别` 挤在同一行时只抽取姓名。
- 后端技能抽取已覆盖 Java、Go、JVM、并发、高可用、分布式、Kafka、RocketMQ、Redis、Elasticsearch、MySQL、DDD、AI Agent 等后端架构技能。
- 岗位匹配评分已能对 Java 后端架构 JD 输出高匹配结果，并保留证据来源，不编造未出现在简历/JD 中的经历。

本地验证：
- 真实 PDF 输出：`profile_name=范小刚`，`headline=Java 后端架构 / 技术 Leader`，技能列表覆盖后端架构核心技能。
- `runtime_api/tests/test_job_agent_pipelines.py` 相关测试通过。

### 2. LinkedIn recruiter / HR 联系人识别

状态：已完成解析器、确定性搜索 pipeline、线上部署和真实 LinkedIn people search 验收；当前账号下候选人主页链接未暴露，因此候选主页自动打开以明确阻塞状态结束，未假装完成。

实现：
- LinkedIn `/in/` 个人主页新增 `linkedin_contact_snapshot`。
- 输出字段包括 `contact_id`、`name`、`headline`、`company`、`location`、`contact_kind`、`channel`、`profile_url`、`available_actions`、`text`。
- `contact_kind` 可识别 `recruiter`、`hiring_manager`、`professional_contact`。

本地验证：
- `chromium_runtime/tests/test_linkedin_parser.py` 全部通过。

线上状态：
- `chromium-runtime` 已随代码部署到云服务器。
- LinkedIn collector 的采样位置是云服务器上的托管 Chromium / noVNC 浏览器，不是 Android 桌面本身。
- 线上 `/api/collectors/status` 显示当前云端 LinkedIn 页面是 `https://www.linkedin.com/jobs/search/...AI Product Manager`，`event_types=["linkedin_visible_snapshot","linkedin_profile_snapshot","linkedin_job_description_snapshot","linkedin_job_search_results"]`。
- 已补应用自动打开 recruiter / HR 主页能力：
  - `runtime-api` 新增 `/api/browser/open-linkedin-profile`，只允许 `linkedin.com/in/...` 个人主页 URL，并入队给云端浏览器。
  - `chromium-runtime` 支持受限的 `open_url_direct`，拒绝任意外站和非 profile URL。
  - `chromium-runtime` 会从 LinkedIn job/search/detail 页 DOM 中发现明确的 recruiter / hiring / talent / HR 个人主页链接，并自动打开新页供 collector 采样。
- 已补“按公司 / 岗位主动搜索 recruiter / hiring manager”pipeline：
  - 新增确定性核心 pipeline：`linkedin_contact_search_pipeline`，已进入 `/api/pipelines/registry`，当前核心 pipeline 数量为 28。
  - 新增能力：`career.linkedin.contact_search`，路由关键词覆盖 `LinkedIn 搜索`、`recruiter`、`hiring manager`、`talent acquisition`、`招聘负责人`、`找 HR`。
  - Pipeline 输出 `browser.open_linkedin_contact_search` provider call plan，权限为 `read_only`，不会直接执行加人、私信、Apply 或 Submit。
  - `runtime-api` 新增 `/api/browser/search-linkedin-contacts`。
  - API 只接受 `company`、`job_title`、`location`、`reason`，不接受任意 URL。
  - 后端生成 LinkedIn people search URL：`/search/results/people/?keywords=<company job location recruiter talent acquisition hiring manager HR>`。
  - 命令队列新增 `open_linkedin_contact_search`，`/api/browser/commands/next` 会二次规范化，仅保留 LinkedIn people search URL。
  - `chromium-runtime` 再次校验 URL 只允许 `linkedin.com/search/results/people/`，拒绝 jobs/search、外站和空关键词。
  - `linkedin_page_kind` 新增 `people_search`。
  - `auto_open_linkedin_recruiter_profile_if_needed` 已支持 people search 页：从 visible DOM 中筛选 recruiter / talent / hiring / HR 候选 `/in/...`，打开候选主页供 collector 发出 `linkedin_contact_snapshot`。
  - people search 页即使没有 `/in/...` 主页链接，也会输出 `linkedin_contact_search_results`，记录候选 headline、location、company_hint、contact_kind、是否匿名、是否可打开主页。
  - 当 LinkedIn 结果页有候选但没有可打开 profile href 时，collector 不再静默成功，而是上报 `auto_open_result.status=blocked_no_profile_links`，并保留候选数量。
  - 全流程只读导航，不加人、不私信、不 Apply / Submit。
- 已修复 `chromium-runtime` 重启时可能早于 Chromium CDP ready 的启动竞态：CDP 连接现在会重试，避免一次失败后永久进入 degraded loop，导致浏览器命令队列不消费。
- 已修复 `chromium-runtime` 后台命令循环生命周期问题：`collector_loop` 与 `browser_command_loop` 现在保存 task 引用，并监控后台 task 是否意外停止；线上日志可见 `browser command loop started` 和 `browser command fetched`。
- 因此后续不应要求用户手动打开 HR 主页；真实验收应由应用根据岗位页或 pipeline 发现的 profile URL 自动导航，然后确认产生 `linkedin_contact_snapshot`。

真实线上验收：
- 入参：`company=OpenAI`、`job_title=Recruiter`、`location=Singapore`。
- `/api/browser/search-linkedin-contacts` 返回 `queued`，目标 URL 为 LinkedIn people search。
- `chromium-runtime` 日志显示 `browser command fetched: open_linkedin_contact_search ...`。
- Redis `browser:commands` 队列长度从 `1` 降为 `0`。
- LinkedIn collector 状态：
  - `page_kind=people_search`
  - `event_types=["linkedin_visible_snapshot","linkedin_profile_snapshot","linkedin_contact_search_results"]`
  - `auto_open_result.status=blocked_no_profile_links`
  - `auto_open_result.candidate_count=8`
- 数据库最新 `linkedin_contact_search_results`：
  - `capture_scope=visible_people_search_results`
  - `contact_count=8`
  - 第一条候选为 `Talent Acquisition Manager | Certified Human Resources Professional®`
  - `contact_kind=recruiter`
  - `is_anonymized=true`
  - `can_open_profile=false`
  - `profile_url=""`

结论：
- “按公司 / 岗位主动搜索 recruiter / hiring manager”已能由应用在云端 LinkedIn 自动执行搜索并采样候选。
- 当前真实账号/页面没有暴露候选个人主页 URL，不能继续自动打开主页；系统已正确记录为可解释阻塞，而不是误报成功。

### 3. 加人 / 批量私信 / Apply / Submit 执行路径

状态：已补可验收 dry-run 执行路径并在线上验证；真实点击未执行。

实现：
- `/api/delegated-automation/execute` 在 `request.dry_run=true` 且授权策略通过时返回 `dry_run_ready`。
- dry-run 返回结构化 `execution_plan`，包含 platform、action、target、evidence_ids、steps。
- dry-run 不调用真实 provider，不产生外部副作用，不扣减每日额度。
- 真执行仍保留 provider 路径和授权门禁。

原因：
- 加人、私信、Apply/Submit 属于真实外部副作用。没有你对具体目标、内容、动作的明确最终确认前，不应自动执行。

本地验证：
- `runtime_api/tests/test_delegated_automation.py` 全部通过。

线上验证：
- `/api/delegated-automation/grants` 缺少必填字段时返回 `422`，不再抛 `500`。
- LinkedIn `send_message` grant / manifest 可创建。
- `/api/delegated-automation/execute` 在 `dry_run=true` 时返回 `dry_run_ready`。
- dry-run 输出包含 `execution_plan.steps`：打开目标页、校验目标身份、加载 JD / 简历 / 草稿证据、准备私信点击路径、采集审计证据。
- `budget_after={"used_today": 0, "remaining_today": 3}`，说明 dry-run 未扣减真实每日额度。

### 4. Android noVNC 断线重连

状态：已完成。

实现：
- `WebWorkspaceActivity` 在 noVNC 页面加载后检测 `Disconnected / 连接已断开 / connection closed`。
- 检测到断线时显示 `远程浏览器已断开，点此重连` banner。
- 点击 banner 触发 `webView.reload()`。

本地验证：
- `WebWorkspaceKeyboardTest` 通过。

### 5. Android 主动气泡噪声过滤

状态：已完成。

实现：
- 后端 `filter_open_suggestions` 过滤 `\d+ notifications total`。
- Android shared `AssistantSuggestion.isDisplayableText` 过滤同类噪声。
- WebSocket proactive message 解析时直接丢弃噪声。
- `FloatingBallService.showProactiveBubble` 显示前再兜底检查。

本地验证：
- `test_filter_open_suggestions_suppresses_gmail_notification_count_noise` 通过。
- `RealtimeClientTest` 通过。

## Verification Commands

```bash
python3 -m pytest -q runtime_api/tests/test_job_agent_pipelines.py runtime_api/tests/test_delegated_automation.py runtime_api/tests/test_vector_and_suggestions.py -k 'backend_job_fit or real_backend_resume or dry_run_returns_plan or calls_provider_only_after_allowed_decision or misconfigured_without_fake_success or notification_count_noise or low_value_focus_page_titles'
python3 -m pytest -q chromium_runtime/tests/test_linkedin_parser.py
gradle :app:testDebugUnitTest --tests com.par.assistant.android.WebWorkspaceKeyboardTest --tests com.par.assistant.android.RealtimeClientTest
```

早期结果：
- Runtime API targeted tests: 8 passed.
- Chromium LinkedIn parser tests: 5 passed.
- Android unit tests: build successful.

最新 LinkedIn / browser targeted verification：

```bash
python3 -m pytest -q chromium_runtime/tests/test_runtime_recovery.py chromium_runtime/tests/test_linkedin_parser.py runtime_api/tests/test_browser_login_commands.py runtime_api/tests/test_job_agent_pipelines.py runtime_api/tests/test_core_pipeline_engine.py::test_pipeline_registry_endpoint_exposes_core_pipeline_contract
```

结果：
- 72 passed.

## Deployment Verification

云服务器：
- `http://206.119.171.141/health` 返回 `{"status":"ok"}`。
- `runtime-api` 已重建并启动。
- `chromium-runtime` 已部署本次 LinkedIn parser 更新。

真机：
- 设备 `DQYTCYFMO7VSEAJB` 在线。
- 已安装最新 debug APK，`versionName=0.1.0`。
- Android 真机是入口和展示层；LinkedIn 页面真实采样以云端 Chromium collector 状态为准。

线上 smoke 输出：

```json
{
  "missing_field_status": 422,
  "missing_field": "scenario",
  "dry_run_status": "dry_run_ready",
  "provider": "delegated_dry_run_executor",
  "trace_status": "dry_run_ready",
  "budget_after": {"used_today": 0, "remaining_today": 3},
  "notification_noise_count": 0
}
```

LinkedIn 自动联系人页打开能力本地验证：

```bash
python3 -m pytest -q runtime_api/tests/test_browser_login_commands.py chromium_runtime/tests/test_runtime_recovery.py chromium_runtime/tests/test_linkedin_parser.py
python3 -m pytest -q runtime_api/tests/test_browser_login_commands.py runtime_api/tests/test_job_agent_pipelines.py runtime_api/tests/test_core_pipeline_engine.py::test_pipeline_registry_endpoint_exposes_core_pipeline_contract chromium_runtime/tests/test_runtime_recovery.py chromium_runtime/tests/test_linkedin_parser.py
```

结果：
- Browser command API / Chromium runtime / LinkedIn parser targeted tests: 42 passed.
- Browser command API / Job Agent pipeline / pipeline registry / Chromium runtime / LinkedIn parser targeted tests: 70 passed.
- 最新补充 people search 结构化采样和后台 task 生命周期修复后：72 passed.

线上验证补充：
- `/api/browser/open-linkedin-profile` 对 LinkedIn profile URL 返回 `queued`。
- `chromium-runtime` 消费命令后 Redis `browser:commands` 队列长度为 `0`。
- 使用测试假 URL `https://www.linkedin.com/in/jane-chen-recruiter/` 时，云端浏览器实际跳转到 LinkedIn `404` 页面，证明自动导航链路已执行；但该 URL 不是一个真实 HR 主页，因此不能用于 `linkedin_contact_snapshot` 真实性验收。
- 验证后已将云端 LinkedIn 页面恢复到 jobs search 页面。
- `/api/browser/search-linkedin-contacts` 已完成真实 LinkedIn people search 验收：提供 company / job_title 后，云端浏览器进入 LinkedIn people search；当前账号下结果有 recruiter / talent 候选但不暴露 `/in/...` profile href，因此系统输出 `blocked_no_profile_links` 和 8 条候选采样。

## Remaining Real-World Verification

以下不是代码 gap，而是真实账号/真实副作用验收需要用户配合：

1. 在云端 LinkedIn 已登录状态下，如果某个真实岗位页、公司页、招聘帖或搜索结果暴露 `/in/...` profile URL，应用会自动打开并产生 `linkedin_contact_snapshot`；当前 OpenAI Recruiter people search 页面没有暴露 profile URL，因此真实主页打开仍受 LinkedIn 页面可见数据限制。
2. 如需真实加人、真实私信、真实 Apply / Submit，需要你明确确认目标、内容、动作和每日限额后再执行；默认只做 dry-run。
3. noVNC 重连和气泡过滤已完成代码与线上 API 验证；仍建议在你下一次实际打开远程浏览器并触发断线时做 UI 目视确认。
