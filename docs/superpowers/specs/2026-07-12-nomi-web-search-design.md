# Nomi Web Search 设计与技术调研

日期：2026-07-12
状态：代码级实现完成；真实 Provider、云服务器和 Android 真机验收待完成
范围：公开互联网检索、网页正文读取、证据引用、深度研究；不包含登录态网站自动操作

## 1. 目标

Nomi 需要的不只是一个 `search(query)` 接口，而是一层统一的 **Web Evidence Runtime**：

1. 普通对话可以回答最新、公开、可核验的信息。
2. 现有核心 Pipeline 可以把公开资料与用户私有资料组合使用，例如“根据我的简历找适合的岗位”。
3. 长尾 Agent / OpenCode 可以在执行复杂任务时多轮搜索、读取来源并生成带证据的产物。
4. 所有来自网页的事实都可追踪到 URL、抓取时间和原文片段。
5. 搜索查询不得泄露用户邮件、电话、聊天原文、联系人身份等私有信息。
6. 网页内容只作为不可信数据，不能直接改变 Agent 目标、权限或触发外部副作用。

## 2. 非目标

- Web Search 不替代 Gmail、WhatsApp、Telegram、LinkedIn 等私有渠道采集。
- Web Search 不等于浏览器自动化；搜索和正文读取默认只读。
- V1 不自建全网索引。
- V1 不允许网页中的指令触发发送、付款、投递、加人或提交表单。
- 搜索结果默认不写入用户长期记忆；长期记忆只保存用户明确确认的结论或由用户行为产生的事实。

## 3. 现有代码审计结论

### 3.1 当前没有统一的公开 Web Search 能力

`ChatContextRoute` 只有 dialogue、source、memory、agenda、tasks 等开关，没有 `needs_web`、时效性、查询范围或研究深度字段。当前“信息类问题”会落入普通模型回答，模型可能依赖训练数据而不是实时证据。

### 3.2 当前所谓 search 主要是私有记忆或特定网站搜索

- `personal_search_pipeline` 搜索用户自己的 KV / 图谱 / RAG 数据。
- LinkedIn 搜索由已登录浏览器完成，属于私有账号内的垂直能力。
- 两者都不能回答公开互联网中的最新新闻、文档、产品、法规或研究问题。

### 3.3 OpenCode 目前也没有被授予 Web Search

`runtime_api/scripts/nomi_opencode_cli_adapter.py` 默认只启用 bash、write、edit、read。OpenCode 官方虽然提供 Exa 驱动的 `websearch` 和 `webfetch`，当前 Nomi 配置没有启用。

不能只把 OpenCode 内置 Web Search 打开就结束：那样普通对话和核心 Pipeline 仍然无法使用，而且搜索记录、缓存、引用、隐私脱敏和成本无法由 Nomi 统一审计。

### 3.4 资源约束不适合默认增加完整浏览器爬虫集群

现有 compose 已包含 Postgres、Redis、runtime-api、worker、OpenCode worker 和 5 GB 上限的 Chromium runtime。默认再部署 Firecrawl/Crawl4AI 浏览器池会扩大内存和故障面。V1 应优先使用托管搜索/正文 API，按需才调用已有 Chromium runtime。

## 4. 外部方案调研

### 4.1 Exa

能力：语义/关键词搜索、正文、highlights、发布时间、live crawl；搜索和正文可以一次请求返回。Exa 官方建议 Agent 工作流优先使用 highlights，避免把整页正文灌入上下文。

优点：

- 最贴合 Agent 的“发现 + 证据片段”模型。
- 结果结构适合直接归一化为 Nomi evidence。
- OpenCode 内置 websearch 也使用 Exa，便于一致性验证。
- 支持低延迟模式和较大的免费测试额度。

限制：

- 中文网页覆盖和中国本地信息质量不能只凭宣传判断，必须跑 Nomi 自己的中文基准。
- 查询和 URL 会发送给第三方，必须先脱敏。
- 不能让 OpenCode 绕过 Nomi 直接使用无审计的托管 MCP 作为最终架构。

### 4.2 Tavily

能力：面向 Agent 的搜索 API，支持 basic / fast / advanced、新闻/金融主题、日期范围、域名包含/排除、国家偏好、清洗正文。

优点：

