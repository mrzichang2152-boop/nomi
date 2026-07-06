# 2026-07-02 WhatsApp A-G 问答验收记录

## 背景

用户已在真实 WhatsApp 环境发送 A-G 测试消息，并要求在 Nomi 对话中验证以下问题：

1. 明天我有哪些安排？
2. 人民广场会面是几月几号几点？
3. 保利广场的安排缺什么信息？
4. 我买保险最关心什么？
5. 周五18点前我要做什么？
6. 我最近有什么被取消的安排？

验收标准：

- 回答必须基于真实 WhatsApp 采集结果。
- 日期必须使用绝对日期。
- 取消事项不能被当作仍需执行。
- 除非确实未采集到，否则不能回答“没有记录”。

## 本次发现并修复的问题

### 1. 未提交的 agenda 操作态污染日程召回

现象：

- `明天我有哪些安排？` 的回答混入旧的“上海博物馆见面”。

根因：

- `agenda_items.status = create` 的旧操作态被普通日程召回当成有效安排。

修复：

- 普通日程召回只允许 `scheduled/pending/confirmed/active`。
- 取消查询只允许 `cancelled/canceled`。
- 新增测试：`test_upcoming_agenda_query_excludes_uncommitted_create_items`。

### 2. 无日期 Gmail 待办污染“明天”类问题

现象：

- “云服务器产品即将到期/安排续费”因为命中宽泛 token `安排`，进入“明天有哪些安排”的候选。

根因：

- 明确日期问题未要求候选具备有效时间，且中文 token 过宽。

修复：

- 当用户问题包含 `今天/明天/周五/周末` 等明确相对日期时，没有解析出开始时间、且不包含同一相对日期标记的候选不进入日程召回。
- 新增测试：`test_upcoming_relative_day_query_excludes_unrelated_undated_items`。

### 3. 跨会话历史回答污染当前回答

现象：

- agenda 召回层已经没有“上海博物馆”，但模型最终回答仍提到它。

根因：

- `retrieve_assistant_dialogue_context` 的 SQL 使用 `conversation_id = 当前会话 OR content ILIKE token`，导致其它会话里的旧错误回答进入 `same_conversation`。

修复：

- 有合法 `conversation_id` 时，只查当前会话 turns。
- 没有合法 `conversation_id` 时，才退回 token 搜索。
- 新增测试：`test_retrieve_assistant_dialogue_context_keeps_valid_conversation_id_isolated`。

## 验证命令

本地验证：

```bash
python3 -m pytest -q runtime_api/tests/test_context_pack_and_chat.py::test_upcoming_agenda_query_excludes_uncommitted_create_items runtime_api/tests/test_context_pack_and_chat.py::test_upcoming_relative_day_query_excludes_unrelated_undated_items
python3 -m pytest -q runtime_api/tests/test_context_pack_and_chat.py::test_retrieve_assistant_dialogue_context_keeps_valid_conversation_id_isolated
python3 -m pytest -q runtime_api/tests/test_context_pack_and_chat.py -k 'assistant_dialogue or same_conversation or session_search or agenda or people_square or cancelled or deadline'
python3 -m pytest -q runtime_api/tests/test_chat_router.py worker/tests/test_worker_semantics.py -k 'agenda_candidate or deadline_before_phrase or not_meeting or cancel or dianban or agenda_question or weekday_deadline or insurance_preference or cancelled_arrangements'
```

结果：

- `2 passed`
- `1 passed`
- `21 passed, 45 deselected`
- `25 passed, 101 deselected`

云端验证：

- `runtime-api` 已重建并重启。
- `/health` 返回 `{"status":"ok"}`。
- 云端容器未安装 `pytest`，所以云端只执行应用级召回和 `/api/chat` 验证。

## DB 采集证据

在云端 PostgreSQL 中确认：

| 证据 | 结果 |
| --- | --- |
| WhatsApp events 中包含 `保利广场` | 3 条 |
| WhatsApp events 中包含 `周五18点前把报价单` | 12 条 |
| WhatsApp events 中包含 `我儿子叫王刚` | 2 条 |
| WhatsApp events 中包含 `免赔` 或 `理赔` | 0 条 |

说明：

- `保利广场`、报价截止、王刚家庭关系均已进入真实 WhatsApp 采集链路。
- 当前 DB 中没有捕获到明确保险偏好，所以 “我买保险最关心什么？” 回答没有记录是合理的；如果用户确实发过包含偏好的消息，则这是采集漏失，需要重新提供原始消息文本继续排查。

## 线上召回层结果

### 明天我有哪些安排？

召回项：

- `2026-07-03 周五 03:30`：提醒看保单，类型 `todo`。
- `2026-07-03 周五`：保利广场详聊，缺 `exact_time`。

没有再召回：

- 上海博物馆见面。
- 云服务器续费。

结论：通过。

### 人民广场会面是几月几号几点？

召回项：

- `2026-07-02 周四 15:30`：人民广场见，带合同，来源 WhatsApp。
- 同时召回到更旧的人民广场历史记录。

结论：基本通过。最新、最相关项排在第一；但回答仍会补充旧历史项，后续可优化为“默认只回答最近一条，历史项折叠提示”。

### 保利广场的安排缺什么信息？

召回项：

- `2026-07-03 周五`：保利广场详聊，缺 `exact_time`。

结论：通过。

