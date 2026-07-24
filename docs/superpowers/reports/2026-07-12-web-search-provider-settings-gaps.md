# Web Search Provider 设置实现与 Gap 报告

日期：2026-07-13
对应设计：`docs/superpowers/specs/2026-07-12-web-search-provider-settings-design.md`
对应计划：`docs/superpowers/plans/2026-07-12-web-search-provider-settings-implementation.md`

## 1. 结论

Exa、Tavily、博查的单实例配置、加密存储、连接测试、动态生效、智能路由和完整 App 设置 UI 已落到代码。本地自动化回归与真实博查直连已通过，但当前不能标记为“全部真实环境验收完成”：本机没有 Exa/Tavily 真实 Key，因此真实多 Provider 路由与故障切换未验收；本轮也未部署云服务器或使用 Android 真机验收设置页。

准确状态：**核心实现完成；真实博查可用；真实多 Provider、云端和真机验收阻塞。**

## 2. 需求逐项状态

| 需求 | 状态 | 实际证据 |
|---|---|---|
| 任配一个 Provider 时全部搜索使用它 | 已完成，博查真实验证 | 单 Provider 路由单测覆盖 Exa/Tavily/博查；真实博查搜索选中项仅为 `bocha` |
| 多 Provider 按类别智能选择并自动降级 | 代码完成，真实联合验收阻塞 | 九类分类、固定顺序、串行 fallback、高风险并行测试通过；缺 Exa/Tavily 真实 Key |
| Key 服务端加密存储 | 已完成 | Fernet 独立派生域、数据库信封、错误 secret 测试通过 |
| 客户端只看到状态、来源、末四位 | 已完成 | API redaction 与静态 UI 合约测试通过；不返回密文或明文 |
| 新 Key 先真实测试再覆盖旧 Key | 已完成 | 候选失败不写库、异常响应不覆盖、旧 Key 保留测试通过 |
| 修改后无需重启 | 已完成，本地自动化验证 | config version、Redis 失效、DB 短 TTL fallback、运行时原子替换测试通过 |
| Web 与 Android 复用同一设置页 | 代码完成，真机阻塞 | Android 未增加本地 Key 存储；WebView 复用完整 App；本轮未做真机实测 |
| Provider 结果审计 | 已完成 | trace 含类别、选中顺序、fallback、每次 Provider 耗时、结果数与错误类型 |

## 3. 已完成实现

### 3.1 配置与安全

- `web_search_provider_configs` 保存实例级 Provider 状态与 Fernet 密文。
- `web_search_routing_config` 保存策略、fallback 顺序和配置版本。
- 数据库 Key 优先于环境变量；删除数据库 Key 后自动回退环境变量。
- API 只输出 `configured`、`config_source`、`key_hint` 和健康状态。
- 候选 Key、Authorization、Provider 原始响应和密文不进入搜索 trace。
- Provider 标准错误归一化为鉴权、限流、超时和 Provider 错误。
- 非标准或异常响应归一化为 `provider_invalid_response`，并显式清除候选 Key。
- 搜索响应与持久化只保留受控错误类型和固定消息，不保存第三方异常原文。
- 超长或类型错误的候选 Key 在 endpoint 内校验，避免 FastAPI/Pydantic 回显敏感输入。
- 固定 `par-dev` 和空 secret 不再允许加密 Provider Key；必须配置独立 secret、原始数据密钥或非默认实例密码。

### 3.2 设置 API

- `GET /api/web-search/settings`
- `PUT /api/web-search/settings/{provider}`
- `POST /api/web-search/settings/{provider}/test`
- `PATCH /api/web-search/settings/{provider}`
- `PATCH /api/web-search/settings/routing`
- `DELETE /api/web-search/settings/{provider}/key`

所有接口要求实例密码。保存采用“测试候选 -> 加密写入 -> 版本递增 -> 运行时失效”的顺序；测试失败不会覆盖旧 Key。

### 3.3 智能路由与动态运行时

