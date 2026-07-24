package com.par.assistant.android;

import static org.junit.Assert.assertTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.Test;

public final class AssistantDraftSurfaceContractTest {
    @Test
    public void floatingChatLoadsAndActsOnServerBackedDraftCards() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );
        String draftSource = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/AssistantDraft.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(source.contains("private void loadAssistantDraftCards()"));
        assertTrue(source.contains("api().assistantDrafts(20)"));
        assertTrue(source.contains("addAssistantDraftCard(draft)"));
        assertTrue(source.contains("draftActionGuard.begin(draft.draftId)"));
        assertTrue(source.contains("api().confirmAssistantDraft(draft.draftId)"));
        assertTrue(source.contains("api().sendAssistantDraft(draft.draftId, confirmationToken)"));
        assertTrue(source.contains("AssistantDraft sentDraft = api().sendAssistantDraft"));
        assertTrue(source.contains("sentDraft.actionResultMessage()"));
        assertTrue(source.contains("editAssistantDraftFromCard(draft)"));
        assertTrue(source.contains("api().editAssistantDraft(draft.draftId"));
        assertTrue(source.contains("body.setText(draft.cardText())"));
        assertTrue(draftSource.contains("依据："));
        assertTrue(source.contains("修改后重新确认"));
        assertTrue(source.contains("api().cancelAssistantDraft(draft.draftId)"));

        int editorStart = source.indexOf("private void editAssistantDraftFromCard(");
        int editorExecutor = source.indexOf("executor.execute(() ->", editorStart);
        int editorEnd = source.indexOf("private void sendAssistantDraftFromCard(", editorStart);
        String editorBeforeWorker = source.substring(editorStart, editorExecutor);
        String editorWorker = source.substring(editorExecutor, editorEnd);
        assertTrue(editorBeforeWorker.contains("String subjectText ="));
        assertTrue(!editorWorker.contains("subjectInput.getText()"));

        int httpStart = source.indexOf("private void sendHttpChat(");
        int streamingStart = source.indexOf("private boolean trySendStreamingChat(", httpStart);
        assertTrue(source.substring(httpStart, streamingStart).contains("loadAssistantDraftCards()"));
        int completeStart = source.indexOf("private void completeStreamingChat(");
        int artifactStart = source.indexOf("private void maybeStartTaskArtifactPolling(", completeStart);
        assertTrue(source.substring(completeStart, artifactStart).contains("loadAssistantDraftCards()"));
    }
}
