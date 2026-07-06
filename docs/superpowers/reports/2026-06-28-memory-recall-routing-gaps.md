# 2026-06-28 Nomi 记忆召回路由实现 Gap 记录

**关联设计文档**：`/Users/wrf/Documents/background/docs/superpowers/specs/2026-06-28-memory-recall-routing-design.md`

**关联实施计划**：`/Users/wrf/Documents/background/docs/superpowers/plans/2026-06-28-memory-recall-routing-implementation.md`

---

## 本轮已落代码

### 1. 结构化路由字段

已在 `runtime_api/app/chat_router.py` 扩展 `ChatContextRoute`：

- 保留旧字段：`intent`、`needs_dialogue`、`needs_source`、`needs_memory`、`needs_agenda`、`needs_tasks`。
- 新增细分字段：
  - `needs_memory_kv`
  - `needs_memory_graph`
  - `needs_memory_rag`
  - `needs_timeline`
  - `needs_external_tool_state`
  - `confidence`
  - `entities`
  - `scope`
  - `risk`
- 新增 `to_decision()`，用于输出可序列化的 route decision。

### 2. 路由规则增强

已补以下实际路由行为：

- “她后来回了吗？”这类没有显式“之前/历史”关键词的隐式指代，会进入 `memory_query`，并打开 graph/RAG/timeline。
- “需要/确认”这类短回复，如果 `ui_state` 中有 pending action/confirmation，会进入 `action_confirmation`，而不是普通聊天。
- “帮我解释一下 BM25 是什么”这类知识问答，不再因为“帮我”误入 `task_request`。
- LinkedIn/JD/简历/HR/求职相关问题会进入 `job_query`，并打开 source、KV、graph、RAG、tasks。
- “Alice 最近有回复吗？”这类联系人关系查询会进入 `relationship_query`，并打开 graph/RAG/timeline。

### 3. Fetch limits 细分

`context_fetch_limits()` 已新增以下预算字段：

- `memory_kv`
- `memory_graph`
- `memory_rag`
- `timeline`
- `external_tool_state`

同时保留旧的 `memory` 字段，避免破坏现有 `/api/chat` 和测试。

### 4. 并行召回层兼容

`runtime_api/app/context_parallel.py` 已支持在 fetchers 中传入：

- `memory_kv`
- `memory_graph`
- `memory_rag`
- `timeline`
- `external_tool_state`

这些层会与 source、memory、dialogue、agenda、tasks 一起并行执行，并进入 `latency_trace`。

---

## 本轮继续补齐的 Gap

### Gap 1：模型驱动 semantic router

状态：已补代码，仍需线上观测。

已实现：

- 新增 `apply_semantic_context_router()`，规则路由先给保守结果。
- 仅对低确定性/模糊问题触发模型路由，例如“有消息了吗”“什么情况”“对方回复了吗”这类可能需要私有上下文的问题。
- 模型只允许返回严格 JSON；解析失败、超时、模型不可用、非法 intent 时全部回退规则路由。
- 最终仍复用 `route_chat_context(..., semantic_router=...)` 的结构校验，模型不能绕过 route schema。
- 单测覆盖模型升级和模型乱回退：
  - `runtime_api/tests/test_semantic_context_router.py`

仍需注意：

- 当前语义路由默认只在 ambiguous 场景调用，不会每条问题都调用模型；这是为了避免首响被额外模型调用拖慢。
- 线上还需要采集 semantic router 的触发率、耗时、误召回率。

### Gap 2：`/api/chat` 和 WebSocket 使用 combined memory fetcher

状态：已补代码。

已实现：

- `/api/chat` 按 route 的 detailed limits 显式注入：
  - `memory_kv`
  - `memory_graph`
  - `memory_rag`
  - `timeline`
- WebSocket 流式聊天入口也同步改成同样的分层 fetcher。
- `merge_parallel_memory_context()` 会按 `memory_kv -> memory_graph -> memory_rag -> timeline -> memory` 顺序合并，并按 `source_id/event_id/id/memory_id/source_event_ids` 去重。
- 修复 `source_id_for_context_item()` 不识别显式 `source_id` 的问题，避免分层证据重复进入 prompt。
- 对 `INV-*`、`PHONE_1` 这类精确私有标识符，仍额外保留一次 literal/legacy memory fetcher，避免发票金额、到期日期等证据被分层过滤漏掉。

