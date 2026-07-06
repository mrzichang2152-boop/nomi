# iOS Dynamic Island Interaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an iOS client for Nomi that uses Live Activities and the Dynamic Island as the iOS equivalent of the Android floating-ball ambient surface, including opt-in token-level reply streaming, opt-in sensitive APNs payloads, and tap-to-open deep links into the app.

**Architecture:** Reuse the existing Nomi runtime API, `/ws` realtime channel, `/ws/voice`, `/api/chat`, `/api/suggestions`, and proactive suggestion action endpoints. Add a narrow iOS Live Activity layer: device/activity registration tables, APNs delivery adapter, Redis realtime bridge, and a chat streaming hook inside `stream_chat_to_websocket()` for token-level Dynamic Island updates.

**Tech Stack:** FastAPI, psycopg, Redis Pub/Sub, httpx HTTP/2, APNs token authentication, SwiftUI, ActivityKit, WidgetKit, App Intents, URL deep links, Keychain.

---

## 2026-06-18 Implementation Status

本轮已按该方案开始落地开发：后端 iOS Live Activity schema/settings/registration/APNs/realtime bridge/token-level chat hook 已实现；iOS SwiftUI app、ActivityKit controller、WidgetKit Dynamic Island UI、deep links、App Intents 和 settings UI 已实现；focused backend tests、iOS XCTest、模拟器 build/install/launch 均通过。2026-06-18 追加修复了本地模拟器不展示的问题：app 现在会在开关开启时调用 `Activity.request(...)` 自动启动 Live Activity，Settings 也提供 Start/Preview/Stop，模拟器 Home Screen 上已验证 Dynamic Island 显示 `N, •` 且点击可回到 app。

由于当前仓库已有大量未提交改动且不是 linked worktree，本轮未按每个 task 自动 commit，也没有批量勾选下方 checklist。验证结果见 `docs/superpowers/reports/2026-06-18-ios-dynamic-island-regression.md`，未闭环项见 `docs/superpowers/reports/2026-06-18-ios-dynamic-island-implementation-gaps.md`。

## Non-Negotiable Requirements

- Token-level `chat_delta` updates to the Dynamic Island must be implemented.
- Sensitive APNs payload mode must be implemented, including Gmail/WhatsApp body/contact/private-context snippets when the user explicitly enables it.
- Both risky behaviors must be controlled by user-facing switches, with conservative defaults.
- Tapping the Dynamic Island or Lock Screen Live Activity must open the iOS app at the relevant conversation, suggestion, task, or settings screen.
- Backend changes must reuse the existing event and realtime architecture as much as possible.

## Existing Backend Reuse Map

- Reuse `/ws` in `runtime_api/app/main.py:12035` for foreground realtime chat and proactive messages.
- Reuse `stream_chat_to_websocket()` in `runtime_api/app/main.py:12089` for token-level chat streaming.
- Reuse `/ws/voice` in `runtime_api/app/main.py:12064` for iOS voice input after the basic app works.
- Reuse `/api/suggestions` in `runtime_api/app/main.py:13688` for suggestion list hydration after a deep link opens the app.
- Reuse `PATCH /api/suggestions/{suggestion_id}` in `runtime_api/app/main.py:14102` for done/dismissed actions.
- Reuse `POST /api/proactive/suggestions/{suggestion_id}/action` in `runtime_api/app/main.py:13744` for action-card execution.
- Reuse worker proactive message shape from `worker/app/worker.py:1146`.
- Reuse Redis `REALTIME_CHANNEL` from `runtime_api/app/main.py:84` and `worker/app/worker.py:29`.
- Reuse Android protocol semantics from `android_app/app/src/main/java/com/par/assistant/android/RealtimeClient.java:103`.

## Product Behavior

### Dynamic Island States

- `idle`: Nomi is connected and waiting.
- `suggestion`: a proactive suggestion is open.
- `task_running`: long-tail task or pipeline is running.
- `task_needs_attention`: task fallback, confirmation, or compensation is needed.
- `task_done`: task delivery is ready.
- `chat_streaming`: Nomi is replying.
- `voice_listening`: user explicitly started voice input inside the app.
- `error`: Nomi cannot reach the private-cloud runtime or APNs delivery failed.

### User Switches

All switches live in the iOS app under Settings > Dynamic Island.

```swift
struct NomiIslandSettings: Codable, Equatable {
    var liveActivityEnabled: Bool = true
    var notificationFallbackEnabled: Bool = true
    var deepLinksEnabled: Bool = true

    // Required by product: implemented but default off.
    var tokenLevelChatStreamingEnabled: Bool = false
    var tokenLevelChatDelivery: TokenLevelChatDelivery = .localWhenForeground

    // Required by product: implemented but default off.
    var sensitiveApnsPayloadEnabled: Bool = false
    var includePrivateMessageBody: Bool = false
    var includeContactNames: Bool = false
    var includeRawPrivateContext: Bool = false
    var maxSensitivePayloadChars: Int = 2400

    enum CodingKeys: String, CodingKey {
        case liveActivityEnabled = "live_activity_enabled"
        case notificationFallbackEnabled = "notification_fallback_enabled"
        case deepLinksEnabled = "deep_links_enabled"
        case tokenLevelChatStreamingEnabled = "token_level_chat_streaming_enabled"
        case tokenLevelChatDelivery = "token_level_chat_delivery"
        case sensitiveApnsPayloadEnabled = "sensitive_apns_payload_enabled"
        case includePrivateMessageBody = "include_private_message_body"
        case includeContactNames = "include_contact_names"
        case includeRawPrivateContext = "include_raw_private_context"
        case maxSensitivePayloadChars = "max_sensitive_payload_chars"
    }
}

enum TokenLevelChatDelivery: String, Codable, CaseIterable {
    case localWhenForeground = "local_when_foreground"
    case apnsBestEffort = "apns_best_effort"
    case localAndApnsBestEffort = "local_and_apns_best_effort"
}
```

Default behavior is safe but not feature-limited:

- Token-level streaming exists, but the default mode updates the Live Activity locally only while the iOS app is connected to `/ws`.
- APNs token-level mode exists and attempts every `chat_delta` update when enabled, but the UI must label it "best effort" because iOS/APNs can throttle or drop frequent updates.
- Sensitive payload mode exists, but all body/contact/raw context switches default to off.
- If sensitive payload mode is off, APNs receives IDs, source labels, counts, and short generic status only.
- If sensitive payload mode is on, APNs receives private snippets up to the payload budget. Anything larger is truncated and marked `truncated: true`.

### Deep Links

Use a custom URL scheme and universal-link-ready path format:

```text
nomi://chat?conversation_id=<uuid>
nomi://suggestion?id=<uuid>
nomi://task?id=<task_id>
nomi://settings/live-activity
nomi://career/opportunity?id=<job_id>
```

Live Activity views set `widgetURL` to the state deep link. Buttons use App Intents for quick actions and open the app only when the action needs review.

## File Structure

### Backend Files

- Create `runtime_api/app/ios_live_activity.py`
  - Owns schema SQL, settings normalization, payload shaping, private-event enrichment, APNs budget truncation, and delivery audit records.
- Create `runtime_api/app/ios_apns.py`
  - Owns APNs JWT signing and HTTP/2 delivery.
- Modify `runtime_api/app/main.py`
  - Imports iOS modules, calls schema ensure, exposes registration/settings endpoints, starts Redis bridge, and hooks chat deltas.
- Modify `runtime_api/requirements.txt`
  - Adds `h2` so `httpx.AsyncClient(http2=True)` can talk to APNs.
- Create `runtime_api/tests/test_ios_live_activity.py`
  - Unit tests for settings, payload privacy modes, APNs payload generation, endpoints, and chat-delta hook.
- Modify `.env.example`
  - Documents APNs and iOS feature flags.

### iOS Files

Create a new native iOS project under `ios_app/Nomi/`:

- Create `ios_app/Nomi/Nomi/NomiApp.swift`
- Create `ios_app/Nomi/Nomi/AppState.swift`
- Create `ios_app/Nomi/Nomi/DeepLinkRouter.swift`
- Create `ios_app/Nomi/Nomi/ServerConfig.swift`
- Create `ios_app/Nomi/Nomi/NomiApiClient.swift`
- Create `ios_app/Nomi/Nomi/NomiRealtimeClient.swift`
- Create `ios_app/Nomi/Nomi/NomiKeychain.swift`
- Create `ios_app/Nomi/Nomi/NomiIslandSettings.swift`
- Create `ios_app/Nomi/Nomi/NomiLiveActivityAttributes.swift`
- Create `ios_app/Nomi/Nomi/NomiLiveActivityController.swift`
- Create `ios_app/Nomi/Nomi/Views/ChatView.swift`
- Create `ios_app/Nomi/Nomi/Views/SuggestionListView.swift`
- Create `ios_app/Nomi/Nomi/Views/SettingsView.swift`
- Create `ios_app/Nomi/NomiWidgets/NomiLiveActivityWidget.swift`
- Create `ios_app/Nomi/NomiIntents/NomiSuggestionIntents.swift`
- Create `ios_app/Nomi/NomiTests/NomiApiClientTests.swift`
- Create `ios_app/Nomi/NomiTests/NomiRealtimeClientTests.swift`
- Create `ios_app/Nomi/NomiTests/NomiLiveActivityControllerTests.swift`
- Create `ios_app/Nomi/NomiWidgetsTests/NomiLiveActivityWidgetTests.swift`

## Backend Data Model

Add these tables through `ensure_ios_live_activity_schema()`:

