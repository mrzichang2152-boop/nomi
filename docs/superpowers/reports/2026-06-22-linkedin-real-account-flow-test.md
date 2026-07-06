# 2026-06-22 LinkedIn 真实账号流程验收报告

## 环境

- 线上服务：http://206.119.171.141
- 访问密码：par-dev
- 云端浏览器：Chromium + noVNC，使用用户已登录的真实 LinkedIn 会话
- Android 真机：DQYTCYFMO7VSEAJB，型号 beryl / Redmi 系列，ADB 在线
- 外部副作用策略：所有 LinkedIn 发消息、加人、Apply / Submit 均保持 dry-run / confirmation gate，不真实执行

## 本轮修复

1. 补齐 LinkedIn DOM collector：
   - 支持 `linkedin_visible_snapshot`
   - 支持 `linkedin_profile_snapshot`
   - 支持 `linkedin_career_prompt`
   - 支持 `linkedin_job_search_results`
   - 支持搜索页右侧打开 JD 的 `linkedin_job_description_snapshot`

2. 修复 LinkedIn Jobs 搜索结果污染：
   - 之前会把 `AI Product Manager in China`、`3 results`、`Set job alert...`、`Save ...` 等 UI 文案误当成岗位。
   - 现在要求形成合理的 `title + company + location` 三元组，并按 LinkedIn 搜索结果区/详情区分区解析。

3. 修复求职 pipeline 地点丢失：
   - `job_discovery_pipeline` 之前没有优先使用 LinkedIn 结构化 `location` 字段，导致真实岗位地点变成空字符串。
   - 现在 `job_pages` 中已有的 `title/company/location/source/source_event_ids` 会被保留。

## 本地自动化测试

已通过：

```text
python3 -m pytest -q chromium_runtime/tests/test_linkedin_parser.py
4 passed

python3 -m pytest -q chromium_runtime/tests/test_linkedin_parser.py chromium_runtime/tests/test_runtime_recovery.py chromium_runtime/tests/test_gmail_parser.py chromium_runtime/tests/test_telegram_parser.py chromium_runtime/tests/test_runtime_injection.py
36 passed

python3 -m pytest -q runtime_api/tests/test_job_agent_pipelines.py -k 'linkedin_structured_location or job_discovery_pipeline_normalizes_public'
2 passed

python3 -m pytest -q runtime_api/tests/test_job_agent_pipelines.py runtime_api/tests/test_core_pipeline_engine.py -k 'job_'
24 passed
```

验收重点不是只看通过，而是检查输出合理性：

- LinkedIn 搜索结果不再包含 UI 噪声岗位。
- ATS 页面标题仍能保持原有解析，不被 LinkedIn 修复影响。
- LinkedIn 结构化地点、公司、岗位名、证据 ID 不丢失。

## 线上真实 LinkedIn 页面采集

### 1. 登录态

已确认用户登录态存在：

- URL：`https://www.linkedin.com/feed/`
- Title：`Feed | LinkedIn`
- 可见 profile 信息包含：
  - 张子长
  - Program Manager at Beijing Sankuai Technology Ltd.
  - Beijing

结论：通过。

### 2. 真实 Jobs 搜索页

通过已登录云端 Chromium 打开真实 LinkedIn Jobs：

- URL：`https://www.linkedin.com/jobs/search/?currentJobId=...&keywords=AI%20Product%20Manager`
- Title：`(2) AI Product Manager Jobs | LinkedIn`
- 可见页面包含真实岗位：
  - 交易产品经理（跟单交易 & 量化策略） / Confidential / Shenzhen, Guangdong, China (Remote)
  - 交易产品经理（跟单交易 & 量化策略） / Confidential / Shanghai, China (Remote)
  - Product Designer / Venture Product Builder (Work From Home) / Persona / APAC (Remote)
  - Top job picks：NVIDIA、Amazon、Amazon Lab126 相关岗位

结论：页面打开和真实 DOM 读取通过。

### 3. Collector 状态

`/api/collectors/status` 中 LinkedIn collector：

- `health_status`: `healthy`
- `page_kind`: `job_search`
- `event_types`:
  - `linkedin_visible_snapshot`
  - `linkedin_profile_snapshot`
  - `linkedin_job_description_snapshot`
  - `linkedin_job_search_results`

数据库事件计数已包含：

- `linkedin_job_search_results`
- `linkedin_job_description_snapshot`
- `linkedin_profile_snapshot`
- `linkedin_visible_snapshot`

结论：线上 collector 采集通过。

## 线上真实 Pipeline 验收

### P19 / job_discovery_pipeline

输入：线上最新 `linkedin_job_search_results.job_pages`

实际输出：

```text
交易产品经理（跟单交易 & 量化策略） / Confidential / Shenzhen, Guangdong, China (Remote)
Product Designer / Venture Product Builder (Work From Home) / Persona / APAC (Remote)
Senior Customer Program Manager – Server and Networking Products / NVIDIA / Beijing, Beijing, China (On-site)
Program Manager II, Product Program Management / Amazon / Beijing, Beijing, China (On-site)
Sr. Technical Program Manager / Amazon Lab126 / Shenzhen, Guangdong, China (On-site)
```

