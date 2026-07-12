# Nomi Web Search Provider 设置与智能路由设计

日期：2026-07-12  
状态：设计已确认，尚未实现  
依赖：`2026-07-12-nomi-web-search-design.md`  
范围：单用户、单实例私有部署；Exa、Tavily、博查的密钥设置、状态管理与智能路由

## 1. 目标

Nomi 部署在用户自己的 PC 或私有云服务器上。实例所有者可以在完整 App 的设置页中配置 Exa、Tavily、博查任意一个或多个 Web Search Provider，并立即生效。

必须满足：

1. 只配置一个 Provider 时，所有需要公开 Web Search 的请求均使用它。
2. 配置多个 Provider 时，根据查询类型选择首选 Provider，并在失败时自动降级。
3. API Key 只提交给私有实例服务端，加密存储，不进入客户端持久化、日志、trace 或 Git。
4. 客户端只能看到是否配置、配置来源和末四位，不能回读完整 Key。
5. 新 Key 必须先真实验证，验证成功后才覆盖旧 Key。
6. 修改后无需重启 Docker，Chat、WebSocket、Pipeline 和 OpenCode 在下一次请求时使用新配置。
7. Web 完整 App 与 Android 真机复用同一服务端设置页和状态，不维护两份配置逻辑。

## 2. 非目标

- 不增加多用户、租户、角色或成员权限体系。
- 不把 Key 存入 Android SharedPreferences、浏览器 localStorage 或客户端数据库。
- 不允许前端读取、导出或复制已保存的完整 Key。
- 不在 V1 开放用户自定义每一种查询类型的复杂路由矩阵。
- 不用设置页修改宿主机 `.env` 或重启 Docker。
- 不把 Agent Search API 作为 Web Search Provider；博查只接 Web Search API。

## 3. 已确认产品决策

### 3.1 实例级配置

Nomi 永远定位为单用户私有实例。Provider 配置与实例访问密码绑定，不引入 `user_id` 或 tenant 维度。

### 3.2 设置页采用方案 B

完整 App 的“设置”增加“Web Search”入口。Web Search 首页使用紧凑列表：

- Exa：技术文档、研究、开源项目。
- Tavily：新闻、时效信息。
- 博查：中文资讯、通用搜索。

每行展示 Provider 名称、能力说明、状态和进入箭头。点击后进入二级编辑页。

二级页展示：

- 脱敏 Key，例如 `••••••••91K2`。
- 启用/禁用开关。
- 最近一次真实测试的状态、耗时和时间。
- “测试连接”“更换 Key”“删除 Key”。
- 配置来源：数据库、环境变量或未配置。

### 3.3 智能路由

- 只有一个可用 Provider：所有搜索直接使用它，不调用分类路由。
- 两个或三个可用 Provider：按查询类型选择首选与备选。
- 用户可以启用/禁用 Provider，并调整通用 fallback 顺序。
- 分类矩阵由 Nomi 内置策略管理，V1 不要求用户编辑。

## 4. 数据模型

新增表 `web_search_provider_configs`：

```sql
CREATE TABLE IF NOT EXISTS web_search_provider_configs (
  provider TEXT PRIMARY KEY,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  priority INTEGER NOT NULL DEFAULT 100,
  encrypted_api_key JSONB NOT NULL DEFAULT '{}'::jsonb,
  key_hint TEXT NOT NULL DEFAULT '',
  connection_status TEXT NOT NULL DEFAULT 'not_configured',
  last_tested_at TIMESTAMPTZ,
  last_test_latency_ms INTEGER,
  last_error_type TEXT NOT NULL DEFAULT '',
  last_error_message TEXT NOT NULL DEFAULT '',
  settings JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (provider IN ('exa', 'tavily', 'bocha')),
  CHECK (connection_status IN ('not_configured', 'untested', 'healthy', 'invalid_key', 'rate_limited', 'timeout', 'provider_error'))
);
```

路由通用设置存为保留记录 `web_search_routing_config`，不与 Key 表混用：

```sql
CREATE TABLE IF NOT EXISTS web_search_routing_config (
  id TEXT PRIMARY KEY CHECK (id = 'instance'),
  fallback_order TEXT[] NOT NULL DEFAULT ARRAY['exa', 'tavily', 'bocha']::TEXT[],
  strategy TEXT NOT NULL DEFAULT 'smart',
  config_version BIGINT NOT NULL DEFAULT 1,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (strategy IN ('smart', 'fixed'))
);
```

