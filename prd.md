# Personal AI Runtime（PAR）

# 完整技术架构方案 v1（基于用户私有云 + Managed Chromium Runtime + 自动语义采集）

---

# 一、项目定位

PAR 是：

# 用户私有化长期个人语义上下文系统

核心：

```text id="ncc9o5"
用户数字行为
    ↓
语义事件
    ↓
长期记忆
    ↓
上下文推理
    ↓
主动帮助
```

不是：

* ChatBot
* AI 浏览器
* 自动化 Agent
* 手动导入资料库

而是：

# Personal Cognitive Runtime

目标：

```text id="zv4mt1"
用户登录自己的真实账号
    ↓
系统自动采集高价值语义事件
    ↓
持续构建个人长期上下文
    ↓
在搜索、提醒、规划、回忆中主动帮助用户
```

第一版必须形成：

* 自动采集闭环
* 自动记忆闭环
* 自动检索闭环
* 自动建议闭环

---

# 二、系统总体架构

```text id="rqarfv"
                ┌──────────────────────┐
                │ Web Assistant UI     │
                └──────────┬───────────┘
                           │
                    REST/WebSocket
                           │
┌─────────────────────────────────────────────────┐
│             User Private Cloud Runtime          │
│                                                 │
│  ┌───────────────────────────────────────────┐  │
│  │ Managed Chromium Runtime                  │  │
│  │                                           │  │
│  │ WhatsApp Web                              │  │
│  │ Gmail                                     │  │
│  │ Google Search                             │  │
│  │ Calendar                                  │  │
│  │ Telegram Web                              │  │
│  └───────────────────────────────────────────┘  │
│                     │                           │
│                     ↓                           │
│           Browser Event Collectors             │
│                     ↓                           │
│                 Redis Queue                    │
│                     ↓                           │
│        Desensitization / Semantic Pipeline     │
│                     ↓                           │
│ ┌───────────────────────────────────────────┐  │
│ │ Memory System                             │  │
│ │                                           │  │
│ │ Timeline Memory                           │  │
│ │ Working Memory                            │  │
│ │ Semantic Memory                           │  │
│ │ Entity Graph                              │  │
│ │ Vector Memory                             │  │
│ └───────────────────────────────────────────┘  │
│                     ↓                           │
│              Reasoning Engine                  │
│                     ↓                           │
│             Suggestion/Search                  │
└─────────────────────────────────────────────────┘
```

---

# 三、部署架构

# 3.1 用户服务器

推荐：

| 配置     | 推荐           |
| ------ | ------------ |
| CPU    | 4 Core       |
| RAM    | 8GB          |
| SSD    | 100GB NVMe   |
| OS     | Ubuntu 22.04 |
| Docker | 必须           |

# 3.2 Docker Compose 架构

```text id="3v4rby"
docker-compose
 ├── chromium-runtime
 ├── runtime-api
 ├── redis
 ├── postgres
 ├── nginx
 ├── worker
 ├── vector-extension
 ├── desensitization-worker
 └── model-router
```

# 3.3 版本形态

## 单用户私有云 / 本地 PC 版本

适合普通用户私有云或本地 PC。

特点：

* 数据存储在用户环境
* 语义抽取调用外部 LLM API
* 请求模型前进行脱敏处理
* 使用轻量 embedding 组件

---

# 四、Managed Chromium Runtime（核心）

# 4.1 技术栈

| 模块                 | 技术                   |
| ------------------ | -------------------- |
| Browser            | Chromium             |
| Automation         | Playwright           |
| Persistent Session | Persistent Context   |
| Virtual Display    | Xvfb                 |
| Injection          | JS Runtime Injection |

---

# 4.2 Runtime 工作方式

用户：

通过远程桌面/VNC：

登录：

* WhatsApp Web
* Gmail
* Google
* Telegram

之后：

# Chromium 永久在线。

---

# 4.3 为什么不用 Extension

因为：

# Chromium 是你完全控制的。

所以：

直接：

```text id="u0jk9p"
Playwright
+
Page Injection
```

即可。

---

# 4.4 Chromium Runtime Controller

核心：

# Playwright Persistent Context

---

# 作用

```text id="olx2n7"
session persistence
page control
dom injection
websocket hook
network hook
```

---

# 4.5 Chromium Runtime 示例

```python id="w1l5if"
browser = playwright.chromium.launch_persistent_context(
    user_data_dir="./user_profile",
    headless=False
)
```

---

# 4.6 Runtime 稳定性要求

