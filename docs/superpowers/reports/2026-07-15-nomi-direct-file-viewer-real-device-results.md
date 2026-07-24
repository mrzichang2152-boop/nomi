# Nomi 内置原格式查看器真实环境验收

**日期：** 2026-07-15
**范围：** 统一聊天附件 Task 18
**云端：** 私有云 Nomi Runtime
**Android 真机：** `DQYTCYFMO7VSEAJB`，Redmi `24094RAD4C`

## 1. 实现结论

Nomi 已具备自托管、同源鉴权的原格式文件查看器。聊天附件和 Nomi 生成产物默认进入
`/viewer`，不再通过 `ACTION_VIEW`、WPS、小米文档查看器或“先下载再打开”完成查看。
V1 使用 Apache-2.0 的 `@file-viewer/web-full@2.1.29`，只打包 image、pdf、word、
presentation、spreadsheet、text 及 docx/pdf/pptx/xlsx vendor 资源。

## 2. TDD 与缺陷修复

1. URL、Web/API、Android Activity 和入口契约均先执行 RED，再实现至 GREEN。
2. 首次真机打开时发现相对 `/viewer?... ` 被 Android 当成 `file:///viewer%3F...`，
   实际显示 `ERR_ACCESS_DENIED`。
3. 新增失败测试 `trustedRelativeViewerUrlIsNormalizedBeforeWebViewLoadsIt`，随后实现
   `FileViewerUrls.normalizeTrustedViewerUrl`：只允许配置的 Nomi origin，保留原 query，
   拒绝外部 origin。
4. 真机重新安装后，相同真实 PPTX 已正常打开。
5. 首次弱网下载 Office renderer 较慢，因此又先增加缓存失败测试，再实现
   `ImmutableViewerStaticFiles`，只为固定版本的
   `/static/vendor/file-viewer/` 返回一年 `immutable` 缓存，不改变普通静态资源。
6. fresh Docker 构建首次暴露 `fastembed==0.4.2` 与 `Pillow==11.3.0` 的依赖冲突。
   新增兼容性回归测试后将 Pillow 固定为双方约束均接受的 `10.4.0`，再执行完整镜像构建、
   解析器测试和后端全量回归。

## 3. 真实文件矩阵

| 格式 | 云端附件 ID | 已知事实 | 云端解析 | 本地移动端直接渲染 | Android 真机直接渲染 |
| --- | --- | --- | --- | --- | --- |
| PNG | `dbfb8c9b-859c-42bf-8282-7ac5ad379e88` | 800×450 测试图 | 通过，尺寸正确 | 通过 | 未执行 |
| PDF | `f4ee221b-75fc-41fa-834c-7fbd6c1d40d7` | 固定测试正文 | 通过，正文一致 | 通过 | 未执行 |
| XLSX | `5289f3b4-43c6-47e8-8f9f-11c285351ef5` | A1:B2 固定表格 | 通过，单元格一致 | 通过，可见 Sheet | 未执行 |
| PPTX | `45b273d5-9c5f-49d3-920e-28ae6f0649ad` | 固定标题与正文 | 通过，slide 内容一致 | 通过，多张可滚动 | 通过 |
| DOCX | `5b99eb8c-8f76-48df-a8f0-e0f1a3f78e1d` | 固定标题与正文 | 通过，段落一致 | 通过 | 未执行 |

云端测试会话 `f04dc605-2eee-47ed-a03d-8af546f1951c` 同时绑定五个真实附件；
模型实际回答正确区分了图片、PDF、表格、幻灯片和 Word 正文。该结果验证上传、解析、
证据选择和原件 API，不用来冒充五种格式均已完成 Android UI 验收。

## 4. 真机实际结果

| 用例 | 预期 | 实际 | 结论 |
| --- | --- | --- | --- |
| 从真实产物卡打开 PPTX | 进入 Nomi Viewer | 进入 `NomiFileViewerActivity`，服务端 `/viewer`、PPTX 原件和 renderer 均返回 200 | 通过 |
| 内容正确性 | 展示真实 PPTX 多页内容 | 标题、中文正文和多张幻灯片可见，工具条显示 27%/1:1/缩放 | 通过 |
| 原格式 | 不转 PDF/图片 | 使用 presentation renderer 和 pptx worker，原件为 PPTX | 通过 |
| 外部 App | 不弹系统选择器 | 未出现 WPS/小米文档查看器/授权弹窗 | 通过 |
| 关闭返回 | 返回完整 App 且悬浮球保留 | 点击关闭和系统返回均回到 `WebWorkspaceActivity`，悬浮球仍在 | 通过 |
| 二次打开 | 可再次加载 | 第二次打开同一 PPTX 并正常显示 | 通过 |

真机证据：

- `/tmp/nomi-device-ppt-viewer-fixed-final.png`
- `/tmp/nomi-device-ppt-viewer-cached-second-ready.png`
- `/tmp/nomi-device-viewer-close-return.png`
- `/tmp/nomi-device-final-main-apk-viewer-open.png`（主工作区最终 APK 覆盖安装后复验）

本地五格式移动端证据：

- `/tmp/nomi-viewer-final-docx.png`
- `/tmp/nomi-viewer-final-pptx.png`
- `/tmp/nomi-viewer-final-xlsx.png`
- `/tmp/nomi-viewer-final-pdf.png`
- `/tmp/nomi-viewer-final-png.png`

## 5. 未完成与性能事实

1. 尚未在 Android 真机逐一打开 PNG、PDF、DOCX、XLSX、CSV、TXT 和 Markdown；这些格式
   只有真实云端解析和本地移动端 Chromium 查看证据。
2. 尚未执行旋转、损坏文件、离线重试、连续十次开关和内存/RSS 观测。
3. 第一次打开 PPTX 时，真机弱网下载约 1.3MB presentation renderer 用时约 37 秒，
   约 572KB worker 用时约 21 秒；功能最终成功，但首开体验不达理想目标。
4. 已为版本固定资源增加 `immutable` 缓存。该增量尚待 SSH 恢复后重新部署并采集新的
   首开/复开时延，不能把本地 GREEN 直接写成线上性能已通过。
5. `npm audit` 对完整依赖树报告 5 个 high 级问题，来源包含未选择的 EPUB/xmldom 链；
   生产构建白名单不复制 EPUB，也不复制 `node_modules`。这降低运行暴露面，但仍应在升级
   Flyfish 版本时重新审计，不能当作依赖树零风险。

## 6. 验收判定

**核心功能：通过。** Nomi 能在真机内部直接查看真实 PPTX，关闭后回到 App，且不调用第三方
查看器；五种主要格式已在真实文件和移动端渲染器层核对内容。

**完整 Task 18 Step 10：部分通过。** 其余真机格式、异常态、旋转、压力与缓存增量云端时延
仍是明确遗留，见 Gap 报告，不标记为全部完成。

## 7. 最终自动化回归

- 后端：`1094 passed`，包含运行时依赖兼容性测试。
- Web/JS：`11 passed`。
- Android：`clean testDebugUnitTest assembleDebug`，`BUILD SUCCESSFUL`。
- Compose：配置解析通过。
- Docker：`docker compose build runtime-api` fresh 构建成功，最终镜像为
  `background-runtime-api:latest`。
- 文件资产：最终镜像中只有 image/pdf/word/presentation/spreadsheet/text 六个 renderer，
  docx/libarchive/pdf/pptx/xlsx vendor，以及查看器主 IIFE/manifest/许可证；资产约
  `25,062,327` bytes，未包含 EPUB 或 `node_modules`。
- 代码格式：`git diff --check` 通过。
