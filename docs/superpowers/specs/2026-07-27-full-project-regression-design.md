# Nomi 全项目分层回归测试设计

**日期：** 2026-07-27

**状态：** 已由用户确认

**范围：** Web 工作台、私有云服务端、Android App 与 Android 真机、受控 Chromium/noVNC、已配置真实账号和外部执行
**明确排除：** iOS App、无法确认属于测试环境的真实职位投递目标

## 1. 目标

本轮工作同时完成两件事：

1. 根据当前仓库代码总结 Nomi 已实现的产品功能、架构边界和外部依赖。
2. 编写并实际执行一套分层发布回归，覆盖自动化测试、API、Web、Android 真机、受控浏览器、真实账号读写、持久化恢复与测试数据清理。

最终交付物包括：

- 当前项目功能总结；
- 可重复执行的详细回归测试用例；
- 每条用例的实际结果和证据；
- 缺陷与阻断项清单；
- 测试数据清理记录；
- `PASS`、`CONDITIONAL PASS`、`FAIL` 或 `BLOCKED` 发布结论。

## 2. 当前项目功能总结

### 2.1 产品定位

Nomi 是面向单用户私有部署的个人 AI 助理。系统把账号会话、私有事件、长期记忆、日程、附件、任务执行和外部工具尽量保留在用户自己的服务器中，通过 Web 工作台和 Android 常驻入口提供交互。

当前完整闭环是：

1. 用户在受控 Chromium 或第三方连接平台中登录账号。
2. 采集器把邮件、聊天、日历、网页焦点和搜索等内容转为私有事件。
3. Worker 完成脱敏、语义抽取、记忆写入、日程解析和主动建议判断。
4. 用户通过 Web 或 Android 对话、查看日程、搜索记忆、处理建议和执行任务。
5. 高频任务进入确定性 Pipeline，复杂任务进入 Long-tail Agent/OpenCode/OpenClaw。
6. 产物和外部动作经过证据、权限、确认、幂等和审计链路后交付。

### 2.2 用户入口

#### Web 工作台

Web 工作台提供：

- 密码登录；
- 对话、流式回复和历史恢复；
- 图片及文档附件上传、状态、重试、预览和原件下载；
- 日程管理；
- 求职助手；
- 设置中心；
- 任务进度、产物卡片和文件查看器；
- 实时主动建议和确认卡片。

主导航保持为：

- 对话；
- 日程；
- 求职；
- 设置。

设置中心集中管理八类能力：

- 主动建议；
- 个人搜索；
- 记忆治理；
- 采集状态；
- 账号连接；
- 助理身份；
- Web Search；
- 隐私管理。

设置中心支持旧哈希深链接、浏览器历史、标题区返回按钮和移动端横向可滚动导航。

#### Android App

Android 端提供：

- 服务器地址和访问密码配置；
- 悬浮球、贴边拖动和前台服务；
- 悬浮聊天面板和完整 Web 工作台；
- 对话流式输出和 HTTP 降级；
- 历史会话恢复；
- 主动消息气泡、未读角标、通知和聊天内卡片；
- 长按语音输入、麦克风权限申请和流式 ASR；
- 图片及文档附件选择、上传、进度、失败重试和跨界面历史；
- 内置原格式文件查看器和认证下载；
- 日程、求职和设置入口；
- 账号连接、助理身份和 Web Search 设置；
- 受控远程浏览器、远端文字输入和浏览器登录回跳。

#### 受控 Chromium/noVNC

服务器保持一个持久化 Chromium Profile，用于：

- 登录 Gmail、WhatsApp Web、Telegram Web、Google Calendar、LinkedIn 等网页；
- 保留 Cookie、Local Storage 和页面会话；
- 采集可见 DOM、页面 URL、标题、焦点、点击、滚动、输入和部分网络事件元信息；
- 执行账号登录和浏览器辅助任务。

Android noVNC 会把 1080×1920 远端画布缩放到当前 WebView，远端 Chromium 使用默认 125% 页面缩放。单指用于点击和拖动，双指用于远端页面滚动，移动端分辨率变化不依赖硬编码尺寸。

### 2.3 私有数据采集

当前采集来源包括：

- Gmail Web 可见内容；
- Gmail/Google 工具连接；
- WhatsApp Web 会话、可见历史和新增消息；
- Telegram Web 可见内容；
- Google Calendar 可见日程；
- LinkedIn 页面、职位和部分个人资料信号；
- 搜索页面和公开网页；
- Chrome bookmarks；
- 页面焦点和交互信号；
- Webhook、Composio 和助理身份入站事件。

