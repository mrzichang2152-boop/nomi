package com.par.assistant.android;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.view.View;

public final class NomiAvatarView extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private int unreadCount;

    public NomiAvatarView(Context context) {
        super(context);
        setContentDescription("Nomi");
    }

    public void setUnreadCount(int unreadCount) {
        this.unreadCount = Math.max(0, unreadCount);
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float width = getWidth();
        float height = getHeight();
        float size = Math.min(width, height);
        float cx = width / 2f;
        float cy = height / 2f;
        float radius = size * 0.46f;

        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.rgb(15, 118, 110));
        canvas.drawCircle(cx, cy, radius, paint);

        paint.setColor(Color.rgb(204, 251, 241));
        canvas.drawCircle(cx, cy - size * 0.10f, size * 0.16f, paint);

        RectF body = new RectF(
                cx - size * 0.23f,
                cy + size * 0.07f,
                cx + size * 0.23f,
                cy + size * 0.34f
        );
        canvas.drawRoundRect(body, size * 0.12f, size * 0.12f, paint);

        paint.setColor(Color.rgb(4, 47, 46));
        canvas.drawCircle(cx - size * 0.055f, cy - size * 0.11f, size * 0.018f, paint);
        canvas.drawCircle(cx + size * 0.055f, cy - size * 0.11f, size * 0.018f, paint);

        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(size * 0.025f);
        paint.setColor(Color.rgb(94, 234, 212));
        canvas.drawArc(
                new RectF(cx - size * 0.09f, cy - size * 0.10f, cx + size * 0.09f, cy + size * 0.03f),
                20,
                140,
                false,
                paint
        );

        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.rgb(45, 212, 191));
        canvas.drawCircle(cx + size * 0.27f, cy - size * 0.30f, size * 0.055f, paint);

        if (unreadCount > 0) {
            drawBadge(canvas, size);
        }
    }

    private void drawBadge(Canvas canvas, float size) {
        String label = unreadCount > 99 ? "99+" : String.valueOf(unreadCount);
        float badgeRadius = size * 0.18f;
        float badgeCx = getWidth() - badgeRadius * 0.92f;
        float badgeCy = badgeRadius * 0.92f;

        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.rgb(244, 63, 94));
        canvas.drawCircle(badgeCx, badgeCy, badgeRadius, paint);

        paint.setColor(Color.WHITE);
        paint.setTextAlign(Paint.Align.CENTER);
        paint.setTypeface(Typeface.DEFAULT_BOLD);
        paint.setTextSize(label.length() > 2 ? size * 0.15f : size * 0.18f);
        Paint.FontMetrics metrics = paint.getFontMetrics();
        float baseline = badgeCy - (metrics.ascent + metrics.descent) / 2f;
        canvas.drawText(label, badgeCx, baseline, paint);
        paint.setTypeface(Typeface.DEFAULT);
    }
}
