# Nomi 统一聊天附件设计

**日期：** 2026-07-13
**状态：** 已确认，等待实现计划
**范围：** Android 悬浮窗与完整 App 的图片和常见文档上传、持久化、理解、问答与跨端同步
**研究依据：** `docs/superpowers/reports/2026-07-13-chat-attachments-research.md`

## 1. 目标

Nomi 必须允许用户在两种 Android 聊天界面中：

1. 只发送一个或多个附件，由 Nomi 默认识别并概括。
2. 同时发送附件与文字，文字作为本次任务指令，附件作为证据。
3. 在后续对话中继续引用已发送附件。
4. 切换悬浮窗、完整 App 或重启客户端后，看到相同的消息和附件状态。
5. 对图片、普通数字文档、扫描文档和大型文档采用不同的理解策略。

功能完成不能以“出现上传按钮”或“接口返回 200”为标准。只有在原始字节可验证、附件与准确消息绑定、模型实际收到正确证据、回答可追溯，并且两种界面保持一致时，功能才算完成。

## 2. 已确认的产品决策

- 采用“轻量本地解析 + Qwen 视觉兜底 + 大文件检索”的方案 A。
- 已发送附件随对话长期保留，删除对话时一起删除。
- 未发送附件属于草稿，默认 24 小时后自动清理。
- 允许纯附件消息，也允许附件与文字一起发送。
- 纯附件消息默认任务是“识别并概括附件内容”。
- PDF 超过 20 页或 PPTX 超过 30 张时，默认完成全量轻量解析和索引，但不逐页调用视觉模型。
- 大文件根据用户问题选择相关文本和页面；只有用户明确要求逐页完整检查时才创建异步任务。
- 完整 Docling 不进入 2 核 4G 默认部署，仅保留为未来可插拔的高配 Worker。

## 3. V1 支持范围

| 类型 | 扩展名 | 默认处理 |
| --- | --- | --- |
| 图片 | `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif` | 校验、方向归一、缩略图；请求时交给 Qwen 视觉理解 |
| PDF | `.pdf` | 分页文本提取；扫描页、图表页和视觉问题按需渲染 |
| Word | `.docx` | 标题、段落、列表、表格、链接、媒体引用提取 |
| PowerPoint | `.pptx` | 幻灯片顺序、标题、正文、备注、表格、媒体引用提取 |
| Spreadsheet | `.xlsx`, `.csv` | Sheet、区域、公式、值和有界预览提取 |
| Text | `.txt`, `.md` | 安全解码并保留行结构 |

V1 明确拒绝：

- 旧版二进制 Office：`.doc`, `.ppt`, `.xls`。
- 压缩包、可执行文件、脚本文件和未知二进制格式。
- 加密或密码保护的文档。
- 损坏、无法安全解压或超过复杂度限制的文档。

拒绝必须返回可操作的中文原因，不能静默忽略附件。

默认可配置限制：

- 单文件最大 25 MB。
- 单条消息最多 8 个附件。
- 单条消息附件总大小最大 64 MB。
- PDF 最多自动建立 200 页索引。
- PPTX 最多自动建立 150 张索引。
- XLSX 最多自动处理 100,000 个非空单元格。
- 单次模型请求最多包含 6 个视觉图片或渲染页。

## 4. 总体架构

```text
完整 App WebView 文件输入 ─┐
                           ├─> 流式上传 ─> 私有原件存储 ─> attachment_id
悬浮窗原生文件选择 Activity ─┘                         │
                                                      v
                                          有界异步解析 Worker
                                                      │
                                                      v
                                                ready / failed
                                                      │
                         message + attachment_ids ────┘
                                                      │
                                                      v
                                    原子写入 user turn + 附件关系
                                                      │
                              ┌───────────────────────┴──────────────────────┐
                              v                                              v
                    上下文与证据选择器                              统一服务端聊天历史
                              │                                              │
                              v                              ┌───────────────┴───────────────┐
                    Qwen 文本/视觉请求                      v                               v
                                                    Android 悬浮窗                  完整 App
```

架构约束：

