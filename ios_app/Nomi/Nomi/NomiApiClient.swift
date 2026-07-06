import Foundation

struct AssistantSuggestion: Codable, Identifiable, Equatable {
    var id: String
    var title: String
    var body: String
    var priority: Double
}

struct ChatTurn: Codable, Equatable {
    var role: String
    var content: String
}

struct ChatRequest: Codable, Equatable {
    var message: String
    var conversation_id: String?
    var client_type: String = "ios"
    var client_request_id: String?
    var client_context_delta: [ChatTurn] = []
}

struct ChatResponse: Codable, Equatable {
    var answer: String
    var conversation_id: String
}

struct NomiTaskDetail: Codable, Equatable, Identifiable {
    var id: String
    var status: String?
    var title: String?
}

struct NomiTaskEvent: Codable, Equatable, Identifiable {
    var id: String
    var type: String
    var message: String?
}

struct CollectorStatus: Codable, Equatable, Identifiable {
    var source: String
    var enabled: Bool
    var paused: Bool
    var healthStatus: String

    var id: String { source }

    enum CodingKeys: String, CodingKey {
        case source
        case enabled
        case paused
        case healthStatus = "health_status"
    }
}

struct ComposioToolkitConnection: Codable, Equatable {
    var slug: String
    var connected: Bool
}

struct AssistantIdentity: Codable, Equatable, Identifiable {
    var identityId: String
    var kind: String
    var displayName: String
    var address: String?
    var status: String?

    var id: String { identityId }

    enum CodingKeys: String, CodingKey {
        case identityId = "identity_id"
        case kind
        case displayName = "display_name"
        case address
        case status
    }
}

struct CareerBoard: Codable, Equatable {
    var profiles: [CareerProfile]?
    var opportunities: [JobOpportunity]?
    var applications: [JobApplicationState]?
}

struct CareerProfile: Codable, Equatable, Identifiable {
    var id: String
    var headline: String?
}

struct JobOpportunity: Codable, Equatable, Identifiable {
    var id: String
    var title: String?
    var company: String?
    var status: String?
}

struct JobApplicationState: Codable, Equatable, Identifiable {
    var id: String
    var jobId: String?
    var status: String?
    var stage: String?
    var nextStep: String?

    enum CodingKeys: String, CodingKey {
        case id
        case jobId = "job_id"
        case status
        case stage
        case nextStep = "next_step"
    }
}

private struct CollectorStatusEnvelope: Codable, Equatable {
    var collectors: [CollectorStatus]
}

private struct AssistantIdentityEnvelope: Codable, Equatable {
    var identities: [AssistantIdentity]
}

private struct ComposioToolkitEnvelope: Codable, Equatable {
    var toolkits: [ComposioToolkitConnection]
}

final class NomiApiClient {
    private let config: ServerConfig
    private let session: URLSession

    init(config: ServerConfig, session: URLSession = .shared) {
        self.config = config
        self.session = session
    }

    static func deviceRegistrationPayload(
        deviceId: String,
        displayName: String,
        settings: NomiIslandSettings,
        apnsEnvironment: String = "sandbox",
        apnsDeviceToken: String = "",
        liveActivityPushToStartToken: String = ""
    ) throws -> Data {
        let payload: [String: Any] = [
            "device_id": deviceId,
            "display_name": displayName,
            "apns_environment": apnsEnvironment,
            "apns_device_token": apnsDeviceToken,
            "live_activity_push_to_start_token": liveActivityPushToStartToken,
            "settings": try settings.asDictionary(),
        ]
        return try JSONSerialization.data(withJSONObject: payload)
    }

    static func remoteBrowserURL(for config: ServerConfig) -> URL {
        var components = URLComponents()
        components.scheme = config.baseURL.scheme
        components.host = config.baseURL.host
        components.port = 6080
        components.path = "/vnc_lite.html"
        let vncPassword = config.password.hasSuffix("-vnc") ? config.password : "\(config.password)-vnc"
        components.queryItems = [
            URLQueryItem(name: "autoconnect", value: "1"),
            URLQueryItem(name: "scale", value: "true"),
            URLQueryItem(name: "quality", value: "6"),
            URLQueryItem(name: "compression", value: "2"),
            URLQueryItem(name: "show_dot", value: "1"),
            URLQueryItem(name: "password", value: vncPassword),
        ]
        return components.url ?? config.baseURL
    }

