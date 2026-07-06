# 2026-06-16 回归失败点修复跟踪

## 范围

来源报告：[2026-06-16-cloud-device-full-chain-regression.md](/Users/wrf/Documents/background/docs/superpowers/reports/2026-06-16-cloud-device-full-chain-regression.md)

目标：逐条修复线上云服务器 / Android 真机全链路回归中发现的失败点。每一项必须包含可复现输入、期望结果、实际结果、根因、修复方式和验收证据。

## F1 Chat 检索未使用已存在的发票记忆

状态：线上已验证通过

复现：

1. 已注入 Gmail 事件，内容包含 `INV-RG-1001`、`1200 USD`、`next Tuesday`。
2. `/search` 查询 `INV-RG-1001 1200 USD next Tuesday` 可以召回对应记忆。
3. `/api/chat` 发送：`帮我处理 INV-RG-1001，但不要付款，只告诉我你找到了什么。`

期望：

- Chat context pack 必须包含与 `INV-RG-1001` 相关的 memory/event/source。
- 模型回答应说明找到了发票编号、金额、到期时间和“不付款”的限制。
- 不应说“没有找到发票信息”。

实际：

- `/api/chat` 返回“没有找到发票信息”。
- 这说明记忆存在，但 chat 检索/上下文拼接没有稳定把强标识符相关内容放入模型上下文。

初步根因：

- `route_chat_context` 能把付款类请求归为 `task_request` 并取 memory。
- 但 `retrieve_context` 主要依赖语义/BM25排序；强标识符如 `INV-RG-1001`、`PHONE_1`、订单号、发票号应作为 literal identifier 强制召回。
- `build_context_pack` 可能在 token 排序时把低置信但强标识符相关内容裁掉。

修复方向：

- 增加强标识符提取与精确召回层。
- 将精确命中的 memory/event 标记为 high-priority evidence，优先进入 context pack。
- 对 payment/invoice 类 task，在未找到强证据时应明确返回“需要补充发票上下文”，而不是让模型自由猜。

验收标准：

- 单元测试：含 `INV-RG-1001` 的 query 必须把精确命中的 memory/event 放入 context pack。
- API 级测试：`/api/chat` 的 fake gateway 能看到 `INV-RG-1001` 上下文。
- 线上复测：真实 `/api/chat` 不再回答找不到发票。

修复记录：

- `runtime_api/app/main.py` 新增强标识符抽取与 `literal_identifier_recall` 精确召回层，覆盖 `INV-*`、`PHONE_1`、`EMAIL_1`、金额/订单等稳定标识。
- 精确召回证据进入 context pack 时标记为 `literal_identifier_recall`，并在 rerank 中获得更高优先级。

本地验收：

- `test_literal_identifiers_extract_invoice_and_masked_phone_tokens`
- `test_retrieve_context_prioritizes_literal_identifier_matches`
- `test_chat_endpoint_passes_literal_identifier_invoice_context_to_model`

## F2 Route pipeline 路由不稳定

状态：线上已验证通过

复现：

- `帮我查去武康路的路线` 有时进入 `openclaw_tool` 并 blocked。
- pipeline smoke 中 route pipeline 可通过，说明能力存在，但自然语言路由不稳定。

期望：

- 查路线/导航/怎么去/去某地路线都应进入 `route_pipeline`。
- 如果只有目的地缺少出发地，应返回 `needs_user_input` 或使用默认当前位置策略，而不是进入长尾 agent。

初步根因：

- core pipeline router 对中文路线意图覆盖不完整。
- OpenClaw fallback 优先级过高。

验收标准：

- 单元测试覆盖“帮我查去武康路的路线”“怎么去人民广场”“导航到静安寺地铁站”。
- 结果为 `core_pipeline/route_pipeline`。

修复/验证记录：

- 当前路由器已有显式 `has_route_intent`，并且 `打车/叫车/Uber` 仍优先进入 `ride_pipeline`。
- 已补充自然口语回归测试，确认路线语句不会落入 OpenClaw 或 ride。

