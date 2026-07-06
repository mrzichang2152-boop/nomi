import Foundation

enum NomiWorkbenchMode: String, CaseIterable, Hashable, Identifiable {
    case chat
    case suggestions
    case tasks
    case accounts
    case career
    case settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .chat:
            return "Chat"
        case .suggestions:
            return "Suggestions"
        case .tasks:
            return "Tasks"
        case .accounts:
            return "Accounts"
        case .career:
            return "Career"
        case .settings:
            return "Settings"
        }
    }

    var systemImage: String {
        switch self {
        case .chat:
            return "bubble.left.and.bubble.right"
        case .suggestions:
            return "lightbulb"
        case .tasks:
            return "checklist"
        case .accounts:
            return "person.crop.circle.badge.checkmark"
        case .career:
            return "briefcase"
        case .settings:
            return "gearshape"
        }
    }
}

struct NomiWorkbenchChrome: Equatable {
    private(set) var selectedMode: NomiWorkbenchMode = .chat
    private(set) var isModeMenuExpanded = false

    var visibleModes: [NomiWorkbenchMode] {
        isModeMenuExpanded ? NomiWorkbenchMode.allCases : [selectedMode]
    }

    mutating func toggleModeMenu() {
        isModeMenuExpanded.toggle()
    }

    mutating func select(_ mode: NomiWorkbenchMode) {
        selectedMode = mode
        isModeMenuExpanded = false
    }

    mutating func syncSelection(_ mode: NomiWorkbenchMode) {
        selectedMode = mode
    }
}

enum NomiWorkbenchPresentation {
    static func connectionLabel(for serverStatus: String) -> String {
        let normalized = serverStatus.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if normalized.contains("connected") {
            return "Connected"
        }
        if normalized.contains("not configured") {
            return "Setup"
        }
        if normalized.contains("not tested") {
            return "Not tested"
        }
        if normalized.contains("testing") {
            return "Testing"
        }
        if normalized.contains("could not connect") || normalized.contains("failed") || normalized.contains("unavailable") {
            return "Offline"
        }
        if normalized.isEmpty {
            return "Setup"
        }
        return "Check"
    }

    static func connectionTint(for serverStatus: String) -> String {
        switch connectionLabel(for: serverStatus) {
        case "Connected":
            return "green"
        case "Testing", "Not tested":
            return "orange"
        default:
            return "secondary"
        }
    }
}

struct NomiRemoteBrowserSource: Identifiable, Equatable {
    let id: String
    let title: String
}

enum NomiWebWorkspaceChrome {
    static let topControlHeight = 52
    static let remoteSources: [NomiRemoteBrowserSource] = [
        NomiRemoteBrowserSource(id: "whatsapp", title: "WhatsApp"),
        NomiRemoteBrowserSource(id: "linkedin", title: "LinkedIn"),
        NomiRemoteBrowserSource(id: "telegram", title: "Telegram"),
        NomiRemoteBrowserSource(id: "search", title: "Search"),
        NomiRemoteBrowserSource(id: "shopping", title: "Shopping"),
    ]

    static func title(for source: String?) -> String {
        let normalized = (source ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return remoteSources.first { $0.id == normalized }?.title ?? "Cloud Browser"
    }
}

@MainActor
final class AppState: ObservableObject {
    @Published var route: NomiRoute?
    @Published var selectedMode: NomiWorkbenchMode = .chat
    @Published var serverConfig: ServerConfig?
    @Published var serverBaseURLInput = ""
    @Published var serverPasswordInput = ""
    @Published var serverConfigStatus = "Server not configured"
    @Published var islandSettings: NomiIslandSettings
    @Published var notificationRegistrationStatus = NomiNotificationRegistrationStatus()
    @Published var suggestionStore = NomiSuggestionStore()
    @Published var taskStore = NomiTaskStore()
    let liveActivityDeviceId: String
    private let settingsStore: NomiIslandSettingsStore
    private let saveServerConfigHandler: (ServerConfig) throws -> Void
    private var apnsTokenObserver: NSObjectProtocol?

