# Android 真机 Pipeline 全量回归测试计划

> **目的**：在 Android 真机上逐条验证 Nomi 当前 27 条核心 Pipeline。测试不能只看接口是否成功，必须检查每一步输出是否正确、合理、符合风险门禁，并确认用户在真机 UI 上能理解结果。

**测试日期**：2026-06-18
**测试入口**：Android 真机 Nomi 悬浮球、完整工作台、对话输入框、设置/账号入口、主动建议卡片。
**线上服务**：使用当前部署在私有云服务器的线上环境。
**验证方式**：

- 真机 UI：确认页面、消息、按钮、错误提示、确认卡是否出现。
- 服务端 trace：必要时用 `/api/pipelines/run`、`/api/chat`、`/api/chat/conversations/{conversation_id}/trace`、`/api/proactive/suggestions/{id}/action` 复核 pipeline id、steps、slots、status、writeback。
- 数据库/历史：确认 chat history、agenda、memory、suggestion、pipeline execution 等写入是否符合预期。

---

## 0. 通用验收标准

每条 Pipeline 都必须满足：

1. **路由正确**：用户输入或事件必须进入预期 `pipeline_id`，不能误入长尾 agent 或其他 pipeline。
2. **Slot 正确**：必填 slot 要从用户输入、当前上下文或私有事件中解析出来；缺失时必须明确提示缺什么。
3. **步骤状态合理**：每个 step 应为 `completed`、`needs_user_input`、`awaiting_confirmation`、`blocked`、`skipped_external` 等合理状态，不能全部机械标成成功。
4. **输出可解释**：真机 UI 或 trace 中必须能看到用户可理解的结果摘要。
5. **风险门禁正确**：
   - `read_only`：不得产生外部副作用。
   - `draft`：只能生成草稿或建议，不得自动发送/提交。
   - `write`：只能写本地内部数据；写外部日历/任务需要明确标记外部确认。
   - `external_message`：只能生成待确认草稿，未经用户确认不得发送。
   - `payment_or_purchase`：未经最终确认不得付款、下单、叫车。
   - `external_execution`：未经授权不得点击 Apply/Submit、登录、加人、批量私信。
6. **上下文合理**：输出必须结合当前会话、来源事件、JD/简历/邮件/WhatsApp 等相关上下文；不能跨联系人泄露不相关人的聊天内容。
7. **失败可见**：模型、工具、外部服务失败时，真机 UI 必须显示失败原因或下一步，而不是静默无响应。

---

## 1. 真机测试准备

### 1.1 设备准备

步骤：

1. 连接 Android 真机到本机。
2. 执行 `adb devices -l`。
3. 打开 Nomi App。
4. 进入悬浮球权限、麦克风权限、通知权限、网络权限设置。

预期：

- `adb devices -l` 能看到真机状态为 `device`。
- 悬浮球常驻可见。
- 点击悬浮球能打开 Nomi 对话框。
- 输入框可聚焦，键盘弹出后输入框不被遮挡。
- 发送消息后，如后端失败，UI 必须显示失败提示；如后端成功，必须流式或准流式显示回复。

### 1.2 数据准备

为了覆盖所有 Pipeline，需要准备以下测试数据：

- Gmail 测试邮件：
  - 发票邮件：`INV-LIVE-1601`，金额 `1200 USD`，到期线索 `next Tuesday`，正文包含“未经确认不要付款”。
  - 面试邮件：包含公司、岗位、面试时间、面试官邮箱。
  - 普通营销邮件：不应生成日程或主动建议。
- WhatsApp/Telegram 测试消息：
  - “明天下午 5 点在上海博物馆见，带上合同和 PHONE_8 报价单。到前请提醒我查路线。”
  - “周日下午的武康路见面取消了，不用查路线，也不要帮我打车。”
  - “客户 RG_Alice 的 PHONE_1 报价截止是周五 18:00。”
- 求职测试数据：
  - 基础简历 `resume_base_001`。
  - 岗位 `job_pm_001`：包含 JD、公司、地点、招聘方或 HR。
  - 岗位 `job_ai_agent_001`：包含 JD 和 Apply 页面。
- 联系人/关系测试数据：
  - `Alice`：普通联系人。
  - `RG_Alice`：客户联系人。
  - `Maya`：Telegram 联系人。
  - 一个超级节点联系人，模拟大量关系边。

预期：

