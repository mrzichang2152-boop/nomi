import XCTest
@testable import Nomi

final class NomiLiveActivityControllerTests: XCTestCase {
    func testHexTokenEncodingMatchesApnsFormat() {
        let token = NomiLiveActivityController.hexToken(Data([0x00, 0x0f, 0xa1, 0xff]))

        XCTAssertEqual(token, "000fa1ff")
    }

    func testInitialStateOmitsWidgetUrlWhenDeepLinksDisabled() {
        let state = NomiLiveActivityController.initialState(deepLinksEnabled: false)

        XCTAssertEqual(state.deepLink, "")
        XCTAssertNil(state.deepLinkURL)
    }

    func testChatDeltaStateUsesConversationUrlOnlyWhenDeepLinksEnabled() {
        let enabled = NomiLiveActivityController.chatDeltaState(
            partialAnswer: "hello",
            tokenSequence: 1,
            conversationId: "c1",
            includeText: true,
            deepLinksEnabled: true
        )
        let disabled = NomiLiveActivityController.chatDeltaState(
            partialAnswer: "hello",
            tokenSequence: 1,
            conversationId: "c1",
            includeText: true,
            deepLinksEnabled: false
        )

        XCTAssertEqual(enabled.deepLink, "nomi://chat?conversation_id=c1")
        XCTAssertEqual(disabled.deepLink, "")
        XCTAssertNil(disabled.deepLinkURL)
    }

    func testProactiveStateUsesSafePayloadAndSuggestionDeepLink() {
        let state = NomiLiveActivityController.proactiveState(
            title: "Review Gmail",
            body: "Private customer body",
            source: "gmail",
            suggestionId: "s1",
            unreadCount: 3,
            includeSensitiveText: false,
            deepLinksEnabled: true
        )

        XCTAssertEqual(state.phase, "proactive_message")
        XCTAssertEqual(state.title, "Review Gmail")
        XCTAssertEqual(state.body, "Open Nomi to review it.")
        XCTAssertEqual(state.suggestionId, "s1")
        XCTAssertEqual(state.unreadCount, 3)
        XCTAssertEqual(state.payloadMode, "safe")
        XCTAssertEqual(state.deepLink, "nomi://suggestion?id=s1")
    }

    func testTaskStateUsesTaskDeepLink() {
        let state = NomiLiveActivityController.taskState(
            phase: "task_delivery",
            title: "Long task complete",
            body: "Draft ready",
            taskId: "task-1",
            unreadCount: 2,
            includeSensitiveText: true,
            deepLinksEnabled: true
        )

        XCTAssertEqual(state.phase, "task_delivery")
        XCTAssertEqual(state.body, "Draft ready")
        XCTAssertEqual(state.taskId, "task-1")
        XCTAssertEqual(state.payloadMode, "sensitive")
        XCTAssertEqual(state.deepLink, "nomi://task?id=task-1")
    }

    func testDynamicIslandPresentationAvoidsLeadingTextClipping() {
        let state = NomiLiveActivityController.chatDeltaState(
            partialAnswer: "Local Dynamic Island preview",
            tokenSequence: 1,
            conversationId: "simulator-preview",
            includeText: true,
            deepLinksEnabled: true
        )

        XCTAssertEqual(state.dynamicIslandLeadingBadge, "N")
        XCTAssertEqual(state.dynamicIslandSourceLabel, "Chat")
        XCTAssertEqual(state.dynamicIslandHeadline, "Nomi is replying")
        XCTAssertEqual(state.dynamicIslandDetail, "Local Dynamic Island preview")
        XCTAssertEqual(state.dynamicIslandCompactTrailing, "1")
    }

    func testDynamicIslandPresentationFormatsTaskAndSuggestionSources() {
        let task = NomiLiveActivityController.taskState(
            phase: "task_delivery",
            title: "Long task complete",
            body: "Draft ready",
            taskId: "task-1",
            unreadCount: 2,
            includeSensitiveText: true,
            deepLinksEnabled: true
        )
        let proactive = NomiLiveActivityController.proactiveState(
            title: "Review Gmail",
            body: "Open the latest message",
            source: "gmail",
            suggestionId: "s1",
            unreadCount: 3,
            includeSensitiveText: true,
            deepLinksEnabled: true
        )

        XCTAssertEqual(task.dynamicIslandSourceLabel, "Task")
        XCTAssertEqual(task.dynamicIslandCompactTrailing, "2")
        XCTAssertEqual(proactive.dynamicIslandSourceLabel, "Gmail")
        XCTAssertEqual(proactive.dynamicIslandCompactTrailing, "3")
    }
}