```sql
CREATE TABLE IF NOT EXISTS ios_devices (
  id UUID PRIMARY KEY,
  device_id TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL DEFAULT '',
  apns_environment TEXT NOT NULL DEFAULT 'sandbox',
  apns_device_token TEXT NOT NULL DEFAULT '',
  live_activity_push_to_start_token TEXT NOT NULL DEFAULT '',
  settings JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ios_live_activities (
  id UUID PRIMARY KEY,
  device_id TEXT NOT NULL REFERENCES ios_devices(device_id) ON DELETE CASCADE,
  activity_id TEXT NOT NULL UNIQUE,
  activity_kind TEXT NOT NULL DEFAULT 'nomi_status',
  update_token TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  last_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ios_live_activity_events (
  id UUID PRIMARY KEY,
  activity_id TEXT NOT NULL,
  device_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  source_id TEXT NOT NULL DEFAULT '',
  payload_mode TEXT NOT NULL DEFAULT 'safe',
  delivery_status TEXT NOT NULL DEFAULT 'pending',
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  error TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ios_live_activities_device_status_idx
ON ios_live_activities(device_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS ios_live_activity_events_activity_idx
ON ios_live_activity_events(activity_id, created_at DESC);
```

## APNs Payload Shape

Safe mode:

```json
{
  "aps": {
    "timestamp": 1781712000,
    "event": "update",
    "content-state": {
      "phase": "suggestion",
      "title": "Nomi has a new suggestion",
      "body": "Open Nomi to review it.",
      "source": "whatsapp",
      "suggestionId": "suggestion-uuid",
      "taskId": "",
      "conversationId": "",
      "unreadCount": 3,
      "partialAnswer": "",
      "tokenSequence": 0,
      "payloadMode": "safe",
      "deepLink": "nomi://suggestion?id=suggestion-uuid",
      "truncated": false
    },
    "stale-date": 1781712600
  }
}
```

Sensitive mode:

```json
{
  "aps": {
    "timestamp": 1781712000,
    "event": "update",
    "content-state": {
      "phase": "suggestion",
      "title": "客户问报价什么时候截止",
      "body": "Alice: 这个报价今天还能确认吗？",
      "source": "whatsapp",
      "suggestionId": "suggestion-uuid",
      "taskId": "",
      "conversationId": "",
      "unreadCount": 3,
      "partialAnswer": "",
      "tokenSequence": 0,
      "payloadMode": "sensitive",
      "deepLink": "nomi://suggestion?id=suggestion-uuid",
      "privateContext": {
        "contact": "Alice",
        "channel": "whatsapp",
        "rawSnippet": "Alice: 这个报价今天还能确认吗？"
      },
      "truncated": false
    },
    "stale-date": 1781712600
  }
}
```

Token-level chat delta update:

```json
{
  "aps": {
    "timestamp": 1781712000,
    "event": "update",
    "content-state": {
      "phase": "chat_streaming",
      "title": "Nomi is replying",
      "body": "正在生成回复",
      "source": "chat",
      "suggestionId": "",
      "taskId": "",
      "conversationId": "conversation-uuid",
      "unreadCount": 0,
      "partialAnswer": "可以，我先帮你核对",
      "tokenSequence": 42,
      "payloadMode": "sensitive",
      "deepLink": "nomi://chat?conversation_id=conversation-uuid",
      "truncated": false
    }
  }
}
```

## Task 1: Backend iOS Schema And Settings Endpoints

**Files:**
- Create: `runtime_api/app/ios_live_activity.py`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_ios_live_activity.py`

- [ ] **Step 1: Write failing tests for settings normalization**

Add to `runtime_api/tests/test_ios_live_activity.py`:

```python
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_ios_settings_defaults_are_conservative():
    from app.ios_live_activity import normalize_ios_live_activity_settings

    settings = normalize_ios_live_activity_settings({})

    assert settings["live_activity_enabled"] is True
    assert settings["notification_fallback_enabled"] is True
    assert settings["deep_links_enabled"] is True
    assert settings["token_level_chat_streaming_enabled"] is False
    assert settings["token_level_chat_delivery"] == "local_when_foreground"
    assert settings["sensitive_apns_payload_enabled"] is False
    assert settings["include_private_message_body"] is False
    assert settings["include_contact_names"] is False
    assert settings["include_raw_private_context"] is False
    assert settings["max_sensitive_payload_chars"] == 2400


def test_ios_settings_accept_explicit_sensitive_and_token_modes():
    from app.ios_live_activity import normalize_ios_live_activity_settings

    settings = normalize_ios_live_activity_settings(
        {
            "token_level_chat_streaming_enabled": True,
            "token_level_chat_delivery": "local_and_apns_best_effort",
            "sensitive_apns_payload_enabled": True,
            "include_private_message_body": True,
            "include_contact_names": True,
            "include_raw_private_context": True,
            "max_sensitive_payload_chars": 3200,
        }
    )

    assert settings["token_level_chat_streaming_enabled"] is True
    assert settings["token_level_chat_delivery"] == "local_and_apns_best_effort"
    assert settings["sensitive_apns_payload_enabled"] is True
    assert settings["include_private_message_body"] is True
    assert settings["include_contact_names"] is True
    assert settings["include_raw_private_context"] is True
    assert settings["max_sensitive_payload_chars"] == 3200
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest runtime_api/tests/test_ios_live_activity.py -q
```

Expected: FAIL because `app.ios_live_activity` does not exist.

- [ ] **Step 3: Implement settings helpers**

Create `runtime_api/app/ios_live_activity.py` with:

```python
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

IOS_LIVE_ACTIVITY_DEFAULT_SETTINGS: dict[str, Any] = {
    "live_activity_enabled": True,
    "notification_fallback_enabled": True,
    "deep_links_enabled": True,
    "token_level_chat_streaming_enabled": False,
    "token_level_chat_delivery": "local_when_foreground",
    "sensitive_apns_payload_enabled": False,
    "include_private_message_body": False,
    "include_contact_names": False,
    "include_raw_private_context": False,
    "max_sensitive_payload_chars": 2400,
}

TOKEN_DELIVERY_MODES = {
    "local_when_foreground",
    "apns_best_effort",
    "local_and_apns_best_effort",
}


def normalize_ios_live_activity_settings(value: dict[str, Any] | None) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    settings = dict(IOS_LIVE_ACTIVITY_DEFAULT_SETTINGS)
    for key in settings:
        if key in raw:
            settings[key] = raw[key]
    if settings["token_level_chat_delivery"] not in TOKEN_DELIVERY_MODES:
        settings["token_level_chat_delivery"] = "local_when_foreground"
    settings["max_sensitive_payload_chars"] = max(
        0,
        min(3400, int(settings.get("max_sensitive_payload_chars") or 0)),
    )
    for key in [
        "live_activity_enabled",
        "notification_fallback_enabled",
        "deep_links_enabled",
        "token_level_chat_streaming_enabled",
        "sensitive_apns_payload_enabled",
        "include_private_message_body",
        "include_contact_names",
        "include_raw_private_context",
    ]:
        settings[key] = bool(settings.get(key))
    return settings


