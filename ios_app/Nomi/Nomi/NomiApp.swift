import SwiftUI
import UIKit
import UserNotifications
import WebKit

@main
struct NomiApp: App {
    @UIApplicationDelegateAdaptor(NomiAppDelegate.self) private var appDelegate
    @StateObject private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(appState)
                .onOpenURL { url in
                    appState.handle(url: url)
                }
        }
    }
}

private struct RootView: View {
    @EnvironmentObject private var appState: AppState
    @StateObject private var liveActivityController = NomiLiveActivityController()
    @State private var liveActivityStatus = "Not started"
    @State private var realtimeClient: NomiRealtimeClient?

    var body: some View {
        NomiWorkbenchView(
            selectedMode: $appState.selectedMode,
            route: appState.route,
            client: appState.apiClientForCurrentServer(),
            serverStatus: appState.serverConfigStatus,
            realtimeSuggestions: appState.suggestionStore.suggestions,
            taskCards: appState.taskStore.cards,
            settings: $appState.islandSettings,
            liveActivityId: liveActivityController.activityId,
            liveActivityStatus: liveActivityStatus,
            updateLiveActivity: { delta in
                await liveActivityController.updateFromChatDelta(
                    delta.text,
                    conversationId: delta.conversationId,
                    includeText: delta.includeText,
                    deepLinksEnabled: appState.islandSettings.deepLinksEnabled,
                    resetStream: delta.resetStream
                )
            },
            startLiveActivity: {
                Task { await startLiveActivity(preview: false) }
            },
            previewLiveActivity: {
                Task { await startLiveActivity(preview: true) }
            },
            stopLiveActivity: {
                Task { await stopLiveActivity() }
            },
            notificationStatus: appState.notificationRegistrationStatus,
            requestNotifications: {
                Task { await requestNotifications() }
            },
            serverBaseURL: $appState.serverBaseURLInput,
            serverPassword: $appState.serverPasswordInput,
            saveServerConfig: {
                saveServerConfig()
            }
        )
        .task {
            await startLiveActivity(preview: false)
        }
        .task(id: realtimeConnectionKey) {
            startRealtime()
        }
        .onChange(of: appState.islandSettings) { _, _ in
            appState.persistIslandSettings()
            Task { await appState.syncIslandSettings() }
        }
        .onChange(of: appState.islandSettings.liveActivityEnabled) { _, enabled in
            Task {
                if enabled {
                    await startLiveActivity(preview: false)
                } else {
                    await stopLiveActivity()
                }
            }
        }
        .onChange(of: appState.islandSettings.deepLinksEnabled) { _, enabled in
            Task { await liveActivityController.refreshDeepLinkPreference(enabled: enabled) }
        }
    }

    @MainActor
    private func startLiveActivity(preview: Bool) async {
        do {
            let result = try await NomiLiveActivityStartup.startIfNeeded(
                settings: appState.islandSettings,
                deviceId: appState.liveActivityDeviceId,
                apiClient: appState.apiClientForCurrentServer(),
                controller: liveActivityController
            )
            switch result {
            case .disabled:
                liveActivityStatus = "Disabled"
            case let .started(activityId):
                liveActivityStatus = "Active \(activityId.prefix(8))"
            case let .alreadyActive(activityId):
                liveActivityStatus = "Active \(activityId.prefix(8))"
            }
            if preview {
                await liveActivityController.updateFromChatDelta(
                    "Local Dynamic Island preview",
                    conversationId: "simulator-preview",
                    includeText: true,
                    deepLinksEnabled: appState.islandSettings.deepLinksEnabled,
                    resetStream: true
                )
                liveActivityStatus = "Preview sent"
            }
        } catch {
            liveActivityStatus = "Unavailable: \(error.localizedDescription)"
        }
    }

    @MainActor
    private func stopLiveActivity() async {
        await liveActivityController.end()
        liveActivityStatus = "Stopped"
    }

    @MainActor
    private func saveServerConfig() {
        do {
            try appState.saveServerConfig(
                baseURL: appState.serverBaseURLInput,
                password: appState.serverPasswordInput
            )
            Task { await appState.registerCurrentDevice() }
        } catch {
            appState.serverConfigStatus = "Server save failed: \(error.localizedDescription)"
        }
    }

    @MainActor
    private func requestNotifications() async {
        let permission = await NomiNotificationRegistrar.requestAuthorizationAndRegister()
        appState.updateNotificationPermission(permission)
        await appState.registerCurrentDevice()
    }

