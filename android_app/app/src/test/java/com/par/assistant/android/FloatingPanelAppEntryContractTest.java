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
    public void fullAppEntryUsesPersistedConversationIdBeforeOpeningWebWorkspace() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(source.contains("String conversationId = ConfigPrefs.conversationId(this);"));
        assertTrue(source.contains("if (conversationId == null || conversationId.trim().isEmpty())"));
        assertTrue(source.contains("conversationId = activeConversationId;"));
        assertTrue(source.contains("WorkbenchUrls.chatUrl(ConfigPrefs.baseUrlOrDefault(this), conversationId)"));
    }

    @Test
    public void floatingPanelHistorySyncUsesDedicatedExecutorAndFreshPersistedConversationId() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(source.contains("private final ExecutorService chatHistoryExecutor = Executors.newSingleThreadExecutor();"));
        assertTrue(source.contains("String conversationId = ConfigPrefs.conversationId(this);"));
        assertTrue(source.contains("if (conversationId == null || conversationId.trim().isEmpty())"));
        assertTrue(source.contains("conversationId = activeConversationId;"));
        assertTrue(source.contains("chatHistoryExecutor.execute(() ->"));
        assertFalse(source.contains("private void loadRemoteChatHistory() {\n        int localSizeAtRequest = chatContext.size();\n        String conversationId = activeConversationId;\n        executor.execute(() ->"));
    }

    @Test
    public void floatingPanelShowsSyncStateBeforeRemoteHistoryInsteadOfFakeWelcome() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(source.contains("private TextView chatHistorySyncView;"));
        assertTrue(source.contains("chatHistorySyncView = addChatMessage(\"Nomi\", \"正在同步最近对话...\");"));
        assertTrue(source.contains("if (mergedMessages.isEmpty())"));
        assertTrue(source.contains("private void clearChatHistorySyncMessage()"));
        assertTrue(source.contains("clearChatHistorySyncMessage();"));
        assertTrue(source.indexOf("正在同步最近对话...") < source.indexOf("if (mergedMessages.isEmpty())"));
    }

    @Test
    public void floatingPanelUsesLocalHistoryCacheThenReconcilesStableRemoteHistory() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(source.contains("if (!renderCachedChatHistory())"));
        assertTrue(source.contains("LocalChatHistoryStore.load(this, activeConversationId)"));
        assertTrue(source.contains("LocalChatHistoryStore.reconcile(localMessages, history.messages, 80)"));
        assertTrue(source.contains("persistChatContext();"));
        assertTrue(source.contains("if (chatContext.size() != localSizeAtRequest)"));
        assertTrue(source.contains("LocalChatHistoryStore.save(this, activeConversationId, mergedMessages);"));
        assertFalse(source.contains("chatHistoryView.removeAllViews();\n        chatContext.replaceWithHistory(history.messages);"));
    }

    @Test
    public void floatingPanelScrollsToNewestMessageAfterRemoteHistoryMerge() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        int applyStart = source.indexOf("private void applyRemoteChatHistory");
        int applyEnd = source.indexOf("private boolean renderCachedChatHistory", applyStart);
        int scrollCall = source.indexOf("scrollChatToLatest();", applyStart);

        assertTrue(applyStart >= 0);
        assertTrue(applyEnd > applyStart);
        assertTrue(scrollCall > applyStart && scrollCall < applyEnd);
        assertTrue(source.contains("private void scrollChatToLatest()"));
        assertTrue(source.contains("target.postDelayed"));
    }

    @Test
    public void floatingPanelRebuildsArtifactDeduplicationStateWithHistoryViews() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        int renderStart = source.indexOf("private void renderChatHistoryMessages");
        int renderEnd = source.indexOf("private void persistChatContext", renderStart);
        int removeViews = source.indexOf("chatHistoryView.removeAllViews();", renderStart);
        int clearArtifacts = source.indexOf("displayedArtifactKeys.clear();", renderStart);
        int renderLoop = source.indexOf("for (ChatHistoryMessage message", renderStart);

        assertTrue(renderStart >= 0);
        assertTrue(renderEnd > renderStart);
        assertTrue(removeViews > renderStart && removeViews < renderEnd);
        assertTrue(clearArtifacts > removeViews && clearArtifacts < renderLoop);
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
        assertTrue(source.contains("addInlineProactiveCard(message)"));
        assertTrue(source.contains("ProactiveSurfacePolicy.choose("));
        assertTrue(source.contains("NomiForegroundUiState.isVisible()"));
        assertTrue(source.contains("ACTION_CLEAR_PROACTIVE_OVERLAY"));
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

    @Test
    public void floatingPanelRendersArtifactCardsOutsidePlainTextMessages() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(source.contains("for (ChatArtifact artifact : result.artifacts)"));
        assertTrue(source.contains("addArtifactCard(artifact)"));
        assertTrue(source.contains("private TextView addArtifactCard(ChatArtifact artifact)"));
        assertTrue(source.contains("openInternalFileViewer("));
        assertTrue(source.contains("artifact.downloadUrl"));
    }

    @Test
    public void floatingPanelViewsArtifactsInsideNomiInsteadOfExternalBrowser() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(source.contains("FileViewerUrls.viewerUrl("));
        assertTrue(source.contains("NomiFileViewerActivity.intentFor(this, viewerUrl)"));
        assertFalse(source.contains("ArtifactOpenActivity.intentFor"));
    }

    @Test
    public void floatingPanelUsesOneDeterministicViewerLaunchPerClick() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(source.contains("hideAssistantOverlaysForArtifactViewer()"));
        assertTrue(source.contains("startActivity(NomiFileViewerActivity.intentFor(this, viewerUrl))"));
        assertTrue(source.contains("点击查看"));
        assertFalse(source.contains("card.setEnabled(false)"));
    }

    @Test
    public void artifactCardOpensTheAuthenticatedOriginalInTheBuiltInViewer() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );
        String activity = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/NomiFileViewerActivity.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(source.contains("artifact.downloadUrl"));
        assertTrue(source.contains("artifact.mimeType"));
        assertTrue(activity.contains("public String getPassword()"));
        assertTrue(activity.contains("FileViewerUrls.isTrustedViewerUrl"));
        assertFalse(activity.contains("Intent.ACTION_VIEW"));
    }

    @Test
    public void artifactOpenHidesOverlayAndUsesDedicatedInternalActivity() throws Exception {
        String service = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );
        String activity = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/NomiFileViewerActivity.java")),
                StandardCharsets.UTF_8
        );
        String manifest = new String(
                Files.readAllBytes(Path.of("src/main/AndroidManifest.xml")),
                StandardCharsets.UTF_8
        );

        assertTrue(service.contains("hideAssistantOverlaysForArtifactViewer()"));
        assertTrue(service.contains("removeView(ballView)"));
        assertTrue(service.contains("NomiFileViewerActivity.intentFor(this, viewerUrl)"));
        assertFalse(activity.contains("Intent.ACTION_VIEW"));
        assertTrue(activity.contains("addJavascriptInterface(new ViewerBridge(), \"NomiViewer\")"));
        assertTrue(activity.contains("restoreFloatingBall()"));
        assertTrue(manifest.contains("android:name=\".NomiFileViewerActivity\""));
    }

    @Test
    public void historicalArtifactDownloadLinksUseInAppArtifactOpeningPath() throws Exception {
        String service = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );
        String urlHelper = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/ArtifactDownloadUrls.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(urlHelper.contains("static boolean isArtifactDownloadUrl"));
        assertTrue(service.contains("ArtifactDownloadUrls.isArtifactDownloadUrl(url)"));
        assertTrue(service.contains("openInternalFileViewer(artifact.downloadUrl, artifact.filename, artifact.mimeType)"));
        assertTrue(service.contains("private ChatArtifact artifactFromDownloadUrl(String url)"));
        assertTrue(
                service.indexOf("ArtifactDownloadUrls.isArtifactDownloadUrl(url)")
                        < service.indexOf("FloatingMessageLinks.isLinkedInJobDetailUrl(url)")
        );
    }

    @Test
    public void historicalAttachmentCardsOpenTheServerOriginalWithoutLocalFileState() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );
        assertTrue(source.contains("attachment.contentUrl"));
        assertTrue(source.contains("attachment.filename"));
        assertTrue(source.contains("attachment.mimeType"));
        assertFalse(source.contains("openExistingDownloadedArtifact"));
    }

    @Test
    public void floatingPanelRendersStreamingArtifactsWhenChatDoneArrives() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(source.contains("public void onChatDone(String answer, String conversationId, List<ChatArtifact> artifacts, String taskRunId)"));
        assertTrue(source.contains("completeStreamingChat(answer, conversationId, artifacts, taskRunId)"));
        assertTrue(source.contains("private void completeStreamingChat(String answer, String conversationId, List<ChatArtifact> artifacts, String taskRunId)"));
    }

    @Test
    public void floatingPanelPollsAsyncLongTailTaskArtifactsAfterInitialChatResponse() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(source.contains("maybeStartTaskArtifactPolling(result.taskRunId)"));
        assertTrue(source.contains("maybeStartTaskArtifactPolling(taskRunId)"));
        assertTrue(source.contains("private void pollTaskArtifacts(String taskRunId, int attempt)"));
        assertTrue(source.contains("api().taskArtifacts(taskRunId)"));
        assertTrue(source.contains("addArtifactCardOnce(artifact)"));
    }
}
