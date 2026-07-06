import Foundation

@MainActor
protocol NomiLiveActivityStarting: AnyObject {
    var activityId: String? { get }

    func start(deviceId: String, apiClient: NomiApiClient?, deepLinksEnabled: Bool) async throws -> String
    func updateFromChatDelta(_ delta: String, conversationId: String, includeText: Bool, deepLinksEnabled: Bool, resetStream: Bool) async
    func refreshDeepLinkPreference(enabled: Bool) async
    func end() async
}

enum NomiLiveActivityStartupResult: Equatable {
    case disabled
    case started(String)
    case alreadyActive(String)
}

enum NomiLiveActivityStartup {
    @MainActor
    static func startIfNeeded(
        settings: NomiIslandSettings,
        deviceId: String,
        apiClient: NomiApiClient?,
        controller: any NomiLiveActivityStarting
    ) async throws -> NomiLiveActivityStartupResult {
        guard settings.liveActivityEnabled else {
            return .disabled
        }
        if let activityId = controller.activityId {
            return .alreadyActive(activityId)
        }
        let activityId = try await controller.start(
            deviceId: deviceId,
            apiClient: apiClient,
            deepLinksEnabled: settings.deepLinksEnabled
        )
        return .started(activityId)
    }
}