def ios_live_activity_schema_sql() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS ios_devices (
          id UUID PRIMARY KEY,
          device_id TEXT NOT NULL UNIQUE,
          display_name TEXT NOT NULL DEFAULT '',
          apns_environment TEXT NOT NULL DEFAULT 'sandbox',
          apns_device_token TEXT NOT NULL DEFAULT '',
          live_activity_push_to_start_token TEXT NOT NULL DEFAULT '',
          settings JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ios_live_activities (
          id UUID PRIMARY KEY,
          device_id TEXT NOT NULL REFERENCES ios_devices(device_id) ON DELETE CASCADE,
          activity_id TEXT NOT NULL UNIQUE,
          activity_kind TEXT NOT NULL DEFAULT 'nomi_status',
          update_token TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          last_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          ended_at TIMESTAMPTZ
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ios_live_activity_events (
          id UUID PRIMARY KEY,
          activity_id TEXT NOT NULL,
          device_id TEXT NOT NULL,
          event_type TEXT NOT NULL,
          source_id TEXT NOT NULL DEFAULT '',
          payload_mode TEXT NOT NULL DEFAULT 'safe',
          delivery_status TEXT NOT NULL DEFAULT 'pending',
          payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          error TEXT NOT NULL DEFAULT '',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS ios_live_activities_device_status_idx
        ON ios_live_activities(device_id, status, updated_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS ios_live_activity_events_activity_idx
        ON ios_live_activity_events(activity_id, created_at DESC)
        """,
    ]
```

- [ ] **Step 4: Wire schema into startup**

Modify `runtime_api/app/main.py`:

```python
from app.ios_live_activity import (
    ios_live_activity_schema_sql,
    normalize_ios_live_activity_settings,
)
```

Add to lifespan after `ensure_model_gateway_schema()`:

```python
    ensure_ios_live_activity_schema()
```

Add near other `ensure_*_schema()` functions:

```python
def ensure_ios_live_activity_schema() -> None:
    with db() as conn:
        for sql in ios_live_activity_schema_sql():
            conn.execute(sql)
```

- [ ] **Step 5: Add endpoint models**

Modify `runtime_api/app/main.py` near other Pydantic models:

```python
class IOSDeviceRegisterIn(BaseModel):
    device_id: str = Field(min_length=1, max_length=160)
    display_name: str = ""
    apns_environment: str = Field(default="sandbox", pattern="^(sandbox|production)$")
    apns_device_token: str = ""
    live_activity_push_to_start_token: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)


class IOSDeviceSettingsIn(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


class IOSLiveActivityRegisterIn(BaseModel):
    device_id: str = Field(min_length=1, max_length=160)
    activity_id: str = Field(min_length=1, max_length=180)
    activity_kind: str = "nomi_status"
    update_token: str = Field(min_length=1)
```

- [ ] **Step 6: Add registration endpoints**

Modify `runtime_api/app/main.py` after collector/settings APIs:

```python
@app.post("/api/ios/devices/register")
def register_ios_device(
    body: IOSDeviceRegisterIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    settings = normalize_ios_live_activity_settings(body.settings)
    with db() as conn:
        conn.execute(
            """
            INSERT INTO ios_devices
              (id, device_id, display_name, apns_environment, apns_device_token,
               live_activity_push_to_start_token, settings, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (device_id) DO UPDATE SET
              display_name = EXCLUDED.display_name,
              apns_environment = EXCLUDED.apns_environment,
              apns_device_token = EXCLUDED.apns_device_token,
              live_activity_push_to_start_token = EXCLUDED.live_activity_push_to_start_token,
              settings = EXCLUDED.settings,
              updated_at = now()
            """,
            (
                uuid.uuid4(),
                body.device_id,
                body.display_name,
                body.apns_environment,
                body.apns_device_token,
                body.live_activity_push_to_start_token,
                json.dumps(settings),
            ),
        )
    return {"device_id": body.device_id, "settings": settings}


@app.patch("/api/ios/devices/{device_id}/settings")
def update_ios_device_settings(
    device_id: str,
    body: IOSDeviceSettingsIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    settings = normalize_ios_live_activity_settings(body.settings)
    with db() as conn:
        cur = conn.execute(
            """
            UPDATE ios_devices
            SET settings = %s, updated_at = now()
            WHERE device_id = %s
            """,
            (json.dumps(settings), device_id),
        )
    if not cur.rowcount:
        raise HTTPException(status_code=404, detail="ios device not found")
    return {"device_id": device_id, "settings": settings}


@app.post("/api/ios/live-activities/register")
def register_ios_live_activity(
    body: IOSLiveActivityRegisterIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    with db() as conn:
        device = conn.execute(
            "SELECT device_id FROM ios_devices WHERE device_id = %s",
            (body.device_id,),
        ).fetchone()
        if not device:
            raise HTTPException(status_code=404, detail="ios device not found")
        conn.execute(
            """
            INSERT INTO ios_live_activities
              (id, device_id, activity_id, activity_kind, update_token, status, updated_at)
            VALUES (%s, %s, %s, %s, %s, 'active', now())
            ON CONFLICT (activity_id) DO UPDATE SET
              device_id = EXCLUDED.device_id,
              activity_kind = EXCLUDED.activity_kind,
              update_token = EXCLUDED.update_token,
              status = 'active',
              ended_at = NULL,
              updated_at = now()
            """,
            (uuid.uuid4(), body.device_id, body.activity_id, body.activity_kind, body.update_token),
        )
    return {"activity_id": body.activity_id, "device_id": body.device_id, "status": "active"}
```

- [ ] **Step 7: Run backend tests**

Run:

```bash
pytest runtime_api/tests/test_ios_live_activity.py runtime_api/tests/test_auth_and_model.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add runtime_api/app/ios_live_activity.py runtime_api/app/main.py runtime_api/tests/test_ios_live_activity.py
git commit -m "feat: add ios live activity registration"
```

## Task 2: Payload Builder With Safe And Sensitive Modes

**Files:**
- Modify: `runtime_api/app/ios_live_activity.py`
- Test: `runtime_api/tests/test_ios_live_activity.py`

- [ ] **Step 1: Add failing tests for safe/sensitive APNs content**

Add:

```python
def test_safe_payload_excludes_private_message_body():
    from app.ios_live_activity import build_live_activity_content_state

    event = {
        "type": "proactive_message",
        "suggestion_id": "s1",
        "title": "客户问报价",
        "body": "Alice: 报价今天还能确认吗？",
        "source": "whatsapp",
    }
    settings = {
        "sensitive_apns_payload_enabled": False,
        "deep_links_enabled": True,
    }

    state = build_live_activity_content_state(event, settings, private_context={"contact": "Alice"})

    assert state["payloadMode"] == "safe"
    assert state["title"] == "Nomi has a new suggestion"
    assert state["body"] == "Open Nomi to review it."
    assert "privateContext" not in state
    assert state["deepLink"] == "nomi://suggestion?id=s1"


def test_sensitive_payload_includes_user_enabled_private_context():
    from app.ios_live_activity import build_live_activity_content_state

    event = {
        "type": "proactive_message",
        "suggestion_id": "s1",
        "title": "客户问报价",
        "body": "Alice: 报价今天还能确认吗？",
        "source": "whatsapp",
    }
    settings = {
        "sensitive_apns_payload_enabled": True,
        "include_private_message_body": True,
        "include_contact_names": True,
        "include_raw_private_context": True,
        "max_sensitive_payload_chars": 2400,
        "deep_links_enabled": True,
    }

    state = build_live_activity_content_state(
        event,
        settings,
        private_context={"contact": "Alice", "channel": "whatsapp", "rawSnippet": "Alice: 报价今天还能确认吗？"},
    )

    assert state["payloadMode"] == "sensitive"
    assert state["title"] == "客户问报价"
    assert state["body"] == "Alice: 报价今天还能确认吗？"
    assert state["privateContext"]["contact"] == "Alice"
    assert state["privateContext"]["rawSnippet"] == "Alice: 报价今天还能确认吗？"
```

- [ ] **Step 2: Implement payload helpers**

Add to `runtime_api/app/ios_live_activity.py`:

```python
def deep_link_for_event(event: dict[str, Any], settings: dict[str, Any]) -> str:
    if not settings.get("deep_links_enabled", True):
        return "nomi://chat"
    event_type = str(event.get("type") or "")
    if event_type == "proactive_message":
        suggestion_id = str(event.get("suggestion_id") or event.get("id") or "")
        return f"nomi://suggestion?id={suggestion_id}" if suggestion_id else "nomi://chat"
    if event_type in {"agent_task_delivery", "agent_task_fallback"}:
        task_id = str(event.get("task_id") or "")
        return f"nomi://task?id={task_id}" if task_id else "nomi://chat"
    if event_type in {"chat_delta", "chat_done", "chat_streaming"}:
        conversation_id = str(event.get("conversation_id") or "")
        return f"nomi://chat?conversation_id={conversation_id}" if conversation_id else "nomi://chat"
    return "nomi://chat"


def build_live_activity_content_state(
    event: dict[str, Any],
    settings: dict[str, Any] | None,
    private_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = normalize_ios_live_activity_settings(settings)
    event_type = str(event.get("type") or "")
    source = str(event.get("source") or "unknown")
    sensitive = bool(normalized.get("sensitive_apns_payload_enabled"))
    private_context = private_context if isinstance(private_context, dict) else {}

    if event_type == "proactive_message":
        suggestion_id = str(event.get("suggestion_id") or event.get("id") or "")
        state = {
            "phase": "suggestion",
            "title": "Nomi has a new suggestion",
            "body": "Open Nomi to review it.",
            "source": source,
            "suggestionId": suggestion_id,
            "taskId": "",
            "conversationId": "",
            "unreadCount": int(event.get("unread_count") or 1),
            "partialAnswer": "",
            "tokenSequence": 0,
            "payloadMode": "safe",
            "deepLink": deep_link_for_event(event, normalized),
            "truncated": False,
        }
        if sensitive:
            state["payloadMode"] = "sensitive"
            if normalized.get("include_private_message_body"):
                state["title"] = str(event.get("title") or state["title"])
                state["body"] = str(event.get("body") or state["body"])
            if normalized.get("include_contact_names") or normalized.get("include_raw_private_context"):
                private_payload: dict[str, Any] = {}
                if normalized.get("include_contact_names") and private_context.get("contact"):
                    private_payload["contact"] = str(private_context["contact"])
                if private_context.get("channel"):
                    private_payload["channel"] = str(private_context["channel"])
                if normalized.get("include_raw_private_context") and private_context.get("rawSnippet"):
                    private_payload["rawSnippet"] = str(private_context["rawSnippet"])
                if private_payload:
                    state["privateContext"] = private_payload
        return trim_state_for_budget(state, normalized)

    if event_type in {"agent_task_delivery", "agent_task_fallback"}:
        task_id = str(event.get("task_id") or "")
        delivery = event.get("delivery") if isinstance(event.get("delivery"), dict) else {}
        fallback = event.get("fallback_decision") if isinstance(event.get("fallback_decision"), dict) else {}
        message = str(delivery.get("message") or fallback.get("message") or "Open Nomi to review the task.")
        return trim_state_for_budget(
            {
                "phase": "task_needs_attention" if event_type == "agent_task_fallback" else "task_done",
                "title": "Nomi task update",
                "body": message if sensitive else "Open Nomi to review the task.",
                "source": "long_tail_agent",
                "suggestionId": "",
                "taskId": task_id,
                "conversationId": "",
                "unreadCount": 0,
                "partialAnswer": "",
                "tokenSequence": 0,
                "payloadMode": "sensitive" if sensitive else "safe",
                "deepLink": deep_link_for_event(event, normalized),
                "truncated": False,
            },
            normalized,
        )

    if event_type == "chat_delta":
        partial_answer = str(event.get("partial_answer") or event.get("delta") or "")
        return trim_state_for_budget(
            {
                "phase": "chat_streaming",
                "title": "Nomi is replying",
                "body": "正在生成回复",
                "source": "chat",
                "suggestionId": "",
                "taskId": "",
                "conversationId": str(event.get("conversation_id") or ""),
                "unreadCount": 0,
                "partialAnswer": partial_answer if sensitive else "",
                "tokenSequence": int(event.get("token_sequence") or 0),
                "payloadMode": "sensitive" if sensitive else "safe",
                "deepLink": deep_link_for_event(event, normalized),
                "truncated": False,
            },
            normalized,
        )

    return {
        "phase": "idle",
        "title": "Nomi",
        "body": "Ready",
        "source": "system",
        "suggestionId": "",
        "taskId": "",
        "conversationId": "",
        "unreadCount": 0,
        "partialAnswer": "",
        "tokenSequence": 0,
        "payloadMode": "safe",
        "deepLink": "nomi://chat",
        "truncated": False,
    }


def trim_state_for_budget(state: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    limit = int(settings.get("max_sensitive_payload_chars") or 2400)
    encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= min(3600, limit + 900):
        return state
    trimmed = dict(state)
    trimmed["truncated"] = True
    for key in ["partialAnswer", "body"]:
        value = str(trimmed.get(key) or "")
        if len(value) > 240:
            trimmed[key] = value[-240:]
    private_context = trimmed.get("privateContext")
    if isinstance(private_context, dict):
        raw = str(private_context.get("rawSnippet") or "")
        if len(raw) > 360:
            private_context["rawSnippet"] = raw[-360:]
    return trimmed
```

- [ ] **Step 3: Run tests**

```bash
pytest runtime_api/tests/test_ios_live_activity.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add runtime_api/app/ios_live_activity.py runtime_api/tests/test_ios_live_activity.py
git commit -m "feat: shape ios live activity payloads"
```

## Task 3: APNs Client And Delivery Audit

**Files:**
- Create: `runtime_api/app/ios_apns.py`
- Modify: `runtime_api/requirements.txt`
- Modify: `.env.example`
- Test: `runtime_api/tests/test_ios_live_activity.py`

- [ ] **Step 1: Add dependency**

Append to `runtime_api/requirements.txt`:

```text
h2==4.1.0
```

- [ ] **Step 2: Add APNs environment variables to `.env.example`**

```text
# iOS Live Activity / Dynamic Island
ENABLE_IOS_LIVE_ACTIVITY_BRIDGE=false
APNS_TEAM_ID=
APNS_KEY_ID=
APNS_BUNDLE_ID=com.nomi.privatecloud
APNS_PRIVATE_KEY_P8=
APNS_ENVIRONMENT=sandbox
```

- [ ] **Step 3: Add failing APNs payload test**

Add:

```python
def test_apns_live_activity_payload_wraps_content_state():
    from app.ios_apns import build_live_activity_apns_payload

    payload = build_live_activity_apns_payload(
        {"phase": "idle", "title": "Nomi", "body": "Ready", "deepLink": "nomi://chat"},
        event="update",
        stale_after_seconds=600,
    )

    assert payload["aps"]["event"] == "update"
    assert payload["aps"]["content-state"]["title"] == "Nomi"
    assert "timestamp" in payload["aps"]
    assert "stale-date" in payload["aps"]
```

- [ ] **Step 4: Implement APNs client**

Create `runtime_api/app/ios_apns.py`:

```python
from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def build_live_activity_apns_payload(
    content_state: dict[str, Any],
    event: str = "update",
    stale_after_seconds: int = 600,
) -> dict[str, Any]:
    now = int(time.time())
    return {
        "aps": {
            "timestamp": now,
            "event": event,
            "content-state": content_state,
            "stale-date": now + max(60, stale_after_seconds),
        }
    }


@dataclass(frozen=True)
class APNsConfig:
    team_id: str
    key_id: str
    bundle_id: str
    private_key_p8: str
    environment: str = "sandbox"

    @property
    def base_url(self) -> str:
        if self.environment == "production":
            return "https://api.push.apple.com"
        return "https://api.sandbox.push.apple.com"

    @property
    def live_activity_topic(self) -> str:
        return f"{self.bundle_id}.push-type.liveactivity"


def apns_config_from_env() -> APNsConfig:
    return APNsConfig(
        team_id=os.getenv("APNS_TEAM_ID", "").strip(),
        key_id=os.getenv("APNS_KEY_ID", "").strip(),
        bundle_id=os.getenv("APNS_BUNDLE_ID", "").strip(),
        private_key_p8=os.getenv("APNS_PRIVATE_KEY_P8", "").replace("\\\\n", "\n").strip(),
        environment=os.getenv("APNS_ENVIRONMENT", "sandbox").strip() or "sandbox",
    )


def apns_jwt(config: APNsConfig, issued_at: int | None = None) -> str:
    issued_at = issued_at or int(time.time())
    header = {"alg": "ES256", "kid": config.key_id}
    claims = {"iss": config.team_id, "iat": issued_at}
    signing_input = f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}.{_b64url(json.dumps(claims, separators=(',', ':')).encode())}"
    private_key = serialization.load_pem_private_key(config.private_key_p8.encode("utf-8"), password=None)
    if not isinstance(private_key, ec.EllipticCurvePrivateKey):
        raise ValueError("APNs private key must be an EC private key")
    der_signature = private_key.sign(signing_input.encode("ascii"), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_signature)
    raw_signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"{signing_input}.{_b64url(raw_signature)}"


class APNsLiveActivityClient:
    def __init__(self, config: APNsConfig | None = None):
        self.config = config or apns_config_from_env()

    def configured(self) -> bool:
        return all([self.config.team_id, self.config.key_id, self.config.bundle_id, self.config.private_key_p8])

    async def send_update(self, update_token: str, content_state: dict[str, Any]) -> dict[str, Any]:
        if not self.configured():
            return {"status": "misconfigured", "status_code": 0, "error": "APNs configuration missing"}
        payload = build_live_activity_apns_payload(content_state)
        headers = {
            "authorization": f"bearer {apns_jwt(self.config)}",
            "apns-topic": self.config.live_activity_topic,
            "apns-push-type": "liveactivity",
            "apns-priority": "10",
        }
        async with httpx.AsyncClient(http2=True, timeout=10.0) as client:
            response = await client.post(
                f"{self.config.base_url}/3/device/{update_token}",
                headers=headers,
                json=payload,
            )
        if 200 <= response.status_code < 300:
            return {"status": "sent", "status_code": response.status_code, "payload": payload}
        return {"status": "failed", "status_code": response.status_code, "error": response.text[:500], "payload": payload}
```

- [ ] **Step 5: Run tests**

```bash
pytest runtime_api/tests/test_ios_live_activity.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime_api/app/ios_apns.py runtime_api/requirements.txt .env.example runtime_api/tests/test_ios_live_activity.py
git commit -m "feat: add apns live activity client"
```

## Task 4: Redis Realtime Bridge For Suggestions And Task Updates

**Files:**
- Modify: `runtime_api/app/ios_live_activity.py`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_ios_live_activity.py`

- [ ] **Step 1: Add bridge selection test**

Add:

```python
def test_realtime_event_maps_to_live_activity_state_for_active_ios_device():
    from app.ios_live_activity import build_live_activity_content_state

    state = build_live_activity_content_state(
        {
            "type": "agent_task_delivery",
            "task_id": "lta_1",
            "delivery": {"message": "邮件草稿已准备"},
        },
        {"sensitive_apns_payload_enabled": True, "deep_links_enabled": True},
    )

    assert state["phase"] == "task_done"
    assert state["taskId"] == "lta_1"
    assert state["deepLink"] == "nomi://task?id=lta_1"
```

- [ ] **Step 2: Add active activity lookup and audit helpers**

Add to `runtime_api/app/ios_live_activity.py`:

```python
def active_ios_live_activities(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT a.activity_id, a.device_id, a.update_token, d.settings
        FROM ios_live_activities a
        JOIN ios_devices d ON d.device_id = a.device_id
        WHERE a.status = 'active'
        ORDER BY a.updated_at DESC
        """
    ).fetchall()
    return [
        {
            "activity_id": row[0],
            "device_id": row[1],
            "update_token": row[2],
            "settings": normalize_ios_live_activity_settings(row[3] or {}),
        }
        for row in rows
    ]


def record_ios_live_activity_delivery(
    conn: Any,
    activity_id: str,
    device_id: str,
    event_type: str,
    source_id: str,
    payload_mode: str,
    delivery_status: str,
    payload: dict[str, Any],
    error: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO ios_live_activity_events
          (id, activity_id, device_id, event_type, source_id, payload_mode, delivery_status, payload, error)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            uuid.uuid4(),
            activity_id,
            device_id,
            event_type,
            source_id,
            payload_mode,
            delivery_status,
            json.dumps(payload, ensure_ascii=False),
            error,
        ),
    )
```

- [ ] **Step 3: Add bridge loop in `main.py`**

Import:

```python
from app.ios_apns import APNsLiveActivityClient
from app.ios_live_activity import (
    active_ios_live_activities,
    build_live_activity_content_state,
    ios_live_activity_schema_sql,
    normalize_ios_live_activity_settings,
    record_ios_live_activity_delivery,
)
```

Add env flag:

```python
ENABLE_IOS_LIVE_ACTIVITY_BRIDGE = os.getenv("ENABLE_IOS_LIVE_ACTIVITY_BRIDGE", "false").lower() == "true"
```

Add to lifespan:

```python
    if ENABLE_IOS_LIVE_ACTIVITY_BRIDGE:
        tasks.append(asyncio.create_task(ios_live_activity_realtime_bridge_loop()))
```

Add bridge function after `redis_realtime_listener()`:

```python
async def ios_live_activity_realtime_bridge_loop() -> None:
    client = aioredis.Redis.from_url(REDIS_URL, decode_responses=True)
    pubsub = client.pubsub()
    apns = APNsLiveActivityClient()
    try:
        await pubsub.subscribe(REALTIME_CHANNEL)
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                event = json.loads(message.get("data") or "{}")
            except json.JSONDecodeError:
                continue
            await push_realtime_event_to_ios_live_activities(event, apns)
    except asyncio.CancelledError:
        raise
    finally:
        await pubsub.close()
        await client.close()


async def push_realtime_event_to_ios_live_activities(event: dict[str, Any], apns: APNsLiveActivityClient) -> None:
    if event.get("type") not in {"proactive_message", "agent_task_delivery", "agent_task_fallback"}:
        return
    with db() as conn:
        activities = active_ios_live_activities(conn)
        for activity in activities:
            settings = activity["settings"]
            if not settings.get("live_activity_enabled", True):
                continue
            private_context = fetch_ios_private_context_for_event(conn, event, settings)
            state = build_live_activity_content_state(event, settings, private_context=private_context)
            result = await apns.send_update(activity["update_token"], state)
            record_ios_live_activity_delivery(
                conn,
                activity_id=activity["activity_id"],
                device_id=activity["device_id"],
                event_type=str(event.get("type") or ""),
                source_id=str(event.get("suggestion_id") or event.get("task_id") or event.get("id") or ""),
                payload_mode=str(state.get("payloadMode") or "safe"),
                delivery_status=str(result.get("status") or "unknown"),
                payload=result.get("payload") or {"content_state": state},
                error=str(result.get("error") or ""),
            )
```

- [ ] **Step 4: Add private context enrichment**

Add to `main.py` near bridge helpers:

```python
def fetch_ios_private_context_for_event(
    conn: psycopg.Connection,
    event: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    if not settings.get("sensitive_apns_payload_enabled"):
        return {}
    if not (settings.get("include_contact_names") or settings.get("include_raw_private_context")):
        return {}
    source_event_id = str(event.get("source_event_id") or "")
    if not source_event_id:
        return {}
    row = conn.execute(
        """
        SELECT source, event_type, COALESCE(raw_data_private, raw_data)
        FROM events
        WHERE id = %s
        """,
        (source_event_id,),
    ).fetchone()
    if not row:
        return {}
    raw = row[2] if isinstance(row[2], dict) else {}
    contact = (
        raw.get("sender")
        or raw.get("from")
        or raw.get("contact")
        or raw.get("chat_name")
        or raw.get("thread_title")
        or ""
    )
    raw_snippet = (
        raw.get("body")
        or raw.get("text")
        or raw.get("message")
        or raw.get("snippet")
        or raw.get("summary")
        or ""
    )
    return {
        "contact": str(contact)[:120],
        "channel": str(row[0] or event.get("source") or ""),
        "rawSnippet": str(raw_snippet)[: int(settings.get("max_sensitive_payload_chars") or 2400)],
    }
```

- [ ] **Step 5: Run tests**

```bash
pytest runtime_api/tests/test_ios_live_activity.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime_api/app/ios_live_activity.py runtime_api/app/main.py runtime_api/tests/test_ios_live_activity.py
git commit -m "feat: bridge realtime events to ios live activities"
```

## Task 5: Token-Level Chat Delta Hook

**Files:**
- Modify: `runtime_api/app/main.py`
- Modify: `runtime_api/app/ios_live_activity.py`
- Test: `runtime_api/tests/test_ios_live_activity.py`

- [ ] **Step 1: Add failing test for token event state**

Add:

```python
def test_chat_delta_state_includes_partial_answer_when_sensitive_streaming_is_enabled():
    from app.ios_live_activity import build_live_activity_content_state

    state = build_live_activity_content_state(
        {
            "type": "chat_delta",
            "conversation_id": "c1",
            "partial_answer": "可以，我先帮你",
            "token_sequence": 7,
        },
        {
            "token_level_chat_streaming_enabled": True,
            "sensitive_apns_payload_enabled": True,
            "deep_links_enabled": True,
        },
    )

    assert state["phase"] == "chat_streaming"
    assert state["partialAnswer"] == "可以，我先帮你"
    assert state["tokenSequence"] == 7
    assert state["deepLink"] == "nomi://chat?conversation_id=c1"
```

- [ ] **Step 2: Extend WebSocket chat message input**

In `websocket_realtime()` inside the `chat_message` branch, pass iOS fields:

```python
                await stream_chat_to_websocket(
                    websocket,
                    str(data.get("message") or ""),
                    int(data.get("limit") or 12),
                    conversation_id=data.get("conversation_id"),
                    client_type=str(data.get("client_type") or "realtime"),
                    client_request_id=str(data.get("client_request_id") or ""),
                    ios_live_activity_id=str(data.get("ios_live_activity_id") or ""),
                    ios_stream_to_live_activity=bool(data.get("ios_stream_to_live_activity") or False),
                )
```

Update the function signature:

```python
async def stream_chat_to_websocket(
    websocket: WebSocket,
    message: str,
    limit: int,
    conversation_id: Optional[str] = None,
    client_type: str = "realtime",
    client_request_id: Optional[str] = None,
    ios_live_activity_id: str = "",
    ios_stream_to_live_activity: bool = False,
) -> None:
```

- [ ] **Step 3: Add chat delta APNs helper**

Add to `main.py`:

```python
async def maybe_push_ios_chat_delta(
    activity_id: str,
    conversation_id: str,
    partial_answer: str,
    token_sequence: int,
    apns: APNsLiveActivityClient | None = None,
) -> None:
    if not activity_id:
        return
    apns = apns or APNsLiveActivityClient()
    with db() as conn:
        row = conn.execute(
            """
            SELECT a.activity_id, a.device_id, a.update_token, d.settings
            FROM ios_live_activities a
            JOIN ios_devices d ON d.device_id = a.device_id
            WHERE a.activity_id = %s AND a.status = 'active'
            """,
            (activity_id,),
        ).fetchone()
        if not row:
            return
        settings = normalize_ios_live_activity_settings(row[3] or {})
        if not settings.get("live_activity_enabled"):
            return
        if not settings.get("token_level_chat_streaming_enabled"):
            return
        if settings.get("token_level_chat_delivery") not in {"apns_best_effort", "local_and_apns_best_effort"}:
            return
        event = {
            "type": "chat_delta",
            "conversation_id": conversation_id,
            "partial_answer": partial_answer,
            "token_sequence": token_sequence,
        }
        state = build_live_activity_content_state(event, settings)
        result = await apns.send_update(row[2], state)
        record_ios_live_activity_delivery(
            conn,
            activity_id=row[0],
            device_id=row[1],
            event_type="chat_delta",
            source_id=conversation_id,
            payload_mode=str(state.get("payloadMode") or "safe"),
            delivery_status=str(result.get("status") or "unknown"),
            payload=result.get("payload") or {"content_state": state},
            error=str(result.get("error") or ""),
        )
```

- [ ] **Step 4: Call helper for every token**

Inside the `async for chunk in model_gateway().stream_chat(messages):` loop, after `await websocket.send_json(event)`:

```python
            if ios_stream_to_live_activity and ios_live_activity_id:
                asyncio.create_task(
                    maybe_push_ios_chat_delta(
                        ios_live_activity_id,
                        user_turn["conversation_id"],
                        "".join(answer_parts)[-800:],
                        len(answer_parts),
                    )
                )
```

This attempts one APNs update per model delta when the user enables APNs token mode. The app also updates the Activity locally from `/ws` deltas when foregrounded, so foreground behavior is not dependent on APNs.

- [ ] **Step 5: Run focused tests**

```bash
pytest runtime_api/tests/test_ios_live_activity.py runtime_api/tests/test_realtime_ws.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime_api/app/main.py runtime_api/app/ios_live_activity.py runtime_api/tests/test_ios_live_activity.py
git commit -m "feat: stream ios chat deltas to live activity"
```

## Task 6: iOS Project Scaffold And Shared Client Models

**Files:**
- Create iOS project under: `ios_app/Nomi/`
- Create files listed in the iOS file structure section.

- [ ] **Step 1: Create the Xcode project**

Use Xcode to create:

```text
Product Name: Nomi
Interface: SwiftUI
Language: Swift
Minimum Deployment: iOS 17.0
Bundle ID: com.<your-team>.nomi
Targets:
- Nomi app
- NomiWidgets widget extension with Live Activity support
- NomiIntents app intents extension if Xcode separates it
```

Enable capabilities:

```text
Nomi app:
- Push Notifications
- Background Modes: Remote notifications
- App Groups: group.com.<your-team>.nomi

NomiWidgets:
- App Groups: group.com.<your-team>.nomi
- Live Activities
```

- [ ] **Step 2: Add shared Live Activity attributes**

Create `ios_app/Nomi/Nomi/NomiLiveActivityAttributes.swift`:

```swift
import ActivityKit
import Foundation

struct NomiLiveActivityAttributes: ActivityAttributes {
    public struct ContentState: Codable, Hashable {
        var phase: String
        var title: String
        var body: String
        var source: String
        var suggestionId: String
        var taskId: String
        var conversationId: String
        var unreadCount: Int
        var partialAnswer: String
        var tokenSequence: Int
        var payloadMode: String
        var deepLink: String
        var truncated: Bool
        var privateContext: PrivateContext?
    }

    struct PrivateContext: Codable, Hashable {
        var contact: String?
        var channel: String?
        var rawSnippet: String?
    }

    var activityId: String
    var deviceId: String
}
```

- [ ] **Step 3: Add server config**

Create `ios_app/Nomi/Nomi/ServerConfig.swift`:

```swift
import Foundation

struct ServerConfig: Codable, Equatable {
    var baseURL: URL
    var password: String

    static func normalize(baseURL input: String, password: String) throws -> ServerConfig {
        var value = input.trimmingCharacters(in: .whitespacesAndNewlines)
        if value.isEmpty { throw ConfigError.missingBaseURL }
        if !value.contains("://") { value = "http://" + value }
        guard let url = URL(string: value), ["http", "https"].contains(url.scheme?.lowercased() ?? "") else {
            throw ConfigError.invalidBaseURL
        }
        let cleanPassword = password.trimmingCharacters(in: .whitespacesAndNewlines)
        if cleanPassword.isEmpty { throw ConfigError.missingPassword }
        return ServerConfig(baseURL: url, password: cleanPassword)
    }

    enum ConfigError: Error, Equatable {
        case missingBaseURL
        case invalidBaseURL
        case missingPassword
    }
}
```

- [ ] **Step 4: Add Keychain storage for server credentials**

Create `ios_app/Nomi/Nomi/NomiKeychain.swift` and add it to the app target and any App Intents target that calls backend actions:

```swift
import Foundation
import Security

enum NomiKeychain {
    private static let service = "com.nomi.private-cloud"
    private static let account = "server-config"

    static func saveServerConfig(_ config: ServerConfig) throws {
        let data = try JSONEncoder().encode(config)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        SecItemDelete(query as CFDictionary)
        var item = query
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(item as CFDictionary, nil)
        guard status == errSecSuccess else { throw KeychainError.unhandled(status) }
    }

    static func loadServerConfig() throws -> ServerConfig {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else {
            throw KeychainError.notFound
        }
        return try JSONDecoder().decode(ServerConfig.self, from: data)
    }

    enum KeychainError: Error, Equatable {
        case notFound
        case unhandled(OSStatus)
    }
}
```

- [ ] **Step 5: Add API client methods matching existing backend**

Create `ios_app/Nomi/Nomi/NomiApiClient.swift`:

```swift
import Foundation

struct AssistantSuggestion: Codable, Identifiable, Equatable {
    var id: String
    var title: String
    var body: String
    var priority: Double
}

struct ChatRequest: Codable {
    var message: String
    var conversation_id: String?
    var client_type: String = "ios"
    var client_request_id: String?
    var client_context_delta: [ChatTurn] = []
}

struct ChatTurn: Codable, Equatable {
    var role: String
    var content: String
}

struct ChatResponse: Codable, Equatable {
    var answer: String
    var conversation_id: String
}

final class NomiApiClient {
    private let config: ServerConfig
    private let session: URLSession

    init(config: ServerConfig, session: URLSession = .shared) {
        self.config = config
        self.session = session
    }

    func health() async throws -> Bool {
        let data = try await request(path: "/health", method: "GET", auth: false)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        return json?["status"] as? String == "ok"
    }

    func suggestions() async throws -> [AssistantSuggestion] {
        let data = try await request(path: "/api/suggestions", method: "GET", auth: true)
        return try JSONDecoder().decode([AssistantSuggestion].self, from: data)
    }

    func updateSuggestion(id: String, status: String) async throws {
        let body = try JSONEncoder().encode(["status": status])
        _ = try await request(path: "/api/suggestions/\(id)", method: "PATCH", auth: true, body: body)
    }

    func chat(_ requestBody: ChatRequest) async throws -> ChatResponse {
        let body = try JSONEncoder().encode(requestBody)
        let data = try await request(path: "/api/chat", method: "POST", auth: true, body: body)
        return try JSONDecoder().decode(ChatResponse.self, from: data)
    }

    func request(path: String, method: String, auth: Bool, body: Data? = nil) async throws -> Data {
        guard let url = URL(string: path, relativeTo: config.baseURL)?.absoluteURL else {
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "content-type")
        if auth { request.setValue(config.password, forHTTPHeaderField: "x-par-password") }
        request.httpBody = body
        let (data, response) = try await session.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            throw URLError(.badServerResponse)
        }
        return data
    }
}
```

- [ ] **Step 6: Build**

Run:

```bash
xcodebuild -project ios_app/Nomi/Nomi.xcodeproj -scheme Nomi -destination 'platform=iOS Simulator,name=iPhone 16 Pro' build
```

Expected: build succeeds.

- [ ] **Step 7: Commit**

```bash
git add ios_app/Nomi
git commit -m "feat: scaffold nomi ios app"
```

## Task 7: Foreground WebSocket And Local Token-Level Live Activity Updates

**Files:**
- Create: `ios_app/Nomi/Nomi/NomiRealtimeClient.swift`
- Create: `ios_app/Nomi/Nomi/NomiLiveActivityController.swift`
- Test: `ios_app/Nomi/NomiTests/NomiRealtimeClientTests.swift`

- [ ] **Step 1: Add realtime event model**

Create `ios_app/Nomi/Nomi/NomiRealtimeClient.swift`:

```swift
import Foundation

enum NomiRealtimeEvent: Equatable {
    case proactiveMessage(id: String, title: String, body: String, source: String)
    case chatDelta(delta: String, elapsedMs: Int)
    case chatDone(answer: String, conversationId: String)
    case error(message: String)
    case ignored
}

struct NomiRealtimeParser {
    static func parse(_ data: Data) throws -> NomiRealtimeEvent {
        let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let type = object?["type"] as? String ?? ""
        switch type {
        case "proactive_message":
            return .proactiveMessage(
                id: object?["suggestion_id"] as? String ?? object?["id"] as? String ?? "",
                title: object?["title"] as? String ?? "",
                body: object?["body"] as? String ?? "",
                source: object?["source"] as? String ?? ""
            )
        case "chat_delta":
            return .chatDelta(delta: object?["delta"] as? String ?? "", elapsedMs: object?["elapsed_ms"] as? Int ?? -1)
        case "chat_done":
            return .chatDone(answer: object?["answer"] as? String ?? "", conversationId: object?["conversation_id"] as? String ?? "")
        case "error":
            return .error(message: object?["message"] as? String ?? "Realtime error")
        default:
            return .ignored
        }
    }
}
```

- [ ] **Step 2: Add tests**

Create `ios_app/Nomi/NomiTests/NomiRealtimeClientTests.swift`:

```swift
import XCTest
@testable import Nomi

final class NomiRealtimeClientTests: XCTestCase {
    func testParseChatDelta() throws {
        let data = #"{"type":"chat_delta","delta":"你","elapsed_ms":120}"#.data(using: .utf8)!
        let event = try NomiRealtimeParser.parse(data)
        XCTAssertEqual(event, .chatDelta(delta: "你", elapsedMs: 120))
    }

    func testParseProactiveMessageUsesSuggestionId() throws {
        let data = #"{"type":"proactive_message","id":"fallback","suggestion_id":"s1","title":"关注一下","body":"客户问报价","source":"whatsapp"}"#.data(using: .utf8)!
        let event = try NomiRealtimeParser.parse(data)
        XCTAssertEqual(event, .proactiveMessage(id: "s1", title: "关注一下", body: "客户问报价", source: "whatsapp"))
    }
}
```

- [ ] **Step 3: Add Live Activity controller**

Create `ios_app/Nomi/Nomi/NomiLiveActivityController.swift`:

```swift
import ActivityKit
import Foundation

@MainActor
final class NomiLiveActivityController: ObservableObject {
    @Published private(set) var activityId: String?
    private var activity: Activity<NomiLiveActivityAttributes>?
    private var partialAnswer = ""
    private var tokenSequence = 0

    func start(deviceId: String) async throws -> String {
        if let activity { return activity.attributes.activityId }
        let id = UUID().uuidString
        let attributes = NomiLiveActivityAttributes(activityId: id, deviceId: deviceId)
        let state = NomiLiveActivityAttributes.ContentState(
            phase: "idle",
            title: "Nomi",
            body: "Ready",
            source: "system",
            suggestionId: "",
            taskId: "",
            conversationId: "",
            unreadCount: 0,
            partialAnswer: "",
            tokenSequence: 0,
            payloadMode: "safe",
            deepLink: "nomi://chat",
            truncated: false,
            privateContext: nil
        )
        let content = ActivityContent(state: state, staleDate: Date().addingTimeInterval(600))
        let newActivity = try Activity.request(attributes: attributes, content: content, pushType: .token)
        activity = newActivity
        activityId = id
        return id
    }

    func updateFromChatDelta(_ delta: String, conversationId: String, includeText: Bool) async {
        guard let activity else { return }
        tokenSequence += 1
        partialAnswer += delta
        let state = NomiLiveActivityAttributes.ContentState(
            phase: "chat_streaming",
            title: "Nomi is replying",
            body: "正在生成回复",
            source: "chat",
            suggestionId: "",
            taskId: "",
            conversationId: conversationId,
            unreadCount: 0,
            partialAnswer: includeText ? String(partialAnswer.suffix(800)) : "",
            tokenSequence: tokenSequence,
            payloadMode: includeText ? "sensitive" : "safe",
            deepLink: "nomi://chat?conversation_id=\(conversationId)",
            truncated: partialAnswer.count > 800,
            privateContext: nil
        )
        await activity.update(ActivityContent(state: state, staleDate: Date().addingTimeInterval(600)))
    }
}
```

- [ ] **Step 4: Register activity push token with backend**

After `start(deviceId:)`, observe:

```swift
Task {
    for await tokenData in newActivity.pushTokenUpdates {
        let token = tokenData.map { String(format: "%02x", $0) }.joined()
        try await apiClient.registerLiveActivity(deviceId: deviceId, activityId: id, updateToken: token)
    }
}
```

Add `registerLiveActivity` to `NomiApiClient`:

```swift
func registerLiveActivity(deviceId: String, activityId: String, updateToken: String) async throws {
    let body = try JSONSerialization.data(withJSONObject: [
        "device_id": deviceId,
        "activity_id": activityId,
        "activity_kind": "nomi_status",
        "update_token": updateToken
    ])
    _ = try await request(path: "/api/ios/live-activities/register", method: "POST", auth: true, body: body)
}
```

- [ ] **Step 5: Send WebSocket chat payload with iOS fields**

When sending chat over `/ws`, include:

```json
{
  "type": "chat_message",
  "message": "帮我回复这条消息",
  "limit": 24,
  "client_type": "ios",
  "conversation_id": "conversation-id",
  "client_request_id": "ios-request-id",
  "ios_live_activity_id": "activity-id",
  "ios_stream_to_live_activity": true
}
```

The iOS app still updates the Activity locally from received `chat_delta` events. The server uses `ios_live_activity_id` only for APNs token-mode updates.

- [ ] **Step 6: Run iOS tests**

```bash
xcodebuild -project ios_app/Nomi/Nomi.xcodeproj -scheme Nomi -destination 'platform=iOS Simulator,name=iPhone 16 Pro' test
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ios_app/Nomi
git commit -m "feat: add ios realtime live activity streaming"
```

## Task 8: Dynamic Island Widget UI And Tap-To-App Deep Links

**Files:**
- Create: `ios_app/Nomi/NomiWidgets/NomiLiveActivityWidget.swift`
- Modify: iOS widget target settings
- Test: `ios_app/Nomi/NomiWidgetsTests/NomiLiveActivityWidgetTests.swift`

- [ ] **Step 1: Implement Live Activity widget**

Create `ios_app/Nomi/NomiWidgets/NomiLiveActivityWidget.swift`:

```swift
import ActivityKit
import SwiftUI
import WidgetKit

struct NomiLiveActivityWidget: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: NomiLiveActivityAttributes.self) { context in
            LockScreenLiveActivityView(state: context.state)
                .activityBackgroundTint(Color.black)
                .activitySystemActionForegroundColor(Color.white)
                .widgetURL(URL(string: context.state.deepLink))
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Nomi").font(.caption.weight(.semibold))
                        Text(context.state.source).font(.caption2).foregroundStyle(.secondary)
                    }
                }
                DynamicIslandExpandedRegion(.trailing) {
                    if context.state.unreadCount > 0 {
                        Text("\(context.state.unreadCount)")
                            .font(.caption.weight(.bold))
                            .padding(6)
                    }
                }
                DynamicIslandExpandedRegion(.bottom) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(context.state.title).font(.caption.weight(.semibold)).lineLimit(1)
                        Text(displayBody(context.state)).font(.caption2).lineLimit(2)
                    }
                    .widgetURL(URL(string: context.state.deepLink))
                }
            } compactLeading: {
                Text("N")
                    .font(.caption.weight(.bold))
                    .widgetURL(URL(string: context.state.deepLink))
            } compactTrailing: {
                if context.state.phase == "chat_streaming" {
                    Text("\(context.state.tokenSequence)")
                        .font(.caption2)
                        .widgetURL(URL(string: context.state.deepLink))
                } else if context.state.unreadCount > 0 {
                    Text("\(context.state.unreadCount)")
                        .font(.caption2)
                        .widgetURL(URL(string: context.state.deepLink))
                } else {
                    Text("•")
                        .font(.caption2)
                        .widgetURL(URL(string: context.state.deepLink))
                }
            } minimal: {
                Text("N")
                    .font(.caption2.weight(.bold))
                    .widgetURL(URL(string: context.state.deepLink))
            }
        }
    }
}

