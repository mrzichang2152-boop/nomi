import XCTest
@testable import Nomi

@MainActor
final class NomiLiveActivityStartupTests: XCTestCase {
    private final class FakeStarter: NomiLiveActivityStarting {
        var activityId: String?
        private(set) var startDeviceIds: [String] = []
        private(set) var startDeepLinksEnabled: [Bool] = []
        private(set) var endCallCount = 0

        func start(deviceId: String, apiClient: NomiApiClient?, deepLinksEnabled: Bool) async throws -> String {
            startDeviceIds.append(deviceId)
            startDeepLinksEnabled.append(deepLinksEnabled)
            activityId = "activity-1"
            return "activity-1"
        }

        func updateFromChatDelta(
            _ delta: String,
            conversationId: String,
            includeText: Bool,
            deepLinksEnabled: Bool,
            resetStream: Bool
        ) async {}

        func refreshDeepLinkPreference(enabled: Bool) async {}

        func end() async {
            endCallCount += 1
            activityId = nil
        }
    }

    func testStartsActivityWhenEnabledAndInactive() async throws {
        var settings = NomiIslandSettings()
        settings.liveActivityEnabled = true
        let starter = FakeStarter()

        let result = try await NomiLiveActivityStartup.startIfNeeded(
            settings: settings,
            deviceId: "device-1",
            apiClient: nil,
            controller: starter
        )

        XCTAssertEqual(result, .started("activity-1"))
        XCTAssertEqual(starter.startDeviceIds, ["device-1"])
        XCTAssertEqual(starter.startDeepLinksEnabled, [true])
    }

    func testDoesNotStartActivityWhenDisabled() async throws {
        var settings = NomiIslandSettings()
        settings.liveActivityEnabled = false
        let starter = FakeStarter()

        let result = try await NomiLiveActivityStartup.startIfNeeded(
            settings: settings,
            deviceId: "device-1",
            apiClient: nil,
            controller: starter
        )

        XCTAssertEqual(result, .disabled)
        XCTAssertTrue(starter.startDeviceIds.isEmpty)
    }

    func testReturnsExistingActivityWithoutStartingAgain() async throws {
        var settings = NomiIslandSettings()
        settings.liveActivityEnabled = true
        let starter = FakeStarter()
        starter.activityId = "existing-activity"

        let result = try await NomiLiveActivityStartup.startIfNeeded(
            settings: settings,
            deviceId: "device-1",
            apiClient: nil,
            controller: starter
        )

        XCTAssertEqual(result, .alreadyActive("existing-activity"))
        XCTAssertTrue(starter.startDeviceIds.isEmpty)
    }

    func testPassesDisabledDeepLinksPreferenceToController() async throws {
        var settings = NomiIslandSettings()
        settings.liveActivityEnabled = true
        settings.deepLinksEnabled = false
        let starter = FakeStarter()

        _ = try await NomiLiveActivityStartup.startIfNeeded(
            settings: settings,
            deviceId: "device-1",
            apiClient: nil,
            controller: starter
        )

        XCTAssertEqual(starter.startDeepLinksEnabled, [false])
    }
}
