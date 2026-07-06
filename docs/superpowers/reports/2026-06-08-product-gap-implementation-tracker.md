# Nomi 产品 Gap 补齐跟踪

日期：2026-06-08

本文件记录当前“产品设想 vs 实际代码”的差距，并跟踪本轮开始补齐的范围。状态定义：

- `未开始`：还没有对应代码。
- `基座`：有 API、策略、Pipeline 或适配器抽象，但还不能构成用户可用闭环。
- `部分完成`：已经有可测试的业务输出，但外部服务、UI 或持久化仍有缺口。
- `完成`：已有端到端代码路径、测试和合理输出。

## 1. 找工作 Agent 完整产品

目标：让 Nomi 能围绕用户求职目标形成闭环：找岗位、读 JD、匹配简历、改简历、生成 Cover Letter/自我介绍、联系招聘方、跟进机会、准备面试、跟踪 Offer。

当前状态：`未开始 -> 部分完成 -> 完成本地产品闭环`

本轮先补：

1. `career_profile_pipeline`：从简历、用户描述、私有事件中形成职业画像。
2. `job_discovery_pipeline`：把用户提供的 JD、ATS/公司招聘页、LinkedIn 可见页面或邮件线索规范化为 job opportunity。
3. `job_fit_scoring_pipeline`：用 JD + 用户简历/职业画像做匹配评分，输出匹配理由、缺口和证据。
4. `resume_tailoring_pipeline`：基于 JD 和简历生成“需要改哪里”的简历修改草案，不编造无证据经历。
5. `cover_letter_pipeline`：基于 JD 和简历生成 Cover Letter / 自我介绍草稿。
6. `outreach_message_pipeline`：生成给 HR、招聘经理或内推人的邮件/LinkedIn/WhatsApp 外联草稿，发送前必须确认。
7. `job_application_pipeline`：准备 Apply/Submit 动作，默认只生成执行计划和确认卡。
8. `application_tracking_pipeline`：维护机会阶段、下一步和跟进提醒。
9. `interview_prep_pipeline`：根据 JD、简历和目标公司生成面试准备材料。

本轮已补到代码：

