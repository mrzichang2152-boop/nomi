package com.par.assistant.android;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.graphics.Color;
import android.graphics.Insets;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.IBinder;
import android.os.SystemClock;
import android.text.Layout;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.view.ViewTreeObserver;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.view.inputmethod.InputMethodManager;
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
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class FloatingBallService extends Service {
    static final String ACTION_SHOW_ACCOUNTS = "com.par.assistant.android.SHOW_ACCOUNTS";
    static final String ACTION_SHOW_EXTERNAL_AUTH_CLOSE = "com.par.assistant.android.SHOW_EXTERNAL_AUTH_CLOSE";
    static final String EXTRA_AUTH_MESSAGE = "com.par.assistant.android.AUTH_MESSAGE";
    private static final String CHANNEL_ID = "par-floating-ball";
    private static final int NOTIFICATION_ID = 1001;
    private static final long STREAMING_CHAT_FALLBACK_TIMEOUT_MS =
            StreamingChatFallbackPolicy.FIRST_DELTA_FALLBACK_TIMEOUT_MS;

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private WindowManager windowManager;
    private NomiAvatarView ballView;
    private TextView bubbleView;
    private Button externalAuthCloseView;
    private WindowManager.LayoutParams ballParams;
    private WindowManager.LayoutParams bubbleParams;
    private WindowManager.LayoutParams externalAuthCloseParams;
    private WindowManager.LayoutParams panelParams;
    private LinearLayout panelView;
    private TextView responseView;
    private LinearLayout suggestionsView;
    private LinearLayout accountsView;
    private ScrollView accountsScrollView;
    private LinearLayout chatContentView;
    private LinearLayout agendaContentView;
    private LinearLayout agendaListView;
    private ScrollView agendaScrollView;
    private TextView agendaStatusView;
    private LinearLayout careerContentView;
    private LinearLayout careerListView;
    private ScrollView careerScrollView;
    private TextView careerStatusView;
    private LinearLayout settingsContentView;
    private TextView settingsStatusView;
    private LinearLayout chatHistoryView;
    private ScrollView chatScrollView;
    private int unreadCount;
    private SuggestionPoller poller;
    private RealtimeClient realtimeClient;
    private StreamingAsrClient streamingAsrClient;
    private StreamingVoiceRecorder voiceRecorder;
    private ProactiveMessage lastProactiveMessage;
    private final FloatingChatContext chatContext = new FloatingChatContext();
    private final StringBuilder streamingAnswerBuffer = new StringBuilder();
    private String activeConversationId;
    private TextView streamingPendingView;
    private String streamingRequestMessage;
    private String streamingRequestConversationId;
    private List<FloatingChatContext.Turn> streamingRequestContext;
    private String streamingRequestClientRequestId;
    private long streamingRequestStartedAtMs;
    private String activeVoiceSessionId;
    private int activeVoiceLastSeq;
    private boolean activeVoiceReady;
    private boolean activeVoiceFinishedByUser;
    private TextView voicePanelMessageView;
    private ViewTreeObserver.OnGlobalLayoutListener panelLayoutListener;
    private int panelDefaultY;
    private int panelDefaultHeight;
    private boolean panelInputFocused;
    private static final AccountChannel[] ACCOUNT_CHANNELS = new AccountChannel[] {
            new AccountChannel("gmail", "Gmail", "邮件、订单、验证码提醒、邮件正文快照", true),
            new AccountChannel("whatsapp", "WhatsApp Web", "聊天预览、打开会话历史、新消息监听", true),
            new AccountChannel("telegram", "Telegram Web", "聊天列表和可见消息预览", true),
            new AccountChannel("calendar", "Google Calendar", "日程、会议、提醒", true),
            new AccountChannel("linkedin", "LinkedIn", "个人主页、岗位 JD、招聘联系人和私信草稿", true),
            new AccountChannel("search", "Google Search", "搜索记录和浏览器页面信号", true),
            new AccountChannel("bookmark", "Chrome Bookmarks", "服务器浏览器书签", false),
            new AccountChannel("focus", "浏览行为", "点击、滚动、输入等本地浏览焦点信号", false),
            new AccountChannel("shopping", "购物/电商", "通过 Gmail 订单邮件和浏览器页面间接支持", true)
    };

    @Override
    public void onCreate() {
        super.onCreate();
        activeConversationId = ConfigPrefs.conversationId(this);
        windowManager = (WindowManager) getSystemService(WINDOW_SERVICE);
        startNomiForeground(false);
        showBall();
        startRealtime();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (windowManager != null && ballView == null) {
            showBall();
        }
        if (intent != null && ACTION_SHOW_ACCOUNTS.equals(intent.getAction())) {
            showAccountsAfterExternalAuth(intent.getStringExtra(EXTRA_AUTH_MESSAGE));
        }
        if (intent != null && ACTION_SHOW_EXTERNAL_AUTH_CLOSE.equals(intent.getAction())) {
            if (ballView == null) showBall();
            showExternalAuthCloseButton();
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        if (poller != null) poller.stop();
        if (realtimeClient != null) realtimeClient.stop();
        stopVoiceSession(true);
        removeView(ballView);
        removeView(bubbleView);
        removeView(externalAuthCloseView);
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

        float touchSlop = ViewConfiguration.get(this).getScaledTouchSlop();
        ballView.setOnTouchListener(new VoicePressController(450, touchSlop, dp(96), new VoicePressController.DecisionCallback() {
            @Override
            public void onTap() {
                togglePanel();
            }

            @Override
            public void onDragMove(int x, int y) {
                moveBallToRawPosition(x, y);
            }

            @Override
            public void onDragEnd(int x, int y) {
                moveBallToRawPosition(x, y);
                snapBallToEdge();
            }

            @Override
            public void onVoiceStart() {
                startVoiceInput();
            }

            @Override
            public void onVoiceCancelArmed(boolean armed) {
                showVoiceBubble(armed ? "松手取消" : "正在听...");
            }

            @Override
            public void onVoiceEnd() {
                finishVoiceInput();
            }

            @Override
            public void onVoiceCancelled() {
                cancelVoiceInput("user_swiped_cancel");
            }
        }));
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
        activeConversationId = ConfigPrefs.conversationId(this);

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

        ImageButton agenda = iconButton(android.R.drawable.ic_menu_my_calendar, "日程");
        agenda.setOnClickListener(view -> showAgendaView());
        header.addView(agenda, new LinearLayout.LayoutParams(dp(42), dp(42)));

        ImageButton app = iconButton(android.R.drawable.ic_menu_view, "进入完整 App");
        app.setOnClickListener(view -> openAppChat());
        header.addView(app, new LinearLayout.LayoutParams(dp(42), dp(42)));

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

        addChatMessage("Nomi", "我在这里。你可以直接发消息，也可以点右上角查看日程或进入完整 App。");

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
            showKeyboard(input);
            if (panelView != null) panelView.postDelayed(this::adjustPanelForKeyboard, 250);
        });
        chatScrollView.setClickable(true);
        chatScrollView.setOnClickListener(view -> hideKeyboard(input));
        chatHistoryView.setClickable(true);
        chatHistoryView.setOnClickListener(view -> hideKeyboard(input));
        LinearLayout composer = new LinearLayout(this);
        composer.setOrientation(LinearLayout.HORIZONTAL);
        composer.setGravity(Gravity.CENTER_VERTICAL);
        composer.addView(input, new LinearLayout.LayoutParams(0, dp(48), 1));

        Button send = new Button(this);
        send.setText("发送");
        send.setFocusable(false);
        send.setFocusableInTouchMode(false);
        stylePrimaryButton(send);
        send.setOnClickListener(view -> {
            String text = input.getText().toString();
            input.setText("");
            input.requestFocus();
            showKeyboard(input);
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

        agendaContentView = buildAgendaContentView();
        agendaContentView.setVisibility(View.GONE);
        panelView.addView(agendaContentView, new LinearLayout.LayoutParams(-1, 0, 1));

        careerContentView = buildCareerContentView();
        careerContentView.setVisibility(View.GONE);
        panelView.addView(careerContentView, new LinearLayout.LayoutParams(-1, 0, 1));

        panelDefaultY = dp(220);
        panelDefaultHeight = dp(440);
        panelParams = overlayParams(dp(340), panelDefaultHeight, true);
        panelParams.gravity = Gravity.TOP | Gravity.START;
        panelParams.x = dp(24);
        panelParams.y = panelDefaultY;
        panelParams.softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING;
        windowManager.addView(panelView, panelParams);
        attachPanelKeyboardListener();
        loadRemoteChatHistory();
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
        String clientRequestId = "android-" + UUID.randomUUID();
        if (trySendStreamingChat(trimmed, conversationId, clientContext, pending, clientRequestId)) {
            return;
        }
        sendHttpChat(trimmed, conversationId, clientContext, pending, clientRequestId);
    }

    private void sendHttpChat(String trimmed, String conversationId, List<FloatingChatContext.Turn> clientContext, TextView pending) {
        sendHttpChat(trimmed, conversationId, clientContext, pending, "");
    }

    private void sendHttpChat(
            String trimmed,
            String conversationId,
            List<FloatingChatContext.Turn> clientContext,
            TextView pending,
            String clientRequestId
    ) {
        executor.execute(() -> {
            try {
                ChatResult result = api().chat(trimmed, conversationId, clientContext, clientRequestId);
                runOnMain(() -> {
                    if (!result.conversationId.trim().isEmpty()) {
                        rememberActiveConversationId(result.conversationId);
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

    private boolean trySendStreamingChat(
            String message,
            String conversationId,
            List<FloatingChatContext.Turn> clientContext,
            TextView pending,
            String clientRequestId
    ) {
        if (realtimeClient == null || streamingPendingView != null) {
            return false;
        }
        streamingPendingView = pending;
        streamingRequestMessage = message;
        streamingRequestConversationId = conversationId;
        streamingRequestContext = clientContext;
        streamingRequestClientRequestId = clientRequestId;
        streamingRequestStartedAtMs = SystemClock.elapsedRealtime();
        streamingAnswerBuffer.setLength(0);
        try {
            boolean sent = realtimeClient.sendChatMessage(message, conversationId, 12, "android", clientRequestId);
            if (!sent) {
                clearStreamingChatState();
            }
            if (sent) {
                pending.postDelayed(() -> {
                    if (!StreamingChatFallbackPolicy.shouldRunHttpFallback(
                            streamingPendingView == pending,
                            streamingAnswerBuffer.length(),
                            SystemClock.elapsedRealtime() - streamingRequestStartedAtMs
                    )) {
                        return;
                    }
                    fallbackStreamingChatAfterRealtimeIssue("实时通道没有返回，正在切换普通请求...");
                }, STREAMING_CHAT_FALLBACK_TIMEOUT_MS);
            }
            return sent;
        } catch (Exception error) {
            clearStreamingChatState();
            return false;
        }
    }

    private void applyStreamingChatDelta(String delta) {
        if (streamingPendingView == null) return;
        if (delta != null) {
            streamingAnswerBuffer.append(delta);
        }
        String answer = streamingAnswerBuffer.toString().trim();
        streamingPendingView.setText(messageText("Nomi", answer.isEmpty() ? "正在思考..." : answer));
    }

    private void completeStreamingChat(String answer, String conversationId) {
        if (streamingPendingView == null) return;
        if (conversationId != null && !conversationId.trim().isEmpty()) {
            rememberActiveConversationId(conversationId);
        }
        String finalAnswer = answer == null || answer.trim().isEmpty()
                ? streamingAnswerBuffer.toString().trim()
                : answer.trim();
        if (finalAnswer.isEmpty()) {
            finalAnswer = "已发送，但没有返回内容。";
        }
        streamingPendingView.setText(messageText("Nomi", finalAnswer));
        chatContext.addAssistant(finalAnswer);
        clearStreamingChatState();
    }

    private void failStreamingChat(String message) {
        if (streamingPendingView == null) return;
        String reason = message == null || message.trim().isEmpty() ? "实时通道异常" : message.trim();
        streamingPendingView.setText(messageText("Nomi", "发送失败：" + reason));
        clearStreamingChatState();
    }

    private void fallbackStreamingChatAfterRealtimeIssue(String statusMessage) {
        TextView pending = streamingPendingView;
        String message = streamingRequestMessage;
        String conversationId = streamingRequestConversationId;
        List<FloatingChatContext.Turn> clientContext = streamingRequestContext;
        String clientRequestId = streamingRequestClientRequestId;
        if (pending == null || message == null || message.trim().isEmpty()) {
            clearStreamingChatState();
            return;
        }
        clearStreamingChatState();
        pending.setText(messageText("Nomi", statusMessage));
        sendHttpChat(
                message,
                conversationId,
                clientContext == null ? List.of() : clientContext,
                pending,
                clientRequestId == null ? "" : clientRequestId
        );
    }

    private void clearStreamingChatState() {
        streamingPendingView = null;
        streamingRequestMessage = null;
        streamingRequestConversationId = null;
        streamingRequestContext = null;
        streamingRequestClientRequestId = null;
        streamingRequestStartedAtMs = 0L;
        streamingAnswerBuffer.setLength(0);
    }

    private void startVoiceInput() {
        if (!hasMicrophonePermission()) {
            showVoiceBubble("请允许麦克风权限。");
            startActivity(MicrophonePermissionActivity.intent(this, "voice_long_press"));
            return;
        }
        stopVoiceSession(false);
        activeVoiceSessionId = UUID.randomUUID().toString();
        activeVoiceLastSeq = 0;
        activeVoiceReady = false;
        activeVoiceFinishedByUser = false;
        voicePanelMessageView = null;
        showVoiceBubble("正在连接语音识别...");
        if (panelView != null) {
            voicePanelMessageView = addChatMessage("Nomi", "按住说话，我正在连接语音识别...");
        }
        try {
            streamingAsrClient = new StreamingAsrClient(ConfigPrefs.read(this), new StreamingAsrClient.Callback() {
                @Override
                public void onReady(String sessionId, String provider, int maxDurationMs) {
                    runOnMain(() -> {
                        activeVoiceReady = true;
                        showVoiceBubble("正在听...");
                        updateVoicePanelMessage("正在听...");
                        startVoiceRecorder();
                        if (activeVoiceFinishedByUser) {
                            finishVoiceInput();
                        }
                    });
                }

                @Override
                public void onPartial(String text, double confidence, boolean stable) {
                    runOnMain(() -> {
                        String partial = text == null || text.trim().isEmpty() ? "正在听..." : text.trim();
                        showVoiceBubble(partial);
                        updateVoicePanelMessage("识别中\n" + partial);
                    });
                }

                @Override
                public void onFinal(String text, double confidence, String transcriptId) {
                    runOnMain(() -> handleVoiceFinal(text, confidence));
                }

                @Override
                public void onError(String code, String message) {
                    runOnMain(() -> failVoiceInput(message));
                }

                @Override
                public void onClosed() {
                    runOnMain(() -> {
                        if (activeVoiceSessionId != null) {
                            failVoiceInput("语音识别连接已断开。");
                        }
                    });
                }
            });
            streamingAsrClient.start(activeVoiceSessionId, activeConversationId, "zh-CN");
        } catch (Exception error) {
            failVoiceInput("语音识别启动失败：" + error.getMessage());
        }
    }

    private void startVoiceRecorder() {
        if (voiceRecorder != null && voiceRecorder.isRecording()) return;
        startNomiForeground(true);
        voiceRecorder = new StreamingVoiceRecorder();
        boolean started = voiceRecorder.start(new StreamingVoiceRecorder.Callback() {
            @Override
            public void onAudioChunk(byte[] pcm, int seq, long capturedAtMs) {
                StreamingAsrClient client = streamingAsrClient;
                String sessionId = activeVoiceSessionId;
                activeVoiceLastSeq = seq;
                if (client != null && sessionId != null) {
                    client.sendAudioChunk(sessionId, pcm, seq, capturedAtMs);
                }
            }

            @Override
            public void onLevel(float rms) {
            }

            @Override
            public void onRecorderError(String userVisibleMessage, Throwable error) {
                runOnMain(() -> failVoiceInput(userVisibleMessage));
            }
        });
        if (!started) {
            startNomiForeground(false);
            failVoiceInput("录音启动失败。");
        }
    }

    private void finishVoiceInput() {
        if (activeVoiceSessionId == null) return;
        activeVoiceFinishedByUser = true;
        if (voiceRecorder != null) {
            voiceRecorder.stop();
        }
        showVoiceBubble(activeVoiceReady ? "正在识别..." : "正在连接语音识别...");
        updateVoicePanelMessage(activeVoiceReady ? "正在识别..." : "正在连接语音识别...");
        StreamingAsrClient client = streamingAsrClient;
        if (client != null && activeVoiceReady) {
            client.finish(activeVoiceSessionId, activeVoiceLastSeq);
        }
    }

    private void cancelVoiceInput(String reason) {
        if (activeVoiceSessionId == null) {
            showVoiceBubble("已取消语音输入。");
            return;
        }
        if (voiceRecorder != null) voiceRecorder.stop();
        if (streamingAsrClient != null) streamingAsrClient.cancel(activeVoiceSessionId, reason);
        stopVoiceSession(false);
        showVoiceBubble("已取消语音输入。");
        updateVoicePanelMessage("已取消语音输入。");
    }

    private void handleVoiceFinal(String text, double confidence) {
        String transcript = text == null ? "" : text.trim();
        stopVoiceSession(false);
        if (transcript.isEmpty() || confidence < 0.55) {
            showVoiceBubble("没听清，再说一次。");
            updateVoicePanelMessage("没听清，再说一次。");
            return;
        }
        if (confidence < 0.78) {
            showVoiceConfirmBubble(transcript);
            updateVoicePanelMessage("我听到的是：\n" + transcript + "\n如正确，请点击气泡发送。");
            return;
        }
        removeBubble();
        updateVoicePanelMessage("已识别：\n" + transcript);
        sendMessage(transcript);
    }

    private void failVoiceInput(String message) {
        String visible = message == null || message.trim().isEmpty() ? "语音识别失败，请稍后重试。" : message.trim();
        stopVoiceSession(false);
        showVoiceBubble(visible);
        updateVoicePanelMessage(visible);
    }

    private void stopVoiceSession(boolean cancelProvider) {
        if (voiceRecorder != null) {
            voiceRecorder.stop();
            voiceRecorder = null;
        }
        startNomiForeground(false);
        if (streamingAsrClient != null) {
            if (cancelProvider && activeVoiceSessionId != null) {
                streamingAsrClient.cancel(activeVoiceSessionId, "service_stopped");
            } else {
                streamingAsrClient.stop();
            }
            streamingAsrClient = null;
        }
        activeVoiceSessionId = null;
        activeVoiceLastSeq = 0;
        activeVoiceReady = false;
        activeVoiceFinishedByUser = false;
    }

    private void updateVoicePanelMessage(String text) {
        if (voicePanelMessageView != null) {
            voicePanelMessageView.setText(messageText("Nomi", text == null ? "" : text));
        }
    }

    private boolean hasMicrophonePermission() {
        return Build.VERSION.SDK_INT < 23 || checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED;
    }

    private void startNomiForeground(boolean withMicrophone) {
        Notification foregroundNotification = notification(
                withMicrophone ? "Nomi 正在听你说话" : "Nomi 正在陪伴你",
                withMicrophone ? "松开悬浮球后发送语音输入" : "点击打开 Nomi"
        );
        if (Build.VERSION.SDK_INT >= 34) {
            int type = ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE;
            if (withMicrophone) {
                type |= ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE;
            }
            startForeground(NOTIFICATION_ID, foregroundNotification, type);
        } else if (Build.VERSION.SDK_INT >= 29 && withMicrophone) {
            startForeground(NOTIFICATION_ID, foregroundNotification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);
        } else {
            startForeground(NOTIFICATION_ID, foregroundNotification);
        }
    }

    private void loadRemoteChatHistory() {
        int localSizeAtRequest = chatContext.size();
        String conversationId = activeConversationId;
        executor.execute(() -> {
            try {
                ChatHistoryResult history = api().chatHistory(conversationId, 80);
                runOnMain(() -> applyRemoteChatHistory(history, localSizeAtRequest));
            } catch (Exception error) {
                runOnMain(() -> {
                    if (responseView != null) {
                        responseView.setText("历史对话加载失败：" + error.getMessage());
                    }
                });
            }
        });
    }

    private void applyRemoteChatHistory(ChatHistoryResult history, int localSizeAtRequest) {
        if (panelView == null || chatHistoryView == null || history == null || history.messages.isEmpty()) {
            return;
        }
        if (chatContext.size() != localSizeAtRequest) {
            return;
        }
        if (!history.conversationId.trim().isEmpty()) {
            rememberActiveConversationId(history.conversationId);
        }
        chatHistoryView.removeAllViews();
        chatContext.replaceWithHistory(history.messages);
        for (ChatHistoryMessage message : history.messages) {
            addChatMessage(speakerForHistoryRole(message.role), message.content);
        }
        if (responseView != null) {
            responseView.setText("");
        }
    }

    private String speakerForHistoryRole(String role) {
        return "user".equals(role) ? "你" : "Nomi";
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
        agendaContentView = null;
        agendaListView = null;
        agendaScrollView = null;
        agendaStatusView = null;
        careerContentView = null;
        careerListView = null;
        careerScrollView = null;
        careerStatusView = null;
        settingsContentView = null;
        settingsStatusView = null;
        chatHistoryView = null;
        chatScrollView = null;
        voicePanelMessageView = null;
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
                dp(380),
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

    private void showKeyboard(EditText input) {
        input.post(() -> {
            input.requestFocus();
            panelInputFocused = true;
            InputMethodManager imm = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
            if (imm != null) {
                imm.showSoftInput(input, InputMethodManager.SHOW_IMPLICIT);
            }
            adjustPanelForKeyboard();
        });
    }

    private void hideKeyboard(EditText input) {
        panelInputFocused = false;
        input.clearFocus();
        InputMethodManager imm = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (imm != null) {
            imm.hideSoftInputFromWindow(input.getWindowToken(), 0);
        }
        if (panelView != null) panelView.post(this::adjustPanelForKeyboard);
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
                    runOnMain(() -> {
                        if (streamingPendingView != null) {
                            if (StreamingChatFallbackPolicy.shouldFallbackOnRealtimeError(true, streamingAnswerBuffer.length())) {
                                fallbackStreamingChatAfterRealtimeIssue("实时通道异常，正在切换普通请求...");
                            } else {
                                failStreamingChat(message);
                            }
                        } else {
                            ignoreBackgroundRealtimeError(message);
                        }
                    });
                }

                @Override
                public void onChatDelta(String delta) {
                    runOnMain(() -> applyStreamingChatDelta(delta));
                }

                @Override
                public void onChatDone(String answer, String conversationId) {
                    runOnMain(() -> completeStreamingChat(answer, conversationId));
                }
            });
            realtimeClient.start();
        } catch (IllegalArgumentException error) {
            startSuggestionPolling();
        }
    }

    private void ignoreBackgroundRealtimeError(String message) {
        // RealtimeClient already schedules reconnects. A background reconnect failure should not
        // overwrite visible chat content; active sends are handled by fallbackStreamingChatAfterRealtimeIssue.
    }

    private void showProactiveBubble(ProactiveMessage message) {
        if (message == null || !message.isDisplayable()) {
            return;
        }
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
        intent.putExtra(WebWorkspaceActivity.EXTRA_URL, ConfigPrefs.baseUrlOrDefault(this) + "#suggestions");
        intent.putExtra(WebWorkspaceActivity.EXTRA_PROACTIVE_ID, message.id);
        intent.putExtra(WebWorkspaceActivity.EXTRA_PROACTIVE_TITLE, message.title);
        intent.putExtra(WebWorkspaceActivity.EXTRA_PROACTIVE_BODY, message.body);
        if (message.rawJson != null && !message.rawJson.trim().isEmpty()) {
            intent.putExtra(WebWorkspaceActivity.EXTRA_REALTIME_EVENT_JSON, message.rawJson);
        }
        startActivity(intent);
        closePanel();
    }

    private void removeBubble() {
        removeView(bubbleView);
        bubbleView = null;
        bubbleParams = null;
    }

    private void showVoiceBubble(String text) {
        removeBubble();
        bubbleView = new TextView(this);
        bubbleView.setText(text == null || text.trim().isEmpty() ? "正在听..." : text.trim());
        bubbleView.setTextSize(13);
        bubbleView.setTextColor(Color.rgb(15, 23, 42));
        bubbleView.setPadding(dp(12), dp(8), dp(12), dp(8));
        bubbleView.setMaxLines(4);
        bubbleView.setBackground(rounded(Color.rgb(204, 251, 241), Color.rgb(20, 184, 166), 16));
        bubbleView.setElevation(dp(8));
        bubbleParams = overlayParams(dp(240), dp(86), false);
        bubbleParams.gravity = Gravity.TOP | Gravity.START;
        positionBubble();
        windowManager.addView(bubbleView, bubbleParams);
    }

    private void showVoiceConfirmBubble(String transcript) {
        String text = transcript == null ? "" : transcript.trim();
        if (text.isEmpty()) {
            showVoiceBubble("没听清，再说一次。");
            return;
        }
        showVoiceBubble("我听到的是：\n" + text + "\n点此发送");
        if (bubbleView != null) {
            bubbleView.setOnClickListener(view -> {
                removeBubble();
                sendMessage(text);
            });
        }
    }

    private void positionBubble() {
        if (bubbleParams == null || ballParams == null) return;
        int screenWidth = getResources().getDisplayMetrics().widthPixels;
        int x = ballParams.x + dp(76);
        if (x + dp(230) > screenWidth) x = Math.max(0, ballParams.x - dp(234));
        bubbleParams.x = x;
        bubbleParams.y = Math.max(0, ballParams.y + dp(4));
    }

    private void moveBallToRawPosition(int rawX, int rawY) {
        if (ballParams == null || ballView == null) return;
        int width = Math.max(ballView.getWidth(), dp(72));
        int height = Math.max(ballView.getHeight(), dp(72));
        int screenWidth = getResources().getDisplayMetrics().widthPixels;
        int screenHeight = getResources().getDisplayMetrics().heightPixels;
        ballParams.x = clamp(rawX - width / 2, 0, Math.max(0, screenWidth - width));
        ballParams.y = clamp(rawY - height / 2, 0, Math.max(0, screenHeight - height));
        windowManager.updateViewLayout(ballView, ballParams);
        positionBubble();
        if (bubbleView != null && bubbleParams != null) windowManager.updateViewLayout(bubbleView, bubbleParams);
    }

    private void snapBallToEdge() {
        if (ballParams == null || ballView == null) return;
        int screenWidth = getResources().getDisplayMetrics().widthPixels;
        int width = Math.max(ballView.getWidth(), dp(72));
        ballParams.x = ballParams.x + width / 2 > screenWidth / 2 ? screenWidth - width : 0;
        windowManager.updateViewLayout(ballView, ballParams);
        positionBubble();
        if (bubbleView != null && bubbleParams != null) windowManager.updateViewLayout(bubbleView, bubbleParams);
    }

    private int clamp(int value, int min, int max) {
        return Math.max(min, Math.min(max, value));
    }

    private void buildSettingsView() {
        if (settingsContentView == null) return;
        settingsContentView.removeAllViews();

        TextView title = new TextView(this);
        title.setText("设置");
        title.setTextSize(15);
        title.setTextColor(Color.rgb(15, 23, 42));
        settingsContentView.addView(title, new LinearLayout.LayoutParams(-1, -2));

        Button back = new Button(this);
        back.setText("返回对话");
        styleSecondaryButton(back);
        back.setOnClickListener(view -> showChatView());
        LinearLayout.LayoutParams backParams = new LinearLayout.LayoutParams(-1, dp(44));
        backParams.setMargins(0, dp(8), 0, 0);
        settingsContentView.addView(back, backParams);

        for (FloatingPanelTab shortcut : FloatingPanelTabs.settingsShortcuts()) {
            Button button = new Button(this);
            button.setText(shortcut.label);
            if ("career".equals(shortcut.id)) {
                stylePrimaryButton(button);
                button.setOnClickListener(view -> showCareerView());
            } else if ("accounts".equals(shortcut.id)) {
                stylePrimaryButton(button);
                button.setOnClickListener(view -> toggleAccounts());
            } else {
                styleSecondaryButton(button);
            }
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, dp(44));
            params.setMargins(0, dp(8), 0, 0);
            settingsContentView.addView(button, params);
        }

        TextView note = new TextView(this);
        note.setText("Gmail、Calendar 等工具授权会打开 Composio；WhatsApp 等网页登录会打开服务器远程浏览器。");
        note.setTextSize(12);
        note.setTextColor(Color.rgb(100, 116, 139));
        LinearLayout.LayoutParams noteParams = new LinearLayout.LayoutParams(-1, -2);
        noteParams.setMargins(0, dp(8), 0, dp(8));
        settingsContentView.addView(note, noteParams);

        settingsStatusView = new TextView(this);
        settingsStatusView.setText("");
        settingsStatusView.setTextSize(12);
        settingsStatusView.setTextColor(Color.rgb(15, 118, 110));
        settingsContentView.addView(settingsStatusView, new LinearLayout.LayoutParams(-1, -2));

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
        if (agendaContentView != null) agendaContentView.setVisibility(View.GONE);
        if (careerContentView != null) careerContentView.setVisibility(View.GONE);
        if (settingsContentView != null) settingsContentView.setVisibility(View.GONE);
    }

    private void showSettingsView() {
        if (chatContentView != null) chatContentView.setVisibility(View.GONE);
        if (agendaContentView != null) agendaContentView.setVisibility(View.GONE);
        if (careerContentView != null) careerContentView.setVisibility(View.GONE);
        if (settingsContentView != null) settingsContentView.setVisibility(View.VISIBLE);
        if (accountsScrollView != null) accountsScrollView.setVisibility(View.GONE);
    }

    private void showAgendaView() {
        if (chatContentView != null) chatContentView.setVisibility(View.GONE);
        if (settingsContentView != null) settingsContentView.setVisibility(View.GONE);
        if (careerContentView != null) careerContentView.setVisibility(View.GONE);
        if (agendaContentView != null) agendaContentView.setVisibility(View.VISIBLE);
        loadAgendaItems();
    }

    private void showCareerView() {
        if (chatContentView != null) chatContentView.setVisibility(View.GONE);
        if (agendaContentView != null) agendaContentView.setVisibility(View.GONE);
        if (settingsContentView != null) settingsContentView.setVisibility(View.GONE);
        if (careerContentView != null) careerContentView.setVisibility(View.VISIBLE);
        loadCareerBoard();
    }

    private LinearLayout buildAgendaContentView() {
        LinearLayout container = new LinearLayout(this);
        container.setOrientation(LinearLayout.VERTICAL);

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        TextView title = new TextView(this);
        title.setText("日程");
        title.setTextSize(15);
        title.setTextColor(Color.rgb(15, 23, 42));
        header.addView(title, new LinearLayout.LayoutParams(0, -2, 1));

        Button back = new Button(this);
        back.setText("对话");
        styleSecondaryButton(back);
        back.setOnClickListener(view -> showChatView());
        header.addView(back, new LinearLayout.LayoutParams(dp(72), dp(42)));

        Button refresh = new Button(this);
        refresh.setText("刷新");
        styleSecondaryButton(refresh);
        refresh.setOnClickListener(view -> loadAgendaItems());
        LinearLayout.LayoutParams refreshParams = new LinearLayout.LayoutParams(dp(72), dp(42));
        refreshParams.setMargins(dp(6), 0, 0, 0);
        header.addView(refresh, refreshParams);
        container.addView(header);

        agendaStatusView = new TextView(this);
        agendaStatusView.setText("");
        agendaStatusView.setTextSize(12);
        agendaStatusView.setTextColor(Color.rgb(15, 118, 110));
        container.addView(agendaStatusView, new LinearLayout.LayoutParams(-1, -2));

        agendaListView = new LinearLayout(this);
        agendaListView.setOrientation(LinearLayout.VERTICAL);
        agendaListView.setPadding(0, dp(6), 0, dp(6));
        agendaScrollView = new ScrollView(this);
        agendaScrollView.addView(agendaListView);
        container.addView(agendaScrollView, new LinearLayout.LayoutParams(-1, 0, 1));
        return container;
    }

    private LinearLayout buildCareerContentView() {
        LinearLayout container = new LinearLayout(this);
        container.setOrientation(LinearLayout.VERTICAL);

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        TextView title = new TextView(this);
        title.setText("求职看板");
        title.setTextSize(15);
        title.setTextColor(Color.rgb(15, 23, 42));
        header.addView(title, new LinearLayout.LayoutParams(0, -2, 1));

        Button back = new Button(this);
        back.setText("设置");
        styleSecondaryButton(back);
        back.setOnClickListener(view -> showSettingsView());
        header.addView(back, new LinearLayout.LayoutParams(dp(72), dp(42)));

        Button refresh = new Button(this);
        refresh.setText("刷新");
        styleSecondaryButton(refresh);
        refresh.setOnClickListener(view -> loadCareerBoard());
        LinearLayout.LayoutParams refreshParams = new LinearLayout.LayoutParams(dp(72), dp(42));
        refreshParams.setMargins(dp(6), 0, 0, 0);
        header.addView(refresh, refreshParams);
        container.addView(header);

        careerStatusView = new TextView(this);
        careerStatusView.setText("");
        careerStatusView.setTextSize(12);
        careerStatusView.setTextColor(Color.rgb(15, 118, 110));
        container.addView(careerStatusView, new LinearLayout.LayoutParams(-1, -2));

        careerListView = new LinearLayout(this);
        careerListView.setOrientation(LinearLayout.VERTICAL);
        careerListView.setPadding(0, dp(6), 0, dp(6));
        careerScrollView = new ScrollView(this);
        careerScrollView.addView(careerListView);
        container.addView(careerScrollView, new LinearLayout.LayoutParams(-1, 0, 1));
        return container;
    }

    private void openAppChat() {
        Intent intent = new Intent(this, WebWorkspaceActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        intent.putExtra(WebWorkspaceActivity.EXTRA_URL, WorkbenchUrls.chatUrl(ConfigPrefs.baseUrlOrDefault(this), activeConversationId));
        startActivity(intent);
        closePanel();
    }

    private void rememberActiveConversationId(String conversationId) {
        String cleanConversationId = conversationId == null ? "" : conversationId.trim();
        if (cleanConversationId.isEmpty()) return;
        activeConversationId = cleanConversationId;
        ConfigPrefs.writeConversationId(this, conversationId);
    }

    private TextView addChatMessage(String speaker, String body) {
        TextView message = new TextView(this);
        message.setText(messageText(speaker, body));
        message.setSingleLine(false);
        message.setHorizontallyScrolling(false);
        message.setBreakStrategy(Layout.BREAK_STRATEGY_HIGH_QUALITY);
        message.setHyphenationFrequency(Layout.HYPHENATION_FREQUENCY_NORMAL);
        message.setTextSize(13);
        message.setTextColor(Color.rgb(15, 23, 42));
        message.setPadding(dp(10), dp(8), dp(10), dp(8));
        FloatingMessageLinks.enableClickableLinks(message, this::openChatMessageUrl);
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
        openAccountsList("正在读取账号状态...");
    }

    private void loadCareerBoard() {
        if (careerListView == null) return;
        careerListView.removeAllViews();
        if (careerStatusView != null) careerStatusView.setText("正在读取求职看板...");
        TextView loading = new TextView(this);
        loading.setText("求职看板\n正在加载岗位、简历草案和申请状态。");
        loading.setTextSize(13);
        loading.setTextColor(Color.rgb(51, 65, 85));
        loading.setPadding(dp(10), dp(8), dp(10), dp(8));
        loading.setBackground(rounded(Color.rgb(248, 250, 252), Color.rgb(226, 232, 240), 12));
        careerListView.addView(loading);
        executor.execute(() -> {
            try {
                CareerBoardResult board = api().careerBoard();
                runOnMain(() -> {
                    renderCareerBoard(board);
                    if (careerStatusView != null) careerStatusView.setText("求职看板已刷新。");
                });
            } catch (Exception error) {
                runOnMain(() -> {
                    careerListView.removeAllViews();
                    TextView failed = new TextView(this);
                    failed.setText("求职看板加载失败\n" + error.getMessage());
                    failed.setTextSize(13);
                    failed.setTextColor(Color.rgb(153, 27, 27));
                    failed.setPadding(dp(10), dp(8), dp(10), dp(8));
                    failed.setBackground(rounded(Color.rgb(254, 226, 226), Color.rgb(252, 165, 165), 12));
                    careerListView.addView(failed);
                    if (careerStatusView != null) careerStatusView.setText("求职看板加载失败。");
                });
            }
        });
    }

    private void loadAgendaItems() {
        if (agendaListView == null) return;
        agendaListView.removeAllViews();
        if (agendaStatusView != null) agendaStatusView.setText("正在读取日程...");
        TextView loading = new TextView(this);
        loading.setText("日程\n正在加载 Gmail、Calendar、WhatsApp、Telegram 等来源整理出的近期安排。");
        loading.setTextSize(13);
        loading.setTextColor(Color.rgb(51, 65, 85));
        loading.setPadding(dp(10), dp(8), dp(10), dp(8));
        loading.setBackground(rounded(Color.rgb(248, 250, 252), Color.rgb(226, 232, 240), 12));
        agendaListView.addView(loading);
        executor.execute(() -> {
            try {
                List<AgendaItem> items = api().agendaItems();
                runOnMain(() -> {
                    renderAgendaItems(items);
                    if (agendaStatusView != null) agendaStatusView.setText("日程已刷新。");
                });
            } catch (Exception error) {
                runOnMain(() -> {
                    agendaListView.removeAllViews();
                    TextView failed = new TextView(this);
                    failed.setText("日程加载失败\n" + error.getMessage());
                    failed.setTextSize(13);
                    failed.setTextColor(Color.rgb(153, 27, 27));
                    failed.setPadding(dp(10), dp(8), dp(10), dp(8));
                    failed.setBackground(rounded(Color.rgb(254, 226, 226), Color.rgb(252, 165, 165), 12));
                    agendaListView.addView(failed);
                    if (agendaStatusView != null) agendaStatusView.setText("日程加载失败。");
                });
            }
        });
    }

    private void renderAgendaItems(List<AgendaItem> items) {
        if (agendaListView == null) return;
        agendaListView.removeAllViews();
        TextView heading = new TextView(this);
        heading.setText("近期日程");
        heading.setTextSize(15);
        heading.setTextColor(Color.rgb(15, 23, 42));
        agendaListView.addView(heading);

        TextView note = new TextView(this);
        note.setText("这里展示 Nomi 从私有信息里整理出的会议、约定、截止日期和提醒。时间优先展示具体日期。");
        note.setTextSize(12);
        note.setTextColor(Color.rgb(100, 116, 139));
        agendaListView.addView(note);

        if (items == null || items.isEmpty()) {
            TextView empty = new TextView(this);
            empty.setText("暂无近期日程。若你刚刚收到会议邮件，Nomi 会在采集器处理后自动出现在这里。");
            empty.setTextSize(13);
            empty.setTextColor(Color.rgb(71, 85, 105));
            empty.setPadding(dp(10), dp(8), dp(10), dp(8));
            empty.setBackground(rounded(Color.rgb(248, 250, 252), Color.rgb(226, 232, 240), 12));
            LinearLayout.LayoutParams emptyParams = new LinearLayout.LayoutParams(-1, -2);
            emptyParams.setMargins(0, dp(6), 0, 0);
            agendaListView.addView(empty, emptyParams);
            return;
        }

        for (AgendaItem item : items) {
            TextView card = new TextView(this);
            card.setText(item.cardText());
            card.setTextSize(13);
            card.setTextColor(Color.rgb(15, 23, 42));
            card.setPadding(dp(10), dp(8), dp(10), dp(8));
            card.setBackground(rounded(Color.rgb(248, 250, 252), Color.rgb(226, 232, 240), 12));
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
            params.setMargins(0, dp(6), 0, 0);
            agendaListView.addView(card, params);
        }
    }

    private void renderCareerBoard(CareerBoardResult board) {
        if (careerListView == null) return;
        careerListView.removeAllViews();
        TextView heading = new TextView(this);
        heading.setText("求职看板");
        heading.setTextSize(15);
        heading.setTextColor(Color.rgb(15, 23, 42));
        careerListView.addView(heading);

        TextView note = new TextView(this);
        note.setText("这里展示 Nomi 从 JD、简历、邮件和 LinkedIn 信号里整理出的机会、材料和申请状态。");
        note.setTextSize(12);
        note.setTextColor(Color.rgb(100, 116, 139));
        careerListView.addView(note);

        for (String cardText : CareerBoardPresenter.cards(board)) {
            TextView card = new TextView(this);
            card.setText(cardText);
            card.setTextSize(13);
            card.setTextColor(Color.rgb(15, 23, 42));
            card.setPadding(dp(10), dp(8), dp(10), dp(8));
            card.setBackground(rounded(Color.rgb(248, 250, 252), Color.rgb(226, 232, 240), 12));
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
            params.setMargins(0, dp(6), 0, 0);
            careerListView.addView(card, params);
        }
        List<CareerBoardAction> actions = CareerBoardPresenter.actions(board);
        if (!actions.isEmpty()) {
            TextView actionHeading = new TextView(this);
            actionHeading.setText("可执行操作");
            actionHeading.setTextSize(14);
            actionHeading.setTextColor(Color.rgb(15, 23, 42));
            LinearLayout.LayoutParams headingParams = new LinearLayout.LayoutParams(-1, -2);
            headingParams.setMargins(0, dp(10), 0, 0);
            careerListView.addView(actionHeading, headingParams);
        }
        for (CareerBoardAction action : actions) {
            Button button = new Button(this);
            button.setText(action.label);
            styleSecondaryButton(button);
            button.setOnClickListener(view -> applyCareerBoardAction(action));
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, dp(42));
            params.setMargins(0, dp(6), 0, 0);
            careerListView.addView(button, params);
        }
    }

    private void applyCareerBoardAction(CareerBoardAction action) {
        if (careerStatusView != null) careerStatusView.setText("正在更新求职状态...");
        executor.execute(() -> {
            try {
                api().updateCareerApplication(
                        action.applicationId,
                        action.status,
                        action.stage,
                        action.nextStep,
                        action.userNote
                );
                CareerBoardResult board = api().careerBoard();
                runOnMain(() -> {
                    renderCareerBoard(board);
                    if (careerStatusView != null) careerStatusView.setText("求职状态已更新。");
                });
            } catch (Exception error) {
                runOnMain(() -> {
                    if (careerStatusView != null) {
                        careerStatusView.setText("求职状态更新失败：" + error.getMessage());
                    }
                });
            }
        });
    }

    private void showAccountsAfterExternalAuth(String message) {
        if (windowManager == null) return;
        removeExternalAuthCloseButton();
        if (ballView == null) showBall();
        if (panelView == null) {
            removeBubble();
            showPanel();
        }
        showSettingsView();
        openAccountsList(
                message == null || message.trim().isEmpty()
                        ? "授权流程已返回，正在刷新账号状态。"
                        : message.trim()
        );
    }

    private void openAccountsList(String message) {
        if (accountsView == null || accountsScrollView == null) return;
        renderAccountChannels(null);
        accountsScrollView.setVisibility(View.VISIBLE);
        if (settingsStatusView != null) settingsStatusView.setText(message == null ? "" : message);
        executor.execute(() -> {
            try {
                Map<String, CollectorStatus> statuses = api().accountStatuses();
                List<AssistantIdentity> identities = api().assistantIdentities();
                runOnMain(() -> {
                    renderAccountChannels(statuses, identities);
                    if (settingsStatusView != null) settingsStatusView.setText("账号状态已刷新。");
                });
            } catch (Exception error) {
                runOnMain(() -> {
                    renderAccountChannels(null);
                    if (settingsStatusView != null) {
                        settingsStatusView.setText("账号状态读取失败，仍可重新打开授权：" + error.getMessage());
                    }
                });
            }
        });
    }

    private void renderAccountChannels(Map<String, CollectorStatus> statuses) {
        renderAccountChannels(statuses, List.of());
    }

    private void renderAccountChannels(Map<String, CollectorStatus> statuses, List<AssistantIdentity> identities) {
        if (accountsView == null) return;
        accountsView.removeAllViews();

        if (identities != null && !identities.isEmpty()) {
            TextView identityHeading = new TextView(this);
            identityHeading.setText("Nomi 身份");
            identityHeading.setTextSize(15);
            identityHeading.setTextColor(Color.rgb(15, 23, 42));
            accountsView.addView(identityHeading);

            TextView identityNote = new TextView(this);
            identityNote.setText("这些是 Nomi 自己用来收发消息的身份，和你的个人账号分开管理。");
            identityNote.setTextSize(12);
            identityNote.setTextColor(Color.rgb(100, 116, 139));
            accountsView.addView(identityNote);

            for (AssistantIdentity identity : identities) {
                accountsView.addView(assistantIdentityRow(identity));
            }
        }

        TextView heading = new TextView(this);
        heading.setText("支持的登录渠道");
        heading.setTextSize(15);
        heading.setTextColor(Color.rgb(15, 23, 42));
        accountsView.addView(heading);

        TextView note = new TextView(this);
        note.setText("点击需要登录的渠道。工具授权会打开 Composio 登录页；网页会打开服务器浏览器。账号密码和扫码仍由你自己完成。");
        note.setTextSize(12);
        note.setTextColor(Color.rgb(100, 116, 139));
        accountsView.addView(note);

        for (AccountChannel channel : ACCOUNT_CHANNELS) {
            accountsView.addView(accountRow(channel, statuses == null ? null : statuses.get(channel.source)));
        }
    }

    private View assistantIdentityRow(AssistantIdentity identity) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setPadding(dp(10), dp(8), dp(10), dp(8));
        row.setBackground(rounded(Color.rgb(240, 253, 250), Color.rgb(153, 246, 228), 12));

        TextView title = new TextView(this);
        title.setText(identity.displayName);
        title.setTextSize(14);
        title.setTextColor(Color.rgb(15, 23, 42));
        row.addView(title);

        TextView body = new TextView(this);
        body.setText(identity.subtitle());
        body.setTextSize(12);
        body.setTextColor(Color.rgb(51, 65, 85));
        row.addView(body);

        LinearLayout.LayoutParams margins = new LinearLayout.LayoutParams(-1, -2);
        margins.setMargins(0, dp(6), 0, 0);
        row.setLayoutParams(margins);
        return row;
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
        AccountChannelRoute route = AccountChannelRoute.forSource(channel.source);
        if (route.shouldOpenForStatus(status)) {
            row.setOnClickListener(view -> openAccountChannel(channel));
        } else if (route.kind() == AccountChannelRoute.Kind.COMPOSIO_CONNECT
                && status != null
                && "healthy".equals(status.healthStatus)) {
            row.setAlpha(0.82f);
            row.setOnClickListener(view -> {
                if (responseView != null) {
                    responseView.setText(channel.name + " 已授权，不需要重新打开授权页。");
                }
            });
        }
        return row;
    }

    private String statusText(AccountChannel channel, CollectorStatus status) {
        if ("shopping".equals(channel.source)) return "间接";
        if (status != null) return status.displayLabel(channel.opensBrowser);
        if (!channel.opensBrowser) {
            return "本地";
        }
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

    private void openRemoteBrowser(String source) {
        String normalizedSource = source == null ? "" : source.trim();
        if (normalizedSource.isEmpty()) {
            if (responseView != null) responseView.setText("缺少远程浏览器来源。");
            return;
        }
        if (responseView != null) responseView.setText("正在打开 " + normalizedSource + " 登录页...");
        executor.execute(() -> {
            try {
                BrowserOpenResult open = api().requestRemoteBrowserOpen(normalizedSource);
                if (open.commandId.isEmpty()) {
                    throw new IllegalStateException("服务器没有返回浏览器命令编号");
                }
                BrowserCommandStatus status = api().waitForBrowserCommand(open.commandId, 45000L);
                runOnMain(() -> {
                    if (status.isNavigationReady()) {
                        openRemoteBrowserActivity();
                        return;
                    }
                    if (responseView != null) {
                        responseView.setText(
                                normalizedSource
                                        + " 登录页还没有准备好："
                                        + (status.status.isEmpty() ? "unknown" : status.status)
                                        + "。请稍后重试。"
                        );
                    }
                });
            } catch (Exception error) {
                runOnMain(() -> {
                    if (responseView != null) {
                        responseView.setText("远程浏览器导航失败：" + error.getMessage());
                    }
                });
            }
        });
    }

    private boolean openChatMessageUrl(String url) {
        if (!FloatingMessageLinks.isLinkedInJobDetailUrl(url)) {
            closePanel();
            return false;
        }
        closePanel();
        executor.execute(() -> {
            try {
                BrowserOpenResult open = api().requestRemoteBrowserOpenLinkedInJob(url);
                if (open.commandId.isEmpty()) {
                    throw new IllegalStateException("服务器没有返回岗位打开命令编号");
                }
                BrowserCommandStatus status = api().waitForBrowserCommand(open.commandId, 45000L);
                runOnMain(() -> {
                    if (status.isNavigationReady()) {
                        openRemoteBrowserActivity();
                        return;
                    }
                    showPanel();
                    if (responseView != null) {
                        responseView.setText("LinkedIn 岗位页还没有准备好：" + (status.status.isEmpty() ? "unknown" : status.status));
                    }
                });
            } catch (Exception error) {
                runOnMain(() -> {
                    showPanel();
                    if (responseView != null) {
                        responseView.setText("打开 LinkedIn 岗位页失败：" + error.getMessage());
                    }
                });
            }
        });
        return true;
    }

    private void openRemoteBrowserActivity() {
        Intent intent = new Intent(this, WebWorkspaceActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        intent.putExtra(WebWorkspaceActivity.EXTRA_URL, ConfigPrefs.remoteBrowserUrl(this));
        intent.putExtra(WebWorkspaceActivity.EXTRA_REMOTE_BROWSER_MODE, true);
        startActivity(intent);
        closePanel();
    }

    private void openAccountChannel(AccountChannel channel) {
        AccountChannelRoute route = AccountChannelRoute.forSource(channel.source);
        if (route.kind() == AccountChannelRoute.Kind.COMPOSIO_CONNECT) {
            if (responseView != null) responseView.setText("正在生成 " + channel.name + " 授权链接...");
            executor.execute(() -> {
                try {
                    String redirectUrl = api().composioConnectUrl(route.composioToolkitSlug());
                    runOnMain(() -> openExternalUrl(redirectUrl, route.requiresUnobstructedExternalAuth()));
                } catch (Exception error) {
                    runOnMain(() -> {
                        if (responseView != null) {
                            responseView.setText(channel.name + " 授权链接生成失败：" + error.getMessage());
                        }
                    });
                }
            });
            return;
        }
        if (route.kind() == AccountChannelRoute.Kind.REMOTE_BROWSER) {
            openRemoteBrowser(route.remoteBrowserSource());
            return;
        }
        if (responseView != null) responseView.setText(channel.name + " 不需要网页登录授权。");
    }

    private void openExternalUrl(String url, boolean hideOverlays) {
        if (hideOverlays) {
            hideAssistantOverlaysForExternalAuth();
        }
        Intent intent = externalAuthIntent(url);
        startActivity(intent);
        if (!hideOverlays) {
            closePanel();
        }
    }

    private Intent externalAuthIntent(String url) {
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        Bundle customTabsExtras = new Bundle();
        customTabsExtras.putBinder("android.support.customtabs.extra.SESSION", null);
        intent.putExtras(customTabsExtras);
        intent.putExtra("android.support.customtabs.extra.TITLE_VISIBILITY", 1);
        return intent;
    }

    private void hideAssistantOverlaysForExternalAuth() {
        closePanel();
        removeBubble();
        if (ballView == null) showBall();
        showExternalAuthCloseButton();
    }

    private void showExternalAuthCloseButton() {
        removeExternalAuthCloseButton();
        externalAuthCloseView = closeButton();
        externalAuthCloseView.setText("×");
        externalAuthCloseView.setContentDescription("关闭授权页面");
        externalAuthCloseView.setElevation(dp(14));
        externalAuthCloseView.setOnClickListener(view -> closeExternalAuthPage());

        externalAuthCloseParams = overlayParams(dp(56), dp(56), false);
        externalAuthCloseParams.gravity = Gravity.TOP | Gravity.END;
        externalAuthCloseParams.x = dp(12);
        externalAuthCloseParams.y = dp(40);
        windowManager.addView(externalAuthCloseView, externalAuthCloseParams);
    }

    private void removeExternalAuthCloseButton() {
        removeView(externalAuthCloseView);
        externalAuthCloseView = null;
        externalAuthCloseParams = null;
    }

    private void closeExternalAuthPage() {
        removeExternalAuthCloseButton();
        Intent home = new Intent(Intent.ACTION_MAIN);
        home.addCategory(Intent.CATEGORY_HOME);
        home.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        startActivity(home);
        showAccountsAfterExternalAuth(ExternalAuthOverlayState.cancelMessage());
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
