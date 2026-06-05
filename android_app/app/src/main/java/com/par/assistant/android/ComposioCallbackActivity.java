package com.par.assistant.android;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;

public final class ComposioCallbackActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        handle(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handle(intent);
    }

    private void handle(Intent intent) {
        Uri uri = intent == null ? null : intent.getData();
        String toolkit = uri == null ? "" : uri.getQueryParameter("toolkit");
        String status = uri == null ? "" : uri.getQueryParameter("status");
        Intent service = new Intent(this, FloatingBallService.class);
        service.setAction(FloatingBallService.ACTION_SHOW_ACCOUNTS);
        service.putExtra(
                FloatingBallService.EXTRA_AUTH_MESSAGE,
                ComposioCallbackPayload.statusMessage(toolkit, status)
        );
        startForegroundService(service);

        Intent home = new Intent(Intent.ACTION_MAIN);
        home.addCategory(Intent.CATEGORY_HOME);
        home.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        startActivity(home);
        finish();
        overridePendingTransition(0, 0);
    }
}