本地验收：

- `test_natural_route_phrases_dispatch_to_route_pipeline`
- `test_ride_phrase_still_dispatches_to_ride_pipeline`

线上复验记录：

- `/api/tools/route` 与 `/api/pipelines/run` 已覆盖：
  - `帮我查去武康路的路线`
  - `怎么去人民广场`
  - `导航到静安寺地铁站`
- 三条路线请求均进入 `route_pipeline`，状态为 `completed_read_only`，目的地分别解析为 `武康路`、`人民广场`、`静安寺地铁站`。
- `帮我打车去武康路` 仍进入 `ride_pipeline`，状态为 `needs_user_input`，缺少 `pickup`，且保留最终确认门禁。
- 判断：自然语言路线请求不会再落到 OpenClaw，打车请求也没有被误归为路线只读。

## F3 Payment pipeline 找不到已存在发票上下文

状态：线上已验证通过，保留 schema 优化项

复现：

- `帮我处理 INV-RG-1001` 进入 payment 相关流程时，未正确从记忆中找到发票。

期望：

- payment pipeline 应复用 F1 的强标识符精确召回。
- 未经用户最终确认不得付款。
- 只读处理时应列出找到的发票信息与可选动作。

初步根因：

- payment pipeline slot 解析只看显式 context 或当前请求文本，未补充检索到的发票 evidence。

验收标准：

- pipeline run 输入 `INV-RG-1001` 时，resolved_slots 至少包含 `invoice_id=INV-RG-1001` 和 evidence/source_event_ids。
- 风险策略仍要求付款前最终确认。

修复记录：

- payment/chat 共享 F1 的强标识符召回能力。
- 现有 pipeline 用例确认 `帮我处理 INV-RG-1001` 会进入 `payment_bill_pipeline`，且可以从 `source_event_ids` 的 sender 推断 counterparty。

本地验收：

- `test_invoice_request_routes_to_payment_bill_pipeline`
- `test_invoice_request_uses_source_event_sender_as_counterparty`

遗留：

- pipeline result 顶层尚未显式输出独立 `invoice_id` 字段，当前仍通过 `amount_or_bill=INV-RG-1001` 表达。线上复验时如前端/执行器需要独立字段，应继续补 schema。

线上复验记录：

- `/api/pipelines/run` 输入 `帮我处理 INV-LIVE-1601`，并提供来源上下文 `counterparty=RG_CFO`。
- 路由结果为 `payment_bill_pipeline`。
- 风险门禁为 `confirmation_required`，没有直接执行付款。
- `resolved_slots.amount_or_bill=INV-LIVE-1601`，`resolved_slots.counterparty=RG_CFO`。
- 判断：支付类 pipeline 的路由、关键 slot 与确认门禁合理；独立 `invoice_id` 字段仍属于后续 schema 清晰度优化，不影响当前安全执行。

## F4 Reply pipeline 指代 slot 解析弱

状态：线上已验证通过

复现：

- `帮我回复这封邮件...` 进入 `reply_pipeline`，但 recipient 解析为 `"这封"`。

期望：

- 对“这封邮件/这个客户/他/她”这类指代，应优先从 `ui_state.current_source`、source context、最近邮件上下文中解析真实收件人。
- 如果上下文不足，应返回缺少收件人，而不是把指代词当收件人。

初步根因：

- slot parser 把中文指代词误当实体。
- source context 与 slot parser 结合不足。

验收标准：

- 单元测试：`这封邮件` 不可作为 recipient。
- 有 `ui_state.current_source.sender/email` 时，应解析为该 sender/email。
- 无上下文时返回 missing slot。

修复记录：

- `communication.message.draft_reply` 的显式回复意图前置，避免“报价单/文件”等正文词把请求误路由到文档 pipeline。
- `extract_recipient_slot` 对“这封邮件/这条消息/这个消息”等指代使用 active source scope，不再把指代词当联系人。

本地验收：