`strategy='smart'` 是 V1 默认。`fixed` 仅作为故障排查或高级设置保留，不在初版 UI 主路径展示。

## 5. 密钥安全

### 5.1 加密

新增独立的 `web_search_config_fernet()`，密钥来源优先级：

1. `WEB_SEARCH_CONFIG_ENCRYPTION_SECRET`
2. `RAW_DATA_ENCRYPTION_KEY`
3. `APP_PASSWORD`
4. 仅开发环境的显式默认值

派生时加入 `nomi:web-search-provider-key:v1` 域分离字符串，不能直接复用模型 Key 的密文域。

加密信封格式：

```json
{
  "version": 1,
  "algorithm": "fernet",
  "ciphertext": "..."
}
```

### 5.2 返回与日志

- API 只返回 `configured=true/false`、`key_hint` 和 `config_source`。
- `key_hint` 最多四个字符，不足四位时全部隐藏。
- 请求体、异常、Provider header 和密文不得写入普通日志或 trace。
- 错误消息经过清洗，移除 Authorization header、Bearer token 和疑似 Key。
- Provider 状态接口继续禁止返回任何 credential。

### 5.3 环境变量兼容

有效 Key 的解析顺序：

1. 数据库中存在可解密的 Provider Key：使用数据库配置。
2. 数据库没有 Key：回退到对应环境变量。
3. 两者都没有：Provider 未配置。

环境变量对应关系：

- Exa：`EXA_API_KEY`
- Tavily：`TAVILY_API_KEY`
- 博查：`BOCHA_API_KEY`

删除数据库 Key 后，如果环境变量仍存在，状态返回 `config_source=environment`，UI 显示“已回退到环境变量配置”。前端不能删除环境变量。

## 6. API 设计

所有接口必须通过 `x-par-password` 实例认证。

### 6.1 获取设置

`GET /api/web-search/settings`

```json
{
  "strategy": "smart",
  "fallback_order": ["exa", "tavily", "bocha"],
  "config_version": 4,
  "providers": [
    {
      "provider": "exa",
      "enabled": true,
      "configured": true,
      "config_source": "database",
      "key_hint": "91K2",
      "connection_status": "healthy",
      "last_tested_at": "2026-07-12T08:42:00Z",
      "last_test_latency_ms": 482,
      "last_error_type": ""
    }
  ]
}
```

`config_source` 只能是 `database`、`environment`、`none`。

### 6.2 保存新 Key

`PUT /api/web-search/settings/{provider}`

```json
{
  "api_key": "candidate-key",
  "enabled": true
}
```

服务端流程：

1. 校验 Provider slug 和 Key 基础格式。
2. 使用候选 Key 创建临时 Provider。
3. 执行固定轻量测试查询；测试请求不得经过生产缓存。
4. 成功或“连接成功但无结果”后，在一个事务中加密写入 Key、状态和耗时。
5. 鉴权失败、超时或 Provider 错误时不覆盖旧 Key。
6. 成功后递增配置版本并使运行时配置缓存失效。

成功响应不包含 Key：

```json
{
  "provider": "exa",
  "saved": true,
  "configured": true,
  "key_hint": "91K2",
  "connection_status": "healthy",
  "latency_ms": 482,
  "config_version": 5
}
```

### 6.3 测试已保存配置

`POST /api/web-search/settings/{provider}/test`

- 使用数据库 Key；没有数据库 Key 时使用环境变量 Key。
- 更新最近测试状态、耗时和错误，但不改变 Key。
- 空结果表示连接可用，状态可以是 `healthy`，响应附带 `result_count=0`。

### 6.4 启用或禁用

`PATCH /api/web-search/settings/{provider}`

```json
{"enabled": false}
```

- 禁用不删除 Key。
- 没有有效 Key 时不能启用，返回 409 `provider_not_configured`。

### 6.5 路由设置

`PATCH /api/web-search/settings/routing`

```json
{
  "strategy": "smart",
  "fallback_order": ["tavily", "exa", "bocha"]
}
```

- 数组必须恰好包含三个支持的 Provider，不能重复。
- 顺序只决定通用降级；智能路由首选仍由查询类型决定。

### 6.6 删除数据库 Key

`DELETE /api/web-search/settings/{provider}/key`

- 删除密文、key hint 和数据库测试状态。
- 保留 enabled 设置。
- 如果环境变量存在，响应显示回退后的环境变量状态。
- 如果没有环境变量，Provider 变为 `not_configured`，并自动从可用路由集合移除。