private func displayBody(_ state: NomiLiveActivityAttributes.ContentState) -> String {
    if state.phase == "chat_streaming", !state.partialAnswer.isEmpty {
        return state.partialAnswer
    }
    if let raw = state.privateContext?.rawSnippet, !raw.isEmpty {
        return raw
    }
    return state.body
}

struct LockScreenLiveActivityView: View {
    let state: NomiLiveActivityAttributes.ContentState

    var body: some View {
        HStack(spacing: 12) {
            Text("N")
                .font(.headline.weight(.bold))
                .frame(width: 32, height: 32)
                .background(.white.opacity(0.16))
                .clipShape(Circle())
            VStack(alignment: .leading, spacing: 3) {
                Text(state.title).font(.subheadline.weight(.semibold)).lineLimit(1)
                Text(displayBody(state)).font(.caption).lineLimit(2)
            }
            Spacer()
        }
        .padding(12)
    }
}
```

- [ ] **Step 2: Wire widget bundle**

Ensure the widget extension includes:

```swift
@main
struct NomiWidgetsBundle: WidgetBundle {
    var body: some Widget {
        NomiLiveActivityWidget()
    }
}
```

- [ ] **Step 3: Add deep link router**

Create `ios_app/Nomi/Nomi/DeepLinkRouter.swift`:

```swift
import Foundation

