package com.par.assistant.android;

import com.par.assistant.core.AssistantSuggestion;
import com.par.assistant.core.ServerConfig;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.OutputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

final class AssistantApiClient {
    private final ServerConfig config;

    AssistantApiClient(ServerConfig config) {
        this.config = config;
    }

    boolean health() throws Exception {
        JSONObject json = request("GET", "/health", null, false);
        return "ok".equals(json.optString("status"));
    }

    String chat(String message) throws Exception {
        return chat(message, null, List.of()).answer;
    }

    ChatResult chat(String message, String conversationId, List<FloatingChatContext.Turn> clientContext) throws Exception {
        JSONObject body = new JSONObject()
                .put("message", message)
                .put("client_type", "android");
        if (conversationId != null && !conversationId.trim().isEmpty()) {
            body.put("conversation_id", conversationId.trim());
        }
        JSONArray context = new JSONArray();
        for (FloatingChatContext.Turn turn : clientContext) {
            context.put(
                    new JSONObject()
                            .put("role", turn.role)
                            .put("content", turn.content)
            );
        }
        body.put("client_context", context);
        JSONObject json = request("POST", "/api/chat", body, true);
        return new ChatResult(
                json.optString("answer", json.optString("message", "")),
                json.optString("conversation_id", conversationId == null ? "" : conversationId)
        );
    }

    List<AssistantSuggestion> suggestions() throws Exception {
        JSONArray array = requestArray("GET", "/api/suggestions", true);
        List<AssistantSuggestion> suggestions = new ArrayList<>();
        for (int index = 0; index < array.length(); index++) {
            JSONObject item = array.getJSONObject(index);
            suggestions.add(
                    new AssistantSuggestion(
                            item.getString("id"),
                            item.optString("title"),
                            item.optString("body"),
                            item.optDouble("priority", 0.0)
                    )
            );
        }
        return suggestions;
    }

    void updateSuggestion(String suggestionId, String status) throws Exception {
        JSONObject body = new JSONObject().put("status", status);
        request("PATCH", "/api/suggestions/" + suggestionId, body, true);
    }

    Map<String, CollectorStatus> collectorStatuses() throws Exception {
        JSONObject json = request("GET", "/api/collectors/status", null, true);
        JSONArray array = json.optJSONArray("collectors");
        Map<String, CollectorStatus> statuses = new HashMap<>();
        if (array == null) return statuses;
        for (int index = 0; index < array.length(); index++) {
            JSONObject item = array.getJSONObject(index);
            String source = item.optString("source", "");
            if (source.isEmpty()) continue;
            statuses.put(
                    source,
                    new CollectorStatus(
                            source,
                            item.optBoolean("enabled", true),
                            item.optBoolean("paused", false),
                            item.optString("health_status", "unknown")
                    )
            );
        }
        return statuses;
    }

    private JSONObject request(String method, String path, JSONObject body, boolean auth) throws Exception {
        String text = requestText(method, path, body, auth);
        return new JSONObject(text);
    }

    private JSONArray requestArray(String method, String path, boolean auth) throws Exception {
        String text = requestText(method, path, null, auth);
        return new JSONArray(text);
    }

    private String requestText(String method, String path, JSONObject body, boolean auth) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(config.baseUrl() + path).openConnection();
        connection.setRequestMethod(method);
        connection.setConnectTimeout(8000);
        connection.setReadTimeout(90000);
        connection.setRequestProperty("content-type", "application/json");
        if (auth) {
            connection.setRequestProperty("x-par-password", config.password());
        }
        if (body != null) {
            connection.setDoOutput(true);
            byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
            try (OutputStream output = connection.getOutputStream()) {
                output.write(bytes);
            }
        }
        int code = connection.getResponseCode();
        BufferedReader reader = new BufferedReader(
                new InputStreamReader(
                        code >= 200 && code < 300 ? connection.getInputStream() : connection.getErrorStream(),
                        StandardCharsets.UTF_8
                )
        );
        StringBuilder builder = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            builder.append(line);
        }
        if (code < 200 || code >= 300) {
            throw new IllegalStateException("HTTP " + code + ": " + builder);
        }
        return builder.toString();
    }
}

final class ChatResult {
    final String answer;
    final String conversationId;

    ChatResult(String answer, String conversationId) {
        this.answer = answer == null ? "" : answer;
        this.conversationId = conversationId == null ? "" : conversationId;
    }
}

final class CollectorStatus {
    final String source;
    final boolean enabled;
    final boolean paused;
    final String healthStatus;

    CollectorStatus(String source, boolean enabled, boolean paused, String healthStatus) {
        this.source = source;
        this.enabled = enabled;
        this.paused = paused;
        this.healthStatus = healthStatus;
    }
}