- API 简单，搜索深度与延迟/成本关系明确。
- 对新闻、时效性查询和按国家搜索配置友好。
- 适合快速问答与深度研究共用一个 provider。

限制：

- advanced 搜索消耗更多 credits。
- 仍需 Nomi 自己做来源去重、可信度排序、引用绑定和隐私处理。

### 4.3 Brave Search API

能力：独立 Web 索引、网页/新闻/图片/视频、freshness、额外 snippets、Goggles 重排。

优点：

- 搜索索引独立，适合做 provider 多样性和故障切换。
- 结果层速度、结构和价格可预测。
- extra snippets 对检索阶段很有价值。

限制：

- 主要返回搜索结果和 snippets，深度正文提取需要另一个组件。
- API 条款对结果存储有单独限制，缓存设计要按所选计划核对。
- 中文效果仍需实测。

### 4.4 SearXNG

能力：自托管元搜索，官方文档列出 279 个 engine、默认启用 83 个，可配置 Brave、Bing、DuckDuckGo、Google CSE、Baidu 等。

优点：

- 开源、provider 可替换、查询控制权高。
- 可以补充中文本地引擎。
- 适合作为开源部署的可选 provider。

限制：

- 它聚合的是第三方搜索页面/API，不是稳定的自有索引。
- 无官方 API 的 engine 可能因反爬、页面结构变化、出口 IP 被限而失效。
- 只解决 URL 发现，不解决正文清洗、引用验证和深度研究。
- 不应把公共 SearXNG 实例用于私有查询。

结论：SearXNG 适合作为可选自托管 provider 或中文补充，不适合作为唯一默认 provider。

### 4.5 Jina Reader / Reranker

能力：URL 转 LLM 友好文本、Web 搜索、rerank。

适用点：

- 当搜索 provider 只返回 URL/snippet 时，可作为正文提取 fallback。
- Reranker 可用于对少量候选正文做二阶段排序。

限制：Reader 官方页面给出的平均延迟明显高于普通搜索，不应放在每次简单问答的必经路径；只对排名靠前且 snippet 不足的页面调用。

### 4.6 Firecrawl / Crawl4AI

两者都擅长动态网页、Markdown 清洗、站点 crawl。Crawl4AI 还支持浏览器池、缓存、深度 crawl；Firecrawl 支持 search/scrape/crawl 和 Agent/MCP。

结论：它们是“页面读取/站点爬取”组件，不是 Nomi V1 的默认搜索后端。考虑当前服务器资源和已有 Chromium runtime，V1 只保留适配器接口；遇到 JS 动态页面时优先复用现有 Chromium，后续再评估独立 crawler 服务。

### 4.7 可借鉴的完整项目

#### Open Deep Research

可借鉴：

- 把查询规划、并行 researcher、结果压缩、最终报告分开。
- 不同阶段使用不同模型/预算。
- 用 Deep Research Bench 做中英文评估。

不直接引入原因：Nomi 已有 long-tail event store、planner、checkpoint、policy 和 OpenCode executor。再引入完整 LangGraph 会产生两套任务状态机。

#### Perplexica / Vane

可借鉴：

- Speed / Balanced / Quality 模式。
- 搜索历史、来源展示、域名限定和可点击引用。
- SearXNG 与模型解耦。

不直接引入原因：它是完整问答产品，不是可嵌入 Nomi 的 Python runtime 组件。

#### OpenCode

OpenCode 官方已区分 `websearch`（发现 URL）和 `webfetch`（读取已知 URL）。这个工具边界是正确的，但 Nomi 应提供自己的受控工具，而不是让 OpenCode 绕过项目审计直接访问外部服务。

## 5. 推荐选型

### 5.1 总体决定

实现 provider-neutral 的 Web Evidence Runtime：

- 首选 provider：`Exa`，用于搜索 + highlights，原因是最适合 Agent、一次调用可返回证据片段、与 OpenCode 生态一致。
- 第二 provider：`Tavily`，用于 A/B、时效/新闻查询和故障切换。
- 中文试用 provider：`Bocha Web Search API`。真实 120-case 基准显示非空率 100%、P50 1.105 秒、P95 1.710 秒，但官方/预期域名命中率仅 35%；适合新闻、开源项目和论文发现，不应单独承担求职、法规原文和最新技术发布的权威证据。
- 可选 provider：`Brave`，用于独立索引、多样性或仅 SERP 的低成本路径。
- 自托管可选项：`SearXNG`，用于不希望配置商业 API 或希望补充中文引擎的部署者。
- 正文提取 fallback：直接 HTTP 清洗 -> Jina Reader -> 已有 Chromium runtime；不默认新增 Firecrawl/Crawl4AI 服务。

