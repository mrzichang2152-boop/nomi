import XCTest
@testable import Nomi

final class DeepLinkRouterTests: XCTestCase {
    func testRoutesSuggestionDeepLink() {
        let route = DeepLinkRouter.route(from: URL(string: "nomi://suggestion?id=s1")!)

        XCTAssertEqual(route, .suggestion(id: "s1"))
    }

    func testRoutesChatConversationDeepLink() {
        let route = DeepLinkRouter.route(from: URL(string: "nomi://chat?conversation_id=c1")!)

        XCTAssertEqual(route, .chat(conversationId: "c1"))
    }

    func testRoutesTaskDeepLinkWithEventId() {
        let route = DeepLinkRouter.route(from: URL(string: "nomi://task?id=t1&event_id=e1")!)

        XCTAssertEqual(route, .task(id: "t1", eventId: "e1"))
    }

    func testRoutesAccountsAndVoiceDeepLinks() {
        XCTAssertEqual(DeepLinkRouter.route(from: URL(string: "nomi://accounts")!), .accounts)
        XCTAssertEqual(DeepLinkRouter.route(from: URL(string: "nomi://voice")!), .voice)
    }

    func testRoutesComposioCallback() {
        let route = DeepLinkRouter.route(from: URL(string: "nomi://composio/connected?toolkit=gmail&status=connected&message=Done")!)

        XCTAssertEqual(route, .composioConnected(toolkit: "gmail", status: "connected", message: "Done"))
    }

    func testRoutesWorkbenchTaskDeepLink() {
        let route = DeepLinkRouter.route(from: URL(string: "nomi://workbench?route=task&task_id=t1")!)

        XCTAssertEqual(route, .workbench(route: "task", taskId: "t1"))
    }

    func testRejectsNonNomiUrl() {
        XCTAssertNil(DeepLinkRouter.route(from: URL(string: "https://example.com")!))
    }
}
