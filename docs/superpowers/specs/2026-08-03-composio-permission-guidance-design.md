# Composio 权限错误提示与配置引导设计

**日期：** 2026-08-03
**状态：** 待用户复核

## 背景

Nomi 的账号连接页已能识别 `COMPOSIO_API_KEY` 是否存在，但点击 Gmail 等账号的“连接”按钮时，Composio SDK 的权限异常未被后端捕获。当前受限 Key 对 `Sessions` 只有读取权限，创建授权会话时 Composio 返回 `403 APIKey_InsufficientPermissions`，该异常最终被暴露为无结构的 `500 Internal Server Error`。前端随后丢弃异常详情，只把按钮文本改为“生成失败”。

这会让用户误以为服务未配置或系统随机故障，也没有可执行的修复入口。

## 目标

- 将 Composio 权限异常安全地转换为结构化 API 错误。
- 在账号连接面板内展示明确、可持续查看的中文提示。
- 提供在外部浏览器中打开 Composio Dashboard API Key 设置页的引导按钮。
- 保留重试入口，并确保正常授权链路和其他账号卡片不受影响。
- 不向客户端、日志或页面泄露 API Key、认证头或 SDK 请求体中的秘密。

## 非目标

- 不自动修改或创建用户的 Composio API Key。
- 不在 Nomi 内嵌 Composio Dashboard。
- 不为所有第三方服务建立通用诊断中心。
- 不改变 Composio 会话、授权回调或账号持久化模型。

## 方案

### 后端错误映射

账号连接端点在创建或复用 Composio Session、生成授权链接时捕获提供方异常，并通过一个小型纯函数完成安全分类。

当异常满足以下任一证据时，映射为权限错误：

- HTTP 状态为 `403` 且提供方错误 slug 为 `APIKey_InsufficientPermissions`；
- 提供方响应明确包含缺少某权限区域的访问级别。

返回 `403`，响应 `detail` 至少包含：

- `code: "composio_api_key_insufficient_permissions"`
- `message`: 面向用户的中文说明
- `provider: "composio"`
- `required_permissions`: 当前操作所需权限，例如 `[{"area":"sessions","access":"read_and_write"}]`
- `settings_url`: Composio Dashboard 的安全 HTTPS 地址
- `retryable: false`

提供方 request id 可以作为脱敏诊断字段返回；原始 API Key、请求认证头和完整 SDK 异常文本不得返回。

其他 Composio 提供方错误也应转换成结构化的 `502` 或 `503`，给出稳定错误码和可读说明，避免继续返回纯文本 500，但不将所有错误误报为权限不足。

### 前端交互

账号连接面板维护一个面板级错误状态。用户点击任意账号的“连接”后：

1. 按钮显示“生成链接...”。
2. 成功时按现有行为打开 Composio Connect Link。
3. 权限不足时恢复按钮状态，并在账号网格下方显示内联错误卡片：
   - 标题：`Composio API Key 权限不足`
   - 说明：`当前 Key 无法创建授权会话。请创建具备 Sessions 读写权限的 Key，并更新 Nomi 配置。`
   - 主操作：`打开 Composio API Key 设置`
   - 次操作：`重试`
4. 主操作通过 `window.open(url, "_blank", "noopener,noreferrer")` 在外部浏览器或新标签页打开 Dashboard，不替换 Nomi 当前页面。
5. 用户再次点击连接或重试时清除旧错误并发起新请求。

普通网络、超时或上游故障复用同一个内联错误容器，但展示对应说明与“重试”，不显示权限设置按钮。

### 通用 API 错误对象

前端 `api()` 在非成功响应时优先解析 JSON，将 `detail.code`、`detail.message`、`detail.settings_url`、`detail.required_permissions` 和 HTTP 状态保存到一个可识别的错误对象。对于纯文本或 HTML 响应，保留安全的通用回退文案。

该变化应向后兼容现有只读取 `error.message` 的调用方。

## 数据流

1. 浏览器请求 `POST /api/integrations/composio/connect/{toolkit}`。
2. Nomi 调用 Composio Session 创建或授权接口。
3. Composio 返回权限不足异常。
4. 后端分类并返回结构化 `403`，不泄露秘密。
5. 前端 `api()` 构造结构化错误对象。
6. Composio 面板渲染权限说明、Dashboard 外部链接和重试入口。

## 测试策略

### 后端

- 先增加失败测试，模拟包含 `403`、`APIKey_InsufficientPermissions` 和 `sessions` 权限提示的 SDK 异常。
- 断言端点返回结构化 `403` 和稳定错误码。
- 断言响应序列化内容不包含测试 API Key、认证头或不必要的原始异常内容。
- 保留并运行现有授权成功、缺少 Key、回调 URL 和持久化测试。

### 前端

- 对 API 错误解析和 Composio 权限引导的纯逻辑增加 JavaScript 单元测试。
- 验证权限错误显示 Dashboard 操作，普通错误不显示该操作。
- 验证 Dashboard URL 仅接受预期的 HTTPS Composio 域名，异常 URL 使用内置安全回退地址。
- 验证成功连接仍打开返回的 Connect Link。

### 线上验证

- 使用当前受限 Key 请求 Gmail 连接端点，确认返回结构化 `403`。
- 在桌面浏览器和 Android 真机上确认页面显示中文权限说明，点击设置按钮从 Nomi 外部打开 Composio Dashboard。
- 使用具备正确权限的新 Key 后，确认 Gmail 连接端点返回真实 Connect Link。
- 复查 Nomi `/health`、容器健康状态和服务日志，确认无新增未捕获异常。

## 安全与兼容性

- Dashboard 地址使用固定的 Composio HTTPS 域名，不信任任意上游 URL。
- 页面只展示权限区域与访问级别，不展示 Key 本身。
- 后端保留原有成功响应结构，现有 Web、Android 和 iOS 成功路径无需迁移。
- Android 原生账号连接错误仍能从结构化响应中获得可读 `message`；Web 端额外提供内联跳转引导。