1. 原始文件、衍生结果和消息关系分别建模。
2. 文件名只用于展示，不作为身份、路径或去重依据。
3. 上传成功不等于解析完成，也不等于已经属于某条消息。
4. HTTP 与 WebSocket 共享同一套附件验证、消息提交和模型上下文逻辑。
5. 服务端消息历史是唯一事实源；Android 本地历史只作为离线镜像。

## 5. 私有存储

附件存储在静态 Web 目录和源码目录之外：

```text
${NOMI_ATTACHMENT_ROOT}/
  temporary/<upload-id>.part
  originals/<id-prefix>/<attachment-id>/<generated-name>
  derived/<attachment-id>/manifest.json
  derived/<attachment-id>/text.txt
  derived/<attachment-id>/thumbnails/
  derived/<attachment-id>/pages/
  derived/<attachment-id>/frames/
```

上传流程：

1. 生成 `attachment_id` 和服务端存储名。
2. 将请求流写入同一文件系统中的临时文件，同时计算 SHA-256 和字节数。
3. 达到大小上限立即终止，不继续接收剩余内容。
4. 根据魔数和容器结构检测真实类型；客户端 MIME 和扩展名只作参考。
5. 对 Office ZIP 检查条目数量、单条目大小、总解压大小和路径穿越。
6. `fsync` 后原子移动到 originals 目录，再标记为 `stored`。
7. 客户端断开或异常遗留的 `receiving` 文件由清理任务删除。

数据库、日志、消息历史和长期记忆均不保存 base64 文件数据或绝对服务器路径。

## 6. 数据模型

### 6.1 `chat_attachments`

每个上传原件一行：

- `id UUID PRIMARY KEY`
- `sha256 TEXT`
- `original_filename TEXT NOT NULL`
- `safe_filename TEXT NOT NULL`
- `declared_mime_type TEXT`
- `detected_mime_type TEXT`
- `extension TEXT`
- `byte_size BIGINT`
- `storage_relative_path TEXT`
- `status TEXT NOT NULL`
- `lifecycle TEXT NOT NULL DEFAULT 'draft'`
- `parser_kind TEXT`
- `processing_version TEXT NOT NULL`
- `error_code TEXT`
- `error_detail_safe TEXT`
- `created_at`, `stored_at`, `processed_at`, `attached_at`, `expires_at`, `deleted_at`

`status` 取值：

```text
receiving -> stored -> processing -> ready
                       |
                       +-> rejected
                       +-> failed
```

`lifecycle` 取值：

- `draft`：未绑定消息，默认 24 小时过期。
- `attached`：已绑定用户消息，随对话保留。
- `deleted`：等待或已经完成物理清理。

### 6.2 `chat_attachment_derivatives`

保存解析和预览产物的元数据：

- `id UUID PRIMARY KEY`
- `attachment_id UUID REFERENCES chat_attachments(id) ON DELETE CASCADE`
- `kind TEXT NOT NULL`
- `mime_type TEXT`
- `storage_relative_path TEXT`
- `byte_size BIGINT`
- `locator JSONB NOT NULL DEFAULT '{}'`
- `metadata JSONB NOT NULL DEFAULT '{}'`
- `processing_version TEXT NOT NULL`
- `created_at TIMESTAMPTZ`

`kind` 包括：`extracted_text`, `document_manifest`, `thumbnail`, `rendered_page`, `representative_frame`, `visual_result`。

### 6.3 `chat_attachment_chunks`

为大文件检索保存可定位文本块：

- `id UUID PRIMARY KEY`
- `attachment_id UUID REFERENCES chat_attachments(id) ON DELETE CASCADE`
- `ordinal INTEGER NOT NULL`
- `text TEXT NOT NULL`
- `token_count INTEGER NOT NULL`
- `locator JSONB NOT NULL`
- `content_hash TEXT NOT NULL`
- `embedding` 使用项目现有向量能力
- `created_at TIMESTAMPTZ`

`locator` 必须能定位到 PDF 页码、PPTX 幻灯片、DOCX 标题/段落或 XLSX Sheet/区域。