- 9 条 Job Agent 后端 Pipeline：职业画像、岗位发现、匹配评分、简历修改草案、Cover Letter、外联草稿、申请准备、机会跟踪、面试准备。
- Pipeline 注册表与意图路由：求职、JD 匹配、改简历、Cover Letter、LinkedIn/HR 外联、Apply/Submit、面试准备会进入对应 Career Pipeline。
- Tool Registry：LinkedIn 外联与 Apply/Submit 不再走泛化长尾浏览器任务，而是先进入受控 Career Pipeline。
- Career 本地状态表：`career_profiles`、`job_opportunities`、`resume_versions`、`job_applications`。
- Career writeback：岗位发现/匹配评分可写入 `job_opportunities`，简历修改草案可写入 `resume_versions`，申请意图/阻断状态可写入 `job_applications`。
- Career Board API：`GET /api/career/board` 返回职业画像、岗位机会、简历版本、申请状态，供 Web/Android 求职 Tab 使用。
- Web 完整工作台求职 Tab：新增“求职”一级导航，拉取 `GET /api/career/board?limit=50`，展示职业画像、岗位、匹配度、匹配项/差距、申请阶段、下一步、简历草稿，并可 PATCH 本地申请状态。
- Android 悬浮面板求职一级 Tab：原生浮窗新增 `对话 / 求职 / 设置` 顶层入口，求职 Tab 直接拉取 Career Board API，不再隐藏在设置页按钮里。
- 求职申请状态更新：`PATCH /api/career/applications/{id}` 可更新本地申请状态；Android 看板提供“标记已投递 / 忽略”动作并刷新看板。
- Public ATS 页面规范化：`job_discovery_pipeline` 可消费用户已打开/采集到的 Greenhouse、Lever、Ashby、Workable、SmartRecruiters、LinkedIn 页面文本，生成带 `source_event_ids` 的岗位机会。
- 求职机会详情 API：`GET /api/career/opportunities/{job_id}` 返回岗位、匹配证据、简历草稿、Cover Letter、外联草稿、申请状态历史和面试准备；所有草稿默认未发送。
- Web 求职机会详情页：求职看板岗位卡增加“查看详情”，详情页展示 JD 要求、匹配项/差距、证据、简历草稿、Cover Letter、外联草稿、面试准备和申请状态历史。
- Public ATS 只读预览 API：`POST /api/career/ats/preview` 可读取或消费用户提供的 Greenhouse、Lever、Ashby、Workable、SmartRecruiters 页面文本，返回规范化岗位机会、来源、下一步和 `writeback_performed=false`。
- Web Public ATS 预览入口：求职页新增公开 ATS URL 输入框，展示只读岗位预览，不自动写入看板、不提交申请。
- Public ATS 列表预览 API：`POST /api/career/ats/list-preview` 可把 Greenhouse、Lever、Ashby、Workable、SmartRecruiters 公开公司职位列表转成只读岗位机会；输出来源、board、API URL、下一步和 `writeback_performed=false`。
- Web Public ATS 列表入口：求职页同一个 URL 输入框新增“预览列表”，用户可先看公司职位列表是否解析合理，再决定是否后续写入/跟进。
- 简历文本导入 API：`POST /api/career/profile/ingest` 可把用户粘贴的简历文本和目标岗位/地点转成本地 `career_profiles` 职业画像。
- Web 简历导入入口：求职页新增简历文本输入框，生成并写入本地职业画像，用户可刷新看板查看。
- 简历文件导入 API：`POST /api/career/resumes/import` 支持 docx/pdf/txt/md，解析文本后写入 `career_resumes` 并生成本地职业画像。
- Web 简历文件导入入口：求职页新增简历文件选择和导入按钮，复用目标岗位/地点输入，成功后展示画像和写入状态。
- 简历导出 API：`POST /api/career/resumes/export` 支持本地生成 docx/pdf 二进制 artifact，返回 base64、文件名、MIME、证据 ID。
- Web 简历草稿导出：岗位详情页新增“导出 DOCX / 导出 PDF”，把当前岗位、匹配证据、简历修改草稿、Cover Letter、外联草稿组装成本地下载文件。
- Offer/面试跟踪 API：`GET /api/career/offers` 只读取 `job_applications` 中 `interviewing` 与 `offer` 阶段，返回下一步、渠道、payload 和证据。
- Web Offer/面试跟踪入口：求职看板顶部新增“Offer 跟踪”，集中展示面试和 Offer 阶段机会，避免混在普通岗位列表里。
- 输出合理性测试：覆盖 JD/简历证据、无编造声明、外联草稿确认、Apply/Submit 未授权阻断、Career 表与 writeback、Web 看板文案、Android 顶层求职 Tab。

本轮继续补齐：

- 简历逐段编辑 UI：岗位详情页新增“简历逐段编辑”，用户可在页面内修改分段内容；DOCX/PDF 导出优先使用页面当前编辑后的 sections。
- 多基础简历版本管理 UI：求职页新增基础简历区，展示 `career_resumes` 摘要，支持设为默认和软删除；`GET /api/career/board` 返回简历摘要且不暴露完整 `parsed_text`。
- 真实 Google Docs 写入执行入口：`/api/delegated-automation/execute` 会把 `platform=google_docs` 或 `action=write_document` 的授权动作转发到 `NOMI_GOOGLE_DOCS_PROVIDER_URL`，带 grant/manifest/target/decision/request；未配置时返回 `misconfigured` 并写 trace，不伪造成功。
- ATS / LinkedIn 外部执行入口：`/api/delegated-automation/execute` 会先跑 grant、target manifest、evidence、quota、challenge、pause 策略，只有 `allowed=true` 才调用 `NOMI_BROWSER_EXECUTOR_URL`；缺 grounded evidence 时 provider 不会被调用。
- 端到端线上回归数据集：新增 8 个 offline-safe E2E case 和 7 条合成私有事件，覆盖 Gmail / WhatsApp / Telegram 新消息、自动日程、主动建议、Job Agent pipeline、长尾 Agent、外部执行阻断/授权。

仍需真实环境验证：

