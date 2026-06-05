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
import java.net.URLEncoder;
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
        body.put("client_context_delta", context);
        JSONObject json = request("POST", "/api/chat", body, true);
        return new ChatResult(
                json.optString("answer", json.optString("message", "")),
                json.optString("conversation_id", conversationId == null ? "" : conversationId)
        );
    }

    ChatHistoryResult chatHistory(String conversationId, int limit) throws Exception {
        int safeLimit = Math.max(1, Math.min(200, limit));
        StringBuilder path = new StringBuilder("/api/chat/history?limit=").append(safeLimit);
        String cleanConversationId = conversationId == null ? "" : conversationId.trim();
        if (!cleanConversationId.isEmpty()) {
            path.append("&conversation_id=")
                    .append(URLEncoder.encode(cleanConversationId, StandardCharsets.UTF_8));
        }
        JSONObject json = request("GET", path.toString(), null, true);
        JSONArray messagesJson = json.optJSONArray("messages");
        List<ChatHistoryMessage> messages = new ArrayList<>();
        if (messagesJson != null) {
            for (int index = 0; index < messagesJson.length(); index++) {
                JSONObject item = messagesJson.getJSONObject(index);
                String role = item.optString("role", "").trim();
                String content = item.optString("content", "").trim();
                if (role.isEmpty() || content.isEmpty()) continue;
                if (!"user".equals(role) && !"assistant".equals(role)) continue;
                messages.add(new ChatHistoryMessage(role, content));
            }
        }
        return new ChatHistoryResult(json.optString("conversation_id", ""), messages);
    }

    List<AssistantIdentity> assistantIdentities() throws Exception {
        JSONObject json = request("GET", "/api/assistant-identities", null, true);
        JSONArray identitiesJson = json.optJSONArray("identities");
        List<AssistantIdentity> identities = new ArrayList<>();
        if (identitiesJson == null) return identities;
        for (int index = 0; index < identitiesJson.length(); index++) {
            JSONObject item = identitiesJson.getJSONObject(index);
            identities.add(
                    new AssistantIdentity(
                            item.optString("identity_id"),
                            item.optString("kind"),
                            item.optString("display_name"),
                            item.optString("address"),
                            item.optString("status")
                    )
            );
        }
        return identities;
    }

    AssistantDraft createAssistantDraft(
            String identityId,
            String channel,
            String recipient,
            String subject,
            String bodyText
    ) throws Exception {
        JSONObject body = new JSONObject()
                .put("identity_id", identityId == null ? "" : identityId)
                .put("channel", channel == null ? "" : channel)
                .put("recipient", recipient == null ? "" : recipient)
                .put("subject", subject == null ? "" : subject)
                .put("body_text", bodyText == null ? "" : bodyText);
        JSONObject json = request("POST", "/api/assistant-outbound/drafts", body, true);
        return new AssistantDraft(
                json.optString("draft_id"),
                assistantIdentityLabel(json.optString("identity_id"), json.optString("channel")),
                json.optString("channel"),
                json.optString("recipient"),
                json.optString("subject"),
                json.optString("body_text")
        );
    }

    private String assistantIdentityLabel(String identityId, String channel) {
        String normalizedChannel = channel == null ? "" : channel.trim().toLowerCase();
        String kind;
        if ("whatsapp".equals(normalizedChannel)) {
            kind = "assistant_whatsapp";
        } else if ("sms".equals(normalizedChannel) || "phone_call".equals(normalizedChannel) || identityId.startsWith("nomi_phone")) {
            kind = "assistant_phone";
        } else {
            kind = "assistant_gmail";
        }
        return new AssistantIdentity(identityId, kind, "Nomi", "", "configured").channelLabel();
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

    Map<String, CollectorStatus> accountStatuses() throws Exception {
        Map<String, CollectorStatus> statuses = collectorStatuses();
        mergeComposioToolkitStatuses(statuses, "readonly");
        mergeComposioToolkitStatuses(statuses, "write");
        return statuses;
    }

    private void mergeComposioToolkitStatuses(Map<String, CollectorStatus> statuses, String sessionKind) throws Exception {
        JSONObject json = request("GET", "/api/integrations/composio/toolkits?session_kind=" + sessionKind, null, true);
        JSONArray array = json.optJSONArray("toolkits");
        if (array == null) return;
        for (int index = 0; index < array.length(); index++) {
            JSONObject item = array.getJSONObject(index);
            String source = sourceForComposioToolkit(item.optString("slug", ""));
            if (source.isEmpty()) continue;
            boolean connected = item.optBoolean("connected", false);
            CollectorStatus previous = statuses.get(source);
            if (previous != null && "healthy".equals(previous.healthStatus)) continue;
            statuses.put(
                    source,
                    new CollectorStatus(
                            source,
                            true,
                            false,
                            connected ? "healthy" : "degraded"
                    )
            );
        }
    }

    private String sourceForComposioToolkit(String slug) {
        String normalized = slug == null ? "" : slug.trim().toLowerCase();
        switch (normalized) {
            case "gmail":
                return "gmail";
            case "googlecalendar":
                return "calendar";
            default:
                return "";
        }
    }

    String composioConnectUrl(String toolkitSlug) throws Exception {
        String slug = toolkitSlug == null ? "" : toolkitSlug.trim();
        if (slug.isEmpty()) {
            throw new IllegalArgumentException("toolkit slug is required");
        }
        JSONObject json = request("POST", "/api/integrations/composio/connect/" + slug, null, true);
        if ("already_connected".equals(json.optString("status", ""))) {
            throw new IllegalStateException(slug + " 已经授权，不需要重新打开授权页");
        }
        String redirectUrl = json.optString("redirect_url", "").trim();
        if (redirectUrl.isEmpty()) {
            throw new IllegalStateException("Composio did not return an authorization link");
        }
        return redirectUrl;
    }

    void requestRemoteBrowserOpen(String source) throws Exception {
        String normalized = source == null ? "" : source.trim();
        if (normalized.isEmpty()) {
            throw new IllegalArgumentException("source is required");
        }
        request("POST", "/api/browser/open", new JSONObject().put("source", normalized), true);
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

final class ChatHistoryResult {
    final String conversationId;
    final List<ChatHistoryMessage> messages;

    ChatHistoryResult(String conversationId, List<ChatHistoryMessage> messages) {
        this.conversationId = conversationId == null ? "" : conversationId;
        this.messages = messages == null ? List.of() : List.copyOf(messages);
    }
}

final class ChatHistoryMessage {
    final String role;
    final String content;

    ChatHistoryMessage(String role, String content) {
        this.role = role == null ? "" : role;
        this.content = content == null ? "" : content;
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