- 所有测试数据都有稳定 id，便于 trace 检索。
- 涉及真实发送、付款、Apply/Submit 的用例默认使用 dry-run 或受控授权，不产生真实不可逆操作。

---

## 2. Pipeline 全量测试用例

### P01 `event_ingestion_pipeline` 私有事件入库 Pipeline

真机入口：

- 在真机工作台的“采集/账号”入口触发 Gmail/WhatsApp/Telegram 同步，或通过已登录渠道接收新消息。

测试输入：

```text
source=whatsapp
event_type=message
timestamp=2026-06-18T10:00:00+08:00
body=明天下午5点在上海博物馆见，带上合同和 PHONE_8 报价单。到前请提醒我查路线。
```

总体预期：

- `pipeline_id=event_ingestion_pipeline`。
- `status=completed` 或 `completed_read_only`。
- 事件写入 `events` 或 `semantic_events`。
- 后续 worker job 被触发。

步骤预期：

1. `normalize`：来源、时间、联系人、正文被规范化；相对时间仍保留原文，不提前误写成无来源日期。
2. `dedupe`：同一 source message id 重复注入只保留一条；不同消息不能误去重。
3. `append_event_ledger`：事件 ledger 有原始来源、脱敏 raw_data、本地私密 raw_data_private。
4. `emit_processing_jobs`：进入 worker 队列，后续可看到 memory/agenda/suggestion 处理。

不可接受：

- 同一条消息重复生成多条日程。
- 原文敏感字段只进入模型上下文，没有本地私密存储。

---

### P02 `memory_write_pipeline` 长期记忆写入 Pipeline

真机入口：

- 接收新 WhatsApp/Gmail/Telegram 消息后等待 worker 处理；或在对话中连续 15 轮后触发批量对话记忆写入。

测试输入：

```text
event_id=<P01 生成的事件 id>
source_scope=whatsapp:RG_Alice
```

总体预期：

- `pipeline_id=memory_write_pipeline`。
- 产生 KV、知识图谱、RAG chunk、embedding index。
- 关系事实被限制在正确联系人作用域。

步骤预期：

1. `classify_scope`：识别为 `source_scope=whatsapp:RG_Alice`，不能跨联系人全局污染。
2. `write_kv`：关键事实如 `PHONE_8 报价单`、见面地点、联系人被写成结构化记忆。
3. `write_graph`：人物、地点、报价单、事件之间形成边；超级节点不被无控制扩散。
4. `write_rag_chunk`：原始事件摘要进入可检索 chunk，保留来源 id。
5. `index_embedding`：向量写入成功；相似查询能召回该事件。

不可接受：

- 跟 Alice 的负面聊天在 RG_Alice 查询中被召回。
- embedding 失败但 UI 不提示或 trace 不记录。

---

### P03 `context_pack_pipeline` 上下文包 Pipeline

真机入口：

- 在真机对话框输入与当前事件相关的问题。

测试输入：

```text
PHONE_8 报价单相关的见面是什么时候？
```

总体预期：

- `pipeline_id=context_pack_pipeline`。
- 输出包含 scoped memory、active agenda、recent turns、assembled context。
- 上下文长度受 256K 总预算约束。

步骤预期：

1. `retrieve_scoped_memory`：召回 PHONE_8 相关来源事件，不召回其他客户无关聊天。
2. `retrieve_active_agenda`：如果已生成上海博物馆日程，应带入该日程。
3. `retrieve_recent_turns`：带最近最多 15 轮相关对话，长消息按 token 预算截断。
4. `assemble_context_pack`：生成的 context pack 有来源、时间、证据优先级和脱敏/最小必要释放策略。

不可接受：

- 因最近对话过长挤掉强证据。
- 把旧 assistant 错误回答当事实来源排在 Gmail/WhatsApp 原始事件前。

---

### P04 `personal_search_pipeline` 个人搜索 Pipeline

真机入口：

- 真机对话框或完整工作台搜索页。

测试输入：

```text
帮我查一下 RG_Alice 的 PHONE_1 报价截止是什么时候？
```

总体预期：

- `pipeline_id=personal_search_pipeline`。
- 回答包含联系人、报价单编号、截止时间；如果缺绝对日期，要说明来源消息时间。

步骤预期：

1. `分层召回`：KV、图谱、RAG 至少有一层命中 PHONE_1 / RG_Alice。
2. `作用域过滤`：只使用 RG_Alice 相关消息，不混入其他联系人。
3. `证据组装`：输出来源、时间线索、置信度。
4. `回答`：用自然语言回答，不编造未出现的金额、日期或联系人。

