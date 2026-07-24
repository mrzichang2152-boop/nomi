# Nomi 统一聊天附件实现 Gap 记录

**日期：** 2026-07-13

**依据规格：** `docs/superpowers/specs/2026-07-13-unified-chat-attachments-design.md`

**执行计划：** `docs/superpowers/plans/2026-07-13-unified-chat-attachments-tdd-implementation.md`
**状态规则：** 只有自动化行为验证和对应真实环境验收都满足时才标记完成。仅有代码、mock 或接口成功不能标记完成。

## 基线

| 检查项 | 命令 | 结果 | 说明 |
| --- | --- | --- | --- |
| 后端完整测试 | `python3 -m pytest -q runtime_api/tests` | 通过，894 tests | 附件实现前基线 |
| Android 单元测试 | `gradle -p android_app :app:testDebugUnitTest` | 通过 | Gradle 提示未来版本弃用警告，不影响当前基线 |
| Compose 配置 | `docker compose config --quiet` | 通过 | 附件 worker 尚未加入 |
| Task 4 后端完整测试 | `python3 -m pytest -q runtime_api/tests` | 通过，961 tests | 队列、Worker、清理与容器边界接入后 |
| Task 4 附件聚焦测试 | `python3 -m pytest -q runtime_api/tests/test_attachment_*.py` | 通过，67 tests | 包含 worker 11 条状态/租约/清理/Compose 契约 |
| Task 4 Compose 配置 | `docker compose config --quiet` | 通过 | 独立非 root `attachment-worker` 与共享私有卷已解析 |
| Task 5 后端完整测试 | `python3 -m pytest -q runtime_api/tests` | 通过，978 tests | 八类解析器、原子结果持久化与恢复性修复接入后 |
| Task 5 附件聚焦测试 | Task 1-5 的全部附件测试文件 | 通过，84 tests | 逐项核对事实、locator、编码、扫描页、公式/值、预览与生命周期 |
| Task 6 后端完整测试 | `python3 -m pytest -q runtime_api/tests` | 通过，995 tests | 状态、预览、下载、重试、删除与物理完整性校验接入后 |
| Task 6 附件聚焦测试 | `python3 -m pytest -q runtime_api/tests/test_attachment_*.py` | 通过，101 tests | 17 条生命周期 API 用例覆盖鉴权、私有响应头、中文文件名、过期、重试去重和删除 |
| Task 7 后端完整测试 | `python3 -m pytest -q runtime_api/tests` | 通过，1015 tests | HTTP/WebSocket 统一提交、事务绑定、并发和 `client_request_id` 幂等接入后 |
| Task 7 附件聚焦测试 | `python3 -m pytest -q runtime_api/tests/test_attachment_*.py` | 通过，118 tests | 17 条绑定测试覆盖纯附件、混合输入、顺序、总量、状态、非法 ID、回滚、并发和请求复用 |
| Task 7 传输一致性测试 | `python3 -m pytest -q runtime_api/tests/test_attachment_chat_binding.py runtime_api/tests/test_realtime_ws.py -k attachment` | 通过，20 tests | HTTP/WS 传递相同有序附件集合，返回相同安全错误码 |
| Task 7 隔离暂存快照 | `git checkout-index` 后运行附件测试与后端全量测试 | 附件 20 tests 通过；全量 2 failed、796 passed | 两个失败为 `test_chat_response_uses_explicit_memory_layer_fetchers` 和 `test_context_pack_pipeline_retrieves_local_memory_agenda_and_turns`；Task 7 前 `HEAD` 快照同样为这两个失败（2 failed、776 passed），确认不是附件提交引入。当前脏工作区的既有上下文改动下后端全量为 1015 passed，不能将那些无关改动混入本检查点 |
| Task 8 聚焦测试 | `python3 -m pytest -q runtime_api/tests/test_attachment_history_and_retry.py runtime_api/tests/test_context_pack_and_chat.py -k 'history or retry or conversation_deletion or outbox'` | 通过，11 tests | 核对批量历史元数据、稳定消息 ID、只装饰用户消息、失败后原 user turn 保留、幂等重试、会话删除与 outbox |
| Task 8 schema/worker 组合测试 | `python3 -m pytest -q runtime_api/tests/test_attachment_history_and_retry.py runtime_api/tests/test_attachment_worker.py runtime_api/tests/test_attachment_schema.py` | 通过，26 tests | 核对 cleanup outbox fresh/runtime schema、租约领取、物理删除完成和失败重排 |
| Task 8 当前工作区后端全量 | `python3 -m pytest -q runtime_api/tests` | 通过，1025 tests | 在包含既有 OpenCode、Web Search、Android 等未提交改动的当前工作区执行；提交前另做隔离暂存快照 |
| Task 8 隔离暂存快照 | `git checkout-index` 后运行 Task 8 聚焦测试与后端全量测试 | 聚焦 11 tests 通过；全量 2 failed、806 passed | 两个失败仍为 `test_chat_response_uses_explicit_memory_layer_fetchers` 和 `test_context_pack_pipeline_retrieves_local_memory_agenda_and_turns`，与 Task 7 前后的暂存 `HEAD` 基线相同；Task 8 新增行为均通过 |
| Task 9 附件检索与聊天接线 | `python3 -m pytest -q runtime_api/tests/test_attachment_chat_context.py runtime_api/tests/test_attachment_retrieval.py runtime_api/tests/test_chat_router.py runtime_api/tests/test_parallel_context_retrieval.py` | 通过，74 tests | 核对全文/混合证据规划、64K 配额、每附件最低配额、视觉升级、稳定 locator/citation、近 15 轮附件引用、并行 fetcher、逐页任务短路模型和引用白名单 |
| Task 9 附件/聊天组合回归 | 附件 API、模型、存储、worker、parser、历史、检索、context、HTTP/WS 组合测试 | 通过，192 tests | 核对 Task 9 没有破坏既有上传、解析、历史、重试、上下文和实时链路 |
| Task 9 当前工作区后端全量 | `python3 -m pytest -q runtime_api/tests` | 通过，1058 tests | 当前脏工作区完整回归；提交前仍需单独验证隔离暂存快照 |
| Task 9 隔离检查点聚焦回归 | `python3 -m pytest -q runtime_api/tests/test_attachment_chat_context.py runtime_api/tests/test_attachment_retrieval.py runtime_api/tests/test_chat_router.py runtime_api/tests/test_parallel_context_retrieval.py` | 通过，69 tests | 在 Task 8 干净提交上只叠加 Task 9 代码执行；不依赖工作区中未提交的 Web Search/OpenCode 改动 |
| Task 9 隔离检查点附件/聊天组合回归 | `python3 -m pytest -q runtime_api/tests/test_attachment*.py runtime_api/tests/test_chat_router.py runtime_api/tests/test_parallel_context_retrieval.py runtime_api/tests/test_context_pack_and_chat.py runtime_api/tests/test_realtime_ws.py` | 通过，278 tests | 上传、解析、生命周期、历史、HTTP/WS、上下文与新证据规划组合回归均通过 |
| Task 9 隔离检查点后端全量 | `python3 -m pytest -q runtime_api/tests` | 2 failed、839 passed | 失败仍为 `test_chat_response_uses_explicit_memory_layer_fetchers` 与 `test_context_pack_pipeline_retrieves_local_memory_agenda_and_turns`，和 Task 7/8 隔离基线相同；Task 9 未新增失败 |
| Task 10 结构化多模态聚焦回归 | `python3 -m pytest -q runtime_api/tests/test_attachment_model_content.py runtime_api/tests/test_attachment_retrieval.py::test_visual_escalation_is_relevant_bounded_and_not_a_large_document_sweep runtime_api/tests/test_attachment_retrieval.py::test_load_attachment_evidence_batches_manifest_chunks_and_vector_scores runtime_api/tests/test_attachment_chat_context.py::test_retrieve_attachment_context_for_chat_uses_current_ids_without_prior_query runtime_api/tests/test_model_non_thinking.py runtime_api/tests/test_model_gateway.py` | 通过，22 tests | 核对视觉派生文件从 DB 进入本轮证据、结构化 content 不被字符串化、最多 6 图、仅 provider 边界 base64、根目录逃逸拒绝、Qwen 非 thinking 及 reasoning 隐藏 |
| Task 10 附件/模型/实时组合回归 | `python3 -m pytest -q runtime_api/tests/test_attachment*.py runtime_api/tests/test_model_non_thinking.py runtime_api/tests/test_model_gateway.py runtime_api/tests/test_context_pack_and_chat.py runtime_api/tests/test_realtime_ws.py` | 通过，261 tests | 上传、解析、检索、历史、引用、HTTP/WS、模型网关与流式正式内容组合回归均通过；`compileall` 通过 |
| Task 10 隔离检查点后端全量 | `python3 -m pytest -q runtime_api/tests` | 2 failed、848 passed | 两个失败仍为既有 `test_chat_response_uses_explicit_memory_layer_fetchers` 与 `test_context_pack_pipeline_retrieves_local_memory_agenda_and_turns`；和 Task 7-9 隔离基线一致，Task 10 未新增失败 |
| Task 11 Web 附件状态机 | `node --test runtime_api/tests_js/chat_attachments.test.cjs` | 通过，8 tests | 覆盖纯附件/混合发送、8 个/64 MiB 限制、有序 ID、可见性轮询、重试/删除、稳定上传 ID、发送幂等和历史合并 |
| Task 11 Web/附件组合回归 | JS syntax check、Task 11 静态契约、既有工作台、附件 API/生命周期/历史/绑定组合测试 | 通过，101 pytest + 8 node tests | 鉴权预览、FormData、错误单次读取、终态停止、消息卡、既有日程/求职工作台均未回归 |
| Task 11 Chromium 响应式检查 | Playwright + Google Chrome，`1440x900` 与 `390x844` | 通过 | 注入图片/文档历史卡和失败上传草稿；两种宽度 `body/chat/message/card` 均无横向溢出，附件名称宽度分别 557/210px，composer 高度 203/193px，无 page error；发现并修复预览失败挤压和响应体二次读取噪声 |
| Task 11 隔离检查点后端全量 | `python3 -m pytest -q runtime_api/tests` | 2 failed、852 passed | 失败仍仅为既有 `test_chat_response_uses_explicit_memory_layer_fetchers` 与 `test_context_pack_pipeline_retrieves_local_memory_agenda_and_turns`；Task 11 未新增失败 |
| Task 12 Android WebView 选择器 TDD | `gradle -p android_app :app:testDebugUnitTest --tests '*WebWorkspaceAttachmentChooserTest'` | 通过，4 tests | 实际执行 chooser session：旧回调只取消一次、单/多选有序交付、重复交付无效、取消/重建清理；同时核对 SAF、允许格式、读权限和无相机入口契约 |
| Task 12 Android 全量单测 | `gradle -p android_app :app:testDebugUnitTest` | 通过，103 tests | WebView 文件选择器、键盘、旋转、远程浏览器、聊天和既有 Android 行为组合回归；Gradle 仅报告未来版本弃用警告 |
| Task 13 Android 悬浮窗附件聚焦测试 | Task 13 五个附件/实时测试类 | 通过，19 tests | 覆盖真实 multipart 大文件字节长度与 SHA-256、分块读取、进度/取消、稳定上传 ID、状态轮询、失败重试/移除、MIME 恢复、纯附件、混合消息、有序 ID 和 HTTP/WS 请求 ID 一致性 |
| Task 13 Android 全量单测与 APK | `gradle -p android_app :app:testDebugUnitTest`、`gradle -p android_app :app:assembleDebug` | 通过，116 tests；APK 构建成功 | 悬浮窗附件托盘、聊天、历史同步、实时通道和既有 Android 行为组合回归；`git diff --check` 通过 |
| Task 14 本地历史与附件对账聚焦测试 | `gradle -p android_app :app:testDebugUnitTest --tests '*LocalChatAttachmentHistoryTest' --tests '*AssistantApiClientTest' --tests '*FloatingChatContextTest'`；`python3 -m pytest -q tests/test_attachment_history_contract.py tests/test_attachment_history_and_retry.py` | Android 通过；后端 11 tests 通过 | 核对服务端稳定消息 ID、显式附件 ordinal、只按 `(message_id, attachment_id)` 归属附件、同名附件不串线、重复正文按出现次数消费已提交 pending、本地无原始字节/Base64/文件路径 |
| Task 14 Android 全量单测与 APK | `gradle -p android_app :app:testDebugUnitTest :app:assembleDebug` | 通过，121 tests；APK 构建成功 | 本地安全镜像、悬浮窗恢复、远端权威对账、附件元数据卡与既有上传/聊天/键盘行为组合回归；`git diff --check` 通过 |
| Task 14 隔离检查点后端全量 | `python3 -m pytest -q runtime_api/tests` | 2 failed、853 passed | 两个失败仍为既有 `test_chat_response_uses_explicit_memory_layer_fetchers` 与 `test_context_pack_pipeline_retrieves_local_memory_agenda_and_turns`，和 Task 7-13 隔离基线相同；Task 14 未新增失败 |
| Task 15 provenance/security/trace 聚焦回归 | Task 15 三个 runtime 测试文件；`worker/tests/test_attachment_memory_provenance.py` | runtime 13 tests、worker 2 tests 通过 | 核对 15 轮前不直接落附件长期记忆、批次及 fact 保留 attachment/turn/locator/hash/version、无文本 chunk 的视觉附件回退到整文件 hash、重处理版本追加不覆盖、注入/路径/HTML/密钥/base64 不进入 trace、鉴权预览/下载、检索与正式首字耗时回填 |
| Task 15 worker 全量 | `cd worker && python3 -m pytest -q tests` | 135 tests 通过 | 事实图谱、日程、语义抽取与新附件 provenance 合并组合回归无新增失败 |
| Task 15 隔离检查点后端全量 | `python3 -m pytest -q runtime_api/tests --tb=short` | 2 failed、867 passed | 两个失败仍为 Task 7-14 已记录的既有上下文层测试；Task 15 未新增失败 |
| Task 18 查看器聚焦回归 | `python3 -m pytest -q runtime_api/tests/test_static_file_viewer.py`；Node URL helper；Android FileViewer/入口契约 | 通过 | 覆盖 source allowlist、密码不入 URL、自托管资产、Blob-to-File、内部 Activity、相对 URL 归一化和版本资源 immutable 缓存 |
| Task 18 本地真实格式渲染 | Playwright，`412x915` | PNG、PDF、DOCX、PPTX、XLSX 均通过 | 核对真实内容、移动端无横向溢出、PPTX 多页和缩放工具条；不是转 PDF 后预览 |
| Task 18 云端/Android 真机 | 私有云真实原件 + `DQYTCYFMO7VSEAJB` | PPTX 真机通过 | 真机直接打开多页 PPTX、关闭返回 App、悬浮球保留；未弹 WPS/小米查看器/系统选择器 |
| Task 18 最终主工作区回归 | `python3 -m pytest -q runtime_api/tests`；Node；`gradle -p android_app clean testDebugUnitTest assembleDebug`；`docker compose build runtime-api`；Compose；`git diff --check` | 后端 1094 passed；Node 11 passed；Android BUILD SUCCESSFUL；fresh Docker 镜像构建成功；其余通过 | 最终 APK 已覆盖安装到真机，真实 PPTX 再次打开并在 5 秒内显示多页，关闭返回完整 App；镜像仅含六个 renderer、docx/libarchive/pdf/pptx/xlsx vendor，无 EPUB/node_modules |
| 工作区 | `git status --short` | 脏工作区 | 存在既有 OpenCode、Web Search、Android 等改动；不得重置或整体暂存 |

