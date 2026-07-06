import XCTest
@testable import Nomi

final class NomiRealtimeClientTests: XCTestCase {
    func testBuildsWebSocketUrlFromServerConfig() throws {
        let http = try ServerConfig.normalize(baseURL: "http://example.com", password: "secret value")
        let https = try ServerConfig.normalize(baseURL: "https://example.com", password: "secret")

        XCTAssertEqual(NomiRealtimeClient.webSocketURL(config: http).absoluteString, "ws://example.com/ws?password=secret%20value")
        XCTAssertEqual(NomiRealtimeClient.webSocketURL(config: https).absoluteString, "wss://example.com/ws?password=secret")
    }

    func testBuildsChatPayloadWithLiveActivityFields() throws {
        let data = try NomiRealtimeClient.chatMessagePayload(
            message: "Continue",
            conversationId: "conversation-1",
            limit: 24,
            clientRequestId: "ios-request-1",
            liveActivityId: "activity-1",
            streamToLiveActivity: true
        )
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]

        XCTAssertEqual(json?["type"] as? String, "chat_message")
        XCTAssertEqual(json?["client_type"] as? String, "ios")
        XCTAssertEqual(json?["message"] as? String, "Continue")
        XCTAssertEqual(json?["conversation_id"] as? String, "conversation-1")
        XCTAssertEqual(json?["client_request_id"] as? String, "ios-request-1")
        XCTAssertEqual(json?["ios_live_activity_id"] as? String, "activity-1")
        XCTAssertEqual(json?["ios_stream_to_live_activity"] as? Bool, true)
        XCTAssertEqual(json?["limit"] as? Int, 24)
    }

    func testParseChatDelta() throws {
        let data = #"{"type":"chat_delta","delta":"you","elapsed_ms":120}"#.data(using: .utf8)!
        let event = try NomiRealtimeParser.parse(data)

        XCTAssertEqual(event, .chatDelta(delta: "you", elapsedMs: 120))
    }

    func testParseProactiveMessageUsesSuggestionId() throws {
        let data = #"{"type":"proactive_message","id":"fallback","suggestion_id":"s1","title":"Worth reviewing","body":"Customer asked about quote deadline","source":"whatsapp"}"#.data(using: .utf8)!
        let event = try NomiRealtimeParser.parse(data)

        XCTAssertEqual(event, .proactiveMessage(id: "s1", title: "Worth reviewing", body: "Customer asked about quote deadline", source: "whatsapp"))
    }

    func testParseAgentTaskDeliveryKeepsEventIdTaskIdAndRawJson() throws {
        let json = #"{"type":"agent_task_delivery","event_id":"event-1","task_id":"task-1","delivery":{"message":"Draft is ready"}}"#
        let event = try NomiRealtimeParser.parse(Data(json.utf8))

        XCTAssertEqual(
            event,
            .agentTaskDelivery(eventId: "event-1", taskId: "task-1", body: "Draft is ready", rawJSON: json)
        )
    }

    func testParseAgentTaskFallbackReadsTopLevelActionCard() throws {
        let json = #"{"type":"agent_task_fallback","event_id":"event-2","task_id":"task-2","action_card":{"title":"Need approval","message":"Confirm sending email"}}"#
        let event = try NomiRealtimeParser.parse(Data(json.utf8))

        XCTAssertEqual(
            event,
            .agentTaskFallback(eventId: "event-2", taskId: "task-2", title: "Need approval", body: "Confirm sending email", rawJSON: json)
        )
    }

    func testChatSendPipelineReturnsServerMessageAndLiveActivityChunks() async throws {
        var settings = NomiIslandSettings()
        settings.tokenLevelChatStreamingEnabled = true
        settings.tokenLevelChatDelivery = .localAndApnsBestEffort
        settings.sensitiveApnsPayloadEnabled = true
        let client = FakeChatClient(response: ChatResponse(answer: "Alpha beta gamma", conversation_id: "conversation-1"))

        let result = try await NomiChatSendPipeline.send(
            message: "Hello",
            conversationId: nil,
            client: client,
            settings: settings,
            liveActivityId: "activity-1"
        )

        XCTAssertEqual(result.messages, [
            NomiChatMessage(role: .user, text: "Hello"),
            NomiChatMessage(role: .assistant, text: "Alpha beta gamma"),
        ])
        XCTAssertEqual(result.conversationId, "conversation-1")
        XCTAssertEqual(result.liveActivityDeltas.map(\.text), ["Alpha ", "beta ", "gamma"])
        XCTAssertEqual(result.liveActivityDeltas.map(\.resetStream), [true, false, false])
        XCTAssertTrue(client.lastRequest?.client_request_id?.hasPrefix("ios-chat-") == true)
    }

    func testChatSendPipelineIncludesContextDeltaWithoutCurrentMessage() async throws {
        let client = FakeChatClient(response: ChatResponse(answer: "Done", conversation_id: "conversation-1"))
        let context = [
            NomiChatMessage(role: .user, text: "Earlier question"),
            NomiChatMessage(role: .assistant, text: "Earlier answer"),
            NomiChatMessage(role: .user, text: "Current message should not duplicate"),
        ]

        _ = try await NomiChatSendPipeline.send(
            message: "Current message should not duplicate",
            conversationId: "conversation-1",
            client: client,
            settings: NomiIslandSettings(),
            liveActivityId: nil,
            contextMessages: context
        )

        XCTAssertEqual(client.lastRequest?.client_context_delta, [
            ChatTurn(role: "user", content: "Earlier question"),
            ChatTurn(role: "assistant", content: "Earlier answer"),
        ])
    }

    func testChatSendPipelineResetsLiveActivityStreamForEachSend() async throws {
        var settings = NomiIslandSettings()
        settings.tokenLevelChatStreamingEnabled = true
        settings.tokenLevelChatDelivery = .localAndApnsBestEffort
        settings.sensitiveApnsPayloadEnabled = true
        let client = FakeChatClient(response: ChatResponse(answer: "One two", conversation_id: "conversation-1"))

        let first = try await NomiChatSendPipeline.send(
            message: "First",
            conversationId: "conversation-1",
            client: client,
            settings: settings,
            liveActivityId: "activity-1"
        )
        let second = try await NomiChatSendPipeline.send(
            message: "Second",
            conversationId: "conversation-1",
            client: client,
            settings: settings,
            liveActivityId: "activity-1"
        )

        XCTAssertEqual(first.liveActivityDeltas.map(\.resetStream), [true, false])
        XCTAssertEqual(second.liveActivityDeltas.map(\.resetStream), [true, false])
    }

    func testChatSendPipelineRequiresConfiguredServer() async {
        await XCTAssertThrowsErrorAsync(
            _ = try await NomiChatSendPipeline.send(
                message: "Hello",
                conversationId: nil,
                client: nil,
                settings: NomiIslandSettings(),
                liveActivityId: nil
            )
        ) { error in
            XCTAssertEqual(error as? NomiChatSendError, .serverNotConfigured)
        }
    }

    private final class FakeChatClient: NomiChatClient {
        let response: ChatResponse
        private(set) var lastRequest: ChatRequest?

        init(response: ChatResponse) {
            self.response = response
        }

        func chat(_ requestBody: ChatRequest) async throws -> ChatResponse {
            lastRequest = requestBody
            return response
        }
    }
}

private func XCTAssertThrowsErrorAsync(
    _ expression: @autoclosure () async throws -> Void,
    _ errorHandler: (Error) -> Void,
    file: StaticString = #filePath,
    line: UInt = #line
) async {
    do {
        try await expression()
        XCTFail("Expected error", file: file, line: line)
    } catch {
        errorHandler(error)
    }
}
