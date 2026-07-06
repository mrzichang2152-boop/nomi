package com.par.assistant.android;

final class WorkbenchUrls {
    private WorkbenchUrls() {
    }

    static String chatUrl(String baseUrl, String conversationId) {
        String cleanBase = baseUrl == null || baseUrl.trim().isEmpty()
                ? ConfigPrefs.DEFAULT_BASE_URL
                : baseUrl.trim();
        String cleanConversationId = conversationId == null ? "" : conversationId.trim();
        if (cleanConversationId.isEmpty()) {
            return stripHash(cleanBase) + "#chat";
        }
        String withoutHash = stripHash(cleanBase);
        String separator = withoutHash.contains("?") ? "&" : "?";
        return withoutHash
                + separator
                + "conversation_id="
                + UrlEncoding.queryComponent(cleanConversationId)
                + "#chat";
    }

    private static String stripHash(String value) {
        int hashIndex = value.indexOf('#');
        return hashIndex >= 0 ? value.substring(0, hashIndex) : value;
    }
}
