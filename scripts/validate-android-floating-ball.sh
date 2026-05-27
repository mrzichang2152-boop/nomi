#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-android_app}"

require_file() {
  test -f "$ROOT/$1" || {
    echo "missing file: $ROOT/$1" >&2
    exit 1
  }
}

require_text() {
  local file="$1"
  local text="$2"
  grep -q "$text" "$ROOT/$file" || {
    echo "missing text '$text' in $ROOT/$file" >&2
    exit 1
  }
}

require_file "settings.gradle"
require_file "build.gradle"
require_file "app/build.gradle"
require_file "app/src/main/AndroidManifest.xml"
require_file "app/src/main/java/com/par/assistant/android/MainActivity.java"
require_file "app/src/main/java/com/par/assistant/android/FloatingBallService.java"
require_file "app/src/main/java/com/par/assistant/android/WebWorkspaceActivity.java"
require_file "app/src/main/java/com/par/assistant/android/AssistantApiClient.java"
require_file "app/src/main/java/com/par/assistant/android/SuggestionPoller.java"
require_file "shared/src/main/java/com/par/assistant/core/ServerConfig.java"
require_file "shared/src/main/java/com/par/assistant/core/SuggestionDeduper.java"

require_text "app/src/main/AndroidManifest.xml" "android.permission.SYSTEM_ALERT_WINDOW"
require_text "app/src/main/AndroidManifest.xml" "android.permission.FOREGROUND_SERVICE"
require_text "app/src/main/AndroidManifest.xml" "android.permission.INTERNET"
require_text "app/src/main/AndroidManifest.xml" "FloatingBallService"
require_text "app/src/main/AndroidManifest.xml" "WebWorkspaceActivity"
require_text "app/src/main/java/com/par/assistant/android/FloatingBallService.java" "WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY"
require_text "app/src/main/java/com/par/assistant/android/FloatingBallService.java" "startForeground"
require_text "app/src/main/java/com/par/assistant/android/AssistantApiClient.java" "/api/suggestions"
require_text "app/src/main/java/com/par/assistant/android/SuggestionPoller.java" "filterNew"
require_text "app/src/main/java/com/par/assistant/android/AssistantApiClient.java" "x-par-password"
require_text "app/src/main/java/com/par/assistant/android/WebWorkspaceActivity.java" "WebView"

echo "Android floating ball structure looks good"