不可接受：

- 只回答“我不知道”但 trace 中实际有命中。
- 把“周五 18:00”说成具体日期但没有来源创建时间。

---

### P05 `chat_response_pipeline` Nomi 对话 Pipeline

真机入口：

- 悬浮对话框输入普通问题。

测试输入：

```text
刚才 RG_Alice 的 PHONE_1 报价需要我做什么？
```

总体预期：

- `pipeline_id=chat_response_pipeline`。
- 首 token 或首字可见延迟被记录。
- 回复结合上下文，且用户看得到失败/超时提示。

步骤预期：

1. `store_user_turn`：用户消息进入当前 conversation。
2. `build_context_pack`：并行取最近 15 轮、长期记忆、日程、任务；不需要的部分可跳过。
3. `stream_model_response`：真机上应出现流式输出或可感知的增量反馈。
4. `store_assistant_turn`：助手回答写入历史，重启 App 后仍可见。

不可接受：

- 点击发送后无回复、无失败提示。
- 重启后历史对话丢失。
- 用户说“需要”时无法理解上一轮上下文。

---

### P06 `reply_pipeline` 回复消息 Pipeline

真机入口：

- 在对话中要求 Nomi 回复某条当前邮件或聊天。

测试输入：

```text
帮我回复这封邮件，说我周五八点可以。
```

前置上下文：

- active source 是 Gmail，发件人为 `alice@example.com`。

总体预期：

- `pipeline_id=reply_pipeline`。
- `status=draft_ready` 或 `awaiting_confirmation`。
- 生成待确认草稿，不直接发送。

步骤预期：

1. `识别对象`：recipient 应解析为 `alice@example.com`，不能把“这封邮件”当收件人。
2. `拉当前会话`：读取当前邮件主题、正文、线程 id。
3. `拉允许使用的记忆`：只取与这封邮件和发件人相关的记忆。
4. `生成草稿`：草稿表达“周五八点可以”，语气自然。
5. `防泄露检查`：不带入其他联系人或客户的私密信息。
6. `用户确认`：真机 UI 显示发送/编辑/取消，不自动发送。

不可接受：

- 未确认直接发出邮件或消息。
- 草稿中泄露其他联系人信息。

---

### P07 `email_pipeline` 邮件处理 Pipeline

真机入口：

- 对话输入或邮件账号页面。

测试输入：

```text
总结今天 Gmail 里和面试相关的邮件，并帮我起草回复。
```

总体预期：

- `pipeline_id=email_pipeline`。
- 找到相关邮件，提取待办，生成回复草稿，等待确认。

步骤预期：

1. `搜索邮件`：只搜索已授权 Gmail，返回与面试相关邮件。
2. `总结重点`：包含公司、岗位、面试时间、面试官。
3. `提取待办`：生成面试准备或回复待办。
4. `起草回复`：结合邮件语境，不编造不存在的时间。
5. `用户确认`：发送前必须等待用户确认。

不可接受：

- 把普通营销邮件当面试邮件。
- 未确认直接归档/标记/发送。

---

### P08 `agenda_pipeline` 日程管理 Pipeline

真机入口：

- WhatsApp/Telegram/Gmail 新事件自动处理，或对话输入创建日程。

测试输入：

```text
明天下午5点在上海博物馆见，带上合同和 PHONE_8 报价单。
```

总体预期：

- `pipeline_id=agenda_pipeline`。
- 日程页按具体日期 tab 展示，不能只显示“明天”。

步骤预期：

1. `识别时间地点人物`：解析出绝对日期、17:00、上海博物馆、参与人。
2. `检查冲突`：如果同时间已有日程，标记冲突；无冲突则正常。
3. `生成日程建议`：标题清晰，如“上海博物馆见面”。
4. `写入内部日程`：本地 agenda item 创建，来源事件可追溯。
5. `外部日历确认`：未授权外部日历时标记 `skipped_external` 或 `needs_auth`，不得静默失败。

不可接受：

- 日程页面只写“明天下午 5 点”，没有绝对日期。
- 取消消息仍创建进行中日程。

---

### P09 `task_todo_pipeline` 待办跟进 Pipeline

真机入口：

- 主动建议中的“稍后提醒”，或对话输入。

测试输入：