enum NomiRoute: Equatable {
    case chat(conversationId: String?)
    case suggestion(id: String)
    case task(id: String)
    case liveActivitySettings
}

struct DeepLinkRouter {
    static func route(from url: URL) -> NomiRoute? {
        guard url.scheme == "nomi" else { return nil }
        let host = url.host ?? ""
        let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        let query = Dictionary(uniqueKeysWithValues: (components?.queryItems ?? []).map { ($0.name, $0.value ?? "") })
        switch host {
        case "chat":
            return .chat(conversationId: query["conversation_id"])
        case "suggestion":
            guard let id = query["id"], !id.isEmpty else { return nil }
            return .suggestion(id: id)
        case "task":
            guard let id = query["id"], !id.isEmpty else { return nil }
            return .task(id: id)
        case "settings":
            if url.path == "/live-activity" { return .liveActivitySettings }
            return nil
        default:
            return nil
        }
    }
}
```

In `NomiApp.swift`:

```swift
.onOpenURL { url in
    appState.route = DeepLinkRouter.route(from: url)
}
```

- [ ] **Step 4: Run on an iPhone simulator/device with Dynamic Island**

Run:

```bash
xcodebuild -project ios_app/Nomi/Nomi.xcodeproj -scheme Nomi -destination 'platform=iOS Simulator,name=iPhone 16 Pro' build
```

Expected: build succeeds. Then launch, start Live Activity, tap compact and expanded island. Expected: app opens to the matching route.

- [ ] **Step 5: Commit**

```bash
git add ios_app/Nomi
git commit -m "feat: add dynamic island live activity ui"
```

## Task 9: App Intents For Quick Actions

**Files:**
- Create: `ios_app/Nomi/NomiIntents/NomiSuggestionIntents.swift`
- Modify: `ios_app/Nomi/NomiWidgets/NomiLiveActivityWidget.swift`

- [ ] **Step 1: Add intents**

Create `ios_app/Nomi/NomiIntents/NomiSuggestionIntents.swift`:

```swift
import AppIntents
import Foundation

