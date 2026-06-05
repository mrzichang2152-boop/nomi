package com.par.assistant.android;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.widget.Toast;

public final class MicrophonePermissionActivity extends Activity {
    static final String EXTRA_REASON = "com.par.assistant.android.MICROPHONE_PERMISSION_REASON";
    private static final int REQUEST_RECORD_AUDIO = 2101;

    static LaunchSpec launchSpec(String reason) {
        return new LaunchSpec(MicrophonePermissionActivity.class.getName(), reason == null ? "" : reason, true);
    }

    static Intent intent(Context context, String reason) {
        Intent intent = new Intent(context, MicrophonePermissionActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        intent.putExtra(EXTRA_REASON, reason == null ? "" : reason);
        return intent;
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        requestPermissionOrFinish();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (Build.VERSION.SDK_INT >= 23
                && checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            restartFloatingBallIfAllowed();
            finish();
        }
    }

    private void requestPermissionOrFinish() {
        if (Build.VERSION.SDK_INT < 23
                || checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            restartFloatingBallIfAllowed();
            finish();
            return;
        }
        requestPermissions(new String[] {Manifest.permission.RECORD_AUDIO}, REQUEST_RECORD_AUDIO);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != REQUEST_RECORD_AUDIO) return;
        boolean granted = grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED;
        if (granted) {
            restartFloatingBallIfAllowed();
        } else {
            Toast.makeText(this, "没有麦克风权限，暂时无法语音输入。", Toast.LENGTH_SHORT).show();
        }
        finish();
    }

    private void restartFloatingBallIfAllowed() {
        if (!Settings.canDrawOverlays(this)) {
            Toast.makeText(this, "麦克风已授权，请先允许 Nomi 显示在其他应用上层。", Toast.LENGTH_SHORT).show();
            return;
        }
        startForegroundService(new Intent(this, FloatingBallService.class));
    }

    static final class LaunchSpec {
        final String activityClassName;
        final String reason;
        final boolean newTask;

        LaunchSpec(String activityClassName, String reason, boolean newTask) {
            this.activityClassName = activityClassName;
            this.reason = reason;
            this.newTask = newTask;
        }
    }
}
