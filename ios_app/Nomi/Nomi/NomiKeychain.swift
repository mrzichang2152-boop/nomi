import Foundation
import Security

enum NomiKeychain {
    private static let service = "com.nomi.private-cloud"
    private static let account = "server-config"
    private static let simulatorFallbackKey = "nomi.ios.simulator.server_config"

    static func saveServerConfig(_ config: ServerConfig) throws {
        let data = try JSONEncoder().encode(config)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
        var item = query
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(item as CFDictionary, nil)
        #if targetEnvironment(simulator)
        if status != errSecSuccess, shouldUseSimulatorFallback(for: status) {
            UserDefaults.standard.set(data, forKey: simulatorFallbackKey)
            return
        }
        UserDefaults.standard.removeObject(forKey: simulatorFallbackKey)
        #endif
        guard status == errSecSuccess else { throw KeychainError.unhandled(status) }
    }

    static func loadServerConfig() throws -> ServerConfig {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else {
            #if targetEnvironment(simulator)
            if let fallbackData = UserDefaults.standard.data(forKey: simulatorFallbackKey) {
                return try JSONDecoder().decode(ServerConfig.self, from: fallbackData)
            }
            #endif
            throw KeychainError.notFound
        }
        return try JSONDecoder().decode(ServerConfig.self, from: data)
    }

    #if targetEnvironment(simulator)
    private static func shouldUseSimulatorFallback(for status: OSStatus) -> Bool {
        status == errSecMissingEntitlement || status == errSecInteractionNotAllowed
    }
    #endif

    enum KeychainError: Error, Equatable, LocalizedError {
        case notFound
        case unhandled(OSStatus)

        var errorDescription: String? {
            switch self {
            case .notFound:
                return "Server config was not found in Keychain."
            case let .unhandled(status):
                return "Keychain operation failed with OSStatus \(status)."
            }
        }
    }
}
