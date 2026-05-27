# PRD Implementation Gaps

更新日期：2026-05-26

本文档用于对照 `prd.md` 标注当前项目中**尚未实现**和**实现不完整**的需求。口径按 PRD 验收，而不是“代码能跑通”验收。

## 当前结论

项目已经具备 MVP 闭环：私有云部署、Chromium/noVNC、事件采集、队列、语义处理、长期记忆、检索、基础聊天和基础主动建议。

但它还不是 PRD 完整版。当前更准确的状态是：

```text
可运行的 Personal AI Runtime MVP
+ 长期记忆验证版
+ Gmail/WhatsApp 初步采集
- PRD 级完整采集与主动助理
```

## 尚未实现

### P0 - 第一版闭环缺口

- [x] Calendar Collector
  - PRD 要求采集 Google Calendar / 日程信息。
  - 已完成：新增 Google Calendar Web 可见日程 parser。
  - 已完成：Chromium runtime 会识别 `calendar.google.com` 页面，采集可见日程并写入 `calendar_event`。
  - 已完成：日程事件包含 `date_context`、`start_time`、`end_time`、`title`、`capture_scope`、`url`、页面标题。
  - 验证结果：新增测试先红后绿；`chromium_runtime` 5 条测试通过。
  - 内容检查：样例输出能正确解析 `2026年5月26日星期二 09:30-10:00 和 Alex 开产品评审会`、`11:00-12:00 云服务器续费提醒`，结构适合后续语义处理。
  - 遗留问题：当前只采集可见日程，不能滚动同步整月/历史，也没有 Google Calendar API 级别的 event id、地点、参与人、提醒时间。

- [x] 采集源开关与会话暂停
  - PRD 要求用户可以按来源关闭采集，也可以临时暂停会话采集。
  - 已完成：新增 `collector_settings` 表、`/api/collectors/settings` 读接口、`/api/collectors/settings/{source}` 更新接口。
  - 已完成：`/event` 会拒绝 disabled 或 paused 的来源，避免暂停后继续入库。
  - 已完成：Chromium runtime 会读取采集设置，并跳过被关闭或暂停的 collector。
  - 已完成：前端增加“采集控制”面板，可以开启/暂停来源。
  - 验证结果：新增测试先红后绿；`runtime_api` 24 条、`chromium_runtime` 3 条、`worker` 9 条测试通过。
  - 内容检查：暂停 Gmail 后，事件写入返回 409，错误体包含 `source=gmail`、`enabled=false`、`reason=manual pause during login`，输出语义合理。
  - 遗留问题：当前前端只有开启/暂停，没有“暂停到某个时间”的时间选择器；API 已支持 `paused_until`。

- [x] 自动每日记忆整理任务
  - PRD 要求每日自动整理长期记忆。
  - 已完成：`runtime-api` 启动后会创建每日维护循环，默认 UTC 19:00 执行，整理前一天记忆。
  - 已完成：新增 `/api/maintenance/daily`，支持手动触发指定日期的 consolidation + raw cleanup。
  - 已完成：新增 `scripts/daily-memory-maintenance.sh`，可用于服务器 cron 或手动运维。
  - 验证结果：新增测试先红后绿；`runtime_api` 27 条测试通过。
  - 内容检查：维护输出包含 `date`、`consolidation.summary`、`fact_count`、`raw_cleanup.low_value_pruned`、`raw_cleanup.expired_pruned`，样例 summary 为 `User: paid cloud server invoice by Alipay`，语义可读。
  - 遗留问题：每日维护循环目前在 `runtime-api` 进程内执行，适合单用户部署；如果未来多副本部署，需要改为带锁的独立 scheduler。

- [x] 原始事件生命周期清理
  - PRD 要求原始事件保留 7-30 天，低价值数据应被压缩或清理。
  - 已完成：低价值事件默认 7 天后压缩 raw payload。
  - 已完成：所有过期 raw payload 默认 30 天后压缩。
  - 实现口径：不直接删除事件行，而是把 `raw_data` 替换为 `pruned=true`、来源、事件类型、清理原因和语义摘要，避免破坏 timeline、facts、vector 引用。
  - 验证结果：测试确认旧 raw payload 被替换为只含 semantic summary 的结构，不保留原始私密 payload。
  - 遗留问题：当前价值判断依赖 `semantic_events.importance < 0.35`，后续需要结合来源、用户反馈和任务上下文动态调整。

