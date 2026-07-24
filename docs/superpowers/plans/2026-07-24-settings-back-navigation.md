# 设置详情页返回导航 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为设置详情页增加可访问的返回按钮，使页面内按钮和 Android 系统返回键都能一次回到进入设置前的工作台页面。

**Architecture:** 扩展现有 `createWorkbenchNavigationController`，让整个设置中心只占用一个浏览历史条目：首次进入设置时用 `pushState` 记录可信来源，设置子项切换时用 `replaceState` 保留来源，退出时回退该条目；直接打开设置时安全替换到对话路由。UI 只通过控制器调用退出逻辑，不直接操作 hash。

**Tech Stack:** 原生 HTML/CSS/JavaScript、Node.js 路由测试工具、pytest、Docker Compose、Android ADB/WebView。

---

## 文件结构

- Modify: `runtime_api/app/static/app.js` — 设置历史条目、来源校验和退出设置逻辑。
- Modify: `runtime_api/app/static/index.html` — 设置页返回按钮与静态资源版本。
- Modify: `runtime_api/app/static/styles.css` — 返回按钮及标题区的桌面/移动端布局。
- Modify: `runtime_api/tests/test_static_workbench_agenda_tab.py` — 历史栈运行时测试和静态 UI 合约测试。

### Task 1: 用测试定义设置历史与返回语义

**Files:**
- Modify: `runtime_api/tests/test_static_workbench_agenda_tab.py:18-94`
- Modify: `runtime_api/tests/test_static_workbench_agenda_tab.py:1200-1325`
- Modify: `runtime_api/app/static/app.js:156-396`

- [ ] **Step 1: 扩展 Node 测试历史桩以支持 state 和 replaceState**

把 `createHarness` 中的历史桩改为保存 `{ hash, state }`，同时保留现有 `entries` 字符串断言：

```javascript
const location = { hash: initialHash };
const historyStack = [{ hash: initialHash, state: null }];
let historyIndex = 0;
const history = {
  entries: [],
  replacements: [],
  get state() {
    return historyStack[historyIndex]?.state ?? null;
  },
  pushState(state, _title, nextHash) {
    this.entries.push(nextHash);
    historyStack.splice(historyIndex + 1);
    historyStack.push({ hash: nextHash, state });
    historyIndex = historyStack.length - 1;
    location.hash = nextHash;
  },
  replaceState(state, _title, nextHash) {
    this.replacements.push(nextHash);
    historyStack[historyIndex] = { hash: nextHash, state };
    location.hash = nextHash;
  },
  back() {
    if (historyIndex === 0) return;
    historyIndex -= 1;
    location.hash = historyStack[historyIndex].hash;
    eventTarget.dispatchEvent({ type: "hashchange" });
  },
  forward() {
    if (historyIndex >= historyStack.length - 1) return;
    historyIndex += 1;
    location.hash = historyStack[historyIndex].hash;
    eventTarget.dispatchEvent({ type: "hashchange" });
  },
};
```

- [ ] **Step 2: 写入设置来源、子路由替换和返回的失败测试**

新增以下运行时测试：

```python
def test_runtime_settings_sections_share_one_history_entry_and_exit_to_source():
    run_navigation_runtime(
        """
const h = createHarness("#career");
h.controller.bindHashChanges(h.eventTarget);
h.controller.activateCurrentRoute();

h.controller.navigateToView("settingsView");
assert.equal(h.location.hash, "#settings");
assert.deepEqual(h.history.entries, ["#settings"]);
assert.equal(h.history.state.nomiWorkbenchSettingsEntry, true);
assert.equal(h.history.state.nomiSettingsReturnHash, "#career");

h.controller.navigateToView("toolsView");
h.controller.navigateToView("webSearchSettingsView");
assert.equal(h.location.hash, "#web-search");
assert.deepEqual(h.history.entries, ["#settings"]);
assert.deepEqual(h.history.replacements, ["#tools", "#web-search"]);
assert.equal(h.history.state.nomiSettingsReturnHash, "#career");

h.controller.exitSettings();
assert.equal(h.location.hash, "#career");
assert.deepEqual(h.routes.at(-1), {
  primaryViewId: "careerView",
  settingsSectionId: "",
});
"""
    )


def test_runtime_android_history_back_exits_settings_after_section_changes():
    run_navigation_runtime(
        """
const h = createHarness("#agenda");
h.controller.bindHashChanges(h.eventTarget);
h.controller.activateCurrentRoute();
h.controller.navigateToView("settingsView");
h.controller.navigateToView("assistantIdentitiesView");
h.controller.navigateToView("privacyView");

h.history.back();
assert.equal(h.location.hash, "#agenda");
assert.deepEqual(h.routes.at(-1), {
  primaryViewId: "agendaView",
  settingsSectionId: "",
});
"""
    )


def test_runtime_direct_settings_entry_back_falls_back_to_chat():
    run_navigation_runtime(
        """
const h = createHarness("#settings");
h.controller.activateCurrentRoute();
h.controller.exitSettings();

assert.equal(h.location.hash, "#chat");
assert.deepEqual(h.history.replacements, ["#chat"]);
assert.deepEqual(h.routes.at(-1), {
  primaryViewId: "chatView",
  settingsSectionId: "",
});
"""
    )
```

