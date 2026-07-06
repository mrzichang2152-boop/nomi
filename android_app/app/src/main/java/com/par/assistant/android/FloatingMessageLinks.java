package com.par.assistant.android;

import android.content.Intent;
import android.net.Uri;
import android.text.Layout;
import android.text.Spannable;
import android.text.method.LinkMovementMethod;
import android.text.style.ClickableSpan;
import android.text.style.URLSpan;
import android.text.util.Linkify;
import android.view.MotionEvent;
import android.widget.TextView;

import java.util.regex.Pattern;

final class FloatingMessageLinks {
    private static final Pattern HTTP_URL = Pattern.compile("https?://\\S+");
    private static final Pattern LINKEDIN_JOB_DETAIL_URL = Pattern.compile(
            "^https?://(www\\.)?linkedin\\.com/jobs/view/[0-9]+/?(?:[?#].*)?$",
            Pattern.CASE_INSENSITIVE
    );

    interface UrlOpener {
        boolean open(String url);
    }

    private FloatingMessageLinks() {
    }

    static boolean containsWebUrl(String text) {
        return text != null && HTTP_URL.matcher(text).find();
    }

    static String firstWebUrl(String text) {
        if (text == null) return "";
        java.util.regex.Matcher matcher = HTTP_URL.matcher(text);
        if (!matcher.find()) return "";
        return trimTrailingPunctuation(matcher.group());
    }

    static void enableClickableLinks(TextView view) {
        enableClickableLinks(view, (UrlOpener) null);
    }

    static void enableClickableLinks(TextView view, Runnable beforeOpen) {
        enableClickableLinks(view, url -> {
            if (beforeOpen != null) beforeOpen.run();
            return false;
        });
    }

    static void enableClickableLinks(TextView view, UrlOpener opener) {
        if (view == null || !containsWebUrl(String.valueOf(view.getText()))) return;
        view.setAutoLinkMask(Linkify.WEB_URLS);
        Linkify.addLinks(view, Linkify.WEB_URLS);
        view.setLinksClickable(true);
        view.setMovementMethod(LinkMovementMethod.getInstance());
        view.setOnTouchListener((target, event) -> target instanceof TextView textView
                && FloatingMessageLinks.handleLinkTouch(textView, event, opener));
        view.setFocusable(false);
        view.setClickable(true);
        view.setOnClickListener(target -> openUrl(view, firstWebUrl(String.valueOf(view.getText())), opener));
    }

    static boolean isLinkedInJobDetailUrl(String url) {
        return url != null && LINKEDIN_JOB_DETAIL_URL.matcher(trimTrailingPunctuation(url)).matches();
    }

    private static boolean handleLinkTouch(TextView view, MotionEvent event, UrlOpener opener) {
        int action = event.getAction();
        if (action != MotionEvent.ACTION_DOWN && action != MotionEvent.ACTION_UP) return false;
        if (!(view.getText() instanceof Spannable spannable)) return false;
        ClickableSpan[] links = linksAt(view, spannable, event);
        if (links.length == 0) return false;
        if (action == MotionEvent.ACTION_UP) {
            openLink(view, links[0], opener);
        }
        return true;
    }

    private static void openLink(TextView view, ClickableSpan span, UrlOpener opener) {
        if (span instanceof URLSpan urlSpan) {
            openUrl(view, urlSpan.getURL(), opener);
            return;
        }
        span.onClick(view);
    }

    private static void openUrl(TextView view, String url, UrlOpener opener) {
        if (url == null || url.trim().isEmpty()) return;
        String cleanUrl = trimTrailingPunctuation(url.trim());
        if (opener != null && opener.open(cleanUrl)) return;
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(cleanUrl));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        view.getContext().startActivity(intent);
    }

    private static String trimTrailingPunctuation(String url) {
        String result = url == null ? "" : url.trim();
        while (result.endsWith(")") || result.endsWith("]") || result.endsWith("。") || result.endsWith(",") || result.endsWith("，")) {
            result = result.substring(0, result.length() - 1);
        }
        return result;
    }

    private static ClickableSpan[] linksAt(TextView view, Spannable spannable, MotionEvent event) {
        Layout layout = view.getLayout();
        if (layout == null) return new ClickableSpan[0];
        int x = (int) event.getX() - view.getTotalPaddingLeft() + view.getScrollX();
        int y = (int) event.getY() - view.getTotalPaddingTop() + view.getScrollY();
        if (x < 0 || y < 0) return new ClickableSpan[0];
        int line = layout.getLineForVertical(y);
        if (line < 0 || line >= layout.getLineCount()) return new ClickableSpan[0];
        int offset = layout.getOffsetForHorizontal(line, x);
        return spannable.getSpans(offset, offset, ClickableSpan.class);
    }
}