### 周五18点前我要做什么？

召回项：

- `2026-07-03 周五 18:00`：发报价单，核对成本和利润率。
- `2026-07-03 周五 10:00`：静安寺地铁站见 Maya。

结论：通过。回答包含报价截止任务，也包含同一天 18:00 前的其它安排。

### 我最近有什么被取消的安排？

召回项：

- `2026-07-03 周五`：原见面取消，改电话聊。

结论：通过。取消事项未被当作仍需执行。

## 线上 `/api/chat` 最终回答验收

### Q1 明天我有哪些安排？

回答摘要：

- `2026年7月3日（周五）03:30` 查看保单提醒。
- `2026年7月3日（周五）下午` 保利广场与大刚详聊，具体时间未定。

上下文：

- `agenda_context_count=2`
- `included_agenda_ids=["d27416dc-742f-4df0-8b0c-bad4e63c1ce0", "3367cdf0-0430-4fa5-bd4c-cffe7141eefe"]`

结论：通过。

### Q2 人民广场会面是几月几号几点？

回答摘要：

- 最新相关项为 `2026年7月2日（周四）15:30` 与大刚在人民广场会面，带合同。
- 回答还列出了旧历史人民广场记录。

上下文：

- `included_agenda_ids=["8858f95d-248a-41cb-acf6-181ca56aa6c0", "ecc5f9bf-7a14-4698-add5-715fc6da3a2a"]`

结论：基本通过，但体验待优化：应该默认突出最近一条，不主动把旧历史项变成“请问你指哪一次”。

### Q3 保利广场的安排缺什么信息？

回答摘要：

- 缺少具体时间点。
- 日期为 `2026年7月3日（周五）下午`。

结论：通过。

### Q4 我买保险最关心什么？

回答摘要：

- 当前没有关于保险偏好或关注点的记录。

上下文：

- `memory_context_count=8`
- DB 中 `免赔/理赔` 相关 WhatsApp event 数为 0。

结论：有条件通过。系统没有乱编；若用户确实发过保险偏好，需要继续排查 WhatsApp 是否漏采。

### Q5 周五18点前我要做什么？

回答摘要：

- `2026年7月3日（周五）18:00 前` 发报价单给大刚，并核对成本和利润率。
- 同时列出当天 `10:00` 静安寺地铁站见 Maya。

结论：通过。

### Q6 我最近有什么被取消的安排？

回答摘要：

- 与大刚的见面已取消，改为电话聊。

结论：通过。

## 额外验证：王刚家庭关系

问题：

- `谁儿子叫王刚？`

首次回答：

- `根据上下文记录，您的儿子叫王刚。`

上下文：

- 同时召回 `kv_profile`、`knowledge_graph_context`、`rag_event_memory`。
- 包含 WhatsApp event `45bdae7f-036f-54de-9152-94295c3b1aa1`。

首次结论：失败。

根因：

- 原始 WhatsApp event 的 `sender=大刚`，`message=我儿子叫王刚`，`message_direction=unknown`。
- 规则抽取层把外部渠道消息里的第一人称固定写成 `subject=user`，导致线上 facts 生成 `user -> son_name -> 王刚`。
- 这不是模型临场误答，而是结构化事实写入阶段的归因错误。

修复：

- `worker/app/worker.py` 增加外部渠道第一人称主体解析：`whatsapp/telegram/gmail/linkedin` 的 incoming/unknown 消息如果有 sender，则第一人称事实归属 sender；明确 `outgoing/self` 的消息仍归属 `user`。
- `worker/tests/test_worker_semantics.py` 增加回归测试：
  - incoming WhatsApp：`sender=大刚` 的 `我儿子叫王刚` 必须写成 `大刚 -> son_name -> 王刚`。
  - outgoing WhatsApp：`message_direction=outgoing` 的同样文本仍写成 `user -> son_name -> 王刚`。
- 已部署 worker 到线上，并对污染数据做窄范围修复：删除该 event 派生的旧 semantic/fact/relationship/state/vector/timeline/working_memory，再用新逻辑重建。

修复后验证：

- 线上 facts：`大刚 -> son_name -> 王刚`。
- 线上 memory state：`state:son_name:大刚`。
- 线上 semantic summary：`大刚的儿子叫王刚。`
- `/api/chat` 回答：`根据记录，大刚的儿子叫王刚。`

结论：修复后通过。

备注：

- 用户说明实际发送账号是 `wang`，但当前 WhatsApp 采集到的显示名是 `大刚`。后续如果需要显示 `wang`，应增加联系人别名映射：`wang <-> 大刚`，否则系统只能基于采集到的显示名回答。

## 遗留问题

1. `人民广场会面是几月几号几点？` 仍会列出旧历史项。功能正确，但体验不够果断。建议后续增加确定性回答策略：对明确地点/时间查询，默认只回答最高相关一条，旧项放到“还找到历史记录”。
2. `明天3点半别忘了，不是开会，是提醒你看一下保单` 被解析为 `03:30`。原消息没有“下午”，所以这是严格解析结果；如果产品上希望更像真人理解，可增加“聊天日常语境中 1-7 点默认下午”的可配置规则，但这会引入误判风险。
3. 报价截止相关 WhatsApp event 有 12 条，说明采集层仍可能有重复事件。当前日程/建议层有去重，但后续仍应继续做源事件级去重治理。