- `test_reply_pipeline_pronoun_email_uses_active_scope_not_literal_this_email`
- `test_reply_pipeline_pronoun_email_uses_active_sender_as_recipient`

线上复验记录：

- `/api/pipelines/run` 输入：`帮我回复这封邮件，说我周五八点可以`。
- 上下文提供：`active_source_scope.source=gmail`、`sender/from=alice@example.com`。
- 修复前结果：`needs_user_input`，缺少 `recipient`。
- 修复后结果：`draft_ready`，`resolved_slots.recipient=alice@example.com`，`channel=gmail`，`message_intent=我周五八点可以`。
- 判断：指代“这封邮件”现在会绑定当前邮件来源发件人，不再把指代词当收件人，也不会在上下文足够时错误要求补充收件人。

## F5 主动建议气泡点击后的落点不完整

状态：线上/真机已验证通过

复现：

1. 新 WhatsApp 事件生成主动建议。
2. 真机显示浮窗气泡和红点。
3. 点击气泡后进入完整工作台，但没有打开建议详情，也没有把该建议上下文带入对话。

期望：

- 点击气泡后至少满足其中之一：
  - 打开建议详情页，并展示来源、正文、动作按钮。
  - 打开对话框，并把建议作为当前上下文展示，用户可直接点 `查路线` / `帮我打车` / `稍后提醒`。

初步根因：

- Android 端 click handler 只打开 workspace，未传 `suggestion_id/source_event_id`。
- Web 工作台缺少读取 query/deeplink 后展示建议详情的入口。

验收标准：

- Android 单元测试或契约测试：bubble tap 生成包含 suggestion id 的 open intent/url。
- Web/API 测试：带 `suggestion_id` 打开时能加载建议详情。
- 真机验证：点击气泡后可看到刚才那条建议内容或动作。

修复记录：

- Android 实时消息解析优先保留 `suggestion_id`，缺失时回退到 `id`，确保主动建议气泡有稳定 deeplink 目标。
- Android 气泡点击打开完整工作台时使用 `#suggestions`，并通过 pending proactive payload 传递 `suggestion_id/id/title/body/rawJson`。
- Web 工作台支持 `#suggestion:<id>`，进入后自动切到建议视图、高亮目标建议、展示来源事件/来源渠道/判断原因。
- Web 建议卡片改为 DOM 安全渲染，避免把用户私有消息直接拼接进 `innerHTML`。
- Web 建议动作按钮接入 `/api/proactive/suggestions/{suggestion_id}/action`，可从建议详情触发 `查路线`、`帮我打车`、`稍后提醒` 等动作；执行后把结果摘要带回对话区。
- Dashboard 并行加载、刷新按钮、主动消息 pending 消费都统一从 URL hash 读取当前 focus suggestion，避免刚高亮又被普通刷新覆盖。

本地验收：

- `node --check runtime_api/app/static/app.js`
- `test_suggestion_action_records_feedback_and_routes_to_pipeline`
- `test_suggestion_action_ride_prepare_keeps_final_confirmation`
- `test_suggestion_action_snooze_records_feedback_and_keeps_evidence`
- `gradle :app:testDebugUnitTest --tests com.par.assistant.android.RealtimeClientTest`

线上遗留：

- 2026-06-17 已完成线上部署和 Redmi 真机复验。

线上/真机复验记录：

- 服务端动作接口 `/api/proactive/suggestions/{suggestion_id}/action` 已返回 `chat_summary`，并把动作结果持久化为同一 `conversation_id` 下的 assistant 消息。
- 线上接口验证：
  - `chat_turn_persisted=True`。
  - `chat_summary` 为：
    - `已按建议进入：路线查询 Pipeline`
    - `目的地：上海博物馆`
    - `执行状态：completed_read_only`
  - 随后请求 `/api/chat/history?conversation_id=<same>` 可读取同一条 assistant 消息，说明不是前端临时假消息。
