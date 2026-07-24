package com.par.assistant.android;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;

import org.junit.Test;
import org.json.JSONObject;

import java.util.List;

public final class RealtimeClientTest {
    @Test
    public void parsesProactiveSuggestionIdAndKeepsRawJsonForWorkspaceDeepLink() throws Exception {
        String json = "{"
                + "\"type\":\"proactive_message\","
                + "\"id\":\"fallback-id\","
                + "\"suggestion_id\":\"suggestion-123\","
                + "\"title\":\"可能值得关注\","
                + "\"body\":\"客户问 PHONE_1 报价什么时候截止。\","
                + "\"source\":\"whatsapp\","
                + "\"actions\":[{\"id\":\"reply_draft\",\"label\":\"起草回复\"}]"
                + "}";

        RealtimeClient.ServerEvent event = RealtimeClient.parseServerEvent(json);

        assertNotNull(event);
        assertEquals("proactive_message", event.type);
        assertEquals("suggestion-123", event.message.id);
        assertEquals("可能值得关注", event.message.title);
        assertEquals("客户问 PHONE_1 报价什么时候截止。", event.message.body);
        assertEquals("whatsapp", event.message.source);
        assertEquals(json, event.message.rawJson);
    }

    @Test
    public void suppressesNotificationCounterNoiseFromProactiveBubbles() throws Exception {
        String json = "{"
                + "\"type\":\"proactive_message\","
                + "\"suggestion_id\":\"noise-1\","
                + "\"title\":\"处理邮件待办\","
                + "\"body\":\"这封邮件可能需要处理：0 notifications total\","
                + "\"source\":\"gmail\""
                + "}";

        assertNull(RealtimeClient.parseServerEvent(json));
    }

    @Test
    public void parsesAgentTaskDeliveryIntoActionableBubbleMessage() throws Exception {
        String json = "{"
                + "\"type\":\"agent_task_delivery\","
                + "\"task_id\":\"lta_1\","
                + "\"delivery\":{"
                + "\"message\":\"已完成：邮件草稿已准备\","
                + "\"actions\":[{\"id\":\"review_external_effect_rollback\",\"effect_id\":\"effect_1\",\"label\":\"查看回滚与补偿\"}]"
                + "}"
                + "}";

        RealtimeClient.ServerEvent event = RealtimeClient.parseServerEvent(json);

        assertNotNull(event);
        assertEquals("agent_task_delivery", event.type);
        assertEquals("lta_1", event.taskId);
        assertEquals("长尾任务完成", event.message.title);
        assertEquals("已完成：邮件草稿已准备", event.message.body);
        assertEquals(json, event.rawJson);
    }

    @Test
    public void parsesAgentTaskFallbackActionCardIntoCompensationBubbleMessage() throws Exception {
        String json = "{"
                + "\"type\":\"agent_task_fallback\","
                + "\"task_id\":\"lta_2\","
                + "\"fallback_decision\":{"
                + "\"action_card\":{"
                + "\"title\":\"发现禁止的外部动作\","
                + "\"message\":\"不能假装已经撤回第三方动作，只能准备补偿。\","
                + "\"actions\":[{\"id\":\"review_external_effects\",\"label\":\"查看外部动作与补偿\"}]"
                + "}"
                + "}"
                + "}";

        RealtimeClient.ServerEvent event = RealtimeClient.parseServerEvent(json);

        assertNotNull(event);
        assertEquals("agent_task_fallback", event.type);
        assertEquals("lta_2", event.taskId);
        assertEquals("发现禁止的外部动作", event.message.title);
        assertEquals("不能假装已经撤回第三方动作，只能准备补偿。", event.message.body);
        assertEquals(json, event.rawJson);
    }

    @Test
    public void parsesStreamingChatDeltaAndDoneEvents() throws Exception {
        RealtimeClient.ServerEvent delta = RealtimeClient.parseServerEvent(
                "{"
                        + "\"type\":\"chat_delta\","
                        + "\"delta\":\"你\","
                        + "\"elapsed_ms\":1200,"
                        + "\"is_first_delta\":true,"
                        + "\"stream_first_token_ms\":1200,"
                        + "\"model_first_token_ms\":900"
                        + "}"
        );
        RealtimeClient.ServerEvent done = RealtimeClient.parseServerEvent(
                "{"
                        + "\"type\":\"chat_done\","
                        + "\"answer\":\"你好，我在。\","
                        + "\"conversation_id\":\"11111111-1111-1111-1111-111111111111\""
                        + "}"
        );

        assertNotNull(delta);
        assertEquals("chat_delta", delta.type);
        assertEquals("你", delta.chatDelta);
        assertEquals(1200, delta.elapsedMs);
        assertEquals(true, delta.isFirstDelta);
        assertEquals(1200, delta.streamFirstTokenMs);
        assertEquals(900, delta.modelFirstTokenMs);
        assertNotNull(done);
        assertEquals("chat_done", done.type);
        assertEquals("你好，我在。", done.chatAnswer);
        assertEquals("11111111-1111-1111-1111-111111111111", done.conversationId);
    }

