# Android Remote Browser Mobile Fit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Android remote browser readable, fully fitted, and scrollable on phones with different resolutions.

**Architecture:** Android enables the noVNC lite client's supported viewport scaling parameter instead of the ignored remote-resize parameter. The remote Chromium runtime uses a configurable 125% default page zoom preference for readability without scaling the X11 window, while noVNC keeps native single-pointer interaction and two-finger remote scrolling.

**Tech Stack:** Android Java, JUnit 4, Bash, Chromium, Docker Compose, pytest, noVNC, ADB/CDP

---

### Task 1: Lock the Android noVNC behavior with failing tests

**Files:**
- Modify: `android_app/app/src/test/java/com/par/assistant/android/ConfigPrefsTest.java`
- Modify: `android_app/app/src/test/java/com/par/assistant/android/WebWorkspaceKeyboardTest.java`

- [ ] **Step 1: Change URL expectations to the supported scale parameter**

Replace both expected `resize=remote` fragments with `scale=1`.

- [ ] **Step 2: Add the remote-scroll discoverability assertion**

Add this assertion to `workspaceActivityProvidesRemoteBrowserTextInputBridge`:

```java
assertTrue(activity.contains("双指上下滑动远端页面"));
```

- [ ] **Step 3: Run the Android tests and verify RED**

Run:

```bash
cd android_app
gradle :app:testDebugUnitTest --tests com.par.assistant.android.ConfigPrefsTest --tests com.par.assistant.android.WebWorkspaceKeyboardTest
```

Expected: URL tests fail because production still emits `resize=remote`; the hint test fails because the activity does not mention two-finger scrolling.

- [ ] **Step 4: Commit the failing tests together with the later minimal implementation**

The RED tests remain uncommitted until Task 3 is green, so the branch never records an intentionally failing state.

### Task 2: Lock the Chromium readability behavior with a failing test

**Files:**
- Modify: `chromium_runtime/tests/test_chromium_startup_flags.py`

- [ ] **Step 1: Add the scale-factor startup test**

```python
def test_chromium_startup_uses_page_zoom_without_scaling_the_x11_window():
    script = Path(__file__).resolve().parents[1] / "start-runtime.sh"
    text = script.read_text(encoding="utf-8")

    assert 'CHROMIUM_PAGE_ZOOM_PERCENT="${CHROMIUM_PAGE_ZOOM_PERCENT:-125}"' in text
    assert 'zoom_factor = float(os.environ["CHROMIUM_PAGE_ZOOM_PERCENT"]) / 100.0' in text
    assert 'math.log(zoom_factor) / math.log(1.2)' in text
    assert 'partition["default_zoom_level"] = {"x": zoom_level}' in text
    assert "--force-device-scale-factor" not in text
```

- [ ] **Step 2: Run the Chromium test and verify RED**

Run:

```bash
python3 -m pytest chromium_runtime/tests/test_chromium_startup_flags.py -q
```

Expected: the new test fails because the startup script has no page-zoom configuration.

### Task 3: Implement the minimal mobile-fit behavior

**Files:**
- Modify: `android_app/app/src/main/java/com/par/assistant/android/ConfigPrefs.java`
- Modify: `android_app/app/src/main/java/com/par/assistant/android/WebWorkspaceActivity.java`
- Modify: `chromium_runtime/start-runtime.sh`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Enable noVNC viewport scaling**

Change `noVncQuery` to return:

```java
return "?path=websockify&autoconnect=1&scale=1&quality=6&compression=2&show_dot=1&password="
        + encode(normalizePassword(appPassword) + "-vnc");
```

- [ ] **Step 2: Expose the native two-finger scroll gesture**

Change the remote input hint to:

```java
hint.setText("双指上下滑动远端页面；先点远端输入框，再在这里输入。");
```

- [ ] **Step 3: Configure Chromium display scaling**

Add this default beside the existing Chromium window variables:

