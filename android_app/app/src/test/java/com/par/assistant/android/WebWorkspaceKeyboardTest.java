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

    @Test
    public void workspaceActivityProvidesRemoteBrowserTextInputBridge() throws Exception {
        String activity = new String(
                Files.readAllBytes(sourcePath("java/com/par/assistant/android/WebWorkspaceActivity.java")),
                StandardCharsets.UTF_8
        );
        String client = new String(
                Files.readAllBytes(sourcePath("java/com/par/assistant/android/AssistantApiClient.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(activity.contains("isRemoteBrowserUrl"));
        assertTrue(activity.contains("showRemoteInputBar"));
        assertTrue(activity.contains("输入到远端"));
        assertTrue(activity.contains("sendRemoteText"));
        assertTrue(activity.contains("requestRemoteBrowserType"));
        assertTrue(client.contains("/api/browser/type"));
    }

    @Test
    public void remoteBrowserTextInputDoesNotTriggerMiuiSecureKeyboard() throws Exception {
        String activity = new String(
                Files.readAllBytes(sourcePath("java/com/par/assistant/android/WebWorkspaceActivity.java")),
                StandardCharsets.UTF_8
        );

        assertFalse(activity.contains("TYPE_TEXT_VARIATION_VISIBLE_PASSWORD"));
        assertTrue(activity.contains("TYPE_TEXT_FLAG_NO_SUGGESTIONS"));
        assertTrue(activity.contains("TYPE_TEXT_VARIATION_NORMAL"));
    }

    @Test
    public void workspaceActivityKeepsRemoteBrowserAliveAcrossOrientationChanges() throws Exception {
        String manifest = new String(
                Files.readAllBytes(sourcePath("AndroidManifest.xml")),
                StandardCharsets.UTF_8
        );
        String activity = new String(
                Files.readAllBytes(sourcePath("java/com/par/assistant/android/WebWorkspaceActivity.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(manifest.contains("android:configChanges=\"orientation|screenSize|keyboardHidden\""));
        assertTrue(activity.contains("onConfigurationChanged"));
        assertTrue(activity.contains("dispatchEvent(new Event('resize'))"));
        assertTrue(activity.contains("webView.requestLayout()"));
        assertTrue(activity.contains("webView.invalidate()"));
    }

    @Test
    public void workspaceActivityShowsReconnectBannerWhenNoVncDisconnects() throws Exception {
        String activity = new String(
                Files.readAllBytes(sourcePath("java/com/par/assistant/android/WebWorkspaceActivity.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(activity.contains("checkRemoteBrowserDisconnected"));
        assertTrue(activity.contains("onRemoteBrowserDisconnected"));
        assertTrue(activity.contains("远程浏览器已断开，点此重连"));
        assertTrue(activity.contains("Disconnected"));
        assertTrue(activity.contains("webView.reload()"));
    }

    @Test
    public void remoteBrowserLoginPageHasVisibleReturnToAccountsControl() throws Exception {
        String activity = new String(
                Files.readAllBytes(sourcePath("java/com/par/assistant/android/WebWorkspaceActivity.java")),
                StandardCharsets.UTF_8
        );
        String service = new String(
                Files.readAllBytes(sourcePath("java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(activity.contains("showRemoteBrowserExitButton"));
        assertTrue(activity.contains("返回账号"));
        assertTrue(activity.contains("返回账号列表"));
        assertTrue(activity.contains("FloatingBallService.ACTION_SHOW_ACCOUNTS"));
        assertTrue(activity.contains("closeRemoteBrowserToAccounts"));
        assertTrue(activity.contains("onBackPressed"));
        assertTrue(activity.contains("EXTRA_REMOTE_BROWSER_MODE"));
        assertTrue(activity.contains("ensureRemoteBrowserControls"));
        assertTrue(activity.contains("getBooleanExtra(EXTRA_REMOTE_BROWSER_MODE"));
        assertTrue(activity.contains("public void enterRemoteBrowserMode()"));
        assertTrue(activity.contains("remoteBrowserMode = true;"));
        assertTrue(activity.contains("ensureRemoteBrowserControls();"));
        assertTrue(service.contains("putExtra(WebWorkspaceActivity.EXTRA_REMOTE_BROWSER_MODE, true)"));
    }

    @Test
    public void workspaceActivityOpensWindowOpenLinksInExternalBrowser() throws Exception {
        String activity = new String(
                Files.readAllBytes(sourcePath("java/com/par/assistant/android/WebWorkspaceActivity.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(activity.contains("setSupportMultipleWindows(true)"));
        assertTrue(activity.contains("setWebChromeClient"));
        assertTrue(activity.contains("onCreateWindow"));
        assertTrue(activity.contains("HitTestResult"));
        assertTrue(activity.contains("Intent.ACTION_VIEW"));
        assertTrue(activity.contains("FLAG_ACTIVITY_NEW_TASK"));
    }

    @Test
    public void workspaceActivityOpensJobLinksFromMainWebViewInExternalBrowser() throws Exception {
        String activity = new String(
                Files.readAllBytes(sourcePath("java/com/par/assistant/android/WebWorkspaceActivity.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(activity.contains("shouldOpenExternally"));
        assertTrue(activity.contains("isWorkspaceUrl"));
        assertTrue(activity.contains("shouldOverrideUrlLoading"));
        assertTrue(activity.contains("openExternalUrl"));
        assertTrue(activity.contains("NomiAndroid"));
    }

    @Test
    public void workspaceActivityKeepsRemoteBrowserUrlsInsideItsOwnWebView() throws Exception {
        String activity = new String(
                Files.readAllBytes(sourcePath("java/com/par/assistant/android/WebWorkspaceActivity.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(activity.contains("if (isRemoteBrowserUrl(url)) {"));
        assertTrue(activity.contains("remoteBrowserMode = true;"));
        assertTrue(activity.contains("ensureRemoteBrowserControls();"));
        assertTrue(activity.contains("webView.loadUrl(url);"));
        assertTrue(activity.contains("if (isRemoteBrowserUrl(url)) {\n"
                + "            return false;\n"
                + "        }\n"
                + "        return !isWorkspaceUrl(url);"));
    }

    @Test
    public void workspaceActivityShowsReadableLoadStateInsteadOfBlankWebView() throws Exception {
        String activity = new String(
                Files.readAllBytes(sourcePath("java/com/par/assistant/android/WebWorkspaceActivity.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(activity.contains("workspaceStatusView"));
        assertTrue(activity.contains("showWorkspaceStatus"));
        assertTrue(activity.contains("hideWorkspaceStatus"));
        assertTrue(activity.contains("onReceivedError"));
        assertTrue(activity.contains("WORKSPACE_LOAD_TIMEOUT_MS"));
        assertTrue(activity.contains("postDelayed"));
        assertTrue(activity.contains("完整 App 加载失败"));
        assertTrue(activity.contains("服务器地址或网络不可用"));
    }

    @Test
    public void workspaceAndFloatingPanelShareActiveConversationId() throws Exception {
        String activity = new String(
                Files.readAllBytes(sourcePath("java/com/par/assistant/android/WebWorkspaceActivity.java")),
                StandardCharsets.UTF_8
        );
        String service = new String(
                Files.readAllBytes(sourcePath("java/com/par/assistant/android/FloatingBallService.java")),
                StandardCharsets.UTF_8
        );
        String prefs = new String(
                Files.readAllBytes(sourcePath("java/com/par/assistant/android/ConfigPrefs.java")),
                StandardCharsets.UTF_8
        );

        assertTrue(activity.contains("public void updateConversationId(String conversationId)"));
        assertTrue(activity.contains("ConfigPrefs.writeConversationId(WebWorkspaceActivity.this, conversationId)"));
        assertTrue(service.contains("activeConversationId = ConfigPrefs.conversationId(this)"));
        assertTrue(service.contains("rememberActiveConversationId"));
        assertTrue(service.contains("ConfigPrefs.writeConversationId(this, conversationId)"));
        assertTrue(prefs.contains("KEY_CONVERSATION_ID"));
        assertTrue(prefs.contains("static String conversationId(Context context)"));
        assertTrue(prefs.contains("static void writeConversationId(Context context, String conversationId)"));
    }

    private static Path sourcePath(String relativePath) {
        Path appModulePath = Paths.get("src/main", relativePath);
        if (Files.exists(appModulePath)) {
            return appModulePath;
        }
        return Paths.get("app/src/main", relativePath);
    }
}
