package com.par.assistant.android;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

final class LocalChatHistoryStore {
    private static final String PREFS = "par_local_chat_history";
    private static final String KEY_CONVERSATION_ID = "conversation_id";
    private static final String KEY_MESSAGES = "messages";
    private static final int DEFAULT_LIMIT = 80;

    private LocalChatHistoryStore() {
    }

    static List<ChatHistoryMessage> load(Context context, String conversationId) {
        if (context == null) return List.of();
        String requestedConversationId = clean(conversationId);
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String storedConversationId = clean(prefs.getString(KEY_CONVERSATION_ID, ""));
        if (!requestedConversationId.equals(storedConversationId)) return List.of();
        return deserializeMessages(prefs.getString(KEY_MESSAGES, "[]"), DEFAULT_LIMIT);
    }

    static void save(Context context, String conversationId, List<ChatHistoryMessage> messages) {
        if (context == null) return;
        String cleanConversationId = clean(conversationId);
        if (cleanConversationId.isEmpty()) return;
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit()
                .putString(KEY_CONVERSATION_ID, cleanConversationId)
                .putString(KEY_MESSAGES, serializeMessages(tail(normalize(messages), DEFAULT_LIMIT)))
                .apply();
    }

    static List<ChatHistoryMessage> fromTurns(List<FloatingChatContext.Turn> turns) {
        if (turns == null || turns.isEmpty()) return List.of();
        ArrayList<ChatHistoryMessage> messages = new ArrayList<>();
        for (FloatingChatContext.Turn turn : turns) {
            if (turn == null || !isSupportedRole(turn.role)) continue;
            String content = clean(turn.content);
            if (content.isEmpty()) continue;
            messages.add(new ChatHistoryMessage(turn.id, turn.createdAt, turn.role, content, turn.attachments));
        }
        return List.copyOf(messages);
    }

    static List<ChatHistoryMessage> reconcile(
            List<ChatHistoryMessage> local,
            List<ChatHistoryMessage> remote,
            int limit
    ) {
        List<ChatHistoryMessage> remoteMessages = normalize(remote);
        ArrayList<ChatHistoryMessage> merged = new ArrayList<>(remoteMessages);
        Map<String, Integer> unclaimedRemoteOccurrences = new HashMap<>();
        for (ChatHistoryMessage remoteMessage : remoteMessages) {
            String key = messageFingerprint(remoteMessage);
            unclaimedRemoteOccurrences.put(key, unclaimedRemoteOccurrences.getOrDefault(key, 0) + 1);
        }
        for (ChatHistoryMessage localMessage : normalize(local)) {
            if (!localMessage.id.isEmpty()) continue;
            String fingerprint = messageFingerprint(localMessage);
            int matchingRemoteCount = unclaimedRemoteOccurrences.getOrDefault(fingerprint, 0);
            if (matchingRemoteCount > 0) {
                unclaimedRemoteOccurrences.put(fingerprint, matchingRemoteCount - 1);
                continue;
            }
            merged.add(new ChatHistoryMessage("", localMessage.createdAt, localMessage.role, localMessage.content));
        }
        return tail(merged, limit);
    }

    static List<ChatHistoryMessage> mergeWithRemote(
            List<ChatHistoryMessage> local,
            List<ChatHistoryMessage> remote,
            int limit
    ) {
        List<ChatHistoryMessage> localMessages = normalize(local);
        List<ChatHistoryMessage> remoteMessages = normalize(remote);
        int safeLimit = Math.max(1, limit);
        if (localMessages.isEmpty()) return tail(remoteMessages, safeLimit);
        if (remoteMessages.isEmpty()) return tail(localMessages, safeLimit);

        boolean hasStableIds = hasAnyId(localMessages) && hasAnyId(remoteMessages);
        Overlap overlap = bestOverlap(localMessages, remoteMessages, hasStableIds);
        int requiredOverlap = Math.min(2, localMessages.size());
        if (overlap.length < requiredOverlap) return tail(remoteMessages, safeLimit);

        ArrayList<ChatHistoryMessage> merged = new ArrayList<>();
        merged.addAll(localMessages.subList(0, overlap.localStart));
        merged.addAll(remoteMessages.subList(overlap.remoteStart, remoteMessages.size()));
        int localSuffixStart = overlap.localStart + overlap.length;
        merged.addAll(localMessages.subList(localSuffixStart, localMessages.size()));
        return tail(merged, safeLimit);
    }

