import Foundation

final class NomiRealtimeClient {
    private let config: ServerConfig
    private let session: URLSession
    private var task: URLSessionWebSocketTask?
    private var onEvent: ((NomiRealtimeEvent) -> Void)?

    init(config: ServerConfig, session: URLSession = .shared) {
        self.config = config
        self.session = session
    }

    static func webSocketURL(config: ServerConfig) -> URL {
        var components = URLComponents(url: config.baseURL, resolvingAgainstBaseURL: false) ?? URLComponents()
        components.scheme = config.baseURL.scheme?.lowercased() == "https" ? "wss" : "ws"
        components.path = "/ws"
        components.queryItems = [URLQueryItem(name: "password", value: config.password)]
        return components.url ?? config.baseURL
    }

    static func chatMessagePayload(
        message: String,
        conversationId: String?,
        limit: Int,
        clientRequestId: String?,
        liveActivityId: String?,
        streamToLiveActivity: Bool
    ) throws -> Data {
        var payload: [String: Any] = [
            "type": "chat_message",
            "message": message,
            "limit": max(1, min(80, limit)),
            "client_type": "ios",
            "ios_stream_to_live_activity": streamToLiveActivity,
        ]
        if let conversationId, !conversationId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            payload["conversation_id"] = conversationId
        }
        if let clientRequestId, !clientRequestId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            payload["client_request_id"] = clientRequestId
        }
        if let liveActivityId, !liveActivityId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            payload["ios_live_activity_id"] = liveActivityId
        }
        return try JSONSerialization.data(withJSONObject: payload)
    }

    func connect(onEvent: @escaping (NomiRealtimeEvent) -> Void) {
        self.onEvent = onEvent
        let task = session.webSocketTask(with: Self.webSocketURL(config: config))
        self.task = task
        task.resume()
        receiveNext()
    }

    func sendChat(
        message: String,
        conversationId: String?,
        limit: Int,
        clientRequestId: String?,
        liveActivityId: String?,
        streamToLiveActivity: Bool
    ) throws {
        let data = try Self.chatMessagePayload(
            message: message,
            conversationId: conversationId,
            limit: limit,
            clientRequestId: clientRequestId,
            liveActivityId: liveActivityId,
            streamToLiveActivity: streamToLiveActivity
        )
        let text = String(decoding: data, as: UTF8.self)
        task?.send(.string(text)) { [weak self] error in
            if let error {
                self?.onEvent?(.error(message: error.localizedDescription))
            }
        }
    }

    func disconnect() {
        task?.cancel(with: .normalClosure, reason: nil)
        task = nil
    }

    private func receiveNext() {
        task?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case let .success(message):
                do {
                    let data: Data
                    switch message {
                    case let .string(text):
                        data = Data(text.utf8)
                    case let .data(raw):
                        data = raw
                    @unknown default:
                        data = Data()
                    }
                    let event = try NomiRealtimeParser.parse(data)
                    DispatchQueue.main.async {
                        self.onEvent?(event)
                    }
                } catch {
                    DispatchQueue.main.async {
                        self.onEvent?(.error(message: error.localizedDescription))
                    }
                }
                self.receiveNext()
            case let .failure(error):
                DispatchQueue.main.async {
                    self.onEvent?(.error(message: error.localizedDescription))
                }
            }
        }
    }
}

enum NomiRealtimeEvent: Equatable {
    case proactiveMessage(id: String, title: String, body: String, source: String)
    case agentTaskDelivery(eventId: String, taskId: String, body: String, rawJSON: String)
    case agentTaskFallback(eventId: String, taskId: String, title: String, body: String, rawJSON: String)
    case chatDelta(delta: String, elapsedMs: Int)
    case chatDone(answer: String, conversationId: String)
    case error(message: String)
    case ignored
}

struct NomiRealtimeParser {
    static func parse(_ data: Data) throws -> NomiRealtimeEvent {
        let rawJSON = String(decoding: data, as: UTF8.self)
        let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let type = object?["type"] as? String ?? ""
        switch type {
        case "proactive_message":
            return .proactiveMessage(
                id: object?["suggestion_id"] as? String ?? object?["id"] as? String ?? "",
                title: object?["title"] as? String ?? "",
                body: object?["body"] as? String ?? "",
                source: object?["source"] as? String ?? ""
            )
        case "agent_task_delivery":
            let delivery = object?["delivery"] as? [String: Any]
            return .agentTaskDelivery(
                eventId: object?["event_id"] as? String ?? "",
                taskId: object?["task_id"] as? String ?? "",
                body: delivery?["message"] as? String ?? "Long-tail task has a new delivery.",
                rawJSON: rawJSON
            )
        case "agent_task_fallback":
            let fallback = object?["fallback_decision"] as? [String: Any]
            let actionCard = object?["action_card"] as? [String: Any] ?? fallback?["action_card"] as? [String: Any]
            return .agentTaskFallback(
                eventId: object?["event_id"] as? String ?? "",
                taskId: object?["task_id"] as? String ?? "",
                title: actionCard?["title"] as? String ?? "Task needs attention",
                body: actionCard?["message"] as? String ?? "Open Nomi to review the next step.",
                rawJSON: rawJSON
            )
        case "chat_delta":
            return .chatDelta(delta: object?["delta"] as? String ?? "", elapsedMs: object?["elapsed_ms"] as? Int ?? -1)
        case "chat_done":
            return .chatDone(answer: object?["answer"] as? String ?? "", conversationId: object?["conversation_id"] as? String ?? "")
        case "error":
            return .error(message: object?["message"] as? String ?? "Realtime error")
        default:
            return .ignored
        }
    }
}