    private var realtimeConnectionKey: String {
        guard let config = appState.serverConfig else { return "" }
        return "\(config.baseURL.absoluteString)|\(config.password)"
    }

    @MainActor
    private func startRealtime() {
        realtimeClient?.disconnect()
        guard let config = appState.serverConfig else { return }
        let client = NomiRealtimeClient(config: config)
        realtimeClient = client
        client.connect { event in
            Task { @MainActor in
                appState.handleRealtimeEvent(event)
                await updateLiveActivity(from: event)
            }
        }
    }

    @MainActor
    private func updateLiveActivity(from event: NomiRealtimeEvent) async {
        switch event {
        case let .proactiveMessage(id, title, body, source):
            await liveActivityController.updateFromProactive(
                title: title,
                body: body,
                source: source,
                suggestionId: id,
                unreadCount: appState.suggestionStore.unreadCount,
                includeSensitiveText: appState.islandSettings.sensitiveApnsPayloadEnabled,
                deepLinksEnabled: appState.islandSettings.deepLinksEnabled
            )
        case let .agentTaskDelivery(_, taskId, body, _):
            await liveActivityController.updateFromTask(
                phase: "task_delivery",
                title: "长尾任务完成",
                body: body,
                taskId: taskId,
                unreadCount: appState.taskStore.unreadCount,
                includeSensitiveText: appState.islandSettings.sensitiveApnsPayloadEnabled,
                deepLinksEnabled: appState.islandSettings.deepLinksEnabled
            )
        case let .agentTaskFallback(_, taskId, title, body, _):
            await liveActivityController.updateFromTask(
                phase: "task_delivery",
                title: title,
                body: body,
                taskId: taskId,
                unreadCount: appState.taskStore.unreadCount,
                includeSensitiveText: appState.islandSettings.sensitiveApnsPayloadEnabled,
                deepLinksEnabled: appState.islandSettings.deepLinksEnabled
            )
        case .chatDelta, .chatDone, .error, .ignored:
            break
        }
    }
}

final class NomiAppDelegate: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        NotificationCenter.default.post(
            name: .nomiAPNsDeviceTokenDidRegister,
            object: nil,
            userInfo: ["token": NomiLiveActivityController.hexToken(deviceToken)]
        )
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        NotificationCenter.default.post(
            name: .nomiAPNsDeviceTokenDidRegister,
            object: nil,
            userInfo: ["token": ""]
        )
    }
}

enum NomiNotificationRegistrar {
    @MainActor
    static func requestAuthorizationAndRegister() async -> NomiNotificationPermissionStatus {
        let center = UNUserNotificationCenter.current()
        do {
            let granted = try await center.requestAuthorization(options: [.alert, .badge, .sound])
            let settings = await center.notificationSettings()
            if granted {
                UIApplication.shared.registerForRemoteNotifications()
            }
            return permissionStatus(from: settings.authorizationStatus)
        } catch {
            return .denied
        }
    }

    static func permissionStatus(from status: UNAuthorizationStatus) -> NomiNotificationPermissionStatus {
        switch status {
        case .notDetermined:
            return .notDetermined
        case .denied:
            return .denied
        case .authorized:
            return .authorized
        case .provisional:
            return .provisional
        case .ephemeral:
            return .ephemeral
        @unknown default:
            return .denied
        }
    }
}