采集器具备启用、暂停、健康状态、登录状态、采集状态和错误信息。网页采集依赖第三方页面结构和登录风控，不等同于官方全量 API。

### 2.4 私有事件、记忆和上下文

记忆是 Nomi 的核心链路，不是聊天接口的附属缓存。当前实现需要按“写入”和“调用”两条路径理解和验证。

#### 记忆写入路径

所有用户对话和采集事件先进入私有事件账本，再按事件价值进入后续层：

```text
Web/Android 对话、Gmail、WhatsApp、Telegram、Calendar、LinkedIn、附件
  -> events / assistant_turns
  -> Redis Stream
  -> Worker 语义抽取
  -> semantic_events
  -> facts / memory_states
  -> entities / relationships
  -> memory_vectors
  -> agenda_items / suggestions（符合条件时）
  -> memory_audit_log / trace
```

对话写入采用冷热分离：

- 每个用户/Nomi turn 立即持久化到 `events`、`assistant_turns` 和会话历史；
- 普通对话默认不在同步回答热路径里立即固化为长期事实；
- 普通对话累计 15 个完整用户/助理轮次后形成 dialogue batch；
- “请记住”、明确偏好、身份关系、长期目标和其他强信号立即进入记忆处理；
- Gmail 会议、LinkedIn JD、简历和附件等高价值来源可以直接进入后台处理；
- 附件记忆必须保留 attachment id、版本、页码/Sheet/单元格等安全 provenance；
- 重复平台 message id 或稳定 fingerprint 不得重复写入；
- 第一人称事实必须按消息 speaker 归属，不能把联系人说的“我”写成用户事实；
- 低价值页面噪音和遥测不得污染稳定事实和关系图谱。

写入结果分层保存：

- `events`：原始私有事件账本；
- `semantic_events`：语义分类、摘要、实体、重要性和来源；
- `facts` / `memory_states`：偏好、身份、项目、目标和当前状态；
- `entities` / `relationships`：人物、组织、职位、地点和关系；
- `memory_vectors`：带 provider 和 scope metadata 的语义检索向量；
- `assistant_conversations` / `assistant_turns`：会话和最近对话；
- `context_snapshots`：每次回答实际使用的上下文和 evidence ids；
- `agenda_items` / `agenda_item_versions`：日程当前状态和变更历史；
- `memory_audit_log`：写入、纠正、删除和治理审计。

#### 记忆调用路径

聊天请求先由 `route_chat_context` 和可选语义路由器判断需要哪些上下文层。当前主要召回层包括：

- 最近对话与 session search；
- 当前 Gmail/WhatsApp/Telegram/LinkedIn 来源上下文；
- KV/状态事实；
- 实体关系图谱；
- 向量/RAG 片段；
- 时间线；
- 活跃日程；
- 求职画像、简历、岗位和任务状态；
- 附件解析内容和 provenance。

`retrieve_context`、分层 fetcher 和 `build_context_pack` 对候选进行作用域过滤、去重、排序、截断和 token 预算控制，再把最终 evidence ids 写入 `context_snapshots`。稳定事实和关系问题应优先使用结构化事实或 active relationship；日程问题应以 `agenda_items` 当前状态为准；RAG 片段用于补充原文，不能覆盖已经纠正或取消的 canonical state。

必须验证以下调用边界：

- 同联系人、同会话信息可以召回；
- 不同联系人、不同会话和不同助理身份的私密信息不能错误泄露；
- 用户直接询问自己的记忆时可以使用更广的私有上下文；
- 给第三方起草回复时只能使用允许进入该目标作用域的信息；
- collector 断线时必须区分“没有记录”和“来源尚未同步”；
- 召回答案需要能追溯到事件、记忆、附件或日程证据；
- 纠正、删除、取消或新证据出现后，旧答案不能继续作为当前事实；
- 模型、向量或单层召回失败时必须诚实降级，不能捏造记忆。

#### 记忆治理路径

当前可验证入口包括：

- `/api/memory/status` 和 `/api/memory/embedding/probe`；
- `/api/memory`；
- `/api/memory/debug`；
- `/api/memory/governance`；
- `/api/memory/semantic/{memory_id}` 纠正；
- `/memory/delete`；
- `/search` 个人搜索；
- `/api/events/{event_id}/trace`；
- `/api/chat/conversations/{conversation_id}/trace`。

