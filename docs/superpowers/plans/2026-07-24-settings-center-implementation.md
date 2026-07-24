# Nomi Settings Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace duplicated configuration navigation with one Settings workspace that contains eight grouped settings sections while preserving existing behavior and deep links.

**Architecture:** Keep chat, agenda, career, and settings as the only primary views. Nest the eight existing configuration panels under `settingsView`, retain their existing DOM ids and loaders, and introduce a route state that resolves both the primary view and selected settings section. Desktop uses a secondary settings rail; mobile uses a horizontally scrollable settings navigation.

**Tech Stack:** Static HTML, vanilla JavaScript, responsive CSS, pytest static-contract tests.

---

## File Map

- Modify: `runtime_api/tests/test_static_workbench_agenda_tab.py`
  - Defines the navigation, settings hierarchy, routing, loading, and responsive layout contracts.
- Modify: `runtime_api/app/static/index.html`
  - Adds the Settings primary view and groups the existing configuration panels inside it.
- Modify: `runtime_api/app/static/app.js`
  - Resolves primary and secondary route state, updates navigation, and preserves existing lazy loaders.
- Modify: `runtime_api/app/static/styles.css`
  - Implements desktop and mobile Settings layouts.

### Task 1: Lock the Settings Information Architecture

**Files:**
- Modify: `runtime_api/tests/test_static_workbench_agenda_tab.py`
- Test: `runtime_api/tests/test_static_workbench_agenda_tab.py`

- [ ] **Step 1: Replace the old duplicated-navigation assertions with failing Settings Center contracts**

Add tests equivalent to:

```python
def test_primary_navigation_only_exposes_workspaces_and_settings():
    html = read_static("index.html")
    sidebar_start = html.index('<nav class="nav-actions"')
    sidebar_end = html.index("</nav>", sidebar_start)
    sidebar = html[sidebar_start:sidebar_end]

    assert sidebar.count('class="nav-button') == 4
    assert 'data-view="chatView"' in sidebar
    assert 'data-view="agendaView"' in sidebar
    assert 'data-view="careerView"' in sidebar
    assert 'data-view="settingsView"' in sidebar
    for old_view in (
        "searchView",
        "governanceView",
        "suggestionsView",
        "collectorsView",
        "assistantIdentitiesView",
        "toolsView",
        "webSearchSettingsView",
    ):
        assert f'data-view="{old_view}"' not in sidebar


def test_settings_view_groups_all_configuration_sections():
    html = read_static("index.html")
    settings_start = html.index('<section id="settingsView" class="view settings-view">')
    settings_end = html.index("</section><!-- settingsView -->", settings_start)
    settings = html[settings_start:settings_end]

    assert 'class="settings-navigation"' in settings
    assert "智能与记忆" in settings
    assert "数据与账号" in settings
    assert "能力与隐私" in settings
    for view_id in (
        "suggestionsView",
        "searchView",
        "governanceView",
        "collectorsView",
        "toolsView",
        "assistantIdentitiesView",
        "webSearchSettingsView",
        "privacyView",
    ):
        assert f'id="{view_id}" class="settings-section' in settings
```

Also update the mobile shortcut-menu contract so it only permits `agendaView`, `careerView`, and `settingsView`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python3 -m pytest runtime_api/tests/test_static_workbench_agenda_tab.py -q
```

Expected: FAIL because `settingsView` and `.settings-navigation` do not exist and the sidebar still has ten buttons.

- [ ] **Step 3: Commit the failing contracts**

```bash
git add runtime_api/tests/test_static_workbench_agenda_tab.py
git commit -m "test: define unified settings center contracts"
```

### Task 2: Build the Settings DOM Hierarchy

**Files:**
- Modify: `runtime_api/app/static/index.html`
- Test: `runtime_api/tests/test_static_workbench_agenda_tab.py`

- [ ] **Step 1: Reduce the primary and shortcut navigation**

Change the primary sidebar to exactly:

```html
<nav class="nav-actions" aria-label="工作台导航">
  <button class="nav-button active" data-view="chatView" type="button">对话</button>
  <button class="nav-button" data-view="agendaView" type="button">日程</button>
  <button class="nav-button" data-view="careerView" type="button">求职</button>
  <button class="nav-button" data-view="settingsView" type="button">设置</button>