把现有 `test_runtime_hash_back_forward_events_restore_routes_with_one_load_each` 的最终断言更新为设置子路由不再形成独立历史条目：

```javascript
assert.deepEqual(h.routes, [
  { primaryViewId: "settingsView", settingsSectionId: "toolsView" },
  { primaryViewId: "agendaView", settingsSectionId: "" },
]);
assert.deepEqual(h.loads.map((item) => item.id), [
  "toolsView",
  "agendaView",
]);
assert.equal(h.location.hash, "#agenda");
```

- [ ] **Step 3: 运行新测试并确认失败**

Run:

```bash
python3 -m pytest runtime_api/tests/test_static_workbench_agenda_tab.py \
  -k 'settings_sections_share_one_history_entry or android_history_back_exits_settings or direct_settings_entry_back' -q
```

Expected: FAIL，错误至少包含 `replaceState is not a function`、`exitSettings is not a function` 或设置子路由仍写入 `history.entries`。

- [ ] **Step 4: 在导航控制器中实现单条设置历史**

在 `createWorkbenchNavigationController` 内增加以下辅助逻辑：

```javascript
  const primaryReturnViewIds = ["chatView", "agendaView", "careerView"];

  function isSettingsRoute(route) {
    return normalizeRoute(route).primaryViewId === "settingsView";
  }

  function safePrimaryHash(hash) {
    const candidate = String(hash || "");
    return primaryReturnViewIds.some((viewId) => `#${hashForView(viewId)}` === candidate)
      ? candidate
      : "";
  }

  function settingsEntryState(returnHash, currentState = null) {
    const base =
      currentState && typeof currentState === "object" && !Array.isArray(currentState)
        ? currentState
        : {};
    return {
      ...base,
      nomiWorkbenchSettingsEntry: true,
      nomiSettingsReturnHash: safePrimaryHash(returnHash),
    };
  }

  function settingsReturnHashFromState() {
    const state = history.state;
    if (!state || state.nomiWorkbenchSettingsEntry !== true) return "";
    return safePrimaryHash(state.nomiSettingsReturnHash);
  }
```

用下面的实现替换 `navigateToHash`，并新增 `exitSettings`：

```javascript
  function navigateToHash(nextHash) {
    if (!nextHash) return activateCurrentRoute();
    if (String(location.hash || "") !== nextHash) {
      const currentRoute = normalizeRoute(routeStateFromHash(location.hash));
      const nextRoute = normalizeRoute(routeStateFromHash(nextHash));
      if (isSettingsRoute(currentRoute) && isSettingsRoute(nextRoute)) {
        const returnHash = settingsReturnHashFromState();
        const nextState = returnHash
          ? settingsEntryState(returnHash, history.state)
          : history.state ?? null;
        history.replaceState(nextState, "", nextHash);
      } else if (!isSettingsRoute(currentRoute) && isSettingsRoute(nextRoute)) {
        const currentHash =
          safePrimaryHash(location.hash) ||
          (currentRoute.primaryViewId === "chatView" ? `#${hashForView("chatView")}` : "");
        history.pushState(settingsEntryState(currentHash), "", nextHash);
      } else {
        history.pushState(null, "", nextHash);
      }
    }
    return activateCurrentRoute();
  }

  function exitSettings() {
    const returnHash = settingsReturnHashFromState();
    if (returnHash && typeof history.back === "function") {
      history.back();
      return;
    }
    const chatHash = `#${hashForView("chatView")}`;
    history.replaceState(null, "", chatHash);
    return activateCurrentRoute();
  }
```

在控制器返回对象中暴露 `exitSettings`：

```javascript
  return {
    activateCurrentRoute,
    activateRoute,
    bindHashChanges,
    consumePendingAgentEvent,
    currentSuggestionFocusId,
    currentRouteContext,
    exitSettings,
    hashForView,
    navigateToSuggestion,
    navigateToView,
    renderAssistantEventWithoutStealingView,
    routeStateFromHash,
    shouldPreserveCurrentViewForAssistantEvent,
    whenIdle,
  };