    init(
        defaults: UserDefaults = .standard,
        loadServerConfig: () throws -> ServerConfig = NomiKeychain.loadServerConfig,
        saveServerConfig: @escaping (ServerConfig) throws -> Void = NomiKeychain.saveServerConfig
    ) {
        let store = NomiIslandSettingsStore(defaults: defaults)
        settingsStore = store
        islandSettings = store.load()
        saveServerConfigHandler = saveServerConfig
        liveActivityDeviceId = Self.loadOrCreateDeviceId(defaults: defaults)
        if let config = try? loadServerConfig() {
            serverConfig = config
            serverBaseURLInput = config.baseURL.absoluteString
            serverPasswordInput = config.password
            serverConfigStatus = "Server loaded, not tested"
        }
        apnsTokenObserver = NotificationCenter.default.addObserver(
            forName: .nomiAPNsDeviceTokenDidRegister,
            object: nil,
            queue: .main
        ) { [weak self] notification in
            guard let token = notification.userInfo?["token"] as? String else { return }
            Task { @MainActor in
                self?.updateApnsDeviceToken(token)
            }
        }
    }

    func handle(url: URL) {
        route = DeepLinkRouter.route(from: url)
        if let route {
            selectedMode = route.preferredMode
        }
    }

    func apiClientForCurrentServer() -> NomiApiClient? {
        guard let serverConfig else { return nil }
        return NomiApiClient(config: serverConfig)
    }

    func persistIslandSettings() {
        try? settingsStore.save(islandSettings)
    }

    func saveServerConfig(baseURL: String, password: String) throws {
        let config = try ServerConfig.normalize(baseURL: baseURL, password: password)
        try saveServerConfigHandler(config)
        serverConfig = config
        serverBaseURLInput = config.baseURL.absoluteString
        serverPasswordInput = config.password
        serverConfigStatus = "Server saved"
    }

    func registerCurrentDevice() async {
        guard let client = apiClientForCurrentServer() else {
            serverConfigStatus = "Server not configured"
            return
        }
        serverConfigStatus = "Testing server..."
        do {
            let isHealthy = try await client.health()
            guard isHealthy else {
                serverConfigStatus = "Server health check failed"
                return
            }
        } catch {
            serverConfigStatus = "Could not connect to server: \(error.localizedDescription)"
            return
        }
        do {
            try await client.registerDevice(
                deviceId: liveActivityDeviceId,
                displayName: "Nomi iOS",
                settings: islandSettings,
                apnsDeviceToken: notificationRegistrationStatus.apnsDeviceToken
            )
            serverConfigStatus = "Server connected"
        } catch {
            serverConfigStatus = "Server reachable; device sync failed: \(error.localizedDescription)"
        }
    }

    func updateApnsDeviceToken(_ token: String) {
        notificationRegistrationStatus.apnsDeviceToken = token
    }

    func updateNotificationPermission(_ permission: NomiNotificationPermissionStatus) {
        notificationRegistrationStatus.permission = permission
    }

    func handleRealtimeEvent(_ event: NomiRealtimeEvent) {
        switch event {
        case let .proactiveMessage(id, title, body, _):
            suggestionStore.ingestRealtime(
                AssistantSuggestion(id: id, title: title, body: body, priority: 0)
            )
        case .agentTaskDelivery, .agentTaskFallback:
            taskStore.ingest(event)
        case .error:
            suggestionStore.setRealtimeConnected(false)
        case .chatDelta, .chatDone, .ignored:
            break
        }
    }

    func syncIslandSettings() async {
        guard let client = apiClientForCurrentServer() else { return }
        do {
            try await client.updateDeviceSettings(deviceId: liveActivityDeviceId, settings: islandSettings)
        } catch {
            serverConfigStatus = "Settings sync failed: \(error.localizedDescription)"
        }
    }