第一版必须支持：

* 浏览器崩溃自动重启
* 登录状态持久化
* 页面断线自动恢复
* Collector 注入状态检测
* Collector 异常告警
* 页面结构变更后的降级采集

核心原则：

```text id="pt92df"
采集器可以降级
但 Runtime 不能静默失效
```

---

# 五、数据采集层（Event Collectors）

# 核心原则

只采集：

# 高价值语义事件

不采集：

* 鼠标移动
* 全键盘
* 屏幕录像

采集方式：

* 自动采集
* 事件驱动
* 低噪音
* 可按来源关闭
* 可按会话暂停

第一版不接受手动导入作为主要数据入口。

---

# 5.1 Search Collector

监听：

```text id="x0cwrt"
google.com/search?q=
```

提取：

```json id="v5m4qv"
{
  "type": "search",
  "query": "东京酒店"
}
```

---

# 5.2 WhatsApp Collector（核心）

# 技术

```javascript id="0vccqz"
MutationObserver
```

---

# 工作方式

监听：

* 新消息
* 新会话
* 联系人变化

---

# 示例

```javascript id="t6g10n"
const observer = new MutationObserver((mutations) => {
    // detect new message node
});
```

---

# 输出

```json id="jlwm80"
{
  "type": "whatsapp_message",
  "sender": "Alex",
  "message": "今晚吃饭？",
  "timestamp": 123456
}
```

---

# 5.3 Gmail Collector

采集：

* subject
* sender
* snippet
* thread id
* received time
* labels

不采集：

* 附件原文
* 大段邮件全文
* 邮件编辑过程

用途：

* 邮件提醒
* 任务识别
* 关系识别
* 时间线生成

---

# 5.4 Calendar Collector

采集：

* event title
* attendees
* time
* location
* meeting link
* calendar source

用途：

* 日程回忆
* 冲突检测
* 计划建议
* social_plan 校验

---

# 5.5 Focus Collector

规则：

```text id="4u4f2s"
页面停留 > 120s
```

输出：

```json id="74by3l"
{
  "type": "deep_focus",
  "url": "...",
  "duration": 320
}
```

---

# 5.6 Bookmark Collector

监听：

```text id="5p1xkl"
bookmark/save/star
```

---

# 5.7 Telegram Collector

采集：

* 新消息
* 新会话
* sender
* timestamp
* message snippet

第一版优先级：

```text id="p4it1a"
WhatsApp > Gmail > Search > Calendar > Telegram
```

Telegram 可以作为 v1.1 进入，但架构上从第一版预留。

---

# 5.8 Collector 健康检查

每个 Collector 必须输出：

```json id="v8q9kd"
{
  "collector": "whatsapp",
  "status": "healthy",
  "last_event_at": 123456,
  "last_injection_at": 123456,
  "error_count": 0
}
```

当页面结构变化导致采集失败：

* 标记 degraded
* 记录错误样本
* 暂停高风险解析
* 保留基础 url/title/focus 事件

---

# 六、事件队列系统

# 技术：

# Redis Stream

---

# Event Schema

```json id="2xmf1v"
{
  "event_id": "",
  "timestamp": "",
  "source": "",
  "event_type": "",
  "raw_data": {}
}
```

---

# 七、Semantic Pipeline（核心）

# 目标

Raw Event
→ Semantic Event

---

# 7.0 Desensitization Layer

Raw Event 在本地保留完整原文，但进入外部 LLM API、默认检索索引和 Redis 语义队列前，必须先通过脱敏层。

本地存储采用双轨：

* `events.raw_data_private`：本地加密保存完整原文，仅在用户授权读取或明确需要原文执行任务时使用。
* `events.raw_data`：保存脱敏后的可检索版本，用于默认搜索、向量化、语义抽取和主动建议。

目标：

```text id="mxs74n"
Raw Event
    ↓
Local Encrypted Original Store
    ↓
PII Detection
    ↓
Entity Placeholder
    ↓
LLM Semantic Extraction
    ↓
Entity Restore / Link
```

脱敏对象：

* email
* phone
* address
* payment info
* access token
* precise personal identifier
* private URL query params

示例：

```json id="y69m01"
{
  "raw": "Alex 约我周五在东京站吃饭",
  "masked": "PERSON_1 约我 DATE_1 在 LOCATION_1 吃饭",
  "entity_map": {
    "PERSON_1": "Alex",
    "DATE_1": "周五",
    "LOCATION_1": "东京站"
  }
}
```

说明：