    static String serializeMessages(List<ChatHistoryMessage> messages) {
        JSONArray items = new JSONArray();
        for (ChatHistoryMessage message : normalize(messages)) {
            try {
                JSONObject item = new JSONObject();
                item.put("id", message.id);
                item.put("created_at", message.createdAt);
                item.put("role", message.role);
                item.put("content", message.content);
                JSONArray attachments = new JSONArray();
                for (ChatHistoryAttachment attachment : message.attachments) {
                    attachments.put(new JSONObject()
                            .put("message_id", attachment.messageId)
                            .put("attachment_id", attachment.attachmentId)
                            .put("filename", attachment.filename)
                            .put("mime_type", attachment.mimeType)
                            .put("byte_size", attachment.byteSize)
                            .put("status", attachment.status)
                            .put("kind", attachment.kind)
                            .put("preview_url", safeUrl(attachment.previewUrl))
                            .put("content_url", safeUrl(attachment.contentUrl))
                            .put("ordinal", attachment.ordinal));
                }
                item.put("attachments", attachments);
                items.put(item);
            } catch (Exception ignored) {
                // Skip a malformed in-memory row instead of corrupting the complete cache.
            }
        }
        return items.toString();
    }

    static List<ChatHistoryMessage> deserializeMessages(String raw, int limit) {
        ArrayList<ChatHistoryMessage> messages = new ArrayList<>();
        try {
            JSONArray items = new JSONArray(raw == null ? "[]" : raw);
            for (int index = 0; index < items.length(); index++) {
                JSONObject item = items.optJSONObject(index);
                if (item == null) continue;
                String id = clean(item.optString("id"));
                String createdAt = clean(item.optString("created_at"));
                String role = clean(item.optString("role"));
                String content = clean(item.optString("content"));
                if (!isSupportedRole(role) || content.isEmpty()) continue;
                ArrayList<ChatHistoryAttachment> attachments = new ArrayList<>();
                JSONArray attachmentItems = item.optJSONArray("attachments");
                if (attachmentItems != null) {
                    for (int attachmentIndex = 0; attachmentIndex < attachmentItems.length(); attachmentIndex++) {
                        JSONObject attachment = attachmentItems.optJSONObject(attachmentIndex);
                        if (attachment == null) continue;
                        attachments.add(new ChatHistoryAttachment(
                                attachment.optString("message_id"),
                                attachment.optString("attachment_id"),
                                attachment.optString("filename"),
                                attachment.optString("mime_type"),
                                attachment.optLong("byte_size", 0L),
                                attachment.optString("status"),
                                attachment.optString("kind"),
                                safeUrl(attachment.optString("preview_url")),
                                safeUrl(attachment.optString("content_url")),
                                attachment.optInt("ordinal", attachmentIndex)
                        ));
                    }
                }
                messages.add(new ChatHistoryMessage(id, createdAt, role, content, attachments));
            }
        } catch (Exception ignored) {
            return List.of();
        }
        return tail(normalize(messages), limit);
    }

    private static List<ChatHistoryMessage> normalize(List<ChatHistoryMessage> messages) {
        if (messages == null || messages.isEmpty()) return List.of();
        ArrayList<ChatHistoryMessage> normalized = new ArrayList<>();
        for (ChatHistoryMessage message : messages) {
            if (message == null) continue;
            String role = clean(message.role);
            String content = clean(message.content);
            String id = clean(message.id);
            if (!isSupportedRole(role) || content.isEmpty()) continue;
            normalized.add(new ChatHistoryMessage(
                    id,
                    clean(message.createdAt),
                    role,
                    content,
                    normalizeAttachments(id, message.attachments)
            ));
        }
        return List.copyOf(normalized);
    }