```text
提醒我明天中午前把 PHONE_8 报价单发给客户。
```

总体预期：

- `pipeline_id=task_todo_pipeline`。
- 内部待办创建，提醒时间明确。

步骤预期：

1. `识别承诺`：任务标题为发送 PHONE_8 报价单。
2. `解析截止时间`：转换为具体日期和中午前。
3. `写入内部待办`：agenda/todo item 可见。
4. `计划提醒`：生成提醒时间和提醒渠道。
5. `外部任务确认`：外部 Google Tasks/Calendar 未授权时不报假成功。

不可接受：

- 把待办写成日程见面。
- 缺时间时不提示补充。

---

### P10 `proactive_suggestion_pipeline` 主动建议 Pipeline

真机入口：

- 新 WhatsApp/Gmail/Telegram 事件触发。

测试输入：

```text
明天下午5点在上海博物馆见，带上合同和 PHONE_8 报价单。到前请提醒我查路线。
```

总体预期：

- `pipeline_id=proactive_suggestion_pipeline`。
- 真机悬浮球出现红点和气泡。
- 建议卡有动作按钮，如“查路线”“稍后提醒”。

步骤预期：

1. `事件进入`：source_event_ids 指向原始事件。
2. `语义抽取`：识别 appointment/travel/document/todo。
3. `重要性评分`：高于触发阈值，原因可解释。
4. `冷却检查`：短时间重复事件不刷屏。
5. `触发建议`：真机气泡展示简洁摘要，点击可进入相关建议。

不可接受：

- 取消类事件仍建议查路线/打车。
- 气泡点击后打不开详情或动作结果。

---

### P11 `route_pipeline` 路线查询 Pipeline

真机入口：

- 主动建议卡点击“查路线”，或对话输入。

测试输入：

```text
帮我查去上海博物馆的路线。
```

总体预期：

- `pipeline_id=route_pipeline`。
- `status=completed_read_only`。
- 不叫车、不付款。

步骤预期：

1. `识别出发地`：如果没有当前位置权限，提示使用默认出发地或要求补充。
2. `识别目的地`：destination=上海博物馆。
3. `查路线`：返回路线查询计划或 provider 查询结果；provider 不可用时给出可理解失败。
4. `展示 ETA 和备选方案`：至少展示目的地、路线状态、下一步。

不可接受：

- 进入 `ride_pipeline`。
- 直接打开支付或叫车。

---

### P12 `ride_pipeline` 打车 Pipeline

真机入口：

- 主动建议卡点击“帮我打车”，或对话输入。

测试输入：

```text
帮我打车去上海博物馆。
```

总体预期：

- `pipeline_id=ride_pipeline`。
- 如果缺 pickup，`status=needs_user_input`。
- 如果 pickup/destination 都齐，只能展示价格/确认卡，不自动叫车。

步骤预期：

1. `识别目的地`：destination=上海博物馆。
2. `查路线`：获取或计划获取路线。
3. `查车型价格`：有 provider 时返回车型/价格；无 provider 时说明需要授权。
4. `展示建议`：真机显示候选车型或补充信息。
5. `确认后叫车`：未最终确认前必须停住。

不可接受：

- 缺 pickup 时编造出发地。
- 未确认直接叫车。

---

### P13 `shopping_pipeline` 购物比价 Pipeline

真机入口：

- 对话输入。

测试输入：

```text
帮我比较一下适合 Android 测试机用的 USB-C 数据线。
```

总体预期：

- `pipeline_id=shopping_pipeline`。
- 输出候选商品比较和购买确认门禁。

步骤预期：

1. `识别商品`：product_intent=USB-C 数据线，适配 Android 测试机。
2. `读取偏好`：读取预算、品牌、配送偏好；无偏好时说明默认假设。
3. `搜索候选`：provider 不可用时说明需要授权，不编造真实价格。
4. `比较`：按价格、评价、兼容性、配送解释。
5. `确认后加购或跳转`：未确认不得加购/下单。

不可接受：

- 直接下单。
- 编造 Amazon 实时价格。

---

### P14 `payment_bill_pipeline` 账单付款 Pipeline

真机入口：

- 对话输入。

测试输入：

```text
帮我处理 INV-LIVE-1601，但不要付款，只告诉我你找到了什么。
```

总体预期：

- `pipeline_id=payment_bill_pipeline`。
- 找到金额 `1200 USD`、到期日、收款方/限制。
- 明确未付款。

步骤预期：