- 支持 `technical_docs`、`research`、`open_source`、`fresh_news`、`current_general`、`china_general`、`jobs_company`、`high_stakes_facts`、`unknown` 九类。
- 单 Provider 跳过 Provider 选择并处理全部公开搜索。
- 普通查询按首选顺序串行降级；首选结果被域名策略全部过滤时继续调用备用 Provider。
- 高风险事实并行检索独立 Provider；只有至少两个 Provider 返回可用来源才标记交叉验证完成，否则搜索状态为 `partial`。
- 只有一个 Provider 时，高风险查询输出 `single_provider_cross_verification_unavailable`。
- Redis 正常时按版本重用 Provider，同时每 2 秒用数据库版本校准；即使 Redis 写入失败并保留旧值，也不会永久使用旧配置。
- 配置变化创建新 Service，已经取得旧 Service 引用的执行中请求不被破坏。
- cache key 含配置版本和显式路由类别，避免切换 Provider 或 Pipeline 路由后读到错误缓存。

### 3.4 设置 UI

- 完整 App 设置页采用紧凑 Provider 列表与二级详情页。
- 支持保存并测试、测试已保存配置、启用/禁用、删除数据库 Key、路由顺序。
- 展示可用 Provider 数量、来源、末四位、最近测试时间和耗时。
- Key 输入仅允许临时显示，返回、页面隐藏、切换视图时立即清空。
- Web Search Key 不写入 `localStorage` 或 `sessionStorage`。
- 已做 412 x 915 移动视口视觉检查，未发现横向溢出；这不等于 Android 真机验收。

## 4. 自动化验证证据

### 4.1 全量回归

```text
python3 -m pytest -q runtime_api/tests
894 passed in 4.84s
```

### 4.2 聚焦回归

```text
Web Search/API/Settings/静态 UI：148 passed
新增覆盖：候选 Key 回显、异常泄漏、弱默认密钥、交叉验证不足、过滤后 fallback、路由缓存隔离、陈旧 Redis、环境 Key 错误状态、malformed 响应和 UI 失败刷新
```

### 4.3 静态与构建检查

以下命令退出码均为 0：

```text
python3 -m compileall -q runtime_api/app runtime_api/scripts
node --check runtime_api/app/static/app.js
docker compose config --quiet
git diff --check
```

### 4.4 明文泄漏扫描

- 扫描 433 个 Git 可提交文件。
- 当前只检测到本地 `.env` 配置博查真实 Key。
- 该博查 Key 在可提交文件中的明文命中数为 0。
- Web Search UI 代码中未发现 Key 与浏览器持久化 API 的组合使用。

### 4.5 独立代码审查

独立只读审查最初发现候选 Key 回显、Provider 异常泄漏、弱默认密钥、交叉验证误标、过滤后不 fallback、路由缓存串用、Redis 陈旧版本、环境 Key 错误状态、异常响应误判和 UI 状态滞后等问题。以上问题均补充了失败测试并修复。

第三轮复核确认第二轮遗留的非对象请求体、Redis 高版本锁死、设置错误正文、Provider 内部结构校验和旧密文 rekey 已关闭；当前未发现仍存的高/中严重级代码问题。该结论只覆盖代码与本地自动化，不替代 Exa/Tavily、云端多进程和 Android 真机验收。

## 5. 真实 Provider 证据

### 5.1 博查

2026-07-13 真实直连复验：

```json
{
  "connection_status": "healthy",
  "connection_latency_ms": 380,
  "connection_result_count": 1,
  "search_status": "completed",
  "route_category": "technical_docs",
  "selected_providers": ["bocha"],
  "provider_latency_ms": 293,
  "source_count": 3,
  "official_domain_hit": true
}
```

查询结果包含 `open.bochaai.com`、阿里云和 CSDN，说明该样例的 Provider 选择、真实请求、标准化、排序和审计 trace 均实际工作。此证据只证明该样例，不代表所有类别质量达标。

此前 120-case 博查真实 benchmark：完成率 100%，非空率 100%，预期官方域名命中率 35%，MRR 0.2315，P50 1105ms，P95 1710ms。开源与新闻较好，职位、法规原文和部分技术文档较弱。因此博查可作为中文/通用试用 Provider，但不应据此宣称它能单独覆盖全部生产检索。