用户可以查看、纠正和删除部分记忆。回归必须验证变更同时影响后续召回、上下文快照和审计记录，而不是只改变治理页的一条展示数据。

### 2.5 对话、附件和文件

对话支持 HTTP 与 WebSocket 两条路径、流式增量、历史恢复和上下文包。

附件 V1 支持：

- PNG、JPG、JPEG、WEBP、GIF；
- PDF；
- DOCX；
- PPTX；
- XLSX、CSV；
- TXT、Markdown。

系统区分原件、衍生结果、解析状态、消息绑定和检索分块。支持纯附件消息、附件加指令、后续追问、失败重试、跨悬浮窗/完整 App 恢复、原格式预览和认证下载。旧版二进制 Office、压缩包、可执行文件、加密文档和危险未知格式应被明确拒绝。

### 2.6 日程和主动建议

系统可以从聊天、邮件和日历事件中识别：

- 精确约定；
- 模糊约定；
- 截止日期和待办；
- 改期；
- 取消；
- 缺失时间、地点或参与者。

日程使用版本记录保存创建、用户修正、改期和取消。主动建议基于事件重要性、冷却、去重和用户反馈生成，可通过 WebSocket、Android 气泡、通知或聊天内卡片展示。

### 2.7 个人搜索与公开 Web Search

个人搜索查询用户自己的记忆、事件和关系证据。

公开 Web Search 是独立能力，当前包含：

- Exa、Tavily、Bocha、Brave、SearXNG Provider 适配；
- Quick、Balanced、Research 三种模式；
- 并行子查询、结果归一化、去重和排序；
- 来源分层、引用链接和 claim-source 记录；
- 查询脱敏、凭证查询阻断、公开 URL 校验和响应限制；
- 内存/Redis 缓存和 Postgres 运行记录；
- Provider Key 加密存储、连接测试、启停、路由和动态生效；
- Chat、求职、开放任务和受控工具集成。

动态网页抓取、独立语义蕴含验证和 DNS rebinding 的完整消除仍属于需要关注的边界。

### 2.8 求职助手

求职能力包括：

- 职业画像；
- LinkedIn/公开 ATS 职位预览和列表解析；
- 职位发现；
- 岗位匹配评分；
- 简历导入和定制；
- Cover Letter、自我介绍和外联文案；
- 申请状态、阶段、下一步和 Offer 跟踪；
- 面试准备；
- 委托自动化 grant、manifest、额度、证据和挑战停止条件。

真实职位提交只允许在目标和授权可以确认时执行。本轮不会把普通真实职位当作测试目标。

### 2.9 助理身份、账号连接和外部动作

用户账号连接用于读取或操作用户授权的外部服务；助理身份用于配置 Nomi 自己的通信身份，两者必须保持独立。

当前助理身份主链路以 Gmail V1 为重点，包括：

- 持久化身份状态；
- Composio/provider 连接和真实健康检查；
- 本地凭证保险库或 provider 托管凭证；
- 入站邮件归一化、去重和作用域；
- 出站草稿、编辑、确认、发送、provider message id 和审计；
- 重启、过期、重连和失败恢复；
- 确定性 Pipeline 与开放式 Agent 统一经过服务端安全网关。

OpenCode 只能调用高层能力，不能取得原始凭证或绕过确认直接调用 provider send。Nomi 自有 WhatsApp 身份、批量营销和全双工电话不作为当前 Gmail V1 完成条件。

### 2.10 开放任务和产物生成

复杂任务由 Task Orchestrator 管理计划、步骤、checkpoint、重试、用户补充信息、证据和最终校验。

系统可以生成或交付：

- PPTX；
- DOCX；
- XLSX；
- Markdown；
- 图片及其他受支持产物。

任务会记录 task run、task step、artifact、evidence link 和 verification status。Web 和 Android 可以查看任务状态、打开产物、预览原文件和下载原件。

### 2.11 部署和基础设施

Docker Compose 部署包含：

- `runtime-api`；
- `worker`；
- `chromium-runtime`；
- `model-router`；
- `attachment-renderer`；
- `postgres`/pgvector；
- `redis`；
- `nginx`；
- 相关工具运行时和持久化卷。

Postgres、Redis、Chromium Profile、附件/产物和模型缓存需要跨容器重启保持。部署按单用户私有服务器设计，不以多租户和大规模并发为当前目标。

## 3. 回归范围

### 3.1 纳入范围