## 7. Provider 连接测试

连接测试查询必须固定、公开、低敏感且可返回结果，不能包含任何用户私有上下文：

```text
Nomi web search provider connectivity test official documentation
```

不同 Provider 使用相同语义查询，限制一条结果。测试只验证：

- 能否鉴权。
- 能否完成请求。
- 是否触发限流。
- 响应结构是否可解析。

测试不代表搜索质量合格。搜索质量继续由 120-case benchmark 判断。

## 8. 智能路由

### 8.1 查询分类

路由输入使用现有 Chat route、Pipeline ID 和显式请求字段，不重新读取私有数据。分类枚举：

- `technical_docs`
- `research`
- `open_source`
- `fresh_news`
- `current_general`
- `china_general`
- `jobs_company`
- `high_stakes_facts`
- `unknown`

### 8.2 默认矩阵

| 分类 | 首选 | 默认备选 |
|---|---|---|
| technical_docs / research / open_source | Exa | Tavily、博查 |
| fresh_news / current_general | Tavily | 博查、Exa |
| china_general | 博查 | Tavily、Exa |
| jobs_company | Exa、Tavily | 博查仅补充 |
| high_stakes_facts | Exa + Tavily 并行 | 博查补充多样性 |
| unknown | fallback_order 第一项 | 其余顺序降级 |

只在已启用、已配置且没有 `invalid_key` 状态的 Provider 中选取。

### 8.3 单 Provider

当可用 Provider 数量为一时：

- 跳过分类到 Provider 的选择。
- 所有 Web Search 请求使用该 Provider。
- 仍保留现有 query 脱敏、SSRF、引用、缓存和预算控制。

### 8.4 多 Provider 与降级

- Quick 默认单 Provider；失败后串行降级。
- Balanced 可调用一个首选和一个备选，是否并行由查询风险和预算决定。
- Research 可以并行调用最多两个 Provider，子查询仍受总预算约束。
- 高风险事实至少需要两个独立来源；只有一个 Provider 时明确标注“未完成跨 Provider 交叉验证”。
- 失败条件：超时、429 超出重试、鉴权失败、空结果、所有结果被域名规则过滤。

### 8.5 Trace

每次搜索记录：

- `route_category`
- `configured_providers`
- `eligible_providers`
- `selected_providers`
- `selection_reason`
- `fallback_events`
- 每个 Provider 的耗时、结果数和错误类型

不得记录 Key、密文、Authorization header 或完整设置请求。

## 9. 动态生效

新增 `WebSearchRuntimeManager`：

1. 保存当前 `config_version` 与 `WebSearchService`。
2. 每次搜索前读取 Redis 中的 `nomi:web-search:config-version`。
3. 版本未变化时复用 Provider 实例、连接池和限流器。
4. 版本变化时从数据库与环境变量重新解析配置并原子替换 Service。
5. Redis 不可用时，以短 TTL 从数据库检查版本，不能永久使用旧配置。

配置更新事务成功后：

- 更新数据库 `config_version`。
- 写 Redis 版本键。
- 当前进程立即 reset。

这样支持单进程和未来可能的多 worker，同时保留博查 Provider 的进程内限流状态。

## 10. UI 交互

### 10.1 设置入口

完整 App 设置面板增加“Web Search”菜单项，与账号连接、求职看板同级。Android 通过完整 App WebView 使用同一页面，不在悬浮窗中增加 Key 输入。

### 10.2 紧凑列表页

顶部显示：

- 智能路由状态。
- 可用 Provider 数量。
- “只配置一个时全部使用它；多个时智能选择”的简短说明。

Provider 状态：

- `可用`：最近测试成功。
- `未测试`：已配置但未验证。
- `异常`：鉴权、超时、限流或 Provider 错误。
- `未配置`：数据库和环境变量都没有 Key。
- `已禁用`：Key 存在但不参与路由。

### 10.3 二级编辑页

- 未配置：密码输入框 + “保存并测试”。
- 数据库配置：脱敏 hint + “测试连接”“更换 Key”“删除 Key”。
- 环境变量配置：脱敏 hint + “测试连接”“使用新 Key 覆盖”；说明环境变量不能从 UI 删除。
- 保存或测试期间禁用重复点击并显示明确进度。
- Key 输入使用密码类型，允许临时显示/隐藏本次输入，但离开页面立即清空。

## 11. 错误契约