- 真实 LinkedIn DOM 加人、私信、Apply/Submit 点击需要部署 `NOMI_BROWSER_EXECUTOR_URL` 对应的 Cloud Playwright/浏览器执行器，并使用用户私有云已登录会话做线上验证。
- 真实 ATS Submit 需要目标 ATS 页面、用户确认和浏览器执行器证据；Nomi core 当前已经能阻断/放行/追踪，但不会自行伪造第三方提交成功。
- 真实 Google Docs 写入需要配置 Google Docs provider URL/token 或 Composio/Google API adapter 并做线上文档写入验证。

## 2. 外部工具真实执行

目标：让 Uber、Amazon/电商、地图、支付、Google Docs/Sheets 写入从“Pipeline 计划”变成可授权真实执行。

当前状态：`基座 -> 部分完成`

已有代码：

- `route_pipeline`
- `ride_pipeline`
- `shopping_pipeline`
- `payment_bill_pipeline`
- `document_file_pipeline`
- Composio session/connect/tool execute。
- Provider call traces、confirmation ledger、pipeline execution results。

本轮已补统一真实执行入口：

- `/api/delegated-automation/execute` 作为高风险外部动作的受控执行入口。
- LinkedIn / ATS / Greenhouse / Lever / Ashby / Workable / SmartRecruiters 类动作默认走 `NOMI_BROWSER_EXECUTOR_URL`。
- Google Docs 写入默认走 `NOMI_GOOGLE_DOCS_PROVIDER_URL`。
- 其他外部执行默认走 `NOMI_EXTERNAL_EXECUTOR_URL`。
- 所有 provider 调用前必须先通过 `evaluate_delegated_action`，所有执行结果都会写入 trace；provider 未配置时返回明确 `misconfigured`。

后续应逐个工具按 TDD 接入：

1. Google Maps readonly route lookup。
2. Gmail/Docs/Sheets draft/write。
3. Uber estimate then confirm booking。
4. Amazon/product compare first，不直接购买。
5. Payment/bill 只做风险展示和确认，不先做真实付款。

## 3. 批量自动化/分级授权

目标：让用户可给 Nomi 授权每日加人、每日私信、Apply/Submit、批量投递等动作，并带额度、目标清单、证据、停止条件和审计。

当前状态：`基座 -> 部分完成`

已有代码：

- `delegated_automation` grant。
- target manifest。
- evaluate policy。
- trace。
- quota / duplicate / challenge / 2FA / pause 规则。

本轮先补：

- Job Agent Pipeline 输出可直接生成 LinkedIn/ATS delegated automation grant/manifest 的建议结构。
- LinkedIn/ATS Apply/Submit 在 Pipeline 层默认 `blocked_until_delegated_grant`，不裸跑。
- Job Application Pipeline 已写入本地申请状态，后续 UI 可以展示“未授权阻断/等待用户授权/等待确认”等阶段。

后续需要：

- Web/Android 授权 UI。
- Cloud Playwright 执行器部署和截图/DOM 证据线上验证。
- LinkedIn/ATS 场景的 target manifest 生成 UI 和审计可视化。

## 4. Nomi 自有 Gmail / WhatsApp / 手机号

目标：Nomi 可以拥有自己的 Gmail、WhatsApp 和手机号，以真实助理身份收消息、发消息、发邮件、发短信、打电话。

当前状态：`基座 -> 部分完成`

已有代码：

- Nomi Gmail / WhatsApp / phone identities。
- Webhook / inbox / outbound draft。
- 电话 V1 单向播放。
- 路由规则禁止绕过草稿确认。

本轮继续补齐：

- 真实 Gmail provider send adapter：`GmailHttpAdapter` 通过 Gmail API `messages/send` 发送确认后的 Nomi 邮件；缺 `ASSISTANT_GMAIL_ADDRESS` / `ASSISTANT_GMAIL_ACCESS_TOKEN` 时返回 `misconfigured`。
- 真实 WhatsApp provider send adapter：`WhatsAppCloudHttpAdapter` 通过 WhatsApp Cloud API 发送确认后的 Nomi WhatsApp 消息；缺 token / phone number id 时不伪成功。
- 真实 SMS/call provider adapter：`HttpAssistantPhoneProvider` 支持 SMS、单向 TTS playback call、turn-based duplex call。
- 双工电话基座：新增 `phone_duplex_call` 草稿确认卡、确认后创建双工通话、`/api/assistant-inbox/phone/calls/duplex/turn` 接收 provider 转写 turn 并返回下一句 TTS reply instruction。
- outbound pipeline 保持确认门槛：Gmail / WhatsApp / SMS / 电话 / 双工电话都必须有 confirmation token 才会调用 provider。
- provider 结果会写回 draft，响应不包含 Authorization header 或 secret。

