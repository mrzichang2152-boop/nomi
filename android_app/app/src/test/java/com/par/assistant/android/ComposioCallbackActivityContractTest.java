package com.par.assistant.android;

import static org.junit.Assert.assertTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.Test;

public final class ComposioCallbackActivityContractTest {
    @Test
    public void assistantOwnedGmailCallbackReturnsToAssistantIdentityPage() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/ComposioCallbackActivity.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(source.contains("getQueryParameter(\"assistant_identity\")"));
        assertTrue(source.contains("ComposioCallbackPayload.assistantIdentityId"));
        assertTrue(source.contains("WorkbenchUrls.assistantIdentitiesUrl(ConfigPrefs.baseUrlOrDefault(this))"));
        assertTrue(source.contains("workspace.putExtra(WebWorkspaceActivity.EXTRA_URL, assistantIdentityUrl)"));
        assertTrue(source.contains("startActivity(workspace)"));
    }

    @Test
    public void userOwnedAccountCallbackKeepsExistingAccountListReturn() throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/ComposioCallbackActivity.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(source.contains("FloatingBallService.ACTION_SHOW_ACCOUNTS"));
        assertTrue(source.contains("Intent.ACTION_MAIN"));
        assertTrue(source.contains("Intent.CATEGORY_HOME"));
    }
}