最终默认 provider 必须由基准测试决定。代码不能把 Exa/Tavily 的字段散落到业务层。

### 5.2 为什么不是“只启用 OpenCode 的 OPENCODE_ENABLE_EXA”

只启用该开关虽然能快速让 PPT 等复杂任务搜索网页，但会留下以下缺口：

- 普通聊天无法搜索。
- 求职等核心 Pipeline 无法统一调用。
- 无法统一脱敏查询。
- 无法统一缓存、限额、trace 和引用表。
- Agent 可能把网页中的恶意指令当作行动指令。
- 同一问题在 Chat 和 OpenCode 中得到不同 provider/不同证据。

因此可以把 OpenCode 内置 search 作为开发期对照组，生产路径应通过 Nomi 的 `web.search` / `web.fetch` 工具。

## 6. 总体架构

```text
用户消息 / 私有事件 / Pipeline / Long-tail task
                    |
             Context & Tool Router
        (need_web / mode / sensitivity)
                    |
       +------------+-------------+
       |                          |
私有上下文并行读取             Web Query Planner
(dialogue/memory/agenda)       (脱敏、拆查询、预算)
       |                          |
       |                   Provider Router
       |             Exa / Tavily / Brave / SearXNG
       |                          |
       |              Normalize + Canonicalize URL
       |                          |
       |             Dedupe + Trust Rank + Rerank
       |                          |
       |              Fetch top documents as needed
       |                          |
       |          Sanitize / Chunk / Injection quarantine
       |                          |
       +-------------+------------+
                     |
              Evidence Pack Builder
                     |
           Answer / Pipeline / OpenCode
                     |
            Claim-Citation Validator
                     |
       Streaming answer + clickable sources + trace
```

## 7. 路由：什么时候调用 Web Search

不能只靠关键词，也不能每个问题都搜索。采用规则优先 + 结构化模型判断 + 运行时兜底。

### 7.1 必须搜索

- 用户明确说“搜索、查一下、网上看看、最新、今天发生了什么”。
- 事实具有明显时效性：新闻、价格、政策、版本、职位、产品库存、人物当前职位。
- 用户要求来源、链接、引用或多方比较。
- 开放式任务要求使用公开资料，例如“做一份 2026 年 AI 视频行业趋势 PPT”。
- Pipeline 声明需要公开证据，例如岗位发现、公司研究、面试准备。

### 7.2 不应搜索

- 闲聊、改写、翻译、计算等模型可直接完成的任务。
- 只询问用户自己的日程、联系人、邮件和聊天记录。
- 已知 URL 的正文读取，应该走 `web.fetch`，不再搜索。
- 用户明确要求只依据给定资料。

### 7.3 可并行搜索与私有数据

例如“根据我的简历找最近适合我的 Go 后端岗位”：

- 私有侧并行获取简历、职业偏好、历史申请记录。
- Web 侧只使用脱敏后的能力画像与岗位条件搜索。
- 两边完成后再做匹配，不把姓名、手机号、邮箱、原始简历全文发给搜索 provider。

### 7.4 新路由字段

```json
{
  "needs_web": true,
  "web_mode": "quick | balanced | research",
  "freshness": "none | day | week | month | custom",
  "query_sensitivity": "public | derived_private | blocked",
  "allowed_domains": [],
  "blocked_domains": [],
  "max_queries": 3,
  "max_sources": 8,
  "reason": "current_information_required"
}
```

`derived_private` 只允许发送抽象后的查询；`blocked` 必须要求用户缩小或明确授权，不允许自动外发。

## 8. 三种执行模式

### 8.1 Quick

适用：单一事实、当前版本、简单链接发现。

- 1 个查询。
- 返回 5 个候选。
- 使用 provider snippets/highlights。
- 仅当片段不足时读取前 1-2 个正文。
- 目标：搜索阶段 P95 小于 3 秒。