    private static List<ChatHistoryAttachment> normalizeAttachments(
            String messageId,
            List<ChatHistoryAttachment> attachments
    ) {
        if (messageId.isEmpty() || attachments == null || attachments.isEmpty()) return List.of();
        ArrayList<ChatHistoryAttachment> normalized = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (ChatHistoryAttachment attachment : attachments) {
            if (attachment == null) continue;
            String owner = clean(attachment.messageId);
            String attachmentId = clean(attachment.attachmentId);
            if (!messageId.equals(owner) || attachmentId.isEmpty()) continue;
            String key = messageId + "\n" + attachmentId;
            if (!seen.add(key)) continue;
            normalized.add(new ChatHistoryAttachment(
                    messageId,
                    attachmentId,
                    clean(attachment.filename),
                    clean(attachment.mimeType),
                    attachment.byteSize,
                    clean(attachment.status),
                    clean(attachment.kind),
                    safeUrl(attachment.previewUrl),
                    safeUrl(attachment.contentUrl),
                    attachment.ordinal
            ));
        }
        normalized.sort(Comparator
                .comparingInt((ChatHistoryAttachment item) -> item.ordinal)
                .thenComparing(item -> item.attachmentId));
        return List.copyOf(normalized);
    }

    private static Overlap bestOverlap(
            List<ChatHistoryMessage> local,
            List<ChatHistoryMessage> remote,
            boolean preferStableIds
    ) {
        Overlap best = new Overlap(0, 0, 0);
        for (int localStart = 0; localStart < local.size(); localStart++) {
            for (int length = local.size() - localStart; length >= 1; length--) {
                for (int remoteStart = 0; remoteStart + length <= remote.size(); remoteStart++) {
                    if (matches(local, localStart, remote, remoteStart, length, preferStableIds)
                            && length > best.length) {
                        best = new Overlap(localStart, remoteStart, length);
                    }
                }
            }
        }
        return best;
    }

    private static boolean matches(
            List<ChatHistoryMessage> local,
            int localStart,
            List<ChatHistoryMessage> remote,
            int remoteStart,
            int length,
            boolean preferStableIds
    ) {
        for (int offset = 0; offset < length; offset++) {
            ChatHistoryMessage left = local.get(localStart + offset);
            ChatHistoryMessage right = remote.get(remoteStart + offset);
            if (preferStableIds) {
                if (left.id.isEmpty() || !left.id.equals(right.id)) return false;
            } else if (!left.role.equals(right.role) || !left.content.equals(right.content)) {
                return false;
            }
        }
        return true;
    }

    private static boolean hasAnyId(List<ChatHistoryMessage> messages) {
        for (ChatHistoryMessage message : messages) {
            if (!message.id.isEmpty()) return true;
        }
        return false;
    }

    private static List<ChatHistoryMessage> tail(List<ChatHistoryMessage> messages, int limit) {
        if (messages == null || messages.isEmpty()) return List.of();
        int safeLimit = Math.max(1, limit);
        int from = Math.max(0, messages.size() - safeLimit);
        return List.copyOf(messages.subList(from, messages.size()));
    }

    private static String safeUrl(String value) {
        String url = clean(value);
        if (url.startsWith("/") || url.startsWith("https://") || url.startsWith("http://")) return url;
        return "";
    }

    private static boolean isSupportedRole(String role) {
        return "user".equals(role) || "assistant".equals(role);
    }

    private static String messageFingerprint(ChatHistoryMessage message) {
        return clean(message.role) + "\n" + clean(message.content);
    }

    private static String clean(String value) {
        return value == null ? "" : value.trim();
    }

    private static final class Overlap {
        final int localStart;
        final int remoteStart;
        final int length;

        Overlap(int localStart, int remoteStart, int length) {
            this.localStart = localStart;
            this.remoteStart = remoteStart;
            this.length = length;
        }
    }
}