- [x] 完整脱敏系统
  - PRD 要求请求模型前做可靠脱敏。
  - 已完成：模型请求前脱敏已增强，覆盖邮箱、手机号、URL 参数、OAuth fragment、验证码、订单号、金额、中文收货地址、身份证、护照、银行卡、Bearer token、token、cookie、session、password/auth/code 类字段。
  - 已完成：`/event` 使用双轨存储：`events.raw_data_private` 本地加密保存完整原文；`events.raw_data` 和 `events:raw` Redis Stream 只保存/投递脱敏版本，避免明文验证码、身份证、银行卡、OAuth token 等进入模型链路。
  - 已完成：新增授权读取接口 `/api/events/{event_id}/private-raw`，必须带应用密码才能解密读取本地原文。
  - 已完成：脱敏后仍保留任务语义，例如“安全提醒”“支付宝付款”“订单号”“身份证”“护照”“银行卡”“收货地址”等关键词不会被抹掉。
  - 验证结果：新增测试先红后绿；目标测试从失败转为通过；全量本地测试为 `runtime_api` 36 条、`worker` 25 条通过；`runtime_api/app/main.py` 和 `worker/app/worker.py` 语法检查通过。
  - 内容检查：样例脱敏输出为 `安全提醒：验证码 CODE_1`、`身份证 ID_CARD_1，护照 PASSPORT_1，银行卡 BANK_CARD_1，订单号 ORDER_1 已通过支付宝付款 AMOUNT_1，收货地址 ADDRESS_1`，OAuth URL 和 authorization 字段被替换为 `REDACTED`，敏感值消失且语义仍可读。
  - 内容检查：加密原文字段的 ciphertext 中不包含 `839201`、`110105199001011234` 等明文敏感值；授权解密后可以恢复完整原始 payload。
  - 遗留问题：这仍是规则型 PII 保护，不是机器学习/专用 DLP 分类器；附件内容、图片 OCR、复杂重定向链路、非中英文证件格式仍需后续专项处理。

### P1 - 核心能力缺口

- [x] Telegram Collector
  - PRD 架构中包含 Telegram Web。
  - 已完成：Chromium runtime 识别 `web.telegram.org` 页面并采集可见聊天预览。
  - 已完成：采集内容包含 `chat_name`、`timestamp_label`、`message`、`capture_scope`、`url`、页面标题，并写入 `telegram_message_preview`。
  - 已完成：`telegram` 已加入 collector settings，可被前端采集控制开启/暂停。
  - 验证结果：新增测试先红后绿；`chromium_runtime` 9 条测试通过。
  - 内容检查：样例输出能解析 `Alice 09:42 Can we move the meeting to Friday?` 和 `PAR Dev Group Yesterday Bob: vector search test passed`，结构适合语义处理。
  - 遗留问题：当前只采集可见聊天预览，没有打开会话读取完整历史，也没有新消息 MutationObserver。

- [x] Bookmark Collector
  - PRD 后续个人搜索需要整合用户收藏/书签。
  - 已完成：Chromium runtime 读取 Chromium profile 的 `Bookmarks` JSON。
  - 已完成：解析书签标题、URL、文件夹路径、添加时间，并写入 `bookmark_item` 事件。
  - 已完成：`bookmark` 已加入 collector settings，可被前端采集控制开启/暂停。
  - 验证结果：新增测试先红后绿；`chromium_runtime` 7 条测试通过。
  - 内容检查：样例输出为 `title=Qwen docs`、`url=https://example.com/qwen`、`folder_path=书签栏 / AI`，结构清晰可用于个人搜索。
  - 遗留问题：当前是定时读取书签文件，不是监听书签文件变化；还没有把书签内容抓取为页面摘要。

- [x] 独立 Model Router
  - PRD Docker 架构中包含 `model-router`，并预期统一处理模型路由。
  - 已完成：新增独立 `model_router` 服务，提供 `/health` 和 `/model/route`。
  - 已完成：`semantic_extraction`、`daily_consolidation` 等 LLM 任务会路由到 OpenAI-compatible 外部模型接口；`embedding` 返回本地 embedding 路由说明，不触发聊天模型调用。
  - 已完成：worker 通过 `MODEL_ROUTER_URL=http://model-router:8090` 调用 router，不再直接把语义抽取请求发到外部模型地址。
  - 已完成：`docker-compose.yml` 增加 `model-router` 服务、healthcheck 和 worker 依赖。
  - 验证结果：新增测试先红后绿；`model_router` 2 条测试、worker router 接入测试通过；全量本地测试 `87 passed`；`docker compose config` 能解析出 `model-router`、`MODEL_ROUTER_URL` 和 8090 healthcheck。
  - 内容检查：样例 router 请求 `task=semantic_extraction` 会转发到 `http://model.local:9161/v1/chat/completions`，返回 `route=external_llm`、`model=qwen3.6`、`content`；`task=embedding` 返回 `route=local_embedding` 且不会调用聊天后端。
  - 遗留问题：当前 router 是轻量策略层，还没有重试队列、熔断、调用成本统计、按任务动态选择多个供应商、模型质量反馈学习。

- [ ] HTTPS / TLS 部署
  - 当前公网入口是 HTTP 80。
  - 443 端口只是预留，没有证书、TLS 终止、自动续签配置。

