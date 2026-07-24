package com.par.assistant.android;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

import org.junit.Test;

public final class WebWorkspaceSettingsBackTest {
    @Test
    public void systemBackDelegatesTrustedSettingsEntryToBrowserHistory() throws Exception {
        String activity = new String(
                Files.readAllBytes(sourcePath("java/com/par/assistant/android/WebWorkspaceActivity.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(activity.contains("WORKSPACE_SETTINGS_BACK_SCRIPT"));
        assertTrue(activity.contains("nomiWorkbenchSettingsEntry"));
        assertTrue(activity.contains("history.back()"));
        assertTrue(activity.contains("evaluateJavascript(WORKSPACE_SETTINGS_BACK_SCRIPT"));
        assertTrue(activity.contains("finishWorkspaceFromBack"));
    }

    @Test
    public void onlyJavascriptTrueMeansSettingsBackWasHandled() {
        assertTrue(WebWorkspaceActivity.javascriptHandledSettingsBack("true"));
        assertFalse(WebWorkspaceActivity.javascriptHandledSettingsBack("false"));
        assertFalse(WebWorkspaceActivity.javascriptHandledSettingsBack("null"));
        assertFalse(WebWorkspaceActivity.javascriptHandledSettingsBack(null));
    }

    private static Path sourcePath(String relativePath) {
        Path appModulePath = Paths.get("src/main", relativePath);
        if (Files.exists(appModulePath)) return appModulePath;
        return Paths.get("app/src/main", relativePath);
    }
}
