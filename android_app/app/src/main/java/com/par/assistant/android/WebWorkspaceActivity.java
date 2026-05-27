package com.par.assistant.android;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.provider.Settings;
import android.os.Bundle;
import android.view.Gravity;
import android.view.MotionEvent;
import android.widget.Button;
import android.widget.FrameLayout;
import android.webkit.WebView;
import android.webkit.WebViewClient;

public final class WebWorkspaceActivity extends Activity {
    static final String EXTRA_URL = "com.par.assistant.android.URL";
    static final String EXTRA_PROACTIVE_TITLE = "com.par.assistant.android.PROACTIVE_TITLE";
    static final String EXTRA_PROACTIVE_BODY = "com.par.assistant.android.PROACTIVE_BODY";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        FrameLayout root = new FrameLayout(this);
        WebView webView = new WebView(this);
        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                String password = ConfigPrefs.password(WebWorkspaceActivity.this).replace("'", "\\'");
                view.evaluateJavascript("localStorage.setItem('par-password', '" + password + "')", null);
                String title = getIntent().getStringExtra(EXTRA_PROACTIVE_TITLE);
                String body = getIntent().getStringExtra(EXTRA_PROACTIVE_BODY);
                if ((title != null && !title.isEmpty()) || (body != null && !body.isEmpty())) {
                    try {
                        String payload = new org.json.JSONObject()
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
            }
        });
        root.addView(webView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
        ));

        Button close = new Button(this);
        close.setText("×");
        close.setContentDescription("关闭工作台");
        close.setTextSize(20);
        close.setTextColor(Color.rgb(15, 23, 42));
        close.setBackground(rounded(Color.rgb(226, 232, 240), 0, 16));
        close.setOnClickListener(view -> closeWorkspace());
        close.setOnTouchListener((view, event) -> {
            if (event.getAction() == MotionEvent.ACTION_UP) {
                closeWorkspace();
            }
            return true;
        });
        close.setElevation(dp(16));
        FrameLayout.LayoutParams closeParams = new FrameLayout.LayoutParams(dp(48), dp(48));
        closeParams.gravity = Gravity.TOP | Gravity.END;
        closeParams.setMargins(0, dp(56), dp(12), 0);
        root.addView(close, closeParams);
        close.bringToFront();

        setContentView(root);
        String url = getIntent().getStringExtra(EXTRA_URL);
        webView.loadUrl(url == null || url.trim().isEmpty() ? ConfigPrefs.baseUrlOrDefault(this) : url);
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

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private GradientDrawable rounded(int fillColor, int strokeColor, int radiusDp) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(fillColor);
        drawable.setCornerRadius(dp(radiusDp));
        if (strokeColor != 0) {
            drawable.setStroke(dp(1), strokeColor);
        }
        return drawable;
    }
}
