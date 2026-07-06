import XCTest
@testable import Nomi

final class ServerConfigTests: XCTestCase {
    func testNormalizeAddsHttpSchemeAndTrimsPassword() throws {
        let config = try ServerConfig.normalize(baseURL: "example.com/", password: " secret ")

        XCTAssertEqual(config.baseURL.absoluteString, "http://example.com")
        XCTAssertEqual(config.password, "secret")
    }

    func testNormalizeRejectsMissingPassword() {
        XCTAssertThrowsError(try ServerConfig.normalize(baseURL: "https://example.com", password: " "))
    }
}
