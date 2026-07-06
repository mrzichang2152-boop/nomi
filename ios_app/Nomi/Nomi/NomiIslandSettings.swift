import Foundation

struct NomiIslandSettings: Codable, Equatable {
    var liveActivityEnabled: Bool = true
    var notificationFallbackEnabled: Bool = true
    var deepLinksEnabled: Bool = true
    var tokenLevelChatStreamingEnabled: Bool = false
    var tokenLevelChatDelivery: TokenLevelChatDelivery = .localWhenForeground
    var sensitiveApnsPayloadEnabled: Bool = false
    var includePrivateMessageBody: Bool = false
    var includeContactNames: Bool = false
    var includeRawPrivateContext: Bool = false
    var maxSensitivePayloadChars: Int = 2400

    enum CodingKeys: String, CodingKey {
        case liveActivityEnabled = "live_activity_enabled"
        case notificationFallbackEnabled = "notification_fallback_enabled"
        case deepLinksEnabled = "deep_links_enabled"
        case tokenLevelChatStreamingEnabled = "token_level_chat_streaming_enabled"
        case tokenLevelChatDelivery = "token_level_chat_delivery"
        case sensitiveApnsPayloadEnabled = "sensitive_apns_payload_enabled"
        case includePrivateMessageBody = "include_private_message_body"
        case includeContactNames = "include_contact_names"
        case includeRawPrivateContext = "include_raw_private_context"
        case maxSensitivePayloadChars = "max_sensitive_payload_chars"
    }
}

enum TokenLevelChatDelivery: String, Codable, CaseIterable, Identifiable {
    case localWhenForeground = "local_when_foreground"
    case apnsBestEffort = "apns_best_effort"
    case localAndApnsBestEffort = "local_and_apns_best_effort"

    var id: String { rawValue }
}

extension NomiIslandSettings {
    func asDictionary() throws -> [String: Any] {
        let data = try JSONEncoder().encode(self)
        return try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
    }
}

struct NomiIslandSettingsStore {
    private let defaults: UserDefaults
    private let key: String

    init(defaults: UserDefaults = .standard, key: String = "nomi.ios.island_settings") {
        self.defaults = defaults
        self.key = key
    }

    func load() -> NomiIslandSettings {
        guard let data = defaults.data(forKey: key) else {
            return NomiIslandSettings()
        }
        return (try? JSONDecoder().decode(NomiIslandSettings.self, from: data)) ?? NomiIslandSettings()
    }

    func save(_ settings: NomiIslandSettings) throws {
        let data = try JSONEncoder().encode(settings)
        defaults.set(data, forKey: key)
    }
}