- 本地代码静态检查和自动化测试；
- Docker Compose 配置与服务健康；
- Runtime API、Worker、Chromium Runtime、Model Router；
- Web 工作台桌面和移动视口；
- Android 单元测试、APK 构建、升级安装和真机；
- 远程 Chromium/noVNC；
- Gmail、WhatsApp、Telegram、Calendar、LinkedIn 等当前可用真实账号；
- 真实测试联系人之间的外部消息、邮件和日历写入；
- 记忆、日程、附件、求职、Web Search、助理身份、任务产物；
- 容器重启和持久化恢复；
- 测试数据清理。

### 3.2 排除范围

- iOS 编译、单测、模拟器和真机；
- 无法确认属于测试环境的真实 ATS 职位提交；
- 向非测试联系人发送消息；
- 购买、付款、真实打车和其他产生费用或法律承诺的动作；
- 绕过验证码、2FA、平台风控或账号安全确认；
- 为通过测试而修改业务代码。

## 4. 执行架构

### 阶段 0：测试资产与证据目录

- 建立本轮 run id；
- 统一使用 `NOMI-REGRESSION-20260727` 作为外部可见标记；
- 记录设备、服务器、Git commit、容器镜像和账号状态；
- 建立证据、日志、截图、API 响应和清理清单目录。

### 阶段 1：环境基线

- Git 工作区和配置完整性；
- Docker Compose 解析；
- 服务、端口、反向代理和健康检查；
- Postgres schema、Redis、磁盘和持久化卷；
- 模型、嵌入、ASR、Web Search 和 Composio/provider 可用性；
- Android ADB 连接、系统版本、分辨率和已安装版本。

### 阶段 2：自动化测试

- Runtime API 全量 pytest；
- Worker 全量 pytest；
- Chromium Runtime 全量 pytest；
- Model Router 全量 pytest；
- Web JavaScript 测试；
- Android shared/app 单元测试；
- Android Debug APK 构建；
- Python compile、Compose config 和差异检查。

自动化阶段不因一个非依赖测试失败而停止其他测试，但会阻断依赖该能力的真实外部动作。

### 阶段 3：记忆写入与调用核心回归

本阶段是独立发布闸门，不合并到普通 API smoke。

验证：

- 原始事件、对话 turn 和 Redis Stream 投递；
- Worker checkpoint、失败重试、dead-letter 和事件幂等；
- 语义事件、事实、状态、图谱、向量和日程分层写入；
- 普通对话 15 轮批处理和强记忆信号即时处理；
- 联系人第一人称归属、跨联系人 scope 和助理身份 scope；
- 附件 provenance、版本和重新解析；
- 记忆路由对 KV、graph、RAG、timeline、dialogue、agenda 和 source 的选择；
- 个人搜索和聊天召回；
- context pack 排序、去重、预算、截断和 evidence ids；
- 记忆纠正、删除、取消、冲突和新证据更新；
- collector 不健康时的可信度提示；
- 容器重启后的写入和召回一致性。

每条写入用例必须检查持久化层；每条调用用例必须检查回答内容和 context/trace。只验证其中一侧不能判为通过。

### 阶段 4：API 与数据层

按功能域验证：

- 鉴权和错误契约；
- 对话、历史和实时通道；
- 事件采集、Worker 处理和去重；
- 日程、版本和主动建议；
- 附件全生命周期；
- Web Search 配置、路由、降级、引用和安全；
- 账号连接和助理身份；
- 求职 Pipeline；
- 开放任务、产物、验证和下载；
- 工具路由、授权、确认、幂等、审计；
- 数据库持久化和删除。

### 阶段 5：Web 工作台

在桌面和移动视口验证：

- 登录和会话；
- 四项主导航；
- 对话、附件和文件查看器；
- 日程；
- 求职；
- 设置中心八个子项；
- 设置深链接、前进/后退和标题区返回；
- 主动建议和确认卡；
- Web Search 来源链接；
- 任务产物；
- 异常、加载、空状态和长内容布局。

### 阶段 6：Android 真机

验证：

- 升级安装和原有配置保留；
- 悬浮窗权限、通知权限、麦克风权限；
- 悬浮球拖动、贴边、打开和关闭；
- 输入法、键盘、旋转和不同可视高度；
- 对话、历史、实时流和断线降级；
- 主动消息的前后台展示策略；
- 附件、内置查看器和 Download/Nomi 下载；
- 日程、求职和设置导航；
- 设置返回按钮和系统返回键；
- Web Search 配置和引用；
- 远程浏览器缩放、点击、双指滚动、文字输入和重连；
- App 重启后的会话与附件恢复。

