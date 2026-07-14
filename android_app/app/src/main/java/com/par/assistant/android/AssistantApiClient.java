package com.par.assistant.android;

import com.par.assistant.core.AssistantSuggestion;
import com.par.assistant.core.ServerConfig;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

final class AssistantApiClient {
    private static final MediaType JSON = MediaType.get("application/json; charset=utf-8");
    private static final int CHAT_TRANSIENT_MAX_ATTEMPTS = 5;
    private static final long CHAT_TRANSIENT_RETRY_BASE_DELAY_MS = 500L;
    private final ServerConfig config;
    private final OkHttpClient httpClient = NomiHttpClients.privateCloudBuilder()
            .connectTimeout(8, TimeUnit.SECONDS)
            .readTimeout(90, TimeUnit.SECONDS)
            .build();

    AssistantApiClient(ServerConfig config) {
        this.config = config;
    }

    boolean health() throws Exception {
        JSONObject json = request("GET", "/health", null, false);
        return "ok".equals(json.optString("status"));
    }

    ConnectionStatus connectionStatus() {
        try {
            if (!health()) {
                return new ConnectionStatus(false, "服务器可达，但 /health 状态异常。");
            }
        } catch (Exception error) {
            return new ConnectionStatus(false, "服务器不可达：" + error.getMessage());
        }
        try {
            request("GET", "/api/model/status", null, true);
            return new ConnectionStatus(true, "服务器可达，访问密码正确，受保护 API 可用。");
        } catch (Exception error) {
            String message = error.getMessage() == null ? "" : error.getMessage();
            if (message.contains("HTTP 401")) {
                return new ConnectionStatus(false, "服务器可达，但访问密码不正确。");
            }
            return new ConnectionStatus(false, "服务器可达，但受保护 API 不可用：" + message);
        }
    }

    String chat(String message) throws Exception {
        return chat(message, null, List.of()).answer;
    }

    ChatResult chat(String message, String conversationId, List<FloatingChatContext.Turn> clientContext) throws Exception {
        return chat(message, conversationId, clientContext, "");
    }

    ChatResult chat(
            String message,
            String conversationId,
            List<FloatingChatContext.Turn> clientContext,
            String clientRequestId
    ) throws Exception {
        return chat(message, conversationId, clientContext, clientRequestId, List.of());
    }

