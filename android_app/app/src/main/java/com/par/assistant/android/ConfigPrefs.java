package com.par.assistant.android;

import android.content.Context;
import android.content.SharedPreferences;

import com.par.assistant.core.ServerConfig;

import java.net.URL;

final class ConfigPrefs {
    static final String PREFS = "par_config";
    static final String KEY_BASE_URL = "base_url";
    static final String KEY_PASSWORD = "password";
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

    static String baseUrlOrDefault(Context context) {
        return prefs(context).getString(KEY_BASE_URL, DEFAULT_BASE_URL);
    }

    static String password(Context context) {
        return prefs(context).getString(KEY_PASSWORD, "");
    }

    static String remoteBrowserUrl(Context context) {
        String baseUrl = baseUrlOrDefault(context);
        try {
            URL url = new URL(baseUrl);
            String protocol = url.getProtocol();
            String host = url.getHost();
            if (host == null || host.isEmpty()) return baseUrl;
            return protocol + "://" + host + ":6080/vnc.html";
        } catch (Exception ignored) {
            return DEFAULT_BASE_URL + ":6080/vnc.html";
        }
    }
}