验证：

- `test_chat_response_uses_explicit_memory_layer_fetchers` 确认普通记忆问题不会走旧 combined fetcher。
- `test_chat_endpoint_passes_literal_identifier_invoice_context_to_model` 确认发票精确编号仍能把金额和绝对日期传给模型。

### Gap 3：route trace 单独持久化

状态：已补代码。

已实现：

- 新增 `context_route_traces` 表和索引。
- 新增：
  - `persist_context_route_trace()`
  - `safe_persist_context_route_trace()`
  - `context_layer_counts()`
  - `context_fusion_summary()`
- `/api/chat` 和 WebSocket 流式聊天都会持久化：
  - route decision
  - fetch limits
  - per-layer latency
  - layer counts
  - fusion summary
  - token budget
- `/api/chat` 和 WebSocket `chat_done` 响应会返回 `context_route_trace_id`。

### Gap 4：Context fusion 分层结果不可解释

状态：已补可解释摘要；底层排序已使用现有 pack 顺序。

已实现：

- `build_context_pack()` 已按固定层级打包：
  - `current_request`
  - `same_conversation`
  - `source_context`
  - `task_context`
  - `agenda_context`
  - `kv_profile`
  - `knowledge_graph_context`
  - `rag_event_memory`
  - `memory_context`
- 新增 `fusion_summary`，在响应和 trace 中展示每层 item count、token 使用、裁剪/警告数量和 retrieval modes。

仍需注意：

- 这版主要补“可解释”和“可验收”，不是彻底重写 ranking 模型。
- 后续线上如果发现某层排序不合理，需要基于 `context_route_traces` 中的真实样本继续调权重。

### Gap 5：超级节点限制

状态：已存在并补充验证说明。

当前代码：

- `RetrievalPlan.supernode_degree_limit = 80`
- `graph_fact_sql()` 使用 `entity_degree` 并对 subject/object 两端 degree 做上限过滤。

已有测试：

- `runtime_api/tests/test_vector_and_suggestions.py::test_graph_query_filters_supernodes`

仍需注意：

- 这是 DB 查询层 degree cap，不是完整的人际关系产品化治理。
- 关系权重衰减、用户可视化纠错、超级节点白名单/黑名单还属于后续产品化治理，不是本次路由 gap 的一部分。

---

## 仍未完成 / 必须如实保留的 Gap

### Gap A：真实线上账号回归没有在本轮执行

本轮只跑了本地单元测试，没有验证：

- 真实 Gmail 新邮件会议查询。
- 真实 WhatsApp/Telegram 消息注入。
- 真实 LinkedIn JD/HR 页面。
- Android 真机悬浮窗连续对话。

后续做法：

- 部署到云服务器后，用真机和真实账号跑 `/Users/wrf/Documents/background/docs/superpowers/plans/2026-06-20-real-account-e2e-regression-plan.md` 里的真实链路。
- 必须检查输出内容是否合理，不能只看接口 success。

---

## 当前结论

这轮已经补齐本地代码层面的主要 gap：结构化 route、模型+规则混合路由、分层并行召回、literal identifier 防漏召回、route trace 持久化、fusion summary、WebSocket 与 HTTP 行为一致。

但这还不能声称真实生产链路完全没问题。剩余必须靠云服务器和真机真实账号验收：Gmail/WhatsApp/Telegram/LinkedIn 的注入、主动建议、Android 流式对话、真实账号 scope 隔离和内容合理性。

本地局部验证命令：

```bash
python3 -m pytest runtime_api/tests/test_chat_router.py runtime_api/tests/test_semantic_context_router.py runtime_api/tests/test_parallel_context_retrieval.py runtime_api/tests/test_context_pack_and_chat.py runtime_api/tests/test_chat_latency_trace.py runtime_api/tests/test_realtime_ws.py -q
```

结果：`78 passed in 0.73s`。

本地全量 runtime API 回归：

```bash
python3 -m pytest runtime_api/tests -q
```

结果：`578 passed in 2.22s`。
