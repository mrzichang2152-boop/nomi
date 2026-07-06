import SwiftUI

protocol NomiSuggestionClient {
    func suggestions() async throws -> [AssistantSuggestion]
    func updateSuggestion(id: String, status: String) async throws
}

extension NomiApiClient: NomiSuggestionClient {}

struct SuggestionListView: View {
    let route: NomiRoute?
    let client: (any NomiSuggestionClient)?
    let realtimeSuggestions: [AssistantSuggestion]
    @State private var suggestions: [AssistantSuggestion] = []
    @State private var hiddenSuggestionIds: Set<String> = []
    @State private var statusMessage = "Suggestions not loaded"
    @State private var isLoading = false

    init(route: NomiRoute?, client: (any NomiSuggestionClient)? = nil, realtimeSuggestions: [AssistantSuggestion] = []) {
        self.route = route
        self.client = client
        self.realtimeSuggestions = realtimeSuggestions
    }

    var body: some View {
        List {
            Section("Suggestions") {
                if displayedSuggestions.isEmpty {
                    Text(emptyText)
                        .foregroundStyle(.secondary)
                }
                ForEach(displayedSuggestions) { suggestion in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(suggestion.title)
                            .font(.headline)
                        Text(suggestion.body)
                            .foregroundStyle(.secondary)
                        HStack {
                            Button("完成") {
                                Task { await update(suggestion, status: "done") }
                            }
                            Button("忽略", role: .destructive) {
                                Task { await update(suggestion, status: "dismissed") }
                            }
                        }
                        .buttonStyle(.borderless)
                    }
                    .padding(.vertical, 4)
                    .listRowBackground(suggestion.id == focusedSuggestionId ? Color.accentColor.opacity(0.12) : nil)
                }
            }
            Section {
                if isLoading {
                    ProgressView()
                }
                Text(routeDescription)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                Text(statusMessage)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                Button("Refresh") {
                    Task { await load() }
                }
            }
        }
        .task {
            await load()
        }
    }

    private var routeDescription: String {
        switch route {
        case let .suggestion(id):
            return "Suggestion \(id)"
        case let .task(id, _):
            return "Task \(id)"
        case let .careerOpportunity(id):
            return "Career opportunity \(id)"
        default:
            return "No deep link selected"
        }
    }

    private var focusedSuggestionId: String? {
        if case let .suggestion(id) = route {
            return id
        }
        return nil
    }

    private var emptyText: String {
        client == nil ? "Configure a Nomi server to load proactive suggestions." : "暂无建议"
    }

    @MainActor
    private func load() async {
        guard let client else {
            statusMessage = "Server not configured"
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            suggestions = try await client.suggestions()
            statusMessage = "Suggestions loaded"
        } catch is CancellationError {
            return
        } catch {
            statusMessage = "无法读取建议：\(error.localizedDescription)"
        }
    }

    @MainActor
    private func update(_ suggestion: AssistantSuggestion, status: String) async {
        guard let client else {
            statusMessage = "Server not configured"
            return
        }
        do {
            try await client.updateSuggestion(id: suggestion.id, status: status)
            suggestions.removeAll { $0.id == suggestion.id }
            hiddenSuggestionIds.insert(suggestion.id)
            statusMessage = "Suggestion \(status)"
        } catch {
            statusMessage = "Suggestion update failed: \(error.localizedDescription)"
        }
    }

    private var displayedSuggestions: [AssistantSuggestion] {
        var seen: Set<String> = []
        var merged: [AssistantSuggestion] = []
        for suggestion in realtimeSuggestions + suggestions where !hiddenSuggestionIds.contains(suggestion.id) && !seen.contains(suggestion.id) {
            seen.insert(suggestion.id)
            merged.append(suggestion)
        }
        return merged
    }
}