### 8.2 Balanced

适用：比较、推荐、岗位/公司研究。

- 由模型生成 2-3 个互补查询并校验重复度。
- 查询并行执行。
- canonical URL 去重后使用 RRF/provider score 合并。
- 读取前 3-5 个正文，至少保留 2 个独立域名。
- 生成结论前做 claim-citation 校验。

### 8.3 Research

适用：报告、PPT、方案、复杂开放式任务。

- 进入现有 long-tail task runtime，不阻塞普通 `/api/chat`。
- Planner 生成研究问题和停止条件。
- 子查询可并行，但总查询、页面、token、时长都有预算。
- 每轮后做 coverage gap 检查；只为未覆盖问题继续搜索。
- 最多 3 轮，禁止无条件循环。
- 产物 manifest 必须包含来源清单和 evidence-to-content map。

## 9. 核心接口

### 9.1 Provider 接口

```python
class WebSearchProvider(Protocol):
    async def search(self, request: SearchRequest) -> SearchResponse: ...

class WebContentProvider(Protocol):
    async def fetch(self, request: FetchRequest) -> FetchResponse: ...
```

业务层只依赖统一 schema，不读取 Exa/Tavily/Brave 原始字段。

### 9.2 Agent 工具

只暴露两个只读工具：

```text
web.search(query, mode, freshness, domains, max_results)
web.fetch(url, focus, max_chars)
```

工具返回结构化 source IDs。OpenCode 不直接拿搜索 provider key；它通过 Nomi 内部 MCP/HTTP tool 调用，从而复用脱敏、缓存、限额和 trace。

### 9.3 标准 Source Schema

```json
{
  "source_id": "websrc_...",
  "run_id": "webrun_...",
  "query_id": "webq_...",
  "provider": "exa",
  "title": "...",
  "url": "https://...",
  "canonical_url": "https://...",
  "domain": "example.com",
  "published_at": "2026-07-10T00:00:00Z",
  "fetched_at": "2026-07-12T10:00:00Z",
  "snippet": "...",
  "highlights": ["..."],
  "content_hash": "sha256:...",
  "provider_rank": 1,
  "relevance_score": 0.91,
  "trust_tier": "primary | authoritative | secondary | unknown",
  "content_status": "snippet_only | fetched | blocked | failed"
}
```

## 10. 排序、去重和来源质量

### 10.1 URL 归一化

- 去除 `utm_*`、fragment 和已知跟踪参数。
- 解析 redirect 后再去重。
- 同一 canonical URL 只保留信息最完整的结果。
- 同域相似页面按内容 hash/标题相似度去重。

### 10.2 排序

第一阶段：provider rank + freshness + query match。
第二阶段：对前 10-20 条做轻量 rerank。
第三阶段：按任务提升官方/一手来源。

来源优先级不是固定白名单，但以下原则必须进入 score：

1. 用户指定域名。
2. 官方文档、政府、论文、公司原始公告。
3. 直接报道/原始数据。
4. 高质量二手分析。
5. 聚合站、SEO 内容和无作者/无日期页面降权。

V1 不在 2C4G/4C8G 服务器上常驻大 reranker。先使用 provider score + 确定性质量规则；Jina reranker 作为可选 adapter。完成基准后再决定是否部署小型多语言 reranker。

## 11. 引用与答案约束

### 11.1 Claim-level 引用

模型不能只在答案末尾堆 URL。每个可核验事实绑定 `source_id`：

```json
{
  "claim": "某版本在 2026-07-10 发布",
  "source_ids": ["websrc_a", "websrc_b"],
  "support": "direct | inferred | conflicting"
}
```

### 11.2 输出规则

- 当前事实必须有引用。
- 比较/推荐必须说明评价标准。
- 来源冲突时展示冲突，不允许静默选一个。
- 找不到足够证据时明确说“不足以确认”。
- 不将 provider 自带的 LLM answer 当作事实来源；它只能作为候选摘要。
- UI 链接必须使用已规范化且校验过的 URL，不能出现不可点击或溢出消息框的长裸链接。

### 11.3 UI