### P2 - 产品形态缺口

- [x] 完整记忆治理页面
  - 当前能查看和删除部分记忆。
  - 已完成：新增 `/api/memory/governance`，支持按来源、敏感状态和关键词筛选事件、长期记忆和状态记忆。
  - 已完成：治理结果会显式返回 `sensitive`、`sensitive_reasons`、summary、intent、importance 等审计字段。
  - 已完成：新增 `/api/memory/semantic/{memory_id}` 纠错接口，可把长期记忆改为用户确认的 summary，并写入 `memory_audit_log`。
  - 已完成：治理页面可以读取本地加密原文、纠正长期记忆、删除长期记忆，并和采集控制页联动支持临时暂停采集。
  - 已完成：事件入库时会为受保护 raw payload 增加 `sensitive` 和 `sensitive_reasons`，避免治理页 `sensitive=true` 筛选失效。
  - 验证结果：新增测试先红后绿；目标治理测试通过；全量本地测试 `97 passed`；2026-05-26 云服务器回归确认敏感事件可筛选、验证码只显示为 `CODE_1`、授权接口仍可恢复本地完整原文。
  - 内容检查：样例 `source=gmail&sensitive=true&q=安全` 只返回 Gmail 敏感事件，包含 `sensitive_reasons=["verification_code"]` 和 `summary=处理安全提醒`；纠错接口会执行 `UPDATE semantic_memory` 并写 `memory_audit_log`。
  - 遗留问题：审计日志目前只记录纠错动作，删除/批量操作的完整审计还可以继续扩展；治理页面使用浏览器 prompt 做轻量纠错输入，还不是复杂表单编辑器。

## 实现不完整

### Managed Chromium Runtime

- [x] JS Runtime Injection 不完整
  - PRD 要求 Playwright + Page Injection，并包含 DOM injection、websocket hook、network hook。
  - 已完成：新增统一 runtime injection 计划，所有受管页面都会安装 network hook 和 focus hook；WhatsApp 额外安装 DOM MutationObserver。
  - 已完成：network hook 覆盖 `fetch`、`XMLHttpRequest`、`WebSocket open/close`，写入页面内 `__parRuntimeQueues.network`。
  - 已完成：collector loop 每轮统一注入 hooks 并 drain network queue，标准化为 `browser_network_event`。
  - 已完成：网络事件只保留 `kind`、`method`、去 query/fragment 的 `url`、`status`、`direction`、`page_url`、`title`、`captured_at`，避免把 token/code/auth 等 URL 参数推进事件链路。
  - 验证结果：新增测试先红后绿；`chromium_runtime` 29 条测试通过；全量本地测试后续验证。
  - 内容检查：WhatsApp 注入计划为 `network + focus + whatsapp_dom`；Gmail 注入计划为 `network + focus`；样例 `https://example.com/api?token=abc&code=123` 被标准化为 `https://example.com/api`。
  - 遗留问题：当前 WebSocket 只记录连接 open/close 元数据，不读取消息 payload；这避免采集协议层私密内容，但也意味着还不是完整协议级同步。

- [x] 页面断线恢复不完整
  - 当前 Gmail 有基础自动打开逻辑。
  - 已完成：新增统一 managed page 恢复策略，覆盖 Gmail、WhatsApp、Google Search、Calendar、Telegram。
  - 已完成：每轮 collector loop 会读取采集设置，只为 enabled 且未 paused 的来源保活页面。
  - 已完成：缺失页面会自动新建并跳转到对应入口，例如 `https://web.whatsapp.com/`、`https://calendar.google.com/calendar/u/0/r`、`https://web.telegram.org/`、`https://www.google.com/`。
  - 已完成：恢复动作会写入 collector health，成功时标记 `recovery=page_reopened`，失败时标记 `recovery=page_reopen_failed`。
  - 已完成：新增 `CHROMIUM_AUTO_OPEN_SOURCES` 配置，默认 `gmail,whatsapp,calendar,telegram,search`，可在 `.env` 调整。
  - 验证结果：新增测试先红后绿；`chromium_runtime` 26 条测试通过。
  - 内容检查：样例设置中 Calendar disabled、Telegram paused 时，恢复目标只包含 Gmail、WhatsApp、Search；已打开 Gmail 后，只会把 WhatsApp 识别为缺失恢复目标，不会重复打开 Gmail。
  - 遗留问题：当前是页面级恢复，不是账号登录状态自动修复；如果站点要求重新扫码/二次验证，系统只会上报降级状态，仍需用户手动登录。

