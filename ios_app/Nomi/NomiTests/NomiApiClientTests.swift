import XCTest
@testable import Nomi

final class NomiApiClientTests: XCTestCase {
    func testDeviceRegistrationPayloadUsesBackendFieldNames() throws {
        var settings = NomiIslandSettings()
        settings.sensitiveApnsPayloadEnabled = true

        let data = try NomiApiClient.deviceRegistrationPayload(
            deviceId: "device-1",
            displayName: "iPhone",
            settings: settings,
            apnsEnvironment: "sandbox",
            apnsDeviceToken: "device-token",
            liveActivityPushToStartToken: "push-to-start"
        )
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let payloadSettings = json?["settings"] as? [String: Any]

        XCTAssertEqual(json?["device_id"] as? String, "device-1")
        XCTAssertEqual(json?["display_name"] as? String, "iPhone")
        XCTAssertEqual(json?["apns_environment"] as? String, "sandbox")
        XCTAssertEqual(json?["apns_device_token"] as? String, "device-token")
        XCTAssertEqual(json?["live_activity_push_to_start_token"] as? String, "push-to-start")
        XCTAssertEqual(payloadSettings?["sensitive_apns_payload_enabled"] as? Bool, true)
    }

    func testRemoteBrowserUrlMatchesAndroidNoVncRule() throws {
        let http = try ServerConfig.normalize(baseURL: "http://127.0.0.1:8080", password: "secret")
        let https = try ServerConfig.normalize(baseURL: "https://nomi.example.com/api", password: "secret")

        XCTAssertEqual(
            NomiApiClient.remoteBrowserURL(for: http).absoluteString,
            "http://127.0.0.1:6080/vnc_lite.html?autoconnect=1&scale=true&quality=6&compression=2&show_dot=1&password=secret-vnc"
        )
        XCTAssertEqual(
            NomiApiClient.remoteBrowserURL(for: https).absoluteString,
            "https://nomi.example.com:6080/vnc_lite.html?autoconnect=1&scale=true&quality=6&compression=2&show_dot=1&password=secret-vnc"
        )
    }

    func testBrowserOpenPayloadUsesSourceField() throws {
        let data = try NomiApiClient.browserOpenPayload(source: "whatsapp")
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]

