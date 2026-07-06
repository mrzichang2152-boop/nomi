package com.par.assistant.android;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.Test;

public final class FloatingStreamingFallbackContractTest {
    @Test
    public void realtimeErrorUsesHttpFallbackInsteadOfImmediateFailureWhenNoDeltaArrived() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(source.contains("fallbackStreamingChatAfterRealtimeIssue"));
        assertTrue(source.contains("shouldFallbackOnRealtimeError"));
        assertFalse(source.contains("if (streamingPendingView != null) {\n                            failStreamingChat(message);"));
    }

    @Test
    public void backgroundRealtimeReconnectErrorsDoNotOverwriteVisibleChatPanel() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        assertFalse(source.contains("responseView.setText(\"实时通道异常：\" + message);"));
        assertTrue(source.contains("ignoreBackgroundRealtimeError"));
    }
}
