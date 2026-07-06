import ActivityKit
import Foundation

struct NomiLiveActivityAttributes: ActivityAttributes {
    public struct ContentState: Codable, Hashable {
        var phase: String
        var title: String
        var body: String
        var source: String
        var suggestionId: String
        var taskId: String
        var conversationId: String
        var unreadCount: Int
        var partialAnswer: String
        var tokenSequence: Int
        var payloadMode: String
        var deepLink: String
        var truncated: Bool
        var privateContext: PrivateContext?
    }

    struct PrivateContext: Codable, Hashable {
        var contact: String?
        var channel: String?
        var rawSnippet: String?
    }

    var activityId: String
    var deviceId: String
}

extension NomiLiveActivityAttributes.ContentState {
    var deepLinkURL: URL? {
        let value = deepLink.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return nil }
        return URL(string: value)
    }

    var dynamicIslandLeadingBadge: String {
        "N"
    }

    var dynamicIslandSourceLabel: String {
        switch source.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "chat":
            return "Chat"
        case "long_tail_agent":
            return "Task"
        case "gmail":
            return "Gmail"
        case "calendar", "googlecalendar":
            return "Calendar"
        case "whatsapp":
            return "WhatsApp"
        case "system", "":
            return "Nomi"
        default:
            return source
                .replacingOccurrences(of: "_", with: " ")
                .capitalized
        }
    }

    var dynamicIslandHeadline: String {
        let cleanTitle = title.trimmingCharacters(in: .whitespacesAndNewlines)
        if phase == "chat_streaming" {
            return "Nomi is replying"
        }
        return cleanTitle.isEmpty ? "Nomi" : cleanTitle
    }

    var dynamicIslandDetail: String {
        if phase == "chat_streaming" {
            let cleanAnswer = partialAnswer.trimmingCharacters(in: .whitespacesAndNewlines)
            if !cleanAnswer.isEmpty {
                return cleanAnswer
            }
        }
        if let raw = privateContext?.rawSnippet?.trimmingCharacters(in: .whitespacesAndNewlines), !raw.isEmpty {
            return raw
        }
        let cleanBody = body.trimmingCharacters(in: .whitespacesAndNewlines)
        return cleanBody.isEmpty ? "Open Nomi to continue." : cleanBody
    }

    var dynamicIslandCompactTrailing: String {
        if phase == "chat_streaming" {
            return tokenSequence > 0 ? "\(tokenSequence)" : "•"
        }
        return unreadCount > 0 ? "\(unreadCount)" : "•"
    }
}