</nav>
```

Change the topbar shortcut menu to keep only 日程管理, 求职助手, and 设置.

- [ ] **Step 2: Add the grouped settings shell**

Add `settingsView` after `careerView`:

```html
<section id="settingsView" class="view settings-view">
  <header class="view-header settings-view-header">
    <div>
      <h2>设置</h2>
      <p class="view-subtitle">管理 Nomi 的记忆、数据源、外部能力与隐私。</p>
    </div>
  </header>
  <div class="settings-layout">
    <nav class="settings-navigation" aria-label="设置导航">
      <section class="settings-navigation-group" aria-labelledby="settings-memory-group">
        <h3 id="settings-memory-group">智能与记忆</h3>
        <button class="settings-nav-button active" data-settings-section="suggestionsView" type="button">主动建议</button>
        <button class="settings-nav-button" data-settings-section="searchView" type="button">个人搜索</button>
        <button class="settings-nav-button" data-settings-section="governanceView" type="button">记忆治理</button>
      </section>
      <section class="settings-navigation-group" aria-labelledby="settings-data-group">
        <h3 id="settings-data-group">数据与账号</h3>
        <button class="settings-nav-button" data-settings-section="collectorsView" type="button">采集状态</button>
        <button class="settings-nav-button" data-settings-section="toolsView" type="button">账号连接</button>
        <button class="settings-nav-button" data-settings-section="assistantIdentitiesView" type="button">助理身份</button>
      </section>
      <section class="settings-navigation-group" aria-labelledby="settings-capability-group">
        <h3 id="settings-capability-group">能力与隐私</h3>
        <button class="settings-nav-button" data-settings-section="webSearchSettingsView" type="button">Web Search</button>
        <button class="settings-nav-button" data-settings-section="privacyView" type="button">隐私管理</button>
      </section>
    </nav>
    <div class="settings-content">
      <!-- existing configuration sections -->
    </div>
  </div>
</section><!-- settingsView -->
```

- [ ] **Step 3: Convert the existing configuration views to settings sections**

For each of the eight panels:

- Keep its existing `id`.
- Replace `class="view settings-child-view"` with `class="settings-section"`.
- Remove the `返回设置` button.
- Preserve refresh buttons, forms, lists, descriptions, and every internal DOM id.
- Mark `suggestionsView` active by default.

Do not move agenda or career into `settingsView`.

- [ ] **Step 4: Run the information-architecture tests and verify GREEN for DOM contracts**

Run:

```bash
python3 -m pytest runtime_api/tests/test_static_workbench_agenda_tab.py -q
```

Expected: DOM/navigation contracts pass; routing contracts may still fail until Task 3.

- [ ] **Step 5: Commit the DOM checkpoint**

```bash
git add runtime_api/app/static/index.html runtime_api/tests/test_static_workbench_agenda_tab.py
git commit -m "feat: add grouped settings workspace"
```

### Task 3: Implement Primary and Settings Route State

**Files:**
- Modify: `runtime_api/tests/test_static_workbench_agenda_tab.py`
- Modify: `runtime_api/app/static/app.js`
- Test: `runtime_api/tests/test_static_workbench_agenda_tab.py`

- [ ] **Step 1: Add failing routing and lazy-loading contracts**

Assert that JavaScript defines:

```javascript
const defaultSettingsSectionId = "suggestionsView";
const settingsSectionIds = new Set([
  "suggestionsView",
  "searchView",
  "governanceView",
  "collectorsView",
  "toolsView",
  "assistantIdentitiesView",
  "webSearchSettingsView",
  "privacyView",
]);
```

The contracts must also require:

- `settingsView: "settings"` in the primary hash map.
- A `routeStateFromHash` helper returning `primaryViewId` and `settingsSectionId`.
- Old hashes such as `#tools` resolving to `settingsView/toolsView`.
- `#suggestion:<id>` resolving to `settingsView/suggestionsView`.
- `switchView` activating `.settings-section` and `.settings-nav-button`.
- `aria-current="page"` on the selected settings navigation button.
- Existing loaders being called based on `settingsSectionId`.
- No `returnToAssistantSettings` or `back-to-settings` click handler.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python3 -m pytest runtime_api/tests/test_static_workbench_agenda_tab.py -q
```

Expected: FAIL because routing still treats each configuration panel as a primary `.view`.

- [ ] **Step 3: Implement route-state parsing**

Introduce:

```javascript
const defaultSettingsSectionId = "suggestionsView";
const settingsSectionIds = new Set([...]);
const settingsSectionHashMap = {
  suggestionsView: "suggestions",
  searchView: "search",
  governanceView: "governance",
  collectorsView: "collectors",
  toolsView: "tools",
  assistantIdentitiesView: "assistant-identities",
  webSearchSettingsView: "web-search",
  privacyView: "privacy",
};

