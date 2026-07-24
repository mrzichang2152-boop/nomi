package com.par.assistant.android;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.Test;

public final class MainActivityAutoStartContractTest {
    @Test
    public void launcherStartOpensChatAndStartsFloatingBallWhenServerConfigWasSaved() throws Exception {
        String activity = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/MainActivity.java")),
                StandardCharsets.UTF_8
        );
        String prefs = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/ConfigPrefs.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(activity.contains("private boolean shouldAutoStartFloatingBall()"));
        assertTrue(activity.contains("ConfigPrefs.hasSavedServerConfig(this)"));
        assertTrue(activity.contains("!getIntent().getBooleanExtra(EXTRA_REQUEST_MICROPHONE, false)"));
        assertTrue(activity.contains("if (shouldAutoStartFloatingBall())"));
        assertTrue(activity.indexOf("if (shouldAutoStartFloatingBall())") < activity.indexOf("setContentView(buildView())"));
        assertTrue(activity.contains("private void launchNomi()"));
        assertTrue(activity.contains("startForegroundService(new Intent(this, FloatingBallService.class))"));
        assertTrue(activity.contains("new Intent(this, WebWorkspaceActivity.class)"));
        assertTrue(activity.contains("WorkbenchUrls.chatUrl("));
        assertTrue(activity.contains("ConfigPrefs.baseUrlOrDefault(this)"));
        assertTrue(activity.contains("ConfigPrefs.conversationId(this)"));
        assertTrue(activity.contains("workspace.putExtra(WebWorkspaceActivity.EXTRA_URL, chatUrl)"));
        assertTrue(activity.contains("startActivity(workspace)"));
        assertTrue(activity.contains("finish()"));
        assertFalse(activity.contains("startForegroundService(new Intent(this, FloatingBallService.class));\n        closePageOnly();"));
        assertTrue(prefs.contains("static boolean hasSavedServerConfig(Context context)"));
        assertTrue(prefs.contains("prefs.contains(KEY_BASE_URL)"));
        assertTrue(prefs.contains("!password(context).trim().isEmpty()"));
    }

    @Test
    public void overlayPermissionReturnContinuesIntoFullChat() throws Exception {
        String activity = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/MainActivity.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(activity.contains("awaitingOverlayPermission = true"));
        assertTrue(activity.contains("protected void onResume()"));
        assertTrue(activity.contains("if (awaitingOverlayPermission && Settings.canDrawOverlays(this))"));
        assertTrue(activity.contains("launchNomi()"));
    }
}