```

- [ ] **Step 5: 运行导航测试并确认通过**

Run:

```bash
python3 -m pytest runtime_api/tests/test_static_workbench_agenda_tab.py \
  -k 'settings_sections_share_one_history_entry or android_history_back_exits_settings or direct_settings_entry_back or hash_back_forward' -q
```

Expected: 所选测试全部 PASS；原有 `history.entries` 断言保持兼容。

- [ ] **Step 6: 提交路由行为**

```bash
git add runtime_api/app/static/app.js runtime_api/tests/test_static_workbench_agenda_tab.py
git commit -m "feat: preserve settings return route"
```

### Task 2: 增加返回按钮和响应式样式

**Files:**
- Modify: `runtime_api/tests/test_static_workbench_agenda_tab.py:310-440`
- Modify: `runtime_api/app/static/index.html:134-142`
- Modify: `runtime_api/app/static/styles.css:378-430`
- Modify: `runtime_api/app/static/styles.css:1725-1870`
- Modify: `runtime_api/app/static/app.js:416-425`
- Modify: `runtime_api/app/static/app.js:4350-4388`

- [ ] **Step 1: 写入返回按钮静态合约的失败测试**

```python
def test_settings_detail_exposes_accessible_back_button():
    html = read_static("index.html")
    js = read_static("app.js")
    css = read_static("styles.css")

    assert 'id="settingsBackButton"' in html
    assert 'class="settings-back-button"' in html
    assert 'aria-label="返回进入设置前的页面"' in html
    assert 'document.querySelector("#settingsBackButton")' in js
    assert "workbenchNavigation.exitSettings()" in js
    assert ".settings-back-button" in css
    assert "min-height: 44px" in css
    assert 'href="/static/styles.css?v=20260724-settings-back-navigation"' in html
    assert 'src="/static/app.js?v=20260724-settings-back-navigation"' in html
```

同时在现有快捷菜单合约测试中继续断言：

```python
assert shortcut_menu.count('class="assistant-settings-item"') == 3
```

把现有静态资源版本断言从：

```python
assert 'href="/static/styles.css?v=20260724-settings-center"' in html
```

更新为：

```python
assert 'href="/static/styles.css?v=20260724-settings-back-navigation"' in html
```

- [ ] **Step 2: 运行静态合约测试并确认失败**

Run:

```bash
python3 -m pytest runtime_api/tests/test_static_workbench_agenda_tab.py \
  -k 'settings_detail_exposes_accessible_back_button or assistant_shortcut_menu' -q
```

Expected: FAIL，缺少 `settingsBackButton`。

- [ ] **Step 3: 增加设置标题区返回按钮**

把 `settingsView` 标题改为：

```html
<header class="view-header settings-view-header">
  <button
    id="settingsBackButton"
    class="settings-back-button"
    type="button"
    aria-label="返回进入设置前的页面"
  >
    <span aria-hidden="true">←</span>
    <span>返回</span>
  </button>
  <div class="settings-view-heading-copy">
    <h2>设置</h2>
    <p class="view-subtitle">管理 Nomi 的记忆、数据源、外部能力与隐私。</p>
  </div>
</header>
```

将两个静态资源版本从 `20260724-settings-center` 更新为 `20260724-settings-back-navigation`：

```html
<link rel="stylesheet" href="/static/styles.css?v=20260724-settings-back-navigation" />
<script src="/static/app.js?v=20260724-settings-back-navigation"></script>
```

- [ ] **Step 4: 增加桌面和移动端样式**

在设置布局样式附近增加：

```css
.settings-view-header {
  align-items: flex-start;
  justify-content: flex-start;
}

.settings-view-heading-copy {
  min-width: 0;
}

.settings-back-button {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 44px;
  padding: 0 13px;
  border: 1px solid #d7dee8;
  border-radius: 10px;
  background: #ffffff;
  color: #172033;
  font-weight: 700;
}

.settings-back-button:hover {
  background: #f1f5f9;
}
```

在 `@media (max-width: 860px)` 内增加：

```css
  .settings-view-header {
    align-items: flex-start;
    gap: 10px;
  }

  .settings-back-button {
    min-height: 44px;
    padding-inline: 12px;
  }
```

- [ ] **Step 5: 绑定返回按钮到导航控制器**

在 DOM 查询区增加：

```javascript
const settingsBackButton = document.querySelector("#settingsBackButton");
```

在事件绑定区增加：

```javascript
settingsBackButton?.addEventListener("click", () => {
  workbenchNavigation.exitSettings();
});
```

- [ ] **Step 6: 运行解析、静态合约和设置回归测试**

Run:

```bash
node --check runtime_api/app/static/app.js
python3 -m pytest \
  runtime_api/tests/test_static_assistant_identity_settings.py \
  runtime_api/tests/test_static_web_search_settings.py \
  runtime_api/tests/test_static_workbench_agenda_tab.py -q