- [x] 页面结构变化降级不完整
  - 当前有基础健康状态。
  - 已完成：新增统一 `build_degraded_details`，页面解析失败时输出 `failure_reason`、`line_count`、`matched_count`、`quality_score`、`selector_hints`、`dom_sample`、`url`、`title`。
  - 已完成：Gmail、Calendar、Telegram、WhatsApp 的“可见文本太少”或“文本可读但 parser 未匹配”路径都改为上报结构化诊断信息。
  - 已完成：DOM 样本会过滤常见 UI 噪声，例如 Gmail 的 `收件箱`、`Gmail` 等固定导航文本，保留更可能帮助定位页面改版的内容。
  - 验证结果：新增测试先红后绿；`chromium_runtime` 24 条测试通过；全量本地测试后续验证。
  - 内容检查：Gmail 样例输出包含 `failure_reason=no_inbox_preview_match`、`quality_score=0.3`、`selector_hints=["div[role='main']", "tr[role='row']", "div[role='listitem']", "span[email]"]`，`dom_sample` 保留 `页面结构疑似变化`、`新的不可识别按钮`，同时过滤掉 `收件箱` 等 UI 噪声。
  - 遗留问题：还没有把失败 DOM 快照持久化为独立诊断事件，也没有采集质量趋势图；目前诊断信息存在 collector health details 中。

### Gmail Collector

- [x] 只采集收件箱预览
  - 当前能采集发件人、主题、摘要、时间标签。
  - 已完成：在用户当前打开某封 Gmail 邮件时，collector 会读取可见线程正文并写入 `gmail_thread_snapshot`。
  - 已完成：打开邮件事件包含 `subject`、`sender`、`timestamp_label`、`body`、`capture_scope=open_thread_visible_body`、`url`、页面标题。
  - 验证结果：新增测试先红后绿；`chromium_runtime` 11 条测试通过。
  - 内容检查：样例输出能解析 `安全提醒`、`Google <no-reply@accounts.google.com>`、`13:21 (3小时前)` 和正文三行，且没有混入“回复/转发”等 UI 行。
  - 遗留问题：为了避免主动点击导致邮件变为已读，目前不会自动打开收件箱里的每封邮件；只采集用户已经打开的邮件正文。

- [x] 没有附件和标签解析
  - 当前没有附件元信息、重要/星标/分类/标签、线程 ID、邮件 ID。
  - 已完成：当前打开邮件线程可解析可见附件文件名，例如 `requirements.pdf`、`meeting-notes.docx`。
  - 已完成：当前打开邮件线程可解析可见标签文本，例如 `工作`、`项目`。
  - 验证结果：新增测试先红后绿；`chromium_runtime` 12 条测试通过。
  - 内容检查：样例输出包含 `attachments=["requirements.pdf","meeting-notes.docx"]`、`labels=["工作","项目"]`，附件/标签没有混入正文。
  - 遗留问题：当前不下载附件，也不解析 Gmail 内部 thread id、message id、星标、重要标记和分类 tab；只能读取页面上可见的附件名和标签。

- [x] 没有验证码和敏感邮件保护策略
  - Gmail 中可能出现验证码、重置链接、支付信息。
  - 已完成：Gmail 打开线程事件写入前会执行采集端敏感保护。
  - 已完成：识别并替换验证码、重置/验证链接、token/code/auth 类链接、订单号、金额等敏感值。
  - 已完成：事件会标注 `sensitive=true` 和 `sensitive_reasons`，便于后续治理和前端提示。
  - 验证结果：新增测试先红后绿；Gmail parser 7 条测试通过。
  - 内容检查：样例正文从 `您的验证码是 839201...token=abc123secret...订单号 498397 金额 199.00 元` 变成 `您的验证码是 CODE_1，请点击 URL_REDACTED 完成验证。订单号 ORDER_1 金额 AMOUNT_1。`，敏感值消失且语义保留。
  - 遗留问题：这仍是规则保护，不是完整 PII 分类器；附件内容、图片 OCR、复杂重定向链接暂未处理。

### WhatsApp Collector

- [x] 只读取当前可见内容
  - 当前能读取 WhatsApp Web 当前页面的可见文本。
  - 已完成：新增受控历史同步脚本 `build_whatsapp_history_sync_script`，在当前打开会话中向上滚动一屏并采集可见历史消息。
  - 已完成：新增 `normalize_whatsapp_history_records`，对历史消息去重，保留 `chat_name`、`source_kind`、`participants`、`sender`、`timestamp_label`、`message`，并标记 `capture_scope=history_scroll_sync`。
  - 已完成：`collect_whatsapp` 在识别到打开聊天时，会在 MutationObserver 新消息之外同步当前会话的一批历史消息。
  - 已完成：新增 `WHATSAPP_HISTORY_SYNC` 配置，默认开启，可在 `.env` 关闭。
  - 验证结果：新增测试先红后绿；WhatsApp 历史同步目标测试通过；全量本地测试 `97 passed`。
  - 内容检查：重复的 `陈子扬 / 09:42 / 历史消息一` 只保留一条；群聊上下文会保留 `chat_name=PAR Dev Group`，历史消息标记为 `history_scroll_sync`。
  - 遗留问题：这是当前打开会话的渐进式滚动同步，不会自动遍历所有联系人，也不会突破 WhatsApp Web 的懒加载/风控限制；完整历史仍依赖用户打开对应会话并让页面逐步加载。

