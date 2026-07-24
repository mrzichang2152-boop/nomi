package com.par.assistant.android;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import com.par.assistant.core.ServerConfig;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;

import java.util.Arrays;
import java.util.List;

import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;

public final class AssistantApiClientTest {
    private MockWebServer server;

    @Before
    public void startServer() throws Exception {
        server = new MockWebServer();
        server.start();
    }

    @After
    public void stopServer() throws Exception {
        if (server != null) {
            server.shutdown();
        }
    }

    @Test
    public void chatHistoryFetchesLatestConversationWithAuthAndPreservesTurnOrder() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"conversation_id\":\"11111111-1111-1111-1111-111111111111\","
                                + "\"messages\":["
                                + "{"
                                + "\"id\":\"22222222-2222-2222-2222-222222222222\","
                                + "\"created_at\":\"2026-05-29T08:00:00+00:00\","
                                + "\"role\":\"user\","
                                + "\"content\":\"需要\""
                                + "},"
                                + "{"
                                + "\"id\":\"44444444-4444-4444-4444-444444444444\","
                                + "\"created_at\":\"2026-05-29T08:00:05+00:00\","
                                + "\"role\":\"assistant\","
                                + "\"content\":\"好的，我会继续核对成本与利润率。\""
                                + "}"
                                + "]"
                                + "}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        ChatHistoryResult result = client.chatHistory(null, 20);