- 真机验证设备：Redmi `24094RAD4C`。
- 真机操作：在建议页点击目标建议的 `查路线` 按钮，UI dump 显示：
  - `主动建议 False`，说明已从建议页切回对话页。
  - `发送 True`，说明对话输入区可见。
  - `已按建议进入 True`。
  - `路线查询 Pipeline True`。
  - `completed_read_only True`。
  - `上海博物馆 True`。
  - `动作处理失败 False`。
  - `处理中 False`。
- 截图证据：`/tmp/nomi_after_route_fixed.png` 显示对话页中出现动作结果摘要，而不是空白或失败提示。

判断：

- 建议动作现在不是只返回接口成功，而是完成了“建议动作 -> pipeline -> assistant turn 持久化 -> 真机对话页可见”的闭环。
- F5 的真实 Android 链路通过。

## F6 取消/改期事件的 agenda/suggestion 处理不准

状态：线上已验证通过

复现：

- 取消类事件仍可能生成“跟进日程安排”主动建议。
- 改期事件可能留下旧日程，或显示为模糊/重复日程。

期望：

- 取消事件应将相关 agenda 标记为 `cancelled` 或生成低优先级确认项，而不是普通跟进建议。
- 改期事件应关联旧日程并记录 version，不应无脑新建重复日程。

初步根因：

- agenda parser/rules 对 cancel/reschedule operation 的识别和 dedupe key 还不够强。
- proactive suggestion generator 未识别 cancellation intent。

验收标准：

- 单元测试：`周末那个见面先取消` 不生成普通 follow-up suggestion。
- 单元测试：`改到周日上午10点` 生成 update/reschedule operation。

修复/验证记录：

- 取消类语义会输出 `operation=cancel`、`status=canceled`、`missing_fields=[]`。
- 取消类主动建议不会再提供 `route_lookup` / `ride_prepare` 动作。
- 改期相关 dedupe/version 逻辑已有现有测试保护。

本地验收：

- `test_agenda_candidate_for_cancel_keeps_cancel_operation_without_route_need`
- `test_suggestion_for_canceled_meeting_does_not_offer_route_or_ride`
- `test_agenda_dedupe_key_links_reschedule_to_original_conversation`

线上复验记录：

- 注入事件：`周日下午的武康路见面取消了，不用查路线，也不要帮我打车。`
- worker 输出：
  - semantic labels 包含 `cancel/appointment/travel/todo`，`primary_label=cancel`。
  - agenda `status=canceled`，`missing_fields=[]`。
  - suggestion title 为 `确认取消安排`。
  - suggestion body 明确表述“取消或停止安排”。
  - suggestion actions 仅保留 `snooze` 和 `open_source`，不再提供 `route_lookup` / `ride_prepare`。
- 判断：取消类事件不会再被包装成普通“跟进日程”，也不会诱导查路线或打车。

## F7 用户普通对话误生成日程

状态：本地已修复，待线上复验

复现：

- `帮我制定一个明天准备产品经理面试的三步计划。` 被生成 agenda。

期望：

- 用户对 Nomi 的规划/问答请求应进入 dialogue/task memory，不应默认变成日程，除非用户明确“提醒我/安排到日历/创建日程”。

初步根因：

- `nomi_chat` 的语义解析规则把“明天 + 准备/计划”过度归类为 appointment。

验收标准：

- 单元测试：该句不写入 `agenda_items`。
- 若有“提醒我明天准备面试”，才可生成 reminder/todo。

修复记录：

- `worker/app/worker.py` 在 agenda candidate 入口区分 Nomi 对话里的“计划咨询”和“明确提醒/创建日程命令”。
- `普通聊天` 且无 appointment/deadline/payment/todo 等强标签时跳过 agenda。
- `提醒我/设个提醒/待办` 优先归为 todo，避免被“面试”误判为 appointment。

本地验收：

- `test_agenda_candidate_ignores_nomi_chat_planning_request_without_schedule_command`
- `test_agenda_candidate_keeps_nomi_chat_explicit_reminder_request`
- `test_agenda_candidate_ignores_casual_chat_with_relative_time`