- [x] 没有按联系人/群组结构化
  - 当前没有完整会话 ID、联系人 ID、群成员、消息方向、消息时间、消息状态等结构。
  - 已完成：打开聊天页时会提取 `chat_name`、`source_kind` 和可见 `participants`。
  - 已完成：MutationObserver 新消息会带上 `chat_name`、`source_kind`、`participants`、`message_direction`、`timestamp_label`。
  - 已完成：chat list preview 和 open chat snapshot 也会附带可用的上下文字段。
  - 验证结果：新增测试先红后绿；`chromium_runtime` 17 条测试通过。
  - 内容检查：群组样例输出包含 `chat_name=PAR Dev Group`、`source_kind=group`、`participants=["Alice","Bob","Chen"]`，消息被标注为 `message_direction=incoming`。
  - 遗留问题：仍没有 WhatsApp 内部 conversation id、message id、已读状态、撤回状态；`message_direction` 目前只能可靠标注 observer 新增消息为 incoming，无法稳定判断自己发出的历史消息。

- [x] 没有 MutationObserver 新消息监听
  - 当前不是实时消息流采集。
  - 已完成：WhatsApp Web 页面注入 MutationObserver，新增 DOM 节点会进入 `window.__parWhatsAppNewMessages` 队列。
  - 已完成：collector 每轮会 drain observer 队列，标准化为 `sender`、`timestamp_label`、`message`、`captured_at`、`capture_scope=mutation_observer` 并写入 `whatsapp_message`。
  - 验证结果：新增测试先红后绿；`chromium_runtime` 15 条测试通过。
  - 内容检查：样例 observer 记录 `陈子扬 / 09:42 / 测试新消息` 被标准化为结构化消息，后台同步提示被过滤。
  - 遗留问题：这是 DOM 新增监听，不是 WhatsApp 协议层或 websocket hook；页面改版时仍可能需要调整标准化规则。

### Google Search Collector

- [x] 搜索采集较浅
  - 当前能根据页面 URL 或可见信息采集搜索事件。
  - 已完成：Google Search collector 会采集可见搜索结果列表，包含 `title`、`url`、`snippet`、`rank`。
  - 已完成：runtime 记录每个页面最近一次 Google 搜索 URL，用户从搜索页跳转到非 Google URL 时写入 `search_result_click`。
  - 验证结果：新增测试先红后绿；`chromium_runtime` 20 条测试通过。
  - 内容检查：样例输出包含搜索结果 `Qwen3 Documentation / https://example.com/qwen3 / rank=1`，点击事件包含 `from_search_url`、`clicked_url`、`clicked_title`，结构可用于搜索意图演化。
  - 遗留问题：点击检测基于页面 URL 变化，不是浏览器级 navigation event；还没有完整返回行为、结果页停留时间和多轮 query reformulation 图谱。

### Focus Collector

- [x] 行为信号较粗
  - 当前主要基于页面停留时间。
  - 已完成：Focus collector 注入页面交互 observer，统计 `scroll`、`click`、`input`、`copy`。
  - 已完成：`deep_focus` 事件新增 `signals` 和 `focus_score`。
  - 验证结果：新增测试先红后绿；`chromium_runtime` 23 条测试通过。
  - 内容检查：180 秒活跃页面样例分数为 `0.74`，同样时长空闲页面为 `0.33`，能区分真实关注和纯停留。
  - 遗留问题：仍未结合浏览器前后台可见性、鼠标轨迹、页面内容变化和跨页面任务链。

### Memory System

- [x] KV State Memory 还不成熟
  - 当前有状态表和部分 profile 聚合。
  - 已完成：新增状态分类 `identity`、`preference`、`project`、`goal`、`profile`、`state`。
  - 已完成：稳定 key 规则，例如 `profile:user:preference`、`profile:user:identity`、`project:par`、`goal:user`。
  - 已完成：state payload 增加 `state_category`、`current_value`，并在 upsert 合并时保留这些字段。
  - 验证结果：新增测试先红后绿；`worker` 21 条测试通过。
  - 内容检查：偏好样例进入 `profile:user:preference`，payload 包含 `current_value=quiet hotels` 和原始事实摘要 `用户偏好安静的酒店。`。
  - 遗留问题：还没有冲突状态解决策略，例如“喜欢安静酒店”和“喜欢热闹酒店”同时出现时的版本/时间衰减。

