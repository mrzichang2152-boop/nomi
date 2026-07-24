package com.par.assistant.android;

import android.content.Context;
import android.content.SharedPreferences;

import com.par.assistant.core.ServerConfig;

import java.io.UnsupportedEncodingException;
import java.net.URL;
import java.net.URLEncoder;

final class ConfigPrefs {
    static final String PREFS = "par_config";
    static final String KEY_BASE_URL = "base_url";
    static final String KEY_PASSWORD = "password";
    static final String KEY_CONVERSATION_ID = "conversation_id";
    static final String DEFAULT_BASE_URL = "http://10.0.2.2:8080";

    private ConfigPrefs() {
    }

    static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static ServerConfig read(Context context) {
        SharedPreferences prefs = prefs(context);
        return ServerConfig.create(
                prefs.getString(KEY_BASE_URL, DEFAULT_BASE_URL),
                prefs.getString(KEY_PASSWORD, "")
        );
    }

    static void write(Context context, ServerConfig config) {
        prefs(context)
                .edit()
                .putString(KEY_BASE_URL, config.baseUrl())
                .putString(KEY_PASSWORD, config.password())
                .apply();
    }

    static boolean hasSavedServerConfig(Context context) {
        SharedPreferences prefs = prefs(context);
        String baseUrl = prefs.getString(KEY_BASE_URL, "");
        return prefs.contains(KEY_BASE_URL)
                && baseUrl != null
                && !baseUrl.trim().isEmpty()
                && prefs.contains(KEY_PASSWORD)
                && !password(context).trim().isEmpty();
    }

    static String baseUrlOrDefault(Context context) {
        return prefs(context).getString(KEY_BASE_URL, DEFAULT_BASE_URL);
    }

    static String password(Context context) {
        return prefs(context).getString(KEY_PASSWORD, "");
    }

    static String conversationId(Context context) {
        return prefs(context).getString(KEY_CONVERSATION_ID, "");
    }

    static void writeConversationId(Context context, String conversationId) {
        String cleanConversationId = conversationId == null ? "" : conversationId.trim();
        SharedPreferences.Editor editor = prefs(context).edit();
        if (cleanConversationId.isEmpty()) {
            editor.remove(KEY_CONVERSATION_ID);
        } else {
            editor.putString(KEY_CONVERSATION_ID, cleanConversationId);
        }
        editor.apply();
    }

    static String remoteBrowserUrl(Context context) {
        return remoteBrowserUrlFor(baseUrlOrDefault(context), password(context));
    }

    static String remoteBrowserUrlFor(String baseUrl) {
        return remoteBrowserUrlFor(baseUrl, "");
    }

    static String remoteBrowserUrlFor(String baseUrl, String appPassword) {
        try {
            URL url = new URL(baseUrl);
            String protocol = url.getProtocol();
            String host = url.getHost();
            if (host == null || host.isEmpty()) return baseUrl;
            return protocol + "://" + host + ":6080/vnc_lite.html" + noVncQuery(appPassword);
        } catch (Exception ignored) {
            return DEFAULT_BASE_URL + ":6080/vnc_lite.html" + noVncQuery(appPassword);
        }
    }

    private static String noVncQuery(String appPassword) {
        return "?path=websockify&autoconnect=1&scale=1&quality=6&compression=2&show_dot=1&password="
                + encode(vncPassword(appPassword));
    }

    private static String vncPassword(String appPassword) {
        String trimmed = appPassword == null ? "" : appPassword.trim();
        if (trimmed.isEmpty()) return "";
        return trimmed.endsWith("-vnc") ? trimmed : trimmed + "-vnc";
    }

    private static String encode(String value) {
        try {
            return URLEncoder.encode(value, "UTF-8");
        } catch (UnsupportedEncodingException ignored) {
            return value;
        }
    }
}
