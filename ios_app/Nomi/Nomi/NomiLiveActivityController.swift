import ActivityKit
import Foundation

@MainActor
final class NomiLiveActivityController: ObservableObject, NomiLiveActivityStarting {
    @Published private(set) var activityId: String?
    private var activity: Activity<NomiLiveActivityAttributes>?
    private var currentState: NomiLiveActivityAttributes.ContentState?
    private var partialAnswer = ""
    private var tokenSequence = 0

    nonisolated static func hexToken(_ data: Data) -> String {
        data.map { String(format: "%02x", $0) }.joined()
    }

    nonisolated static func initialState(deepLinksEnabled: Bool) -> NomiLiveActivityAttributes.ContentState {
        NomiLiveActivityAttributes.ContentState(
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
            deepLink: deepLinksEnabled ? "nomi://chat" : "",
            truncated: false,
            privateContext: nil
        )
    }

    nonisolated static func chatDeltaState(
        partialAnswer: String,
        tokenSequence: Int,
        conversationId: String,
        includeText: Bool,
        deepLinksEnabled: Bool
    ) -> NomiLiveActivityAttributes.ContentState {
        NomiLiveActivityAttributes.ContentState(
            phase: "chat_streaming",
            title: "Nomi is replying",
            body: "Generating response",
            source: "chat",
            suggestionId: "",
            taskId: "",
            conversationId: conversationId,
            unreadCount: 0,
            partialAnswer: includeText ? String(partialAnswer.suffix(800)) : "",
            tokenSequence: tokenSequence,
            payloadMode: includeText ? "sensitive" : "safe",
            deepLink: deepLinksEnabled ? "nomi://chat?conversation_id=\(conversationId)" : "",
            truncated: partialAnswer.count > 800,
            privateContext: nil
        )
    }

    nonisolated static func proactiveState(
        title: String,
        body: String,
        source: String,
        suggestionId: String,
        unreadCount: Int,
        includeSensitiveText: Bool,
        deepLinksEnabled: Bool
    ) -> NomiLiveActivityAttributes.ContentState {
        NomiLiveActivityAttributes.ContentState(
            phase: "proactive_message",
            title: title.isEmpty ? "Nomi" : title,
            body: includeSensitiveText ? body : "Open Nomi to review it.",
            source: source,
            suggestionId: suggestionId,
            taskId: "",
            conversationId: "",
            unreadCount: unreadCount,
            partialAnswer: "",
            tokenSequence: 0,
            payloadMode: includeSensitiveText ? "sensitive" : "safe",
            deepLink: deepLinksEnabled ? "nomi://suggestion?id=\(suggestionId)" : "",
            truncated: false,
            privateContext: nil
        )
    }

    nonisolated static func taskState(
        phase: String,
        title: String,
        body: String,
        taskId: String,
        unreadCount: Int,
        includeSensitiveText: Bool,
        deepLinksEnabled: Bool
    ) -> NomiLiveActivityAttributes.ContentState {
        NomiLiveActivityAttributes.ContentState(
            phase: phase,
            title: title.isEmpty ? "Nomi Task" : title,
            body: includeSensitiveText ? body : "Open Nomi to review it.",
            source: "long_tail_agent",
            suggestionId: "",
            taskId: taskId,
            conversationId: "",
            unreadCount: unreadCount,
            partialAnswer: "",
            tokenSequence: 0,
            payloadMode: includeSensitiveText ? "sensitive" : "safe",
            deepLink: deepLinksEnabled ? "nomi://task?id=\(taskId)" : "",
            truncated: false,
            privateContext: nil
        )
    }

    func start(deviceId: String, apiClient: NomiApiClient? = nil, deepLinksEnabled: Bool) async throws -> String {
        if let activity { return activity.attributes.activityId }
        if let existingActivity = Activity<NomiLiveActivityAttributes>.activities.first {
            activity = existingActivity
            activityId = existingActivity.attributes.activityId
            currentState = Self.initialState(deepLinksEnabled: deepLinksEnabled)
            return existingActivity.attributes.activityId
        }
        let id = UUID().uuidString
        let attributes = NomiLiveActivityAttributes(activityId: id, deviceId: deviceId)
        let state = Self.initialState(deepLinksEnabled: deepLinksEnabled)
        let content = ActivityContent(state: state, staleDate: Date().addingTimeInterval(600))
        let pushType: PushType? = apiClient == nil ? nil : .token
        let newActivity = try Activity.request(attributes: attributes, content: content, pushType: pushType)
        activity = newActivity
        activityId = id
        currentState = state
        if let apiClient {
            Task {
                for await tokenData in newActivity.pushTokenUpdates {
                    let token = Self.hexToken(tokenData)
                    try? await apiClient.registerLiveActivity(deviceId: deviceId, activityId: id, updateToken: token)
                }
            }
        }
        return id
    }

