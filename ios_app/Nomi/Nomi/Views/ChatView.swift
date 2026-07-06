import SwiftUI

enum NomiChatRole: String {
    case user
    case assistant
}

struct NomiChatMessage: Identifiable, Equatable {
    let id: UUID
    var role: NomiChatRole
    var text: String

    init(id: UUID = UUID(), role: NomiChatRole, text: String) {
        self.id = id
        self.role = role
        self.text = text
    }

    static func == (lhs: NomiChatMessage, rhs: NomiChatMessage) -> Bool {
        lhs.role == rhs.role && lhs.text == rhs.text
    }
}

struct NomiChatLiveActivityDelta: Equatable {
    var text: String
    var conversationId: String
    var includeText: Bool
    var resetStream: Bool = false
}

struct NomiChatSendResult: Equatable {
    var messages: [NomiChatMessage]
    var conversationId: String
    var liveActivityDeltas: [NomiChatLiveActivityDelta]
}

enum NomiChatSendError: Error, Equatable, LocalizedError {
    case emptyMessage
    case serverNotConfigured

    var errorDescription: String? {
        switch self {
        case .emptyMessage:
            return "Message is empty"
        case .serverNotConfigured:
            return "Server not configured"
        }
    }
}

protocol NomiChatClient {
    func chat(_ requestBody: ChatRequest) async throws -> ChatResponse
}

extension NomiApiClient: NomiChatClient {}

enum NomiChatSendPipeline {
    static func send(
        message: String,
        conversationId: String?,
        client: (any NomiChatClient)?,
        settings: NomiIslandSettings,
        liveActivityId: String?,
        contextMessages: [NomiChatMessage] = []
    ) async throws -> NomiChatSendResult {
        let cleanMessage = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanMessage.isEmpty else { throw NomiChatSendError.emptyMessage }
        guard let client else { throw NomiChatSendError.serverNotConfigured }

        let contextDelta = clientContextDelta(from: contextMessages, currentMessage: cleanMessage)
        let request = ChatRequest(
            message: cleanMessage,
            conversation_id: conversationId,
            client_request_id: "ios-chat-\(UUID().uuidString)",
            client_context_delta: contextDelta
        )
        let response = try await client.chat(request)
        return NomiChatSendResult(
            messages: [
                NomiChatMessage(role: .user, text: cleanMessage),
                NomiChatMessage(role: .assistant, text: response.answer),
            ],
            conversationId: response.conversation_id,
            liveActivityDeltas: liveActivityDeltas(
                answer: response.answer,
                conversationId: response.conversation_id,
                settings: settings,
                liveActivityId: liveActivityId
            )
        )
    }

    private static func liveActivityDeltas(
        answer: String,
        conversationId: String,
        settings: NomiIslandSettings,
        liveActivityId: String?
    ) -> [NomiChatLiveActivityDelta] {
        guard liveActivityId != nil else { return [] }
        guard settings.tokenLevelChatStreamingEnabled else { return [] }
        guard settings.tokenLevelChatDelivery != .apnsBestEffort else { return [] }
        return tokenChunks(answer).enumerated().map { index, chunk in
            NomiChatLiveActivityDelta(
                text: chunk,
                conversationId: conversationId,
                includeText: settings.sensitiveApnsPayloadEnabled,
                resetStream: index == 0
            )
        }
    }

    private static func tokenChunks(_ answer: String) -> [String] {
        let parts = answer.split(separator: " ", omittingEmptySubsequences: false)
        guard parts.count > 1 else { return answer.isEmpty ? [] : [answer] }
        return parts.enumerated().map { index, part in
            index == parts.count - 1 ? String(part) : "\(part) "
        }.filter { !$0.isEmpty }
    }

    private static func clientContextDelta(from messages: [NomiChatMessage], currentMessage: String) -> [ChatTurn] {
        var source = messages
        if let last = source.last, last.role == .user, last.text == currentMessage {
            source.removeLast()
        }
        var result: [ChatTurn] = []
        var usedCharacters = 0
        for message in source.reversed() {
            let text = message.text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else { continue }
            let nextCount = usedCharacters + text.count
            if nextCount > 12_000, !result.isEmpty {
                break
            }
            usedCharacters = nextCount
            result.append(ChatTurn(role: message.role.rawValue, content: text))
        }
        return result.reversed()
    }
}

enum NomiChatComposerFocusPolicy {
    static let shouldFocusComposerOnAppear = true
    static let shouldRestoreFocusAfterSend = true
}