## F8 Trace 接口对非 UUID conversation_id 返回 500

状态：线上已验证通过

复现：

- 用非 UUID conversation_id 调 `/api/chat`。
- 再访问 `/api/chat/conversations/{conversation_id}/trace`。
- 返回 500，错误为 PostgreSQL UUID 类型转换失败。

期望：

- 非 UUID 应返回 400，或在写入 chat 时统一标准化成 UUID。
- 任何客户端输入错误都不应产生 500。

初步根因：

- trace endpoint 直接把 path 参数按 UUID 查询。

验收标准：

- API 测试：非 UUID conversation id 返回 400/404，不能 500。

修复记录：

- conversation trace 保留原始 turn，但只把合法 UUID 的 `event_id/suggestion_id` 用于 UUID[] 关联查询。
- 非 UUID 本地事件不会再触发 PostgreSQL UUID cast 错误。
- conversation trace 对非法 `conversation_id` 先做 UUID 校验，直接返回 400。

本地验收：

- `test_conversation_trace_ignores_non_uuid_turn_references`
- `test_conversation_trace_rejects_non_uuid_conversation_id`

线上复验记录：

- 请求：`GET /api/chat/conversations/not-a-uuid/trace`。
- 结果：HTTP 400，body 为 `{"detail":"conversation_id must be a UUID"}`。
- 判断：客户端非法 path 参数不再打到 PostgreSQL UUID cast，也不会暴露 500。

## 修复顺序

1. F1/F3：强标识符精确召回，影响 chat 与 payment。
2. F2/F4：pipeline router 与 slot parser。
3. F6/F7：agenda/proactive 语义解析。
4. F5：Android/Web 建议 deeplink。
5. F8：API 健壮性。

## 2026-06-16 本地聚合验收

已执行：

- `python3 -m pytest runtime_api/tests/test_context_pack_and_chat.py::test_literal_identifiers_extract_invoice_and_masked_phone_tokens runtime_api/tests/test_context_pack_and_chat.py::test_retrieve_context_prioritizes_literal_identifier_matches runtime_api/tests/test_context_pack_and_chat.py::test_chat_endpoint_passes_literal_identifier_invoice_context_to_model runtime_api/tests/test_core_pipeline_engine.py::test_natural_route_phrases_dispatch_to_route_pipeline runtime_api/tests/test_core_pipeline_engine.py::test_ride_phrase_still_dispatches_to_ride_pipeline runtime_api/tests/test_core_pipeline_engine.py::test_reply_pipeline_pronoun_email_uses_active_scope_not_literal_this_email runtime_api/tests/test_core_pipeline_engine.py::test_conversation_trace_ignores_non_uuid_turn_references runtime_api/tests/test_private_event_gap_closure.py::test_suggestion_action_records_feedback_and_routes_to_pipeline runtime_api/tests/test_private_event_gap_closure.py::test_suggestion_action_ride_prepare_keeps_final_confirmation runtime_api/tests/test_private_event_gap_closure.py::test_suggestion_action_snooze_records_feedback_and_keeps_evidence -q`
- `python3 -m pytest worker/tests/test_worker_semantics.py::test_agenda_candidate_ignores_casual_chat_with_relative_time worker/tests/test_worker_semantics.py::test_agenda_candidate_ignores_nomi_chat_planning_request_without_schedule_command worker/tests/test_worker_semantics.py::test_agenda_candidate_keeps_nomi_chat_explicit_reminder_request worker/tests/test_worker_semantics.py::test_agenda_candidate_for_cancel_keeps_cancel_operation_without_route_need worker/tests/test_worker_semantics.py::test_suggestion_for_canceled_meeting_does_not_offer_route_or_ride worker/tests/test_worker_semantics.py::test_agenda_dedupe_key_links_reschedule_to_original_conversation -q`
- `node --check runtime_api/app/static/app.js`
- `gradle :app:testDebugUnitTest --tests com.par.assistant.android.RealtimeClientTest`

