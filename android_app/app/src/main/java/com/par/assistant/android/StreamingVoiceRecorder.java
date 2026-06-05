package com.par.assistant.android;

import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;

import java.util.Arrays;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

final class StreamingVoiceRecorder {
    static final int SAMPLE_RATE = 16000;
    static final int FRAME_MS = 200;
    static final int CHANNEL_CONFIG = AudioFormat.CHANNEL_IN_MONO;
    static final int ENCODING = AudioFormat.ENCODING_PCM_16BIT;
    static final int CHUNK_BYTES = chunkBytesFor(SAMPLE_RATE, FRAME_MS);

    interface Callback {
        void onAudioChunk(byte[] pcm, int seq, long capturedAtMs);
        void onLevel(float rms);
        void onRecorderError(String userVisibleMessage, Throwable error);
    }

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private volatile boolean recording;
    private AudioRecord audioRecord;

    boolean start(Callback callback) {
        if (recording) return false;
        try {
            int minBuffer = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL_CONFIG, ENCODING);
            int bufferSize = Math.max(CHUNK_BYTES * 2, minBuffer);
            audioRecord = new AudioRecord(
                    MediaRecorder.AudioSource.VOICE_RECOGNITION,
                    SAMPLE_RATE,
                    CHANNEL_CONFIG,
                    ENCODING,
                    bufferSize
            );
            if (audioRecord.getState() != AudioRecord.STATE_INITIALIZED) {
                releaseRecorder();
                callback.onRecorderError("麦克风初始化失败，请重试。", null);
                return false;
            }
            recording = true;
            audioRecord.startRecording();
            executor.execute(() -> readLoop(callback));
            return true;
        } catch (SecurityException error) {
            recording = false;
            releaseRecorder();
            callback.onRecorderError("需要麦克风权限才能语音输入。", error);
            return false;
        } catch (Throwable error) {
            recording = false;
            releaseRecorder();
            callback.onRecorderError("录音启动失败：" + error.getMessage(), error);
            return false;
        }
    }

    void stop() {
        recording = false;
        AudioRecord record = audioRecord;
        if (record != null) {
            try {
                record.stop();
            } catch (IllegalStateException ignored) {
            }
        }
    }

    boolean isRecording() {
        return recording;
    }

    private void readLoop(Callback callback) {
        int seq = 0;
        byte[] buffer = new byte[CHUNK_BYTES];
        try {
            while (recording) {
                int offset = 0;
                while (recording && offset < buffer.length) {
                    int read = audioRecord.read(buffer, offset, buffer.length - offset);
                    if (read < 0) {
                        throw new IllegalStateException("AudioRecord read failed: " + read);
                    }
                    offset += read;
                }
                if (!recording || offset <= 0) break;
                byte[] chunk = offset == buffer.length ? Arrays.copyOf(buffer, buffer.length) : Arrays.copyOf(buffer, offset);
                callback.onLevel(rms(chunk));
                callback.onAudioChunk(chunk, ++seq, System.currentTimeMillis());
            }
        } catch (Throwable error) {
            if (recording) {
                callback.onRecorderError("录音读取失败：" + error.getMessage(), error);
            }
        } finally {
            recording = false;
            releaseRecorder();
        }
    }

    private void releaseRecorder() {
        AudioRecord record = audioRecord;
        audioRecord = null;
        if (record != null) {
            try {
                record.release();
            } catch (Exception ignored) {
            }
        }
    }

    static int chunkBytesFor(int sampleRate, int frameMs) {
        return sampleRate * frameMs / 1000 * 2;
    }

    private float rms(byte[] pcm16le) {
        if (pcm16le == null || pcm16le.length < 2) return 0f;
        double sum = 0;
        int samples = 0;
        for (int i = 0; i + 1 < pcm16le.length; i += 2) {
            int low = pcm16le[i] & 0xff;
            int high = pcm16le[i + 1];
            int sample = (high << 8) | low;
            sum += sample * (double) sample;
            samples++;
        }
        if (samples == 0) return 0f;
        return (float) Math.sqrt(sum / samples) / 32768f;
    }
}
