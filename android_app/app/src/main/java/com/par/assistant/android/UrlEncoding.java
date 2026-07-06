package com.par.assistant.android;

import java.io.UnsupportedEncodingException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;

final class UrlEncoding {
    private UrlEncoding() {
    }

    static String queryComponent(String value) {
        try {
            return URLEncoder.encode(value == null ? "" : value, StandardCharsets.UTF_8.name());
        } catch (UnsupportedEncodingException error) {
            throw new IllegalStateException("UTF-8 URL encoding is unavailable", error);
        }
    }
}
