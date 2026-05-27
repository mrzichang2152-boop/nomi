package com.par.assistant.android;

import android.content.Intent;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import android.app.Activity;

import com.par.assistant.core.ServerConfig;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private EditText baseUrlInput;
    private EditText passwordInput;
    private TextView statusText;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(buildView());
    }

    private LinearLayout buildView() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setBackgroundColor(Color.rgb(248, 250, 252));
        int pad = dp(20);
        root.setPadding(pad, pad, pad, pad);

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);

        TextView title = new TextView(this);
        title.setText("Nomi");
        title.setTextSize(22);
        title.setTextColor(Color.rgb(15, 23, 42));
        header.addView(title, new LinearLayout.LayoutParams(0, -2, 1));

        Button close = new Button(this);
        close.setText("×");
        close.setTextSize(20);
        close.setTextColor(Color.rgb(15, 23, 42));
        close.setBackground(rounded(Color.rgb(226, 232, 240), 0, 16));
        close.setOnClickListener(view -> closePageOnly());
        header.addView(close, new LinearLayout.LayoutParams(dp(48), dp(48)));
        root.addView(header, matchWidthWithoutTopMargin());

        TextView subtitle = new TextView(this);
        subtitle.setText("你的私人助理，运行在你自己的环境里。");
        subtitle.setTextColor(Color.rgb(100, 116, 139));
        subtitle.setTextSize(14);
        root.addView(subtitle, matchWidth());

        baseUrlInput = new EditText(this);
        baseUrlInput.setHint("服务器地址");
        baseUrlInput.setSingleLine(true);
        baseUrlInput.setText(ConfigPrefs.baseUrlOrDefault(this));
        baseUrlInput.setBackground(rounded(Color.WHITE, Color.rgb(203, 213, 225), 12));
        baseUrlInput.setPadding(dp(14), 0, dp(14), 0);
        root.addView(baseUrlInput, matchWidth());

        passwordInput = new EditText(this);
        passwordInput.setHint("访问密码");
        passwordInput.setSingleLine(true);
        passwordInput.setText(ConfigPrefs.password(this));
        passwordInput.setBackground(rounded(Color.WHITE, Color.rgb(203, 213, 225), 12));
        passwordInput.setPadding(dp(14), 0, dp(14), 0);
        root.addView(passwordInput, matchWidth());

        Button save = new Button(this);
        save.setText("保存并测试连接");
        styleSecondaryButton(save);
        save.setOnClickListener(view -> saveAndTest());
        root.addView(save, matchWidth());

        Button overlay = new Button(this);
        overlay.setText("启动 Nomi");
        stylePrimaryButton(overlay);
        overlay.setOnClickListener(view -> startFloatingBall());
        root.addView(overlay, matchWidth());

        Button web = new Button(this);
        web.setText("打开完整工作台");
        styleSecondaryButton(web);
        web.setOnClickListener(view -> startActivity(new Intent(this, WebWorkspaceActivity.class)));
        root.addView(web, matchWidth());

        statusText = new TextView(this);
        statusText.setText("保存配置后，Nomi 会以小人形象留在屏幕上。");
        statusText.setTextColor(Color.rgb(71, 85, 105));
        root.addView(statusText, matchWidth());
        return root;
    }

    private void saveAndTest() {
        try {
            ServerConfig config = ServerConfig.create(baseUrlInput.getText().toString(), passwordInput.getText().toString());
            ConfigPrefs.write(this, config);
            statusText.setText("连接测试中...");
            executor.execute(() -> {
                try {
                    boolean ok = new AssistantApiClient(config).health();
                    runOnUiThread(() -> statusText.setText(ok ? "连接正常" : "服务器状态异常"));
                } catch (Exception error) {
                    runOnUiThread(() -> statusText.setText("连接失败：" + error.getMessage()));
                }
            });
        } catch (IllegalArgumentException error) {
            statusText.setText(error.getMessage());
        }
    }

    private void startFloatingBall() {
        if (!Settings.canDrawOverlays(this)) {
            Intent intent = new Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:" + getPackageName())
            );
            startActivity(intent);
            statusText.setText("请授权显示在其他应用上层。");
            return;
        }
        startForegroundService(new Intent(this, FloatingBallService.class));
        closePageOnly();
    }

    private void closePageOnly() {
        moveTaskToBack(true);
    }

    private LinearLayout.LayoutParams matchWidth() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
        params.topMargin = dp(12);
        return params;
    }

    private LinearLayout.LayoutParams matchWidthWithoutTopMargin() {
        return new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
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

    private void stylePrimaryButton(Button button) {
        button.setAllCaps(false);
        button.setTextColor(Color.WHITE);
        button.setBackground(rounded(Color.rgb(15, 118, 110), 0, 14));
    }

    private void styleSecondaryButton(Button button) {
        button.setAllCaps(false);
        button.setTextColor(Color.rgb(15, 118, 110));
        button.setBackground(rounded(Color.rgb(204, 251, 241), 0, 14));
    }
}