    ChatResult chat(
            String message,
            String conversationId,
            List<FloatingChatContext.Turn> clientContext,
            String clientRequestId,
            List<String> attachmentIds
    ) throws Exception {
        JSONObject body = new JSONObject()
                .put("message", message)
                .put("client_type", "android");
        if (conversationId != null && !conversationId.trim().isEmpty()) {
            body.put("conversation_id", conversationId.trim());
        }
        if (clientRequestId != null && !clientRequestId.trim().isEmpty()) {
            body.put("client_request_id", clientRequestId.trim());
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
        JSONArray attachments = new JSONArray();
        if (attachmentIds != null) {
            for (String attachmentId : attachmentIds) {
                if (attachmentId != null && !attachmentId.trim().isEmpty()) {
                    attachments.put(attachmentId.trim());
                }
            }
        }
        body.put("attachment_ids", attachments);
        JSONObject json = requestChatWithTransientRetry(body);
        return new ChatResult(
                json.optString("answer", json.optString("message", "")),
                json.optString("conversation_id", conversationId == null ? "" : conversationId)
        );
    }

    ChatAttachment uploadAttachment(AttachmentDraft draft, RequestBody fileBody) throws Exception {
        if (draft == null) throw new IllegalArgumentException("attachment draft is required");
        if (fileBody == null) throw new IllegalArgumentException("attachment body is required");
        MultipartBody multipart = new MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("client_upload_id", draft.clientUploadId)
                .addFormDataPart("file", draft.filename, fileBody)
                .build();
        Request request = authenticatedRequestBuilder("/api/chat/attachments")
                .post(multipart)
                .build();
        return parseAttachment(executeJson(request), draft.clientUploadId);
    }

    ChatAttachment attachmentStatus(String attachmentId) throws Exception {
        String id = requiredAttachmentId(attachmentId);
        return parseAttachment(request("GET", "/api/chat/attachments/" + id, null, true), "");
    }

    ChatAttachment retryAttachment(String attachmentId) throws Exception {
        String id = requiredAttachmentId(attachmentId);
        return parseAttachment(request("POST", "/api/chat/attachments/" + id + "/retry", null, true), "");
    }

    void deleteAttachment(String attachmentId) throws Exception {
        String id = requiredAttachmentId(attachmentId);
        requestText("DELETE", "/api/chat/attachments/" + id, null, true);
    }

    private String requiredAttachmentId(String attachmentId) {
        String id = attachmentId == null ? "" : attachmentId.trim();
        if (id.isEmpty()) throw new IllegalArgumentException("attachment id is required");
        return id;
    }

    private ChatAttachment parseAttachment(JSONObject json, String clientUploadId) {
        return new ChatAttachment(
                json.optString("attachment_id"),
                clientUploadId,
                json.optString("filename"),
                json.optString("mime_type"),
                json.optLong("byte_size", 0L),
                json.optString("status"),
                json.optString("kind"),
                json.optString("preview_url"),
                json.optString("content_url"),
                json.optString("error_message", json.optString("error_code"))
        );
    }

    ChatHistoryResult chatHistory(String conversationId, int limit) throws Exception {
        int safeLimit = Math.max(1, Math.min(200, limit));
        StringBuilder path = new StringBuilder("/api/chat/history?limit=").append(safeLimit);
        String cleanConversationId = conversationId == null ? "" : conversationId.trim();
        if (!cleanConversationId.isEmpty()) {
            path.append("&conversation_id=")
                    .append(UrlEncoding.queryComponent(cleanConversationId));
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
                String messageId = item.optString("id", "").trim();
                JSONArray attachmentsJson = item.optJSONArray("attachments");
                List<ChatHistoryAttachment> attachments = new ArrayList<>();
                if (attachmentsJson != null) {
                    for (int attachmentIndex = 0; attachmentIndex < attachmentsJson.length(); attachmentIndex++) {
                        JSONObject attachment = attachmentsJson.optJSONObject(attachmentIndex);
                        if (attachment == null) continue;
                        attachments.add(
                                new ChatHistoryAttachment(
                                        messageId,
                                        attachment.optString("attachment_id"),
                                        attachment.optString("filename"),
                                        attachment.optString("mime_type"),
                                        attachment.optLong("byte_size", 0L),
                                        attachment.optString("status"),
                                        attachment.optString("kind"),
                                        attachment.optString("preview_url"),
                                        attachment.optString("content_url"),
                                        attachment.optInt("ordinal", attachmentIndex)
                                )
                        );
                    }
                }
                messages.add(
                        new ChatHistoryMessage(
                                messageId,
                                item.optString("created_at", ""),
                                role,
                                content,
                                attachments
                        )
                );
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
                            item.optString("health_status", "unknown"),
                            item.optString("auth_status", ""),
                            item.optString("browser_login_status", ""),
                            item.optString("collection_status", ""),
                            item.optString("status_label", ""),
                            item.optString("status_detail", "")
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
            if (previous == null) {
                previous = new CollectorStatus(source, true, false, "unknown");
            }
            statuses.put(source, previous.withComposioConnection(connected));
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

    List<AgendaItem> agendaItems() throws Exception {
        JSONObject json = request("GET", "/api/agenda?status=scheduled&limit=50", null, true);
        JSONArray array = json.optJSONArray("items");
        List<AgendaItem> items = new ArrayList<>();
        if (array == null) return items;
        for (int index = 0; index < array.length(); index++) {
            JSONObject item = array.getJSONObject(index);
            String status = item.optString("status");
            if (!isActiveAgendaStatus(status)) {
                continue;
            }
            JSONObject timeWindow = item.optJSONObject("time_window");
            JSONObject metadata = item.optJSONObject("metadata");
            items.add(
                    new AgendaItem(
                            item.optString("id"),
                            item.optString("title"),
                            status,
                            item.optString("certainty"),
                            timeWindow == null ? "" : timeWindow.optString("display", timeWindow.optString("text", "")),
                            item.optString("place"),
                            stringList(item.optJSONArray("participants")),
                            stringList(item.optJSONArray("missing_fields")),
                            metadata == null ? "" : metadata.optString("source", "")
                    )
            );
        }
        return items;
    }

    private boolean isActiveAgendaStatus(String status) {
        String normalized = status == null ? "" : status.trim().toLowerCase();
        return !normalized.equals("dismissed")
                && !normalized.equals("canceled")
                && !normalized.equals("cancelled")
                && !normalized.equals("done")
                && !normalized.equals("completed");
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

    BrowserOpenResult requestRemoteBrowserOpen(String source) throws Exception {
        String normalized = source == null ? "" : source.trim();
        if (normalized.isEmpty()) {
            throw new IllegalArgumentException("source is required");
        }
        JSONObject json = request("POST", "/api/browser/open", new JSONObject().put("source", normalized), true);
        return new BrowserOpenResult(
                json.optString("command_id"),
                json.optString("status"),
                json.optString("source"),
                json.optString("target_url"),
                json.optString("host_fragment")
        );
    }

    BrowserOpenResult requestRemoteBrowserOpenLinkedInJob(String jobUrl) throws Exception {
        String cleanUrl = jobUrl == null ? "" : jobUrl.trim();
        if (cleanUrl.isEmpty()) {
            throw new IllegalArgumentException("job url is required");
        }
        JSONObject json = request(
                "POST",
                "/api/browser/open-linkedin-job",
                new JSONObject().put("job_url", cleanUrl),
                true
        );
        return new BrowserOpenResult(
                json.optString("command_id"),
                json.optString("status"),
                json.optString("source"),
                json.optString("target_url"),
                json.optString("host_fragment")
        );
    }

    BrowserCommandStatus browserCommandStatus(String commandId) throws Exception {
        String cleanId = commandId == null ? "" : commandId.trim();
        if (cleanId.isEmpty()) {
            throw new IllegalArgumentException("command id is required");
        }
        JSONObject json = request("GET", "/api/browser/commands/" + cleanId + "/status", null, true);
        JSONObject details = json.optJSONObject("details");
        return new BrowserCommandStatus(
                json.optString("command_id"),
                json.optString("status"),
                json.optString("source"),
                json.optString("target_url"),
                details == null ? "" : details.optString("url", details.optString("target_url", ""))
        );
    }

    BrowserCommandStatus waitForBrowserCommand(String commandId, long timeoutMs) throws Exception {
        long deadline = System.currentTimeMillis() + Math.max(0L, timeoutMs);
        BrowserCommandStatus last = null;
        while (System.currentTimeMillis() <= deadline) {
            last = browserCommandStatus(commandId);
            if (last.isTerminal()) {
                return last;
            }
            Thread.sleep(250L);
        }
        if (last != null) {
            return last;
        }
        throw new IllegalStateException("remote browser command did not return a status");
    }

    void requestRemoteBrowserType(String text, boolean submit) throws Exception {
        String cleanText = text == null ? "" : text.trim();
        if (cleanText.isEmpty()) {
            throw new IllegalArgumentException("text is required");
        }
        request(
                "POST",
                "/api/browser/type",
                new JSONObject()
                        .put("text", cleanText)
                        .put("submit", submit),
                true
        );
    }

    CareerBoardResult careerBoard() throws Exception {
        JSONObject json = request("GET", "/api/career/board?limit=50", null, true);
        List<CareerProfile> profiles = new ArrayList<>();
        List<JobOpportunity> opportunities = new ArrayList<>();
        List<ResumeVersion> resumeVersions = new ArrayList<>();
        List<JobApplicationState> applications = new ArrayList<>();

        JSONArray profileJson = json.optJSONArray("profiles");
        if (profileJson != null) {
            for (int index = 0; index < profileJson.length(); index++) {
                JSONObject item = profileJson.getJSONObject(index);
                profiles.add(
                        new CareerProfile(
                                item.optString("id"),
                                item.optString("headline"),
                                stringList(item.optJSONArray("target_roles")),
                                stringList(item.optJSONArray("target_locations")),
                                stringList(item.optJSONArray("skills"))
                        )
                );
            }
        }

        JSONArray opportunityJson = json.optJSONArray("opportunities");
        if (opportunityJson != null) {
            for (int index = 0; index < opportunityJson.length(); index++) {
                JSONObject item = opportunityJson.getJSONObject(index);
                double fitScore = item.has("fit_score") && !item.isNull("fit_score") ? item.optDouble("fit_score", -1.0) : -1.0;
                opportunities.add(
                        new JobOpportunity(
                                item.optString("id"),
                                item.optString("source"),
                                item.optString("title"),
                                item.optString("company"),
                                item.optString("location"),
                                item.optString("url"),
                                item.optString("status"),
                                fitScore,
                                stringList(item.optJSONArray("requirements"))
                        )
                );
            }
        }

        JSONArray resumeJson = json.optJSONArray("resume_versions");
        if (resumeJson != null) {
            for (int index = 0; index < resumeJson.length(); index++) {
                JSONObject item = resumeJson.getJSONObject(index);
                resumeVersions.add(
                        new ResumeVersion(
                                item.optString("id"),
                                item.optString("base_resume_id"),
                                item.optString("target_job_id"),
                                item.optString("status")
                        )
                );
            }
        }

        JSONArray applicationJson = json.optJSONArray("applications");
        if (applicationJson != null) {
            for (int index = 0; index < applicationJson.length(); index++) {
                applications.add(parseJobApplicationState(applicationJson.getJSONObject(index)));
            }
        }

        return new CareerBoardResult(profiles, opportunities, resumeVersions, applications);
    }

    JobApplicationState updateCareerApplication(
            String applicationId,
            String status,
            String stage,
            String nextStep,
            String userNote
    ) throws Exception {
        String cleanId = applicationId == null ? "" : applicationId.trim();
        if (cleanId.isEmpty()) {
            throw new IllegalArgumentException("application id is required");
        }
        JSONObject body = new JSONObject()
                .put("status", status == null ? JSONObject.NULL : status)
                .put("stage", stage == null ? JSONObject.NULL : stage)
                .put("next_step", nextStep == null ? JSONObject.NULL : nextStep)
                .put("user_note", userNote == null ? JSONObject.NULL : userNote);
        JSONObject json = request("PATCH", "/api/career/applications/" + UrlEncoding.queryComponent(cleanId), body, true);
        return parseJobApplicationState(json);
    }

    private JobApplicationState parseJobApplicationState(JSONObject item) {
        return new JobApplicationState(
                item.optString("id"),
                item.optString("job_id"),
                item.optString("status"),
                item.optString("stage"),
                item.optString("next_step"),
                item.optString("application_action"),
                item.optString("platform")
        );
    }

    private List<String> stringList(JSONArray array) {
        List<String> values = new ArrayList<>();
        if (array == null) return values;
        for (int index = 0; index < array.length(); index++) {
            String value = array.optString(index, "").trim();
            if (!value.isEmpty()) values.add(value);
        }
        return values;
    }

    private JSONObject request(String method, String path, JSONObject body, boolean auth) throws Exception {
        String text = requestText(method, path, body, auth);
        return new JSONObject(text);
    }

    private JSONObject requestChatWithTransientRetry(JSONObject body) throws Exception {
        Exception lastError = null;
        for (int attempt = 1; attempt <= CHAT_TRANSIENT_MAX_ATTEMPTS; attempt++) {
            try {
                return request("POST", "/api/chat", body, true);
            } catch (Exception error) {
                lastError = error;
                if (attempt >= CHAT_TRANSIENT_MAX_ATTEMPTS || !isTransientChatError(error)) {
                    throw error;
                }
                Thread.sleep(CHAT_TRANSIENT_RETRY_BASE_DELAY_MS * attempt);
            }
        }
        throw lastError == null ? new IllegalStateException("chat request failed") : lastError;
    }

    private boolean isTransientChatError(Exception error) {
        String message = error.getMessage();
        if (message == null) return false;
        String lower = message.toLowerCase();
        return lower.contains("http 502")
                || lower.contains("http 503")
                || lower.contains("http 504")
                || lower.contains("bad gateway")
                || lower.contains("gateway timeout")
                || lower.contains("connection refused")
                || lower.contains("failed to connect")
                || lower.contains("timeout");
    }

    private JSONArray requestArray(String method, String path, boolean auth) throws Exception {
        String text = requestText(method, path, null, auth);
        return new JSONArray(text);
    }

    private String requestText(String method, String path, JSONObject body, boolean auth) throws Exception {
        Request.Builder builder = new Request.Builder()
                .url(config.baseUrl() + path)
                .header("content-type", "application/json");
        if (auth) {
            builder.header("x-par-password", config.password());
        }
        RequestBody requestBody = body == null
                ? null
                : RequestBody.create(body.toString(), JSON);
        if (body != null) {
            builder.method(method, requestBody);
        } else if ("GET".equals(method)) {
            builder.get();
        } else {
            builder.method(method, RequestBody.create(new byte[0], JSON));
        }
        return executeText(builder.build());
    }

    private Request.Builder authenticatedRequestBuilder(String path) {
        return new Request.Builder()
                .url(config.baseUrl() + path)
                .header("x-par-password", config.password());
    }

    private JSONObject executeJson(Request request) throws Exception {
        return new JSONObject(executeText(request));
    }

    private String executeText(Request request) throws Exception {
        Response response = httpClient.newCall(request).execute();
        int code = response.code();
        String text = response.body() == null ? "" : response.body().string();
        response.close();
        if (code < 200 || code >= 300) {
            throw new IllegalStateException("HTTP " + code + ": " + text);
        }
        return text;
    }
}

final class BrowserOpenResult {
    final String commandId;
    final String status;
    final String source;
    final String targetUrl;
    final String hostFragment;

    BrowserOpenResult(String commandId, String status, String source, String targetUrl, String hostFragment) {
        this.commandId = commandId == null ? "" : commandId;
        this.status = status == null ? "" : status;
        this.source = source == null ? "" : source;
        this.targetUrl = targetUrl == null ? "" : targetUrl;
        this.hostFragment = hostFragment == null ? "" : hostFragment;
    }
}

final class BrowserCommandStatus {
    final String commandId;
    final String status;
    final String source;
    final String targetUrl;
    final String currentUrl;

    BrowserCommandStatus(String commandId, String status, String source, String targetUrl, String currentUrl) {
        this.commandId = commandId == null ? "" : commandId;
        this.status = status == null ? "" : status;
        this.source = source == null ? "" : source;
        this.targetUrl = targetUrl == null ? "" : targetUrl;
        this.currentUrl = currentUrl == null ? "" : currentUrl;
    }

    boolean isNavigationReady() {
        return "opened".equals(status) || "focused".equals(status) || "navigated".equals(status);
    }

    boolean isTerminal() {
        return isNavigationReady() || "failed".equals(status) || "ignored".equals(status);
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

final class ConnectionStatus {
    final boolean ok;
    final String message;

    ConnectionStatus(boolean ok, String message) {
        this.ok = ok;
        this.message = message == null ? "" : message;
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
    final String id;
    final String createdAt;
    final String role;
    final String content;
    final List<ChatHistoryAttachment> attachments;

    ChatHistoryMessage(String role, String content) {
        this("", "", role, content, List.of());
    }

    ChatHistoryMessage(String id, String createdAt, String role, String content) {
        this(id, createdAt, role, content, List.of());
    }

    ChatHistoryMessage(
            String id,
            String createdAt,
            String role,
            String content,
            List<ChatHistoryAttachment> attachments
    ) {
        this.id = id == null ? "" : id.trim();
        this.createdAt = createdAt == null ? "" : createdAt.trim();
        this.role = role == null ? "" : role.trim();
        this.content = content == null ? "" : content.trim();
        this.attachments = attachments == null ? List.of() : List.copyOf(attachments);
    }
}

final class ChatHistoryAttachment {
    final String messageId;
    final String attachmentId;
    final String filename;
    final String mimeType;
    final long byteSize;
    final String status;
    final String kind;
    final String previewUrl;
    final String contentUrl;
    final int ordinal;

    ChatHistoryAttachment(
            String messageId,
            String attachmentId,
            String filename,
            String mimeType,
            long byteSize,
            String status,
            String kind,
            String previewUrl,
            String contentUrl,
            int ordinal
    ) {
        this.messageId = messageId == null ? "" : messageId.trim();
        this.attachmentId = attachmentId == null ? "" : attachmentId.trim();
        this.filename = filename == null ? "" : filename.trim();
        this.mimeType = mimeType == null ? "" : mimeType.trim();
        this.byteSize = Math.max(0L, byteSize);
        this.status = status == null ? "" : status.trim();
        this.kind = kind == null ? "" : kind.trim();
        this.previewUrl = previewUrl == null ? "" : previewUrl.trim();
        this.contentUrl = contentUrl == null ? "" : contentUrl.trim();
        this.ordinal = Math.max(0, ordinal);
    }
}

final class AgendaItem {
    final String id;
    final String title;
    final String status;
    final String certainty;
    final String timeDisplay;
    final String place;
    final List<String> participants;
    final List<String> missingFields;
    final String source;

    AgendaItem(
            String id,
            String title,
            String status,
            String certainty,
            String timeDisplay,
            String place,
            List<String> participants,
            List<String> missingFields,
            String source
    ) {
        this.id = id == null ? "" : id;
        this.title = title == null ? "" : title;
        this.status = status == null ? "" : status;
        this.certainty = certainty == null ? "" : certainty;
        this.timeDisplay = timeDisplay == null ? "" : timeDisplay;
        this.place = place == null ? "" : place;
        this.participants = participants == null ? List.of() : List.copyOf(participants);
        this.missingFields = missingFields == null ? List.of() : List.copyOf(missingFields);
        this.source = source == null ? "" : source;
    }

    String timeDisplay() {
        return timeDisplay.isEmpty() ? "待补充" : timeDisplay;
    }

    String cardText() {
        StringBuilder builder = new StringBuilder();
        builder.append(title.isEmpty() ? "未命名日程" : title);
        builder.append("\n时间：").append(timeDisplay());
        if (!place.isEmpty()) {
            builder.append("\n地点：").append(place);
        }
        if (!participants.isEmpty()) {
            builder.append("\n参与：").append(String.join("、", participants));
        }
        if (!source.isEmpty()) {
            builder.append("\n来源：").append(source);
        }
        if (!missingFields.isEmpty()) {
            builder.append("\n待补充：").append(String.join("、", missingFields));
        }
        if (!status.isEmpty() || !certainty.isEmpty()) {
            builder.append("\n状态：");
            if (!status.isEmpty()) builder.append(status);
            if (!status.isEmpty() && !certainty.isEmpty()) builder.append(" · ");
            if (!certainty.isEmpty()) builder.append(certainty);
        }
        return builder.toString();
    }
}

final class CollectorStatus {
    final String source;
    final boolean enabled;
    final boolean paused;
    final String healthStatus;
    final String authStatus;
    final String browserLoginStatus;
    final String collectionStatus;
    final String statusLabel;
    final String statusDetail;

    CollectorStatus(String source, boolean enabled, boolean paused, String healthStatus) {
        this(source, enabled, paused, healthStatus, "", "", "", "", "");
    }

    CollectorStatus(
            String source,
            boolean enabled,
            boolean paused,
            String healthStatus,
            String authStatus,
            String browserLoginStatus,
            String collectionStatus,
            String statusLabel,
            String statusDetail
    ) {
        this.source = source;
        this.enabled = enabled;
        this.paused = paused;
        this.healthStatus = healthStatus == null ? "" : healthStatus;
        this.authStatus = authStatus == null ? "" : authStatus;
        this.browserLoginStatus = browserLoginStatus == null ? "" : browserLoginStatus;
        this.collectionStatus = collectionStatus == null ? "" : collectionStatus;
        this.statusLabel = statusLabel == null ? "" : statusLabel;
        this.statusDetail = statusDetail == null ? "" : statusDetail;
    }

    CollectorStatus withComposioConnection(boolean connected) {
        String nextAuthStatus = connected ? "api_connected" : "api_not_connected";
        String nextLabel = statusLabel;
        String nextDetail = statusDetail;
        if (connected) {
            nextLabel = "API 已连接";
            if ("logged_out".equals(browserLoginStatus)) {
                nextDetail = "浏览器未登录，但 API 同步可用。";
            } else if ("unavailable".equals(browserLoginStatus)) {
                nextDetail = "浏览器不可用，但 API 同步可用。";
            } else if (nextDetail.isEmpty()) {
                nextDetail = "API 同步可用。";
            }
        } else if (nextLabel.isEmpty()) {
            nextLabel = "待授权";
        }
        return new CollectorStatus(
                source,
                enabled,
                paused,
                healthStatus,
                nextAuthStatus,
                browserLoginStatus,
                collectionStatus,
                nextLabel,
                nextDetail
        );
    }

    String displayLabel(boolean opensBrowser) {
        if (!statusLabel.isEmpty()) return statusLabel;
        if (!enabled) return "已停用";
        if (paused) return "暂停";
        if (opensBrowser) {
            if ("logged_in".equals(browserLoginStatus)) {
                if ("healthy".equals(collectionStatus) || "healthy".equals(healthStatus)) return "已登录";
                return "已登录 / 采集异常";
            }
            if ("logged_out".equals(browserLoginStatus)) return "未登录";
            if ("unavailable".equals(browserLoginStatus)) return "浏览器不可用";
            if ("healthy".equals(healthStatus)) return "正常";
            if ("degraded".equals(healthStatus)) return "待登录";
            if ("failed".equals(healthStatus)) return "异常";
            return "可登录";
        }
        if ("failed".equals(healthStatus)) return "异常";
        return "本地";
    }
}

final class CareerBoardResult {
    final List<CareerProfile> profiles;
    final List<JobOpportunity> opportunities;
    final List<ResumeVersion> resumeVersions;
    final List<JobApplicationState> applications;

    CareerBoardResult(
            List<CareerProfile> profiles,
            List<JobOpportunity> opportunities,
            List<ResumeVersion> resumeVersions,
            List<JobApplicationState> applications
    ) {
        this.profiles = profiles == null ? List.of() : List.copyOf(profiles);
        this.opportunities = opportunities == null ? List.of() : List.copyOf(opportunities);
        this.resumeVersions = resumeVersions == null ? List.of() : List.copyOf(resumeVersions);
        this.applications = applications == null ? List.of() : List.copyOf(applications);
    }
}

final class CareerProfile {
    final String id;
    final String headline;
    final List<String> targetRoles;
    final List<String> targetLocations;
    final List<String> skills;

    CareerProfile(String id, String headline, List<String> targetRoles, List<String> targetLocations, List<String> skills) {
        this.id = id == null ? "" : id;
        this.headline = headline == null ? "" : headline;
        this.targetRoles = targetRoles == null ? List.of() : List.copyOf(targetRoles);
        this.targetLocations = targetLocations == null ? List.of() : List.copyOf(targetLocations);
        this.skills = skills == null ? List.of() : List.copyOf(skills);
    }
}

final class JobOpportunity {
    final String id;
    final String source;
    final String title;
    final String company;
    final String location;
    final String url;
    final String status;
    final double fitScore;
    final List<String> requirements;

    JobOpportunity(
            String id,
            String source,
            String title,
            String company,
            String location,
            String url,
            String status,
            double fitScore,
            List<String> requirements
    ) {
        this.id = id == null ? "" : id;
        this.source = source == null ? "" : source;
        this.title = title == null ? "" : title;
        this.company = company == null ? "" : company;
        this.location = location == null ? "" : location;
        this.url = url == null ? "" : url;
        this.status = status == null ? "" : status;
        this.fitScore = fitScore;
        this.requirements = requirements == null ? List.of() : List.copyOf(requirements);
    }

    String statusLine() {
        if (fitScore >= 0) {
            return "匹配 " + Math.round(fitScore * 100) + "% · " + status;
        }
        return status;
    }
}

final class ResumeVersion {
    final String id;
    final String baseResumeId;
    final String targetJobId;
    final String status;

    ResumeVersion(String id, String baseResumeId, String targetJobId, String status) {
        this.id = id == null ? "" : id;
        this.baseResumeId = baseResumeId == null ? "" : baseResumeId;
        this.targetJobId = targetJobId == null ? "" : targetJobId;
        this.status = status == null ? "" : status;
    }
}

final class JobApplicationState {
    final String id;
    final String jobId;
    final String status;
    final String stage;
    final String nextStep;
    final String applicationAction;
    final String platform;

    JobApplicationState(
            String id,
            String jobId,
            String status,
            String stage,
            String nextStep,
            String applicationAction,
            String platform
    ) {
        this.id = id == null ? "" : id;
        this.jobId = jobId == null ? "" : jobId;
        this.status = status == null ? "" : status;
        this.stage = stage == null ? "" : stage;
        this.nextStep = nextStep == null ? "" : nextStep;
        this.applicationAction = applicationAction == null ? "" : applicationAction;
        this.platform = platform == null ? "" : platform;
    }

    String statusLine() {
        String label = "blocked_until_delegated_grant".equals(status) ? "等待授权" : status;
        if (nextStep.isEmpty()) return label;
        return label + " · " + nextStep;
    }
}