结果：

- runtime API 10 条通过。
- worker 语义 6 条通过。
- Web 工作台 JS 语法检查通过。
- Android RealtimeClient 单测通过。

仍需真实链路验证：

- 云服务器部署后的 `/api/chat` 首 token、强标识符召回、pipeline 路由、建议动作执行。
- 真机 Android 悬浮气泡点击打开建议详情，以及连续发送/键盘/浮窗闪烁等 UI 真实表现。
- Gmail/WhatsApp/Telegram 注入到 worker 队列的端到端延迟和主动建议合理性。

## 2026-06-17 补充聚合验收

已执行：

- `python3 -m pytest runtime_api/tests/test_core_pipeline_engine.py::test_natural_route_phrases_dispatch_to_route_pipeline runtime_api/tests/test_core_pipeline_engine.py::test_ride_phrase_still_dispatches_to_ride_pipeline runtime_api/tests/test_core_pipeline_engine.py::test_invoice_request_routes_to_payment_bill_pipeline runtime_api/tests/test_core_pipeline_engine.py::test_invoice_request_uses_source_event_sender_as_counterparty runtime_api/tests/test_core_pipeline_engine.py::test_reply_pipeline_pronoun_email_uses_active_sender_as_recipient runtime_api/tests/test_core_pipeline_engine.py::test_conversation_trace_rejects_non_uuid_conversation_id runtime_api/tests/test_core_pipeline_engine.py::test_conversation_trace_ignores_non_uuid_turn_references -q`
- `python3 -m pytest worker/tests/test_worker_semantics.py::test_suggestion_for_canceled_meeting_does_not_offer_route_or_ride worker/tests/test_worker_semantics.py::test_suggestion_for_social_plan_includes_route_ride_and_snooze_actions worker/tests/test_worker_semantics.py::test_agenda_candidate_for_cancel_keeps_cancel_operation_without_route_need -q`

结果：

- runtime API 7 条通过。
- worker 语义 3 条通过。

线上部署/健康检查：

- 云端 `docker compose ps --format json` 确认：
  - `nomi-runtime-api-1` running。
  - `nomi-worker-1` running。
  - `nomi-model-router-1` healthy。
  - `nomi-postgres-1` healthy。
  - `nomi-redis-1` healthy。
  - `nomi-nginx-1` running。
  - `nomi-chromium-runtime-1` running。

历史阻塞已解除：

- 之前本机 `adb devices -l` 返回空设备列表，导致 F5 无法做真机 UI 回归。
- 2026-06-17 真机重新连接后，已完成 F5 的“建议详情 -> 建议动作 -> 对话页结果展示”验证。

## C1 线上强标识符问答仍过度脱敏金额

状态：本地已修复，待线上复验

复现：

1. 线上注入 Gmail 事件，正文包含 `INV-LIVE-1601`、`1200 USD`、`next Tuesday`、`Do not pay without confirmation`。
2. worker 完成 memory vector / agenda / suggestion 处理。
3. `/api/chat` 发送：`帮我处理 INV-LIVE-1601，但不要付款，只告诉我你找到了什么。`

期望：

- Nomi 应能说明找到了发票编号、金额 `1200 USD`、到期线索和“不要付款/未经确认不付款”的限制。
- 不执行付款。
- 不向模型释放整封邮件或验证码、密码、银行卡等不必要敏感字段。

实际：

- Nomi 能找到 `INV-LIVE-1601`，但金额显示为 `AMOUNT_1`。
- 这说明强标识符召回已经生效，但模型上下文只拿到了 `raw_data` 的保护版，没有拿到必要的本地私有字段。

根因：

- 事件写入时同时保存了脱敏 `raw_data` 和本地加密 `raw_data_private`。
- chat 检索路径只读取并打包脱敏版 `raw_data`。
- 对普通检索这是正确的；但对用户拿强标识符请求“只告诉我找到了什么”的第一方只读场景，应做最小必要字段释放。