- [x] Entity Graph 抽取较浅
  - 当前有实体和关系表，也有超级节点 degree filter。
  - 已完成：支持 structured fact 的 `subject`、`predicate`、`object` 优先入口，避免所有事实都落到 source/summary。
  - 已完成：新增 alias/canonical 合并入口，例如 `Chen Ziyang` 可合并到 `陈子扬`，原名写入 aliases。
  - 已完成：relationships 增加 metadata，记录 `confidence`、`source_event_id`、`summary`、`valid_from`，方便解释关系来源。
  - 已完成：worker 会自动执行 `ALTER TABLE relationships ADD COLUMN IF NOT EXISTS metadata`，兼容已有服务器表。
  - 验证结果：新增测试先红后绿；`worker` 21 条测试通过。
  - 内容检查：alias 样例输出 canonical=`陈子扬`、alias=`chen ziyang`；关系 metadata 包含来源事件和摘要。
  - 遗留问题：实体消歧仍依赖模型提供 aliases，不是自动模糊匹配；关系过期、冲突解决仍未完成。

- [x] Semantic Memory 来源不完全符合 PRD
  - PRD 更倾向于从整理后的稳定记忆形成 semantic memory。
  - 已完成：worker 不再把单个高价值事件直接写入稳定 `semantic_memory`。
  - 已完成：事件级语义仍保存在 `semantic_events`，作为事实、图谱、向量和整理任务的输入。
  - 已完成：`consolidate_day` 会把每日整理结果写入 `semantic_memory`，`memory_type=daily_consolidation`，content 标注 `source=consolidated_daily`。
  - 验证结果：新增测试先红后绿；`runtime_api` 34 条、`worker` 24 条测试通过。
  - 内容检查：稳定语义记忆样例包含 `date`、`summary`、`fact_count`、`source=consolidated_daily`，来源从事件流转为整理产物。
  - 遗留问题：目前只做 daily consolidation；周/月级长期稳定记忆还没有单独层级。

- [x] Vector Memory 覆盖不完整
  - 当前主要对语义事件摘要建向量。
  - 已完成：向量内容不再只取 summary，会按来源拼接更完整的文本。
  - 已完成：Gmail thread 向量包含 subject、sender、body、attachments、labels。
  - 已完成：WhatsApp/Telegram 向量包含 chat_name、sender、message。
  - 已完成：Bookmark 向量包含 title、url、folder_path；Search 向量包含 query 和结果 title/url/snippet。
  - 已完成：向量 metadata 增加 `memory_scope`，记录 `conversation_label`、`speaker`、`related_entities`、`sensitivity`、可用/禁用输出场景。
  - 验证结果：新增测试先红后绿；`worker` 21 条测试通过。
  - 内容检查：邮件样例向量文本包含 `项目资料邮件。/ 项目资料 / Alice / 这里是完整正文，请查看附件。/ requirements.pdf / 工作`。
  - 遗留问题：附件内容本身、网页正文抓取、文件内容向量化还没有做；目前只覆盖可见/已采集元数据和正文。

- [x] Timeline Memory 整理较粗
  - 当前有 timeline 和手动 consolidation。
  - 已完成：每日摘要从事实串联升级为结构化 digest，包含 `今日重点`、`待跟进`、`稳定记忆`。
  - 已完成：consolidation 同时写 timeline、daily_summary state 和 stable semantic memory。
  - 验证结果：新增测试先红后绿；`runtime_api` 34 条测试通过。
  - 内容检查：样例输出为 `今日重点：...`、`待跟进：calendar...gmail...`、`稳定记忆：user: preference quiet hotels`，比原始串联更适合用户阅读和后续检索。
  - 遗留问题：摘要仍是规则生成，不是 LLM 高质量日报；还没有周报、月报和主题聚合。

- [x] Importance Scoring 较粗
  - PRD 预期综合 focus_time、repeat_frequency、user_action、relationship_weight。
  - 已完成：新增 `compute_importance`，综合 source/event_type、focus_score、input/copy 等用户动作、relationship_weight、repeat_frequency。
  - 已完成：`deep_focus` 事件会被识别为 `focused_attention`，importance 使用 focus_score 与交互信号计算。
  - 验证结果：新增测试先红后绿；`worker` 23 条测试通过。
  - 内容检查：高关注样例 importance 为 `0.81`，低关注样例为 `0.27`；`Research` 页面 deep focus 被抽取为 `focused_attention`，importance=`0.709`。
  - 遗留问题：权重仍是工程启发式，不是基于用户反馈学习出来的个性化权重。

### Retrieval / Reasoning

