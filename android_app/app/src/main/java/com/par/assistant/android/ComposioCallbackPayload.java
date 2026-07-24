package com.par.assistant.android;

final class ComposioCallbackPayload {
    private ComposioCallbackPayload() {
    }

    static boolean isCallback(String scheme, String host, String path) {
        return "nomi".equalsIgnoreCase(clean(scheme))
                && "composio".equalsIgnoreCase(clean(host))
                && "/connected".equals(clean(path));
    }

    static String statusMessage(String toolkitSlug, String status) {
        String label = toolkitLabel(toolkitSlug);
        String normalizedStatus = clean(status);
        if (normalizedStatus.isEmpty()) {
            return label + " 授权流程已返回，正在刷新账号状态。";
        }
        if (!"success".equalsIgnoreCase(normalizedStatus)) {
            return label + " 授权未完成，请重新尝试。";
        }
        return label + " 授权已完成，正在刷新账号状态。";
    }

    static String assistantIdentityId(String rawIdentityId) {
        String identityId = clean(rawIdentityId);
        return "nomi_gmail_primary".equals(identityId) ? identityId : "";
    }

    private static String toolkitLabel(String toolkitSlug) {
        String slug = clean(toolkitSlug).toLowerCase();
        switch (slug) {
            case "gmail":
                return "Gmail";
            case "googlecalendar":
                return "Google Calendar";
            case "googledrive":
                return "Google Drive";
            case "googledocs":
                return "Google Docs";
            case "googlesheets":
                return "Google Sheets";
            case "googletasks":
                return "Google Tasks";
            default:
                return slug.isEmpty() ? "账号" : slug;
        }
    }

    private static String clean(String value) {
        return value == null ? "" : value.trim();
    }
}
