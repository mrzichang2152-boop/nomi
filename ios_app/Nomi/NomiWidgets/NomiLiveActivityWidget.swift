import ActivityKit
import AppIntents
import SwiftUI
import WidgetKit

struct NomiLiveActivityWidget: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: NomiLiveActivityAttributes.self) { context in
            LockScreenLiveActivityView(state: context.state)
                .activityBackgroundTint(Color.black)
                .activitySystemActionForegroundColor(Color.white)
                .widgetURL(context.state.deepLinkURL)
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    Text(context.state.dynamicIslandLeadingBadge)
                        .font(.caption2.weight(.bold))
                        .foregroundStyle(.white)
                        .frame(width: 20, height: 20)
                        .background(.white.opacity(0.16))
                        .clipShape(Circle())
                        .padding(.leading, 10)
                        .widgetURL(context.state.deepLinkURL)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    Text(context.state.dynamicIslandCompactTrailing)
                        .font(.caption.weight(.bold))
                        .foregroundStyle(.white)
                        .frame(minWidth: 20, minHeight: 20)
                        .padding(.horizontal, 6)
                        .background(.white.opacity(0.14))
                        .clipShape(Capsule())
                        .padding(.trailing, 8)
                        .widgetURL(context.state.deepLinkURL)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    VStack(alignment: .leading, spacing: 5) {
                        HStack(spacing: 6) {
                            Text("Nomi")
                                .font(.caption2.weight(.semibold))
                            Text(context.state.dynamicIslandSourceLabel)
                                .font(.caption2.weight(.medium))
                                .foregroundStyle(.secondary)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(.white.opacity(0.12))
                                .clipShape(Capsule())
                            Spacer(minLength: 0)
                        }
                        Text(context.state.dynamicIslandHeadline)
                            .font(.caption.weight(.semibold))
                            .lineLimit(1)
                            .minimumScaleFactor(0.82)
                        Text(context.state.dynamicIslandDetail)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                            .multilineTextAlignment(.leading)
                            .minimumScaleFactor(0.86)
                        if !context.state.suggestionId.isEmpty {
                            HStack(spacing: 8) {
                                Button(intent: MarkSuggestionDoneIntent(suggestionId: context.state.suggestionId)) {
                                    Text("Done")
                                }
                                Button(intent: DismissSuggestionIntent(suggestionId: context.state.suggestionId)) {
                                    Text("Dismiss")
                                }
                            }
                            .font(.caption2)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 10)
                    .padding(.bottom, 2)
                    .widgetURL(context.state.deepLinkURL)
                }
            } compactLeading: {
                Text(context.state.dynamicIslandLeadingBadge)
                    .font(.caption.weight(.bold))
                    .widgetURL(context.state.deepLinkURL)
            } compactTrailing: {
                Text(context.state.dynamicIslandCompactTrailing)
                    .font(.caption2)
                    .widgetURL(context.state.deepLinkURL)
            } minimal: {
                Text(context.state.dynamicIslandLeadingBadge)
                    .font(.caption2.weight(.bold))
                    .widgetURL(context.state.deepLinkURL)
            }
        }
    }
}

private func displayBody(_ state: NomiLiveActivityAttributes.ContentState) -> String {
    if state.phase == "chat_streaming", !state.partialAnswer.isEmpty {
        return state.partialAnswer
    }
    if let raw = state.privateContext?.rawSnippet, !raw.isEmpty {
        return raw
    }
    return state.body
}

private struct LockScreenLiveActivityView: View {
    let state: NomiLiveActivityAttributes.ContentState

    var body: some View {
        HStack(spacing: 12) {
            Text("N")
                .font(.headline.weight(.bold))
                .frame(width: 32, height: 32)
                .background(.white.opacity(0.16))
                .clipShape(Circle())
            VStack(alignment: .leading, spacing: 3) {
                Text(state.title)
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(1)
                Text(displayBody(state))
                    .font(.caption)
                    .lineLimit(2)
            }
            Spacer()
        }
        .padding(12)
    }
}