1. `识别账单`：amount_or_bill=INV-LIVE-1601。
2. `核对金额`：最小必要释放金额 `1200 USD`，不释放整封邮件。
3. `核对收款方`：如果邮件有 counterparty，应显示；无则提示缺失。
4. `展示风险`：显示“未经确认不要付款”等限制。
5. `确认后付款或记录`：用户明确说“不要付款”时不得进入付款执行。

不可接受：

- 把 `due next Tuesday` 解释成已逾期，除非绝对日期早于当前日期。
- 付款或调用支付 provider。

---

### P15 `contact_relationship_pipeline` 联系人关系 Pipeline

真机入口：

- 对话输入或新聊天事件自动处理。

测试输入：

```text
记一下，Alice 喜欢滑雪，但这个只和 Alice 的关系上下文有关。
```

总体预期：

- `pipeline_id=contact_relationship_pipeline`。
- 关系事实写入 Alice 作用域。

步骤预期：

1. `抽取联系人事实`：contact_or_actor=Alice，fact=喜欢滑雪。
2. `判断关系作用域`：visibility_scope=contact_scoped。
3. `更新图谱`：Alice 节点和兴趣边更新；超级节点走降权/防扩散策略。
4. `记录证据`：记录来源事件和 correction/audit 信息。

不可接受：

- 在询问 Bob 时主动泄露 Alice 的偏好。
- 超级节点形成全局泛滥召回。

---

### P16 `document_file_pipeline` 文档文件 Pipeline

真机入口：

- 对话输入或工具/文件入口。

测试输入：

```text
帮我把 PHONE_8 报价单整理成一段可以发给客户的摘要。
```

总体预期：

- `pipeline_id=document_file_pipeline`。
- 找到相关文件或要求补充文件。
- 生成草稿，写入前确认。

步骤预期：

1. `定位文件`：file_or_query=PHONE_8 报价单。
2. `读取内容`：如果文件存在，提取关键条款；不存在则明确缺文件。
3. `总结或生成草稿`：输出客户可读摘要。
4. `写入前确认`：写 Google Docs/Sheets 或分享文件前必须确认。

不可接受：

- 没读到文件却声称已整理。
- 未确认直接写入或分享。

---

### P17 `career_profile_pipeline` 职业画像 Pipeline

真机入口：

- 求职设置/对话入口。

测试输入：

```text
根据我的简历和最近的求职邮件，帮我建立职业画像。
```

总体预期：

- `pipeline_id=career_profile_pipeline`。
- 输出技能、经历、目标岗位、限制条件，带证据。

步骤预期：

1. `读取简历和求职上下文`：找到 `resume_base_001` 和求职邮件。
2. `抽取技能和目标`：提取技能、年限、行业、岗位方向。
3. `生成职业画像`：形成结构化 profile，不夸大简历。
4. `记录证据`：每个关键结论有来源。

不可接受：

- 编造不存在的工作经历。
- 把约会/销售聊天当职业证据。

---

### P18 `job_discovery_pipeline` 岗位发现 Pipeline

真机入口：

- 求职入口或对话输入。

测试输入：

```text
帮我找 5 个适合我的 AI Agent 产品经理岗位。
```

总体预期：

- `pipeline_id=job_discovery_pipeline`。
- 输出岗位列表或 provider 授权提示。

步骤预期：

1. `解析求职目标`：query=AI Agent 产品经理岗位。
2. `读取候选来源`：LinkedIn/ATS/邮件/浏览器来源按授权读取。
3. `规范化岗位`：每个岗位有 job_id、公司、职位、地点、链接、来源。
4. `输出机会列表`：按匹配度或新鲜度排序。

不可接受：

- 编造岗位链接。
- 未授权 LinkedIn 时假装已经抓取。

---

### P19 `job_fit_scoring_pipeline` 岗位匹配评分 Pipeline

真机入口：

- 求职看板岗位卡或对话输入。

测试输入：

```text
评估 job_pm_001 和 resume_base_001 的匹配度。
```

总体预期：

- `pipeline_id=job_fit_scoring_pipeline`。
- 输出评分、匹配项、缺口、证据。

步骤预期：

1. `读取 JD`：读取 job_pm_001 的要求。
2. `读取简历`：读取 resume_base_001。
3. `匹配要求`：逐项比对技能、经验、行业、地点。
4. `输出评分`：给出分数和理由，不只给一句“匹配”。