- 对话正文使用 `[1] [2]` 紧凑引用标记。
- 点击引用打开来源底部面板：标题、域名、发布日期、相关片段、打开网页。
- Research 任务显示“正在搜索 / 正在阅读 / 正在核验 / 已完成”，而不是长时间无反馈。
- Android 悬浮窗与完整 App 复用同一消息及 citation 数据，不在客户端重新拼接链接。

## 12. 安全与隐私

### 12.1 查询脱敏

禁止外发：姓名 + 联系方式、邮箱原文、聊天原文、简历全文、客户名单、访问 token、Cookie、账号密码。

例：

```text
原始：根据张子长的简历，找北京适合他的工作
外发：北京 Go/Python 后端工程师 5年经验 分布式系统 招聘 2026
```

在 trace 中保存脱敏前后的 hash 和 redaction summary，不保存 secret。

### 12.2 SSRF 与抓取边界

- 只允许 `http` / `https`。
- DNS 解析后拒绝 loopback、private、link-local、multicast、云 metadata 地址。
- 每次 redirect 重新校验目标。
- 限制响应体、超时、redirect 次数和 content type。
- 不携带 Chromium 登录 Cookie 读取公开网页。
- 登录态页面继续走现有受控 browser pipeline，不能交给通用 `web.fetch`。

### 12.3 间接 Prompt Injection

OWASP 明确把网页、邮件、文档中的隐藏指令列为间接 Prompt Injection 风险。Nomi 必须执行：

- 网页文本标记为 `UNTRUSTED_WEB_CONTENT`。
- 删除 script/style/隐藏 DOM、可疑编码和明显注入标记。
- 搜索/读取模型没有外部写权限。
- 网页内容不得修改 original goal、plan、permission、confirmation 或 tool allowlist。
- 任何由网页内容诱发的外部动作都必须回到原始用户意图与现有 policy gate 重新校验。
- 对注入命中、域名、source hash 和处理结果留 trace。

## 13. 缓存与持久化

### 13.1 Redis

- Search cache key：provider + normalized query + locale + freshness + domains。
- Quick TTL：普通事实 15 分钟；新闻 2-5 分钟；稳定文档 6-24 小时。
- Fetch cache key：canonical URL + content hash/etag。
- negative cache 只保留 1-5 分钟，避免长期记住暂时性失败。

### 13.2 Postgres

新增：

- `web_search_runs`：用户请求、模式、状态、预算、耗时、route trace。
- `web_search_queries`：脱敏查询、provider、参数、耗时、错误。
- `web_sources`：统一 source schema、内容 hash、trust score。
- `web_claim_citations`：答案/产物中的 claim 到 source 的显式引用。
- `web_search_feedback`：用户对结果有用/无用、链接失效反馈。

正文默认短期保存或只保存 hash + 必要片段，保留期由 provider 条款和项目配置决定。公开网页内容与用户长期记忆分表，绝不自动进入 memory facts/entity graph。

## 14. 与现有功能的集成

### 14.1 Chat

`ChatContextRoute` 增加 web fields。`context_parallel` 根据 route 并行执行 dialogue/memory/agenda/tasks/web，不让 Web Search 串行阻塞其他上下文。

### 14.2 核心 Pipeline

Web Search 是底层 read-only tool，不把所有请求强行改成一个新 Pipeline。

- `job_recommendation_pipeline`：LinkedIn 登录态搜索 + 公开公司职位页/招聘页。
- `interview_preparation_pipeline`：JD + 简历 + 公司公开资料。
- `comparison/shopping/route` 等 Pipeline：按需调用公开证据。
- 新增 `web_answer_pipeline` 只处理纯公开信息问答。

### 14.3 Long-tail Agent / OpenCode

- Planner 可以声明步骤需要 `web.search` 或 `web.fetch`。
- step packet 只携带当前步骤需要的 sources，不把全部网页塞进 256K 上下文。
- OpenCode 通过 Nomi 内部工具调用搜索；生产配置应禁用绕过审计的直接 provider 工具。
- 产物 manifest 的 `source_evidence_ids` 同时支持 private evidence 和 `websrc_*`。

### 14.4 主动建议

V1 不因普通搜索结果主动打扰用户。只有用户已经存在的目标/监控任务才允许定时搜索，例如：

- 已启用的职位监控。
- 用户明确关注的产品价格/政策变化。
- 与已确认行程直接相关的公开状态变化。

