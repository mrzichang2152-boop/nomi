package com.par.assistant.android;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class StreamingChatFallbackPolicyTest {
    @Test
    public void waitsLongEnoughForSlowButHealthyRealtimeFirstToken() {
        assertFalse(StreamingChatFallbackPolicy.shouldRunHttpFallback(true, 0, 12_000L));
        assertFalse(StreamingChatFallbackPolicy.shouldRunHttpFallback(true, 0, 30_000L));
        assertTrue(StreamingChatFallbackPolicy.shouldRunHttpFallback(true, 0, 45_000L));
    }

    @Test
    public void doesNotFallbackAfterAnyRealtimeDeltaArrived() {
        assertFalse(StreamingChatFallbackPolicy.shouldRunHttpFallback(true, 1, 120_000L));
    }

    @Test
    public void doesNotFallbackWhenMessageIsNoLongerPending() {
        assertFalse(StreamingChatFallbackPolicy.shouldRunHttpFallback(false, 0, 120_000L));
    }
}
