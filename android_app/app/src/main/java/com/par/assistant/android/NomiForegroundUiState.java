package com.par.assistant.android;

import java.util.concurrent.atomic.AtomicInteger;

final class NomiForegroundUiState {
    private static final AtomicInteger VISIBLE_ACTIVITY_COUNT = new AtomicInteger();

    private NomiForegroundUiState() {
    }

    static void enter() {
        VISIBLE_ACTIVITY_COUNT.incrementAndGet();
    }

    static void exit() {
        while (true) {
            int current = VISIBLE_ACTIVITY_COUNT.get();
            if (current <= 0) return;
            if (VISIBLE_ACTIVITY_COUNT.compareAndSet(current, current - 1)) return;
        }
    }

    static boolean isVisible() {
        return VISIBLE_ACTIVITY_COUNT.get() > 0;
    }

    static void resetForTests() {
        VISIBLE_ACTIVITY_COUNT.set(0);
    }
}