每个 monitor 需要 cadence、停止条件、去重 fingerprint 和通知阈值，避免重复建议。

## 15. Provider 故障与预算

### 15.1 Provider Router

- 单 provider 超时不应拖死整个对话。
- Quick 模式默认不进行串行三次重试；失败后立即切一次 fallback。
- Balanced/Research 可并行向两个 provider 查询，但必须受预算控制。
- 记录 provider success rate、P50/P95、空结果率、正文成功率和成本。

### 15.2 Budget

每次运行限制：

- `max_queries`
- `max_results_per_query`
- `max_pages_fetched`
- `max_chars_per_page`
- `max_total_web_tokens`
- `deadline_ms`
- `max_cost_usd`

达到预算就返回当前最有证据的结果，不允许 Agent 自行无限搜索。

## 16. 基准测试计划

在决定默认 provider 前，必须用相同 query set 对 Exa、Tavily、Brave 和可选 SearXNG 做实测。

### 16.1 数据集

至少 120 条：

- 30 条中文时效事实/新闻。
- 20 条英文技术文档/版本。
- 20 条中国本地公司、岗位、产品问题。
- 15 条多来源比较。
- 15 条需要官方一手来源的问题。
- 10 条已知 URL 正文读取。
- 10 条恶意网页/间接 prompt injection。

可加入 Deep Research Bench 的中英文任务作为 Research 模式评估，但不能只依赖 LLM judge。

### 16.2 指标

- Search success rate / empty result rate。
- P50/P95 latency。
- Precision@5、官方来源召回率、域名多样性。
- 结果重复率、失效链接率。
- 正文提取成功率、有效文本比例。
- citation precision：引用是否真的支持 claim。
- citation coverage：可核验 claim 是否都有引用。
- freshness correctness：发布日期与事件日期是否混淆。
- 中文质量人工评分。
- 单请求成本。
- prompt injection 防护通过率。

### 16.3 初始验收线

- Quick 搜索 provider 阶段 P95 <= 3 秒。
- 正文读取不是简单事实的必经路径。
- 前 5 条至少 3 条与问题直接相关。
- 需要官方来源的用例，Top 5 中必须出现官方/一手来源。
- citation precision >= 95%，coverage >= 90%。
- 100% 的恶意网页不得改变目标、权限或触发外部动作。
- 所有超时、限流、空结果都给用户明确状态，不静默失败。

## 17. 实施阶段

### Phase 0：Provider benchmark

- 固化测试集和人工判分规范。
- 编写独立 benchmark harness，不接生产聊天。
- 选出中文/英文/时效/成本下的默认和 fallback provider。

### Phase 1：统一只读 Web Evidence Runtime

- provider interface、schema、query redaction、URL canonicalization。
- Redis cache、Postgres trace、SSRF guard。
- `web.search` / `web.fetch` 内部 API。
- Quick/Balance 查询与 citation pack。

### Phase 2：Chat 与核心 Pipeline

- 扩展语义 router 和 context parallel。
- `web_answer_pipeline`。
- 求职/公司研究等现有 Pipeline 接入。
- Android/Web 的可点击引用 UI。

### Phase 3：Long-tail Agent / OpenCode

- Nomi 内部 MCP/custom tool。
- Research planner、coverage check、预算/停止条件。
- artifact manifest 引用与任务进度事件。

### Phase 4：监控与主动搜索

- 用户显式创建 monitor。
- 变化检测、去重、主动建议门槛。
- Provider 质量和成本仪表。

## 18. 主要代码落点（当前实现）

```text
runtime_api/app/web_search/
  schema.py
  providers/base.py
  providers/exa.py
  providers/tavily.py
  providers/brave.py
  providers/searxng.py
  privacy.py
  urls.py
  ranking.py
  fetcher.py
  citations.py
  cache.py
  persistence.py
  runtime.py
  service.py

runtime_api/app/chat_router.py
runtime_api/app/context_parallel.py
runtime_api/app/artifact_tasks.py
runtime_api/app/pipelines/career.py
runtime_api/app/main.py
runtime_api/scripts/nomi_opencode_cli_adapter.py
runtime_api/scripts/nomi_web_tool.py
runtime_api/scripts/benchmark_web_search.py
research/web-search/fixtures/benchmark_queries.json
```