* 外部 LLM API 请求前必须脱敏
* 脱敏失败时事件进入 pending，不直接发送模型

---

# 7.1 Semantic Extractor

# 技术：

Model Router

外部 LLM API：

* Qwen / GPT / Claude 等 OpenAI-compatible API

---

# 输入

```json id="vll7cc"
{
  "message": "周五一起吃饭？"
}
```

---

# 输出

```json id="e0pd90"
{
  "intent": "social_plan",
  "people": ["Alex"],
  "time": "Friday",
  "importance": 0.82
}
```

---

# 7.2 Entity Extraction

提取：

* person
* location
* company
* project
* time

---

# 7.3 Importance Scoring

公式：

```text id="v2lb1u"
importance =
focus_time
+ repeat_frequency
+ user_action
+ relationship_weight
```

---

# 7.4 Model Router

根据任务类型选择模型 API：

| 任务 | 路由 |
| --- | --- |
| semantic extraction | 脱敏后外部 LLM API |
| daily consolidation | 脱敏后外部 LLM API |
| embedding | 轻量 embedding 组件或外部 embedding API |
| reranking | 轻量模型/API |

降级策略：

* 外部 API 不可用时，事件保留在队列
* 所有模型输出必须写入解析版本号
* 独立 `model-router` 服务统一暴露 `/model/route`
* worker、runtime-api 等内部服务不直接散落调用模型供应商

---

# 八、Memory Architecture（真正核心）

# 多层 Memory 系统

---

# 8.0 总原则：Episode + KV + Temporal Graph + RAG

PAR 的长期记忆不采用“聊天记录向量库”作为核心，而采用：

```text id="memory-core-v2"
Episode Store：原始证据
Fact Store：结构化事实
KV State Memory：当前状态与长期偏好
Temporal Knowledge Graph：实体、关系、时间有效性
Vector/BM25 RAG：模糊召回证据
Daily Consolidation：长期沉淀与压缩
```

职责划分：

* Episode 保存证据，不直接等同长期记忆。
* Fact 是从 Episode 中抽取的结构化事实。
* Entity Graph 维护人、地点、项目、商品、事件之间的关系。
* KV State Memory 保存当前活跃任务、稳定偏好、长期状态。
* Vector Memory 只负责召回，不作为最终事实来源。
* Timeline / Semantic Memory 由 consolidation 生成，不应只是逐事件摘要堆积。

---

# 8.1 Episode Store / Raw Events

# PostgreSQL

表：

```sql id="h0eky9"
events
```

保存：

7~30 天。

每条 episode 必须可追溯到来源 app、时间、collector、raw_data。后续所有 fact、memory state、suggestion 都必须保留 `source_event_ids`。

---

# 8.2 Fact Store

# PostgreSQL

表：

```sql id="facts-table-v1"
facts
```

核心字段：

```json id="fact-schema-v1"
{
  "subject": "Alex",
  "predicate": "invited_user_to_dinner",
  "object": "Friday dinner",
  "confidence": 0.84,
  "valid_from": "2026-05-26T00:00:00Z",
  "valid_to": null,
  "source_event_ids": ["..."]
}
```

Fact 是长期记忆的事实单元。Summary 只能辅助展示，不能替代 Fact。

---

# 8.3 Timeline Memory

# PostgreSQL

表：

```sql id="7krt4v"
timeline
```

---

# 示例

```json id="r8wmcw"
{
  "date": "2025-09-01",
  "summary": "用户正在规划东京出差"
}
```

Timeline 由 daily consolidation 生成。第一版可以按天生成 summary，后续支持按主题生成多条 timeline。

---

# 8.4 KV State Memory

# Redis + PostgreSQL

保存：

当前活跃状态。

---

# 示例

```json id="stp2lc"
{
  "active_topic": "Tokyo Trip"
}
```

TTL：

24h~72h。

稳定状态会沉淀到 PostgreSQL `memory_states`：

```json id="memory-state-v1"
{
  "key": "preference.travel.hotel",
  "value": {
    "summary": "用户偏好安静、靠近车站的酒店"
  },
  "confidence": 0.88,
  "source_fact_ids": ["..."]
}
```

---

# 8.5 Semantic Memory

# PostgreSQL JSONB

表：

```sql id="b2db3t"
semantic_memory
```

---

# 示例

```json id="3k9q8j"
{
  "interest": "Japan Travel",
  "confidence": 0.91
}
```

Semantic Memory 是 consolidation 后的稳定长期状态，不是每条事件的重要摘要。