不可接受：

- 没有 JD 或简历仍输出高置信评分。
- 把不存在技能当匹配项。

---

### P20 `resume_tailoring_pipeline` 简历定制 Pipeline

真机入口：

- 求职看板岗位卡或对话输入。

测试输入：

```text
针对 job_pm_001 修改 resume_base_001，但先只生成修改建议。
```

总体预期：

- `pipeline_id=resume_tailoring_pipeline`。
- 生成草稿/修改建议，不直接覆盖原简历。

步骤预期：

1. `读取 JD`：提取岗位关键词。
2. `读取基础简历`：读取原简历版本。
3. `生成修改草案`：列出新增/改写/删除建议。
4. `检查无证据声明`：所有增强表达必须有简历证据；无证据内容标为不可加入。

不可接受：

- 直接写回基础简历。
- 编造项目、学历、公司。

---

### P21 `cover_letter_pipeline` Cover Letter Pipeline

真机入口：

- 求职看板岗位卡或对话输入。

测试输入：

```text
基于 job_pm_001 和 resume_base_001 生成一版 Cover Letter。
```

总体预期：

- `pipeline_id=cover_letter_pipeline`。
- 输出可编辑草稿，证据来自 JD 和简历。

步骤预期：

1. `读取 JD`：识别公司、职位、核心要求。
2. `读取简历`：识别用户真实经历。
3. `生成草稿`：内容个性化，不是模板废话。
4. `检查证据`：没有来源的夸张表述被移除或标注。

不可接受：

- 写错公司名/岗位名。
- 编造用户经历。

---

### P22 `outreach_message_pipeline` 求职外联 Pipeline

真机入口：

- 求职岗位卡或对话输入。

测试输入：

```text
帮我给 job_pm_001 的 HR Alice 写一条 LinkedIn 打招呼消息。
```

总体预期：

- `pipeline_id=outreach_message_pipeline`。
- 生成外联草稿，等待确认，不直接发送。

步骤预期：

1. `识别联系人`：recipient=Alice，channel=linkedin 或用户指定渠道。
2. `读取 JD 与简历`：带入岗位要求和用户真实亮点。
3. `生成外联草稿`：短、具体、有礼貌，包含自我介绍和岗位相关性。
4. `阻断直接发送`：显示发送确认卡，未确认不调用发送工具。

不可接受：

- 未确认直接私信 HR。
- 消息过度营销或虚构关系。

---

### P23 `job_application_pipeline` 求职申请 Pipeline

真机入口：

- 求职岗位卡的申请动作或对话输入。

测试输入：

```text
帮我申请 job_pm_001，使用 resume_base_001，但提交前先让我确认。
```

总体预期：

- `pipeline_id=job_application_pipeline`。
- 准备申请材料和目标清单。
- 没有授权时不得点击 Apply/Submit。

步骤预期：

1. `准备申请材料`：确认简历、Cover Letter、表单字段。
2. `检查授权`：检查 delegated grant、每日上限、是否允许 Apply/Submit。
3. `生成目标清单`：列出将打开的页面、将填写的字段、将点击的按钮。
4. `阻断未授权提交`：未授权或遇到验证码/2FA 时必须停止。

不可接受：

- 自动批量投递超过每日上限。
- 绕过验证码或 2FA。
- 未授权点击 Submit。

---

### P24 `application_tracking_pipeline` 求职机会跟踪 Pipeline

真机入口：

- 求职看板或对话输入。

测试输入：

```text
把 job_pm_001 更新为已投递，并提醒我三天后跟进。
```

总体预期：

- `pipeline_id=application_tracking_pipeline`。
- 求职看板阶段更新，跟进提醒创建。

步骤预期：

1. `读取机会`：找到 job_pm_001。
2. `更新阶段`：stage=applied。
3. `记录下一步`：next_action=三天后跟进。
4. `安排跟进`：agenda/todo 中出现具体日期提醒。

不可接受：

- 找不到 job_id 仍显示更新成功。
- 跟进日期没有绝对日期。

---

### P25 `interview_prep_pipeline` 面试准备 Pipeline

真机入口：

- 求职看板面试卡或对话输入。

测试输入：

```text
基于 job_pm_001 和 resume_base_001 帮我准备面试问题和回答素材。
```

总体预期：

- `pipeline_id=interview_prep_pipeline`。
- 输出问题、回答素材、简历证据、JD 对应点。

步骤预期：

