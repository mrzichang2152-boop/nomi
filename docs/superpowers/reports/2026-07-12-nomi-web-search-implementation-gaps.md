# Nomi Web Search 实现与 Gap 报告

日期：2026-07-12
对应设计：`docs/superpowers/specs/2026-07-12-nomi-web-search-design.md`
结论：核心代码链路已实现并通过本地回归；博查真实 Provider 基准已完成，云端及 Android 真机验收尚未完成。

## 1. 已完成能力

### 1.1 统一 Web Evidence Runtime

- 五类 Provider：Exa、Tavily、Bocha、Brave、SearXNG。
- 统一 Search/Fetch schema、Provider 顺序降级和失败显式返回。
- Quick、Balanced、Research 模式及多查询并发。
- URL 规范化、结果去重、来源可信层级和排序；允许/阻止域名会在统一层再次强制过滤，不依赖 Provider 自觉执行。
- query 脱敏，阻止邮箱、电话、access token、secret 等私有值进入第三方搜索。
- Redis/内存缓存；缓存故障不会让主对话失败。

### 1.2 安全 Fetch

- 只允许公开 HTTP/HTTPS URL。
- 拒绝 localhost、私网、链路本地和云元数据地址。
- 每一跳重定向重新校验。
- 限制超时、重定向次数、正文大小和 content type。
- 删除 script、style、noscript、svg、canvas、template 等不可信页面结构。

### 1.3 Chat、Pipeline 与 Agent 集成

- Chat router 能区分稳定常识、最新公开事实、私有记忆问题和求职发现。
- Web Search 与 KV、RAG、图谱、日程、任务等上下文可并行读取。
- HTTP 与 WebSocket 使用相同 Web 上下文、来源和引用处理。
- 求职岗位发现能把公开搜索结果转入现有 ATS/岗位 Pipeline。
- 开放式产物任务仅在用户允许公开资料时进行 Research，并把 Web evidence 合并进私有 evidence pack。
- OpenCode 只能调用 Nomi 内部 `nomi_web_tool.py`，不会直接得到 Provider API Key。

### 1.4 引用、审计与持久化

- 搜索运行、来源、query hash、耗时和状态分别持久化；来源 ID 按运行隔离，相同 URL 的后续搜索不会覆盖旧运行的审计归属。
- 模型使用 `[websrc_*]` 引用，服务端转换为可点击 Markdown 链接。
- 不存在的 source ID 会被移除，不允许生成伪链接。
- `web_claim_citations` 显式记录 assistant message、claim、source 和绑定状态。
- Web 文本被标记为不可信证据，不能改变任务目标、权限或触发副作用。

## 2. 本地验证证据

- `python3 -m pytest -q runtime_api/tests`：`780 passed in 4.86s`。
- `python3 -m compileall -q runtime_api/app runtime_api/scripts`：通过。
- `git diff --check`：通过。
- 40 条 benchmark query 可展开为 Quick/Balanced/Research 共 120 个 case。
- 博查 Web Search API 的 120-case 真实 benchmark 结果：

```json
{"case_count":120,"completion_rate":1.0,"nonempty_rate":1.0,"expected_domain_hit_rate":0.35,"mean_reciprocal_rank":0.2315,"latency_p50_ms":1105,"latency_p95_ms":1710}
```

分类结果显示：开源项目与最新新闻命中率 100%，论文 75%，中文权威来源 50%，技术文档 25%；最新技术发布、职位和法规原文均为 0%。因此博查可用于试用和部分中文检索，但不适合作为唯一生产证据源。

## 3. 阻塞项

### G01 生产 Provider 组合尚未确定

状态：博查已实测，仍需对照 Provider。
影响：博查官方来源命中率不足，不能满足设计中权威信息 Top 5 命中和求职发现要求。
解除条件：至少再配置 Exa 或 Tavily，运行同一 120-case 基准并按类别确定默认与 fallback；不能只按返回非空率选型。

### G02 云服务器与 Android 真机未验收

状态：本轮尚未部署。
影响：无法证明真机引用链接可点击、长 URL 不溢出、WebSocket 流式回复正常、Provider 失败提示合理。
验收要求：部署后至少覆盖普通最新问答、求职岗位搜索、开放式 Research 产物、Provider 超时降级四条真实链路。

## 4. 已知代码/产品 Gap

### G03 引用仍是 marker-level，不是 semantic entailment

现状：系统能确保引用指向实际返回的 source，并记录引用前的 claim；不能独立判断该来源是否在语义上充分支持 claim。
后续：加入轻量 citation verifier，输出 supported/partial/unsupported；真实基准要求 precision >= 95%、coverage >= 90%。

### G04 动态页面 Fetch fallback 未完成

现状：通用 Fetch 支持静态 HTML/text。
缺口：JavaScript 强依赖页面可能正文为空。
后续：按静态 Fetch -> Reader API -> 现有 Chromium runtime 的顺序降级，并沿用相同 SSRF、预算和审计策略。

### G05 DNS rebinding 仍有检查/连接时间差

现状：请求前解析域名并拒绝私网 IP，重定向也重复校验。
缺口：真正建立连接时未固定到刚刚校验过的 IP，恶意 DNS 可在两次解析之间变化。
后续：使用可固定 resolved IP 且保留 TLS SNI/Host 校验的 transport，或把 Fetch 隔离到无内网访问权限的网络命名空间。

### G06 Android 独立来源 UI 未实现

现状：服务端输出可点击 Markdown，复用 Android 已有链接打开能力。
缺口：没有独立来源卡片、域名/时间/可信级别展示，也未做真机排版验收。
后续：消息模型直接消费服务端 citation 数据，悬浮窗与完整 App 使用同一 message ID 和 source list。

### G07 模型辅助 Research 规划与验证仍较基础

现状：Research 有确定性多查询、并发、预算和停止条件；OpenCode 可按任务继续调用受控工具。
缺口：query decomposition 主要是确定性扩展，没有独立 coverage checker 自动发现证据空洞。

### G08 成本/速率治理尚未产品化

现状：单请求有模式、查询数、来源数、超时等预算。
缺口：没有按用户/Provider/日累计的 credits、rate limit 和成本看板。

### G09 主动 Web Monitor 不在本次实现范围

现状：普通搜索不会自动写长期记忆，也不会主动打扰用户。
缺口：职位监控、价格变化、法规更新等显式 monitor 尚未实现；这是设计 Phase 4，不应误报为当前能力。

## 5. 下一次真实验收顺序

1. 配置 Exa 或 Tavily 对照 Provider，运行同一 120-case benchmark。
2. 根据中文、英文、时效、官方来源命中和 P95 选择默认/fallback；博查暂作为可用试用 Provider。
3. 部署到云服务器，验证 `/api/web-search/providers`、`/search`、`/fetch` 和 Chat/WebSocket trace。
4. 真机提问最新公开事实，检查首 token、引用可点击性、链接排版和错误降级。
5. 真机运行“依据真实简历找岗位”，确认私有简历与公开岗位证据同时存在且作用域不串线。
6. 真机运行一个需公开研究的 PPT/报告任务，确认 OpenCode 只走受控工具、产物引用可回溯。
7. 注入恶意网页文本，确认其不能改变目标、获取密钥或触发发送/投递等副作用。

## 6. 验收口径

只有在 G01/G02 完成并保存真实 trace 后，才能把 Web Search 标记为“线上可用”。当前准确状态是：**核心代码已实现并通过本地回归，真实环境质量验收未完成。**