```

Expected: JavaScript 解析退出码 0；pytest 全部 PASS。

- [ ] **Step 7: 提交 UI**

```bash
git add \
  runtime_api/app/static/index.html \
  runtime_api/app/static/styles.css \
  runtime_api/app/static/app.js \
  runtime_api/tests/test_static_workbench_agenda_tab.py
git commit -m "feat: add settings back button"
```

### Task 3: 发布并在真机验收

**Files:**
- Deploy: `runtime_api/app/static/index.html`
- Deploy: `runtime_api/app/static/styles.css`
- Deploy: `runtime_api/app/static/app.js`

- [ ] **Step 1: 运行最终本地验证**

Run:

```bash
git diff --check
node --check runtime_api/app/static/app.js
python3 -m pytest \
  runtime_api/tests/test_static_assistant_identity_settings.py \
  runtime_api/tests/test_static_web_search_settings.py \
  runtime_api/tests/test_static_workbench_agenda_tab.py -q
git status --short
```

Expected: diff check 和 Node 解析退出码 0；pytest 全部 PASS；工作区只保留用户原有的 `?? source`。

- [ ] **Step 2: 备份并同步三项静态资源**

先在 `/opt/nomi/.deploy-backups/` 创建带时间戳的备份目录，再同步文件：

```bash
sshpass -p "$NOMI_SSH_PASSWORD" ssh -4 root@206.119.171.141 \
  'install -d -m 700 /opt/nomi/.deploy-backups/20260724-settings-back-navigation &&
   cp -a /opt/nomi/runtime_api/app/static/index.html \
         /opt/nomi/runtime_api/app/static/styles.css \
         /opt/nomi/runtime_api/app/static/app.js \
         /opt/nomi/.deploy-backups/20260724-settings-back-navigation/'

sshpass -p "$NOMI_SSH_PASSWORD" rsync -rlpt \
  -e 'ssh -4 -o StrictHostKeyChecking=accept-new' \
  runtime_api/app/static/index.html \
  runtime_api/app/static/styles.css \
  runtime_api/app/static/app.js \
  root@206.119.171.141:/opt/nomi/runtime_api/app/static/
```

Expected: 只列出 `index.html`、`styles.css`、`app.js` 三个更新文件。

- [ ] **Step 3: 校验哈希并重建服务**

Run:

```bash
shasum -a 256 \
  runtime_api/app/static/index.html \
  runtime_api/app/static/styles.css \
  runtime_api/app/static/app.js

sshpass -p "$NOMI_SSH_PASSWORD" ssh -4 root@206.119.171.141 \
  'cd /opt/nomi &&
   sha256sum runtime_api/app/static/index.html \
             runtime_api/app/static/styles.css \
             runtime_api/app/static/app.js &&
   docker compose -p nomi up -d --build runtime-api'
```

Expected: 本地和远端三个哈希分别一致；Compose 退出码 0。

- [ ] **Step 4: 验证线上健康和资源版本**

Run:

```bash
sshpass -p "$NOMI_SSH_PASSWORD" ssh -4 root@206.119.171.141 \
  'test "$(docker inspect --format "{{.State.Health.Status}}" nomi-runtime-api-1)" = healthy &&
   curl -fsS http://127.0.0.1/static/index.html |
   grep -q "20260724-settings-back-navigation"'
```

Expected: 退出码 0。

- [ ] **Step 5: 在真机验证触摸返回**

Run:

```bash
adb shell am force-stop com.par.assistant.android
adb shell am start -n com.par.assistant.android/.MainActivity
```

等待 App 打开后，通过系统触摸依次完成：

1. 点击右上角齿轮。
2. 确认菜单仍只有“日程管理 / 求职助手 / 设置”。
3. 点击“设置”，确认标题区出现“← 返回”。
4. 在设置内切换到“账号连接”或“Web Search”。
5. 点击“← 返回”，确认一次回到进入设置前的页面。
6. 再次进入设置并切换子项，发送 Android 系统返回键：

```bash
adb shell input keyevent KEYCODE_BACK
```

Expected: 标题区返回按钮和系统返回键都一次回到来源页；页面不退出 App。

- [ ] **Step 6: 保存截图并清理临时调试端口**

```bash
adb exec-out screencap -p > /tmp/nomi-settings-back-navigation-verified.png
adb forward --list
```

Expected: 截图包含设置返回按钮或返回后的来源页；没有遗留本次创建的 ADB forward。
