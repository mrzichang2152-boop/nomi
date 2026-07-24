# Android Inline Notifications and File Viewer Verification

Date: 2026-07-22

## Result

方案 A 已实现并部署：确认/提醒内容进入聊天消息流，不再使用覆盖聊天内容的独立确认层；Office 文件由 Nomi 原格式查看器直接解析，保留独立的下载原文件命令。

当前结论是“方案 A 已完成真机闭环验收”。服务器下载成功没有被直接视为通过；最终结论来自 Android 真机落盘、回拉、逐字节比较和 OOXML 完整性检查。

## Implemented Behavior

- 前台工作台、悬浮对话框或文件查看器可见时，主动提醒不再弹出覆盖式 overlay。
- 悬浮对话框打开时，主动内容按时间顺序插入消息流，且不污染普通问答历史。
- PPTX、DOCX、XLSX、PDF 和图片使用原始文件直接查看，不先转 PDF。
- 查看器从 `Content-Disposition` 和 `Content-Type` 解析可信文件名与 MIME。
- Android 下载使用带 `x-par-password` 的同源请求，通过 `MediaStore` 写入 `Download/Nomi`。
- 下载按钮有重复点击保护、失败清理和 UI 完成回调。
- 静态资源使用 `20260722-file-viewer-v2` 版本参数，避免 Android WebView 继续执行旧缓存脚本。

## Automated Verification

- `python3 -m pytest -q runtime_api/tests/test_static_file_viewer.py runtime_api/tests/test_static_assistant_draft_chat_cards.py runtime_api/tests/test_static_chat_attachments.py runtime_api/tests/test_static_workbench_agenda_tab.py`
  - Result: `67 passed`.
- `node --test runtime_api/tests_js/file_viewer_links.test.cjs`
  - Result: `9 passed`.
- `gradle :app:testDebugUnitTest :app:assembleDebug`
  - Result: `BUILD SUCCESSFUL`.

测试覆盖的不只是 HTTP 成功：还检查了提醒表面决策、前台生命周期、文件名/MIME 优先级、路径清理、同源限制、认证头、MediaStore 目录、失败行清理、重复点击保护和缓存版本标识。

## Cloud Verification

- `http://127.0.0.1/health` through the cloud host returned `{"status":"ok"}`.
- `/viewer` references `viewer.css`, `file-viewer-links.js`, and `viewer.js` with version `20260722-file-viewer-v2`.
- Deployed `viewer.js` exposes `window.NomiViewerBuild = "20260722-file-viewer-v2"` and restores the download command after renderer settling.
- Real artifact: `artifact_033a8a150b574b9f8bd6f6b7b4309dda`.
- Filename: `Nomi_auto_delivery_visual_20260720.pptx`.
- Size: `30,728` bytes.
- SHA-256: `0ebd6caab311c2a27bbf3c9931513d6a519752c23af65a03b362bb561e8c415c`.
- `file` result: `Microsoft OOXML`.
- `unzip -t` result: all OOXML entries valid, no compressed-data errors.

## Physical Device Evidence

- The physical Android device opened the real cloud artifact in `NomiFileViewerActivity`.
- Both PPT slides rendered directly in the Nomi viewer.
- The title showed the real filename and `31 KB · 原格式查看`.
- The download and close commands were visible in stable fixed-size controls.
- A real Nomi Gmail result/reminder card appeared inside the conversation flow above the composer rather than as a separate layer covering the conversation.
- Reloading the real viewer page reported `window.NomiViewerBuild = "20260722-file-viewer-v2"`; the download command was enabled and the status was `31 KB · 原格式查看`.
- Tapping the real download command changed the viewer status to `已下载到 Download/Nomi/Nomi_auto_delivery_visual_20260720.pptx`.
- The physical device contained `/sdcard/Download/Nomi/Nomi_auto_delivery_visual_20260720.pptx`, size `30,728` bytes.
- The file pulled back from Android had SHA-256 `0ebd6caab311c2a27bbf3c9931513d6a519752c23af65a03b362bb561e8c415c`, identical to the cloud artifact.
- `cmp` reported identical bytes, `file` reported `Microsoft OOXML`, and `unzip -t` reported no errors.

Screenshots captured during acceptance:

- `/tmp/nomi_after_version_deploy.png`
- `/tmp/nomi_proxy_state.png`
- `/tmp/nomi_viewer_reconnected.png`
- `/tmp/nomi_download_complete.png`

## Remaining Gaps

No known implementation or acceptance gap remains within the agreed scope of方案 A. The viewer renders the original PPTX, the inline reminder/result card stays in the conversation flow, and the exact original file can be downloaded and recovered from the physical device without byte changes.
