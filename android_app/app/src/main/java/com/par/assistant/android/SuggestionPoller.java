package com.par.assistant.android;

import android.os.Handler;
import android.os.Looper;

import com.par.assistant.core.AssistantSuggestion;
import com.par.assistant.core.SuggestionDeduper;

import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

final class SuggestionPoller {
    interface Callback {
        void onNewSuggestions(List<AssistantSuggestion> suggestions);

        void onError(Exception error);
    }

    private final AssistantApiClient api;
    private final SuggestionDeduper deduper;
    private final Callback callback;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final long intervalMillis;
    private boolean running;

    SuggestionPoller(AssistantApiClient api, SuggestionDeduper deduper, Callback callback, long intervalMillis) {
        this.api = api;
        this.deduper = deduper;
        this.callback = callback;
        this.intervalMillis = intervalMillis;
    }

    void start() {
        if (running) return;
        running = true;
        handler.post(this::pollOnce);
    }

    void stop() {
        running = false;
        handler.removeCallbacksAndMessages(null);
    }

    private void pollOnce() {
        if (!running) return;
        executor.execute(() -> {
            try {
                List<AssistantSuggestion> fresh = deduper.filterNew(api.suggestions());
                for (AssistantSuggestion suggestion : fresh) {
                    deduper.markDisplayed(suggestion.id());
                }
                if (!fresh.isEmpty()) {
                    handler.post(() -> callback.onNewSuggestions(fresh));
                }
            } catch (Exception error) {
                handler.post(() -> callback.onError(error));
            } finally {
                handler.postDelayed(this::pollOnce, intervalMillis);
            }
        });
    }
}
