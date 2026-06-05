package com.par.assistant.android;

import android.view.MotionEvent;
import android.view.View;

final class VoicePressController implements View.OnTouchListener {
    interface DecisionCallback {
        void onTap();
        void onDragMove(int x, int y);
        void onDragEnd(int x, int y);
        void onVoiceStart();
        void onVoiceCancelArmed(boolean armed);
        void onVoiceEnd();
        void onVoiceCancelled();
    }

    private final DecisionState state;

    VoicePressController(long longPressMs, float touchSlopPx, float cancelDistancePx, DecisionCallback callback) {
        this.state = new DecisionState(longPressMs, touchSlopPx, cancelDistancePx, callback);
    }

    @Override
    public boolean onTouch(View view, MotionEvent event) {
        state.handle(event.getActionMasked(), event.getRawX(), event.getRawY(), event.getEventTime());
        return true;
    }

    static final class DecisionState {
        private enum Mode {
            IDLE,
            ARMING,
            DRAGGING,
            VOICE
        }

        private final long longPressMs;
        private final float touchSlopPx;
        private final float cancelDistancePx;
        private final DecisionCallback callback;
        private Mode mode = Mode.IDLE;
        private float downX;
        private float downY;
        private long downAtMs;
        private boolean cancelArmed;

        DecisionState(long longPressMs, float touchSlopPx, float cancelDistancePx, DecisionCallback callback) {
            this.longPressMs = longPressMs;
            this.touchSlopPx = touchSlopPx;
            this.cancelDistancePx = cancelDistancePx;
            this.callback = callback;
        }

        void handle(int action, float rawX, float rawY, long eventTimeMs) {
            if (action == MotionEvent.ACTION_DOWN) {
                mode = Mode.ARMING;
                downX = rawX;
                downY = rawY;
                downAtMs = eventTimeMs;
                cancelArmed = false;
                return;
            }

            if (mode == Mode.ARMING && action == MotionEvent.ACTION_MOVE) {
                float dx = rawX - downX;
                float dy = rawY - downY;
                float distance = distance(dx, dy);
                if (eventTimeMs - downAtMs >= longPressMs && distance <= touchSlopPx * 1.5f) {
                    mode = Mode.VOICE;
                    callback.onVoiceStart();
                    return;
                }
                if (distance > touchSlopPx * 1.5f) {
                    mode = Mode.DRAGGING;
                    callback.onDragMove(Math.round(rawX), Math.round(rawY));
                    return;
                }
            }

            if (mode == Mode.DRAGGING) {
                if (action == MotionEvent.ACTION_MOVE) {
                    callback.onDragMove(Math.round(rawX), Math.round(rawY));
                } else if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
                    callback.onDragEnd(Math.round(rawX), Math.round(rawY));
                    reset();
                }
                return;
            }

            if (mode == Mode.VOICE) {
                if (action == MotionEvent.ACTION_MOVE) {
                    boolean armed = rawY <= downY - cancelDistancePx || rawX <= downX - cancelDistancePx;
                    if (armed != cancelArmed) {
                        cancelArmed = armed;
                        callback.onVoiceCancelArmed(armed);
                    }
                    return;
                }
                if (action == MotionEvent.ACTION_UP) {
                    if (cancelArmed) {
                        callback.onVoiceCancelled();
                    } else {
                        callback.onVoiceEnd();
                    }
                    reset();
                    return;
                }
                if (action == MotionEvent.ACTION_CANCEL) {
                    callback.onVoiceCancelled();
                    reset();
                }
                return;
            }

            if (mode == Mode.ARMING && action == MotionEvent.ACTION_UP) {
                if (eventTimeMs - downAtMs >= longPressMs) {
                    callback.onVoiceStart();
                    callback.onVoiceEnd();
                } else {
                    callback.onTap();
                }
                reset();
                return;
            }

            if (action == MotionEvent.ACTION_CANCEL) {
                reset();
            }
        }

        boolean voiceActive() {
            return mode == Mode.VOICE;
        }

        private void reset() {
            mode = Mode.IDLE;
            cancelArmed = false;
        }

        private float distance(float dx, float dy) {
            return (float) Math.sqrt(dx * dx + dy * dy);
        }
    }
}