struct ChatView: View {
    let route: NomiRoute?
    var client: (any NomiChatClient)?
    var settings: NomiIslandSettings = NomiIslandSettings()
    var liveActivityId: String?
    var updateLiveActivity: (NomiChatLiveActivityDelta) async -> Void = { _ in }
    @State private var draft = ""
    @State private var conversationId: String?
    @State private var messages: [NomiChatMessage] = []
    @State private var statusMessage = "Private-cloud assistant chat"
    @State private var isSending = false
    @FocusState private var isComposerFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            if showsRouteDescription {
                Text(routeDescription)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 4)
                    .padding(.bottom, 6)
            }
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        if messages.isEmpty {
                            emptyState
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.top, 12)
                        }
                        ForEach(messages) { message in
                            messageBubble(message)
                                .id(message.id)
                        }
                    }
                    .padding(.top, 8)
                    .padding(.bottom, 12)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .onChange(of: messages.count) { _, _ in
                    scrollToLatestMessage(using: proxy)
                }
            }
            composer
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear {
            syncConversationFromRoute()
            focusComposerSoon()
        }
        .onChange(of: route) { _, _ in
            syncConversationFromRoute()
            focusComposerSoon()
        }
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Ask Nomi")
                .font(.headline)
            Text("What should Nomi help with next?")
                .font(.callout)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 10)
    }

    private var composer: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .bottom, spacing: 8) {
                TextField("Ask Nomi", text: $draft, axis: .vertical)
                    .lineLimit(1...4)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(Color(uiColor: .secondarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                    .disabled(isSending)
                    .focused($isComposerFocused)
                    .submitLabel(.send)
                    .onSubmit {
                        Task { await sendDraft() }
                    }
                Button {
                    Task { await sendDraft() }
                } label: {
                    Image(systemName: "paperplane.fill")
                        .font(.headline)
                        .frame(width: 22, height: 22)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(isSending || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .accessibilityLabel("Send")
            }
            if let visibleStatus {
                Text(visibleStatus)
                    .font(.footnote)
                    .foregroundStyle(isSending ? Color.secondary : Color.red)
            }
        }
        .padding(.vertical, 8)
        .background(Color(uiColor: .systemBackground))
    }

    private func messageBubble(_ message: NomiChatMessage) -> some View {
        HStack {
            if message.role == .user {
                Spacer(minLength: 48)
            }
            VStack(alignment: .leading, spacing: 4) {
                Text(message.role == .user ? "You" : "Nomi")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(message.text)
                    .font(.body)
                    .textSelection(.enabled)
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(message.role == .user ? Color.accentColor.opacity(0.14) : Color.secondary.opacity(0.10))
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            if message.role == .assistant {
                Spacer(minLength: 32)
            }
        }
    }

    private var routeDescription: String {
        if case let .chat(conversationId) = route, let conversationId {
            return "Conversation \(conversationId)"
        }
        return "Private-cloud assistant chat"
    }

    private var showsRouteDescription: Bool {
        if case let .chat(conversationId) = route, conversationId != nil {
            return true
        }
        return false
    }

    private var visibleStatus: String? {
        if isSending {
            return "Sending"
        }
        if statusMessage == "Sent" || statusMessage == "Private-cloud assistant chat" {
            return nil
        }
        return statusMessage
    }

    private func syncConversationFromRoute() {
        if case let .chat(routeConversationId) = route, let routeConversationId {
            conversationId = routeConversationId
        }
    }

    private func focusComposerSoon() {
        guard NomiChatComposerFocusPolicy.shouldFocusComposerOnAppear else { return }
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 250_000_000)
            isComposerFocused = true
        }
    }

    private func scrollToLatestMessage(using proxy: ScrollViewProxy) {
        guard let id = messages.last?.id else { return }
        withAnimation(.easeOut(duration: 0.18)) {
            proxy.scrollTo(id, anchor: .bottom)
        }
    }

    @MainActor
    private func sendDraft() async {
        let message = draft
        draft = ""
        isSending = true
        statusMessage = "Sending"
        do {
            let result = try await NomiChatSendPipeline.send(
                message: message,
                conversationId: conversationId,
                client: client,
                settings: settings,
                liveActivityId: liveActivityId,
                contextMessages: messages
            )
            messages.append(contentsOf: result.messages)
            conversationId = result.conversationId
            for delta in result.liveActivityDeltas {
                await updateLiveActivity(delta)
            }
            statusMessage = "Sent"
            if NomiChatComposerFocusPolicy.shouldRestoreFocusAfterSend {
                isComposerFocused = true
            }
        } catch {
            draft = message
            statusMessage = error.localizedDescription
            isComposerFocused = true
        }
        isSending = false
    }
}