### 阶段 7：真实账号和外部执行

本阶段允许真实写入，但目标必须是用户确认的测试账号或测试联系人。

覆盖：

- Gmail 收取测试邮件、采集、记忆、草稿、确认和真实发送；
- WhatsApp 测试联系人收发、采集、会话作用域和真实回复；
- Telegram 测试联系人收发和采集；
- Google Calendar 创建、读取、修改和删除测试日程；
- LinkedIn 测试联系人外联或其他可安全确认的测试动作；
- Web Search 真实 Provider 查询和降级；
- 助理身份真实 Gmail 端到端；
- 外部动作的 provider id、审计、幂等和重试。

需要二维码、短信验证码、2FA、账号确认或验证码时暂停自动执行，由用户完成最小必要交互后继续。

### 阶段 8：恢复、稳定性和清理

- 重启 Runtime API、Worker 和 Chromium Runtime；
- 验证浏览器登录态、身份状态、对话、附件、日程、任务和 pending draft；
- 验证重复 webhook、重复确认和网络重试不会产生重复外部动作；
- 验证 noVNC、WebSocket 和 Android 自动/手动重连；
- 删除测试日程、测试邮件和可撤回测试数据；
- 对不可撤回消息登记预期残留；
- 检查测试 Key、密码、token、Cookie 和验证码没有进入报告、Git 或普通日志。

## 5. 记忆核心回归矩阵

### 5.1 写入链路

| 用例 | 优先级 | 场景 | 必须证明 |
| --- | --- | --- | --- |
| RG-MEM-W01 | P0 | 私有事件基本写入 | `events` 有唯一记录，source、event type、时间和 raw evidence 可追溯 |
| RG-MEM-W02 | P0 | 稳定 message id 去重 | 相同 source event uid 重放不产生重复事件、语义、向量或建议 |
| RG-MEM-W03 | P1 | 无平台 ID 的 fingerprint 去重 | 同账号、会话、speaker、文本和时间桶的重放保持幂等 |
| RG-MEM-W04 | P1 | Worker 语义处理 | 新事件生成正确 `semantic_events`，保留 source 和 trace |
| RG-MEM-W05 | P1 | 普通对话延迟固化 | 单轮普通对话只写会话；不足 15 个完整轮次不创建 dialogue batch |
| RG-MEM-W06 | P1 | 15 轮对话批处理 | 第 15 个完整轮次后只生成一个 batch，摘要覆盖正确轮次 |
| RG-MEM-W07 | P1 | 强记忆信号即时处理 | “请记住”、偏好、身份、长期目标无需等待 15 轮 |
| RG-MEM-W08 | P0 | 联系人第一人称归属 | WhatsApp/Telegram/Gmail 联系人的“我”归属 speaker，不归属用户 |
| RG-MEM-W09 | P1 | 用户第一人称归属 | 用户与 Nomi 对话中的“我”归属 owner user |
| RG-MEM-W10 | P1 | 结构化事实写入 | subject/predicate/object、置信度、scope 和 evidence 正确 |
| RG-MEM-W11 | P1 | 状态记忆更新 | 同一状态 key 更新 current value，不产生多个互相矛盾的当前值 |
| RG-MEM-W12 | P1 | 实体和关系写入 | alias 归一、active relationship、confidence 和 provenance 正确 |
| RG-MEM-W13 | P1 | 向量写入 | 维度、归一化、实际 provider、source scope 和原始证据元数据正确 |
| RG-MEM-W14 | P1 | 嵌入降级 | 外部/本地 embedding 失败时显式使用 fallback，不伪装成主 provider |
| RG-MEM-W15 | P1 | 附件记忆 provenance | 文件 id、解析版本、页码/Sheet/单元格或 whole-file 证据可追溯 |
| RG-MEM-W16 | P1 | 附件重新解析 | 新版本增加新 provenance，不改写既有 evidence 历史 |
| RG-MEM-W17 | P1 | 日程 canonical 写入 | 相对时间转绝对时间；创建、改期和取消写入版本 |
| RG-MEM-W18 | P1 | 噪音抑制 | 页面标题、聊天列表 badge、网络遥测等低价值事件不写稳定事实/关系 |
| RG-MEM-W19 | P1 | Worker 可恢复失败 | 可重试数据库错误不前移 checkpoint；坏 payload 进入 dead-letter |
| RG-MEM-W20 | P1 | 写入审计 | 写入、更新、纠正和删除动作具有 event/evidence/audit 关联 |

