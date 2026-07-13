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
| 工作区 | `git status --short` | 脏工作区 | 存在既有 OpenCode、Web Search、Android 等改动；不得重置或整体暂存 |

## 规格覆盖状态

| 规格域 | 状态 | 自动化证据 | 真实环境证据 | 已知 Gap | 阻塞 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 产品输入：纯附件/附件+文字 | 部分完成 | `test_attachment_models.py` 已验证输入域规则 | 无 | HTTP/WS 尚未接收附件 ID，`ChatIn` 仍待 Task 7 接入 | 无 | Task 7 |
| 支持格式与拒绝格式 | 检测层代码与自动化完成，解析内容未完成 | `test_attachment_detection.py` 覆盖 11 种允许格式及伪装可执行文件、旧 Office、脚本、损坏/加密容器、ZIP traversal/bomb、图片像素上限 | 无 | 尚未在 Worker 中调用检测层；正文与视觉衍生物待 Task 4、5 | 无 | Task 4、5、17 |
| 私有流式存储 | 代码与自动化完成，未部署 | `test_attachment_storage.py` 核对 256 KiB 分块、SHA-256、越限立即中止、断连清理、`fsync` 后原子替换、随机磁盘名、路径逃逸拒绝 | 无 | 尚未接上传 API 和真实挂载卷 | 云环境部署待 Task 16 | Task 3、16、17 |
| 四表数据模型 | 代码与自动化完成，未部署 | runtime/fresh-install schema 契约测试通过；后端全量 903 passed | 无 | 尚未在真实 PostgreSQL 执行迁移并核对约束 | 云环境部署待 Task 16 | Task 16、17 |
| 上传与草稿幂等 | 代码与自动化完成，未部署 | `test_attachment_api.py` 10 条用例验证鉴权、multipart、202 草稿、安全响应、24 小时过期、断连/越限/拒绝、相同字节幂等及不同字节 409；后端全量 950 passed | 无 | 尚未在真实 PostgreSQL、Redis、挂载卷和客户端上传中验收 | 云环境部署待 Task 16 | Task 10-12、16、17 |
| 状态、预览、原件、重试、删除 API | 未开始 | 无 | 无 | 端点未建立 | 无 | Task 6 |
| 有界异步解析 Worker | 未开始 | 无 | 无 | 没有队列、并发门禁和超时隔离 | 无 | Task 4 |
| 图片/PDF/Office/表格/文本解析 | 未开始 | 无 | 无 | 没有统一解析结果与 locator | 无 | Task 5 |
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
| 安全与提示注入防护 | 文件入口安全部分完成 | hostile-file 测试已验证 ZIP bomb、ZIP traversal、加密/损坏容器、脚本与伪装可执行文件；错误信息不回显本地路径 | 无 | 文档内提示注入、鉴权下载、审计和真实恶意样本待后续任务 | 无 | Task 6、8、14、17 |
| 隐私安全 Trace | 未开始 | 无 | 无 | 无附件证据和耗时 trace | 无 | Task 15 |
| 2 核 4G 性能与部署 | 未开始 | 无 | 无 | 无 attachment-worker 资源实测 | 无 | Task 16、17 |
| 云端、真实文件、Qwen、Android 真机 | 未开始 | 无 | 无 | 全部真实验收尚未执行 | 需要后续真机在线 | Task 17 |

## 执行纪律

1. 每个行为先增加能正确失败的测试，再写最小实现。
2. 任何真实环境阻塞都记录在本文件，不使用 fake 成功替代。
3. 每次提交前只暂存附件功能的新文件或精确 hunk。
4. 解析成功必须核对事实和 locator；模型成功必须核对实际证据、引用和覆盖范围。
5. 真机验收必须同时覆盖完整 App 和悬浮窗，并核对服务端历史一致性。
