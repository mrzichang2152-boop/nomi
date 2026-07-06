package com.par.assistant.android;

final class AccountChannelRoute {
    enum Kind {
        COMPOSIO_CONNECT,
        REMOTE_BROWSER,
        LOCAL_ONLY
    }

    private final Kind kind;
    private final String composioToolkitSlug;
    private final String remoteBrowserSource;
    private final boolean requiresUnobstructedExternalAuth;

    private AccountChannelRoute(Kind kind, String composioToolkitSlug, String remoteBrowserSource, boolean requiresUnobstructedExternalAuth) {
        this.kind = kind;
        this.composioToolkitSlug = composioToolkitSlug == null ? "" : composioToolkitSlug;
        this.remoteBrowserSource = remoteBrowserSource == null ? "" : remoteBrowserSource;
        this.requiresUnobstructedExternalAuth = requiresUnobstructedExternalAuth;
    }

    static AccountChannelRoute forSource(String source) {
        String normalized = source == null ? "" : source.trim().toLowerCase();
        switch (normalized) {
            case "gmail":
                return composio("gmail");
            case "calendar":
            case "googlecalendar":
                return composio("googlecalendar");
            case "googledrive":
            case "drive":
                return composio("googledrive");
            case "googledocs":
            case "docs":
                return composio("googledocs");
            case "googlesheets":
            case "sheets":
                return composio("googlesheets");
            case "googletasks":
            case "tasks":
                return composio("googletasks");
            case "github":
            case "slack":
            case "notion":
                return composio(normalized);
            case "whatsapp":
            case "telegram":
            case "linkedin":
            case "search":
            case "shopping":
                return new AccountChannelRoute(Kind.REMOTE_BROWSER, "", normalized, false);
            default:
                return new AccountChannelRoute(Kind.LOCAL_ONLY, "", "", false);
        }
    }

    private static AccountChannelRoute composio(String toolkitSlug) {
        return new AccountChannelRoute(Kind.COMPOSIO_CONNECT, toolkitSlug, "", true);
    }

    Kind kind() {
        return kind;
    }

    String composioToolkitSlug() {
        return composioToolkitSlug;
    }

    String remoteBrowserSource() {
        return remoteBrowserSource;
    }

    boolean shouldOpenForStatus(CollectorStatus status) {
        if (kind == Kind.LOCAL_ONLY) {
            return false;
        }
        if (kind == Kind.REMOTE_BROWSER
                && status != null
                && status.enabled
                && !status.paused
                && "logged_in".equals(status.browserLoginStatus)) {
            return false;
        }
        if (kind == Kind.COMPOSIO_CONNECT
                && status != null
                && status.enabled
                && !status.paused
                && ("api_connected".equals(status.authStatus) || "healthy".equals(status.healthStatus))) {
            return false;
        }
        return true;
    }

    boolean requiresUnobstructedExternalAuth() {
        return requiresUnobstructedExternalAuth;
    }
}