        RecordedRequest request = server.takeRequest();
        assertEquals("/api/chat/history?limit=20", request.getPath());
        assertEquals("secret", request.getHeader("x-par-password"));
        assertEquals("11111111-1111-1111-1111-111111111111", result.conversationId);
        assertEquals(2, result.messages.size());
        assertEquals("22222222-2222-2222-2222-222222222222", result.messages.get(0).id);
        assertEquals("2026-05-29T08:00:00+00:00", result.messages.get(0).createdAt);
        assertEquals("user", result.messages.get(0).role);
        assertEquals("需要", result.messages.get(0).content);
        assertEquals("44444444-4444-4444-4444-444444444444", result.messages.get(1).id);
        assertEquals("2026-05-29T08:00:05+00:00", result.messages.get(1).createdAt);
        assertEquals("assistant", result.messages.get(1).role);
        assertEquals("好的，我会继续核对成本与利润率。", result.messages.get(1).content);
    }

    @Test
    public void chatHistoryKeepsStableMessageIdsAndOrderedSafeAttachmentMetadata() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"conversation_id\":\"conv-attachments\","
                                + "\"messages\":[{"
                                + "\"id\":\"message-1\","
                                + "\"created_at\":\"2026-07-13T10:00:00+08:00\","
                                + "\"role\":\"user\","
                                + "\"content\":\"比较附件\","
                                + "\"attachments\":["
                                + "{\"attachment_id\":\"a-1\",\"ordinal\":0,\"filename\":\"第一.png\","
                                + "\"mime_type\":\"image/png\",\"byte_size\":11,\"status\":\"ready\","
                                + "\"kind\":\"image\",\"preview_url\":\"/preview/a-1\",\"content_url\":\"/content/a-1\"},"
                                + "{\"attachment_id\":\"a-2\",\"ordinal\":1,\"filename\":\"第二.pdf\","
                                + "\"mime_type\":\"application/pdf\",\"byte_size\":22,\"status\":\"ready\","
                                + "\"kind\":\"pdf\",\"preview_url\":null,\"content_url\":\"/content/a-2\"}"
                                + "]}]}" )
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        ChatHistoryMessage message = client.chatHistory("conv-attachments", 20).messages.get(0);

        assertEquals("message-1", message.id);
        assertEquals("2026-07-13T10:00:00+08:00", message.createdAt);
        assertEquals(2, message.attachments.size());
        assertEquals("message-1", message.attachments.get(0).messageId);
        assertEquals("a-1", message.attachments.get(0).attachmentId);
        assertEquals(0, message.attachments.get(0).ordinal);
        assertEquals("a-2", message.attachments.get(1).attachmentId);
        assertEquals(1, message.attachments.get(1).ordinal);
    }

    @Test
    public void chatPostsClientRequestIdForFallbackIdempotency() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{\"answer\":\"pong\",\"conversation_id\":\"conv-1\",\"client_request_id\":\"android-request-1\"}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        ChatResult result = client.chat("ping", "conv-1", java.util.List.of(), "android-request-1");

        RecordedRequest request = server.takeRequest();
        assertEquals("/api/chat", request.getPath());
        assertEquals("secret", request.getHeader("x-par-password"));
        String requestBody = request.getBody().readUtf8();
        assertTrue(requestBody.contains("\"client_request_id\":\"android-request-1\""));
        assertTrue(requestBody.contains("\"conversation_id\":\"conv-1\""));
        assertEquals("pong", result.answer);
        assertEquals("conv-1", result.conversationId);
    }

    @Test
    public void chatParsesArtifactCardsFromResponse() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"answer\":\"PPT 已生成，可以下载。\","
                                + "\"conversation_id\":\"conv-artifact\","
                                + "\"artifacts\":[{"
                                + "\"artifact_id\":\"artifact_1\","
                                + "\"task_run_id\":\"lta_1\","
                                + "\"artifact_type\":\"pptx\","
                                + "\"filename\":\"普通人也能理解_LLM.pptx\","
                                + "\"mime_type\":\"application/vnd.openxmlformats-officedocument.presentationml.presentation\","
                                + "\"download_url\":\"/api/artifacts/artifact_1/download\","
                                + "\"verification_status\":\"verified\""
                                + "}]"
                                + "}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        ChatResult result = client.chat("做一个 PPT", "conv-artifact", java.util.List.of(), "android-artifact-1");

        assertEquals("PPT 已生成，可以下载。", result.answer);
        assertEquals("conv-artifact", result.conversationId);
        assertEquals(1, result.artifacts.size());
        ChatArtifact artifact = result.artifacts.get(0);
        assertEquals("artifact_1", artifact.artifactId);
        assertEquals("lta_1", artifact.taskRunId);
        assertEquals("pptx", artifact.artifactType);
        assertEquals("普通人也能理解_LLM.pptx", artifact.filename);
        assertEquals("/api/artifacts/artifact_1/download", artifact.downloadUrl);
        assertEquals("verified", artifact.verificationStatus);
        assertEquals("PPTX · 已校验", artifact.statusLine());
    }

    @Test
    public void chatParsesArtifactCardsFromNestedTaskResponse() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"answer\":\"已生成 PPT 文件：LLM工作原理.pptx\","
                                + "\"conversation_id\":\"conv-artifact\","
                                + "\"task\":{"
                                + "\"task_run_id\":\"task_1\","
                                + "\"status\":\"completed\","
                                + "\"artifacts\":[{"
                                + "\"artifact_id\":\"artifact_nested\","
                                + "\"task_run_id\":\"task_1\","
                                + "\"artifact_type\":\"pptx\","
                                + "\"filename\":\"LLM工作原理.pptx\","
                                + "\"mime_type\":\"application/vnd.openxmlformats-officedocument.presentationml.presentation\","
                                + "\"download_url\":\"http://testserver/api/artifacts/artifact_nested/download\","
                                + "\"verification_status\":\"verified\""
                                + "}]"
                                + "}"
                                + "}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        ChatResult result = client.chat("帮我做一个 PPT", "conv-artifact", java.util.List.of(), "android-artifact-nested");

        assertEquals("已生成 PPT 文件：LLM工作原理.pptx", result.answer);
        assertEquals(1, result.artifacts.size());
        ChatArtifact artifact = result.artifacts.get(0);
        assertEquals("artifact_nested", artifact.artifactId);
        assertEquals("task_1", artifact.taskRunId);
        assertEquals("LLM工作原理.pptx", artifact.filename);
        assertEquals("http://testserver/api/artifacts/artifact_nested/download", artifact.downloadUrl);
        assertEquals("PPTX · 已校验", artifact.statusLine());
    }

    @Test
    public void chatParsesTaskRunIdFromNestedTaskWhenArtifactIsGeneratedLater() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"answer\":\"我已把 PPT 任务交给 OpenCode 处理。\","
                                + "\"conversation_id\":\"conv-later-artifact\","
                                + "\"task\":{"
                                + "\"task_run_id\":\"lta_async_1\","
                                + "\"status\":\"running\""
                                + "}"
                                + "}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        ChatResult result = client.chat("帮我生成 PPT", "conv-later-artifact", java.util.List.of(), "android-later-artifact");

        assertEquals("我已把 PPT 任务交给 OpenCode 处理。", result.answer);
        assertEquals("conv-later-artifact", result.conversationId);
        assertEquals("lta_async_1", result.taskRunId);
        assertEquals(0, result.artifacts.size());
    }

    @Test
    public void chatDoesNotPollArtifactsForClarificationTask() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"answer\":\"可以。我先确认两点：讲给谁？偏科普还是技术？\","
                                + "\"conversation_id\":\"conv-clarify\","
                                + "\"task\":{"
                                + "\"task_run_id\":\"lta_clarify_1\","
                                + "\"status\":\"waiting_user\","
                                + "\"current_node\":\"waiting_for_human_input\","
                                + "\"clarification\":{\"missing_fields\":[\"audience\",\"depth\"]}"
                                + "}"
                                + "}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        ChatResult result = client.chat("帮我做一个 PPT", "conv-clarify", java.util.List.of(), "android-clarify");

        assertEquals("可以。我先确认两点：讲给谁？偏科普还是技术？", result.answer);
        assertEquals("conv-clarify", result.conversationId);
        assertEquals("", result.taskRunId);
        assertEquals(0, result.artifacts.size());
    }

    @Test
    public void taskArtifactsFetchesVerifiedArtifactsForAsyncLongTailTask() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"task_run_id\":\"lta_async_1\","
                                + "\"artifacts\":[{"
                                + "\"artifact_id\":\"artifact_async\","
                                + "\"task_run_id\":\"lta_async_1\","
                                + "\"artifact_type\":\"pptx\","
                                + "\"filename\":\"RAG_for_small_business.pptx\","
                                + "\"download_url\":\"/api/artifacts/artifact_async/download\","
                                + "\"verification_status\":\"verified\""
                                + "}]"
                                + "}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        java.util.List<ChatArtifact> artifacts = client.taskArtifacts("lta_async_1");

        RecordedRequest request = server.takeRequest();
        assertEquals("/api/tasks/lta_async_1/artifacts", request.getPath());
        assertEquals("secret", request.getHeader("x-par-password"));
        assertEquals(1, artifacts.size());
        ChatArtifact artifact = artifacts.get(0);
        assertEquals("artifact_async", artifact.artifactId);
        assertEquals("lta_async_1", artifact.taskRunId);
        assertEquals("RAG_for_small_business.pptx", artifact.filename);
        assertEquals("PPTX · 已校验", artifact.statusLine());
    }

    @Test
    public void chatRetriesTransientBadGatewayWithSameClientRequestId() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(502)
                        .setHeader("content-type", "application/json")
                        .setBody("{\"detail\":\"runtime-api restarting\"}")
        );
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{\"answer\":\"已恢复\",\"conversation_id\":\"conv-502\",\"client_request_id\":\"android-retry-1\"}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        ChatResult result = client.chat("ping", "conv-502", java.util.List.of(), "android-retry-1");

        RecordedRequest first = server.takeRequest();
        RecordedRequest second = server.takeRequest();
        assertEquals("/api/chat", first.getPath());
        assertEquals("/api/chat", second.getPath());
        assertTrue(first.getBody().readUtf8().contains("\"client_request_id\":\"android-retry-1\""));
        assertTrue(second.getBody().readUtf8().contains("\"client_request_id\":\"android-retry-1\""));
        assertEquals("已恢复", result.answer);
        assertEquals("conv-502", result.conversationId);
    }

    @Test
    public void agendaItemsFetchesRecentScheduleWithAbsoluteTime() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"items\":["
                                + "{"
                                + "\"id\":\"agenda-1\","
                                + "\"title\":\"2026-06-25 周四 16:00 人民广场会面\","
                                + "\"status\":\"pending\","
                                + "\"certainty\":\"time_specific\","
                                + "\"time_window\":{\"display\":\"2026-06-25 周四 16:00\",\"text\":\"2026-06-25 周四 16:00\"},"
                                + "\"place\":\"人民广场\","
                                + "\"participants\":[\"Alice\"],"
                                + "\"missing_fields\":[],"
                                + "\"metadata\":{\"source\":\"gmail\"}"
                                + "}"
                                + "]"
                                + "}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        java.util.List<AgendaItem> items = client.agendaItems();

        RecordedRequest request = server.takeRequest();
        assertEquals("/api/agenda?status=scheduled&limit=50", request.getPath());
        assertEquals("secret", request.getHeader("x-par-password"));
        assertEquals(1, items.size());
        AgendaItem item = items.get(0);
        assertEquals("agenda-1", item.id);
        assertEquals("2026-06-25 周四 16:00 人民广场会面", item.title);
        assertEquals("2026-06-25 周四 16:00", item.timeDisplay());
        assertEquals("人民广场", item.place);
        assertEquals("Alice", item.participants.get(0));
        assertEquals("gmail", item.source);
    }

    @Test
    public void agendaItemsDropsInactiveLinkedInBrowserNoiseIfServerReturnsIt() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"items\":["
                                + "{"
                                + "\"id\":\"bad-linkedin-agenda\","
                                + "\"title\":\"0 notifications\\nSkip to footer\\nBJAK\\nBackend Engineer, AI (Agent Systems)\","
                                + "\"status\":\"dismissed\","
                                + "\"certainty\":\"fuzzy\","
                                + "\"time_window\":{\"display\":\"待补充\"},"
                                + "\"metadata\":{\"source\":\"linkedin\"}"
                                + "},"
                                + "{"
                                + "\"id\":\"agenda-2\","
                                + "\"title\":\"2026-07-06 周一 15:30 人民广场会面\","
                                + "\"status\":\"scheduled\","
                                + "\"certainty\":\"exact\","
                                + "\"time_window\":{\"display\":\"2026-07-06 周一 15:30\"},"
                                + "\"place\":\"人民广场\","
                                + "\"participants\":[],"
                                + "\"missing_fields\":[],"
                                + "\"metadata\":{\"source\":\"whatsapp\"}"
                                + "}"
                                + "]"
                                + "}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        java.util.List<AgendaItem> items = client.agendaItems();

        assertEquals(1, items.size());
        assertEquals("agenda-2", items.get(0).id);
        assertEquals("2026-07-06 周一 15:30 人民广场会面", items.get(0).title);
    }

    @Test
    public void connectionStatusChecksProtectedApiAndReportsPasswordFailure() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{\"status\":\"ok\"}")
        );
        server.enqueue(
                new MockResponse()
                        .setResponseCode(401)
                        .setHeader("content-type", "application/json")
                        .setBody("{\"detail\":\"invalid password\"}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "wrong"));

        ConnectionStatus status = client.connectionStatus();

        RecordedRequest health = server.takeRequest();
        RecordedRequest protectedApi = server.takeRequest();
        assertEquals("/health", health.getPath());
        assertEquals("/api/model/status", protectedApi.getPath());
        assertEquals("wrong", protectedApi.getHeader("x-par-password"));
        assertEquals(false, status.ok);
        assertEquals("服务器可达，但访问密码不正确。", status.message);
    }

    @Test
    public void connectionStatusReportsProtectedApiAvailable() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{\"status\":\"ok\"}")
        );
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{\"providers\":[]}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        ConnectionStatus status = client.connectionStatus();

        assertEquals("/health", server.takeRequest().getPath());
        RecordedRequest protectedApi = server.takeRequest();
        assertEquals("/api/model/status", protectedApi.getPath());
        assertEquals("secret", protectedApi.getHeader("x-par-password"));
        assertTrue(status.ok);
        assertEquals("服务器可达，访问密码正确，受保护 API 可用。", status.message);
    }

    @Test
    public void assistantIdentitiesFetchesNomiOwnedAccounts() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"count\":3,"
                                + "\"identities\":["
                                + "{\"identity_id\":\"nomi_gmail_primary\",\"kind\":\"assistant_gmail\",\"display_name\":\"Nomi\",\"address\":\"nomi@example.com\",\"status\":\"connected\"},"
                                + "{\"identity_id\":\"nomi_whatsapp_primary\",\"kind\":\"assistant_whatsapp\",\"display_name\":\"Nomi\",\"address\":\"+15551234567\",\"status\":\"configured\"},"
                                + "{\"identity_id\":\"nomi_phone_primary\",\"kind\":\"assistant_phone\",\"display_name\":\"Nomi\",\"address\":\"+15557654321\",\"status\":\"configured\"}"
                                + "]"
                                + "}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        java.util.List<AssistantIdentity> identities = client.assistantIdentities();

        RecordedRequest request = server.takeRequest();
        assertEquals("/api/assistant-identities", request.getPath());
        assertEquals("secret", request.getHeader("x-par-password"));
        assertEquals(3, identities.size());
        assertEquals("Nomi Gmail · nomi@example.com · 已连接", identities.get(0).subtitle());
        assertEquals("Nomi WhatsApp · +15551234567 · 已配置", identities.get(1).subtitle());
        assertEquals("Nomi Phone · +15557654321 · 已配置", identities.get(2).subtitle());
    }

    @Test
    public void assistantIdentitiesParseProviderLifecycleCapabilitiesAndRedactedSecretState() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"count\":1,"
                                + "\"identities\":[{"
                                + "\"identity_id\":\"nomi_gmail_primary\","
                                + "\"kind\":\"assistant_gmail\","
                                + "\"display_name\":\"Nomi\","
                                + "\"address\":\"nomi.assistant@gmail.com\","
                                + "\"provider\":\"composio_gmail\","
                                + "\"capabilities\":[\"receive\",\"draft\",\"send\"],"
                                + "\"status\":\"degraded\","
                                + "\"version\":7,"
                                + "\"last_verified_at\":\"2026-07-22T06:00:00Z\","
                                + "\"last_error_code\":\"gmail_inbound_stale\","
                                + "\"secret_presence\":{\"stored\":true}"
                                + "}]}" )
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        AssistantIdentity identity = client.assistantIdentities().get(0);

        assertEquals("composio_gmail", identity.provider);
        assertEquals(java.util.List.of("receive", "draft", "send"), identity.capabilities);
        assertEquals(7L, identity.version);
        assertEquals("2026-07-22T06:00:00Z", identity.lastVerifiedAt);
        assertEquals("gmail_inbound_stale", identity.lastErrorCode);
        assertTrue(identity.secretStored);
        assertEquals("Nomi Gmail · nomi.assistant@gmail.com · 连接异常", identity.subtitle());
    }

    @Test
    public void assistantGmailConnectLinkUsesDedicatedIdentityEndpoint() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"status\":\"authorization_pending\","
                                + "\"identity_id\":\"nomi_gmail_primary\","
                                + "\"redirect_url\":\"https://connect.composio.dev/link/nomi-gmail\","
                                + "\"version\":3"
                                + "}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        String redirectUrl = client.assistantGmailConnectUrl();

        RecordedRequest request = server.takeRequest();
        assertEquals("/api/assistant-identities/nomi_gmail_primary/connect-link", request.getPath());
        assertEquals("secret", request.getHeader("x-par-password"));
        assertEquals("https://connect.composio.dev/link/nomi-gmail", redirectUrl);
    }

    @Test
    public void assistantIdentityLifecycleActionsUseExplicitEndpoints() throws Exception {
        for (int index = 0; index < 4; index++) {
            server.enqueue(
                    new MockResponse()
                            .setResponseCode(200)
                            .setHeader("content-type", "application/json")
                            .setBody("{\"status\":\"ok\"}")
            );
        }
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        client.verifyAssistantIdentity("nomi_gmail_primary");
        client.disableAssistantIdentity("nomi_gmail_primary");
        client.enableAssistantIdentity("nomi_gmail_primary");
        client.disconnectAssistantIdentity("nomi_gmail_primary");

        assertEquals("/api/assistant-identities/nomi_gmail_primary/verify", server.takeRequest().getPath());
        assertEquals("/api/assistant-identities/nomi_gmail_primary/disable", server.takeRequest().getPath());
        assertEquals("/api/assistant-identities/nomi_gmail_primary/enable", server.takeRequest().getPath());
        assertEquals("/api/assistant-identities/nomi_gmail_primary/disconnect", server.takeRequest().getPath());
    }

    @Test
    public void createAssistantDraftPostsConfirmationPayload() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"draft_id\":\"draft-1\","
                                + "\"identity_id\":\"nomi_gmail_primary\","
                                + "\"channel\":\"gmail\","
                                + "\"recipient\":\"alice@example.com\","
                                + "\"subject\":\"报价\","
                                + "\"body_text\":\"我是 Nomi。\","
                                + "\"status\":\"draft\""
                                + "}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        AssistantDraft draft = client.createAssistantDraft(
                "nomi_gmail_primary",
                "gmail",
                "alice@example.com",
                "报价",
                "我是 Nomi。"
        );

        RecordedRequest request = server.takeRequest();
        assertEquals("/api/assistant-outbound/drafts", request.getPath());
        assertEquals("secret", request.getHeader("x-par-password"));
        assertTrue(request.getBody().readUtf8().contains("\"identity_id\":\"nomi_gmail_primary\""));
        assertEquals("draft-1", draft.draftId);
        assertEquals(
                "将使用：Nomi Gmail\n状态：待确认\n收件人：alice@example.com\n主题：报价\n\n我是 Nomi。\n\n依据：0 条\n\n发送 / 编辑 / 取消",
                draft.cardText()
        );
    }

    @Test
    public void createPhoneCallDraftReturnsOneWayPlaybackCard() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"draft_id\":\"draft-call-1\","
                                + "\"identity_id\":\"nomi_phone_primary\","
                                + "\"channel\":\"phone_call\","
                                + "\"recipient\":\"+15551234567\","
                                + "\"subject\":\"\","
                                + "\"body_text\":\"我是 Nomi，张子长的个人助理。他十分钟后到。\","
                                + "\"status\":\"draft\""
                                + "}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        AssistantDraft draft = client.createAssistantDraft(
                "nomi_phone_primary",
                "phone_call",
                "+15551234567",
                "",
                "我是 Nomi，张子长的个人助理。他十分钟后到。"
        );

        RecordedRequest request = server.takeRequest();
        assertEquals("/api/assistant-outbound/drafts", request.getPath());
        assertTrue(request.getBody().readUtf8().contains("\"channel\":\"phone_call\""));
        assertEquals("draft-call-1", draft.draftId);
        assertTrue(draft.cardText().contains("将使用：Nomi Phone"));
        assertTrue(draft.cardText().contains("电话只会播放这段语音，不会实时对话"));
        assertTrue(draft.cardText().contains("拨打 / 编辑 / 取消"));
    }

    @Test
    public void assistantDraftsReadServerBackedIdentityStateAndStableDraftId() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"count\":1,"
                                + "\"items\":[{"
                                + "\"draft_id\":\"draft-shared-1\","
                                + "\"identity_id\":\"nomi_gmail_primary\","
                                + "\"channel\":\"gmail\","
                                + "\"recipient\":\"alice@example.com\","
                                + "\"subject\":\"会议确认\","
                                + "\"body_text\":\"周五下午三点见。\","
                                + "\"status\":\"draft\","
                                + "\"confirmation_required\":true,"
                                + "\"updated_at\":\"2026-07-22T10:00:00Z\""
                                + "}]}" )
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        List<AssistantDraft> drafts = client.assistantDrafts(20);

        RecordedRequest request = server.takeRequest();
        assertEquals("/api/assistant-outbound/drafts?limit=20", request.getPath());
        assertEquals("secret", request.getHeader("x-par-password"));
        assertEquals(1, drafts.size());
        AssistantDraft draft = drafts.get(0);
        assertEquals("draft-shared-1", draft.draftId);
        assertEquals("nomi_gmail_primary", draft.identityId);
        assertEquals("draft", draft.status);
        assertTrue(draft.confirmationRequired);
        assertEquals("2026-07-22T10:00:00Z", draft.updatedAt);
    }

    @Test
    public void assistantDraftConfirmationAndSendUseTheSameServerDraftId() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{\"confirmation_token\":\"confirm-one-use\"}")
        );
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{\"draft_id\":\"draft-shared-1\",\"status\":\"sent\"}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        String confirmationToken = client.confirmAssistantDraft("draft-shared-1");
        AssistantDraft sent = client.sendAssistantDraft("draft-shared-1", confirmationToken);

        RecordedRequest confirmRequest = server.takeRequest();
        RecordedRequest sendRequest = server.takeRequest();
        assertEquals("/api/assistant-outbound/drafts/draft-shared-1/confirm", confirmRequest.getPath());
        assertEquals("/api/assistant-outbound/drafts/draft-shared-1/send", sendRequest.getPath());
        assertTrue(sendRequest.getBody().readUtf8().contains("\"confirmation_token\":\"confirm-one-use\""));
        assertEquals("draft-shared-1", sent.draftId);
        assertEquals("sent", sent.status);
    }

    @Test
    public void assistantDraftsParseEvidenceAndEditTheSameServerDraftId() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"count\":1,"
                                + "\"items\":[{"
                                + "\"draft_id\":\"draft-edit-1\","
                                + "\"identity_id\":\"nomi_gmail_primary\","
                                + "\"channel\":\"gmail\","
                                + "\"recipient\":\"alice@example.com\","
                                + "\"subject\":\"旧主题\","
                                + "\"body_text\":\"旧正文\","
                                + "\"status\":\"draft\","
                                + "\"confirmation_required\":true,"
                                + "\"source_evidence_ids\":[\"evt-1\",\"evt-2\"]"
                                + "}]}" )
        );
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"draft_id\":\"draft-edit-1\","
                                + "\"identity_id\":\"nomi_gmail_primary\","
                                + "\"channel\":\"gmail\","
                                + "\"recipient\":\"alice@example.com\","
                                + "\"subject\":\"新主题\","
                                + "\"body_text\":\"新正文\","
                                + "\"status\":\"draft\","
                                + "\"confirmation_required\":true,"
                                + "\"source_evidence_ids\":[\"evt-1\",\"evt-2\"]"
                                + "}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        AssistantDraft original = client.assistantDrafts(20).get(0);
        AssistantDraft edited = client.editAssistantDraft("draft-edit-1", "新主题", "新正文");

        RecordedRequest listRequest = server.takeRequest();
        RecordedRequest editRequest = server.takeRequest();
        assertEquals("/api/assistant-outbound/drafts?limit=20", listRequest.getPath());
        assertEquals(Arrays.asList("evt-1", "evt-2"), original.sourceEvidenceIds);
        assertEquals("PATCH", editRequest.getMethod());
        assertEquals("/api/assistant-outbound/drafts/draft-edit-1", editRequest.getPath());
        String editBody = editRequest.getBody().readUtf8();
        assertTrue(editBody.contains("\"subject\":\"新主题\""));
        assertTrue(editBody.contains("\"body_text\":\"新正文\""));
        assertEquals("draft-edit-1", edited.draftId);
        assertEquals("新主题", edited.subject);
        assertEquals("新正文", edited.bodyText);
        assertEquals(Arrays.asList("evt-1", "evt-2"), edited.sourceEvidenceIds);
    }

    @Test
    public void careerBoardFetchesJobAgentStateForWorkTab() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"profiles\":[{\"id\":\"career_profile_default\",\"headline\":\"AI workflow product manager\",\"target_roles\":[\"AI Product Manager\"],\"target_locations\":[\"Shanghai\"],\"skills\":[\"LLM product\",\"workflow automation\"],\"source_event_ids\":[\"resume_evt_1\"],\"payload\":{},\"updated_at\":\"2026-06-08T09:00:00+08:00\"}],"
                                + "\"opportunities\":[{\"id\":\"job_pm_ai_1\",\"source\":\"linkedin_browser\",\"title\":\"AI Product Manager\",\"company\":\"Example AI\",\"location\":\"Shanghai\",\"url\":\"https://www.linkedin.com/jobs/view/job_pm_ai_1\",\"status\":\"tracked\",\"fit_score\":0.82,\"requirements\":[\"LLM product\",\"workflow automation\"],\"source_event_ids\":[\"job_evt_1\"],\"payload\":{},\"created_at\":\"2026-06-08T09:10:00+08:00\",\"updated_at\":\"2026-06-08T09:20:00+08:00\"}],"
                                + "\"resume_versions\":[{\"id\":\"resume_version_resume_base_1_job_pm_ai_1\",\"base_resume_id\":\"resume_base_1\",\"target_job_id\":\"job_pm_ai_1\",\"status\":\"draft\",\"source_event_ids\":[\"resume_evt_1\"],\"payload\":{\"changes\":[{\"section\":\"summary\",\"change\":\"突出 LLM product\"}]},\"created_at\":\"2026-06-08T09:30:00+08:00\",\"updated_at\":\"2026-06-08T09:30:00+08:00\"}],"
                                + "\"applications\":[{\"id\":\"application_job_pm_ai_1_submit_application\",\"job_id\":\"job_pm_ai_1\",\"status\":\"blocked_until_delegated_grant\",\"stage\":\"apply_submit_blocked\",\"next_step\":\"request_delegated_grant_and_target_manifest\",\"application_action\":\"submit_application\",\"platform\":\"linkedin\",\"source_event_ids\":[\"jd_evt_1\"],\"payload\":{},\"created_at\":\"2026-06-08T09:40:00+08:00\",\"updated_at\":\"2026-06-08T09:40:00+08:00\"}]"
                                + "}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        CareerBoardResult board = client.careerBoard();

        RecordedRequest request = server.takeRequest();
        assertEquals("/api/career/board?limit=50", request.getPath());
        assertEquals("secret", request.getHeader("x-par-password"));
        assertEquals("AI workflow product manager", board.profiles.get(0).headline);
        assertEquals("AI Product Manager", board.opportunities.get(0).title);
        assertEquals("Example AI", board.opportunities.get(0).company);
        assertEquals("匹配 82% · tracked", board.opportunities.get(0).statusLine());
        assertEquals("resume_base_1", board.resumeVersions.get(0).baseResumeId);
        assertEquals("等待授权 · request_delegated_grant_and_target_manifest", board.applications.get(0).statusLine());
    }

    @Test
    public void updateCareerApplicationPostsTrackingState() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"id\":\"application_job_pm_ai_1_submit_application\","
                                + "\"job_id\":\"job_pm_ai_1\","
                                + "\"status\":\"submitted\","
                                + "\"stage\":\"submitted\","
                                + "\"next_step\":\"prepare_interview_if_replied\","
                                + "\"application_action\":\"submit_application\","
                                + "\"platform\":\"linkedin\","
                                + "\"source_event_ids\":[\"jd_evt_1\"],"
                                + "\"payload\":{},"
                                + "\"created_at\":\"2026-06-08T09:40:00+08:00\","
                                + "\"updated_at\":\"2026-06-08T10:00:00+08:00\""
                                + "}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        JobApplicationState state = client.updateCareerApplication(
                "application_job_pm_ai_1_submit_application",
                "submitted",
                "submitted",
                "prepare_interview_if_replied",
                "用户确认已投递"
        );

        RecordedRequest request = server.takeRequest();
        assertEquals("/api/career/applications/application_job_pm_ai_1_submit_application", request.getPath());
        assertEquals("PATCH", request.getMethod());
        assertEquals("secret", request.getHeader("x-par-password"));
        String requestBody = request.getBody().readUtf8();
        assertTrue(requestBody.contains("\"status\":\"submitted\""));
        assertTrue(requestBody.contains("\"next_step\":\"prepare_interview_if_replied\""));
        assertEquals("submitted", state.status);
        assertEquals("submitted", state.stage);
        assertEquals("submitted · prepare_interview_if_replied", state.statusLine());
    }

    @Test
    public void accountStatusesPreserveCollectorHealthWhileMergingComposioAuthorization() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"collectors\":["
                                + "{"
                                + "\"source\":\"gmail\","
                                + "\"enabled\":true,"
                                + "\"paused\":false,"
                                + "\"health_status\":\"degraded\","
                                + "\"auth_status\":\"api_not_connected\","
                                + "\"browser_login_status\":\"logged_out\","
                                + "\"collection_status\":\"degraded\","
                                + "\"status_label\":\"浏览器未登录\","
                                + "\"status_detail\":\"浏览器停在 Google 登录页\""
                                + "},"
                                + "{"
                                + "\"source\":\"whatsapp\","
                                + "\"enabled\":true,"
                                + "\"paused\":false,"
                                + "\"health_status\":\"degraded\","
                                + "\"auth_status\":\"browser_required\","
                                + "\"browser_login_status\":\"logged_out\","
                                + "\"collection_status\":\"degraded\","
                                + "\"status_label\":\"未登录\","
                                + "\"status_detail\":\"请扫码登录 WhatsApp Web\""
                                + "},"
                                + "{"
                                + "\"source\":\"telegram\","
                                + "\"enabled\":true,"
                                + "\"paused\":false,"
                                + "\"health_status\":\"healthy\","
                                + "\"auth_status\":\"browser_required\","
                                + "\"browser_login_status\":\"logged_in\","
                                + "\"collection_status\":\"healthy\","
                                + "\"status_label\":\"已登录\","
                                + "\"status_detail\":\"可采集当前可见聊天列表\""
                                + "}"
                                + "]"
                                + "}")
        );
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{\"toolkits\":[{\"slug\":\"gmail\",\"connected\":true}]}")
        );
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{\"toolkits\":[]}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        java.util.Map<String, CollectorStatus> statuses = client.accountStatuses();

        assertEquals("/api/collectors/status", server.takeRequest().getPath());
        assertEquals("/api/integrations/composio/toolkits?session_kind=readonly", server.takeRequest().getPath());
        assertEquals("/api/integrations/composio/toolkits?session_kind=write", server.takeRequest().getPath());
        CollectorStatus gmail = statuses.get("gmail");
        assertEquals("degraded", gmail.healthStatus);
        assertEquals("api_connected", gmail.authStatus);
        assertEquals("logged_out", gmail.browserLoginStatus);
        assertEquals("API 已连接", gmail.statusLabel);
        assertTrue(gmail.statusDetail.contains("浏览器未登录"));

        assertEquals("未登录", statuses.get("whatsapp").displayLabel(true));
        assertEquals("已登录", statuses.get("telegram").displayLabel(true));
    }

    @Test
    public void remoteBrowserOpenReturnsCommandAndCanWaitUntilNavigationCompletes() throws Exception {
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"status\":\"queued\","
                                + "\"command_id\":\"cmd-whatsapp\","
                                + "\"source\":\"whatsapp\","
                                + "\"target_url\":\"https://web.whatsapp.com/\","
                                + "\"host_fragment\":\"web.whatsapp.com\""
                                + "}")
        );
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"command_id\":\"cmd-whatsapp\","
                                + "\"status\":\"queued\","
                                + "\"source\":\"whatsapp\","
                                + "\"target_url\":\"https://web.whatsapp.com/\""
                                + "}")
        );
        server.enqueue(
                new MockResponse()
                        .setResponseCode(200)
                        .setHeader("content-type", "application/json")
                        .setBody("{"
                                + "\"command_id\":\"cmd-whatsapp\","
                                + "\"status\":\"navigated\","
                                + "\"source\":\"whatsapp\","
                                + "\"target_url\":\"https://web.whatsapp.com/\","
                                + "\"details\":{\"url\":\"https://web.whatsapp.com/\"}"
                                + "}")
        );
        AssistantApiClient client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));

        BrowserOpenResult open = client.requestRemoteBrowserOpen("whatsapp");
        BrowserCommandStatus status = client.waitForBrowserCommand(open.commandId, 2000);

        RecordedRequest openRequest = server.takeRequest();
        RecordedRequest firstPoll = server.takeRequest();
        RecordedRequest secondPoll = server.takeRequest();
        assertEquals("/api/browser/open", openRequest.getPath());
        assertEquals("{\"source\":\"whatsapp\"}", openRequest.getBody().readUtf8());
        assertEquals("/api/browser/commands/cmd-whatsapp/status", firstPoll.getPath());
        assertEquals("/api/browser/commands/cmd-whatsapp/status", secondPoll.getPath());
        assertEquals("cmd-whatsapp", open.commandId);
        assertEquals("whatsapp", open.source);
        assertEquals("navigated", status.status);
        assertTrue(status.isNavigationReady());
    }
}