### 5.2 调用与召回链路

| 用例 | 优先级 | 场景 | 必须证明 |
| --- | --- | --- | --- |
| RG-MEM-R01 | P1 | 精确事实召回 | 问题命中正确事实，回答与 source evidence 一致 |
| RG-MEM-R02 | P1 | 同义/改写召回 | 不复用原词的问法可通过 RAG 或语义层召回 |
| RG-MEM-R03 | P1 | 字面标识符召回 | 发票号、订单号、脱敏手机号等优先命中字面证据 |
| RG-MEM-R04 | P1 | 人物关系图谱 | “谁是谁的儿子/同事”等问题优先使用 active edge |
| RG-MEM-R05 | P1 | 当前状态事实 | 偏好、项目、目标等使用最新 state，而不是旧历史文本 |
| RG-MEM-R06 | P1 | 最近对话短指代 | “那她后来回复了吗”等短问句使用当前会话最近上下文 |
| RG-MEM-R07 | P0 | 跨会话隔离 | 标识符任务和私密对话不混入无关 conversation 的 assistant answer |
| RG-MEM-R08 | P0 | 跨联系人隔离 | 与联系人 A 相关的问题/回复不召回联系人 B 的私密评价 |
| RG-MEM-R09 | P0 | 用户账号/助理身份隔离 | 用户 Gmail 与 Nomi Gmail 的事件、草稿和记忆 scope 不混用 |
| RG-MEM-R10 | P1 | 日程当前状态 | active、改期、取消和过期状态以 `agenda_items` 当前值为准 |
| RG-MEM-R11 | P1 | 当前来源上下文 | 打开的 Gmail/WhatsApp/LinkedIn 页面能作为 source context，且有 durable fallback |
| RG-MEM-R12 | P1 | 附件后续追问 | 重启或切换界面后仍可用已绑定附件证据回答，并给出定位 |
| RG-MEM-R13 | P1 | 求职记忆调用 | 职业画像、简历、JD 和岗位按 career scope 召回，旧简历不覆盖新简历 |
| RG-MEM-R14 | P1 | 多层并行融合 | KV、graph、RAG、timeline、dialogue、agenda 去重后按相关性排序 |
| RG-MEM-R15 | P1 | token 预算 | 超长候选被有界截断/摘要，关键事实和 provenance 不丢失 |
| RG-MEM-R16 | P1 | collector 不可信 | 来源断线时回答区分“没有记录”和“尚未同步” |
| RG-MEM-R17 | P0 | 外部回复 scope gate | 给测试联系人生成/发送回复时不使用禁止进入目标作用域的第三方私密信息 |
| RG-MEM-R18 | P1 | context snapshot | 最终回答记录 included event/memory/agenda ids、scope filter 和 latency trace |
| RG-MEM-R19 | P1 | 召回降级 | graph/vector/model 任一层故障时诚实降级，不编造缺失记忆 |
| RG-MEM-R20 | P1 | HTTP/WS 一致性 | `/api/chat` 与 WebSocket 对同一记忆问题使用一致的 scope 和证据 |

### 5.3 记忆生命周期、治理和恢复

| 用例 | 优先级 | 场景 | 必须证明 |
| --- | --- | --- | --- |
| RG-MEM-L01 | P1 | 治理列表 | 治理 API/UI 能展示事实、语义记忆、来源和状态 |
| RG-MEM-L02 | P1 | 语义记忆纠正 | PATCH 后新回答采用纠正值，trace 指向纠正后的证据 |
| RG-MEM-L03 | P0 | 删除记忆 | 删除后搜索和聊天不再召回，相关审计保留且原始授权边界正确 |
| RG-MEM-L04 | P1 | 冲突事实 | 新证据不会让两个矛盾值同时作为当前事实回答 |
| RG-MEM-L05 | P1 | 日程取消/改期 | 旧日程保留版本证据，但不再作为当前活跃安排 |
| RG-MEM-L06 | P1 | 新证据使旧答案失效 | 事实/日程变化后重复提问返回新状态 |
| RG-MEM-L07 | P0 | 容器重启恢复 | Runtime API、Worker、Redis 或 Postgres 重启后记忆可继续写入和召回 |
| RG-MEM-L08 | P1 | Worker 断点续传 | checkpoint 恢复不漏事件、不重复固化 |
| RG-MEM-L09 | P1 | 对话历史恢复 | Android 悬浮窗、完整 App 和 Web 使用同一服务端会话事实源 |
| RG-MEM-L10 | P1 | 附件/会话删除联动 | 删除会话后附件关系、衍生物和记忆 provenance 按策略清理 |
| RG-MEM-L11 | P1 | 每日维护 | 维护任务合并/清理时不删除 active evidence 或未完成任务 |
| RG-MEM-L12 | P0 | 敏感字段边界 | token、验证码、支付和凭证不进入普通模型上下文、trace 或报告 |

