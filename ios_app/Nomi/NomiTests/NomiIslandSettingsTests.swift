import XCTest
@testable import Nomi

final class NomiIslandSettingsTests: XCTestCase {
    func testEncodesSnakeCaseSettingsForBackend() throws {
        var settings = NomiIslandSettings()
        settings.tokenLevelChatStreamingEnabled = true
        settings.tokenLevelChatDelivery = .localAndApnsBestEffort
        settings.sensitiveApnsPayloadEnabled = true

        let dictionary = try settings.asDictionary()

        XCTAssertEqual(dictionary["token_level_chat_streaming_enabled"] as? Bool, true)
        XCTAssertEqual(dictionary["token_level_chat_delivery"] as? String, "local_and_apns_best_effort")
        XCTAssertEqual(dictionary["sensitive_apns_payload_enabled"] as? Bool, true)
        XCTAssertNil(dictionary["tokenLevelChatStreamingEnabled"])
    }

    func testSettingsStorePersistsUserChoices() throws {
        let suiteName = "nomi-settings-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }
        var settings = NomiIslandSettings()
        settings.liveActivityEnabled = false
        settings.deepLinksEnabled = false
        settings.tokenLevelChatStreamingEnabled = true
        settings.tokenLevelChatDelivery = .localAndApnsBestEffort
        settings.sensitiveApnsPayloadEnabled = true

        try NomiIslandSettingsStore(defaults: defaults).save(settings)
        let restored = NomiIslandSettingsStore(defaults: defaults).load()

        XCTAssertEqual(restored, settings)
    }

    func testKeychainErrorsExposeReadableDescriptions() {
        XCTAssertEqual(
            NomiKeychain.KeychainError.notFound.errorDescription,
            "Server config was not found in Keychain."
        )
        XCTAssertEqual(
            NomiKeychain.KeychainError.unhandled(-34018).errorDescription,
            "Keychain operation failed with OSStatus -34018."
        )
    }
}

final class NomiWorkbenchChromeTests: XCTestCase {
    func testDefaultsToChatWithSecondaryModesCollapsed() {
        let chrome = NomiWorkbenchChrome()

        XCTAssertEqual(chrome.selectedMode, .chat)
        XCTAssertFalse(chrome.isModeMenuExpanded)
        XCTAssertEqual(chrome.visibleModes, [.chat])
    }

    func testExpandedMenuShowsAllWorkbenchModes() {
        var chrome = NomiWorkbenchChrome()

        chrome.toggleModeMenu()

        XCTAssertTrue(chrome.isModeMenuExpanded)
        XCTAssertEqual(chrome.visibleModes, NomiWorkbenchMode.allCases)
    }

    func testSelectingASecondaryModeCollapsesMenuAroundThatMode() {
        var chrome = NomiWorkbenchChrome()
        chrome.toggleModeMenu()

        chrome.select(.tasks)

        XCTAssertEqual(chrome.selectedMode, .tasks)
        XCTAssertFalse(chrome.isModeMenuExpanded)
        XCTAssertEqual(chrome.visibleModes, [.tasks])
    }
}

final class NomiWorkbenchPresentationTests: XCTestCase {
    func testCompactConnectionLabelsHideVerboseServerStatus() {
        XCTAssertEqual(NomiWorkbenchPresentation.connectionLabel(for: "Server connected"), "Connected")
        XCTAssertEqual(NomiWorkbenchPresentation.connectionLabel(for: "Server loaded, not tested"), "Not tested")
        XCTAssertEqual(NomiWorkbenchPresentation.connectionLabel(for: "Could not connect to server: timeout"), "Offline")
        XCTAssertEqual(NomiWorkbenchPresentation.connectionLabel(for: "Server not configured"), "Setup")
    }

    func testChatComposerFocusPolicyFocusesOnEntryAndAfterSend() {
        XCTAssertTrue(NomiChatComposerFocusPolicy.shouldFocusComposerOnAppear)
        XCTAssertTrue(NomiChatComposerFocusPolicy.shouldRestoreFocusAfterSend)
    }

    func testWebWorkspaceChromeKeepsRemoteTabsBelowLocalControls() {
        XCTAssertGreaterThanOrEqual(NomiWebWorkspaceChrome.topControlHeight, 48)
        XCTAssertEqual(
            NomiWebWorkspaceChrome.remoteSources.map(\.id),
            ["whatsapp", "linkedin", "telegram", "search", "shopping"]
        )
        XCTAssertEqual(NomiWebWorkspaceChrome.title(for: "linkedin"), "LinkedIn")
        XCTAssertEqual(NomiWebWorkspaceChrome.title(for: "whatsapp"), "WhatsApp")
    }
}

final class NomiInfoPlistTests: XCTestCase {
    func testPrivateCloudHttpServerIsAllowedByAppTransportSecurity() throws {
        let appTransportSecurity = try XCTUnwrap(Bundle.main.infoDictionary?["NSAppTransportSecurity"] as? [String: Any])
        let exceptionDomains = try XCTUnwrap(appTransportSecurity["NSExceptionDomains"] as? [String: Any])
        let privateCloud = try XCTUnwrap(exceptionDomains["206.119.171.141"] as? [String: Any])

        XCTAssertEqual(privateCloud["NSExceptionAllowsInsecureHTTPLoads"] as? Bool, true)
        XCTAssertEqual(privateCloud["NSIncludesSubdomains"] as? Bool, false)
    }
}