| 场景 | HTTP | error code | 是否覆盖旧 Key |
|---|---:|---|---|
| Provider 不支持 | 404 | `unsupported_web_search_provider` | 否 |
| Key 格式为空 | 422 | `api_key_required` | 否 |
| 鉴权失败 | 422 | `provider_auth_failed` | 否 |
| 连接超时 | 503 | `provider_test_timeout` | 否 |
| 限流 | 429 | `provider_rate_limited` | 否 |
| 返回结构错误 | 502 | `provider_invalid_response` | 否 |
| 数据库写入失败 | 500 | `provider_config_save_failed` | 否 |
| 加密/解密失败 | 500 | `provider_secret_error` | 否 |
| 启用未配置 Provider | 409 | `provider_not_configured` | 不适用 |

错误响应不包含候选 Key 或 Provider 原始响应体。

## 12. 测试设计

### 12.1 加密与持久化

- 明文加密后数据库只出现密文。
- 正确 secret 可解密，错误 secret 失败且不返回明文。
- API 列表只返回末四位。
- 候选 Key 测试失败时旧密文完全不变。
- 删除数据库 Key 后正确回退环境变量。

### 12.2 Provider 配置 API

- Exa、Tavily、博查分别保存、测试、禁用、启用、替换、删除。
- 不支持的 slug、空 Key、错误 Key、429、timeout、空结果、异常结构。
- 未授权请求返回 401。
- 响应、日志和 trace 不含明文或密文。

### 12.3 路由

- 只配置 Exa、只配置 Tavily、只配置博查时全部走唯一 Provider。
- 三个均配置时覆盖九种分类矩阵。
- 首选失败后 fallback 顺序正确。
- 高风险查询并行两个 Provider；单 Provider 时返回验证不足标记。
- 禁用、无 Key、invalid_key 的 Provider 不参与路由。

### 12.4 动态配置

- 保存后下一次搜索使用新 Provider，无需重启。
- 多个 runtime manager 看到 Redis 版本变化后重建。
- Redis 不可用时数据库 TTL 检查仍能更新。
- 并发搜索期间替换配置不破坏正在执行的旧请求。

### 12.5 UI

- Web 桌面和 Android 真机均能从设置进入 Web Search。
- 紧凑列表和二级页状态一致。
- 密码键盘正常弹出，输入框不被遮挡。
- 保存失败有明确原因，不出现静默失败或错误成功提示。
- 页面旋转、重载和返回后不保留输入中的明文 Key。

### 12.6 真实环境

1. 三个 Provider 分别单独配置并执行真实查询。
2. 三个 Provider 同时配置，验证技术、新闻、中文、求职、高风险五类路由。
3. 主动让首选 Provider 失败，验证降级和 trace。
4. 云服务器部署后通过 Android 真机完成设置、查询、引用点击和重启后持久化。
5. 对代码、Git、容器日志、数据库普通列和 Android logcat 扫描明文 Key。

## 13. 验收标准

- 任一单 Provider 配置均可独立支持完整 Web Search。
- 多 Provider 智能路由符合矩阵，降级原因可追踪。
- 无有效 Provider 时明确引导进入设置，不生成伪实时答案。
- 保存错误 Key 不破坏旧配置。
- Key 不在任何客户端存储、API 响应、日志、trace 或 Git 中出现。
- 配置修改在下一次请求生效，不重启容器。
- Web 与 Android 真机 UI 无白屏、遮挡、卡死和状态不同步。
- 单元、API、路由、静态 UI 和真实 Provider 回归均通过后才能标记完成。

## 14. 实现边界

主要落点：

```text
runtime_api/app/web_search/config.py
runtime_api/app/web_search/router.py
runtime_api/app/web_search/runtime.py
runtime_api/app/web_search/providers/{exa,tavily,bocha}.py
runtime_api/app/main.py
runtime_api/app/static/index.html
runtime_api/app/static/app.js
runtime_api/app/static/styles.css
runtime_api/tests/test_web_search_settings.py
runtime_api/tests/test_web_search_runtime.py
runtime_api/tests/test_static_web_search_settings.py
db/init.sql
```

Android 不新增原生 Key 配置代码，只验证 `WebWorkspaceActivity` 加载的完整 App 设置页行为。

## 15. 已知后续工作

- Exa/Tavily 仍需要真实测试 Key 才能完成三 Provider 联合验收。
- 120-case benchmark 负责搜索质量，不与连接测试混为一谈。
- Claim semantic entailment、动态网页 fetch fallback 和 DNS rebinding hardening 仍按 Web Search 主设计的 gap 继续跟踪。
