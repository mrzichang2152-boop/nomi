# iOS Android Function Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the iOS Nomi workbench so it matches Android user-facing capabilities while keeping the UI simple.

**Architecture:** Implement feature slices in TDD order: protocol/API contracts first, stores next, then SwiftUI workbench screens, then simulator regression. Keep backend reuse through `NomiApiClient` and `/ws` instead of adding parallel iOS-only APIs.

**Tech Stack:** Swift 5, SwiftUI, XCTest, ActivityKit, UserNotifications, WebKit, AVFoundation.

---

### Task 1: API, Routes, And Gap Tracker

**Files:**
- Modify: `ios_app/Nomi/Nomi/NomiApiClient.swift`
- Modify: `ios_app/Nomi/Nomi/DeepLinkRouter.swift`
- Modify: `ios_app/Nomi/Nomi/NomiRealtimeClient.swift`
- Modify: `ios_app/Nomi/NomiTests/NomiApiClientTests.swift`
- Modify: `ios_app/Nomi/NomiTests/DeepLinkRouterTests.swift`
- Modify: `ios_app/Nomi/NomiTests/NomiRealtimeClientTests.swift`
- Create: `docs/superpowers/reports/2026-06-20-ios-android-function-parity-gap-tracker.md`

- [x] Write failing tests for backend path/body contracts, deep links, and realtime task parsing.
- [x] Run iOS tests and verify the new tests fail for missing behavior.
- [x] Implement minimal models/routes/parsers/API methods.
- [x] Run iOS tests and verify all pass.

### Task 2: Stores And Workbench Modes

**Files:**
- Modify: `ios_app/Nomi/Nomi/AppState.swift`
- Modify: `ios_app/Nomi/Nomi/NomiApp.swift`
- Modify: `ios_app/Nomi/Nomi/Views/SuggestionListView.swift`
- Create or modify Swift files for tasks/accounts/career/workbench state.
- Modify existing XCTest files or add new XCTest files if project wiring is updated.

- [x] Write failing tests for mode routing, suggestion dedupe/poll fallback decisions, task event dedupe, account channel routing, career action payloads, and voice confidence decisions.
- [x] Run iOS tests and verify failures.
- [x] Implement stores and state transitions.
- [x] Run iOS tests and verify all pass.

### Task 3: SwiftUI Workbench

**Files:**
- Modify: `ios_app/Nomi/Nomi/NomiApp.swift`
- Modify: `ios_app/Nomi/Nomi/Views/ChatView.swift`
- Modify: `ios_app/Nomi/Nomi/Views/SuggestionListView.swift`
- Modify: `ios_app/Nomi/Nomi/Views/SettingsView.swift`
- Create or modify SwiftUI views for Tasks, Accounts, Career, Web Workbench, and diagnostics.

- [x] Add tests where view logic is extractable.
- [x] Implement `NomiWorkbenchView` with Chat/Suggestions/Tasks/Accounts/Career/Settings modes.
- [x] Add real loading/error/empty/success states for feature screens.
- [x] Build the app and fix compile issues.

### Task 4: Device Notifications, Web Workbench, And Voice

**Files:**
- Modify: `ios_app/Nomi/Nomi/NomiApp.swift`
- Modify: `ios_app/Nomi/Nomi/AppState.swift`
- Modify: `ios_app/Nomi/Nomi/Views/ChatView.swift`
- Create or modify notification, WebKit, and voice controller code.

- [x] Add tests for token/status payloads, noVNC URL building, localStorage injection script, and voice payload/decision logic.
- [x] Implement APNs registration status plumbing, Web workbench, remote browser URL, and voice controller scaffolding.
- [x] Record simulator-only or real-device-only gaps in the gap tracker.
- [x] Run iOS tests.

### Task 5: Regression

**Files:**
- Create or modify: `docs/superpowers/reports/2026-06-20-ios-android-function-parity-regression-run.md`

- [x] Run full iOS unit tests.
- [x] Build and launch the app on iPhone 17 Pro simulator.
- [x] Capture UI evidence for workbench modes.
- [x] Record exact gaps and close conditions.