---

# 8.6 Temporal Entity Graph

# V1：

PostgreSQL

后期：

# Neo4j

---

# 表

```sql id="p7y28i"
entities
relationships
facts
```

其中 `facts` 提供事实溯源和时间有效性。

---

# 示例

```text id="4svqgm"
Alex
↔ Tokyo
↔ dinner
↔ friend
```

---

# 8.7 Vector / BM25 RAG Memory

# pgvector

后期：

# Qdrant

---

# 保存

* message embedding
* page embedding
* timeline embedding

Vector Memory 只负责召回候选证据。回答前必须回到 Episode / Fact / Timeline / Semantic Memory 做证据组装。

---

# 8.8 第一版检索路由与落地要求

第一版不是让模型“自己决定记忆从哪里查”，而是在 runtime-api 中先做确定性检索计划：

```text id="memory-routing-v1"
用户问题
  -> rule-based retrieval planner
  -> KV State / Timeline / Semantic Memory / Entity Graph / BM25 / Vector
  -> heuristic reranker
  -> 把带 layer 的证据 JSON 交给模型回答
```

路由原则：

* 当前状态、最近偏好、活跃任务：优先查 `memory_states`。
* 人、关系、明确事实、benchmark QA：优先查 `facts` + `entities` + `relationships`。
* 模糊回忆、长文本、原始对话证据：使用 BM25 + pgvector。
* 时间类问题补充查 `timeline`。
* 所有返回给模型的证据必须保留 `layer`，方便 debug 和质量评估。

embedding 第一版使用本地 `fastembed`：

```text id="embedding-v1"
provider: fastembed
model: sentence-transformers/all-MiniLM-L6-v2
dimensions: 384
fallback: hash_fallback 仅作为不可用时的降级，不可当作质量达标
```

runtime 必须提供 `/api/memory/embedding/probe`，返回实际 provider，不能只展示配置项。
worker 写入 `memory_vectors.metadata.embedding_provider`，用于验证新入库向量是否真实来自 fastembed。

超级节点处理：

* 图谱检索必须计算实体 degree。
* 超过阈值的超级节点不参与当前问题的关系扩展。
* 第一版阈值为 80，后续需要按实体类型动态调整。

验证数据：

* LOCOMO 用于个人对话长期记忆样例。
* LongMemEval-cleaned 用于更大的长期记忆检索验证。
* 验证不能只看接口成功，必须检查每层输出是否包含合理证据。

---

# 九、Memory Consolidation（灵魂）

# 每天凌晨执行

同时支持：

* 低频事件实时合并
* 高价值事件即时更新 Working Memory
* 每日长期记忆 consolidation

---

# 输入

当天全部 events。

---

# AI 自动：

---

## 1. 总结今天

---

## 2. 更新长期状态

---

## 3. 更新关系

---

## 4. 删除低价值 raw events

---

## 5. 生成 timeline

---

## 6. 更新 KV State Memory

---

## 7. 更新 Vector / BM25 索引

---

# 输出

```json id="c1zshq"
{
  "state": [
    "正在规划东京出差",
    "最近频繁联系 Alex"
  ]
}
```

---

# 9.1 Memory Governance

虽然第一阶段暂不把完整隐私合规作为阻塞项，但产品必须提供基本记忆治理能力。

用户可以：

* 查看系统记住了什么
* 删除某条 memory
* 删除某个来源的 memory
* 暂停某个 Collector
* 重新生成某天 timeline

这是产品可信度功能，不作为合规模块处理。

---

# 十、Reasoning Engine

# 技术：

LLM + Retrieval

---

# 工作流

```text id="vcr4oc"
User Query
    ↓
Working Memory
    ↓
Timeline Retrieval
    ↓
Semantic Memory
    ↓
Entity Graph / Fact Retrieval
    ↓
Vector Recall
    ↓
Reranking
    ↓
Reasoning
```

---

# 示例

用户：

```text id="ib7msq"
“我是不是答应了谁吃饭？”
```

---

# 查询：

* WhatsApp
* Timeline
* Calendar
* Semantic Memory

---

# 输出：

```text id="4u6g49"
Alex 周五邀请过晚餐
```

---

# 十一、Suggestion Engine

# Event-driven

不是：

# autonomous loop

第一版只做建议，不直接执行。

---

# Trigger

例如：

```text id="azj6fq"
social_plan
+
calendar_missing
```

---

# 输出

```text id="l8u3jx"
你今晚似乎有晚餐安排
是否需要路线规划？
```