    static func browserOpenPayload(source: String) throws -> Data {
        try JSONSerialization.data(withJSONObject: ["source": source])
    }

    static func composioConnectPath(slug: String, force: Bool = false) -> String {
        let normalized = slug.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let path = "/api/integrations/composio/connect/\(normalized)"
        return force ? "\(path)?force=true" : path
    }

    static func careerApplicationPatchPayload(status: String?, stage: String?, nextStep: String? = nil, userNote: String?) throws -> Data {
        var payload: [String: String] = [:]
        if let status, !status.isEmpty {
            payload["status"] = status
        }
        if let stage, !stage.isEmpty {
            payload["stage"] = stage
        }
        if let nextStep, !nextStep.isEmpty {
            payload["next_step"] = nextStep
        }
        if let userNote, !userNote.isEmpty {
            payload["user_note"] = userNote
        }
        return try JSONSerialization.data(withJSONObject: payload)
    }

    static func taskHumanInputPayload(_ input: String) throws -> Data {
        try JSONSerialization.data(withJSONObject: ["input": input])
    }

    static func taskCancelPayload(_ reason: String) throws -> Data {
        try JSONSerialization.data(withJSONObject: ["reason": reason])
    }

    static func decodeCollectorsStatus(_ data: Data) throws -> [CollectorStatus] {
        let decoder = JSONDecoder()
        if let direct = try? decoder.decode([CollectorStatus].self, from: data) {
            return direct
        }
        return try decoder.decode(CollectorStatusEnvelope.self, from: data).collectors
    }

    static func decodeAssistantIdentities(_ data: Data) throws -> [AssistantIdentity] {
        let decoder = JSONDecoder()
        if let direct = try? decoder.decode([AssistantIdentity].self, from: data) {
            return direct
        }
        return try decoder.decode(AssistantIdentityEnvelope.self, from: data).identities
    }

    static func decodeComposioToolkits(_ data: Data) throws -> [ComposioToolkitConnection] {
        let decoder = JSONDecoder()
        if let direct = try? decoder.decode([ComposioToolkitConnection].self, from: data) {
            return direct
        }
        return try decoder.decode(ComposioToolkitEnvelope.self, from: data).toolkits
    }

    static func mergeCollectorStatuses(
        _ collectors: [CollectorStatus],
        with toolkits: [ComposioToolkitConnection]
    ) -> [CollectorStatus] {
        var order = collectors.map(\.source)
        var bySource = Dictionary(uniqueKeysWithValues: collectors.map { ($0.source, $0) })
        for toolkit in toolkits {
            guard let source = sourceForComposioToolkit(toolkit.slug) else { continue }
            if bySource[source]?.healthStatus == "healthy" {
                continue
            }
            bySource[source] = CollectorStatus(
                source: source,
                enabled: true,
                paused: false,
                healthStatus: toolkit.connected ? "healthy" : "degraded"
            )
            if !order.contains(source) {
                order.append(source)
            }
        }
        return order.compactMap { bySource[$0] }
    }

    static func decodeTaskDetail(_ data: Data) throws -> NomiTaskDetail {
        let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let state = object?["state"] as? [String: Any] ?? object ?? [:]
        return NomiTaskDetail(
            id: firstNonEmpty(state["task_id"], state["id"]) ?? "",
            status: firstNonEmpty(state["status"]),
            title: firstNonEmpty(state["title"], state["original_goal"], state["current_node"])
        )
    }