检查结果：

- 标题合理：通过
- 公司合理：通过
- 地点保留：通过
- 无 `Set job alert`、`3 results`、`Save...` 伪岗位：通过
- `source_event_ids` 保留：通过
- `external_effects` 为空：通过

结论：通过。

### P20 / job_fit_scoring_pipeline

输入：

- 真实 LinkedIn JD：Confidential / 交易产品经理（跟单交易 & 量化策略）
- 当前可用简历数据：仅 LinkedIn profile 摘要和手工构造的 minimal profile，不是完整简历

实际输出：

- `status`: `completed_read_only`
- `fit_score`: `0.08`
- `matched_requirements`: `[]`
- `recommendation`: `先补材料再申请`
- `unsupported_claims`: `[]`

合理性判断：

- 系统没有编造用户有交易、量化、AI 投资产品经验：通过
- 因简历材料不足而给出低匹配/先补材料建议：合理
- 若要验收“高质量匹配评分”，仍需接入用户真实简历或职业画像。

结论：基础防幻觉通过；完整匹配质量待真实简历接入后复验。

### P22 / outreach_message_pipeline

输入：

- 真实 LinkedIn JD
- minimal profile
- 联系人：招聘负责人，channel=linkedin

实际输出：

- `status`: `draft_ready`
- `risk.permission`: `external_message`
- `confirmation_required`: `true`
- `external_effects`: `["send_message"]`
- 草稿内容包含岗位名和公司，没有直接发送。

合理性判断：

- 草稿结合了真实岗位标题和公司：通过
- 未声称不存在的强经历：通过
- 发送前确认卡存在：通过

结论：通过。

### P23 / job_application_pipeline

输入：

- 真实 LinkedIn JD
- minimal profile
- `application_action=submit_application`

实际输出：

- `status`: `blocked_until_delegated_grant`
- `risk.permission`: `external_execution`
- `confirmation_required`: `true`
- `external_effects`: `["submit_application"]`
- `apply_submit_blocked`: `true`
- `suggested_grant.platform`: `linkedin`
- `daily_limit`: `10`
- `requires_target_manifest`: `true`
- `stop_on_challenge`: `true`

合理性判断：

- 未授权不执行真实 Apply / Submit：通过
- 给出 LinkedIn 平台授权建议和目标清单：通过
- 高风险动作被门禁拦住：通过

结论：通过。

## 真机 UI 观察

ADB 截图：`/tmp/nomi-linkedin-flow-current.png`

观察到：

- 真机在线。
- Nomi 悬浮球仍在。
- noVNC 顶部显示 `Disconnected`。
- Nomi 气泡出现旧/噪声提示：“处理邮件待办：这封邮件可能需要处理：0 notifications total”。

判断：

- noVNC 断开是本轮重启 `chromium-runtime` 后手机页面没有自动重连，不代表云端 LinkedIn 登录态失效。
- 主动气泡内容不合理，需要后续过滤导航/通知类 UI 文本，并清理 Android 本地残留提示。

结论：后端 LinkedIn 流程通过；真机远程浏览器视觉入口需要重连体验优化。

## 仍未完全验收的点

1. 完整简历接入后的匹配评分
   - 目前只用 minimal profile 验证了“不编造”和“低材料低评分”。
   - 需要用户上传/连接真实简历后复测。

2. LinkedIn 联系人页/招聘负责人识别
   - 本轮未打开真实 recruiter profile。
   - 外联草稿只用“招聘负责人”占位联系人，未验证联系人图谱关联。

3. LinkedIn 加人/批量私信/Apply 点击的真实 UI 执行
   - 本轮按安全策略停在授权门禁，没有真实点击。
   - 后续若要测，需要用户明确给 delegated automation grant，并设置每日上限、目标清单、验证码停止策略。

4. Android 真机远程浏览器自动重连
   - noVNC 页面在容器重启后显示 disconnected。
   - 需要 Android 端检测断连并提供“重连远程浏览器”按钮或自动刷新。

5. 主动气泡 UI 噪声
   - `0 notifications total` 不应触发“邮件待办”提示。
   - 需要在主动建议入口过滤 collector 可见文本中的通知、导航、状态类 UI 文案。

## 总结

本轮真实 LinkedIn 账号环境下，已完成并通过：

- LinkedIn 登录态确认
- Feed/Profile 可见 DOM 采集
- Jobs 搜索页真实 DOM 采集
- Jobs 搜索结果结构化
- 打开 JD 详情结构化
- `job_discovery_pipeline`
- `job_fit_scoring_pipeline` 的防幻觉基础验证
- `outreach_message_pipeline` 草稿与确认门禁
- `job_application_pipeline` Apply/Submit 授权门禁

未声称通过：

- 真实简历驱动的高质量匹配
- 真实联系人识别
- 真实加人/私信/Apply UI 执行
- Android noVNC 自动重连体验
- 主动气泡 UI 噪声治理
