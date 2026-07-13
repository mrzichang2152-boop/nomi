package com.par.assistant.android;

import com.par.assistant.core.AssistantSuggestion;
import com.par.assistant.core.ServerConfig;

import android.os.Handler;
import android.os.Looper;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.List;


import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;

final class RealtimeClient {
    interface Callback {
        void onProactiveMessage(ProactiveMessage message);
        void onError(String message);

        default void onChatDelta(String delta) {
        }

        default void onChatDone(String answer, String conversationId) {
        }
    }

    private final ServerConfig config;
    private final Callback callback;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final OkHttpClient client = NomiHttpClients.privateCloudBuilder().build();
    private final RealtimeConnectionState connectionState = new RealtimeConnectionState();
    private WebSocket socket;
    private boolean stopped;

    RealtimeClient(ServerConfig config, Callback callback) {
        this.config = config;
        this.callback = callback;
    }

    void start() {
        stopped = false;
        Request request = new Request.Builder().url(wsUrl()).build();
        WebSocket nextSocket = client.newWebSocket(request, new WebSocketListener() {
            @Override
            public void onOpen(WebSocket webSocket, Response response) {
                connectionState.markOpen(webSocket);
            }

            @Override
            public void onMessage(WebSocket webSocket, String text) {
                handleMessage(text);
            }

            @Override
            public void onClosing(WebSocket webSocket, int code, String reason) {
                connectionState.markClosed(webSocket);
                webSocket.close(code, reason);
            }

            @Override
            public void onClosed(WebSocket webSocket, int code, String reason) {
                connectionState.markClosed(webSocket);
                scheduleReconnect();
            }

            @Override
            public void onFailure(WebSocket webSocket, Throwable t, Response response) {
                connectionState.markClosed(webSocket);
                callback.onError(t.getMessage() == null ? "实时连接失败" : t.getMessage());
                scheduleReconnect();
            }
        });
        socket = nextSocket;
        connectionState.markConnecting(nextSocket);
    }

    void stop() {
        stopped = true;
        mainHandler.removeCallbacksAndMessages(null);
        if (socket != null) {
            socket.close(1000, "service stopped");
            connectionState.clear(socket);
            socket = null;
        }
    }

    boolean sendChatMessage(String message, String conversationId, int limit, String clientType) {
        return sendChatMessage(message, conversationId, limit, clientType, "");
    }

    boolean sendChatMessage(String message, String conversationId, int limit, String clientType, String clientRequestId) {
        return sendChatMessage(message, conversationId, limit, clientType, clientRequestId, List.of());
    }

    boolean sendChatMessage(
            String message,
            String conversationId,
            int limit,
            String clientType,
            String clientRequestId,
            List<String> attachmentIds
    ) {
        WebSocket currentSocket = socket;
        boolean hasMessage = message != null && !message.trim().isEmpty();
        boolean hasAttachments = attachmentIds != null && !attachmentIds.isEmpty();
        if (!connectionState.isOpen(currentSocket) || (!hasMessage && !hasAttachments)) {
            return false;
        }
        return currentSocket.send(chatMessagePayload(message, conversationId, limit, clientType, clientRequestId, attachmentIds));
    }

    private void scheduleReconnect() {
        if (stopped) return;
        mainHandler.postDelayed(() -> {
            if (!stopped) start();
        }, 3000L);
    }

    private void handleMessage(String text) {
        try {
            ServerEvent event = parseServerEvent(text);
            if (event == null) return;
            if (event.message != null) {
                callback.onProactiveMessage(event.message);
            } else if ("chat_delta".equals(event.type)) {
                callback.onChatDelta(event.chatDelta);
            } else if ("chat_done".equals(event.type)) {
                callback.onChatDone(event.chatAnswer, event.conversationId);
            } else if ("error".equals(event.type)) {
                callback.onError(event.chatError.isEmpty() ? "实时通道异常" : event.chatError);
            }
        } catch (Exception error) {
            callback.onError("实时消息解析失败：" + error.getMessage());
        }
    }

    static ServerEvent parseServerEvent(String text) throws Exception {
        JSONObject json = new JSONObject(text);
        String type = json.optString("type");
        if ("proactive_message".equals(type)) {
            String suggestionId = json.optString("suggestion_id", json.optString("id"));
            ProactiveMessage message = new ProactiveMessage(
                    suggestionId,
                    json.optString("title"),
                    json.optString("body"),
                    json.optString("source"),
                    type,
                    json.optString("task_id"),
                    text
            );
            if (!message.isDisplayable()) return null;
            return new ServerEvent(type, json.optString("task_id"), text, message);
        }
        if ("agent_task_delivery".equals(type)) {
            JSONObject delivery = json.optJSONObject("delivery");
            String body = delivery == null ? "" : delivery.optString("message");
            if (body.trim().isEmpty()) body = "长尾任务有新的交付结果。";
            ProactiveMessage message = new ProactiveMessage(
                    json.optString("event_id"),
                    "长尾任务完成",
                    body,
                    "long_tail_agent",
                    type,
                    json.optString("task_id"),
                    text
            );
            return new ServerEvent(type, json.optString("task_id"), text, message);
        }
        if ("agent_task_fallback".equals(type)) {
            JSONObject fallback = json.optJSONObject("fallback_decision");
            JSONObject actionCard = json.optJSONObject("action_card");
            if (actionCard == null && fallback != null) actionCard = fallback.optJSONObject("action_card");
            String title = actionCard == null ? "长尾任务需要处理" : actionCard.optString("title", "长尾任务需要处理");
            String body = actionCard == null ? "任务已暂停，请查看下一步。" : actionCard.optString("message", "任务已暂停，请查看下一步。");
            ProactiveMessage message = new ProactiveMessage(
                    json.optString("event_id"),
                    title,
                    body,
                    "long_tail_agent",
                    type,
                    json.optString("task_id"),
                    text
            );
            return new ServerEvent(type, json.optString("task_id"), text, message);
        }
        if ("chat_delta".equals(type)) {
            return new ServerEvent(
                    type,
                    "",
                    text,
                    null,
                    "",
                    json.optString("delta"),
                    "",
                    "",
                    json.optInt("elapsed_ms", -1),
                    json.optBoolean("is_first_delta", false),
                    json.optInt("stream_first_token_ms", -1),
                    json.optInt("model_first_token_ms", -1)
            );
        }
        if ("chat_done".equals(type)) {
            return new ServerEvent(
                    type,
                    "",
                    text,
                    null,
                    json.optString("conversation_id"),
                    "",
                    json.optString("answer"),
                    ""
            );
        }
        if ("error".equals(type)) {
            return new ServerEvent(type, "", text, null, "", "", "", json.optString("message"));
        }
        return null;
    }

