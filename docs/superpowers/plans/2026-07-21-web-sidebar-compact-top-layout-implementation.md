# Nomi Web Sidebar Compact Top Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the desktop workbench navigation directly below the Nomi brand while preserving navigation behavior and mobile layout.

**Architecture:** Keep the existing HTML structure and change only the desktop `.sidebar` flex contract. A static regression test reads the shipped CSS and enforces top alignment, stable spacing, and vertical overflow support.

**Tech Stack:** HTML, CSS, pytest static-asset tests, Docker Compose runtime-api/nginx.

---

### Task 1: Enforce and implement compact desktop sidebar layout

**Files:**
- Modify: `runtime_api/tests/test_static_workbench_agenda_tab.py`
- Modify: `runtime_api/app/static/styles.css`

- [x] **Step 1: Write the failing layout contract test**

```python
def test_desktop_sidebar_keeps_navigation_compact_and_top_aligned():
    css = read_static("styles.css")
    sidebar_start = css.index(".sidebar {")
    sidebar_end = css.index("}", sidebar_start)
    sidebar_rule = css[sidebar_start:sidebar_end]

    assert "justify-content: flex-start" in sidebar_rule
    assert "gap: 32px" in sidebar_rule
    assert "overflow-y: auto" in sidebar_rule
    assert "justify-content: space-between" not in sidebar_rule
```

- [x] **Step 2: Run the focused test and verify RED**

Run: `python3 -m pytest runtime_api/tests/test_static_workbench_agenda_tab.py::test_desktop_sidebar_keeps_navigation_compact_and_top_aligned -q`

Expected: FAIL because the current sidebar uses `justify-content: space-between` and has no stable gap or overflow rule.

- [x] **Step 3: Implement the minimal desktop CSS change**

```css
.sidebar {
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  gap: 32px;
  overflow-y: auto;
  padding: 24px;
  background: #101828;
  color: #f2f4f7;
}
```

- [x] **Step 4: Run focused and related tests**

Run: `python3 -m pytest runtime_api/tests/test_static_workbench_agenda_tab.py -q`

Expected: PASS for the new layout contract and all existing workbench navigation contracts.

- [x] **Step 5: Rebuild and verify the served Web UI**

Run: `docker compose up -d --build runtime-api nginx`

Expected: `runtime-api` becomes healthy and nginx continues serving port 80.

Run: `curl -fsS http://127.0.0.1/health`

Expected: `{"status":"ok"}`.

- [x] **Step 6: Verify rendered desktop geometry**

At a desktop viewport, verify the first navigation button starts below the brand with a compact fixed gap; all navigation buttons remain clickable, and the sidebar scrolls if viewport height is insufficient.

- [x] **Step 7: Commit only the sidebar test and CSS change**

```bash
git add runtime_api/tests/test_static_workbench_agenda_tab.py runtime_api/app/static/styles.css docs/superpowers/plans/2026-07-21-web-sidebar-compact-top-layout-implementation.md
git commit -m "fix: compact desktop workbench sidebar"
```