@MainActor
final class AppStateTests: XCTestCase {
    func testLoadsPersistedIslandSettingsOnLaunch() throws {
        let suiteName = "nomi-app-state-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }
        var persisted = NomiIslandSettings()
        persisted.deepLinksEnabled = false
        persisted.tokenLevelChatStreamingEnabled = true
        try NomiIslandSettingsStore(defaults: defaults).save(persisted)

        let state = AppState(
            defaults: defaults,
            loadServerConfig: { throw NomiKeychain.KeychainError.notFound },
            saveServerConfig: { _ in }
        )

        XCTAssertEqual(state.islandSettings, persisted)
    }

    func testDeepLinkToSettingsSelectsSettingsTab() {
        let suiteName = "nomi-route-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let state = AppState(
            defaults: defaults,
            loadServerConfig: { throw NomiKeychain.KeychainError.notFound },
            saveServerConfig: { _ in }
        )

        state.handle(url: URL(string: "nomi://settings/live-activity")!)

        XCTAssertEqual(state.route, .liveActivitySettings)
        XCTAssertEqual(state.selectedMode, .settings)
    }

    func testDeepLinksSelectWorkbenchModes() {
        let suiteName = "nomi-mode-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let state = AppState(
            defaults: defaults,
            loadServerConfig: { throw NomiKeychain.KeychainError.notFound },
            saveServerConfig: { _ in }
        )

        state.handle(url: URL(string: "nomi://task?id=t1")!)
        XCTAssertEqual(state.selectedMode, .tasks)

        state.handle(url: URL(string: "nomi://accounts")!)
        XCTAssertEqual(state.selectedMode, .accounts)

        state.handle(url: URL(string: "nomi://career/opportunity?id=o1")!)
        XCTAssertEqual(state.selectedMode, .career)

        state.handle(url: URL(string: "nomi://voice")!)
        XCTAssertEqual(state.selectedMode, .chat)
    }

    func testRealtimeEventsUpdateSharedStores() {
        let suiteName = "nomi-realtime-store-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let state = AppState(
            defaults: defaults,
            loadServerConfig: { throw NomiKeychain.KeychainError.notFound },
            saveServerConfig: { _ in }
        )

        state.handleRealtimeEvent(.proactiveMessage(id: "s1", title: "Review", body: "Body", source: "gmail"))
        state.handleRealtimeEvent(.agentTaskDelivery(eventId: "e1", taskId: "t1", body: "Done", rawJSON: "{}"))

        XCTAssertEqual(state.suggestionStore.suggestions.map(\.id), ["s1"])
        XCTAssertEqual(state.taskStore.cards.map(\.taskId), ["t1"])
    }

    func testSavesServerConfigThroughInjectedSecureStore() throws {
        let suiteName = "nomi-server-config-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }
        var savedConfig: ServerConfig?
        let state = AppState(
            defaults: defaults,
            loadServerConfig: { throw NomiKeychain.KeychainError.notFound },
            saveServerConfig: { savedConfig = $0 }
        )

        try state.saveServerConfig(baseURL: "example.com/", password: " secret ")

        XCTAssertEqual(state.serverConfig?.baseURL.absoluteString, "http://example.com")
        XCTAssertEqual(state.serverConfig?.password, "secret")
        XCTAssertEqual(savedConfig, state.serverConfig)
        XCTAssertEqual(state.serverConfigStatus, "Server saved")
    }

    func testLoadedServerConfigIsMarkedUntestedUntilHealthCheckRuns() throws {
        let suiteName = "nomi-loaded-server-config-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let config = ServerConfig(baseURL: URL(string: "http://localhost")!, password: "par-dev")

        let state = AppState(
            defaults: defaults,
            loadServerConfig: { config },
            saveServerConfig: { _ in }
        )

        XCTAssertEqual(state.serverConfig, config)
        XCTAssertEqual(state.serverConfigStatus, "Server loaded, not tested")
    }
}

final class NomiParityStoreTests: XCTestCase {
    func testAccountChannelRouteMatchesAndroidSources() {
        XCTAssertEqual(NomiAccountChannelRoute.forSource("gmail"), .composio(slug: "gmail"))
        XCTAssertEqual(NomiAccountChannelRoute.forSource("googlecalendar"), .composio(slug: "googlecalendar"))
        XCTAssertEqual(NomiAccountChannelRoute.forSource("github"), .composio(slug: "github"))
        XCTAssertEqual(NomiAccountChannelRoute.forSource("linear"), .composio(slug: "linear"))
        XCTAssertEqual(NomiAccountChannelRoute.forSource("jira"), .composio(slug: "jira"))
        XCTAssertEqual(NomiAccountChannelRoute.forSource("todoist"), .composio(slug: "todoist"))
        XCTAssertEqual(NomiAccountChannelRoute.forSource("google_maps"), .composio(slug: "google_maps"))
        XCTAssertEqual(NomiAccountChannelRoute.forSource("whatsapp"), .remoteBrowser(source: "whatsapp"))
        XCTAssertEqual(NomiAccountChannelRoute.forSource("linkedin"), .remoteBrowser(source: "linkedin"))
        XCTAssertEqual(NomiAccountChannelRoute.forSource("shopping"), .remoteBrowser(source: "shopping"))
        XCTAssertEqual(NomiAccountChannelRoute.forSource("bookmark"), .localOnly)
    }