### 6.4 `assistant_turn_attachments`

附件与准确聊天消息的关系：

现有 `assistant_turns` 表同时保存 `user` 和 `assistant` 角色，因此该关系表会把用户上传的附件绑定到准确的 user turn，并不是绑定到助手回复。

- `turn_id UUID REFERENCES assistant_turns(id) ON DELETE CASCADE`
- `attachment_id UUID REFERENCES chat_attachments(id)`
- `ordinal INTEGER NOT NULL`
- `purpose TEXT NOT NULL DEFAULT 'user_provided'`
- 主键 `(turn_id, attachment_id)`
- 唯一约束 `(turn_id, ordinal)`

一条用户消息可有多个附件。V1 不提供把一个已经绑定的附件重新附加到另一条新消息的 UI；后续对话通过历史消息引用原附件。

## 7. API 合约

### 7.1 上传

`POST /api/chat/attachments`

- 使用现有 `X-Par-Password` 鉴权。
- `multipart/form-data`，一个 `file` 和可选 `client_upload_id`。
- 流式接收，不把完整文件载入 Python 内存。
- 返回 `attachment_id`、安全元数据、状态和处理进度。
- `client_upload_id` 提供幂等上传；重试不能生成重复草稿。

### 7.2 状态、预览与原件

- `GET /api/chat/attachments/{id}`：状态和安全元数据。
- `GET /api/chat/attachments/{id}/preview`：认证缩略图或预览。
- `GET /api/chat/attachments/{id}/content`：认证原件下载。
- `POST /api/chat/attachments/{id}/retry`：从完整原件重新解析。
- `DELETE /api/chat/attachments/{id}`：仅删除未绑定草稿。

客户端在前台每秒轮询 processing 状态；页面离开或附件终态后停止。未来可以增加 WebSocket 状态事件，但 V1 不依赖它保证正确性。

### 7.3 发送消息

HTTP 和 WebSocket 均增加：

```json
{
  "message": "请比较这些材料，也可以为空字符串",
  "attachment_ids": ["uuid-1", "uuid-2"],
  "conversation_id": "optional-uuid",
  "client_request_id": "stable-client-id"
}
```

验证规则：

- `message` 与 `attachment_ids` 不能同时为空。
- 附件数量、总大小和 ID 唯一性符合限制。
- 每个附件必须是 `ready`、未过期、未删除的草稿。
- 同一 `client_request_id` 必须返回同一发送结果。

发送事务：

1. 锁定全部附件行。
2. 完成全部验证。
3. 写入用户 `assistant_turns` 行。
4. 按顺序写入 `assistant_turn_attachments`。
5. 将附件 lifecycle 更新为 `attached` 并清除 `expires_at`。
6. 提交事务。

任一附件验证失败时，整条消息不写入。不能静默丢弃失败附件后发送纯文本。

用户消息提交后，如果模型调用失败：

- 用户消息及附件继续保留在历史中。
- UI 在该消息后显示可重试的助手错误状态。
- 重试使用原 user turn ID，不重复上传、不新建第二条用户消息。

### 7.4 历史

`GET /api/chat/history` 中每条消息增加有序 `attachments`：

```json
{
  "id": "turn-uuid",
  "role": "user",
  "content": "请分析附件",
  "attachments": [
    {
      "attachment_id": "uuid-1",
      "filename": "architecture.png",
      "mime_type": "image/png",
      "byte_size": 431551,
      "status": "ready",
      "kind": "image",
      "preview_url": "/api/chat/attachments/uuid-1/preview",
      "content_url": "/api/chat/attachments/uuid-1/content"
    }
  ]
}
```

## 8. 解析 Worker

解析在有界后台 Worker 中执行，不在聊天请求内执行。默认并发：

- 轻量文本解析最多 2 个并行任务。
- LibreOffice 渲染最多 1 个任务。
- Qwen 视觉分析最多 1 个并行任务。

Worker 对每个文件设置超时、内存、页数、幻灯片、单元格和解压复杂度限制。解析失败不能导致主 API 进程退出。