    @Test
    public void parsesStreamingChatDoneArtifactCards() throws Exception {
        RealtimeClient.ServerEvent done = RealtimeClient.parseServerEvent(
                "{"
                        + "\"type\":\"chat_done\","
                        + "\"answer\":\"PPT 已生成，可以下载。\","
                        + "\"conversation_id\":\"conv-artifact\","
                        + "\"artifacts\":[{"
                        + "\"artifact_id\":\"artifact_1\","
                        + "\"task_run_id\":\"lta_1\","
                        + "\"artifact_type\":\"pptx\","
                        + "\"filename\":\"普通人也能理解_LLM.pptx\","
                        + "\"download_url\":\"/api/artifacts/artifact_1/download\","
                        + "\"verification_status\":\"verified\""
                        + "}]"
                        + "}"
        );

        assertNotNull(done);
        assertEquals(1, done.artifacts.size());
        ChatArtifact artifact = done.artifacts.get(0);
        assertEquals("artifact_1", artifact.artifactId);
        assertEquals("普通人也能理解_LLM.pptx", artifact.filename);
        assertEquals("PPTX · 已校验", artifact.statusLine());
    }

    @Test
    public void parsesStreamingChatDoneArtifactCardsFromTaskPayload() throws Exception {
        RealtimeClient.ServerEvent done = RealtimeClient.parseServerEvent(
                "{"
                        + "\"type\":\"chat_done\","
                        + "\"answer\":\"PPT 已生成，可以下载。\","
                        + "\"conversation_id\":\"conv-artifact\","
                        + "\"task\":{"
                        + "\"status\":\"completed\","
                        + "\"artifacts\":[{"
                        + "\"artifact_id\":\"artifact_nested\","
                        + "\"task_run_id\":\"lta_nested\","
                        + "\"artifact_type\":\"pptx\","
                        + "\"filename\":\"LLM工作原理.pptx\","
                        + "\"download_url\":\"http://testserver/api/artifacts/artifact_nested/download\","
                        + "\"verification_status\":\"verified\""
                        + "}]"
                        + "}"
                        + "}"
        );

        assertNotNull(done);
        assertEquals(1, done.artifacts.size());
        assertEquals("artifact_nested", done.artifacts.get(0).artifactId);
        assertEquals("LLM工作原理.pptx", done.artifacts.get(0).filename);
    }

    @Test
    public void parsesStreamingChatDoneTaskRunIdWhenArtifactIsGeneratedLater() throws Exception {
        RealtimeClient.ServerEvent done = RealtimeClient.parseServerEvent(
                "{"
                        + "\"type\":\"chat_done\","
                        + "\"answer\":\"我已把 PPT 任务交给 OpenCode 处理。\","
                        + "\"conversation_id\":\"conv-async-artifact\","
                        + "\"task\":{"
                        + "\"task_run_id\":\"lta_async_realtime\","
                        + "\"status\":\"running\""
                        + "}"
                        + "}"
        );

        assertNotNull(done);
        assertEquals("chat_done", done.type);
        assertEquals("lta_async_realtime", done.taskId);
        assertEquals("我已把 PPT 任务交给 OpenCode 处理。", done.chatAnswer);
        assertEquals(0, done.artifacts.size());
    }

    @Test
    public void parsesStreamingChatDoneWithoutTaskRunIdForClarificationTask() throws Exception {
        RealtimeClient.ServerEvent done = RealtimeClient.parseServerEvent(
                "{"
                        + "\"type\":\"chat_done\","
                        + "\"answer\":\"可以。我先确认两点：讲给谁？偏科普还是技术？\","
                        + "\"conversation_id\":\"conv-clarify\","
                        + "\"task\":{"
                        + "\"task_run_id\":\"lta_clarify_realtime\","
                        + "\"status\":\"waiting_user\","
                        + "\"current_node\":\"waiting_for_human_input\","
                        + "\"clarification\":{\"missing_fields\":[\"audience\",\"depth\"]}"
                        + "}"
                        + "}"
        );

        assertNotNull(done);
        assertEquals("chat_done", done.type);
        assertEquals("", done.taskId);
        assertEquals("可以。我先确认两点：讲给谁？偏科普还是技术？", done.chatAnswer);
        assertEquals(0, done.artifacts.size());
    }

    @Test
    public void buildsStreamingChatMessagePayloadForServerWebSocket() throws Exception {
        String payload = RealtimeClient.chatMessagePayload(
                "继续核对成本",
                "11111111-1111-1111-1111-111111111111",
                24,
                "android",
                "android-request-1"
        );

        JSONObject json = new JSONObject(payload);
        assertEquals("chat_message", json.getString("type"));
        assertEquals("继续核对成本", json.getString("message"));
        assertEquals("11111111-1111-1111-1111-111111111111", json.getString("conversation_id"));
        assertEquals(24, json.getInt("limit"));
        assertEquals("android", json.getString("client_type"));
        assertEquals("android-request-1", json.getString("client_request_id"));
    }

    @Test
    public void buildsAttachmentOnlyStreamingPayloadWithOrderedIdsAndSameRequestId() throws Exception {
        String payload = RealtimeClient.chatMessagePayload(
                "",
                "conv-a",
                24,
                "android",
                "android-request-a",
                List.of("attachment-1", "attachment-2")
        );

        JSONObject json = new JSONObject(payload);
        assertEquals("", json.getString("message"));
        assertEquals("android-request-a", json.getString("client_request_id"));
        assertEquals("attachment-1", json.getJSONArray("attachment_ids").getString(0));
        assertEquals("attachment-2", json.getJSONArray("attachment_ids").getString(1));
    }
}