修复方向：

- 仅对 `literal_identifier_recall` 命中的事件尝试读取 `raw_data_private`。
- 仅在第一方只读/确认门控请求中释放最小字段：匹配标识符、金额、到期/时间线索、少量命中行。
- 验证码、密码、OAuth token、银行卡、证件号等永不释放。
- 在 context pack 中保留释放策略和原因，便于审计。

验收标准：

- 单元测试：`INV-LIVE-1601` 查询的检索上下文包含 `released_private_evidence.fields.amounts = ["1200 USD"]`。
- API 测试：模型可见上下文中包含 `1200 USD`，而不是只有 `AMOUNT_1`。
- 线上复测：真实 qwen 回答应说出 `1200 USD`，同时确认不会付款。

修复记录：

- `literal_identifier_recall` 查询同时取回 `events.raw_data_private`。
- 仅在第一方只读/确认门控请求中解密私有原文并生成 `released_private_evidence`。
- 最小释放字段包括：强匹配标识符、金额、到期/时间线索、少量命中行。
- 模型上下文压缩白名单只放行 `released_private_evidence` 及其必要嵌套字段，不放行整封私有邮件。
- 邮箱、手机号、URL secret、OAuth token、验证码、银行卡、证件等仍会被过滤或跳过。

本地验收：

- `test_retrieve_context_releases_minimal_private_invoice_fields_for_read_only_literal_query`
- `test_chat_endpoint_passes_literal_identifier_invoice_context_to_model`

线上复验记录：

- 第三次线上复验在 C4 修复后通过：回答使用绝对日期 `2026年6月23日（周二）`，没有再把 `due` 表述为“已逾期/已到期”。

线上复验记录：

- 第一次线上复验金额已正确输出 `1200 USD`，但 qwen 仍把 `due next Tuesday` 表述为 `已到期（Due）`。
- 判定：C1 金额释放已生效；C2 语义仍失败。

## C2 英文 due 被模型误读为已逾期

状态：线上已验证通过

复现：

1. 同 C1，Gmail 原文为 `Invoice INV-LIVE-1601 for 1200 USD is due next Tuesday...`。
2. `/api/chat` 询问只读处理发票。

期望：

- Nomi 应表达为“2026-06-23 周二到期/截止”或“下周二到期”。
- 不能说“已到期/已逾期”，除非绝对日期早于当前或来源时间。

实际：

- 线上 qwen 第一次回答：`状态：已到期（Due）`。
- 金额已经正确，但时间状态解释不合理。

根因：

- 模型看到了英文 `due` 与相对时间 `next Tuesday`，但上下文没有给出解析后的绝对日期。
- 系统提示只要求使用绝对日期，未明确 `due` 的语义边界。

修复记录：

- `released_private_evidence.fields` 新增 `resolved_time_clues`，由来源事件时间解析 `next Tuesday/tomorrow/明天/下周X` 等相对时间。
- 模型上下文白名单放行 `resolved_time_clues`。
- 系统提示增加规则：英文账单/发票里的 `due` 默认表示“到期/截止”，只有绝对到期日期早于当前或来源时间才可说“已逾期”。

本地验收：

- `test_retrieve_context_releases_minimal_private_invoice_fields_for_read_only_literal_query`
- `test_chat_endpoint_passes_literal_identifier_invoice_context_to_model`

## C3 跨会话旧助手回答污染当前证据

状态：本地已修复，待线上复验

复现：

1. C1/C2 的线上复验会把旧的 Nomi 回答也写入对话历史，其中旧回答包含 `INV-LIVE-1601 状态：已到期（Due）`。
2. 再次询问同一发票时，`assistant_dialogue` 按关键词重叠召回了跨会话旧助手回答。
3. 即使新的 Gmail 证据里有 `2026-06-23 周二`，模型仍复读旧助手答案里的“已到期”。

期望：

- 当前会话内的助手追问/上下文可以保留。
- 跨会话的用户纠正和用户偏好可以保留。
- 跨会话的旧助手结论不应作为当前事实证据进入模型上下文，尤其不能覆盖原始私有来源证据。