### 8.1 图片

- 使用 Pillow 验证真实图片格式、尺寸和像素总量。
- 保留原图；基于 EXIF 方向生成最大边 2048 像素的预览衍生文件。
- GIF 选择最多 4 个视觉差异明显的代表帧。
- 上传阶段不为每张图片额外调用模型生成描述。
- 消息请求时按用户指令把必要图片交给 Qwen；结果可以按文件哈希和处理版本缓存。

### 8.2 PDF

- 使用 `pypdf` 分页提取文本和元数据。
- 每页保留页码、字符数和文本密度。
- 低文本密度页标记为疑似扫描页。
- 使用 `pypdfium2` 在 Worker 中按需渲染页面。
- 普通 PDF 不自动逐页调用视觉模型。

### 8.3 DOCX

- 使用 `python-docx` 和必要的 OOXML 读取标题、段落、列表、表格、链接、媒体引用与顺序。
- 需要检查版式或图片时，在隔离 Worker 中使用 LibreOffice headless 转换相关页面，再渲染为图片。

### 8.4 PPTX

- 使用 `python-pptx` 读取幻灯片顺序、标题、正文、备注、表格和媒体引用。
- 需要检查布局、图表或整张幻灯片时，使用单并发 LibreOffice headless 渲染。

### 8.5 XLSX 与 CSV

- 使用 `openpyxl` 的只读模式读取 Sheet、公式和值。
- 每个文本块保留 Sheet 名和单元格范围。
- 图表或视觉布局问题按需使用 LibreOffice 渲染选定 Sheet 区域。
- CSV 使用流式读取、编码检测、列数和行长度限制。

### 8.6 TXT 与 Markdown

- 优先 UTF-8，失败时使用明确的安全回退并记录编码。
- 保留行号、标题和代码块边界。
- Markdown 中的 HTML 不直接渲染为可信内容。

## 9. 上下文和检索策略

### 9.1 三种模式

**受限全文**

- 提取内容不超过约 24K token。
- 在总上下文预算允许时包含全文和定位标记。

**按问题检索**

- 大文件或多附件超出全文预算时使用。
- 使用项目现有向量 + 关键词混合检索。
- 按附件分配最低证据配额，避免一个大文件挤掉其他附件。
- 结果保留页码、幻灯片、标题和单元格范围。

**逐页完整检查**

- 仅在用户明确要求时启动异步任务。
- 分批处理并通过任务状态向用户报告进度。
- 最终回答必须说明覆盖范围和失败页面。

### 9.2 视觉升级条件

满足任一条件时，选择相关页或图片交给 Qwen：

- 页面文本低于阈值，疑似扫描件。
- 页面包含影响答案的图表、流程图、截图或关键图片。
- 用户询问布局、颜色、视觉关系或图片内容。
- 文本检索命中页面，但纯文本不足以回答。

PDF 超过 20 页或 PPTX 超过 30 张时，仍完成全量轻量解析和索引，但视觉升级只作用于与问题相关的页面。单次请求最多 6 个视觉项目；更多内容分批提取摘要后再综合。

### 9.3 256K 上下文预算

附件证据参与现有 256K 总预算：

- 系统和安全指令优先保留。
- 保留已确认的最近 15 轮会话策略。
- 长期记忆、日程和任务上下文继续由现有路由决定。
- 附件证据默认最多使用 64K token。
- 为模型正式输出预留预算。
- 被截断或排除的附件内容写入 trace，并在影响结论时告诉用户。

## 10. 模型适配

现有 `list[dict[str, str]]` 必须升级为结构化内容类型：

```text
ChatContent = string | [TextPart | ImageUrlPart]
```

OpenAI-compatible Qwen 请求示例：

```json
[
  {"type": "text", "text": "用户指令与带定位的附件证据"},
  {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
]
```

只有模型适配器读取私有图片并临时编码 base64。base64 不进入数据库、日志、trace、长期记忆或聊天历史。

文档内容必须包裹为“不可信证据”：

