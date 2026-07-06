import XCTest
@testable import Nomi

final class NomiSuggestionIntentsTests: XCTestCase {
    func testSuggestionIntentsCarrySuggestionId() {
        let done = MarkSuggestionDoneIntent(suggestionId: "s1")
        let dismiss = DismissSuggestionIntent(suggestionId: "s2")

        XCTAssertEqual(done.suggestionId, "s1")
        XCTAssertEqual(dismiss.suggestionId, "s2")
    }
}
