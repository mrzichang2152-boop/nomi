package com.par.assistant.android;

final class StreamingChatFallbackPolicy {
    static final long FIRST_DELTA_FALLBACK_TIMEOUT_MS = 45_000L;

    private StreamingChatFallbackPolicy() {
    }

    static boolean shouldRunHttpFallback(boolean pendingMessageStillCurrent, int streamedCharacterCount) {
        return shouldRunHttpFallback(
                pendingMessageStillCurrent,
                streamedCharacterCount,
                FIRST_DELTA_FALLBACK_TIMEOUT_MS
        );
    }

    static boolean shouldRunHttpFallback(
            boolean pendingMessageStillCurrent,
            int streamedCharacterCount,
            long elapsedMs
    ) {
        return pendingMessageStillCurrent
                && streamedCharacterCount <= 0
                && elapsedMs >= FIRST_DELTA_FALLBACK_TIMEOUT_MS;
    }

    static boolean shouldFallbackOnRealtimeError(boolean pendingMessageStillCurrent, int streamedCharacterCount) {
        return shouldRunHttpFallback(pendingMessageStillCurrent, streamedCharacterCount);
    }
}