    func testSuggestionStoreDedupesRealtimeAndPollingSuggestions() {
        var store = NomiSuggestionStore()
        let suggestion = AssistantSuggestion(id: "s1", title: "Review", body: "Look at Gmail", priority: 0.9)

        store.ingestRealtime(suggestion)
        store.ingestPolled([suggestion])

        XCTAssertEqual(store.suggestions, [suggestion])
        XCTAssertEqual(store.unreadCount, 1)
    }

    func testSuggestionStoreStartsPollingWhenRealtimeDisconnects() {
        var store = NomiSuggestionStore()

        store.setRealtimeConnected(false)

        XCTAssertTrue(store.shouldPollSuggestions)
        XCTAssertEqual(store.pollIntervalSeconds, 60)
    }

    func testTaskStoreCreatesDeliveryAndFallbackCardsWithDedupe() {
        var store = NomiTaskStore()
        let delivery = NomiRealtimeEvent.agentTaskDelivery(eventId: "e1", taskId: "t1", body: "Draft ready", rawJSON: "{}")
        let fallback = NomiRealtimeEvent.agentTaskFallback(eventId: "e2", taskId: "t2", title: "Need approval", body: "Confirm send", rawJSON: "{}")

        store.ingest(delivery)
        store.ingest(delivery)
        store.ingest(fallback)

        XCTAssertEqual(store.cards.map(\.id), ["e2", "e1"])
        XCTAssertEqual(store.cards.first?.title, "Need approval")
        XCTAssertEqual(store.cards.last?.phase, .delivery)
        XCTAssertEqual(store.unreadCount, 2)
    }

    func testVoiceConfidenceDecisionMatchesAndroidThresholds() {
        XCTAssertEqual(NomiVoiceConfidenceDecision.decide(confidence: 0.80), .autoSend)
        XCTAssertEqual(NomiVoiceConfidenceDecision.decide(confidence: 0.70), .confirmBeforeSend)
        XCTAssertEqual(NomiVoiceConfidenceDecision.decide(confidence: 0.40), .reject)
    }

    func testVoicePayloadsUseAndroidCompatibleFields() throws {
        let start = try NomiVoicePayloadBuilder.startPayload(sessionId: "session-1", conversationId: "conversation-1")
        let startJSON = try JSONSerialization.jsonObject(with: start) as? [String: Any]
        let audio = startJSON?["audio"] as? [String: Any]

        XCTAssertEqual(startJSON?["type"] as? String, "voice_start")
        XCTAssertEqual(startJSON?["client_type"] as? String, "ios_workbench_voice")
        XCTAssertEqual(audio?["codec"] as? String, "pcm_s16le")
        XCTAssertEqual(audio?["sample_rate_hz"] as? Int, 16_000)
        XCTAssertEqual(audio?["channels"] as? Int, 1)
        XCTAssertEqual(audio?["frame_ms"] as? Int, 200)

        let chunk = try NomiVoicePayloadBuilder.audioChunkPayload(
            sessionId: "session-1",
            seq: 2,
            capturedAtMs: 123,
            audioBase64: "AAAA"
        )
        let chunkJSON = try JSONSerialization.jsonObject(with: chunk) as? [String: Any]
        XCTAssertEqual(chunkJSON?["type"] as? String, "audio_chunk")
        XCTAssertEqual(chunkJSON?["seq"] as? Int, 2)
        XCTAssertEqual(chunkJSON?["audio_base64"] as? String, "AAAA")
    }

    func testWebWorkspaceInjectionScriptsUseExpectedStorageKeys() {
        let passwordScript = NomiWebWorkspaceBridge.passwordInjectionScript(password: "p'ass")
        let eventScript = NomiWebWorkspaceBridge.pendingAgentEventScript(rawJSON: #"{"event_id":"e1"}"#)

        XCTAssertTrue(passwordScript.contains("localStorage.setItem(\"par-password\""))
        XCTAssertTrue(passwordScript.contains("p'ass"))
        XCTAssertTrue(eventScript.contains("localStorage.setItem(\"nomi-pending-agent-event\""))
        XCTAssertTrue(eventScript.contains("nomi-pending-agent-event"))
    }

    func testNotificationDeviceTokenStatusText() {
        var status = NomiNotificationRegistrationStatus()
        XCTAssertEqual(status.fallbackAvailabilityText, "APNs fallback unavailable: notification permission not requested")

        status.permission = .authorized
        status.apnsDeviceToken = "deadbeef"

        XCTAssertEqual(status.fallbackAvailabilityText, "APNs fallback ready")
    }
}
