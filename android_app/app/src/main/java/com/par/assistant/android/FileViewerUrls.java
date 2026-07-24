package com.par.assistant.android;

import java.net.URI;
import java.util.Locale;
import java.util.regex.Pattern;

final class FileViewerUrls {
    private static final Pattern ATTACHMENT = Pattern.compile(
            "^/api/chat/attachments/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/content/?$"
    );
    private static final Pattern ARTIFACT = Pattern.compile(
            "^/api/artifacts/[A-Za-z0-9_-]+/download/?$"
    );

    private FileViewerUrls() {
    }

    static boolean isAllowedSource(String source) {
        String clean = source == null ? "" : source.trim();
        if (clean.isEmpty() || clean.contains("..") || clean.contains("\\") || clean.startsWith("//")) {
            return false;
        }
        int query = clean.indexOf('?');
        int fragment = clean.indexOf('#');
        int end = clean.length();
        if (query >= 0) end = Math.min(end, query);
        if (fragment >= 0) end = Math.min(end, fragment);
        String path = clean.substring(0, end);
        return ATTACHMENT.matcher(path).matches() || ARTIFACT.matcher(path).matches();
    }

    static String viewerUrl(String baseUrl, String source, String filename, String mimeType) {
        try {
            URI base = normalizedBase(baseUrl);
            String normalizedSource = normalizeSource(base, source);
            if (normalizedSource.isEmpty()) return "";
            String query = "source=" + encode(normalizedSource);
            String cleanFilename = clean(filename);
            String cleanMimeType = clean(mimeType);
            if (!cleanFilename.isEmpty()) query += "&filename=" + encode(cleanFilename);
            if (!cleanMimeType.isEmpty()) query += "&mime_type=" + encode(cleanMimeType);
            return origin(base) + "/viewer?" + query;
        } catch (Exception ignored) {
            return "";
        }
    }

    static boolean isTrustedViewerUrl(String baseUrl, String viewerUrl) {
        return !normalizeTrustedViewerUrl(baseUrl, viewerUrl).isEmpty();
    }

    static String normalizeTrustedViewerUrl(String baseUrl, String viewerUrl) {
        try {
            URI base = normalizedBase(baseUrl);
            URI candidate = base.resolve(clean(viewerUrl));
            if (!sameOrigin(base, candidate) || !"/viewer".equals(candidate.getPath())) return "";
            String query = candidate.getRawQuery();
            return origin(base) + "/viewer" + (query == null || query.isEmpty() ? "" : "?" + query);
        } catch (Exception ignored) {
            return "";
        }
    }

    private static String normalizeSource(URI base, String source) {
        String clean = clean(source);
        if (clean.isEmpty() || clean.contains("..") || clean.contains("\\") || clean.startsWith("//")) return "";
        try {
            URI candidate = base.resolve(clean);
            if (!sameOrigin(base, candidate)) return "";
            String path = candidate.getPath();
            return isAllowedSource(path) ? path.replaceAll("/$", "") : "";
        } catch (Exception ignored) {
            return "";
        }
    }

    private static URI normalizedBase(String baseUrl) throws Exception {
        String clean = clean(baseUrl);
        if (clean.isEmpty()) clean = ConfigPrefs.DEFAULT_BASE_URL;
        URI uri = new URI(clean);
        if (uri.getScheme() == null || uri.getHost() == null) throw new IllegalArgumentException("invalid base URL");
        return uri;
    }

    private static String origin(URI uri) {
        int port = uri.getPort();
        return uri.getScheme().toLowerCase(Locale.ROOT)
                + "://"
                + uri.getHost().toLowerCase(Locale.ROOT)
                + (port >= 0 ? ":" + port : "");
    }

    private static boolean sameOrigin(URI left, URI right) {
        return origin(left).equals(origin(right));
    }

    private static String encode(String value) {
        return UrlEncoding.queryComponent(value).replace("+", "%20");
    }

    private static String clean(String value) {
        return value == null ? "" : value.trim();
    }
}
