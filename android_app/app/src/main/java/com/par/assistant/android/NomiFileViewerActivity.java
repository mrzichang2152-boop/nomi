package com.par.assistant.android;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

public final class NomiFileViewerActivity extends Activity {
    private static final String EXTRA_VIEWER_URL = "com.par.assistant.android.FILE_VIEWER_URL";
    private WebView webView;
    private TextView errorView;
    private boolean floatingBallRestored;
    private final ExecutorService downloadExecutor = Executors.newSingleThreadExecutor();
    private final AtomicBoolean downloadInProgress = new AtomicBoolean();

    static Intent intentFor(Context context, String source, String filename, String mimeType) {
        String viewerUrl = FileViewerUrls.viewerUrl(
                ConfigPrefs.baseUrlOrDefault(context),
                source,
                filename,
                mimeType
        );
        return intentFor(context, viewerUrl);
    }

    static Intent intentFor(Context context, String viewerUrl) {
        Intent intent = new Intent(context, NomiFileViewerActivity.class);
        intent.putExtra(
                EXTRA_VIEWER_URL,
                FileViewerUrls.normalizeTrustedViewerUrl(
                        ConfigPrefs.baseUrlOrDefault(context),
                        viewerUrl
                )
        );
        if (!(context instanceof Activity)) intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        return intent;
    }

    @Override
    protected void onStart() {
        super.onStart();
        NomiForegroundUiState.enter();
        startForegroundService(FloatingBallService.clearProactiveOverlayIntent(this));
    }

    @Override
    protected void onStop() {
        NomiForegroundUiState.exit();
        super.onStop();
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.rgb(237, 241, 244));
        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        webView.addJavascriptInterface(new ViewerBridge(), "NomiViewer");
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                String url = request == null || request.getUrl() == null ? "" : request.getUrl().toString();
                return blockUntrustedNavigation(url);
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return blockUntrustedNavigation(url);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                hideError();
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request != null && request.isForMainFrame()) {
                    showError("Nomi 文件查看器加载失败，请检查服务器连接后重试。");
                }
            }
        });
        root.addView(webView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
        ));

        errorView = new TextView(this);
        errorView.setTextColor(Color.rgb(71, 85, 105));
        errorView.setTextSize(15);
        errorView.setGravity(Gravity.CENTER);
        errorView.setPadding(40, 40, 40, 40);
        errorView.setBackgroundColor(Color.rgb(244, 246, 248));
        errorView.setVisibility(View.GONE);
        root.addView(errorView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
        ));
        setContentView(root);

        String viewerUrl = FileViewerUrls.normalizeTrustedViewerUrl(
                ConfigPrefs.baseUrlOrDefault(this),
                getIntent().getStringExtra(EXTRA_VIEWER_URL)
        );
        if (viewerUrl.isEmpty()) {
            showError("文件地址无效，Nomi 已阻止打开。请返回对话后重试。");
            return;
        }
        webView.loadUrl(viewerUrl);
    }

    private boolean blockUntrustedNavigation(String url) {
        if (FileViewerUrls.isTrustedViewerUrl(ConfigPrefs.baseUrlOrDefault(this), url)) return false;
        Toast.makeText(this, "Nomi 已阻止文件查看器跳转到外部页面", Toast.LENGTH_SHORT).show();
        return true;
    }

    private void showError(String message) {
        if (errorView == null) return;
        errorView.setText(message == null ? "文件查看失败。" : message);
        errorView.setVisibility(View.VISIBLE);
    }

    private void hideError() {
        if (errorView != null) errorView.setVisibility(View.GONE);
    }

    private void closeViewer() {
        restoreFloatingBall();
        finish();
        overridePendingTransition(0, 0);
    }

    private void restoreFloatingBall() {
        if (floatingBallRestored) return;
        floatingBallRestored = true;
        startForegroundService(new Intent(this, FloatingBallService.class));
    }

    @Override
    public void onBackPressed() {
        closeViewer();
    }

    @Override
    protected void onDestroy() {
        restoreFloatingBall();
        downloadExecutor.shutdownNow();
        if (webView != null) {
            webView.removeJavascriptInterface("NomiViewer");
            webView.stopLoading();
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }

    private final class ViewerBridge {
        @JavascriptInterface
        public String getPassword() {
            return ConfigPrefs.password(NomiFileViewerActivity.this);
        }

        @JavascriptInterface
        public void closeViewer() {
            runOnUiThread(NomiFileViewerActivity.this::closeViewer);
        }

        @JavascriptInterface
        public boolean downloadFile(String source, String filename, String mimeType) {
            if (!downloadInProgress.compareAndSet(false, true)) {
                return false;
            }
            try {
                downloadExecutor.execute(() -> {
                    OriginalFileDownload.Result result = OriginalFileDownload.download(
                            NomiFileViewerActivity.this,
                            ConfigPrefs.baseUrlOrDefault(NomiFileViewerActivity.this),
                            ConfigPrefs.password(NomiFileViewerActivity.this),
                            source,
                            filename,
                            mimeType
                    );
                    downloadInProgress.set(false);
                    notifyDownloadFinished(result);
                });
                return true;
            } catch (RuntimeException error) {
                downloadInProgress.set(false);
                return false;
            }
        }
    }

    private void notifyDownloadFinished(OriginalFileDownload.Result result) {
        boolean success = result != null && result.success;
        String message = result == null ? "下载失败，请重新尝试。" : result.message;
        String script = "window.NomiViewerDownloadFinished && window.NomiViewerDownloadFinished("
                + success
                + ","
                + JSONObject.quote(message)
                + ");";
        runOnUiThread(() -> {
            if (webView != null) webView.evaluateJavascript(script, null);
        });
    }
}