- 文档中的指令不能覆盖系统提示。
- 文档中的文本不能自行触发工具或外部动作。
- 工具调用只由用户当前请求和 Nomi 的风险门禁触发。

Qwen 视觉端点已经实测可以正确理解图片，但当前部署在视觉请求中仍可能产生 `reasoning_content`。客户端只流式展示正式 `content`；隐藏 reasoning 不落库、不显示。视觉首字耗时与普通文本首字耗时分开记录。

## 11. 回答引用

附件答案必须使用稳定定位：

- `[方案.pdf，第 7 页]`
- `[介绍.pptx，第 12 张]`
- `[预算.xlsx，Sheet1!A2:D18]`
- `[需求.docx，“验收标准”章节]`
- `[architecture.png]`

模型不得声称阅读过未进入上下文或未完成处理的页面。部分覆盖时必须说明实际检查范围。

## 12. 长期记忆

附件原文不会在上传时自动复制到长期记忆：

1. 聊天消息永久保留附件关系。
2. 当前对话和后续对该消息的引用可以读取附件证据。
3. 现有每 15 轮对话记忆批处理可以提取真正长期有用的事实。
4. 从附件得到的长期事实必须保留 `attachment_id`、`turn_id`、页码/位置和处理版本。
5. 重新解析产生新 derivative 版本，不能静默改写旧引用的证据来源。

## 13. Android 与 Web 交互

### 13.1 共同行为

- 输入框旁增加熟悉的附件图标。
- 选中附件显示在输入框上方的一体化附件托盘。
- 图片显示缩略图；文档显示类型、文件名、大小和状态。
- 文件名最多两行，超长省略，不能撑出消息框。
- 支持删除草稿、解析失败重试和重新选择。
- 全部附件 ready 前发送按钮不可用。
- 文字为空但至少一个附件 ready 时允许发送。
- 键盘出现时，附件托盘和输入区整体移动到键盘上方。

### 13.2 完整 App

- Web 聊天表单增加 `accept` 和 `multiple` 文件输入。
- `WebWorkspaceActivity` 实现 `WebChromeClient.onShowFileChooser`。
- 使用 Android Storage Access Framework 返回 URI。
- WebView 的 accept 类型只改善选择体验，Android 和服务端仍必须独立验证实际类型。

### 13.3 悬浮窗

- `FloatingBallService` 的输入区增加原生附件按钮和托盘。
- 由透明或轻量 Picker Activity 启动 `ACTION_OPEN_DOCUMENT` 并返回 URI grants。
- 使用 OkHttp RequestBody 从 `ContentResolver` 流式上传，不把整个文件载入 Java 堆。
- Picker Activity 返回后恢复原悬浮窗草稿和键盘状态。

### 13.4 草稿与历史同步

- 未发送草稿只属于创建它的当前界面，不在完整 App 与悬浮窗间迁移。
- 已发送消息立即成为服务端事实，并通过现有 message ID 同步逻辑出现在两个界面。
- Android 本地离线镜像保存附件安全元数据，不保存原始 base64。
- 恢复历史时以服务端 `message_id + attachment_id` 合并，不能按文件名猜测。

## 14. 错误与重试

稳定错误码：

- `unsupported_type`
- `too_large`
- `complexity_limit`
- `encrypted`
- `corrupt`
- `storage_failed`
- `parse_failed`
- `parse_timeout`
- `vision_unavailable`
- `attachment_not_ready`
- `attachment_expired`
- `attachment_already_attached`

错误响应只包含安全信息，不暴露绝对路径、模型凭据或上游原始响应。

当视觉服务不可用但文本证据完整时，可以继续回答，但必须明确说明没有完成视觉检查。若视觉内容是回答的必要条件，则返回可重试错误，不能编造。

## 15. 安全要求

- 使用扩展名 allowlist、魔数、容器结构和解析器验证的组合。
- 原件存储在 Web root 之外，使用随机服务端名称。
- 下载和预览必须使用现有密码鉴权并设置安全 Content-Disposition。
- 防止路径穿越、ZIP bomb、超大像素图片、超长 CSV 行和解析器资源耗尽。
- HTML/Markdown 预览必须净化，不能直接执行附件中的脚本。
- 解析 Worker 使用非 root 用户、只读应用目录、受限临时目录和超时。
- 外部杀毒或 CDR 可以作为未来可选适配器，不是 V1 正确性的前提。