    func updateFromChatDelta(
        _ delta: String,
        conversationId: String,
        includeText: Bool,
        deepLinksEnabled: Bool,
        resetStream: Bool = false
    ) async {
        guard let activity else { return }
        if resetStream {
            partialAnswer = ""
            tokenSequence = 0
        }
        tokenSequence += 1
        partialAnswer += delta
        let state = Self.chatDeltaState(
            partialAnswer: partialAnswer,
            tokenSequence: tokenSequence,
            conversationId: conversationId,
            includeText: includeText,
            deepLinksEnabled: deepLinksEnabled
        )
        currentState = state
        await activity.update(ActivityContent(state: state, staleDate: Date().addingTimeInterval(600)))
    }

    func updateFromProactive(
        title: String,
        body: String,
        source: String,
        suggestionId: String,
        unreadCount: Int,
        includeSensitiveText: Bool,
        deepLinksEnabled: Bool
    ) async {
        guard let activity else { return }
        let state = Self.proactiveState(
            title: title,
            body: body,
            source: source,
            suggestionId: suggestionId,
            unreadCount: unreadCount,
            includeSensitiveText: includeSensitiveText,
            deepLinksEnabled: deepLinksEnabled
        )
        currentState = state
        await activity.update(ActivityContent(state: state, staleDate: Date().addingTimeInterval(600)))
    }

    func updateFromTask(
        phase: String,
        title: String,
        body: String,
        taskId: String,
        unreadCount: Int,
        includeSensitiveText: Bool,
        deepLinksEnabled: Bool
    ) async {
        guard let activity else { return }
        let state = Self.taskState(
            phase: phase,
            title: title,
            body: body,
            taskId: taskId,
            unreadCount: unreadCount,
            includeSensitiveText: includeSensitiveText,
            deepLinksEnabled: deepLinksEnabled
        )
        currentState = state
        await activity.update(ActivityContent(state: state, staleDate: Date().addingTimeInterval(600)))
    }

    func refreshDeepLinkPreference(enabled: Bool) async {
        guard let activity else { return }
        var state = currentState ?? Self.initialState(deepLinksEnabled: enabled)
        state.deepLink = enabled ? deepLink(for: state) : ""
        currentState = state
        await activity.update(ActivityContent(state: state, staleDate: Date().addingTimeInterval(600)))
    }

    private func deepLink(for state: NomiLiveActivityAttributes.ContentState) -> String {
        if state.phase == "chat_streaming", !state.conversationId.isEmpty {
            return "nomi://chat?conversation_id=\(state.conversationId)"
        }
        if !state.suggestionId.isEmpty {
            return "nomi://suggestion?id=\(state.suggestionId)"
        }
        if !state.taskId.isEmpty {
            return "nomi://task?id=\(state.taskId)"
        }
        return "nomi://chat"
    }

    func end() async {
        guard let activity else {
            activityId = nil
            partialAnswer = ""
            tokenSequence = 0
            return
        }
        let state = NomiLiveActivityAttributes.ContentState(
            phase: "idle",
            title: "Nomi",
            body: "Stopped",
            source: "system",
            suggestionId: "",
            taskId: "",
            conversationId: "",
            unreadCount: 0,
            partialAnswer: "",
            tokenSequence: tokenSequence,
            payloadMode: "safe",
            deepLink: "nomi://chat",
            truncated: false,
            privateContext: nil
        )
        await activity.end(ActivityContent(state: state, staleDate: nil), dismissalPolicy: .immediate)
        self.activity = nil
        activityId = nil
        currentState = nil
        partialAnswer = ""
        tokenSequence = 0
    }
}