```bash
CHROMIUM_PAGE_ZOOM_PERCENT="${CHROMIUM_PAGE_ZOOM_PERCENT:-125}"
export CHROMIUM_PAGE_ZOOM_PERCENT
```

In the existing startup preference update, convert the percentage to Chromium's
official zoom level and store it for the default profile partition:

```python
zoom_factor = float(os.environ["CHROMIUM_PAGE_ZOOM_PERCENT"]) / 100.0
zoom_level = math.log(zoom_factor) / math.log(1.2)
partition = preferences.setdefault("partition", {})
partition["default_zoom_level"] = {"x": zoom_level}
```

Add this explicit environment value to `chromium-runtime` in `docker-compose.yml`:

```yaml
CHROMIUM_PAGE_ZOOM_PERCENT: "125"
```

Do not add `--force-device-scale-factor`; it scales the Chromium rendering surface
beyond the fixed X11 window and causes physical-pixel clipping.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
cd android_app
gradle :app:testDebugUnitTest --tests com.par.assistant.android.ConfigPrefsTest --tests com.par.assistant.android.WebWorkspaceKeyboardTest
cd ..
python3 -m pytest chromium_runtime/tests/test_chromium_startup_flags.py -q
```

Expected: all focused tests pass.

- [ ] **Step 5: Commit the implementation**

```bash
git add android_app/app/src/main/java/com/par/assistant/android/ConfigPrefs.java \
  android_app/app/src/main/java/com/par/assistant/android/WebWorkspaceActivity.java \
  android_app/app/src/test/java/com/par/assistant/android/ConfigPrefsTest.java \
  android_app/app/src/test/java/com/par/assistant/android/WebWorkspaceKeyboardTest.java \
  chromium_runtime/start-runtime.sh \
  chromium_runtime/tests/test_chromium_startup_flags.py \
  docker-compose.yml
git commit -m "fix: fit remote browser on mobile screens"
```

### Task 4: Run the automated regression suite and build the APK

**Files:**
- Verify: `android_app`
- Verify: `chromium_runtime`

- [ ] **Step 1: Run all Android unit tests**

Run:

```bash
cd android_app
gradle :app:testDebugUnitTest
```

Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 2: Run all Chromium runtime tests**

Run:

```bash
python3 -m pytest chromium_runtime/tests -q
```

Expected: all tests pass.

- [ ] **Step 3: Build the debug APK**

Run:

```bash
cd android_app
gradle :app:assembleDebug
```

Expected: `android_app/app/build/outputs/apk/debug/app-debug.apk` exists and the build succeeds.

### Task 5: Deploy and verify on the connected Android phone

**Files:**
- Deploy: `chromium_runtime/start-runtime.sh`
- Deploy: `docker-compose.yml`
- Install: `android_app/app/build/outputs/apk/debug/app-debug.apk`

- [ ] **Step 1: Synchronize and recreate the Chromium runtime**

Run the repository deployment workflow, rebuild `chromium-runtime`, and keep its persisted profile volume. Confirm the live Chromium command does not contain `--force-device-scale-factor`, and the profile contains a default zoom level equivalent to 125%.

- [ ] **Step 2: Install the APK**

Run:

```bash
adb install -r android_app/app/build/outputs/apk/debug/app-debug.apk
```

Expected: `Success`.

- [ ] **Step 3: Verify full-page fit and pointer mapping**

Open the WhatsApp remote browser from the Android app. Confirm the WebView URL contains `scale=1`, the noVNC canvas fits within the WebView bounds, the full WhatsApp login page is visible, and tapping the QR refresh control updates the QR code.

- [ ] **Step 4: Verify two-finger scrolling through the real touch path**

Bring a temporary long page to the front in the remote Chromium instance. Send a two-contact upward drag through the Android WebView and confirm the remote page's scroll position increases. Restore WhatsApp to the foreground after the check.

- [ ] **Step 5: Capture final evidence**

Save a true-device screenshot showing the complete remote page and record the measured WebView size, canvas bounds, Chromium page zoom, horizontal overflow, and remote scroll delta.
