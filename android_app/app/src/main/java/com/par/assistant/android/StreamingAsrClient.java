package com.par.assistant.android;

import com.par.assistant.core.ServerConfig;

import android.os.Handler;
import android.os.Looper;

import org.json.JSONObject;

import java.util.Base64;

import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;

final class StreamingAsrClient {
    interface Callback {
        void onReady(String sessionId, String provider, int maxDurationMs);
        void onPartial(String text, double confidence, boolean stable);
        void onFinal(String text, double confidence, String transcriptId);
        void onError(String code, String message);
        void onClosed();
    }

    private final ServerConfig config;
    private final Callback callback;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final OkHttpClient client = NomiHttpClients.privateCloudBuilder().build();
    private WebSocket socket;
    private boolean stopped;

    StreamingAsrClient(ServerConfig config, Callback callback) {
        this.config = config;
        this.callback = callback;
    }

    void start(String sessionId, String conversationId, String languageHint) {
        stopped = false;
        Request request = new Request.Builder().url(wsUrl(config)).build();
        socket = client.newWebSocket(request, new WebSocketListener() {
            @Override
            public void onOpen(WebSocket webSocket, Response response) {
                webSocket.send(voiceStartPayload(sessionId, conversationId, languageHint));
            }

            @Override
            public void onMessage(WebSocket webSocket, String text) {
                handleMessage(text);
            }

            @Override
            public void onFailure(WebSocket webSocket, Throwable t, Response response) {
                postError("voice_socket_failure", t.getMessage() == null ? "语音识别连接失败。" : t.getMessage());
            }

            @Override
            public void onClosed(WebSocket webSocket, int code, String reason) {
                if (!stopped) {
                    mainHandler.post(callback::onClosed);
                }
            }
        });
    }

    boolean sendAudioChunk(String sessionId, byte[] pcm, int seq, long capturedAtMs) {
        return socket != null && socket.send(audioChunkPayload(sessionId, pcm, seq, capturedAtMs));
    }

    boolean finish(String sessionId, int lastSeq) {
        return socket != null && socket.send(voiceEndPayload(sessionId, lastSeq));
    }

    boolean cancel(String sessionId, String reason) {
        boolean sent = socket != null && socket.send(voiceCancelPayload(sessionId, reason));
        stop();
        return sent;
    }

    void stop() {
        stopped = true;
        if (socket != null) {
            socket.close(1000, "voice stopped");
            socket = null;
        }
    }

    private void handleMessage(String text) {
        try {
            ServerEvent event = parseServerEvent(text);
            if (event == null) return;
            if ("voice_ready".equals(event.type)) {
                mainHandler.post(() -> callback.onReady(event.sessionId, event.provider, event.maxDurationMs));
            } else if ("asr_partial".equals(event.type)) {
                mainHandler.post(() -> callback.onPartial(event.text, event.confidence, event.stable));
            } else if ("asr_final".equals(event.type)) {
                mainHandler.post(() -> callback.onFinal(event.text, event.confidence, event.transcriptId));
            } else if ("voice_error".equals(event.type)) {
                mainHandler.post(() -> callback.onError(event.code, event.message));
            }
        } catch (Exception error) {
            postError("voice_event_parse_failed", "语音识别消息解析失败：" + error.getMessage());
        }
    }

    private void postError(String code, String message) {
        mainHandler.post(() -> callback.onError(code, message));
    }

    static String wsUrl(ServerConfig config) {
        String base = config.baseUrl();
        String wsBase;
        if (base.startsWith("https://")) {
            wsBase = "wss://" + base.substring("https://".length());
        } else if (base.startsWith("http://")) {
            wsBase = "ws://" + base.substring("http://".length());
        } else {
            wsBase = base;
        }
        String password = UrlEncoding.queryComponent(config.password());
        return wsBase + "/ws/voice?password=" + password;
    }

    static String voiceStartPayload(String sessionId, String conversationId, String languageHint) {
        try {
            JSONObject audio = new JSONObject()
                    .put("codec", "pcm_s16le")
                    .put("sample_rate", 16000)
                    .put("channels", 1)
                    .put("frame_ms", 200);
            JSONObject json = new JSONObject()
                    .put("type", "voice_start")
                    .put("session_id", sessionId == null ? "" : sessionId)
                    .put("client_type", "android_floating_ball_voice")
                    .put("language_hint", languageHint == null || languageHint.trim().isEmpty() ? "zh-CN" : languageHint.trim())
                    .put("audio", audio);
            if (conversationId != null && !conversationId.trim().isEmpty()) {
                json.put("conversation_id", conversationId.trim());
            }
            return json.toString();
        } catch (Exception error) {
            throw new IllegalStateException("语音开始消息构造失败", error);
        }
    }

    static String audioChunkPayload(String sessionId, byte[] pcm, int seq, long capturedAtMs) {
        try {
            String audio = Base64.getEncoder().encodeToString(pcm == null ? new byte[0] : pcm);
            return new JSONObject()
                    .put("type", "audio_chunk")
                    .put("session_id", sessionId == null ? "" : sessionId)
                    .put("seq", seq)
                    .put("captured_at_ms", capturedAtMs)
                    .put("audio_base64", audio)
                    .toString();
        } catch (Exception error) {
            throw new IllegalStateException("语音分包消息构造失败", error);
        }
    }

    static String voiceEndPayload(String sessionId, int lastSeq) {
        try {
            return new JSONObject()
                    .put("type", "voice_end")
                    .put("session_id", sessionId == null ? "" : sessionId)
                    .put("last_seq", lastSeq)
                    .toString();
        } catch (Exception error) {
            throw new IllegalStateException("语音结束消息构造失败", error);
        }
    }

    static String voiceCancelPayload(String sessionId, String reason) {
        try {
            return new JSONObject()
                    .put("type", "voice_cancel")
                    .put("session_id", sessionId == null ? "" : sessionId)
                    .put("reason", reason == null || reason.trim().isEmpty() ? "cancelled" : reason.trim())
                    .toString();
        } catch (Exception error) {
            throw new IllegalStateException("语音取消消息构造失败", error);
        }
    }

    static ServerEvent parseServerEvent(String text) throws Exception {
        JSONObject json = new JSONObject(text);
        String type = json.optString("type");
        if (type == null || type.isEmpty()) return null;
        return new ServerEvent(
                type,
                json.optString("session_id"),
                json.optString("provider"),
                json.optInt("max_duration_ms"),
                json.optString("text"),
                json.optDouble("confidence"),
                json.optBoolean("stable"),
                json.optInt("seq"),
                json.optString("transcript_id"),
                json.optString("code"),
                json.optString("message")
        );
    }

    static final class ServerEvent {
        final String type;
        final String sessionId;
        final String provider;
        final int maxDurationMs;
        final String text;
        final double confidence;
        final boolean stable;
        final int seq;
        final String transcriptId;
        final String code;
        final String message;

        ServerEvent(
                String type,
                String sessionId,
                String provider,
                int maxDurationMs,
                String text,
                double confidence,
                boolean stable,
                int seq,
                String transcriptId,
                String code,
                String message
        ) {
            this.type = type == null ? "" : type;
            this.sessionId = sessionId == null ? "" : sessionId;
            this.provider = provider == null ? "" : provider;
            this.maxDurationMs = maxDurationMs;
            this.text = text == null ? "" : text;
            this.confidence = confidence;
            this.stable = stable;
            this.seq = seq;
            this.transcriptId = transcriptId == null ? "" : transcriptId;
            this.code = code == null ? "" : code;
            this.message = message == null ? "" : message;
        }
    }
}
