import Foundation

struct ServerConfig: Codable, Equatable {
    var baseURL: URL
    var password: String

    static func normalize(baseURL input: String, password: String) throws -> ServerConfig {
        var value = input.trimmingCharacters(in: .whitespacesAndNewlines)
        if value.isEmpty { throw ConfigError.missingBaseURL }
        if !value.contains("://") { value = "http://" + value }
        while value.hasSuffix("/") && value.count > "https://".count {
            value.removeLast()
        }
        guard let url = URL(string: value), ["http", "https"].contains(url.scheme?.lowercased() ?? "") else {
            throw ConfigError.invalidBaseURL
        }
        let cleanPassword = password.trimmingCharacters(in: .whitespacesAndNewlines)
        if cleanPassword.isEmpty { throw ConfigError.missingPassword }
        return ServerConfig(baseURL: url, password: cleanPassword)
    }

    enum ConfigError: Error, Equatable {
        case missingBaseURL
        case invalidBaseURL
        case missingPassword
    }
}