    static func loadOrCreateDeviceId(defaults: UserDefaults, key: String = "nomi.ios.device_id") -> String {
        if let existing = defaults.string(forKey: key), !existing.isEmpty {
            return existing
        }
        let value = "ios-\(UUID().uuidString)"
        defaults.set(value, forKey: key)
        return value
    }
}

extension Notification.Name {
    static let nomiAPNsDeviceTokenDidRegister = Notification.Name("nomiAPNsDeviceTokenDidRegister")
}

enum NomiAccountChannelRoute: Equatable {
    case composio(slug: String)
    case remoteBrowser(source: String)
    case localOnly

    static func forSource(_ source: String) -> NomiAccountChannelRoute {
        let normalized = source.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        switch normalized {
        case "gmail":
            return .composio(slug: "gmail")
        case "calendar", "googlecalendar":
            return .composio(slug: "googlecalendar")
        case "googledrive", "drive":
            return .composio(slug: "googledrive")
        case "googledocs", "docs":
            return .composio(slug: "googledocs")
        case "googlesheets", "sheets":
            return .composio(slug: "googlesheets")
        case "googletasks", "tasks":
            return .composio(slug: "googletasks")
        case "github", "slack", "notion", "linear", "jira", "todoist", "google_maps":
            return .composio(slug: normalized)
        case "whatsapp", "telegram", "linkedin", "search", "shopping":
            return .remoteBrowser(source: normalized)
        default:
            return .localOnly
        }
    }
}

struct NomiSuggestionStore {
    private(set) var suggestions: [AssistantSuggestion] = []
    private(set) var unreadCount = 0
    private(set) var shouldPollSuggestions = false
    let pollIntervalSeconds = 60
    private var displayedIds: Set<String> = []

    mutating func setRealtimeConnected(_ connected: Bool) {
        shouldPollSuggestions = !connected
    }

    mutating func ingestRealtime(_ suggestion: AssistantSuggestion) {
        ingest([suggestion], incrementsUnread: true)
    }

    mutating func ingestPolled(_ polled: [AssistantSuggestion]) {
        ingest(polled, incrementsUnread: true)
    }

    private mutating func ingest(_ incoming: [AssistantSuggestion], incrementsUnread: Bool) {
        var fresh: [AssistantSuggestion] = []
        for suggestion in incoming where !displayedIds.contains(suggestion.id) {
            displayedIds.insert(suggestion.id)
            fresh.append(suggestion)
        }
        guard !fresh.isEmpty else { return }
        suggestions.insert(contentsOf: fresh, at: 0)
        if incrementsUnread {
            unreadCount += fresh.count
        }
    }
}

enum NomiTaskPhase: Equatable {
    case delivery
    case fallback
}

struct NomiTaskCard: Identifiable, Equatable {
    var id: String
    var taskId: String
    var title: String
    var body: String
    var phase: NomiTaskPhase
    var rawJSON: String
}

struct NomiTaskStore {
    private(set) var cards: [NomiTaskCard] = []
    private(set) var unreadCount = 0
    private var displayedEventIds: Set<String> = []

    mutating func ingest(_ event: NomiRealtimeEvent) {
        let card: NomiTaskCard?
        switch event {
        case let .agentTaskDelivery(eventId, taskId, body, rawJSON):
            card = NomiTaskCard(
                id: eventId,
                taskId: taskId,
                title: "长尾任务完成",
                body: body.isEmpty ? "长尾任务有新的交付结果。" : body,
                phase: .delivery,
                rawJSON: rawJSON
            )
        case let .agentTaskFallback(eventId, taskId, title, body, rawJSON):
            card = NomiTaskCard(
                id: eventId,
                taskId: taskId,
                title: title.isEmpty ? "长尾任务需要处理" : title,
                body: body.isEmpty ? "任务已暂停，请查看下一步。" : body,
                phase: .fallback,
                rawJSON: rawJSON
            )
        default:
            card = nil
        }
        guard let card, !displayedEventIds.contains(card.id) else { return }
        displayedEventIds.insert(card.id)
        cards.insert(card, at: 0)
        unreadCount += 1
    }
}

enum NomiVoiceConfidenceDecision: Equatable {
    case autoSend
    case confirmBeforeSend
    case reject

