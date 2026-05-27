package com.par.assistant.android;

import com.par.assistant.core.ServerConfig;

import android.os.Handler;
import android.os.Looper;

import org.json.JSONObject;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;

import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;

final class RealtimeClient {
    interface Callback {
        void onProactiveMessage(ProactiveMessage message);
        void onError(String message);
    }

    private final ServerConfig config;
    private final Callback callback;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final OkHttpClient client = new OkHttpClient();
    private WebSocket socket;
    private boolean stopped;

    RealtimeClient(ServerConfig config, Callback callback) {
        this.config = config;
        this.callback = callback;
    }

    void start() {
        stopped = false;
        Request request = new Request.Builder().url(wsUrl()).build();
        socket = client.newWebSocket(request, new WebSocketListener() {
            @Override
            public void onMessage(WebSocket webSocket, String text) {
                handleMessage(text);
            }

            @Override
            public void onFailure(WebSocket webSocket, Throwable t, Response response) {
                callback.onError(t.getMessage() == null ? "实时连接失败" : t.getMessage());
                scheduleReconnect();
            }
        });
    }

    void stop() {
        stopped = true;
        mainHandler.removeCallbacksAndMessages(null);
        if (socket != null) {
            socket.close(1000, "service stopped");
            socket = null;
        }
    }

    private void scheduleReconnect() {
        if (stopped) return;
        mainHandler.postDelayed(() -> {
            if (!stopped) start();
        }, 3000L);
    }

    private void handleMessage(String text) {
        try {
            JSONObject json = new JSONObject(text);
            if (!"proactive_message".equals(json.optString("type"))) return;
            callback.onProactiveMessage(
                    new ProactiveMessage(
                            json.optString("id"),
                            json.optString("title"),
                            json.optString("body"),
                            json.optString("source")
                    )
            );
        } catch (Exception error) {
            callback.onError("实时消息解析失败：" + error.getMessage());
        }
    }

    private String wsUrl() {
        String base = config.baseUrl();
        String wsBase;
        if (base.startsWith("https://")) {
            wsBase = "wss://" + base.substring("https://".length());
        } else if (base.startsWith("http://")) {
            wsBase = "ws://" + base.substring("http://".length());
        } else {
            wsBase = base;
        }
        String password = URLEncoder.encode(config.password(), StandardCharsets.UTF_8);
        return wsBase + "/ws?password=" + password;
    }
}

final class ProactiveMessage {
    final String id;
    final String title;
    final String body;
    final String source;

    ProactiveMessage(String id, String title, String body, String source) {
        this.id = id;
        this.title = title == null ? "" : title;
        this.body = body == null ? "" : body;
        this.source = source == null ? "" : source;
    }
}
