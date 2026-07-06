package com.par.assistant.android;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.Test;

public final class FloatingPanelAppEntryContractTest {
    @Test
    public void floatingPanelKeepsFullAppEntryWithoutFullWorkspaceMode() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(source.contains("\"进入完整 App\""));
        assertTrue(source.contains("openAppChat()"));
        assertTrue(source.contains("WorkbenchUrls.chatUrl"));
        assertFalse(source.contains("完整工作台"));
    }

    @Test
    public void floatingPanelHeaderDoesNotExposeSettingsWrench() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        assertFalse(source.contains("iconButton(android.R.drawable.ic_menu_manage, \"设置\")"));
        assertFalse(source.contains("ic_menu_manage"));
        assertFalse(source.contains("或管理设置"));
    }

    @Test
    public void floatingPanelHasDirectAgendaEntryInsideOverlay() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(source.contains("\"日程\""));
        assertTrue(source.contains("showAgendaView()"));
        assertTrue(source.contains("loadAgendaItems()"));
    }

    @Test
    public void floatingPanelDoesNotInjectProactiveBubbleIntoChatHistory() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        assertFalse(source.contains("addChatMessage(\"Nomi\", proactive)"));
        assertFalse(source.contains("chatContext.addAssistant(proactive)"));
    }

    @Test
    public void floatingPanelChatMessagesWrapLongLinksInsideBubble() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(source.contains("message.setSingleLine(false)"));
        assertTrue(source.contains("message.setHorizontallyScrolling(false)"));
        assertTrue(source.contains("message.setBreakStrategy(Layout.BREAK_STRATEGY_HIGH_QUALITY)"));
    }
}
