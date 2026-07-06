import AppIntents
import Foundation

struct MarkSuggestionDoneIntent: AppIntent {
    static var title: LocalizedStringResource = "Mark Nomi suggestion done"
    static var description = IntentDescription("Marks a proactive Nomi suggestion as done.")

    @Parameter(title: "Suggestion ID")
    var suggestionId: String

    init() {
        self.suggestionId = ""
    }

    init(suggestionId: String) {
        self.suggestionId = suggestionId
    }

    func perform() async throws -> some IntentResult {
        let config = try NomiKeychain.loadServerConfig()
        let client = NomiApiClient(config: config)
        try await client.updateSuggestion(id: suggestionId, status: "done")
        return .result()
    }
}

struct DismissSuggestionIntent: AppIntent {
    static var title: LocalizedStringResource = "Dismiss Nomi suggestion"
    static var description = IntentDescription("Dismisses a proactive Nomi suggestion.")

    @Parameter(title: "Suggestion ID")
    var suggestionId: String

    init() {
        self.suggestionId = ""
    }

    init(suggestionId: String) {
        self.suggestionId = suggestionId
    }

    func perform() async throws -> some IntentResult {
        let config = try NomiKeychain.loadServerConfig()
        let client = NomiApiClient(config: config)
        try await client.updateSuggestion(id: suggestionId, status: "dismissed")
        return .result()
    }
}