## 规格覆盖状态

| 规格域 | 状态 | 自动化证据 | 真实环境证据 | 已知 Gap | 阻塞 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 产品输入：纯附件/附件+文字 | 代码与自动化完成，未部署 | `ChatIn`、HTTP 和 WebSocket 均接收有序附件 ID；空文本附件消息使用统一附件理解指令；Web 完整 App、Android WebView 与悬浮窗均已接选择器；传输一致性测试通过 | 无 | 尚未在云端和真机核对真实选择、上传、解析、纯附件与混合发送 | 云环境部署待 Task 16 | Task 16、17 |
| 支持格式与拒绝格式 | 轻量解析代码与自动化完成，未部署 | 检测测试覆盖 11 种允许格式与恶意输入；`test_attachment_parsers.py` 逐项验证图片、PDF、DOCX、PPTX、XLSX、CSV、TXT、MD 的实际事实和稳定 locator | 无 | LibreOffice 版式渲染与真实 Qwen 视觉升级尚未接入；真实文件集待 Task 17 | 无 | Task 9、10、17 |
| 私有流式存储 | 代码与自动化完成，未部署 | `test_attachment_storage.py` 核对 256 KiB 分块、SHA-256、越限立即中止、断连清理、`fsync` 后原子替换、随机磁盘名、路径逃逸拒绝 | 无 | 尚未接上传 API 和真实挂载卷 | 云环境部署待 Task 16 | Task 3、16、17 |
| 四表数据模型 | 代码与自动化完成，未部署 | runtime/fresh-install schema 契约测试通过；后端全量 903 passed | 无 | 尚未在真实 PostgreSQL 执行迁移并核对约束 | 云环境部署待 Task 16 | Task 16、17 |
| 上传与草稿幂等 | 代码与自动化完成，未部署 | `test_attachment_api.py` 10 条用例验证鉴权、multipart、202 草稿、安全响应、24 小时过期、断连/越限/拒绝、相同字节幂等及不同字节 409；后端全量 950 passed | 无 | 尚未在真实 PostgreSQL、Redis、挂载卷和客户端上传中验收 | 云环境部署待 Task 16 | Task 10-12、16、17 |
| 状态、预览、原件、重试、删除 API | 代码与自动化完成，未部署 | `test_attachment_lifecycle_api.py` 17 条用例验证安全元数据、图片衍生预览、通用文件卡、原件分块下载、RFC 5987 中文名、鉴权无字节泄露、原件哈希校验、单一版本重试、两阶段物理删除、attached 拒绝、过期与缺失 ID | 无 | 尚未在真实 PostgreSQL、Redis、云端卷及 Web/Android 客户端验收 | 云环境部署待 Task 16 | Task 11-13、16、17 |
| 有界异步解析 Worker | 代码与自动化完成，未部署 | `test_attachment_worker.py` 14 条用例验证版本去重、stale-version 隔离、状态迁移、分类并发、超时、安全失败、租约/崩溃恢复、可重试两阶段清理、孤儿临时文件及 attached 排除；Compose 约束 CPU 0.75、内存 768MB、非 root、只读根目录和共享私有卷 | 无 | Redis/PostgreSQL 真实进程与资源峰值尚未验收 | 云环境部署待 Task 16 | Task 16、17 |
| 图片/PDF/Office/表格/文本解析 | 轻量解析与语义自动化完成，未部署 | 14 组 parser 测试验证 EXIF 旋转、GIF 去重帧、数字/扫描 PDF 与按页渲染、DOCX 标题/表格/链接、31 张 PPTX 备注、XLSX 公式+缓存值、长 CSV、UTF-8/GB18030、Markdown 代码块；worker 在同一 DB 事务保存 manifest/chunks/derivatives 后才置 ready | 无 | Office 版式渲染、图表视觉理解和 visual-result 的生产缓存读写随 Task 9/10 接入；尚无云端真实性能数据 | 无 | Task 9、10、16、17 |
| 消息原子绑定和幂等 | 代码与自动化完成，未部署 | 同一事务 `FOR UPDATE` 锁定草稿，完整校验后写 user turn、有序关系并置为 attached；非法集合零写入；并发同草稿仅一个成功；相同 `client_request_id` 复用原 turn，载荷变化返回 409；HTTP/WS 错误码一致 | 无 | 尚未在真实 PostgreSQL 隔离级别、Redis 和双客户端并发下验收 | 云环境部署待 Task 16 | Task 16、17 |
| 历史、失败重试和会话删除 | 代码与自动化完成，未部署 | 历史按本批 user turn 一次查询有序附件元数据；assistant 消息不输出空附件；重试复用原 user turn 和附件绑定并以稳定 key 防重复；删除在数据库事务内先写相对路径 outbox，再级联删除，worker 租约消费且失败退避重排；Task 8 聚焦 11 tests、组合 26 tests、当前工作区全量 1025 tests 通过 | 无 | 重试当前只重建原消息和附件元数据；附件正文/视觉证据选择由 Task 9 接入。真实 PostgreSQL outbox、worker 崩溃恢复和客户端重试尚未验收 | 云环境部署待 Task 16 | Task 9、16、17 |
| 全文/混合检索/逐页检查 | 代码与自动化完成，未部署 | 小附件全文、PDF>20/PPTX>30 或 >24K 混合检索；按附件最低配额后全局重排；显式逐页请求持久化 `attachment_full_inspection`，worker 用 lease 和 `SKIP LOCKED` 分批推进，终态明确失败/未处理 locator；真实 `/api/chat` 已接并行附件 fetcher | 无 | 尚未在真实 PostgreSQL/Redis 跑逐页任务、观察崩溃恢复和客户端任务轮询 | 云环境部署待 Task 16 | Task 10、16、17 |
| 视觉升级和最多 6 项限制 | 代码与自动化完成，未部署 | 低文本密度、图片/图表、视觉问题和文本不足进入 visual evidence；DB 同步选择匹配 locator 的私有派生图；稳定排序且最多 6 项，超限写 `visual_limit`；组合回归通过 | 无 | 尚未用真实 Qwen 与真实图片/PDF 核对视觉结论、引用和资源峰值 | 云环境部署待 Task 16 | Task 16、17 |
| 256K 上下文与附件 64K 配额 | 代码与自动化完成，未部署 | attachment section 独立上限 64K，并受 256K 总预算、已保留上下文和输出预算共同限制；保留既有最近 15 轮上下文；排除原因进入 evidence plan | 无 | 尚未用真实长 PDF/PPTX 测 token 估算、首 token 和内存峰值 | 云环境部署待 Task 16 | Task 10、16、17 |
| Qwen 结构化多模态与非 thinking | 代码与自动化完成，未部署 | 文本 content 保持字符串；视觉 content 为有序 `text/image_url`；私有相对路径只在 provider 边界校验后读取并转 data URL；输入不变；Qwen 请求显式 `enable_thinking=false`/`reasoning_effort=none`；正式响应忽略 reasoning；安全 trace 不含 base64/path | 无 | 尚未向线上 `qwen3.6` 发真实图文请求并核对首字、正式答案与视觉事实；未验证上游是否完整支持当前 data URL 契约 | 云环境与模型端待 Task 16/17 | Task 16、17 |
| 稳定引用与覆盖声明 | 代码与自动化完成，未部署 | PDF 页、PPTX 张、DOCX 章节、XLSX sheet/range、图片和文本行号有稳定 label；答案只能引用本轮选中 label，未选页引用会被移除并产生 validation trace；partial coverage 明确未覆盖位置 | 无 | 尚未用真实 Qwen 输出验证引用服从率；逐页终态摘要尚未在双客户端展示验收 | 云环境部署待 Task 16 | Task 10、16、17 |
| 长期记忆来源 | 代码与自动化完成，未部署 | 只有正常 15 轮 dialogue batch 可携带附件来源；worker 将 attachment/turn/locator/hash/version 写入 fact metadata；相同事实重处理时对 provenance 做 JSONB 去重追加而非覆盖；runtime/worker 聚焦 5 tests 通过 | 无 | 当前 provenance 以对话批次为归属边界；尚未在真实 PostgreSQL 验证冲突更新和真实附件对话形成的 fact | 云环境部署待 Task 16 | Task 16、17 |
| Web 完整 App 交互 | 代码与自动化完成，未部署 | 8 个纯 JS 状态机测试、4 个静态契约、101 个 Web/附件组合回归；真实 Chromium 桌面/390px 响应式检查通过 | 本地真实 Chromium 已核对布局；上传接口使用静态服务器故意得到失败态，只验证失败 UI，不冒充真实上传成功 | 尚未连接真实 PostgreSQL/Redis/worker 完成上传、ready、纯附件/混合发送、鉴权预览下载和服务端历史重载 | 云环境部署待 Task 16 | Task 13-16、17 |
| Android 完整 App WebView 选择器 | 代码与自动化完成，未部署 | 4 条 chooser 行为/契约测试；Android 全量 103 tests；`ACTION_OPEN_DOCUMENT` 多选、允许 MIME、旧回调取消、单/多 URI 有序返回、持久读权限、状态恢复和无相机入口 | 无 | 尚未在真机点击完整 App 回形针并选择单文件、多文件和取消；尚未验证具体文档 provider 是否授予可持久权限 | 真机待 Task 16 | Task 16、17 |
| Android 悬浮窗交互 | 代码与自动化完成，未部署 | 19 条聚焦测试、116 条 Android 全量测试和 debug APK 构建通过；原生 `ACTION_OPEN_DOCUMENT`、允许格式、持久读权限、分块流式上传、进度/取消、ready 轮询、失败重试/移除、图片缩略图/文档图标、纯附件/混合发送、HTTP/WS 同序附件 ID 均已接入 | 无 | 尚未在真机核对不同文档 provider 的 URI 授权、旋转/服务重建、真实上传/解析 ready、失败重试、纯附件与混合发送以及服务端历史重载 | 真机与云环境待 Task 16 | Task 16、17 |
| 双界面历史一致性 | 代码与自动化完成，未部署 | 服务端历史 DTO 与 Android 本地镜像保留相同有序安全附件元数据；服务端稳定 ID 权威覆盖已发送消息，删除项不在本地复活；本地只保留尚未被服务端同角色/正文出现次数消费的无 ID pending，且草稿附件始终留在原控制器；Android 全量 121 tests、后端聚焦 11 tests 通过 | 无 | 尚未在真实服务器、完整 App 与悬浮窗之间执行上传后切换、进程重启、离线 pending、服务端删除和附件卡重载；历史附件卡当前只展示安全元数据，真实鉴权下载/打开由 Task 16/17 验收 | 云环境与真机待 Task 16 | Task 16、17 |
| 安全与提示注入防护 | 代码与自动化完成，未部署 | hostile-file、ZIP traversal、加密/损坏容器、脚本伪装、parser timeout、鉴权下载均有回归；模型系统提示将附件作为不可信证据；trace 严格 allowlist，拒绝正文、绝对路径、HTML、base64、API key 和文档内工具指令 | 无 | 尚未以真实恶意文件和线上模型验证提示注入服从率 | 云环境部署待 Task 16 | Task 16、17 |
| 隐私安全 Trace | 代码与自动化完成但生产计时仍有 Gap，未部署 | trace 输出 request/client/turn ID、重试数、附件类型/状态/版本、selected/excluded locator、hash、视觉数；检索耗时及 HTTP/WS 正式首字和总耗时已回填；聚焦 trace/security tests 通过 | 无 | 上传/hash/store/parse/chunk/embed/render 的生产者尚未逐阶段产出真实耗时，当前字段为 `null` 而不是伪造 0；附件 chunk embedding 当前也没有生产写入路径，因此 `embed_ms` 无真实值 | 云环境部署待 Task 16 | Task 16 先测量并决定是否新增持久化/遥测载体，Task 17 核对线上 trace |
| 4 核 8G 性能与部署 | 容器预算契约完成，未完整负载实测 | 自动化锁定 attachment-worker 并发、非 root、只读根文件系统和 Compose 资源上限；`docker compose config --quiet` 通过；核心解析、Chromium 采集和后台任务未因 2C4G 兼容而删除 | 云端本次真实五格式上传/解析和聊天期间 API 保持健康 | 尚未以 25MB 上传、31 页/幻灯片解析和并发聊天采集完整 CPU/RSS/P95 数据 | 无 | Task 17 完成生产负载矩阵 |
| 云端、真实文件、Qwen、Android 真机 | 未开始 | 无 | 无 | 全部真实验收尚未执行 | 需要后续真机在线 | Task 17 |
| Nomi 内置原格式查看器 | 核心功能完成，真机格式矩阵部分完成 | 查看器/API/URL/Android 契约、7 条静态资源测试、11 条 URL helper、Android 全量与 APK 构建通过；精简 Flyfish 资产固定为 `2.1.29`；fresh runtime-api 镜像构建通过并核对无 EPUB/node_modules；`Pillow==10.4.0` 与 `fastembed==0.4.2` 兼容性已有回归测试 | 云端真实 PNG/PDF/DOCX/PPTX/XLSX 均 ready 且内容解析合理；本地移动端 Chromium 五格式直接渲染；真机真实 PPTX 多页查看、二次打开、关闭返回 App 均通过 | CSV/TXT/MD 和 PNG/PDF/DOCX/XLSX 尚未逐一在真机 UI 打开；旋转、离线/损坏错误页、连续十次开关和内存观测未完成；首次 PPTX 会下载约 1.9MB renderer/worker，弱网首开较慢，已增加一年 immutable 缓存但新版缓存响应头待再次云端部署后复测 | SSH 当前偶发 banner timeout，不影响已部署版本的真机访问，但阻塞本轮缓存头增量部署 | 完成剩余 Task 18 Step 10 矩阵并采集首开/复开时延 |

## 执行纪律

1. 每个行为先增加能正确失败的测试，再写最小实现。
2. 任何真实环境阻塞都记录在本文件，不使用 fake 成功替代。
3. 每次提交前只暂存附件功能的新文件或精确 hunk。
4. 解析成功必须核对事实和 locator；模型成功必须核对实际证据、引用和覆盖范围。
5. 真机验收必须同时覆盖完整 App 和悬浮窗，并核对服务端历史一致性。