### 5.4 真实来源端到端

| 用例 | 优先级 | 场景 | 必须证明 |
| --- | --- | --- | --- |
| RG-MEM-E01 | P1 | Gmail 邮件到记忆再召回 | 真实测试邮件被采集、写入、可搜索，并能回答主题/截止日期 |
| RG-MEM-E02 | P1 | WhatsApp 事实到图谱再召回 | 测试联系人发送身份/关系事实，后续问题命中正确 speaker 和关系 |
| RG-MEM-E03 | P1 | WhatsApp 改期/取消 | 原约定、改期、取消形成同一日程版本链，回答只用当前状态 |
| RG-MEM-E04 | P1 | Telegram 消息到记忆 | 真实消息被采集并在正确 contact scope 中召回 |
| RG-MEM-E05 | P1 | Calendar 到日程问答 | 测试日历事件写入/采集后，问答返回绝对时间和来源 |
| RG-MEM-E06 | P1 | LinkedIn/求职上下文 | 测试资料和职位进入 career scope，匹配和后续问答使用正确版本 |
| RG-MEM-E07 | P1 | 真实附件到后续任务 | 上传真实文件后，跨轮次问答和产物任务能引用同一 provenance |
| RG-MEM-E08 | P0 | 真实外发前的记忆隔离 | 外发内容只使用允许证据；provider id、最终正文哈希和审计一致 |

记忆阶段通过标准：

- 写入测试必须同时有事件/数据库记录和 trace 证据；
- 召回测试必须同时检查答案、scope、evidence ids 和 canonical state；
- 不能以“回答里碰巧出现目标字符串”代替正确召回；
- 不能以“数据库有一行”代替后续实际可调用；
- RG-MEM-W01、W02、W08、R07、R08、R09、R17、L03、L07、L12、E08 任一失败均至少是 P0/P1 发布阻断。

## 6. 用例模型

每条详细用例必须包含：

- 用例编号；
- 功能域；
- 优先级；
- 测试层级；
- 前置条件；
- 测试数据；
- 操作步骤；
- 预期结果；
- 实际结果；
- 证据位置；
- 清理动作；
- `PASS`、`FAIL`、`BLOCKED` 或 `NOT_RUN` 状态。

用例编号使用：

```text
RG-PRE-*   环境和鉴权
RG-AUTO-*  自动化测试
RG-API-*   API 合约
RG-WEB-*   Web 工作台
RG-AND-*   Android 真机
RG-BRW-*   远程浏览器
RG-COL-*   采集器
RG-MEM-*   记忆和治理
RG-CHAT-*  对话
RG-ATT-*   附件和查看器
RG-AGD-*   日程
RG-PRO-*   主动建议
RG-SEARCH-* Web Search
RG-JOB-*   求职助手
RG-ID-*    助理身份
RG-EXT-*   外部真实执行
RG-TASK-*  开放任务和产物
RG-SEC-*   安全、权限和审计
RG-REC-*   重启和恢复
RG-CLEAN-* 清理
```

## 7. 优先级和缺陷严重度

### P0

- 无法登录或核心服务整体不可用；
- 数据丢失或不可恢复损坏；
- 凭证、Cookie、验证码或隐私数据泄露；
- 向非测试目标误发；
- 未经确认产生费用、法律承诺或真实职位申请；
- 安全门、作用域或身份隔离失效。

### P1

- 对话、账号连接、日程、附件、求职、Web Search 或外部发送核心链路不可用；
- 重复发送或重复创建外部资源；
- Android 主入口、设置或远程浏览器无法使用；
- 重启后关键状态丢失。

### P2

- 存在替代路径的功能异常；
- 单一 Provider、单一格式或非关键状态异常；
- 明显 UI、响应式、错误提示或兼容性问题。

### P3

