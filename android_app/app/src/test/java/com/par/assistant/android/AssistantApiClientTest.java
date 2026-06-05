package com.par.assistant.android;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import com.par.assistant.core.ServerConfig;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;

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
                                + "{\"role\":\"user\",\"content\":\"需要\"},"
                                + "{\"role\":\"assistant\",\"content\":\"好的，我会继续核对成本与利润率。\"}"
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
        assertEquals("user", result.messages.get(0).role);
        assertEquals("需要", result.messages.get(0).content);
        assertEquals("assistant", result.messages.get(1).role);
        assertEquals("好的，我会继续核对成本与利润率。", result.messages.get(1).content);
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
        assertEquals("将使用：Nomi Gmail\n收件人：alice@example.com\n主题：报价\n\n我是 Nomi。\n\n发送 / 编辑 / 取消", draft.cardText());
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
}
