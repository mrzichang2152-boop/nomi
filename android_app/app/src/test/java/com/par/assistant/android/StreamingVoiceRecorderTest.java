package com.par.assistant.android;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public final class StreamingVoiceRecorderTest {
    @Test
    public void usesVolcengineRecommendedTwoHundredMillisecondPcmChunks() {
        assertEquals(16000, StreamingVoiceRecorder.SAMPLE_RATE);
        assertEquals(200, StreamingVoiceRecorder.FRAME_MS);
        assertEquals(6400, StreamingVoiceRecorder.chunkBytesFor(16000, 200));
    }
}