- 文案、视觉细节或低频体验问题；
- 不影响功能和数据正确性的轻微偏差。

## 8. 执行控制

- 阶段 1 的 P0/P1 会阻断依赖它的后续高副作用测试。
- 独立模块继续执行，以最大化一次回归得到的信息。
- 外部写入前再次核对测试标记、目标账号和动作类型。
- 同一发送用例优先使用唯一 client request id 和业务幂等键。
- 不使用真实密码、token、Cookie、二维码或验证码作为报告证据。
- 不自动解决验证码、2FA 或平台风控。
- 不修改生产代码；如果发现缺陷，只诊断和记录，等待用户另行授权修复。

## 9. 证据和可追溯性

每条用例至少保留一种证据，关键链路至少保留两种：

- 命令及退出码；
- 测试框架输出；
- API 请求和脱敏响应；
- 数据库查询；
- 容器状态和相关日志片段；
- Web 截图；
- Android 真机截图、UI 层级或 logcat；
- provider message/event id；
- 文件哈希、MIME、字节数和结构校验；
- 任务 trace、pipeline result 或审计记录。

证据目录不得存储明文凭证。外部系统返回的隐私内容只记录验证所需的最小片段或哈希。

## 10. 测试数据和清理

统一外部标记：

```text
NOMI-REGRESSION-20260727
```

推荐测试数据包括：

- 唯一主题的测试邮件；
- 包含精确时间和模糊时间的测试消息；
- 改期和取消消息；
- 测试日历事件；
- 不同类型真实附件；
- 可验证答案的 Web Search 查询；
- 求职测试画像、测试 JD 和测试简历；
- 产物生成请求；
- 一次故意重复的 webhook/确认请求。

清理规则：

- 删除测试日历事件；
- 删除或归档可删除的测试邮件；
- 删除测试草稿、临时附件和测试任务；
- 对 WhatsApp、Telegram、LinkedIn 等不可撤回消息登记预期残留；
- 清理测试数据库数据前先保存必要审计证据；
- 不删除回归前已经存在的用户数据；
- 不删除或重置真实浏览器 Profile。

## 11. 发布判定

### PASS

- P0/P1 全部通过；
- Web、Android 和服务端核心链路通过；
- 至少一条真实入站和一条真实出站链路通过；
- 重启恢复和幂等通过；
- 可清理测试数据完成清理；
- 无未说明的敏感数据残留。

### CONDITIONAL PASS

- 不存在 P0；
- 存在用户明确接受的 P1/P2；
- 问题不影响本次主要使用场景；
- 报告中明确列出规避方式和风险。

### FAIL

- 存在 P0；
- 核心主链路存在不可接受的 P1；
- 真实外部动作发生重复、误发或绕过确认；
- 数据恢复、作用域隔离或凭证保护不满足要求。

### BLOCKED

- 关键账号、服务、模型或 provider 无法取得；
- 必要人工登录未完成；
- 缺少可确认的安全测试目标；
- 阻断导致无法对主要功能给出可信结论。

## 12. 人工协作点

仅在以下情况请求用户操作：

- 扫描 WhatsApp 或其他账号二维码；
- 输入短信或邮箱验证码；
- 完成 2FA；
- 处理平台明确要求的账号确认；
- 确认某个 LinkedIn/ATS 目标确实是测试目标；
- 外部平台要求无法自动化的验证码。

用户完成后，测试从当前用例继续，不要求用户重复已完成步骤。

## 13. 已知边界

- 第三方网页 DOM 变化可能造成采集回归。
- 外部 Provider 的限流、风控、地区和账号状态可能产生环境性阻断。
- Web Search claim-source 绑定还不是独立语义蕴含验证。
- 通用公开网页抓取不保证执行动态 JavaScript。
- Nomi 自有 WhatsApp 身份不作为当前 Gmail V1 助理身份完成条件。
- 批量营销、真实付款、真实购物、真实打车和非测试职位投递不在本轮授权内。
- 单用户私有部署不以高并发或多租户隔离作为发布门槛。

## 14. 设计完成标准

- 项目功能总结覆盖当前主要代码模块和近期功能；
- 回归范围明确包含 Web、服务端、Android 真机和真实账号；
- iOS 和高风险非测试动作明确排除；
- 外部发送、人工登录、证据、清理和发布判定没有歧义；
- 下一步可以据此编写逐条可执行测试计划和命令；
- 实际执行不会因测试设计缺少目标、证据或清理规则而临时扩大授权。
