package com.par.assistant.android;

final class ArtifactDownloadUrls {
    private static final String ARTIFACT_PATH_MARKER = "/api/artifacts/";
    private static final String DOWNLOAD_PATH_MARKER = "/download";

    private ArtifactDownloadUrls() {
    }

    static String resolveForExternalBrowser(String baseUrl, String downloadUrl, String password) {
        String resolved = resolve(baseUrl, downloadUrl);
        if (!isArtifactDownloadUrl(resolved)) return resolved;
        String cleanPassword = password == null ? "" : password.trim();
        if (cleanPassword.isEmpty() || hasPasswordQuery(resolved)) return resolved;
        return appendQuery(resolved, "password=" + encodeQueryComponent(cleanPassword));
    }

    static String resolveForAppDownload(String baseUrl, String downloadUrl) {
        return resolve(baseUrl, downloadUrl);
    }

    private static String resolve(String baseUrl, String downloadUrl) {
        String clean = downloadUrl == null ? "" : downloadUrl.trim();
        if (clean.startsWith("http://") || clean.startsWith("https://")) {
            return clean;
        }
        String base = baseUrl == null ? "" : baseUrl.trim();
        if (base.isEmpty()) return clean;
        if (base.endsWith("/") && clean.startsWith("/")) {
            return base.substring(0, base.length() - 1) + clean;
        }
        if (!base.endsWith("/") && !clean.startsWith("/")) {
            return base + "/" + clean;
        }
        return base + clean;
    }

    static boolean isArtifactDownloadUrl(String url) {
        if (url == null || url.trim().isEmpty()) return false;
        int queryIndex = url.indexOf('?');
        int fragmentIndex = url.indexOf('#');
        int endIndex = url.length();
        if (queryIndex >= 0) endIndex = Math.min(endIndex, queryIndex);
        if (fragmentIndex >= 0) endIndex = Math.min(endIndex, fragmentIndex);
        String path = url.substring(0, endIndex);
        return path.contains(ARTIFACT_PATH_MARKER) && path.endsWith(DOWNLOAD_PATH_MARKER);
    }

    private static boolean hasPasswordQuery(String url) {
        return url.contains("?password=") || url.contains("&password=");
    }

    private static String appendQuery(String url, String queryPart) {
        int fragmentIndex = url.indexOf('#');
        String fragment = "";
        String withoutFragment = url;
        if (fragmentIndex >= 0) {
            fragment = url.substring(fragmentIndex);
            withoutFragment = url.substring(0, fragmentIndex);
        }
        String separator = withoutFragment.contains("?") ? "&" : "?";
        return withoutFragment + separator + queryPart + fragment;
    }

    private static String encodeQueryComponent(String value) {
        return UrlEncoding.queryComponent(value).replace("+", "%20");
    }
}
