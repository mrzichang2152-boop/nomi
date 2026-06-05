package com.par.assistant.android;

import static org.junit.Assert.assertTrue;
import static org.junit.Assert.assertFalse;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

import org.junit.Test;

public final class WebWorkspaceKeyboardTest {
    @Test
    public void workspaceActivityRequestsResizeWhenKeyboardAppears() throws Exception {
        String manifest = new String(
                Files.readAllBytes(sourcePath("AndroidManifest.xml")),
                StandardCharsets.UTF_8
        );
        String activity = new String(
                Files.readAllBytes(sourcePath("java/com/par/assistant/android/WebWorkspaceActivity.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(manifest.contains("android:name=\".WebWorkspaceActivity\""));
        assertTrue(manifest.contains("android:windowSoftInputMode=\"adjustResize\""));
        assertTrue(activity.contains("SOFT_INPUT_ADJUST_RESIZE"));
        assertTrue(activity.contains("WebSettings.LOAD_NO_CACHE"));
        assertFalse(activity.contains("clearCache(true)"));
    }

    private static Path sourcePath(String relativePath) {
        Path appModulePath = Paths.get("src/main", relativePath);
        if (Files.exists(appModulePath)) {
            return appModulePath;
        }
        return Paths.get("app/src/main", relativePath);
    }
}
