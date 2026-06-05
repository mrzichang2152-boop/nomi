package com.par.assistant.android;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import com.par.assistant.core.ServerConfig;

import org.json.JSONObject;
import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.util.Base64;

public final class StreamingAsrClientTest {
    @Test
    public void buildsVoiceWebSocketUrlFromHttpBaseUrl() {
        ServerConfig config = ServerConfig.create("http://206.119.171.141", "par-dev");

        String url = StreamingAsrClient.wsUrl(config);

        assertEquals("ws://206.119.171.141/ws/voice?password=par-dev", url);
    }

    @Test
    public void buildsVoiceWebSocketUrlFromHttpsBaseUrl() {
        ServerConfig config = ServerConfig.create("https://nomi.example.com/", "p@ss word");

        String url = StreamingAsrClient.wsUrl(config);

        assertEquals("wss://nomi.example.com/ws/voice?password=p%40ss+word", url);
    }

    @Test
    public void buildsVoiceStartPayloadForVolcengineCompatibleAudio() throws Exception {
        String payload = StreamingAsrClient.voiceStartPayload("voice-1", "conv-1", "zh-CN");
        JSONObject json = new JSONObject(payload);
        JSONObject audio = json.getJSONObject("audio");

        assertEquals("voice_start", json.getString("type"));
        assertEquals("voice-1", json.getString("session_id"));
        assertEquals("conv-1", json.getString("conversation_id"));
        assertEquals("android_floating_ball_voice", json.getString("client_type"));
        assertEquals("zh-CN", json.getString("language_hint"));
        assertEquals("pcm_s16le", audio.getString("codec"));
        assertEquals(16000, audio.getInt("sample_rate"));
        assertEquals(1, audio.getInt("channels"));
        assertEquals(200, audio.getInt("frame_ms"));
    }

    @Test
    public void buildsAudioChunkPayloadWithBase64Audio() throws Exception {
        byte[] pcm = "pcm".getBytes(StandardCharsets.UTF_8);

        String payload = StreamingAsrClient.audioChunkPayload("voice-1", pcm, 3, 1234L);
        JSONObject json = new JSONObject(payload);

        assertEquals("audio_chunk", json.getString("type"));
        assertEquals("voice-1", json.getString("session_id"));
        assertEquals(3, json.getInt("seq"));
        assertEquals(1234L, json.getLong("captured_at_ms"));
        assertEquals(Base64.getEncoder().encodeToString(pcm), json.getString("audio_base64"));
    }

    @Test
    public void parsesReadyPartialFinalAndErrorEvents() throws Exception {
        StreamingAsrClient.ServerEvent ready = StreamingAsrClient.parseServerEvent(
                "{\"type\":\"voice_ready\",\"session_id\":\"v1\",\"provider\":\"fake\",\"max_duration_ms\":60000}"
        );
        StreamingAsrClient.ServerEvent partial = StreamingAsrClient.parseServerEvent(
                "{\"type\":\"asr_partial\",\"session_id\":\"v1\",\"text\":\"帮我查\",\"confidence\":0.72,\"stable\":false,\"seq\":4}"
        );
        StreamingAsrClient.ServerEvent fin = StreamingAsrClient.parseServerEvent(
                "{\"type\":\"asr_final\",\"session_id\":\"v1\",\"text\":\"帮我查路线\",\"confidence\":0.86,\"transcript_id\":\"tr1\"}"
        );
        StreamingAsrClient.ServerEvent error = StreamingAsrClient.parseServerEvent(
                "{\"type\":\"voice_error\",\"session_id\":\"v1\",\"code\":\"empty_audio\",\"message\":\"没听清\"}"
        );

        assertNotNull(ready);
        assertEquals("voice_ready", ready.type);
        assertEquals("fake", ready.provider);
        assertEquals(60000, ready.maxDurationMs);
        assertEquals("asr_partial", partial.type);
        assertEquals("帮我查", partial.text);
        assertFalse(partial.stable);
        assertEquals(4, partial.seq);
        assertEquals("asr_final", fin.type);
        assertEquals("帮我查路线", fin.text);
        assertEquals("tr1", fin.transcriptId);
        assertEquals("voice_error", error.type);
        assertEquals("empty_audio", error.code);
        assertEquals("没听清", error.message);
    }

    @Test
    public void buildsFinishAndCancelPayloads() throws Exception {
        JSONObject finish = new JSONObject(StreamingAsrClient.voiceEndPayload("voice-1", 8));
        JSONObject cancel = new JSONObject(StreamingAsrClient.voiceCancelPayload("voice-1", "user_swiped_cancel"));

        assertEquals("voice_end", finish.getString("type"));
        assertEquals("voice-1", finish.getString("session_id"));
        assertEquals(8, finish.getInt("last_seq"));
        assertEquals("voice_cancel", cancel.getString("type"));
        assertEquals("user_swiped_cancel", cancel.getString("reason"));
        assertTrue(cancel.getString("session_id").contains("voice-1"));
    }
}
