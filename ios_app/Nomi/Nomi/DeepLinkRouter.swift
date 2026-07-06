import Foundation

enum NomiRoute: Equatable {
    case chat(conversationId: String?)
    case suggestion(id: String)
    case task(id: String, eventId: String? = nil)
    case liveActivitySettings
    case careerOpportunity(id: String)
    case accounts
    case voice
    case composioConnected(toolkit: String, status: String, message: String)
    case workbench(route: String, taskId: String?)
}

struct DeepLinkRouter {
    static func route(from url: URL) -> NomiRoute? {
        guard url.scheme == "nomi" else { return nil }
        let host = url.host ?? ""
        let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        let query = Dictionary(uniqueKeysWithValues: (components?.queryItems ?? []).map { ($0.name, $0.value ?? "") })

        switch host {
        case "chat":
            return .chat(conversationId: query["conversation_id"])
        case "suggestion":
            guard let id = query["id"], !id.isEmpty else { return nil }
            return .suggestion(id: id)
        case "task":
            guard let id = query["id"], !id.isEmpty else { return nil }
            return .task(id: id, eventId: query["event_id"])
        case "settings":
            return url.path == "/live-activity" ? .liveActivitySettings : nil
        case "career":
            guard url.path == "/opportunity", let id = query["id"], !id.isEmpty else { return nil }
            return .careerOpportunity(id: id)
        case "accounts":
            return .accounts
        case "voice":
            return .voice
        case "composio":
            guard url.path == "/connected" else { return nil }
            return .composioConnected(
                toolkit: query["toolkit"] ?? "",
                status: query["status"] ?? "",
                message: query["message"] ?? ""
            )
        case "workbench":
            return .workbench(route: query["route"] ?? "", taskId: query["task_id"])
        default:
            return nil
        }
    }
}