    static func decide(confidence: Double) -> NomiVoiceConfidenceDecision {
        if confidence >= 0.78 {
            return .autoSend
        }
        if confidence >= 0.55 {
            return .confirmBeforeSend
        }
        return .reject
    }
}

enum NomiVoicePayloadBuilder {
    static func startPayload(sessionId: String, conversationId: String?) throws -> Data {
        var payload: [String: Any] = [
            "type": "voice_start",
            "session_id": sessionId,
            "client_type": "ios_workbench_voice",
            "language_hint": "zh-CN",
            "audio": [
                "codec": "pcm_s16le",
                "sample_rate_hz": 16_000,
                "channels": 1,
                "frame_ms": 200,
            ],
        ]
        if let conversationId, !conversationId.isEmpty {
            payload["conversation_id"] = conversationId
        }
        return try JSONSerialization.data(withJSONObject: payload)
    }

    static func audioChunkPayload(sessionId: String, seq: Int, capturedAtMs: Int, audioBase64: String) throws -> Data {
        try JSONSerialization.data(withJSONObject: [
            "type": "audio_chunk",
            "session_id": sessionId,
            "seq": seq,
            "captured_at_ms": capturedAtMs,
            "audio_base64": audioBase64,
        ])
    }

    static func endPayload(sessionId: String, lastSeq: Int) throws -> Data {
        try JSONSerialization.data(withJSONObject: [
            "type": "voice_end",
            "session_id": sessionId,
            "last_seq": lastSeq,
        ])
    }

    static func cancelPayload(sessionId: String, reason: String) throws -> Data {
        try JSONSerialization.data(withJSONObject: [
            "type": "voice_cancel",
            "session_id": sessionId,
            "reason": reason,
        ])
    }
}

enum NomiWebWorkspaceBridge {
    static func passwordInjectionScript(password: String) -> String {
        "localStorage.setItem(\"par-password\", \(javascriptString(password)));"
    }

    static func pendingProactiveScript(json: String) -> String {
        "localStorage.setItem(\"nomi-pending-proactive\", \(javascriptString(json))); window.dispatchEvent(new Event(\"nomi-pending-proactive\"));"
    }

    static func pendingAgentEventScript(rawJSON: String) -> String {
        "localStorage.setItem(\"nomi-pending-agent-event\", \(javascriptString(rawJSON))); window.dispatchEvent(new Event(\"nomi-pending-agent-event\"));"
    }

    private static func javascriptString(_ value: String) -> String {
        let data = try? JSONSerialization.data(withJSONObject: [value])
        let array = data.flatMap { String(data: $0, encoding: .utf8) } ?? "[\"\"]"
        return String(array.dropFirst().dropLast())
    }
}

enum NomiNotificationPermissionStatus: Equatable {
    case notDetermined
    case denied
    case authorized
    case provisional
    case ephemeral
}

struct NomiNotificationRegistrationStatus: Equatable {
    var permission: NomiNotificationPermissionStatus = .notDetermined
    var apnsDeviceToken: String = ""

    var fallbackAvailabilityText: String {
        switch permission {
        case .notDetermined:
            return "APNs fallback unavailable: notification permission not requested"
        case .denied:
            return "APNs fallback unavailable: notification permission denied"
        case .authorized, .provisional, .ephemeral:
            return apnsDeviceToken.isEmpty ? "APNs fallback unavailable: device token missing" : "APNs fallback ready"
        }
    }
}

private extension NomiRoute {
    var preferredMode: NomiWorkbenchMode {
        switch self {
        case .chat:
            return .chat
        case .suggestion:
            return .suggestions
        case .task:
            return .tasks
        case .careerOpportunity:
            return .career
        case .liveActivitySettings:
            return .settings
        case .accounts, .composioConnected:
            return .accounts
        case .voice:
            return .chat
        case let .workbench(route, _):
            switch route {
            case "chat":
                return .chat
            case "suggestions":
                return .suggestions
            case "task", "tasks":
                return .tasks
            case "accounts":
                return .accounts
            case "career":
                return .career
            case "settings":
                return .settings
            default:
                return .chat
            }
        }
    }
}