根因：

- `relevant_assistant_dialogue_items` 对跨会话助手消息使用了关键词重叠召回。
- 旧助手回答不是事实来源，只是历史模型输出；在强标识符任务中会污染原始 Gmail/WhatsApp/Telegram 证据。

修复记录：

- 同一会话消息仍保留。
- 跨会话仅保留用户纠正/用户偏好，或用户本人发出的重叠内容。
- 跨会话助手回答不再仅凭关键词重叠进入 `assistant_dialogue`。

本地验收：

- `test_build_context_pack_excludes_cross_conversation_assistant_answers_for_identifier_tasks`

线上复验记录：

- 第二次线上复验仍失败：Gmail 真实来源已经包含 `1200 USD` 和 `2026-06-23 周二`，但模型回答仍受到旧 Nomi 输出影响。
- 进一步查看 `sources/context_pack` 后确认：问题不只在 `assistant_dialogue`，`literal_identifier_recall` 本身也把旧的 `nomi_chat assistant_message` 和重复用户提问作为强标识符证据召回。
- 第三次线上复验在 C4 修复后通过：`sources` 首位为 Gmail 真实来源，旧跨会话 assistant 结论未再覆盖事实证据。

## C4 literal identifier recall 把旧 Nomi 问答当事实证据

状态：线上已验证通过

复现：

1. 同一强标识符 `INV-LIVE-1601` 已经被多次询问。
2. `events` 表里同时存在：
   - Gmail 原始事件：包含发票编号、金额、到期线索、确认前不付款限制。
   - Nomi 旧用户提问。
   - Nomi 旧 assistant 回答，其中可能包含错误解释，例如“已到期（Due）”。
3. 再次询问时，`literal_identifier_recall` 和 BM25/vector 都可能把 `nomi_chat` 旧问答排在 Gmail 前面。

期望：

- 强标识符查询要优先把 Gmail/WhatsApp/Telegram/LinkedIn/Calendar/文件等外部真实来源作为事实证据。
- 旧 assistant 输出不是事实来源，不能参与当前事实判断。
- 重复的用户提问只表示用户问过，不表示找到事实，也不应挤掉真实来源。

根因：

- 原 `rerank_context` 对所有 `literal_identifier_recall` 给同样高分。
- SQL 层 `LIMIT` 没有优先外部来源，历史 `nomi_chat` 事件可能先占满召回槽位。
- 在已找到外部真实证据时，没有过滤旧 assistant 输出和重复用户提问。

修复记录：

- 新增外部事实来源权重：`gmail`、`whatsapp`、`telegram`、`linkedin`、`calendar`、`browser`、`file` 等。
- `literal_identifier_recall` SQL 改为优先外部来源、优先带 `raw_data_private` 的事实事件。
- 当强标识符已找到外部来源证据时，过滤：
  - `nomi_chat assistant_message`
  - 与当前 query 完全相同的 `nomi_chat user_message`
- 排序额外提升包含 `released_private_evidence` 的来源，尤其是有金额、绝对时间、命中行的事件。

本地验收：

- `test_retrieve_context_prioritizes_external_literal_evidence_over_old_nomi_answers`
- 相关上下文/聊天/pipeline 回归共 13 条通过。

线上复验记录：

- 请求：`帮我处理 INV-LIVE-1601，但不要付款，只告诉我你找到了什么。`
- 结果正确输出：
  - 金额：`1200 美元`
  - 到期日：`2026年6月23日（周二）`
  - 状态：`待付款（需确认）`
  - 明确：`未执行付款操作`
- `sources[0]` 为 Gmail 原始事件，且包含最小私有证据释放 `released_private_evidence.fields.amounts=["1200 USD"]` 和 `resolved_time_clues=["2026-06-23 周二 ..."]`。
- 判断：该链路现在不再只看接口成功，而是语义输出也符合证据和业务约束。