仍需真实环境验证：

- Gmail / WhatsApp / SMS / 电话 provider 需要真实账号、回调 URL 和 token 才能线上发送/拨打。
- 双工电话当前是 provider-agnostic 的 turn-based voice contract；真实音频媒体流、ASR/TTS provider 回调稳定性、打断/静音/挂断等实时语音细节仍需接入具体电话厂商后验证。

## 5. 长尾 Agent 稳定复杂任务

目标：复杂任务不跑偏、不死循环、能 checkpoint、能回滚/补偿、能最终验收。

当前状态：`基座`

已有代码：

- Planner。
- 结构化 task memory。
- step verifier。
- external effect proposal/confirm/execute/rollback/compensation。
- task events。

本轮不扩展 Long-tail Agent 内核，只让 Job Agent 的不确定动作按规则回到 Pipeline/Delegated Automation，而不是让 Agent 直接发送或提交。

## 6. 长期记忆产品化治理

目标：让用户可视化管理 KV、图谱、RAG 记忆，处理超级节点、关系权重、关系衰减、错误纠正。

当前状态：`部分完成`

已有代码：

- KV + knowledge graph + vector/RAG。
- 作用域隔离。
- governance API。
- memory correction API。
- supernode mitigation 的部分 pipeline 输出。

本轮不补 UI。后续需要：

- 关系图谱可视化。
- 联系人关系热度。
- 关系衰减策略。
- 用户可编辑/撤销/合并实体。
- 超级节点治理指标面板。

## 7. LinkedIn 私有云自动化

目标：用户在私有云浏览器登录 LinkedIn，Nomi 在授权额度内找岗位、加人、私信、投递、跟进。

当前状态：`未开始 -> 部分完成`

本轮先补：

- `linkedin_browser_observation` 作为 Job Discovery 来源之一。
- `outreach_message_pipeline` 输出 LinkedIn draft。
- `job_application_pipeline` 输出 Apply/Submit 确认卡和 delegated automation 所需 manifest/grant 建议。
- 所有 LinkedIn 自动化都要求 target manifest、daily limit、batch limit、evidence ids、challenge stop。
- Tool Registry 已将 LinkedIn 外联/Apply 绑定到 Career Pipeline，避免直接落入长尾浏览器任务。

本轮继续补齐：

- `/api/delegated-automation/execute` 为 LinkedIn DOM、批量私信、Apply/Submit 点击提供统一执行入口和 trace。
- 执行前强制 grant、manifest、evidence、quota、challenge、pause 检查；没有证据或授权时不会调用 provider。
- 缺少 `NOMI_BROWSER_EXECUTOR_URL` 时返回 `misconfigured`，预算不递增，不写“已完成”。

仍需真实环境验证：

- 真实 LinkedIn DOM 执行器本身需要以独立 provider/服务部署到私有云浏览器环境。
- 批量加人、批量私信、Apply/Submit 点击需要在用户已授权额度内做线上小批量验证，并保留截图/DOM 证据。

## 本轮完成标准

1. 新增 Job Agent 后端 Pipeline。
2. 相关 Pipeline 能被 `/api/pipelines/run` 或 `run_core_pipeline` 调用。
3. 每个 Pipeline 输出结构化 slots、风险、证据、下一步和外部动作阻断原因。
4. LinkedIn/ATS 自动化相关 Pipeline 必须输出授权/额度/目标 manifest 要求。
5. 测试不仅验证成功状态，还要验证输出内容合理：
   - JD/简历匹配不能编造。
   - 外联草稿必须引用 JD/简历证据。
   - Apply/Submit 不能绕过授权。
   - LinkedIn 批量动作遇到缺少 manifest 或 evidence 时必须阻断。