    static func decodeTaskEvents(_ data: Data) throws -> [NomiTaskEvent] {
        let object = try JSONSerialization.jsonObject(with: data)
        let rawEvents: [[String: Any]]
        if let array = object as? [[String: Any]] {
            rawEvents = array
        } else if let dictionary = object as? [String: Any], let events = dictionary["events"] as? [[String: Any]] {
            rawEvents = events
        } else {
            rawEvents = []
        }

        return rawEvents.enumerated().map { index, event in
            let payload = event["payload"] as? [String: Any]
            let fallbackId = "event-\(index + 1)"
            return NomiTaskEvent(
                id: firstNonEmpty(event["event_id"], event["id"]) ?? fallbackId,
                type: firstNonEmpty(event["event_type"], event["type"]) ?? "event",
                message: firstNonEmpty(
                    event["message"],
                    payload?["message"],
                    payload?["original_goal"],
                    payload?["status"],
                    payload?["reason"]
                )
            )
        }
    }

    func health() async throws -> Bool {
        let data = try await request(path: "/health", method: "GET", auth: false)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        return json?["status"] as? String == "ok"
    }

    func suggestions() async throws -> [AssistantSuggestion] {
        let data = try await request(path: "/api/suggestions", method: "GET", auth: true)
        return try JSONDecoder().decode([AssistantSuggestion].self, from: data)
    }

    func updateSuggestion(id: String, status: String) async throws {
        let body = try JSONEncoder().encode(["status": status])
        _ = try await request(path: "/api/suggestions/\(id)", method: "PATCH", auth: true, body: body)
    }