private struct NomiWorkbenchView: View {
    @Binding var selectedMode: NomiWorkbenchMode
    let route: NomiRoute?
    let client: NomiApiClient?
    let serverStatus: String
    let realtimeSuggestions: [AssistantSuggestion]
    let taskCards: [NomiTaskCard]
    @Binding var settings: NomiIslandSettings
    let liveActivityId: String?
    let liveActivityStatus: String
    let updateLiveActivity: (NomiChatLiveActivityDelta) async -> Void
    let startLiveActivity: () -> Void
    let previewLiveActivity: () -> Void
    let stopLiveActivity: () -> Void
    let notificationStatus: NomiNotificationRegistrationStatus
    let requestNotifications: () -> Void
    @Binding var serverBaseURL: String
    @Binding var serverPassword: String
    let saveServerConfig: () -> Void
    @State private var chrome = NomiWorkbenchChrome()
    @State private var webDestination: NomiWebDestination?

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 8) {
                header
                if chrome.isModeMenuExpanded {
                    modeSwitcher
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
                content
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .safeAreaPadding(.horizontal, 16)
            .safeAreaPadding(.top, 8)
            .background(Color(uiColor: .systemBackground))
            .toolbar(.hidden, for: .navigationBar)
            .onAppear {
                chrome.syncSelection(selectedMode)
            }
            .onChange(of: selectedMode) { _, mode in
                chrome.syncSelection(mode)
            }
        }
        .sheet(item: $webDestination) { destination in
            NomiWebWorkspaceSheetView(
                destination: destination,
                openRemoteBrowser: openRemoteBrowser(source:)
            )
        }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 10) {
            Text("Nomi")
                .font(.title3.weight(.semibold))
                .lineLimit(1)
            connectionBadge
            Spacer(minLength: 8)
            if !chrome.isModeMenuExpanded {
                modeButton(selectedMode)
            }
            modeMenuButton
        }
        .frame(minHeight: 40)
    }

    private var modeSwitcher: some View {
        HStack(spacing: 8) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(chrome.visibleModes) { mode in
                        modeButton(mode)
                    }
                }
            }
            .frame(maxWidth: .infinity)
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Nomi mode")
    }

    private var connectionBadge: some View {
        let label = NomiWorkbenchPresentation.connectionLabel(for: serverStatus)
        let tint = NomiWorkbenchPresentation.connectionTint(for: serverStatus)
        return HStack(spacing: 4) {
            Circle()
                .fill(connectionColor(for: tint))
                .frame(width: 7, height: 7)
            Text(label)
                .font(.caption2.weight(.medium))
                .lineLimit(1)
        }
        .foregroundStyle(.secondary)
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(Color.secondary.opacity(0.10))
        .clipShape(Capsule())
        .accessibilityLabel("Server \(label)")
    }

    private var modeMenuButton: some View {
        Button {
            withAnimation(.easeInOut(duration: 0.16)) {
                chrome.toggleModeMenu()
            }
        } label: {
            Image(systemName: chrome.isModeMenuExpanded ? "chevron.up.circle.fill" : "ellipsis.circle")
                .font(.title3)
                .frame(width: 38, height: 38)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(chrome.isModeMenuExpanded ? "Collapse Nomi tools" : "Show Nomi tools")
    }

    private func connectionColor(for tint: String) -> Color {
        switch tint {
        case "green":
            return .green
        case "orange":
            return .orange
        default:
            return .secondary
        }
    }

    private func modeButton(_ mode: NomiWorkbenchMode) -> some View {
        Button {
            withAnimation(.easeInOut(duration: 0.16)) {
                chrome.select(mode)
                selectedMode = mode
            }
        } label: {
            Label(mode.title, systemImage: mode.systemImage)
                .labelStyle(.titleAndIcon)
                .font(.caption.weight(.semibold))
                .lineLimit(1)
                .padding(.horizontal, 10)
                .padding(.vertical, 7)
                .frame(minWidth: 72, minHeight: 32)
        }
        .buttonStyle(.plain)
        .foregroundStyle(selectedMode == mode ? Color.white : Color.primary)
        .background(selectedMode == mode ? Color.accentColor : Color.secondary.opacity(0.12))
        .clipShape(Capsule())
        .accessibilityLabel(mode.title)
    }

    @ViewBuilder
    private var content: some View {
        switch selectedMode {
        case .chat:
            ChatView(
                route: route,
                client: client,
                settings: settings,
                liveActivityId: liveActivityId,
                updateLiveActivity: updateLiveActivity
            )
        case .suggestions:
            SuggestionListView(route: route, client: client, realtimeSuggestions: realtimeSuggestions)
        case .tasks:
            NomiTaskListView(route: route, client: client, realtimeCards: taskCards)
        case .accounts:
            NomiAccountsView(
                client: client,
                openRemoteBrowser: openRemoteBrowser(source:),
                startComposioAuth: startComposioAuth(slug:force:)
            )
        case .career:
            NomiCareerBoardView(route: route, client: client)
        case .settings:
            SettingsView(
                settings: $settings,
                activityId: liveActivityId,
                statusMessage: liveActivityStatus,
                startLiveActivity: startLiveActivity,
                previewLiveActivity: previewLiveActivity,
                stopLiveActivity: stopLiveActivity,
                notificationStatus: notificationStatus,
                requestNotifications: requestNotifications,
                openWebWorkbench: {
                    openWorkbench(route: "chat")
                },
                openRemoteBrowser: {
                    openRemoteBrowser(source: "search")
                },
                serverBaseURL: $serverBaseURL,
                serverPassword: $serverPassword,
                serverConfigStatus: serverStatus,
                saveServerConfig: saveServerConfig
            )
        }
    }

    private func openWorkbench(route: String, pendingAgentEvent: String? = nil, pendingProactive: String? = nil) {
        guard let base = URL(string: serverBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)), !serverPassword.isEmpty else { return }
        var components = URLComponents(url: base, resolvingAgainstBaseURL: false)
        components?.fragment = route
        guard let url = components?.url else { return }
        webDestination = NomiWebDestination(
            url: url,
            password: serverPassword,
            pendingProactive: pendingProactive,
            pendingAgentEvent: pendingAgentEvent,
            remoteSource: nil
        )
    }

    private func openRemoteBrowser(source: String) {
        guard let config = try? ServerConfig.normalize(baseURL: serverBaseURL, password: serverPassword) else { return }
        Task {
            try? await client?.openBrowser(source: source)
            await MainActor.run {
                webDestination = NomiWebDestination(
                    url: NomiApiClient.remoteBrowserURL(for: config),
                    password: serverPassword,
                    pendingProactive: nil,
                    pendingAgentEvent: nil,
                    remoteSource: source
                )
            }
        }
    }

    private func startComposioAuth(slug: String, force: Bool = false) {
        Task {
            do {
                guard let url = try await client?.composioConnectURL(slug: slug, force: force) else { return }
                await MainActor.run {
                    UIApplication.shared.open(url)
                }
            } catch {
                await MainActor.run {
                    webDestination = nil
                }
            }
        }
    }
}