struct MarkSuggestionDoneIntent: AppIntent {
    static var title: LocalizedStringResource = "Mark Nomi suggestion done"

    @Parameter(title: "Suggestion ID")
    var suggestionId: String

    init() {
        self.suggestionId = ""
    }

    init(suggestionId: String) {
        self.suggestionId = suggestionId
    }

    func perform() async throws -> some IntentResult {
        let config = try NomiKeychain.loadServerConfig()
        let client = NomiApiClient(config: config)
        try await client.updateSuggestion(id: suggestionId, status: "done")
        return .result()
    }
}

struct DismissSuggestionIntent: AppIntent {
    static var title: LocalizedStringResource = "Dismiss Nomi suggestion"

    @Parameter(title: "Suggestion ID")
    var suggestionId: String

    init() {
        self.suggestionId = ""
    }

    init(suggestionId: String) {
        self.suggestionId = suggestionId
    }

    func perform() async throws -> some IntentResult {
        let config = try NomiKeychain.loadServerConfig()
        let client = NomiApiClient(config: config)
        try await client.updateSuggestion(id: suggestionId, status: "dismissed")
        return .result()
    }
}
```

- [ ] **Step 2: Add buttons to expanded Dynamic Island only**

In `DynamicIslandExpandedRegion(.bottom)`, below text:

```swift
if !context.state.suggestionId.isEmpty {
    HStack(spacing: 8) {
        Button(intent: MarkSuggestionDoneIntent(suggestionId: context.state.suggestionId)) {
            Text("Done")
        }
        Button(intent: DismissSuggestionIntent(suggestionId: context.state.suggestionId)) {
            Text("Dismiss")
        }
    }
    .font(.caption2)
}
```

- [ ] **Step 3: Build and manually verify**

Run:

```bash
xcodebuild -project ios_app/Nomi/Nomi.xcodeproj -scheme Nomi -destination 'platform=iOS Simulator,name=iPhone 16 Pro' build
```

Expected: build succeeds. Long-press Dynamic Island, tap Done/Dismiss. Expected: backend `PATCH /api/suggestions/{id}` is called and suggestion status changes.

- [ ] **Step 4: Commit**

```bash
git add ios_app/Nomi
git commit -m "feat: add dynamic island suggestion intents"
```

## Task 10: Settings UI For Required Risk Switches

**Files:**
- Create: `ios_app/Nomi/Nomi/NomiIslandSettings.swift`
- Modify: `ios_app/Nomi/Nomi/Views/SettingsView.swift`
- Modify: `ios_app/Nomi/Nomi/NomiApiClient.swift`

- [ ] **Step 1: Add settings model**

Create `ios_app/Nomi/Nomi/NomiIslandSettings.swift`:

```swift
import Foundation