    private String wsUrl() {
        String base = config.baseUrl();
        String wsBase;
        if (base.startsWith("https://")) {
            wsBase = "wss://" + base.substring("https://".length());
        } else if (base.startsWith("http://")) {
            wsBase = "ws://" + base.substring("http://".length());
        } else {
            wsBase = base;
        }
        String password = UrlEncoding.queryComponent(config.password());
        return wsBase + "/ws?password=" + password;
    }

    static String chatMessagePayload(String message, String conversationId, int limit, String clientType) {
        return chatMessagePayload(message, conversationId, limit, clientType, "");
    }

    static String chatMessagePayload(String message, String conversationId, int limit, String clientType, String clientRequestId) {
        return chatMessagePayload(message, conversationId, limit, clientType, clientRequestId, List.of());
    }

    static String chatMessagePayload(
            String message,
            String conversationId,
            int limit,
            String clientType,
            String clientRequestId,
            List<String> attachmentIds
    ) {
        int boundedLimit = Math.max(1, Math.min(80, limit));
        String normalizedClient = clientType == null || clientType.trim().isEmpty()
                ? "android"
                : clientType.trim();
        try {
            JSONObject json = new JSONObject()
                    .put("type", "chat_message")
                    .put("message", message == null ? "" : message)
                    .put("limit", boundedLimit)
                    .put("client_type", normalizedClient);
            if (conversationId != null && !conversationId.trim().isEmpty()) {
                json.put("conversation_id", conversationId.trim());
            }
            if (clientRequestId != null && !clientRequestId.trim().isEmpty()) {
                json.put("client_request_id", clientRequestId.trim());
            }
            JSONArray attachments = new JSONArray();
            if (attachmentIds != null) {
                for (String attachmentId : attachmentIds) {
                    if (attachmentId != null && !attachmentId.trim().isEmpty()) {
                        attachments.put(attachmentId.trim());
                    }
                }
            }
            json.put("attachment_ids", attachments);
            return json.toString();
        } catch (Exception error) {
            throw new IllegalStateException("实时聊天消息构造失败", error);
        }
    }

    static final class ServerEvent {
        final String type;
        final String taskId;
        final String rawJson;
        final ProactiveMessage message;
        final String conversationId;
        final String chatDelta;
        final String chatAnswer;
        final String chatError;
        final int elapsedMs;
        final boolean isFirstDelta;
        final int streamFirstTokenMs;
        final int modelFirstTokenMs;

        ServerEvent(String type, String taskId, String rawJson, ProactiveMessage message) {
            this(type, taskId, rawJson, message, "", "", "", "");
        }

        ServerEvent(
                String type,
                String taskId,
                String rawJson,
                ProactiveMessage message,
                String conversationId,
                String chatDelta,
                String chatAnswer,
                String chatError
        ) {
            this(type, taskId, rawJson, message, conversationId, chatDelta, chatAnswer, chatError, -1, false, -1, -1);
        }

        ServerEvent(
                String type,
                String taskId,
                String rawJson,
                ProactiveMessage message,
                String conversationId,
                String chatDelta,
                String chatAnswer,
                String chatError,
                int elapsedMs,
                boolean isFirstDelta,
                int streamFirstTokenMs,
                int modelFirstTokenMs
        ) {
            this.type = type == null ? "" : type;
            this.taskId = taskId == null ? "" : taskId;
            this.rawJson = rawJson == null ? "" : rawJson;
            this.message = message;
            this.conversationId = conversationId == null ? "" : conversationId;
            this.chatDelta = chatDelta == null ? "" : chatDelta;
            this.chatAnswer = chatAnswer == null ? "" : chatAnswer;
            this.chatError = chatError == null ? "" : chatError;
            this.elapsedMs = elapsedMs;
            this.isFirstDelta = isFirstDelta;
            this.streamFirstTokenMs = streamFirstTokenMs;
            this.modelFirstTokenMs = modelFirstTokenMs;
        }
    }
}

final class ProactiveMessage {
    final String id;
    final String title;
    final String body;
    final String source;
    final String type;
    final String taskId;
    final String rawJson;

    ProactiveMessage(String id, String title, String body, String source) {
        this(id, title, body, source, "proactive_message", "", "");
    }

    ProactiveMessage(String id, String title, String body, String source, String type, String taskId, String rawJson) {
        this.id = id;
        this.title = title == null ? "" : title;
        this.body = body == null ? "" : body;
        this.source = source == null ? "" : source;
        this.type = type == null ? "" : type;
        this.taskId = taskId == null ? "" : taskId;
        this.rawJson = rawJson == null ? "" : rawJson;
    }

    boolean isDisplayable() {
        return AssistantSuggestion.isDisplayableText(title, body);
    }
}