        XCTAssertEqual(json?["source"] as? String, "whatsapp")
    }

    func testComposioConnectPathCanForceReconnectForAlreadyConnectedAccounts() {
        XCTAssertEqual(
            NomiApiClient.composioConnectPath(slug: "gmail", force: true),
            "/api/integrations/composio/connect/gmail?force=true"
        )
        XCTAssertEqual(
            NomiApiClient.composioConnectPath(slug: "googlecalendar", force: false),
            "/api/integrations/composio/connect/googlecalendar"
        )
    }

    func testCareerApplicationPatchPayloadPreservesActionFields() throws {
        let data = try NomiApiClient.careerApplicationPatchPayload(
            status: "submitted",
            stage: "submitted",
            nextStep: "prepare_interview_if_replied",
            userNote: "Applied on LinkedIn"
        )
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]

        XCTAssertEqual(json?["status"] as? String, "submitted")
        XCTAssertEqual(json?["stage"] as? String, "submitted")
        XCTAssertEqual(json?["next_step"] as? String, "prepare_interview_if_replied")
        XCTAssertEqual(json?["user_note"] as? String, "Applied on LinkedIn")
    }

    func testTaskHumanInputPayloadUsesInputField() throws {
        let data = try NomiApiClient.taskHumanInputPayload("Use the concise version")
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]

        XCTAssertEqual(json?["input"] as? String, "Use the concise version")
    }

    func testTaskCancelPayloadUsesBackendReasonField() throws {
        let data = try NomiApiClient.taskCancelPayload("cancelled_from_ios")
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]

        XCTAssertEqual(json?["reason"] as? String, "cancelled_from_ios")
    }

    func testDecodesCollectorStatusEnvelopeFromBackend() throws {
        let data = """
        {
          "collectors": [
            {
              "source": "gmail",
              "enabled": true,
              "paused": false,
              "health_status": "healthy"
            },
            {
              "source": "whatsapp",
              "enabled": true,
              "paused": false,
              "health_status": "unknown"
            }
          ]
        }
        """.data(using: .utf8)!

        let collectors = try NomiApiClient.decodeCollectorsStatus(data)

        XCTAssertEqual(collectors.map(\.source), ["gmail", "whatsapp"])
        XCTAssertEqual(collectors.first?.healthStatus, "healthy")
    }

    func testDecodesAssistantIdentityEnvelopeFromBackend() throws {
        let data = """
        {
          "count": 2,
          "identities": [
            {
              "identity_id": "nomi_gmail",
              "kind": "assistant_gmail",
              "display_name": "Nomi Gmail",
              "address": "nomi@example.com",
              "status": "configured"
            },
            {
              "identity_id": "nomi_phone",
              "kind": "assistant_phone",
              "display_name": "Nomi Phone",
              "address": "+15555550100",
              "status": "configured"
            }
          ]
        }
        """.data(using: .utf8)!

        let identities = try NomiApiClient.decodeAssistantIdentities(data)

        XCTAssertEqual(identities.map(\.identityId), ["nomi_gmail", "nomi_phone"])
        XCTAssertEqual(identities.first?.displayName, "Nomi Gmail")
    }

    func testDecodesTaskDetailEnvelopeFromBackend() throws {
        let data = """
        {
          "state": {
            "task_id": "task-ios-real-server",
            "status": "created",
            "current_node": "created",
            "original_goal": "Validate iOS Tasks tab against real server"
          },
          "event_count": 1
        }
        """.data(using: .utf8)!

        let detail = try NomiApiClient.decodeTaskDetail(data)

        XCTAssertEqual(detail.id, "task-ios-real-server")
        XCTAssertEqual(detail.status, "created")
        XCTAssertEqual(detail.title, "Validate iOS Tasks tab against real server")
    }

    func testDecodesTaskEventsEnvelopeFromBackend() throws {
        let data = """
        {
          "task_id": "task-ios-real-server",
          "events": [
            {
              "event_id": "evt-ios-real-server",
              "event_type": "task.created",
              "payload": {
                "original_goal": "Validate iOS Tasks tab against real server"
              }
            }
          ]
        }
        """.data(using: .utf8)!

        let events = try NomiApiClient.decodeTaskEvents(data)

        XCTAssertEqual(events.map(\.id), ["evt-ios-real-server"])
        XCTAssertEqual(events.first?.type, "task.created")
        XCTAssertEqual(events.first?.message, "Validate iOS Tasks tab against real server")
    }

    func testMergesConnectedComposioToolkitsIntoCollectorStatuses() {
        let collectors = [
            CollectorStatus(source: "gmail", enabled: true, paused: false, healthStatus: "degraded"),
            CollectorStatus(source: "calendar", enabled: true, paused: false, healthStatus: "degraded"),
            CollectorStatus(source: "whatsapp", enabled: true, paused: false, healthStatus: "healthy"),
        ]
        let toolkits = [
            ComposioToolkitConnection(slug: "gmail", connected: true),
            ComposioToolkitConnection(slug: "googlecalendar", connected: false),
        ]

        let merged = NomiApiClient.mergeCollectorStatuses(collectors, with: toolkits)
        let gmail = merged.first { $0.source == "gmail" }
        let calendar = merged.first { $0.source == "calendar" }

        XCTAssertEqual(gmail?.healthStatus, "healthy")
        XCTAssertEqual(gmail?.enabled, true)
        XCTAssertEqual(gmail?.paused, false)
        XCTAssertEqual(calendar?.healthStatus, "degraded")
    }

    func testMergesAllConfiguredComposioToolkitsIntoAccountStatuses() {
        let toolkits = [
            ComposioToolkitConnection(slug: "google_maps", connected: false),
            ComposioToolkitConnection(slug: "linear", connected: false),
            ComposioToolkitConnection(slug: "jira", connected: false),
            ComposioToolkitConnection(slug: "todoist", connected: false),
        ]

        let merged = NomiApiClient.mergeCollectorStatuses([], with: toolkits)

        XCTAssertEqual(merged.map(\.source), ["google_maps", "linear", "jira", "todoist"])
        XCTAssertTrue(merged.allSatisfy { $0.enabled && !$0.paused && $0.healthStatus == "degraded" })
    }
}
