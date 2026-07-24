# Bocha Web Search API 基准摘要

日期：2026-07-12
数据集：`fixtures/benchmark_queries.json`，40 条基础查询 × Quick/Balanced/Research，共 120 case。
Provider：Bocha Web Search API。测试 Key 仅保存在被 Git 忽略的本地 `.env`，未写入结果或源码。

## 总体结果

| 指标 | 结果 |
|---|---:|
| 完成率 | 100% |
| 非空结果率 | 100% |
| 预期/官方域名命中率 | 35% |
| MRR | 0.2315 |
| P50 | 1,105 ms |
| P95 | 1,710 ms |

Bocha 原始接口在并发 Research 查询时出现过 HTTP 429。适配器加入最小请求间隔和 Retry-After 重试后，全量基准没有遗留 Provider error。

## 分类结果

| 类别 | 预期域名命中率 |
|---|---:|
| open_source | 100% |
| fresh_news | 100% |
| china_research | 100% |
| research | 75% |
| china_authoritative | 50% |
| standards | 50% |
| authoritative | 33% |
| technical_docs | 25% |
| fresh_technical | 0% |
| jobs | 0% |
| law_policy | 0% |

## 质量判断

- 优点：延迟稳定、中文摘要完整，开源项目、新闻和论文发现表现可用。
- 问题：技术问题经常优先返回 CSDN、博客园、PHP 中文网、知乎等二手内容；最新版本、招聘平台和法规原文缺少官方来源。
- 结论：可以作为 Nomi 当前试用 Provider，也可以作为中文搜索 fallback；不能作为唯一生产 Provider，尤其不能单独承担求职 Pipeline 和高风险事实回答。

## 后续对照

使用完全相同的 120-case 数据集测试 Exa/Tavily。生产选型必须比较官方来源命中率、MRR、P95、费用和中文质量，而不是只看请求成功或结果非空。
