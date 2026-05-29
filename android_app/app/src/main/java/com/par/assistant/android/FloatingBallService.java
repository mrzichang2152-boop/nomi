package com.par.assistant.android;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Insets;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.IBinder;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewTreeObserver;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageButton;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import com.par.assistant.core.AssistantSuggestion;
import com.par.assistant.core.ServerConfig;
import com.par.assistant.core.SuggestionDeduper;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class FloatingBallService extends Service {
    private static final String CHANNEL_ID = "par-floating-ball";
    private static final int NOTIFICATION_ID = 1001;

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private WindowManager windowManager;
    private NomiAvatarView ballView;
    private TextView bubbleView;
    private WindowManager.LayoutParams ballParams;
    private WindowManager.LayoutParams bubbleParams;
    private WindowManager.LayoutParams panelParams;
    private LinearLayout panelView;
    private TextView responseView;
    private LinearLayout suggestionsView;
    private LinearLayout accountsView;
    private ScrollView accountsScrollView;
    private LinearLayout chatContentView;
    private LinearLayout settingsContentView;
    private LinearLayout chatHistoryView;
    private ScrollView chatScrollView;
    private int unreadCount;
    private SuggestionPoller poller;
    private RealtimeClient realtimeClient;
    private ProactiveMessage lastProactiveMessage;
    private final FloatingChatContext chatContext = new FloatingChatContext();
    private String activeConversationId;
    private ViewTreeObserver.OnGlobalLayoutListener panelLayoutListener;
    private int panelDefaultY;
    private int panelDefaultHeight;
    private boolean panelInputFocused;
    private static final AccountChannel[] ACCOUNT_CHANNELS = new AccountChannel[] {
            new AccountChannel("gmail", "Gmail", "邮件、订单、验证码提醒、邮件正文快照", true),
            new AccountChannel("whatsapp", "WhatsApp Web", "聊天预览、打开会话历史、新消息监听", true),
            new AccountChannel("telegram", "Telegram Web", "聊天列表和可见消息预览", true),
            new AccountChannel("calendar", "Google Calendar", "日程、会议、提醒", true),
            new AccountChannel("search", "Google Search", "搜索记录和浏览器页面信号", true),
            new AccountChannel("bookmark", "Chrome Bookmarks", "服务器浏览器书签", false),
            new AccountChannel("focus", "浏览行为", "点击、滚动、输入等本地浏览焦点信号", false),
            new AccountChannel("shopping", "购物/电商", "通过 Gmail 订单邮件和浏览器页面间接支持", true)
    };

    @Override
    public void onCreate() {
        super.onCreate();
        windowManager = (WindowManager) getSystemService(WINDOW_SERVICE);
        startForeground(NOTIFICATION_ID, notification("Nomi 正在陪伴你", "点击打开完整工作台"));
        showBall();
        startRealtime();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        if (poller != null) poller.stop();
        if (realtimeClient != null) realtimeClient.stop();
        removeView(ballView);
        removeView(bubbleView);
        closePanel();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void showBall() {
        ballView = new NomiAvatarView(this);

        ballParams = overlayParams(dp(72), dp(72), false);
        ballParams.gravity = Gravity.TOP | Gravity.START;
        ballParams.x = dp(12);
        ballParams.y = dp(140);

        DragController drag = new DragController(ballParams, () -> togglePanel());
        ballView.setOnTouchListener(drag);
        ballView.setOnLongClickListener(view -> {
            Intent intent = new Intent(this, MainActivity.class);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(intent);
            return true;
        });
        windowManager.addView(ballView, ballParams);
    }

    private void togglePanel() {
        if (panelView == null) {
            removeBubble();
            showPanel();
        } else {
            closePanel();
        }
    }

    private void showPanel() {
        unreadCount = 0;
        updateBallBadge();

        panelView = new LinearLayout(this);
        panelView.setOrientation(LinearLayout.VERTICAL);
        panelView.setPadding(dp(12), dp(12), dp(12), dp(12));
        panelView.setBackground(rounded(Color.WHITE, 0, 18));
        panelView.setElevation(dp(8));

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);

        TextView title = new TextView(this);
        title.setText("Nomi");
        title.setTextSize(18);
        title.setTextColor(Color.rgb(15, 23, 42));
        header.addView(title, new LinearLayout.LayoutParams(0, -2, 1));

        ImageButton web = iconButton(android.R.drawable.ic_menu_view, "打开完整工作台");
        web.setOnClickListener(view -> openWorkbench());
        header.addView(web, new LinearLayout.LayoutParams(dp(42), dp(42)));

        ImageButton settings = iconButton(android.R.drawable.ic_menu_manage, "设置");
        settings.setOnClickListener(view -> showSettingsView());
        header.addView(settings, new LinearLayout.LayoutParams(dp(42), dp(42)));

        Button close = closeButton();
        close.setOnClickListener(view -> closePanel());
        header.addView(close, new LinearLayout.LayoutParams(dp(42), dp(42)));
        panelView.addView(header);

        chatContentView = new LinearLayout(this);
        chatContentView.setOrientation(LinearLayout.VERTICAL);

        chatHistoryView = new LinearLayout(this);
        chatHistoryView.setOrientation(LinearLayout.VERTICAL);
        chatHistoryView.setPadding(0, dp(8), 0, dp(8));
        chatScrollView = new ScrollView(this);
        chatScrollView.setFillViewport(false);
        chatScrollView.addView(chatHistoryView);
        chatContentView.addView(chatScrollView, new LinearLayout.LayoutParams(-1, 0, 1));

        addChatMessage("Nomi", "我在这里。你可以直接发消息，也可以点右上角打开完整工作台。");
        if (lastProactiveMessage != null) {
            String proactive = bubbleText(lastProactiveMessage);
            addChatMessage("Nomi", proactive);
            chatContext.addAssistant(proactive);
        }

        EditText input = new EditText(this);
        input.setHint("和 Nomi 说点什么");
        input.setSingleLine(false);
        input.setMinLines(1);
        input.setMaxLines(3);
        input.setPadding(dp(12), 0, dp(12), 0);
        input.setBackground(rounded(Color.rgb(248, 250, 252), Color.rgb(203, 213, 225), 12));
        input.setOnFocusChangeListener((view, hasFocus) -> {
            panelInputFocused = hasFocus;
            if (panelView != null) panelView.postDelayed(this::adjustPanelForKeyboard, hasFocus ? 250 : 0);
        });
        input.setOnClickListener(view -> {
            panelInputFocused = true;
            if (panelView != null) panelView.postDelayed(this::adjustPanelForKeyboard, 250);
        });
        LinearLayout composer = new LinearLayout(this);
        composer.setOrientation(LinearLayout.HORIZONTAL);
        composer.setGravity(Gravity.CENTER_VERTICAL);
        composer.addView(input, new LinearLayout.LayoutParams(0, dp(48), 1));

        Button send = new Button(this);
        send.setText("发送");
        stylePrimaryButton(send);
        send.setOnClickListener(view -> {
            String text = input.getText().toString();
            input.setText("");
            sendMessage(text);
        });
        LinearLayout.LayoutParams sendParams = new LinearLayout.LayoutParams(dp(76), dp(48));
        sendParams.setMargins(dp(8), 0, 0, 0);
        composer.addView(send, sendParams);
        LinearLayout.LayoutParams composerParams = new LinearLayout.LayoutParams(-1, -2);
        composerParams.setMargins(0, dp(8), 0, 0);
        chatContentView.addView(composer, composerParams);

        responseView = new TextView(this);
        responseView.setText("");
        responseView.setTextColor(Color.rgb(71, 85, 105));
        chatContentView.addView(responseView);
        panelView.addView(chatContentView, new LinearLayout.LayoutParams(-1, 0, 1));

        settingsContentView = new LinearLayout(this);
        settingsContentView.setOrientation(LinearLayout.VERTICAL);
        settingsContentView.setVisibility(View.GONE);
        panelView.addView(settingsContentView, new LinearLayout.LayoutParams(-1, 0, 1));
        buildSettingsView();

        panelDefaultY = dp(220);
        panelDefaultHeight = dp(440);
        panelParams = overlayParams(dp(340), panelDefaultHeight, true);
        panelParams.gravity = Gravity.TOP | Gravity.START;
        panelParams.x = dp(24);
        panelParams.y = panelDefaultY;
        panelParams.softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING;
        windowManager.addView(panelView, panelParams);
        attachPanelKeyboardListener();
    }

    private void sendMessage(String text) {
        if (text == null || text.trim().isEmpty()) return;
        String trimmed = text.trim();
        List<FloatingChatContext.Turn> clientContext = chatContext.snapshotDelta(12000);
        addChatMessage("你", trimmed);
        chatContext.addUser(trimmed);
        TextView pending = addChatMessage("Nomi", "正在思考...");
        responseView.setText("");
        String conversationId = activeConversationId;
        executor.execute(() -> {
            try {
                ChatResult result = api().chat(trimmed, conversationId, clientContext);
                runOnMain(() -> {
                    if (!result.conversationId.trim().isEmpty()) {
                        activeConversationId = result.conversationId.trim();
                    }
                    String answer = result.answer.isEmpty() ? "已发送，但没有返回内容。" : result.answer;
                    pending.setText(messageText("Nomi", answer));
                    chatContext.addAssistant(answer);
                });
            } catch (Exception error) {
                runOnMain(() -> pending.setText(messageText("Nomi", "发送失败：" + error.getMessage())));
            }
        });
    }

    private void closePanel() {
        detachPanelKeyboardListener();
        removeView(panelView);
        panelView = null;
        panelParams = null;
        panelInputFocused = false;
        accountsView = null;
        accountsScrollView = null;
        chatContentView = null;
        settingsContentView = null;
        chatHistoryView = null;
        chatScrollView = null;
    }

    private void attachPanelKeyboardListener() {
        if (panelView == null) return;
        panelLayoutListener = this::adjustPanelForKeyboard;
        panelView.getViewTreeObserver().addOnGlobalLayoutListener(panelLayoutListener);
        panelView.setOnApplyWindowInsetsListener((view, insets) -> {
            adjustPanelForKeyboard();
            return insets;
        });
        panelView.post(this::adjustPanelForKeyboard);
    }

    private void detachPanelKeyboardListener() {
        if (panelView == null || panelLayoutListener == null) return;
        ViewTreeObserver observer = panelView.getViewTreeObserver();
        if (observer.isAlive()) {
            observer.removeOnGlobalLayoutListener(panelLayoutListener);
        }
        panelLayoutListener = null;
        panelView.setOnApplyWindowInsetsListener(null);
    }

    private void adjustPanelForKeyboard() {
        if (panelView == null || panelParams == null) return;

        int screenHeight = getResources().getDisplayMetrics().heightPixels;
        int visibleBottom = visibleDisplayBottom(screenHeight);
        visibleBottom = FloatingPanelLayout.visibleBottomForInputFocus(
                screenHeight,
                visibleBottom,
                panelInputFocused,
                dp(560),
                dp(120)
        );
        FloatingPanelLayout.Frame frame = FloatingPanelLayout.compute(
                panelDefaultY,
                panelDefaultHeight,
                visibleBottom,
                screenHeight,
                dp(24),
                dp(12),
                dp(260),
                dp(120)
        );
        if (panelParams.y != frame.y || panelParams.height != frame.height) {
            panelParams.y = frame.y;
            panelParams.height = frame.height;
            windowManager.updateViewLayout(panelView, panelParams);
        }
    }

    private int visibleDisplayBottom(int screenHeight) {
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsets insets = panelView.getRootWindowInsets();
            if (insets != null && insets.isVisible(WindowInsets.Type.ime())) {
                Insets imeInsets = insets.getInsets(WindowInsets.Type.ime());
                if (imeInsets.bottom > dp(80)) {
                    return screenHeight - imeInsets.bottom;
                }
            }
        }
        Rect visibleFrame = new Rect();
        panelView.getWindowVisibleDisplayFrame(visibleFrame);
        return visibleFrame.bottom > 0 ? visibleFrame.bottom : screenHeight;
    }

    private void startRealtime() {
        try {
            realtimeClient = new RealtimeClient(ConfigPrefs.read(this), new RealtimeClient.Callback() {
                @Override
                public void onProactiveMessage(ProactiveMessage message) {
                    runOnMain(() -> showProactiveBubble(message));
                }

                @Override
                public void onError(String message) {
                    if (responseView != null) runOnMain(() -> responseView.setText("实时通道异常：" + message));
                }
            });
            realtimeClient.start();
        } catch (IllegalArgumentException error) {
            startSuggestionPolling();
        }
    }

    private void showProactiveBubble(ProactiveMessage message) {
        lastProactiveMessage = message;
        unreadCount += 1;
        updateBallBadge();
        removeBubble();

        bubbleView = new TextView(this);
        bubbleView.setText(bubbleText(message));
        bubbleView.setTextSize(13);
        bubbleView.setTextColor(Color.rgb(15, 23, 42));
        bubbleView.setPadding(dp(12), dp(8), dp(12), dp(8));
        bubbleView.setMaxLines(3);
        bubbleView.setBackground(rounded(Color.WHITE, Color.rgb(183, 215, 209), 16));
        bubbleView.setElevation(dp(8));
        bubbleView.setOnClickListener(view -> openWorkbenchChat(message));

        bubbleParams = overlayParams(dp(230), dp(76), false);
        bubbleParams.gravity = Gravity.TOP | Gravity.START;
        positionBubble();
        windowManager.addView(bubbleView, bubbleParams);
    }

    private String bubbleText(ProactiveMessage message) {
        String title = message.title == null ? "" : message.title.trim();
        String body = message.body == null ? "" : message.body.trim();
        String text = title.isEmpty() ? body : title + "\n" + body;
        return text.length() > 72 ? text.substring(0, 72) + "..." : text;
    }

    private void openWorkbenchChat(ProactiveMessage message) {
        removeBubble();
        unreadCount = 0;
        updateBallBadge();
        Intent intent = new Intent(this, WebWorkspaceActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        intent.putExtra(WebWorkspaceActivity.EXTRA_URL, ConfigPrefs.baseUrlOrDefault(this) + "#chat");
        intent.putExtra(WebWorkspaceActivity.EXTRA_PROACTIVE_TITLE, message.title);
        intent.putExtra(WebWorkspaceActivity.EXTRA_PROACTIVE_BODY, message.body);
        startActivity(intent);
        closePanel();
    }

    private void removeBubble() {
        removeView(bubbleView);
        bubbleView = null;
        bubbleParams = null;
    }

    private void positionBubble() {
        if (bubbleParams == null || ballParams == null) return;
        int screenWidth = getResources().getDisplayMetrics().widthPixels;
        int x = ballParams.x + dp(76);
        if (x + dp(230) > screenWidth) x = Math.max(0, ballParams.x - dp(234));
        bubbleParams.x = x;
        bubbleParams.y = Math.max(0, ballParams.y + dp(4));
    }

    private void buildSettingsView() {
        if (settingsContentView == null) return;
        settingsContentView.removeAllViews();

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);

        Button back = new Button(this);
        back.setText("返回对话");
        styleSecondaryButton(back);
        back.setOnClickListener(view -> showChatView());
        row.addView(back, new LinearLayout.LayoutParams(0, dp(46), 1));

        Button accounts = new Button(this);
        accounts.setText("登录账号");
        stylePrimaryButton(accounts);
        accounts.setOnClickListener(view -> toggleAccounts());
        LinearLayout.LayoutParams accountsParams = new LinearLayout.LayoutParams(0, dp(46), 1);
        accountsParams.setMargins(dp(8), 0, 0, 0);
        row.addView(accounts, accountsParams);
        settingsContentView.addView(row);

        TextView note = new TextView(this);
        note.setText("账号登录会打开服务器上的远程浏览器。");
        note.setTextSize(12);
        note.setTextColor(Color.rgb(100, 116, 139));
        LinearLayout.LayoutParams noteParams = new LinearLayout.LayoutParams(-1, -2);
        noteParams.setMargins(0, dp(8), 0, dp(8));
        settingsContentView.addView(note, noteParams);

        accountsView = new LinearLayout(this);
        accountsView.setOrientation(LinearLayout.VERTICAL);
        accountsView.setPadding(0, dp(6), 0, dp(6));
        accountsScrollView = new ScrollView(this);
        accountsScrollView.setVisibility(View.GONE);
        accountsScrollView.addView(accountsView);
        settingsContentView.addView(accountsScrollView, new LinearLayout.LayoutParams(-1, 0, 1));
    }

    private void showChatView() {
        if (chatContentView != null) chatContentView.setVisibility(View.VISIBLE);
        if (settingsContentView != null) settingsContentView.setVisibility(View.GONE);
    }

    private void showSettingsView() {
        if (chatContentView != null) chatContentView.setVisibility(View.GONE);
        if (settingsContentView != null) settingsContentView.setVisibility(View.VISIBLE);
        if (accountsScrollView != null) accountsScrollView.setVisibility(View.GONE);
    }

    private void openWorkbench() {
        Intent intent = new Intent(this, WebWorkspaceActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        intent.putExtra(WebWorkspaceActivity.EXTRA_URL, ConfigPrefs.baseUrlOrDefault(this) + "#chat");
        startActivity(intent);
        closePanel();
    }

    private TextView addChatMessage(String speaker, String body) {
        TextView message = new TextView(this);
        message.setText(messageText(speaker, body));
        message.setTextSize(13);
        message.setTextColor(Color.rgb(15, 23, 42));
        message.setPadding(dp(10), dp(8), dp(10), dp(8));
        int fill = "你".equals(speaker) ? Color.rgb(204, 251, 241) : Color.rgb(248, 250, 252);
        message.setBackground(rounded(fill, Color.rgb(226, 232, 240), 12));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.setMargins(0, 0, 0, dp(8));
        if (chatHistoryView != null) {
            chatHistoryView.addView(message, params);
            if (chatScrollView != null) {
                chatScrollView.post(() -> chatScrollView.fullScroll(View.FOCUS_DOWN));
            }
        }
        return message;
    }

    private String messageText(String speaker, String body) {
        String label = speaker == null || speaker.trim().isEmpty() ? "Nomi" : speaker.trim();
        String content = body == null ? "" : body.trim();
        return label + "\n" + content;
    }

    private void toggleAccounts() {
        if (accountsView == null || accountsScrollView == null) return;
        if (accountsScrollView.getVisibility() == View.VISIBLE) {
            accountsScrollView.setVisibility(View.GONE);
            return;
        }
        renderAccountChannels(null);
        accountsScrollView.setVisibility(View.VISIBLE);
        executor.execute(() -> {
            try {
                Map<String, CollectorStatus> statuses = api().collectorStatuses();
                runOnMain(() -> renderAccountChannels(statuses));
            } catch (Exception error) {
                runOnMain(() -> {
                    renderAccountChannels(null);
                    if (responseView != null) {
                        responseView.setText("账号状态读取失败，仍可打开服务器浏览器登录：" + error.getMessage());
                    }
                });
            }
        });
    }

    private void renderAccountChannels(Map<String, CollectorStatus> statuses) {
        if (accountsView == null) return;
        accountsView.removeAllViews();

        TextView heading = new TextView(this);
        heading.setText("支持的登录渠道");
        heading.setTextSize(15);
        heading.setTextColor(Color.rgb(15, 23, 42));
        accountsView.addView(heading);

        TextView note = new TextView(this);
        note.setText("点击需要登录的渠道，会打开服务器上的远程浏览器。账号密码和扫码仍由你自己完成。");
        note.setTextSize(12);
        note.setTextColor(Color.rgb(100, 116, 139));
        accountsView.addView(note);

        for (AccountChannel channel : ACCOUNT_CHANNELS) {
            accountsView.addView(accountRow(channel, statuses == null ? null : statuses.get(channel.source)));
        }
    }

    private View accountRow(AccountChannel channel, CollectorStatus status) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(8), dp(8), dp(8), dp(8));
        row.setBackground(rounded(Color.rgb(248, 250, 252), Color.rgb(226, 232, 240), 12));

        TextView icon = new TextView(this);
        icon.setText(channel.name.substring(0, 1));
        icon.setTextSize(14);
        icon.setGravity(Gravity.CENTER);
        icon.setTextColor(Color.rgb(15, 118, 110));
        icon.setBackground(rounded(Color.rgb(204, 251, 241), 0, 10));
        row.addView(icon, new LinearLayout.LayoutParams(dp(34), dp(34)));

        LinearLayout text = new LinearLayout(this);
        text.setOrientation(LinearLayout.VERTICAL);
        text.setPadding(dp(8), 0, dp(8), 0);
        TextView title = new TextView(this);
        title.setText(channel.name);
        title.setTextSize(14);
        title.setTextColor(Color.rgb(15, 23, 42));
        TextView body = new TextView(this);
        body.setText(channel.description);
        body.setTextSize(11);
        body.setTextColor(Color.rgb(100, 116, 139));
        text.addView(title);
        text.addView(body);
        row.addView(text, new LinearLayout.LayoutParams(0, -2, 1));

        TextView badge = new TextView(this);
        badge.setText(statusText(channel, status));
        badge.setTextSize(11);
        badge.setGravity(Gravity.CENTER);
        badge.setTextColor(statusColor(status));
        badge.setBackground(rounded(statusFill(status), 0, 99));
        row.addView(badge, new LinearLayout.LayoutParams(dp(58), dp(30)));

        LinearLayout.LayoutParams margins = new LinearLayout.LayoutParams(-1, -2);
        margins.setMargins(0, dp(6), 0, 0);
        row.setLayoutParams(margins);
        if (channel.opensBrowser) {
            row.setOnClickListener(view -> openRemoteBrowser());
        }
        return row;
    }

    private String statusText(AccountChannel channel, CollectorStatus status) {
        if ("shopping".equals(channel.source)) return "间接";
        if (!channel.opensBrowser) {
            if (status == null) return "本地";
            if (!status.enabled) return "已停用";
            if (status.paused) return "暂停";
            if ("failed".equals(status.healthStatus)) return "异常";
            return "本地";
        }
        if (status == null) return channel.opensBrowser ? "可登录" : "本地";
        if (!status.enabled) return "已停用";
        if (status.paused) return "暂停";
        if ("healthy".equals(status.healthStatus)) return "正常";
        if ("degraded".equals(status.healthStatus)) return "待登录";
        if ("failed".equals(status.healthStatus)) return "异常";
        return channel.opensBrowser ? "可登录" : "本地";
    }

    private int statusColor(CollectorStatus status) {
        if (status == null) return Color.rgb(51, 65, 85);
        if ("healthy".equals(status.healthStatus)) return Color.rgb(22, 101, 52);
        if ("failed".equals(status.healthStatus)) return Color.rgb(153, 27, 27);
        return Color.rgb(146, 64, 14);
    }

    private int statusFill(CollectorStatus status) {
        if (status == null) return Color.rgb(226, 232, 240);
        if ("healthy".equals(status.healthStatus)) return Color.rgb(220, 252, 231);
        if ("failed".equals(status.healthStatus)) return Color.rgb(254, 226, 226);
        return Color.rgb(254, 243, 199);
    }

    private void openRemoteBrowser() {
        Intent intent = new Intent(this, WebWorkspaceActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        intent.putExtra(WebWorkspaceActivity.EXTRA_URL, ConfigPrefs.remoteBrowserUrl(this));
        startActivity(intent);
        closePanel();
    }

    private void startSuggestionPolling() {
        try {
            poller = new SuggestionPoller(api(), new SuggestionDeduper(), new SuggestionPoller.Callback() {
                @Override
                public void onNewSuggestions(List<AssistantSuggestion> suggestions) {
                    unreadCount += suggestions.size();
                    updateBallBadge();
                    showSuggestionNotification(suggestions.get(0));
                    if (suggestionsView != null) {
                        for (AssistantSuggestion suggestion : suggestions) {
                            addSuggestionCard(suggestion);
                        }
                    }
                }

                @Override
                public void onError(Exception error) {
                    if (responseView != null) responseView.setText("主动消息同步失败：" + error.getMessage());
                }
            }, 60000);
            poller.start();
        } catch (IllegalArgumentException ignored) {
            updateBallBadge();
        }
    }

    private void addSuggestionCard(AssistantSuggestion suggestion) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(0, dp(6), 0, dp(6));
        TextView title = new TextView(this);
        title.setText(suggestion.title());
        title.setTextSize(15);
        TextView body = new TextView(this);
        body.setText(suggestion.body());
        LinearLayout actions = new LinearLayout(this);
        Button done = new Button(this);
        done.setText("完成");
        done.setOnClickListener(view -> updateSuggestion(suggestion, "done", card));
        Button dismiss = new Button(this);
        dismiss.setText("忽略");
        dismiss.setOnClickListener(view -> updateSuggestion(suggestion, "dismissed", card));
        actions.addView(done);
        actions.addView(dismiss);
        card.addView(title);
        card.addView(body);
        card.addView(actions);
        suggestionsView.addView(card, 0);
    }

    private void updateSuggestion(AssistantSuggestion suggestion, String status, View card) {
        executor.execute(() -> {
            try {
                api().updateSuggestion(suggestion.id(), status);
                runOnMain(() -> suggestionsView.removeView(card));
            } catch (Exception error) {
                runOnMain(() -> responseView.setText("更新建议失败：" + error.getMessage()));
            }
        });
    }

    private AssistantApiClient api() {
        ServerConfig config = ConfigPrefs.read(this);
        return new AssistantApiClient(config);
    }

    private void updateBallBadge() {
        if (ballView != null) ballView.setUnreadCount(unreadCount);
    }

    private void showSuggestionNotification(AssistantSuggestion suggestion) {
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.notify(NOTIFICATION_ID + 1, notification(suggestion.title(), suggestion.body()));
    }

    private Notification notification(String title, String body) {
        createChannel();
        Intent intent = new Intent(this, WebWorkspaceActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        PendingIntent pendingIntent = PendingIntent.getActivity(
                this,
                0,
                intent,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT
        );
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL_ID)
                : new Notification.Builder(this);
        return builder
                .setContentTitle(title)
                .setContentText(body)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentIntent(pendingIntent)
                .setOngoing(false)
                .build();
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager manager = getSystemService(NotificationManager.class);
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "Nomi Floating Assistant",
                NotificationManager.IMPORTANCE_DEFAULT
        );
        manager.createNotificationChannel(channel);
    }

    private WindowManager.LayoutParams overlayParams(int width, int height, boolean focusable) {
        int flags = focusable ? 0 : WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE;
        return new WindowManager.LayoutParams(
                width,
                height,
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                flags,
                PixelFormat.TRANSLUCENT
        );
    }

    private void removeView(View view) {
        if (view != null) {
            try {
                windowManager.removeView(view);
            } catch (IllegalArgumentException ignored) {
            }
        }
    }

    private void runOnMain(Runnable runnable) {
        ballView.post(runnable);
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

    private ImageButton iconButton(int iconRes, String description) {
        ImageButton button = new ImageButton(this);
        button.setImageResource(iconRes);
        button.setContentDescription(description);
        button.setBackground(rounded(Color.rgb(241, 245, 249), 0, 14));
        button.setColorFilter(Color.rgb(15, 23, 42));
        button.setPadding(dp(10), dp(10), dp(10), dp(10));
        return button;
    }

    private Button closeButton() {
        Button close = new Button(this);
        close.setText("×");
        close.setTextSize(18);
        close.setTextColor(Color.rgb(15, 23, 42));
        close.setBackground(rounded(Color.rgb(226, 232, 240), 0, 14));
        close.setAllCaps(false);
        return close;
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

    private final class DragController implements View.OnTouchListener {
        private final WindowManager.LayoutParams params;
        private final Runnable clickAction;
        private int startX;
        private int startY;
        private float touchStartX;
        private float touchStartY;
        private boolean moved;

        DragController(WindowManager.LayoutParams params, Runnable clickAction) {
            this.params = params;
            this.clickAction = clickAction;
        }

        @Override
        public boolean onTouch(View view, MotionEvent event) {
            if (event.getAction() == MotionEvent.ACTION_DOWN) {
                startX = params.x;
                startY = params.y;
                touchStartX = event.getRawX();
                touchStartY = event.getRawY();
                moved = false;
                return true;
            }
            if (event.getAction() == MotionEvent.ACTION_MOVE) {
                int dx = Math.round(event.getRawX() - touchStartX);
                int dy = Math.round(event.getRawY() - touchStartY);
                moved = moved || Math.abs(dx) > dp(6) || Math.abs(dy) > dp(6);
                params.x = startX + dx;
                params.y = startY + dy;
                windowManager.updateViewLayout(view, params);
                positionBubble();
                if (bubbleView != null && bubbleParams != null) windowManager.updateViewLayout(bubbleView, bubbleParams);
                return true;
            }
            if (event.getAction() == MotionEvent.ACTION_UP) {
                if (!moved) {
                    clickAction.run();
                } else {
                    int screenWidth = getResources().getDisplayMetrics().widthPixels;
                    params.x = params.x + view.getWidth() / 2 > screenWidth / 2 ? screenWidth - view.getWidth() : 0;
                    windowManager.updateViewLayout(view, params);
                    positionBubble();
                    if (bubbleView != null && bubbleParams != null) windowManager.updateViewLayout(bubbleView, bubbleParams);
                }
                return true;
            }
            return false;
        }
    }

    private static final class AccountChannel {
        final String source;
        final String name;
        final String description;
        final boolean opensBrowser;

        AccountChannel(String source, String name, String description, boolean opensBrowser) {
            this.source = source;
            this.name = name;
            this.description = description;
            this.opensBrowser = opensBrowser;
        }
    }
}