function routeStateFromHash(hash = location.hash) {
  if (String(hash || "").startsWith("#suggestion:")) {
    return { primaryViewId: "settingsView", settingsSectionId: "suggestionsView" };
  }
  const primaryViewId = hashViewMap[String(hash || "")];
  if (primaryViewId) return { primaryViewId, settingsSectionId: "" };
  const settingsSectionId = settingsHashViewMap[String(hash || "")];
  if (settingsSectionId) return { primaryViewId: "settingsView", settingsSectionId };
  return { primaryViewId: "", settingsSectionId: "" };
}
```

Retain `viewIdFromHash` as a small compatibility helper that returns `routeStateFromHash(hash).primaryViewId`.

- [ ] **Step 4: Update view switching and click handlers**

`switchView(primaryViewId, settingsSectionId)` must:

1. Normalize direct legacy calls using a settings section id into `settingsView`.
2. Activate only the requested primary `.view`.
3. Activate the requested settings section, defaulting to `suggestionsView`.
4. Update primary and settings navigation states.
5. Clear Web Search key input whenever the selected section is not Web Search.
6. Run only the loader for the selected section.

Update:

- initial app routing;
- primary nav clicks;
- shortcut-menu clicks;
- settings secondary-nav clicks;
- `hashchange`;
- assistant-event view-preservation logic.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
python3 -m pytest runtime_api/tests/test_static_workbench_agenda_tab.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the routing checkpoint**

```bash
git add runtime_api/app/static/app.js runtime_api/tests/test_static_workbench_agenda_tab.py
git commit -m "feat: route settings through unified workspace"
```

### Task 4: Add Responsive Settings Layout

**Files:**
- Modify: `runtime_api/tests/test_static_workbench_agenda_tab.py`
- Modify: `runtime_api/app/static/styles.css`
- Test: `runtime_api/tests/test_static_workbench_agenda_tab.py`

- [ ] **Step 1: Add failing desktop and mobile CSS contracts**

Require selectors and properties for:

```css
#settingsView.active
.settings-layout
.settings-navigation
.settings-navigation-group
.settings-nav-button
.settings-nav-button.active
.settings-content
.settings-section
.settings-section.active
```

Desktop contracts:

- `settings-layout` uses a 232px secondary rail and a flexible content column.
- navigation and content have independent vertical overflow.

Mobile contracts inside `@media (max-width: 860px)`:

- `settings-layout` becomes a single column.
- `settings-navigation` becomes a horizontal grid/flex flow with `overflow-x: auto`.
- group headings are hidden.
- settings buttons do not shrink to unreadable widths.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python3 -m pytest runtime_api/tests/test_static_workbench_agenda_tab.py -q
```

Expected: FAIL because Settings-specific responsive selectors are missing.

- [ ] **Step 3: Implement the desktop settings layout**

Use a restrained operational layout:

```css
#settingsView.active {
  grid-template-rows: auto minmax(0, 1fr);
}

.settings-layout {
  display: grid;
  grid-template-columns: 232px minmax(0, 1fr);
  min-height: 0;
  border-top: 1px solid #e4e7ec;
}

.settings-navigation,
.settings-content {
  min-height: 0;
  overflow-y: auto;
}
```

Use compact list-style navigation with an emerald active indicator. Do not introduce decorative cards or nested card containers.

- [ ] **Step 4: Implement the mobile settings layout**

Inside the existing mobile media query:

```css
.settings-layout {
  grid-template-columns: 1fr;
  grid-template-rows: auto minmax(0, 1fr);
}

.settings-navigation {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding: 10px 14px;
}

.settings-navigation-group {
  display: contents;
}

.settings-navigation-group h3 {
  display: none;
}
```

Ensure long Web Search and account content remains vertically scrollable and no settings element causes horizontal page overflow.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
python3 -m pytest runtime_api/tests/test_static_workbench_agenda_tab.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the responsive-layout checkpoint**

```bash
git add runtime_api/app/static/styles.css runtime_api/tests/test_static_workbench_agenda_tab.py
git commit -m "style: add responsive settings center layout"
```

### Task 5: Regression and Browser Verification

**Files:**
- Modify only if verification exposes a defect:
  - `runtime_api/app/static/index.html`
  - `runtime_api/app/static/app.js`
  - `runtime_api/app/static/styles.css`
  - `runtime_api/tests/test_static_workbench_agenda_tab.py`

- [ ] **Step 1: Run the complete static-workbench test file**

```bash
python3 -m pytest runtime_api/tests/test_static_workbench_agenda_tab.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run the full runtime API suite**

```bash
python3 -m pytest runtime_api/tests -q
```

Expected: all tests pass, aside from explicitly documented existing skips.

- [ ] **Step 3: Start the local runtime and inspect desktop behavior**

Open the workbench at a desktop viewport and verify:

- main sidebar contains four entries;
- `#settings` opens Settings with 主动建议 selected;
- all eight settings sections are reachable;
- old hashes open the correct settings section;
- refresh/forms still operate with their existing APIs;
- browser back/forward restores the previous section.

- [ ] **Step 4: Inspect mobile behavior**

At a 412×915 or equivalent mobile viewport verify:

- gear menu contains only 日程、求职、设置;
- Settings navigation scrolls horizontally;
- each section fills the remaining content area;
- no horizontal overflow, overlay trap, or missing back navigation;
- realtime assistant events do not steal the active settings view.

- [ ] **Step 5: Run final diff checks**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only intentional files are modified. The pre-existing untracked `source` file remains untouched.

- [ ] **Step 6: Commit any verification fixes**

```bash
git add runtime_api/app/static/index.html runtime_api/app/static/app.js runtime_api/app/static/styles.css runtime_api/tests/test_static_workbench_agenda_tab.py
git commit -m "fix: complete settings center regression"
```
