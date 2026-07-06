package com.par.assistant.android;

import android.app.Activity;
import android.content.Intent;
import android.content.res.Configuration;
import android.net.Uri;
import android.provider.Settings;
import android.os.Bundle;
import android.os.Message;
import android.graphics.Color;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.inputmethod.InputMethodManager;
import android.view.inputmethod.EditorInfo;
import android.content.Context;
import android.text.InputType;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebSettings;

public final class WebWorkspaceActivity extends Activity {
    private static final long WORKSPACE_LOAD_TIMEOUT_MS = 10_000L;
    static final String EXTRA_URL = "com.par.assistant.android.URL";
    static final String EXTRA_PROACTIVE_ID = "com.par.assistant.android.PROACTIVE_ID";
    static final String EXTRA_PROACTIVE_TITLE = "com.par.assistant.android.PROACTIVE_TITLE";
    static final String EXTRA_PROACTIVE_BODY = "com.par.assistant.android.PROACTIVE_BODY";
    static final String EXTRA_REALTIME_EVENT_JSON = "com.par.assistant.android.REALTIME_EVENT_JSON";
    static final String EXTRA_REMOTE_BROWSER_MODE = "com.par.assistant.android.REMOTE_BROWSER_MODE";
    private WebView webView;
    private FrameLayout rootLayout;
    private TextView remoteReconnectBanner;
    private TextView workspaceStatusView;
    private boolean workspaceMainFrameFailed;
    private boolean workspaceLoadCompleted;
    private boolean remoteBrowserMode;
    private boolean remoteBrowserControlsShown;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);

        FrameLayout root = new FrameLayout(this);
        rootLayout = root;
        webView = new WebView(this);
        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.getSettings().setCacheMode(WebSettings.LOAD_NO_CACHE);
        webView.getSettings().setSupportMultipleWindows(true);
        webView.addJavascriptInterface(new WorkspaceBridge(), "NomiAndroid");
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onCreateWindow(WebView view, boolean isDialog, boolean isUserGesture, Message resultMsg) {
                WebView.HitTestResult hitTestResult = view == null ? null : view.getHitTestResult();
                String hitUrl = hitTestResult == null ? "" : hitTestResult.getExtra();
                if (openExternalBrowser(hitUrl)) {
                    return false;
                }

                WebView popup = new WebView(WebWorkspaceActivity.this);
                popup.setWebViewClient(new WebViewClient() {
                    @Override
                    public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                        String url = request == null || request.getUrl() == null ? "" : request.getUrl().toString();
                        openExternalBrowser(url);
                        view.destroy();
                        return true;
                    }

                    @Override
                    public boolean shouldOverrideUrlLoading(WebView view, String url) {
                        openExternalBrowser(url);
                        view.destroy();
                        return true;
                    }
                });
                WebView.WebViewTransport transport = (WebView.WebViewTransport) resultMsg.obj;
                transport.setWebView(popup);
                resultMsg.sendToTarget();
                return true;
            }
        });
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                String url = request == null || request.getUrl() == null ? "" : request.getUrl().toString();
                if (shouldOpenExternally(url)) {
                    return openExternalBrowser(url);
                }
                return false;
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                if (shouldOpenExternally(url)) {
                    return openExternalBrowser(url);
                }
                return false;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (!workspaceMainFrameFailed) {
                    workspaceLoadCompleted = true;
                    hideWorkspaceStatus();
                }
                String password = ConfigPrefs.password(WebWorkspaceActivity.this).replace("'", "\\'");
                view.evaluateJavascript("localStorage.setItem('par-password', '" + password + "')", null);
                String suggestionId = getIntent().getStringExtra(EXTRA_PROACTIVE_ID);
                String title = getIntent().getStringExtra(EXTRA_PROACTIVE_TITLE);
                String body = getIntent().getStringExtra(EXTRA_PROACTIVE_BODY);
                if ((suggestionId != null && !suggestionId.isEmpty()) || (title != null && !title.isEmpty()) || (body != null && !body.isEmpty())) {
                    try {
                        String payload = new org.json.JSONObject()
                                .put("suggestion_id", suggestionId == null ? "" : suggestionId)
                                .put("id", suggestionId == null ? "" : suggestionId)
                                .put("title", title == null ? "" : title)
                                .put("body", body == null ? "" : body)
                                .toString()
                                .replace("\\", "\\\\")
                                .replace("'", "\\'");
                        view.evaluateJavascript("localStorage.setItem('nomi-pending-proactive', '" + payload + "'); window.dispatchEvent(new Event('nomi-pending-proactive'));", null);
                    } catch (org.json.JSONException ignored) {
                        // Static keys and string values should not fail, but avoid blocking the WebView if Android changes behavior.
                    }
                }
                String realtimeEventJson = getIntent().getStringExtra(EXTRA_REALTIME_EVENT_JSON);
                if (realtimeEventJson != null && !realtimeEventJson.trim().isEmpty()) {
                    String payload = org.json.JSONObject.quote(realtimeEventJson);
                    view.evaluateJavascript("localStorage.setItem('nomi-pending-agent-event', " + payload + "); window.dispatchEvent(new Event('nomi-pending-agent-event'));", null);
                }
                if (isRemoteBrowserUrl(url)) {
                    remoteBrowserMode = true;
                    ensureRemoteBrowserControls();
                    hideRemoteReconnectBanner();
                    checkRemoteBrowserDisconnected(view);
                }
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request != null && !request.isForMainFrame()) {
                    return;
                }
                String description = error == null || error.getDescription() == null
                        ? "服务器地址或网络不可用。"
                        : error.getDescription().toString();
                workspaceMainFrameFailed = true;
                workspaceLoadCompleted = true;
                showWorkspaceStatus("完整 App 加载失败\n服务器地址或网络不可用。\n" + description);
            }
        });
        root.addView(webView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
        ));
        workspaceStatusView = new TextView(this);
        workspaceStatusView.setTextColor(Color.rgb(71, 85, 105));
        workspaceStatusView.setTextSize(15);
        workspaceStatusView.setGravity(Gravity.CENTER);
        workspaceStatusView.setPadding(dp(24), dp(24), dp(24), dp(24));
        workspaceStatusView.setBackgroundColor(Color.WHITE);
        root.addView(workspaceStatusView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
        ));

        setContentView(root);
        String url = getIntent().getStringExtra(EXTRA_URL);
        String initialUrl = url == null || url.trim().isEmpty() ? ConfigPrefs.baseUrlOrDefault(this) : url;
        remoteBrowserMode = getIntent().getBooleanExtra(EXTRA_REMOTE_BROWSER_MODE, false)
                || isRemoteBrowserUrl(initialUrl);
        workspaceMainFrameFailed = false;
        workspaceLoadCompleted = false;
        showWorkspaceStatus("正在加载完整 App...");
        root.postDelayed(() -> {
            if (workspaceLoadCompleted || isFinishing()) return;
            workspaceMainFrameFailed = true;
            showWorkspaceStatus("完整 App 加载失败\n服务器地址或网络不可用。\n加载超时，请检查服务器是否已启动。");
        }, WORKSPACE_LOAD_TIMEOUT_MS);
        if (remoteBrowserMode) {
            ensureRemoteBrowserControls();
        }
        webView.loadUrl(initialUrl);
    }

    private void showWorkspaceStatus(String message) {
        if (workspaceStatusView == null) return;
        workspaceStatusView.setText(message == null ? "" : message);
        workspaceStatusView.setVisibility(View.VISIBLE);
    }

    private void hideWorkspaceStatus() {
        if (workspaceStatusView == null) return;
        workspaceStatusView.setVisibility(View.GONE);
    }

    private boolean openExternalBrowser(String rawUrl) {
        String url = rawUrl == null ? "" : rawUrl.trim();
        if (isRemoteBrowserUrl(url)) {
            remoteBrowserMode = true;
            ensureRemoteBrowserControls();
            if (webView != null) {
                webView.loadUrl(url);
                return true;
            }
            return false;
        }
        if (!shouldOpenExternally(url)) {
            return false;
        }
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        startActivity(intent);
        return true;
    }

    private boolean shouldOpenExternally(String rawUrl) {
        String url = rawUrl == null ? "" : rawUrl.trim();
        if (!(url.startsWith("http://") || url.startsWith("https://"))) {
            return false;
        }
        if (isRemoteBrowserUrl(url)) {
            return false;
        }
        return !isWorkspaceUrl(url);
    }

    private boolean isWorkspaceUrl(String rawUrl) {
        if (isRemoteBrowserUrl(rawUrl)) {
            return true;
        }
        try {
            Uri target = Uri.parse(rawUrl);
            Uri workspace = Uri.parse(ConfigPrefs.baseUrlOrDefault(this));
            if (target.getHost() == null || workspace.getHost() == null) {
                return false;
            }
            int targetPort = target.getPort() == -1 ? defaultPort(target.getScheme()) : target.getPort();
            int workspacePort = workspace.getPort() == -1 ? defaultPort(workspace.getScheme()) : workspace.getPort();
            return target.getHost().equalsIgnoreCase(workspace.getHost())
                    && targetPort == workspacePort
                    && String.valueOf(target.getScheme()).equalsIgnoreCase(String.valueOf(workspace.getScheme()));
        } catch (Exception error) {
            return false;
        }
    }

    private int defaultPort(String scheme) {
        return "https".equalsIgnoreCase(scheme) ? 443 : 80;
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        refreshWebViewAfterConfigurationChange();
    }

    private final class WorkspaceBridge {
        @JavascriptInterface
        public void closeWorkspace() {
            runOnUiThread(WebWorkspaceActivity.this::closeWorkspace);
        }

        @JavascriptInterface
        public void onRemoteBrowserDisconnected() {
            runOnUiThread(WebWorkspaceActivity.this::showRemoteReconnectBanner);
        }

        @JavascriptInterface
        public void enterRemoteBrowserMode() {
            runOnUiThread(() -> {
                remoteBrowserMode = true;
                ensureRemoteBrowserControls();
            });
        }

        @JavascriptInterface
        public void openExternalUrl(String url) {
            runOnUiThread(() -> openExternalBrowser(url));
        }

        @JavascriptInterface
        public void updateConversationId(String conversationId) {
            runOnUiThread(() -> ConfigPrefs.writeConversationId(WebWorkspaceActivity.this, conversationId));
        }
    }

    private void closeWorkspace() {
        if (Settings.canDrawOverlays(this)) {
            Intent service = new Intent(this, FloatingBallService.class);
            startForegroundService(service);
            Intent home = new Intent(Intent.ACTION_MAIN);
            home.addCategory(Intent.CATEGORY_HOME);
            home.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(home);
        }
        finish();
        overridePendingTransition(0, 0);
    }

    private void closeRemoteBrowserToAccounts() {
        if (Settings.canDrawOverlays(this)) {
            Intent service = new Intent(this, FloatingBallService.class);
            service.setAction(FloatingBallService.ACTION_SHOW_ACCOUNTS);
            service.putExtra(FloatingBallService.EXTRA_AUTH_MESSAGE, "登录页已关闭，正在刷新账号状态。");
            startForegroundService(service);
        }
        finish();
        overridePendingTransition(0, 0);
    }

    @Override
    public void onBackPressed() {
        if (remoteBrowserMode) {
            closeRemoteBrowserToAccounts();
            return;
        }
        super.onBackPressed();
    }

    private boolean isRemoteBrowserUrl(String url) {
        String value = url == null ? "" : url.toLowerCase();
        return value.contains("vnc_lite.html") || value.contains(":6080/");
    }

    private void ensureRemoteBrowserControls() {
        if (rootLayout == null || remoteBrowserControlsShown) {
            return;
        }
        remoteBrowserControlsShown = true;
        showRemoteInputBar(rootLayout);
        showRemoteBrowserExitButton(rootLayout);
    }

    private void showRemoteBrowserExitButton(FrameLayout root) {
        Button back = new Button(this);
        back.setText("返回账号");
        back.setContentDescription("返回账号列表");
        back.setTextSize(14);
        back.setAllCaps(false);
        back.setTextColor(Color.rgb(15, 23, 42));
        back.setBackgroundColor(Color.rgb(226, 232, 240));
        back.setElevation(dp(14));
        back.setOnClickListener(view -> closeRemoteBrowserToAccounts());

        FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(dp(96), dp(48));
        params.gravity = Gravity.TOP | Gravity.END;
        params.setMargins(0, dp(38), dp(12), 0);
        root.addView(back, params);
        back.bringToFront();
    }

    private void showRemoteInputBar(FrameLayout root) {
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.VERTICAL);
        bar.setPadding(dp(12), dp(10), dp(12), dp(10));
        bar.setBackgroundColor(Color.rgb(245, 248, 252));

        TextView hint = new TextView(this);
        hint.setText("先点远端输入框，再在这里输入。");
        hint.setTextColor(Color.rgb(75, 85, 99));
        hint.setTextSize(13);
        bar.addView(hint, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        ));

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);

        EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setHint("输入到远端");
        input.setInputType(InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_VARIATION_NORMAL
                | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        input.setImeOptions(EditorInfo.IME_ACTION_DONE | EditorInfo.IME_FLAG_NO_EXTRACT_UI);
        row.addView(input, new LinearLayout.LayoutParams(
                0,
                dp(52),
                1f
        ));

        Button send = new Button(this);
        send.setText("发送到远端");
        row.addView(send, new LinearLayout.LayoutParams(
                dp(116),
                dp(52)
        ));
        bar.addView(row, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        ));

        send.setOnClickListener(view -> sendRemoteText(input, false));
        input.setOnEditorActionListener((view, actionId, event) -> {
            sendRemoteText(input, false);
            return true;
        });
        input.setOnFocusChangeListener((view, hasFocus) -> {
            if (hasFocus) {
                InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
                if (imm != null) {
                    imm.showSoftInput(input, InputMethodManager.SHOW_IMPLICIT);
                }
            }
        });

        FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT
        );
        params.gravity = Gravity.BOTTOM;
        root.addView(bar, params);
    }

    private void checkRemoteBrowserDisconnected(WebView view) {
        view.evaluateJavascript(
                "(() => {"
                        + "const text = ((document.body && document.body.innerText) || '').trim();"
                        + "const disconnected = /Disconnected|连接已断开|断开连接|connection\\s+closed/i.test(text);"
                        + "if (disconnected && window.NomiAndroid && window.NomiAndroid.onRemoteBrowserDisconnected) {"
                        + "window.NomiAndroid.onRemoteBrowserDisconnected();"
                        + "}"
                        + "return disconnected;"
                        + "})()",
                null
        );
    }

    private void showRemoteReconnectBanner() {
        if (rootLayout == null) {
            return;
        }
        if (remoteReconnectBanner == null) {
            TextView banner = new TextView(this);
            banner.setText("远程浏览器已断开，点此重连");
            banner.setTextColor(Color.WHITE);
            banner.setTextSize(15);
            banner.setGravity(Gravity.CENTER);
            banner.setPadding(dp(16), dp(10), dp(16), dp(10));
            banner.setBackgroundColor(Color.rgb(15, 23, 42));
            banner.setOnClickListener(view -> {
                hideRemoteReconnectBanner();
                if (webView != null) {
                    webView.reload();
                }
            });
            FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.WRAP_CONTENT,
                    FrameLayout.LayoutParams.WRAP_CONTENT
            );
            params.gravity = Gravity.TOP | Gravity.CENTER_HORIZONTAL;
            params.topMargin = dp(16);
            rootLayout.addView(banner, params);
            remoteReconnectBanner = banner;
        }
        remoteReconnectBanner.setVisibility(View.VISIBLE);
    }

    private void hideRemoteReconnectBanner() {
        if (remoteReconnectBanner != null) {
            remoteReconnectBanner.setVisibility(View.GONE);
        }
    }

    private void sendRemoteText(EditText input, boolean submit) {
        String text = input.getText() == null ? "" : input.getText().toString();
        if (text.trim().isEmpty()) {
            Toast.makeText(this, "请输入要发送到远端的内容", Toast.LENGTH_SHORT).show();
            return;
        }
        input.setEnabled(false);
        new Thread(() -> {
            try {
                new AssistantApiClient(ConfigPrefs.read(this)).requestRemoteBrowserType(text, submit);
                runOnUiThread(() -> {
                    input.setText("");
                    input.setEnabled(true);
                    input.requestFocus();
                    Toast.makeText(this, "已发送到远端输入框", Toast.LENGTH_SHORT).show();
                });
            } catch (Exception error) {
                runOnUiThread(() -> {
                    input.setEnabled(true);
                    input.requestFocus();
                    Toast.makeText(this, "远端输入失败：" + error.getMessage(), Toast.LENGTH_LONG).show();
                });
            }
        }).start();
    }

    private void refreshWebViewAfterConfigurationChange() {
        if (webView == null) {
            return;
        }
        webView.requestLayout();
        webView.invalidate();
        webView.postDelayed(() -> {
            webView.requestLayout();
            webView.invalidate();
            webView.evaluateJavascript("window.dispatchEvent(new Event('resize'))", null);
        }, 120);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

}
