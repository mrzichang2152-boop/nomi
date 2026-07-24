package com.par.assistant.android;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.Test;

public final class NomiFileViewerContractTest {
    @Test
    public void viewerActivityIsInternalRestrictedAndRestoresFloatingBall() throws Exception {
        String activity = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/NomiFileViewerActivity.java")),
                StandardCharsets.UTF_8
        );
        String manifest = new String(
                Files.readAllBytes(Path.of("src/main/AndroidManifest.xml")),
                StandardCharsets.UTF_8
        );

        assertTrue(manifest.contains("android:name=\".NomiFileViewerActivity\""));
        assertTrue(manifest.contains("android:windowSoftInputMode=\"adjustResize\""));
        assertTrue(activity.contains("addJavascriptInterface"));
        assertTrue(activity.contains("\"NomiViewer\""));
        assertTrue(activity.contains("public String getPassword()"));
        assertTrue(activity.contains("public void closeViewer()"));
        assertTrue(activity.contains("public boolean downloadFile(String source, String filename, String mimeType)"));
        assertTrue(activity.contains("downloadInProgress.compareAndSet(false, true)"));
        assertTrue(activity.contains("OriginalFileDownload.download("));
        assertTrue(activity.contains("webView.evaluateJavascript"));
        assertTrue(activity.contains("NomiViewerDownloadFinished"));
        assertTrue(activity.contains("FileViewerUrls.isTrustedViewerUrl"));
        assertTrue(activity.contains("shouldOverrideUrlLoading"));
        assertTrue(activity.contains("restoreFloatingBall"));
        assertTrue(activity.contains("NomiForegroundUiState.enter()"));
        assertTrue(activity.contains("NomiForegroundUiState.exit()"));
        assertTrue(activity.contains("FloatingBallService.clearProactiveOverlayIntent(this)"));
        assertFalse(activity.contains("Intent.ACTION_VIEW"));
    }

    @Test
    public void nativeDownloadUsesAuthenticatedMediaStoreStreaming() throws Exception {
        String download = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/OriginalFileDownload.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(download.contains("FileViewerUrls.isAllowedSource"));
        assertTrue(download.contains("NomiHttpClients.privateCloudBuilder()"));
        assertTrue(download.contains("\"x-par-password\""));
        assertTrue(download.contains("MediaStore.Downloads.EXTERNAL_CONTENT_URI"));
        assertTrue(download.contains("Environment.DIRECTORY_DOWNLOADS + \"/Nomi\""));
        assertTrue(download.contains("MediaStore.MediaColumns.IS_PENDING"));
        assertTrue(download.contains("resolver.delete(itemUri"));
    }

    @Test
    public void floatingAndWorkspaceAttachmentClicksUseTheSameInternalViewer() throws Exception {
        String service = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );
        String workspace = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/WebWorkspaceActivity.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(service.contains("NomiFileViewerActivity.intentFor"));
        assertTrue(service.contains("attachment.contentUrl"));
        assertTrue(service.contains("card.setOnClickListener"));
        assertTrue(workspace.contains("public void openFileViewer"));
        assertTrue(workspace.contains("NomiFileViewerActivity.intentFor"));
        assertFalse(service.contains("ArtifactOpenActivity.intentFor"));
    }
}
