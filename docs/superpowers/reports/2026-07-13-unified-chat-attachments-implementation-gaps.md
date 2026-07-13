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
| 工作区 | `git status --short` | 脏工作区 | 存在既有 OpenCode、Web Search、Android 等改动；不得重置或整体暂存 |

## 规格覆盖状态

| 规格域 | 状态 | 自动化证据 | 真实环境证据 | 已知 Gap | 阻塞 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 产品输入：纯附件/附件+文字 | 部分完成 | `test_attachment_models.py` 已验证输入域规则 | 无 | HTTP/WS 尚未接收附件 ID，`ChatIn` 仍待 Task 7 接入 | 无 | Task 7 |
| 支持格式与拒绝格式 | 轻量解析代码与自动化完成，未部署 | 检测测试覆盖 11 种允许格式与恶意输入；`test_attachment_parsers.py` 逐项验证图片、PDF、DOCX、PPTX、XLSX、CSV、TXT、MD 的实际事实和稳定 locator | 无 | LibreOffice 版式渲染与真实 Qwen 视觉升级尚未接入；真实文件集待 Task 17 | 无 | Task 9、10、17 |
| 私有流式存储 | 代码与自动化完成，未部署 | `test_attachment_storage.py` 核对 256 KiB 分块、SHA-256、越限立即中止、断连清理、`fsync` 后原子替换、随机磁盘名、路径逃逸拒绝 | 无 | 尚未接上传 API 和真实挂载卷 | 云环境部署待 Task 16 | Task 3、16、17 |
| 四表数据模型 | 代码与自动化完成，未部署 | runtime/fresh-install schema 契约测试通过；后端全量 903 passed | 无 | 尚未在真实 PostgreSQL 执行迁移并核对约束 | 云环境部署待 Task 16 | Task 16、17 |
| 上传与草稿幂等 | 代码与自动化完成，未部署 | `test_attachment_api.py` 10 条用例验证鉴权、multipart、202 草稿、安全响应、24 小时过期、断连/越限/拒绝、相同字节幂等及不同字节 409；后端全量 950 passed | 无 | 尚未在真实 PostgreSQL、Redis、挂载卷和客户端上传中验收 | 云环境部署待 Task 16 | Task 10-12、16、17 |
| 状态、预览、原件、重试、删除 API | 代码与自动化完成，未部署 | `test_attachment_lifecycle_api.py` 17 条用例验证安全元数据、图片衍生预览、通用文件卡、原件分块下载、RFC 5987 中文名、鉴权无字节泄露、原件哈希校验、单一版本重试、两阶段物理删除、attached 拒绝、过期与缺失 ID | 无 | 尚未在真实 PostgreSQL、Redis、云端卷及 Web/Android 客户端验收 | 云环境部署待 Task 16 | Task 11-13、16、17 |
| 有界异步解析 Worker | 代码与自动化完成，未部署 | `test_attachment_worker.py` 14 条用例验证版本去重、stale-version 隔离、状态迁移、分类并发、超时、安全失败、租约/崩溃恢复、可重试两阶段清理、孤儿临时文件及 attached 排除；Compose 约束 CPU 0.75、内存 768MB、非 root、只读根目录和共享私有卷 | 无 | Redis/PostgreSQL 真实进程与资源峰值尚未验收 | 云环境部署待 Task 16 | Task 16、17 |
| 图片/PDF/Office/表格/文本解析 | 轻量解析与语义自动化完成，未部署 | 14 组 parser 测试验证 EXIF 旋转、GIF 去重帧、数字/扫描 PDF 与按页渲染、DOCX 标题/表格/链接、31 张 PPTX 备注、XLSX 公式+缓存值、长 CSV、UTF-8/GB18030、Markdown 代码块；worker 在同一 DB 事务保存 manifest/chunks/derivatives 后才置 ready | 无 | Office 版式渲染、图表视觉理解和 visual-result 的生产缓存读写随 Task 9/10 接入；尚无云端真实性能数据 | 无 | Task 9、10、16、17 |
| 消息原子绑定和幂等 | 未开始 | 无 | 无 | HTTP/WS 未接收附件 ID | 无 | Task 7 |
| 历史、失败重试和会话删除 | 未开始 | 无 | 无 | 历史无附件，失败重试未复用 user turn | 无 | Task 8 |
| 全文/混合检索/逐页检查 | 未开始 | 无 | 无 | 附件证据不进入上下文 | 无 | Task 9 |
| 视觉升级和最多 6 项限制 | 未开始 | 无 | 无 | 未选择和渲染视觉证据 | 无 | Task 9、10 |
| 256K 上下文与附件 64K 配额 | 未开始 | 无 | 无 | 没有附件预算与排除 trace | 无 | Task 9 |
| Qwen 结构化多模态与非 thinking | 未开始 | 无 | 无 | 当前消息 content 会被字符串化 | 无 | Task 10 |
| 稳定引用与覆盖声明 | 未开始 | 无 | 无 | 回答无法证明读取位置 | 无 | Task 9、17 |
| 长期记忆来源 | 未开始 | 无 | 无 | 未保存 attachment/turn/locator/version 来源 | 无 | Task 15 |
| Web 完整 App 交互 | 未开始 | 无 | 无 | 无选择器、托盘、状态卡和附件历史 | 无 | Task 11、12 |
| Android 悬浮窗交互 | 未开始 | 无 | 无 | 无原生选择、流式上传和托盘 | 无 | Task 13 |
| 双界面历史一致性 | 未开始 | 无 | 无 | 本地镜像无附件元数据 | 无 | Task 14 |
| 安全与提示注入防护 | 文件入口、解析失败隔离和鉴权下载完成，未部署 | hostile-file 测试验证 ZIP bomb、ZIP traversal、加密/损坏容器、脚本与伪装可执行文件；解析异常不回显路径；持久化失败清除未提交衍生文件；物理删除失败可恢复；预览/原件无密码返回 401 且不含文件字节，响应含 `nosniff` 与私有缓存头 | 无 | 文档内提示注入、审计和真实恶意样本待后续任务 | 无 | Task 8、14、17 |
| 隐私安全 Trace | 未开始 | 无 | 无 | 无附件证据和耗时 trace | 无 | Task 15 |
| 2 核 4G 性能与部署 | 容器预算契约完成，未实测 | 自动化锁定 attachment-worker `0.75 CPU / 768MB`、分类并发 `2/1/1`、非 root 和只读根文件系统；`docker compose config --quiet` 通过 | 无 | 尚未构建镜像并以 25MB 上传、31 页解析和并发聊天做资源实测 | 云环境部署待 Task 16 | Task 16、17 |
| 云端、真实文件、Qwen、Android 真机 | 未开始 | 无 | 无 | 全部真实验收尚未执行 | 需要后续真机在线 | Task 17 |

## 执行纪律

1. 每个行为先增加能正确失败的测试，再写最小实现。
2. 任何真实环境阻塞都记录在本文件，不使用 fake 成功替代。
3. 每次提交前只暂存附件功能的新文件或精确 hunk。
4. 解析成功必须核对事实和 locator；模型成功必须核对实际证据、引用和覆盖范围。
5. 真机验收必须同时覆盖完整 App 和悬浮窗，并核对服务端历史一致性。
