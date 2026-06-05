package com.par.assistant.android;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;

import org.junit.Test;
import org.json.JSONObject;

public final class RealtimeClientTest {
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
                "{\"type\":\"chat_delta\",\"delta\":\"你好\"}"
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
        assertEquals("你好", delta.chatDelta);
        assertNotNull(done);
        assertEquals("chat_done", done.type);
        assertEquals("你好，我在。", done.chatAnswer);
        assertEquals("11111111-1111-1111-1111-111111111111", done.conversationId);
    }

    @Test
    public void buildsStreamingChatMessagePayloadForServerWebSocket() throws Exception {
        String payload = RealtimeClient.chatMessagePayload(
                "继续核对成本",
                "11111111-1111-1111-1111-111111111111",
                24,
                "android"
        );

        JSONObject json = new JSONObject(payload);
        assertEquals("chat_message", json.getString("type"));
        assertEquals("继续核对成本", json.getString("message"));
        assertEquals("11111111-1111-1111-1111-111111111111", json.getString("conversation_id"));
        assertEquals(24, json.getInt("limit"));
        assertEquals("android", json.getString("client_type"));
    }
}