- [x] 问题路由还不够智能
  - 当前已经有 working memory、KV、timeline、semantic、graph、BM25、vector 多层检索。
  - 已完成：新增 `explain_retrieval_plan`，输出优先层、路由原因和每层 limit。
  - 已完成：`/search` 返回 `retrieval_plan`，`/api/chat` sources 增加每条来源的 explanation。
  - 验证结果：新增测试先红后绿；`runtime_api` 34 条测试通过。
  - 内容检查：问题 `Alex 和我是什么关系？` 输出 `priority_layers=["entity_graph"]`，原因是“问题包含关系/人物线索，优先使用知识图谱。”，limit 中 graph 高于基础层。
  - 遗留问题：planner 仍是可解释规则，不是学习型路由器；还没有基于用户反馈或答案质量自动调整权重。

- [x] `/search` 不等于完整 Personal Search
  - `/api/chat` 的检索链更完整。
  - 已完成：`/search` 改为复用 `retrieve_context` 分层检索，覆盖 working memory、timeline、semantic memory、entity graph、BM25、vector recall。
  - 已完成：返回 `layers`、`confidence` 和每条 source 的 `explanation`，便于解释为什么命中。
  - 验证结果：新增测试先红后绿；`runtime_api` 28 条测试通过。
  - 内容检查：样例查询 `东京酒店` 返回 `vector_recall` 与 `entity_graph` 两层证据，并解释为“向量召回：语义相近的历史内容”“知识图谱：实体、关系或事实匹配”。
  - 遗留问题：还没有前端专门的 Personal Search 结果页；目前只是 API 响应升级。

- [x] 联系人/会话边界召回缺失
  - 风险：和 A 对话或起草回复时，全局 RAG 可能召回 B 私下评价 A 的内容，造成第三方隐私泄露和社交尴尬。
  - 已完成：新增 `infer_memory_access_policy`，能把“帮我回复 Alice”识别为 `reply_to_contact`，并抽取目标联系人。
  - 已完成：新增 `filter_context_by_memory_access_policy`，在回复联系人时过滤第三方私密负面评价、非目标会话中提到目标联系人的内容。
  - 已完成：worker 写入 facts、relationships、memory_vectors 时附带 `memory_scope`，保留来源会话、说话人、相关实体、敏感级别和禁用场景。
  - 已完成：`/api/chat` 系统提示新增防泄露要求，回复/邮件草稿不得带入第三方私下评价、抱怨、负面观点或敏感信息。
  - 验证结果：新增测试先红后绿；`runtime_api` 45 条测试通过，`worker` 30 条测试通过。
  - 内容检查：样例“帮我回复 Alice”会过滤 `Bob 私下吐槽 Alice 不靠谱`，保留 Alice 当前会话里的“周五八点可以吃饭”；样例“帮我分析 Alice 和 Bob 的关系”允许进入私下分析场景。
  - 遗留问题：目标联系人识别仍主要依赖规则和显式上下文；历史老数据没有 `memory_scope` 时只能从 raw_data 做降级推断。后续应让前端/collector 传入当前 conversation_id 和 target_contact，并对既有向量做一次 scope 回填。

### Suggestion Engine

- [x] 主动建议类型不完整
  - 当前有基础事件驱动建议。
  - 已完成：新增 `email_todo`，用于 Gmail 待处理邮件、付款提醒、验证/任务类邮件。
  - 已完成：新增 `calendar_reminder`，用于 Calendar 日程跟进。
  - 已完成：新增 `research_followup`，用于搜索/研究后的资料整理、比较选项、下一步建议。
  - 已完成：新增 `social_followup`，用于社交安排跟进。
  - 验证结果：新增测试先红后绿；`worker` 13 条测试通过。
  - 内容检查：邮件样例输出 `处理邮件待办：这封邮件可能需要处理：新订单需要尽快完成付款。`；日程样例输出 `跟进日程安排：今天 09:30 有产品评审会。`；搜索样例输出无重复标点，语义可读。
  - 遗留问题：购物比价、出行规划、跨平台复杂建议还只是入口级支持，没有完整规划链路。

- [x] 缺少建议质量控制
  - 当前没有建议置信度校准、重复抑制、用户反馈学习、建议过期策略。
  - 已完成：建议 metadata 增加 `suggestion_type`、`confidence`、`dedupe_key`、`expires_at`。
  - 已完成：`/api/suggestions` 返回前会过滤过期建议，并按 `dedupe_key` 抑制重复建议。
  - 验证结果：新增测试先红后绿；`runtime_api` 29 条测试通过。
  - 内容检查：重复的 `email_todo:gmail:*` 只保留优先级更高的一条，过期建议不会返回给前端。
  - 遗留问题：还没有用户反馈学习；`confidence` 目前主要来自事件 importance，不是模型校准分。

### Frontend / User Interaction