struct NomiIslandSettings: Codable, Equatable {
    var liveActivityEnabled: Bool = true
    var notificationFallbackEnabled: Bool = true
    var deepLinksEnabled: Bool = true
    var tokenLevelChatStreamingEnabled: Bool = false
    var tokenLevelChatDelivery: TokenLevelChatDelivery = .localWhenForeground
    var sensitiveApnsPayloadEnabled: Bool = false
    var includePrivateMessageBody: Bool = false
    var includeContactNames: Bool = false
    var includeRawPrivateContext: Bool = false
    var maxSensitivePayloadChars: Int = 2400

    enum CodingKeys: String, CodingKey {
        case liveActivityEnabled = "live_activity_enabled"
        case notificationFallbackEnabled = "notification_fallback_enabled"
        case deepLinksEnabled = "deep_links_enabled"
        case tokenLevelChatStreamingEnabled = "token_level_chat_streaming_enabled"
        case tokenLevelChatDelivery = "token_level_chat_delivery"
        case sensitiveApnsPayloadEnabled = "sensitive_apns_payload_enabled"
        case includePrivateMessageBody = "include_private_message_body"
        case includeContactNames = "include_contact_names"
        case includeRawPrivateContext = "include_raw_private_context"
        case maxSensitivePayloadChars = "max_sensitive_payload_chars"
    }
}

