# 2026-07-01 WhatsApp 登录异常排查记录

## 用户现象

- Android 真机账号连接页打开 WhatsApp 后，用户看到先加载聊天数据，随后感觉登录失败或退出。
- 之前出现过 WhatsApp Web 数据库错误、重新关联设备失败、noVNC 断开/灰屏等现象。

## 已核验证据

- 云服务器 `chromium-runtime` 当前可打开 `https://web.whatsapp.com/`。
- Playwright CDP 读取到页面标题为 `(1) WhatsApp`。
- 页面正文包含真实聊天列表：
  - `+86 137 5203 1655`
  - `NOMI_REG_WA_0629 明天15:30人民广场见，带合同`
- `/collectors/health` 中 `whatsapp` 状态为：
  - `status=healthy`
  - `login_state=logged_in`
  - `title=(1) WhatsApp`
- worker 日志已处理 WhatsApp 事件：
  - `event_type=whatsapp_message`
  - `event_type=whatsapp_snapshot`

## 根因判断

当前不是 WhatsApp 账号仍然无法登录。当前云端 WhatsApp Web 已登录且可读取消息。

历史登录失败更可能由两类问题叠加造成：

1. Chromium 曾被 OOM kill
   - `dmesg` 有记录：`Memory cgroup out of memory: Killed process ... chromium`
   - WhatsApp Web 在加载聊天/写 IndexedDB 时被杀，容易触发“数据库错误”或关联设备失败。
   - 已将 `chromium-runtime` 内存限制提升到 5GiB，当前运行约 1GiB，无新 OOM。

2. noVNC/Chromium 恢复状态误导用户
   - runtime 重启后 Android 真机 noVNC 会停在连接页，用户看到的不是 WhatsApp 页面。
   - Chromium crash 后会弹 `Restore pages?`，遮挡页面并造成“登录流程异常”的感知。

## 已修复

- `chromium_runtime/start-runtime.sh`
  - 启动时继续保留 Cookies、Local Storage、IndexedDB、Session Storage。
  - 清理 Chromium stale tab/session 文件。
  - 写入 clean profile 状态：
    - `profile.exited_cleanly=true`
    - `profile.exit_type=Normal`
    - `sessions.event_log=[]`
    - `sessions.session_data_status=0`
  - 目的：避免 crash 后的 `Restore pages?` 干扰远程登录页面。
- `chromium_runtime/tests/test_chromium_startup_flags.py`
  - 增加回归测试，确保启动脚本标记 clean profile 且不清除站点登录数据。

## 验证结果

- 本地测试：
  - `python3 -m pytest chromium_runtime/tests/test_chromium_startup_flags.py chromium_runtime/tests/test_whatsapp_observer.py -q`
  - 结果：`12 passed`
- 线上部署后两次重启 `chromium-runtime`：
  - WhatsApp 均保持已登录。
  - collector 均为 `healthy/logged_in`。
  - 真机 noVNC 连接后可看到 WhatsApp 聊天列表。
  - 第二次重启后 `Restore pages?` 弹窗已消失。

## 遗留问题

- Android 真机 noVNC 在 runtime 重启后仍停留在“连接”按钮页，需要用户手点一次后才显示远程浏览器。
- 这不是 WhatsApp 登录失败，但会让用户误判。后续应在 Android 远程浏览器页增加自动重连/自动点击 noVNC connect 的兜底。