## 16. 可观测性

每个附件相关 trace 记录：

- attachment ID、实际类型、字节数、处理版本和状态。
- 上传、哈希、存储、解析、chunk、embedding、检索、渲染耗时。
- 进入模型的文本块、定位信息和视觉项目数量。
- 被排除内容及原因。
- Qwen 首个上游分片、首个正式答案字符和总耗时。
- HTTP/WebSocket 请求 ID、client_request_id、user turn ID 和 assistant turn ID。
- 错误码和重试次数，不记录原始私有内容。

trace 必须能证明回答实际使用了哪个附件的哪些位置，而不是仅证明请求执行成功。

## 17. 性能目标

在 2 核 4G 私有服务器上：

- 普通小型数字文档解析 `P95 <= 5 秒`。
- 图片或扫描页问答首个正式字符 `P95 <= 12 秒`。
- 轻量解析最大并发 2，Office 渲染和视觉分析最大并发各 1。
- 连续混合文件测试不能导致主 API OOM、重启或聊天健康检查失败。
- 大文件处理不能长期占满高优先级聊天队列。

## 18. 测试与验收

### 18.1 单元测试

- 类型检测、文件名安全、大小和复杂度限制。
- 状态机合法转换与 24 小时草稿过期。
- message/attachment 原子绑定和 client_request_id 幂等。
- 各格式解析器输出及定位。
- 低文本密度扫描页检测。
- 上下文预算、附件配额、视觉升级和引用格式。
- 模型结构化内容转换，确保图片不被字符串化。

### 18.2 API 集成测试

- multipart 流式上传、断线、重试和部分文件清理。
- processing 轮询、失败重试、认证预览和原件下载。
- HTTP 与 WebSocket 的成功和失败行为一致。
- 模型失败后复用原 user turn 重试，不生成重复消息。
- 删除对话后数据库关系和物理文件最终一致。

### 18.3 真实文件质量测试

- 图片、DOCX、PPTX、PDF、XLSX、CSV、TXT、MD 各至少一个真实文件。
- 图片单独发送、文件单独发送、附件加文字。
- 扫描 PDF 必须触发视觉兜底并识别正确文字。
- 超过 20 页 PDF 和超过 30 张 PPTX 必须按问题检索。
- 表格回答引用正确 Sheet 和单元格范围。
- 文件内提示注入不能改变系统行为或触发工具。
- 模型回答逐条核对事实、引用和覆盖范围，不能只看 `success`。

### 18.4 Android 真机测试

- 完整 App 和悬浮窗分别选择单文件、多文件和图片。
- 键盘不遮挡附件托盘、输入框、发送按钮或返回内容。
- 上传进度、解析进度、失败、重试和删除状态合理。
- 切换两种界面和重启 App 后，已发送附件历史一致。
- 超长文件名、中文文件名和长回答不横向溢出。
- 断网、恢复网络和模型失败时不重复上传或重复发送。

## 19. 实施边界

本设计不包含：

- 音频和视频附件理解。
- 旧版 `.doc/.ppt/.xls` 转换。
- 跨用户权限模型；Nomi 保持单用户私有部署定位。
- 云端第三方文档解析服务。
- 默认启用完整 Docling。
- 在两个界面间同步未发送的本地草稿。

## 20. 实施顺序

1. 数据表、私有存储和上传 API。
2. 轻量解析 Worker、状态与清理任务。
3. 消息原子绑定、历史返回和 HTTP/WebSocket 统一。
4. 模型结构化内容、检索、视觉升级和引用。
5. Web 完整 App 文件选择与附件 UI。
6. Android 悬浮窗 Picker Activity、上传和附件 UI。
7. 错误重试、trace、资源限制和安全加固。
8. 云服务器、模拟器和 Android 真机完整回归。