enum TokenLevelChatDelivery: String, Codable, CaseIterable, Identifiable {
    case localWhenForeground = "local_when_foreground"
    case apnsBestEffort = "apns_best_effort"
    case localAndApnsBestEffort = "local_and_apns_best_effort"

    var id: String { rawValue }
}

extension NomiIslandSettings {
    func asDictionary() throws -> [String: Any] {
        let data = try JSONEncoder().encode(self)
        return try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
    }
}
```

- [ ] **Step 2: Add API client sync**

Add to `NomiApiClient`:

```swift
func registerDevice(deviceId: String, displayName: String, settings: NomiIslandSettings) async throws {
    let payload: [String: Any] = [
        "device_id": deviceId,
        "display_name": displayName,
        "apns_environment": "sandbox",
        "settings": try settings.asDictionary()
    ]
    let body = try JSONSerialization.data(withJSONObject: payload)
    _ = try await request(path: "/api/ios/devices/register", method: "POST", auth: true, body: body)
}

func updateDeviceSettings(deviceId: String, settings: NomiIslandSettings) async throws {
    let body = try JSONSerialization.data(withJSONObject: ["settings": try settings.asDictionary()])
    _ = try await request(path: "/api/ios/devices/\(deviceId)/settings", method: "PATCH", auth: true, body: body)
}
```

Use `NomiIslandSettings.asDictionary()` from Step 1; do not use a generic `[String: Any]` JSON encoder because Swift cannot encode arbitrary dictionaries directly.

- [ ] **Step 3: Add explicit warning UI**

In `SettingsView.swift`, include these toggles and warning copy:

```swift
Toggle("Show Nomi in Dynamic Island", isOn: $settings.liveActivityEnabled)
Toggle("Stream every reply token to Dynamic Island", isOn: $settings.tokenLevelChatStreamingEnabled)

Picker("Token delivery", selection: $settings.tokenLevelChatDelivery) {
    Text("Foreground only").tag(TokenLevelChatDelivery.localWhenForeground)
    Text("APNs best effort").tag(TokenLevelChatDelivery.apnsBestEffort)
    Text("Foreground + APNs").tag(TokenLevelChatDelivery.localAndApnsBestEffort)
}

Toggle("Allow private content in APNs payloads", isOn: $settings.sensitiveApnsPayloadEnabled)
if settings.sensitiveApnsPayloadEnabled {
    Text("Private message text may pass through Apple Push Notification service. Enable only if you accept that tradeoff.")
        .font(.footnote)
        .foregroundStyle(.secondary)
    Toggle("Include Gmail/WhatsApp message body", isOn: $settings.includePrivateMessageBody)
    Toggle("Include contact names", isOn: $settings.includeContactNames)
    Toggle("Include raw private context snippet", isOn: $settings.includeRawPrivateContext)
}
Toggle("Open app when tapping Dynamic Island", isOn: $settings.deepLinksEnabled)
```

- [ ] **Step 4: Persist settings locally and sync to backend**

Persist in `UserDefaults` or App Group storage for widget visibility. Store server password only in Keychain.

Expected sync behavior:

- On Save: call `PATCH /api/ios/devices/{device_id}/settings`.
- On app launch: register device with current settings.
- On Live Activity start: upload activity update token.

- [ ] **Step 5: Commit**

```bash
git add ios_app/Nomi
git commit -m "feat: add ios dynamic island settings"
```

## Task 11: End-To-End Verification

**Files:**
- Create: `docs/superpowers/reports/YYYY-MM-DD-ios-dynamic-island-regression.md`

- [ ] **Step 1: Backend tests**

Run:

```bash
pytest runtime_api/tests/test_ios_live_activity.py runtime_api/tests/test_realtime_ws.py runtime_api/tests/test_vector_and_suggestions.py -q
```

Expected: PASS.

- [ ] **Step 2: iOS build/tests**

Run:

```bash
xcodebuild -project ios_app/Nomi/Nomi.xcodeproj -scheme Nomi -destination 'platform=iOS Simulator,name=iPhone 16 Pro' test
```

Expected: PASS.

- [ ] **Step 3: Safe-mode manual regression**

Setup:

```bash
docker compose up --build
```

Actions:

- Open iOS app.
- Configure private cloud base URL and password.
- Enable "Show Nomi in Dynamic Island".
- Keep sensitive APNs payload off.
- Start Live Activity.
- Create a test event:

```bash
curl -X POST http://localhost:8080/event \
  -H 'content-type: application/json' \
  -d '{"source":"whatsapp","event_type":"message","raw_data":{"sender":"Alice","message":"报价今天还能确认吗？"}}'
```

Expected:

- Dynamic Island shows generic Nomi suggestion.
- No raw message body or contact appears in APNs audit payload.
- Tapping Dynamic Island opens `nomi://suggestion?id=...` and hydrates from `/api/suggestions`.

- [ ] **Step 4: Sensitive-mode manual regression**

Actions:

- Enable "Allow private content in APNs payloads".
- Enable "Include Gmail/WhatsApp message body".
- Enable "Include contact names".
- Enable "Include raw private context snippet".
- Repeat the WhatsApp event.

Expected:

- Dynamic Island may show contact/body.
- `ios_live_activity_events.payload` contains `payloadMode: sensitive`.
- Payload is under APNs size budget and marks `truncated: true` if trimmed.
- Tapping Dynamic Island opens the app to the suggestion.

- [ ] **Step 5: Token-level chat regression**

Actions:

- Enable "Stream every reply token to Dynamic Island".
- Select "Foreground + APNs".
- Send chat over the iOS app WebSocket.

Expected:

- Foreground iOS app updates Live Activity locally for each `chat_delta`.
- Backend records one attempted APNs event per model delta when `ios_stream_to_live_activity=true`.
- If APNs throttles, audit rows show failed or delayed delivery, but local foreground updates still work.

- [ ] **Step 6: Write report**

Create `docs/superpowers/reports/2026-06-18-ios-dynamic-island-regression.md`:

```markdown
# iOS Dynamic Island Regression

Date: 2026-06-18

## Backend

- pytest command:
- result:

## iOS

- xcodebuild command:
- result:

## Safe Mode

- result:
- APNs payload sample:

## Sensitive Mode

- result:
- APNs payload sample:

## Token-Level Chat

- result:
- APNs audit count:
- known APNs throttling observations:

## Deep Links

- chat:
- suggestion:
- task:
- settings:
```

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/reports/2026-06-18-ios-dynamic-island-regression.md
git commit -m "test: verify ios dynamic island integration"
```

## Known Risks And Guardrails

- APNs delivery is not a private-cloud-only path. Sensitive mode must remain explicit and warning-gated.
- APNs payloads have a hard size budget. Full raw context cannot be guaranteed; implement deterministic truncation.
- Token-level APNs updates may be throttled. The app must still update the Activity locally from foreground `/ws` deltas.
- Live Activities are time-limited and user-dismissable. The app must treat the Dynamic Island as an ambient surface, not the only interaction path.
- Live Activity push tokens can change. The iOS app must observe `pushTokenUpdates` and re-register.
- Keychain access may be unavailable before first unlock after reboot. App Intents should fail gracefully and tell the user to open Nomi.
- If `ENABLE_IOS_LIVE_ACTIVITY_BRIDGE=false`, iOS foreground local Live Activity updates still work, but background APNs updates do not.

## Self-Review

- Requirement: token-level `chat_delta` to Dynamic Island. Covered by Task 5 and Task 7.
- Requirement: sensitive Gmail/WhatsApp/private context in APNs payload with switch. Covered by Task 2, Task 4, and Task 10.
- Requirement: tap Dynamic Island to app. Covered by Task 8.
- Requirement: reuse backend. Covered by Existing Backend Reuse Map, Task 4 Redis bridge, and Task 5 chat hook.
- Requirement: local document. This file is the implementation plan.
- Placeholder scan: no `TBD`, `TODO`, or intentionally vague implementation steps remain.