### 5.2 Exa

状态：**阻塞**。当前 `.env` 没有真实 `EXA_API_KEY`，只完成 adapter、API、路由与错误路径自动化测试。

### 5.3 Tavily

状态：**阻塞**。当前 `.env` 没有真实 `TAVILY_API_KEY`，只完成 adapter、API、路由与错误路径自动化测试。

### 5.4 多 Provider

状态：**阻塞**。至少需要两个真实 Provider Key，才能验证真实技术、新闻、中文、求职、高风险路由，以及人为制造首选失败后的真实 fallback。

## 6. 遗留 Gap

### G01 真实 Exa/Tavily 与多 Provider 路由未验收

影响：路由矩阵目前有确定性的代码和自动化证据，但没有真实服务质量、限流和故障切换证据。

解除条件：配置 Exa、Tavily 真实 Key，分别单 Provider 查询，再进行五类多 Provider 查询和一次真实故障注入。

### G02 云服务器部署未验收

影响：不能证明数据库密文、Redis 版本传播、容器重启后持久化和线上日志脱敏均正确。

解除条件：部署本次代码，在云端完成保存、重测、禁用、删除回退、重启后状态保持，并扫描容器日志和数据库普通列。

### G03 Android 真机设置页未验收

影响：412 x 915 浏览器视口正常不等于真机键盘、WebView 返回、旋转和输入清理正常。

解除条件：真机完成进入设置、配置测试 Key、保存失败提示、返回清空、重载、旋转和引用点击。

### G04 博查搜索质量不稳定

影响：连接健康和结果非空不能代表证据权威。只配博查时，技术、职位和法规类查询可能缺少官方来源。

建议：配置 Exa/Tavily 后按类别比较同一 benchmark；以官方域名命中、MRR、引用支持度和 P95 决定路由，不以非空率决定。

### G05 部署前必须配置安全的加密 secret

当前本地 `.env` 没有 `WEB_SEARCH_CONFIG_ENCRYPTION_SECRET`、`RAW_DATA_ENCRYPTION_KEY` 或非默认 `APP_PASSWORD`。环境变量中的博查 Key 可继续直接搜索，但通过设置 UI 保存数据库 Key 会返回 `provider_secret_error`，防止使用可推导的固定密钥。

解除条件：执行 `openssl rand -hex 32`，把结果配置到私有实例的 `WEB_SEARCH_CONFIG_ENCRYPTION_SECRET` 后重新部署。启动时会识别旧 `par-dev` 和固定开发密钥生成的信封，并在安全 secret 可用后立即 rekey；无法识别的历史密文才需要重新输入 Provider Key。系统不会继续用弱密钥处理新配置。

### G06 主 Web Search 设计的安全与质量 Gap 仍存在

- 引用可追溯，但尚无独立 semantic entailment verifier。
- JavaScript 动态页面没有完整 Fetch fallback。
- DNS 检查与实际连接之间仍有 rebinding 时间差。
- Android 没有独立来源卡片与真机排版证据。
- Research query decomposition 和 coverage checker 仍较基础。

这些不属于 Provider 设置功能本身，但会影响 Web Search 整体生产质量，继续由 `2026-07-12-nomi-web-search-implementation-gaps.md` 跟踪。

## 7. 下一步真实验收顺序

1. 在设置页配置 Exa 或 Tavily 的真实 Key，并确认候选测试失败不会替换博查配置。
2. 三个 Provider 分别运行单 Provider 真实查询。
3. 技术、新闻、中文、求职、高风险五类各运行至少一条多 Provider 查询，检查 `provider_outcomes`。
4. 临时使用错误 Key 或超时注入，核对 fallback 顺序和用户可见提示。
5. 部署云服务器并验证重启持久化、Redis 版本传播和日志泄漏。
6. Android 真机验证设置 UI、键盘、返回清理、引用链接和错误态。

在 G01-G03 解除前，禁止将该功能描述为“真实多 Provider 与真机全部验收通过”。
