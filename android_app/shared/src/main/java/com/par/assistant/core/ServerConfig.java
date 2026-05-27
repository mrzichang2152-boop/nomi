package com.par.assistant.core;

public final class ServerConfig {
    private final String baseUrl;
    private final String password;

    private ServerConfig(String baseUrl, String password) {
        this.baseUrl = baseUrl;
        this.password = password;
    }

    public static ServerConfig create(String inputBaseUrl, String inputPassword) {
        String normalizedBaseUrl = normalizeBaseUrl(inputBaseUrl);
        String normalizedPassword = inputPassword == null ? "" : inputPassword.trim();
        if (normalizedPassword.isEmpty()) {
            throw new IllegalArgumentException("password is required");
        }
        return new ServerConfig(normalizedBaseUrl, normalizedPassword);
    }

    public String baseUrl() {
        return baseUrl;
    }

    public String password() {
        return password;
    }

    public static String normalizeBaseUrl(String input) {
        String value = input == null ? "" : input.trim();
        if (value.isEmpty()) {
            throw new IllegalArgumentException("server base url is required");
        }
        if (!value.contains("://")) {
            value = "http://" + value;
        }
        if (!value.startsWith("http://") && !value.startsWith("https://")) {
            throw new IllegalArgumentException("server base url must use http or https");
        }
        while (value.endsWith("/") && value.length() > "https://".length()) {
            value = value.substring(0, value.length() - 1);
        }
        if (value.equals("http://") || value.equals("https://")) {
            throw new IllegalArgumentException("server host is required");
        }
        return value;
    }
}