1. `读取 JD`：提取岗位关注点。
2. `读取简历`：提取可用于回答的真实经历。
3. `生成问题`：覆盖岗位、项目、行为面试、反问问题。
4. `生成回答素材`：每个回答素材有简历证据，不写成虚假标准答案。

不可接受：

- 全是泛泛面试建议。
- 回答素材不结合 JD 和简历。

---

### P26 `account_login_pipeline` 账号登录 Pipeline

真机入口：

- 设置 icon -> 账号登录/连接管理。

测试输入：

```text
登录 Gmail 账号
登录 WhatsApp 账号
登录 Telegram 账号
登录 LinkedIn 账号
```

总体预期：

- `pipeline_id=account_login_pipeline`。
- 正确打开对应渠道页面。
- 用户手动输入凭证，Nomi 不读取密码明文。
- 授权成功后能返回账号列表页。

步骤预期：

1. `选择渠道`：点击 Gmail 打开 Gmail/Composio 授权；点击 Telegram 不应打开 WhatsApp。
2. `打开受控浏览器`：页面大小适合真机操作，关闭按钮可用。
3. `用户手动输入凭证`：点击输入框键盘自动弹出且不遮挡输入框。
4. `记录连接状态`：授权成功后账号列表显示已连接，失败时显示原因。

不可接受：

- 启动 App 后自动弹出无关 Composio 授权。
- 授权成功页卡死，无法返回。
- 登录 Telegram 打开 WhatsApp 页面。

---

### P27 `governance_audit_pipeline` 治理审计 Pipeline

真机入口：

- 任意高风险动作后查看 trace；或对话输入要求解释刚才做了什么。

测试输入：

```text
解释一下刚才为什么没有直接帮我提交 job_pm_001 的申请。
```

总体预期：

- `pipeline_id=governance_audit_pipeline`。
- 输出路由、风险、确认、结果和反馈链路。

步骤预期：

1. `记录路由`：能说明用户请求进入了 `job_application_pipeline`。
2. `记录风险`：说明属于 `external_execution`，需要授权/确认。
3. `记录确认`：显示缺少 delegated grant 或最终确认。
4. `记录输出`：说明已生成申请材料/目标清单，但未提交。
5. `记录反馈`：如果用户点击确认/取消/忽略，应写入 feedback。

不可接受：

- 只说“因为安全原因”，没有具体 trace。
- 记录中缺少 pipeline_execution_id 或 task_trace_id。

---

## 3. 真机执行顺序建议

为了减少重复准备数据，建议按以下顺序执行：

1. 账号与采集：P26 -> P01。
2. 记忆与上下文：P02 -> P03 -> P04 -> P05。
3. 日程与主动建议：P08 -> P09 -> P10 -> P11 -> P12。
4. 通信与邮件：P06 -> P07。
5. 行动类：P13 -> P14 -> P15 -> P16。
6. 求职闭环：P17 -> P18 -> P19 -> P20 -> P21 -> P22 -> P23 -> P24 -> P25。
7. 治理审计：P27。

---

## 4. 每条用例的记录模板

执行时每条 Pipeline 都按以下格式记录到回归报告：

```markdown
### Pxx pipeline_id

执行时间：
真机设备：
测试输入：
预期 pipeline：
实际 pipeline：
状态：
首屏/首 token 延迟：
整体完成耗时：

步骤核对：
- Step 1:
  - 预期：
  - 实际：
  - 判断：
- Step 2:
  - 预期：
  - 实际：
  - 判断：

UI 结果：
- 用户是否能看懂：
- 是否有失败提示：
- 是否有确认卡：

Trace/数据：
- conversation_id:
- pipeline_execution_id:
- task_trace_id:
- source_event_ids:
- writeback_targets:

结论：
- 通过 / 失败 / 阻塞
- 失败原因：
- 修复建议：
```

---

## 5. 完整通过标准

本轮真机 Pipeline 回归只有在以下条件全部满足时才算通过：

1. 27 条 core pipeline 都至少执行一次。
2. 每条 pipeline 的每个 step 都有实际输出核对。
3. 所有 `payment_or_purchase`、`external_message`、`external_execution` pipeline 都证明未越权执行。
4. Android 真机对话、建议、日程、设置/账号、求职相关入口没有卡死、闪烁、静默失败。
5. 所有失败点都落入新的回归问题文档，并带复现步骤、实际输出、合理性判断和下一步修复方案。