说明：Web 与 Android 目前通过服务端生成的 Markdown 链接复用现有点击能力；独立的来源卡片 UI 尚未实现，见实现 gap 报告。

## 19. 关键决策摘要

1. Web Search 是统一 Evidence 层，不是 OpenCode 独占插件。
2. Search 与 Fetch 分开，简单问题不无条件抓全文。
3. 私有上下文读取与 Web Search 可以并行，但搜索 query 必须脱敏。
4. Quick/Balanced 走确定性 Pipeline；Research 走现有 long-tail runtime。
5. 首选 Exa、Tavily fallback、Brave/SearXNG 可插拔，最终由中文实测决定。
6. Web 内容不自动写长期记忆。
7. 每个事实做 claim-level citation；找不到证据就明确不足。
8. OpenCode 通过 Nomi 自己的受控工具搜索，避免绕过审计。
9. 不在当前服务器上默认增加重型 crawler/浏览器池。
10. 在开发生产链路前先完成 provider benchmark。

## 20. 调研来源

- OpenCode Tools: https://opencode.ai/docs/tools/
- OpenCode MCP: https://opencode.ai/docs/mcp-servers
- Exa Search: https://exa.ai/docs/reference/search
- Exa Contents: https://exa.ai/docs/reference/contents-api-guide
- Exa Pricing: https://exa.ai/pricing
- Tavily Search: https://docs.tavily.com/documentation/api-reference/endpoint/search
- Tavily Pricing: https://www.tavily.com/pricing
- Brave Search API: https://brave.com/search/api/
- Brave Pricing: https://api-dashboard.search.brave.com/documentation/pricing
- SearXNG Search API: https://docs.searxng.org/dev/search_api.html
- SearXNG Engines: https://docs.searxng.org/user/configured_engines.html
- Jina Reader/Reranker: https://jina.ai/en-US/reader/
- Crawl4AI: https://github.com/unclecode/crawl4ai
- Firecrawl: https://github.com/firecrawl/firecrawl
- Open Deep Research: https://github.com/langchain-ai/open_deep_research
- Perplexica/Vane: https://github.com/ItzCrazyKns/Vane
- OWASP Prompt Injection Prevention: https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html

## 21. 当前实现核对（2026-07-12）

### 21.1 已完成

- 已实现 Exa、Tavily、Bocha、Brave、SearXNG 五类 Provider 适配器及顺序降级。
- 已实现 Quick、Balanced、Research 三种模式、并行子查询、结果归一化、去重、来源分层和排序。
- 已实现 query 脱敏、凭证查询拦截、公开 URL 校验、重定向逐跳校验、响应大小及内容类型限制。
- 已实现内存/Redis 缓存、`web_search_runs`、`web_search_sources`、`web_claim_citations` 持久化。
- 已接入 HTTP Chat、WebSocket Chat、上下文并行读取、求职岗位发现、开放式产物任务和受控 OpenCode 工具。
- 已实现来源 ID 到可点击 Markdown 链接的转换、未知来源剔除和 claim-source 显式记录。
- 已添加 40 条基础查询、三种模式合计 120 个 case 的 benchmark harness。
- 已完成本地全量回归：`780 passed`；Python compile、Docker Compose 配置解析和 `git diff --check` 通过。

### 21.2 尚未完成或尚未证明

- 已使用独立博查测试 Key 完成 120-case 真实搜索基准；结果证明接口和限流重试可用，但官方来源命中率只有 35%，不能据此确定生产默认 Provider。
- 未部署到云服务器，也未在 Android 真机用真实互联网问题验收链接点击、排版、降级提示和端到端 trace。
- claim-source 目前是模型标记约束与显式绑定，不是独立的语义蕴含判定器。
- 通用 fetch 仅处理静态 HTML/text，尚未接入 Jina Reader 或 Chromium 动态页面 fallback。
- URL 校验会解析并拒绝私网 IP，但请求连接未固定到已校验 IP，仍需进一步消除 DNS rebinding 的检查/连接时间差。
- Android 独立来源卡片、Provider 成本看板、用户显式 Web monitor 和主动搜索属于后续阶段。

完整说明见 `docs/superpowers/reports/2026-07-12-nomi-web-search-implementation-gaps.md`。