---

# 11.1 Suggestion 类型

第一版建议类型：

* 日程缺失提醒
* 承诺未记录提醒
* 出行/路线建议
* 购物/比价回忆
* 邮件待办提醒
* 近期主题继续提醒

触发原则：

* 必须有明确证据
* 必须可追溯来源
* 必须可被用户忽略
* 不允许自动执行动作

---

# 十二、搜索系统（核心产品）

# Personal Search

---

# 用户：

```text id="fopjlwm"
我之前看的东京酒店
```

---

# 搜索流程

```text id="m4c0fe"
Vector Recall
    ↓
BM25 Recall
    ↓
Timeline Filter
    ↓
Entity Filter
    ↓
Reranking
    ↓
Evidence Assembly
```

---

# 12.1 搜索结果要求

搜索结果必须包含：

* answer
* source events
* related timeline
* confidence
* source app
* event time

示例：

```json id="t5h2wm"
{
  "answer": "你之前看过东京站附近的两家酒店，并在周三搜索过价格。",
  "confidence": 0.86,
  "sources": [
    {
      "source": "google_search",
      "time": "2025-09-01T20:11:00Z",
      "title": "东京站酒店"
    }
  ]
}
```

---

# 十三、API 架构

# Backend

推荐：

# FastAPI

---

# API 示例

---

## POST /event

上传事件。

---

## GET /timeline

获取 timeline。

---

## POST /search

Personal search。

---

## POST /reason

上下文推理。

---

## GET /collectors/health

查看 Collector 健康状态。

---

## POST /memory/delete

删除指定 memory 或指定来源 memory。

---

## POST /model/route

内部模型路由接口，由独立 `model-router` 服务提供。

输入：

```json
{
  "task": "semantic_extraction",
  "messages": []
}
```

输出：

```json
{
  "task": "semantic_extraction",
  "route": "external_llm",
  "model": "qwen3.6",
  "content": "{}"
}
```

---

# 十四、数据与模型调用策略

# 核心原则

所有数据：

# 存储在用户私有云。

其中完整原文保存在本地加密字段，默认模型调用、默认检索和长期记忆整理只使用脱敏版本。

---

# 默认：

# Read Only AI

---

# 14.1 模型请求策略

默认流程：

```text id="qek9ai"
Raw Event
    ↓
Local Desensitization
    ↓
External LLM API
    ↓
Semantic Event
    ↓
Local Memory
```

---

# 14.2 第一阶段暂不展开

以下内容不作为 v1 PRD 阻塞项：

* 完整合规审计
* 平台 ToS 分析
* 企业级权限系统
* 多用户隔离
* 零知识加密
* 完整威胁建模

---

# 不允许：

* 自动发消息
* 自动点击
* 自动支付

---

# 十五、V1 范围（完整自动化闭环）

# 第一阶段必须做：

---

## Managed Chromium Runtime

---

## WhatsApp Collector

---

## Gmail Collector

---

## Search Collector

---

## Calendar Collector

---

## Focus Collector

---

## Timeline

---

## Working Memory

---

## Semantic Memory

---

## Personal Search

---

## Suggestion Engine

---

## Desensitization Worker

---

## Model Router

---

## Collector Health Dashboard

---

# 不做：

* screenpipe
* OCR
* autonomous agent
* 自动回复
* 多用户
* 手动导入作为主要入口

说明：

* v1 交互入口使用 Web Assistant UI
* v1 不追求全平台覆盖，但必须完成自动采集闭环

---

# 十六、真正核心的数据流

```text id="2j3vud"
Chromium Runtime
      ↓
DOM/WebSocket Events
      ↓
Redis Queue
      ↓
Desensitization
      ↓
Model Router
      ↓
Semantic Extraction
      ↓
Working Memory
      ↓
Timeline
      ↓
Semantic Memory
      ↓
Entity Graph
      ↓
Vector Recall
      ↓
Reasoning
      ↓
Suggestion / Search / Assistant
      ↓
Redis Pub/Sub Realtime Channel
      ↓
Web Assistant UI / Android Nomi Floating Bubble
```

说明：主动建议生成后不依赖高频轮询触达用户。Worker 在写入建议记录后向实时频道发布 `proactive_message`，Web / Android 客户端通过 WebSocket 保持连接；Android 端在 Nomi 悬浮球旁展示气泡，用户点击后进入完整工作台对话页。工作台对话使用同一 WebSocket 返回 `chat_delta` / `chat_done`，实现流式输出。
