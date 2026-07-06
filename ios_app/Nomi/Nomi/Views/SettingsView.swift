import SwiftUI

struct SettingsView: View {
    @Binding var settings: NomiIslandSettings
    var activityId: String? = nil
    var statusMessage: String = "Not started"
    var startLiveActivity: () -> Void = {}
    var previewLiveActivity: () -> Void = {}
    var stopLiveActivity: () -> Void = {}
    var notificationStatus: NomiNotificationRegistrationStatus = NomiNotificationRegistrationStatus()
    var requestNotifications: () -> Void = {}
    var openWebWorkbench: () -> Void = {}
    var openRemoteBrowser: () -> Void = {}
    @Binding var serverBaseURL: String
    @Binding var serverPassword: String
    var serverConfigStatus: String = "Server not configured"
    var saveServerConfig: () -> Void = {}

    init(
        settings: Binding<NomiIslandSettings>,
        activityId: String? = nil,
        statusMessage: String = "Not started",
        startLiveActivity: @escaping () -> Void = {},
        previewLiveActivity: @escaping () -> Void = {},
        stopLiveActivity: @escaping () -> Void = {},
        notificationStatus: NomiNotificationRegistrationStatus = NomiNotificationRegistrationStatus(),
        requestNotifications: @escaping () -> Void = {},
        openWebWorkbench: @escaping () -> Void = {},
        openRemoteBrowser: @escaping () -> Void = {},
        serverBaseURL: Binding<String> = .constant(""),
        serverPassword: Binding<String> = .constant(""),
        serverConfigStatus: String = "Server not configured",
        saveServerConfig: @escaping () -> Void = {}
    ) {
        self._settings = settings
        self.activityId = activityId
        self.statusMessage = statusMessage
        self.startLiveActivity = startLiveActivity
        self.previewLiveActivity = previewLiveActivity
        self.stopLiveActivity = stopLiveActivity
        self.notificationStatus = notificationStatus
        self.requestNotifications = requestNotifications
        self.openWebWorkbench = openWebWorkbench
        self.openRemoteBrowser = openRemoteBrowser
        self._serverBaseURL = serverBaseURL
        self._serverPassword = serverPassword
        self.serverConfigStatus = serverConfigStatus
        self.saveServerConfig = saveServerConfig
    }

    var body: some View {
        Form {
            Section("Server") {
                TextField("Base URL", text: $serverBaseURL)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                    .autocorrectionDisabled()
                SecureField("Password", text: $serverPassword)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Text(serverConfigStatus)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                Button {
                    saveServerConfig()
                } label: {
                    Label("Save and test server", systemImage: "checkmark.circle")
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }

            Section("Dynamic Island") {
                Toggle("Show Nomi in Dynamic Island", isOn: $settings.liveActivityEnabled)
                Toggle("Open target page when tapping Dynamic Island", isOn: $settings.deepLinksEnabled)
                Toggle("Notification fallback", isOn: $settings.notificationFallbackEnabled)
                Text(notificationStatus.fallbackAvailabilityText)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                HStack {
                    Text("APNs token")
                    Spacer()
                    Text(notificationStatus.apnsDeviceToken.isEmpty ? "Missing" : String(notificationStatus.apnsDeviceToken.prefix(8)))
                        .foregroundStyle(.secondary)
                }
                Button("Request notifications") {
                    requestNotifications()
                }
                HStack {
                    Text("Activity")
                    Spacer()
                    Text(activityId.map { String($0.prefix(8)) } ?? "Inactive")
                        .foregroundStyle(.secondary)
                }
                Text(statusMessage)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                HStack {
                    Button("Start") {
                        startLiveActivity()
                    }
                    Button("Preview") {
                        previewLiveActivity()
                    }
                    Button("Stop", role: .destructive) {
                        stopLiveActivity()
                    }
                }
                .buttonStyle(.borderless)
            }

            Section("Assistant") {
                Button("Open Web Workbench") {
                    openWebWorkbench()
                }
                Button("Open Remote Browser") {
                    openRemoteBrowser()
                }
            }

            Section("Token streaming") {
                Toggle("Stream every reply token", isOn: $settings.tokenLevelChatStreamingEnabled)
                Picker("Delivery", selection: $settings.tokenLevelChatDelivery) {
                    Text("Foreground only").tag(TokenLevelChatDelivery.localWhenForeground)
                    Text("APNs best effort").tag(TokenLevelChatDelivery.apnsBestEffort)
                    Text("Foreground and APNs").tag(TokenLevelChatDelivery.localAndApnsBestEffort)
                }
            }

            Section("Private APNs payloads") {
                Toggle("Allow private content in APNs", isOn: $settings.sensitiveApnsPayloadEnabled)
                if settings.sensitiveApnsPayloadEnabled {
                    Text("Private message text may pass through Apple Push Notification service. Enable only if you accept that tradeoff.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    Toggle("Include message body", isOn: $settings.includePrivateMessageBody)
                    Toggle("Include contact names", isOn: $settings.includeContactNames)
                    Toggle("Include raw private context", isOn: $settings.includeRawPrivateContext)
                    Stepper("Payload limit: \(settings.maxSensitivePayloadChars)", value: $settings.maxSensitivePayloadChars, in: 0...3400, step: 100)
                }
            }
        }
    }
}