- [x] 前端只是基础交互页
  - 当前可以发消息、看部分记忆/建议。
  - 已完成：前端从抽屉式基础页面升级为多标签工作台，包含对话、个人搜索、记忆治理、主动建议、采集状态五个视图。
  - 已完成：个人搜索页调用 `/search`，展示检索计划、来源层和命中解释。
  - 已完成：记忆治理页支持关键词/来源/敏感状态筛选、读取本地加密原文、纠正长期记忆、删除长期记忆。
  - 已完成：建议页支持完成/忽略建议；采集页支持开启/暂停和暂停 1 小时。
  - 验证结果：前端 JS 语法检查通过；静态文件内容检查确认 `chatView/searchView/governanceView/suggestionsView/collectorsView` 与治理接口调用均存在；全量本地测试 `97 passed`。
  - 内容检查：工作台导航直接进入实际功能页，不再依赖右侧抽屉；治理页会调用 `/api/memory/governance` 和 `/api/events/{event_id}/private-raw`。
  - 遗留问题：未做浏览器截图级视觉回归；当前是功能型工作台，后续还可以增加趋势图、账号身份卡片和更细的建议工作流。

- [x] 缺少记忆解释能力
  - 用户问“你为什么这么建议”时，系统还不能稳定展示完整证据链。
  - 已完成：后端 `decorate_context_sources` 给聊天 sources 增加来源解释。
  - 已完成：前端聊天消息会展开最多 6 条引用记忆，显示 layer、explanation 和摘要/对象。
  - 验证结果：新增测试先红后绿；`runtime_api` 34 条测试通过，前端 JS 语法检查通过。
  - 内容检查：`entity_graph` 来源会显示“知识图谱：实体、关系或事实匹配”，并保留 subject/predicate/object。
  - 遗留问题：这还是证据列表，不是完整“推理过程回放”；建议解释和聊天解释还没有统一成一个专门页面。

- [x] 缺少采集状态可视化
  - 当前有 health API。
  - 已完成：新增 `/api/collectors/status`，合并 collector settings 与 collector health。
  - 已完成：前端“采集控制”面板显示每个来源的开启/暂停状态、健康状态、最后事件时间、最后注入时间、错误数和 details。
  - 验证结果：新增测试先红后绿；`runtime_api` 30 条测试通过，前端 JS 语法检查通过。
  - 内容检查：样例状态输出包含 `source=gmail`、`enabled=true`、`health_status=healthy`、`last_event_at`、`last_injection_at`、`details.preview_count=10`。
  - 遗留问题：仍没有每个账号的登录身份展示，也没有采集质量趋势图；目前是状态面板，不是完整可观测性 dashboard。

## 已经基本实现，但需要继续验证

- [x] 私有云 Docker 部署
- [x] noVNC + Chromium 持久化登录环境
- [x] Redis Stream 事件队列
- [x] Postgres + pgvector 存储
- [x] 本地 FastEmbed 向量化
- [x] 基础语义事件处理
- [x] Gmail 收件箱预览采集
- [x] WhatsApp 可见页面文本采集
- [x] Google Search 基础采集
- [x] Focus 基础采集
- [x] KV + 知识图谱 + RAG 的初版记忆架构
- [x] 基础主动建议 API
- [x] 简单密码保护 Web 页面
- [x] 记忆查看与删除接口
- [x] 服务器 4C/8G 资源限制和持久化配置
- [ ] 高噪声采集下的 worker 吞吐优化
  - 2026-05-26 云服务器回归发现：真实 Chromium runtime 持续产生 focus/network 事件时，单 worker 顺序调用模型会排队，测试样本需要暂停采集器或降低噪声后才能稳定快速验证。
  - 当前不影响低频个人使用的正确性，但长期运行时应增加事件优先级、低价值 network 事件过滤/聚合、worker 并发或消费组、模型调用超时与重试观测。

## 建议开发顺序

### 第一优先级

1. 补齐采集源开关和暂停采集。
2. 补 Gmail 深度正文采集，但先加验证码/支付/链接脱敏保护。
3. 补自动每日 consolidation 和 raw event 清理。
4. 补 Calendar Collector。
5. 补主动建议中的邮件待办和日程提醒。

### 第二优先级

1. 把 WhatsApp 从可见文本采集升级为 MutationObserver 新消息监听。
2. 强化实体抽取、实体合并、关系置信度。
3. 把 `/search` 升级成真正 Personal Search。
4. 前端增加 collector 状态、记忆来源、删除/暂停入口。

### 第三优先级

1. 独立 model-router。
2. HTTPS/TLS。

## 验收注意事项

后续每补一个模块，都不能只看接口是否成功或测试是否通过，还需要检查：

- 采集到的原始内容是否真实、完整、没有明显误读。
- 脱敏后的内容是否仍保留任务所需语义。
- 语义事件的 summary、intent、entities 是否合理。
- KV、知识图谱、RAG 分别写入了什么，是否应该写入。
- 检索时命中的记忆是否和问题相关。
- 主动建议是否有价值，是否过度打扰。
- 删除或暂停后，数据是否真的不再被使用。
