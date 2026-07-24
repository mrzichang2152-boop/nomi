# Nomi Web Search 系统回归报告

日期：2026-07-21
环境：本地测试、云服务器真实 Runtime、Android 真机 `DQYTCYFMO7VSEAJB`
Provider：Bocha（真实 API）；Exa、Tavily 未配置 Key

## 1. 验收目标

本轮不是单独修复“北京天气”，而是检查完整链路：

1. 用户问题是否正确判断需要联网。
2. 私有问题是否避免发送到公网 Provider。
3. Search Provider 是否按 freshness、mode 和 route 执行。
4. 搜索结果是否经过垃圾过滤、相关性排序、来源等级和证据门禁。
5. 模型是否只依据可追溯证据回答并输出可点击引用。
6. Pipeline 与 OpenCode 开放式 Agent 是否使用同一套审计 Web Search。
7. Android 真机发送、流式回答、历史同步与显示是否可用。

## 2. 本轮发现并修复的根因

### 2.1 普通英文查询被软件实体门禁误杀

- 现象：`What is the weather in Beijing today%3F Cite official sources.` 的结果全部被过滤。
- 根因：原本为 Qwen Release 垃圾结果设计的实体一致性门禁，把句首 `What/Cite` 和地点 `Beijing` 当成软件产品实体。
- 修复：实体一致性门禁只用于 Release、Version、GitHub、Download、Docs 等软件发布/文档查询。
- 回归：跨语言天气来源保留；Qwen 垃圾下载站仍被过滤。

### 2.2 权威域名与查询主题未绑定

- 现象：烟台开发区政府天气页面被当成北京天气的权威证据。
- 根因：质量门禁只检查 `trust_tier`，不检查权威来源是否支持查询地点。
- 修复：天气场景提取地点主题；权威来源必须同时满足来源等级和主题匹配。
- 结果：英文北京天气未找到同地点官方英文来源时返回 `partial`，不再伪装成已核验。

### 2.3 Primary 与 Authoritative 层级混用

- 现象：品牌当前售价可以被高校或政府页面“满足”。
- 根因：`primary_source_not_found` 也接受 `authoritative`。
- 修复：品牌价格必须是 `primary`；政府/气象等事实允许 `primary` 或 `authoritative`。
- 修复补充：价格、天气、现任公职、GitHub Release 等场景专属规则优先于通用“官方”规则。

### 2.4 中文相关性计算退化

- 现象：中文连续文本被当成一个完整 token，排序主要依赖 Provider 原始 rank。
- 修复：中文查询生成 2/3 字 n-gram；标题匹配与正文匹配分别计分，标题匹配权重更高。
- 结果：政策原文、正式标题、具体地点页面优先级提高。

### 2.5 中文凭据未被隐私层识别

- 现象：`我的 Gmail 密码是 secret123，请帮我联网搜索` 曾被发给 Provider。
- 根因：凭据识别只覆盖英文 `password=...`，未覆盖“密码是/密码为/令牌：/API Key 是”。
- 修复：支持中文与全角标点凭据语法；只有凭据和搜索套话的请求在 Provider 调用前返回 422。
- 线上复验：HTTP 422，原因 `query_contains_only_credentials_or_private_identifiers`。

### 2.6 OpenCode Agent 没有显式 freshness

- 现象：开放式 Agent 的“最新/过去 24 小时”可能检索到过旧资料。
- 修复：`nomi_web_tool.py` 增加 `--freshness day/week/month/year`；OpenCode 提示约束按任务选择 freshness。
- 线上复验：在真实 `nomi-opencode-artifact-worker-1` 内执行，返回当天来源。

### 2.7 确定性 Pipeline 的引用污染

- 现象：求职确定性结果后追加无关掘金等通用引用。
- 修复：确定性 Pipeline 禁止自动追加 fallback sources，只保留 Pipeline 本身的真实 LinkedIn 来源。

### 2.8 模型重复输出证据质量提示

- 现象：系统已经加入“未找到官方一手来源”，模型仍会在开头或结尾重复说明二手来源，导致回答啰嗦且像故障提示。
- 修复：只清理首段或明确以“注意/说明”开头的重复证据质量段落；保留“没有找到具体 Release”这类直接回答问题的有效结论。
- 线上复验：回答只保留一条系统质量提示；`websrc_*` 均转换为可点击链接，正文无原始引用标记。

## 3. 实际回归结果