private struct NomiWebDestination: Identifiable {
    let id = UUID()
    var url: URL
    var password: String
    var pendingProactive: String?
    var pendingAgentEvent: String?
    var remoteSource: String?
}

private struct NomiWebWorkspaceSheetView: View {
    @Environment(\.dismiss) private var dismiss
    let destination: NomiWebDestination
    let openRemoteBrowser: (String) -> Void
    @State private var reloadID = UUID()

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            Divider()
            NomiWebWorkspaceView(destination: destination, reloadID: reloadID)
        }
        .background(Color(uiColor: .systemBackground))
    }

    private var toolbar: some View {
        HStack(spacing: 10) {
            Button {
                dismiss()
            } label: {
                Image(systemName: "xmark")
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("Close cloud browser")

            VStack(alignment: .leading, spacing: 2) {
                Text(NomiWebWorkspaceChrome.title(for: destination.remoteSource))
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(1)
                Text("Cloud browser")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }

            Spacer(minLength: 8)

            Menu {
                ForEach(NomiWebWorkspaceChrome.remoteSources) { source in
                    Button {
                        openRemoteBrowser(source.id)
                    } label: {
                        Label(source.title, systemImage: source.id == destination.remoteSource ? "checkmark" : "globe")
                    }
                }
            } label: {
                Label("Switch", systemImage: "rectangle.on.rectangle")
                    .labelStyle(.iconOnly)
            }
            .accessibilityLabel("Switch cloud browser source")

            Button {
                reloadID = UUID()
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("Reload cloud browser")
        }
        .frame(minHeight: CGFloat(NomiWebWorkspaceChrome.topControlHeight))
        .padding(.horizontal, 14)
        .background(Color(uiColor: .secondarySystemBackground))
    }
}

private struct NomiWebWorkspaceView: UIViewRepresentable {
    let destination: NomiWebDestination
    let reloadID: UUID

    func makeCoordinator() -> Coordinator {
        Coordinator(destination: destination, reloadID: reloadID)
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = true
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.load(URLRequest(url: destination.url))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        guard context.coordinator.destination.id != destination.id || context.coordinator.reloadID != reloadID else {
            return
        }
        context.coordinator.destination = destination
        context.coordinator.reloadID = reloadID
        webView.load(URLRequest(url: destination.url))
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        var destination: NomiWebDestination
        var reloadID: UUID

        init(destination: NomiWebDestination, reloadID: UUID) {
            self.destination = destination
            self.reloadID = reloadID
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            webView.evaluateJavaScript(NomiWebWorkspaceBridge.passwordInjectionScript(password: destination.password))
            if let pendingProactive = destination.pendingProactive {
                webView.evaluateJavaScript(NomiWebWorkspaceBridge.pendingProactiveScript(json: pendingProactive))
            }
            if let pendingAgentEvent = destination.pendingAgentEvent {
                webView.evaluateJavaScript(NomiWebWorkspaceBridge.pendingAgentEventScript(rawJSON: pendingAgentEvent))
            }
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard let url = navigationAction.request.url else {
                decisionHandler(.cancel)
                return
            }
            if url.host == destination.url.host || url.scheme == "about" {
                decisionHandler(.allow)
            } else {
                UIApplication.shared.open(url)
                decisionHandler(.cancel)
            }
        }
    }
}

private struct NomiTaskListView: View {
    let route: NomiRoute?
    let client: NomiApiClient?
    let realtimeCards: [NomiTaskCard]
    @State private var detail: NomiTaskDetail?
    @State private var events: [NomiTaskEvent] = []
    @State private var status = "No task selected"
    @State private var isLoading = false

    var body: some View {
        List {
            Section("Realtime") {
                if realtimeCards.isEmpty {
                    Text("No realtime task cards.")
                        .foregroundStyle(.secondary)
                }
                ForEach(realtimeCards) { card in
                    VStack(alignment: .leading) {
                        Text(card.title)
                            .font(.headline)
                        Text(card.body)
                            .foregroundStyle(.secondary)
                    }
                    .listRowBackground(card.taskId == taskId ? Color.accentColor.opacity(0.12) : nil)
                }
            }
            Section("Task") {
                if let taskId {
                    Text("Task \(taskId)")
                    if let detail {
                        Text(detail.title ?? detail.status ?? "Task loaded")
                    }
                    HStack {
                        Button("Resume") {
                            Task { await runTaskAction("resumed") { try await client?.resumeTask(taskId: taskId) } }
                        }
                        Button("Cancel", role: .destructive) {
                            Task { await runTaskAction("cancelled") { try await client?.cancelTask(taskId: taskId) } }
                        }
                    }
                    .buttonStyle(.borderless)
                } else {
                    Text("Open a task from Dynamic Island or a proactive event.")
                        .foregroundStyle(.secondary)
                }
                if isLoading {
                    ProgressView()
                }
                Text(status)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            Section("Events") {
                if events.isEmpty {
                    Text("No task events loaded.")
                        .foregroundStyle(.secondary)
                }
                ForEach(events) { event in
                    VStack(alignment: .leading) {
                        Text(event.type)
                            .font(.headline)
                        Text(event.message ?? event.id)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .task(id: taskId) {
            await load()
        }
    }

    private var taskId: String? {
        if case let .task(id, _) = route {
            return id
        }
        if case let .workbench(route, taskId) = route, route == "task" {
            return taskId
        }
        return nil
    }

    @MainActor
    private func load() async {
        guard let taskId else { return }
        guard let client else {
            status = "Server not configured"
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            async let detail = client.taskDetail(taskId: taskId)
            async let events = client.taskEvents(taskId: taskId)
            self.detail = try await detail
            self.events = try await events
            status = "Task loaded"
        } catch is CancellationError {
            return
        } catch {
            status = "Unable to load task: \(error.localizedDescription)"
        }
    }

    @MainActor
    private func runTaskAction(_ success: String, action: () async throws -> Void) async {
        do {
            try await action()
            status = "Task \(success)"
            await load()
        } catch {
            status = "Task action failed: \(error.localizedDescription)"
        }
    }
}

private struct NomiAccountsView: View {
    let client: NomiApiClient?
    let openRemoteBrowser: (String) -> Void
    let startComposioAuth: (String, Bool) -> Void
    @State private var collectors: [CollectorStatus] = []
    @State private var identities: [AssistantIdentity] = []
    @State private var status = "Accounts not loaded"
    @State private var isLoading = false

    var body: some View {
        List {
            Section("Nomi identities") {
                if identities.isEmpty {
                    Text("No identities loaded.")
                        .foregroundStyle(.secondary)
                }
                ForEach(identities) { identity in
                    VStack(alignment: .leading) {
                        Text(identity.displayName)
                        Text(identity.address ?? identity.kind)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            Section("Channels") {
                ForEach(collectors) { collector in
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            VStack(alignment: .leading) {
                                Text(collector.source)
                                Text(channelRouteText(for: collector.source))
                                    .font(.footnote)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(collector.healthStatus)
                                .font(.caption)
                                .foregroundStyle(collector.enabled && !collector.paused ? .green : .orange)
                        }
                        actionButton(for: collector)
                    }
                }
                if collectors.isEmpty {
                    Text("No account channels loaded.")
                        .foregroundStyle(.secondary)
                }
            }
            Section {
                if isLoading {
                    ProgressView()
                }
                Text(status)
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

    @ViewBuilder
    private func actionButton(for collector: CollectorStatus) -> some View {
        switch NomiAccountChannelRoute.forSource(collector.source) {
        case let .composio(slug):
            if collector.enabled && !collector.paused && collector.healthStatus == "healthy" {
                HStack {
                    Text("Already connected")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    Button("Reconnect") {
                        startComposioAuth(slug, true)
                    }
                    .buttonStyle(.borderless)
                }
            } else {
                Button("Connect") {
                    startComposioAuth(slug, false)
                }
                .buttonStyle(.borderless)
            }
        case let .remoteBrowser(source):
            Button("Open browser") {
                openRemoteBrowser(source)
            }
            .buttonStyle(.borderless)
        case .localOnly:
            Text("Local")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
    }

    private func channelRouteText(for source: String) -> String {
        switch NomiAccountChannelRoute.forSource(source) {
        case let .composio(slug):
            return "Composio \(slug)"
        case let .remoteBrowser(source):
            return "Remote browser \(source)"
        case .localOnly:
            return "Local"
        }
    }

    @MainActor
    private func load() async {
        guard let client else {
            status = "Server not configured"
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            async let collectors = client.collectorsStatus()
            async let identities = client.assistantIdentities()
            self.collectors = try await collectors
            self.identities = try await identities
            status = "Accounts loaded"
        } catch is CancellationError {
            return
        } catch {
            status = "Unable to load accounts: \(error.localizedDescription)"
        }
    }
}

private struct NomiCareerBoardView: View {
    let route: NomiRoute?
    let client: NomiApiClient?
    @State private var board = CareerBoard(profiles: [], opportunities: [], applications: [])
    @State private var status = "Career board not loaded"
    @State private var isLoading = false

    var body: some View {
        List {
            Section("Profile") {
                ForEach(board.profiles ?? []) { profile in
                    Text(profile.headline ?? profile.id)
                }
                if (board.profiles ?? []).isEmpty {
                    Text("还没有求职数据...")
                        .foregroundStyle(.secondary)
                }
            }
            Section("Opportunities") {
                ForEach(board.opportunities ?? []) { opportunity in
                    VStack(alignment: .leading) {
                        Text(opportunity.title ?? opportunity.id)
                        Text([opportunity.company, opportunity.status].compactMap { $0 }.joined(separator: " · "))
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            Section("Applications") {
                ForEach(board.applications ?? []) { application in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(application.id)
                        Text([application.status, application.stage, application.nextStep].compactMap { $0 }.joined(separator: " · "))
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                        if shouldShowActions(for: application) {
                            HStack {
                                Button("标记已投递") {
                                    Task {
                                        await updateApplication(
                                            application,
                                            status: "submitted",
                                            stage: "submitted",
                                            nextStep: "prepare_interview_if_replied",
                                            userNote: "用户在 iOS 求职看板中标记已投递"
                                        )
                                    }
                                }
                                Button("忽略", role: .destructive) {
                                    Task {
                                        await updateApplication(
                                            application,
                                            status: "ignored",
                                            stage: "ignored",
                                            nextStep: "none",
                                            userNote: "用户在 iOS 求职看板中忽略该机会"
                                        )
                                    }
                                }
                            }
                            .buttonStyle(.borderless)
                        }
                    }
                }
            }
            Section {
                if isLoading {
                    ProgressView()
                }
                Text(status)
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

    @MainActor
    private func load() async {
        guard let client else {
            status = "Server not configured"
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            board = try await client.careerBoard()
            status = focusText ?? "Career board loaded"
        } catch is CancellationError {
            return
        } catch {
            status = "Unable to load career board: \(error.localizedDescription)"
        }
    }

    private var focusText: String? {
        if case let .careerOpportunity(id) = route {
            return "Focused opportunity \(id)"
        }
        return nil
    }

    private func shouldShowActions(for application: JobApplicationState) -> Bool {
        application.status != "ignored" && application.status != "submitted"
    }

    @MainActor
    private func updateApplication(
        _ application: JobApplicationState,
        status: String,
        stage: String,
        nextStep: String,
        userNote: String
    ) async {
        guard let client else {
            self.status = "Server not configured"
            return
        }
        do {
            try await client.patchCareerApplication(
                applicationId: application.id,
                status: status,
                stage: stage,
                nextStep: nextStep,
                userNote: userNote
            )
            self.status = "Career application \(status)"
            await load()
        } catch {
            self.status = "Career application update failed: \(error.localizedDescription)"
        }
    }
}