    func chatHistory(conversationId: String?, limit: Int = 80) async throws -> [ChatTurn] {
        var path = "/api/chat/history?limit=\(max(1, min(80, limit)))"
        if let conversationId, !conversationId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            path += "&conversation_id=\(conversationId)"
        }
        let data = try await request(path: path, method: "GET", auth: true)
        return try JSONDecoder().decode([ChatTurn].self, from: data)
    }

    func chat(_ requestBody: ChatRequest) async throws -> ChatResponse {
        let body = try JSONEncoder().encode(requestBody)
        let data = try await request(path: "/api/chat", method: "POST", auth: true, body: body)
        return try JSONDecoder().decode(ChatResponse.self, from: data)
    }

    func registerDevice(
        deviceId: String,
        displayName: String,
        settings: NomiIslandSettings,
        apnsEnvironment: String = "sandbox",
        apnsDeviceToken: String = "",
        liveActivityPushToStartToken: String = ""
    ) async throws {
        let body = try Self.deviceRegistrationPayload(
            deviceId: deviceId,
            displayName: displayName,
            settings: settings,
            apnsEnvironment: apnsEnvironment,
            apnsDeviceToken: apnsDeviceToken,
            liveActivityPushToStartToken: liveActivityPushToStartToken
        )
        _ = try await request(path: "/api/ios/devices/register", method: "POST", auth: true, body: body)
    }

    func registerLiveActivity(deviceId: String, activityId: String, updateToken: String) async throws {
        let payload: [String: Any] = [
            "device_id": deviceId,
            "activity_id": activityId,
            "activity_kind": "nomi_status",
            "update_token": updateToken,
        ]
        let body = try JSONSerialization.data(withJSONObject: payload)
        _ = try await request(path: "/api/ios/live-activities/register", method: "POST", auth: true, body: body)
    }

    func updateDeviceSettings(deviceId: String, settings: NomiIslandSettings) async throws {
        let body = try JSONSerialization.data(withJSONObject: ["settings": try settings.asDictionary()])
        _ = try await request(path: "/api/ios/devices/\(deviceId)/settings", method: "PATCH", auth: true, body: body)
    }

    func openBrowser(source: String) async throws {
        let body = try Self.browserOpenPayload(source: source)
        _ = try await request(path: "/api/browser/open", method: "POST", auth: true, body: body)
    }

    func composioConnectURL(slug: String, force: Bool = false) async throws -> URL {
        let data = try await request(path: Self.composioConnectPath(slug: slug, force: force), method: "POST", auth: true)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let value = json?["url"] as? String
            ?? json?["connect_url"] as? String
            ?? json?["redirect_url"] as? String
            ?? json?["link"] as? String
            ?? ""
        guard let url = URL(string: value), !value.isEmpty else {
            throw URLError(.badURL)
        }
        return url
    }

    func taskDetail(taskId: String) async throws -> NomiTaskDetail {
        let data = try await request(path: "/api/agent-tasks/\(taskId)", method: "GET", auth: true)
        return try Self.decodeTaskDetail(data)
    }

    func taskEvents(taskId: String) async throws -> [NomiTaskEvent] {
        let data = try await request(path: "/api/agent-tasks/\(taskId)/events", method: "GET", auth: true)
        return try Self.decodeTaskEvents(data)
    }

    func resumeTask(taskId: String) async throws {
        _ = try await request(path: "/api/agent-tasks/\(taskId)/resume", method: "POST", auth: true)
    }

    func cancelTask(taskId: String) async throws {
        let body = try Self.taskCancelPayload("cancelled_from_ios")
        _ = try await request(path: "/api/agent-tasks/\(taskId)/cancel", method: "POST", auth: true, body: body)
    }

    func submitHumanInput(taskId: String, input: String) async throws {
        let body = try Self.taskHumanInputPayload(input)
        _ = try await request(path: "/api/agent-tasks/\(taskId)/human-input", method: "POST", auth: true, body: body)
    }

    func collectorsStatus() async throws -> [CollectorStatus] {
        async let collectorData = request(path: "/api/collectors/status", method: "GET", auth: true)
        async let readonlyToolkits = request(path: "/api/integrations/composio/toolkits?session_kind=readonly", method: "GET", auth: true)
        async let writeToolkits = request(path: "/api/integrations/composio/toolkits?session_kind=write", method: "GET", auth: true)
        let collectors = try Self.decodeCollectorsStatus(try await collectorData)
        let toolkits = try Self.decodeComposioToolkits(try await readonlyToolkits) + Self.decodeComposioToolkits(try await writeToolkits)
        return Self.mergeCollectorStatuses(collectors, with: toolkits)
    }

    func assistantIdentities() async throws -> [AssistantIdentity] {
        let data = try await request(path: "/api/assistant-identities", method: "GET", auth: true)
        return try Self.decodeAssistantIdentities(data)
    }

    func careerBoard(limit: Int = 50) async throws -> CareerBoard {
        let data = try await request(path: "/api/career/board?limit=\(limit)", method: "GET", auth: true)
        return try JSONDecoder().decode(CareerBoard.self, from: data)
    }

    func patchCareerApplication(applicationId: String, status: String?, stage: String?, nextStep: String? = nil, userNote: String?) async throws {
        let body = try Self.careerApplicationPatchPayload(status: status, stage: stage, nextStep: nextStep, userNote: userNote)
        _ = try await request(path: "/api/career/applications/\(applicationId)", method: "PATCH", auth: true, body: body)
    }

    func request(path: String, method: String, auth: Bool, body: Data? = nil) async throws -> Data {
        guard let url = URL(string: path, relativeTo: config.baseURL)?.absoluteURL else {
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "content-type")
        if auth {
            request.setValue(config.password, forHTTPHeaderField: "x-par-password")
        }
        request.httpBody = body
        let (data, response) = try await session.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            throw URLError(.badServerResponse)
        }
        return data
    }

    private static func firstNonEmpty(_ values: Any?...) -> String? {
        for value in values {
            let text: String
            if let value = value as? String {
                text = value
            } else if let value {
                text = String(describing: value)
            } else {
                continue
            }
            let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty {
                return trimmed
            }
        }
        return nil
    }

    private static func sourceForComposioToolkit(_ slug: String) -> String? {
        switch slug.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "gmail":
            return "gmail"
        case "googlecalendar":
            return "calendar"
        case "googledrive":
            return "googledrive"
        case "googledocs":
            return "googledocs"
        case "googlesheets":
            return "googlesheets"
        case "googletasks":
            return "googletasks"
        case "github", "slack", "notion", "google_maps", "linear", "jira", "todoist":
            return slug.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        default:
            return nil
        }
    }
}