| 场景 | 实际路由/状态 | 内容核对 | 结论 |
|---|---|---|---|
| `今天北京天气怎么样？请给出来源` | `web_query`，`needs_web=true` | 7 月 21 日、多云、30/24°C、傍晚雷阵雨；引用中国天气网、腾讯、京报 | 通过 |
| Android 真机 `Weather in Beijing today cite sources` | Web Search，`partial` | 返回北京 7 月 21 日天气；明确说明仅有二手媒体转引气象台，未冒充官方英文证据 | 安全降级通过 |
| Android 真机部署后复验 `What is the weather in Beijing today? Cite sources.` | `dynamic_public_fact`，`freshness=day` | 最终回答只保留一条质量提示，三个来源均为可点击链接，无 `websrc_*` 原始标记 | 通过 |
| `2026年7月北京人工智能产业最新政策` | `completed` | 北京市政府政策文件、北京市科委政策解读等真实来源 | 通过，候选中仍有相关但不够精确的新闻 |
| `iPhone 17 当前官方价格` | `partial` | 未找到 Apple Primary 页面，不把中关村在线价格当官方售价 | 通过 |
| `日本现任首相是谁` | `partial` | 没有日本政府来源时不宣称已核验 | 通过 |
| `Qwen GitHub 最新 Release` | `partial` | 没找到 GitHub Release 官方页；垃圾下载页已过滤 | 通过 |
| `过去24小时人工智能领域最重要的三条新闻` | `fresh_news`，`completed` | 来源均在 freshness 范围内，但“最重要”排序仍包含日报/综述噪声 | 时效通过，重要性排序遗留 |
| `我们部门负责人是谁？` | `relationship_query`，`needs_web=false` | `web_ms=0`，只取本地 source/KV/graph/RAG/timeline | 隐私路由通过 |
| 中文 Gmail 密码查询 | Provider 前阻断 | HTTP 422，没有执行搜索 | 通过 |
| 求职公开岗位 | `job_query` 确定性 Pipeline | 只返回真实 LinkedIn 岗位来源，不再追加无关通用引用 | 通过 |
| OpenCode worker 搜索 | 审计 Web Tool | `freshness=day`，返回当天北京市科委页面 | 通过 |

## 4. 真机 UI 核对

- 真机能够发送查询并收到云端真实回答。
- 输入框在键盘上方，发送后历史同步正常。
- 新回答未出现横向链接溢出，文本边界在悬浮窗内。
- 回答过长时需要纵向滚动，链接位于后续正文。
- 顶部主动建议气泡会遮住部分聊天内容；这是 UI 遗留，不属于 Search Runtime 成功。

## 5. 性能数据

中文天气完整 `/api/chat`：

- 总耗时：16,860 ms
- 上下文检索：1,228 ms
- Web Search：1,226 ms
- 模型：15,448 ms
- 持久化：62 ms

Qwen GitHub Release 完整 `/api/chat`（第二轮）：

- 总耗时：27,179 ms
- 上下文检索：120 ms
- Web Search：117 ms
- 模型：26,857 ms
- 持久化：60 ms

结论：检索本身约 0.1-1.5 秒，当前主要延迟来自 Qwen 回答生成，而不是 Bocha 搜索。搜索正确性和回答时延需要分开治理。

## 6. 自动化验证

- Web Search Runtime 测试：128 passed。
- Web Search、路由、上下文、求职 Pipeline、Artifact/OpenCode 组合回归：474 passed。
- 新增测试均先验证旧实现失败，再实现修复。

## 7. 仍存在的真实 Gap

1. 只有 Bocha 配置了 Key，Exa/Tavily 多 Provider 路由与交叉验证尚未做真实线上验收。
2. “过去 24 小时最重要新闻”的重要性排序仍偏噪；freshness 正确，但缺少事件聚类、跨来源复现度和语义 reranker。
3. Provider 原始结果仍可能包含“主题相关但意图不完全一致”的页面；本轮 n-gram 与标题加权已改善，尚未达到语义重排效果。
4. 英文地点查询遇到中文官方页面时，缺少地点跨语言实体对齐，因此会保守降级为 partial。
5. `/api/chat` 响应未完整暴露内部 `citation_validation` / model trace，线上排障还需要查数据库。
6. Android 真机已确认最终 `chat_done` 会把原始引用标记替换为可点击链接，但流式中间态曾短暂显示 `websrc_*`；正式 UI 仍应延迟展示未校验的引用片段或在客户端隐藏该标记。
7. 模型生成占总耗时主要部分；Search Runtime 优化不能解决 15 秒级生成延迟。
8. 真机主动建议气泡会遮挡聊天区域，需要独立 UI 修复。

## 8. 当前结论

Web Search 的路由、隐私、检索、来源门禁、引用和 Agent 工具链已在真实环境跑通；天气问题不是一个孤立补丁。本轮同时修复了会影响所有中文查询和动态事实查询的底层错误。

系统仍不能宣称“所有搜索质量问题已解决”：单 Provider、新闻重要性排序、跨语言实体对齐和流式中间态验证仍是明确遗留。
