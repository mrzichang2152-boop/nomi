package com.par.assistant.android;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import android.view.MotionEvent;

import org.junit.Test;

import java.util.ArrayList;
import java.util.List;

public final class VoicePressControllerTest {
    @Test
    public void shortTapTriggersTapOnly() {
        Recorder recorder = new Recorder();
        VoicePressController.DecisionState state = new VoicePressController.DecisionState(450, 12, 96, recorder);

        state.handle(MotionEvent.ACTION_DOWN, 10, 10, 0);
        state.handle(MotionEvent.ACTION_UP, 10, 10, 120);

        assertEquals(List.of("tap"), recorder.events);
        assertFalse(state.voiceActive());
    }

    @Test
    public void movementBeforeLongPressStartsDrag() {
        Recorder recorder = new Recorder();
        VoicePressController.DecisionState state = new VoicePressController.DecisionState(450, 12, 96, recorder);

        state.handle(MotionEvent.ACTION_DOWN, 10, 10, 0);
        state.handle(MotionEvent.ACTION_MOVE, 40, 10, 100);
        state.handle(MotionEvent.ACTION_UP, 44, 12, 140);

        assertEquals(List.of("dragMove:40,10", "dragEnd:44,12"), recorder.events);
        assertFalse(state.voiceActive());
    }

    @Test
    public void longPressStartsVoiceAndReleaseEndsVoice() {
        Recorder recorder = new Recorder();
        VoicePressController.DecisionState state = new VoicePressController.DecisionState(450, 12, 96, recorder);

        state.handle(MotionEvent.ACTION_DOWN, 10, 10, 0);
        state.handle(MotionEvent.ACTION_MOVE, 10, 10, 451);
        assertTrue(state.voiceActive());
        state.handle(MotionEvent.ACTION_UP, 10, 10, 600);

        assertEquals(List.of("voiceStart", "voiceEnd"), recorder.events);
        assertFalse(state.voiceActive());
    }

    @Test
    public void slideDuringVoiceArmsCancelAndReleaseCancels() {
        Recorder recorder = new Recorder();
        VoicePressController.DecisionState state = new VoicePressController.DecisionState(450, 12, 96, recorder);

        state.handle(MotionEvent.ACTION_DOWN, 100, 100, 0);
        state.handle(MotionEvent.ACTION_MOVE, 100, 100, 451);
        state.handle(MotionEvent.ACTION_MOVE, 100, 0, 520);
        state.handle(MotionEvent.ACTION_UP, 100, 0, 560);

        assertEquals(List.of("voiceStart", "cancelArmed:true", "voiceCancelled"), recorder.events);
        assertFalse(state.voiceActive());
    }

    @Test
    public void actionCancelCleansUpVoiceState() {
        Recorder recorder = new Recorder();
        VoicePressController.DecisionState state = new VoicePressController.DecisionState(450, 12, 96, recorder);

        state.handle(MotionEvent.ACTION_DOWN, 10, 10, 0);
        state.handle(MotionEvent.ACTION_MOVE, 10, 10, 451);
        state.handle(MotionEvent.ACTION_CANCEL, 10, 10, 460);

        assertEquals(List.of("voiceStart", "voiceCancelled"), recorder.events);
        assertFalse(state.voiceActive());
    }

    private static final class Recorder implements VoicePressController.DecisionCallback {
        final List<String> events = new ArrayList<>();

        @Override
        public void onTap() {
            events.add("tap");
        }

        @Override
        public void onDragMove(int x, int y) {
            events.add("dragMove:" + x + "," + y);
        }

        @Override
        public void onDragEnd(int x, int y) {
            events.add("dragEnd:" + x + "," + y);
        }

        @Override
        public void onVoiceStart() {
            events.add("voiceStart");
        }

        @Override
        public void onVoiceCancelArmed(boolean armed) {
            events.add("cancelArmed:" + armed);
        }

        @Override
        public void onVoiceEnd() {
            events.add("voiceEnd");
        }

        @Override
        public void onVoiceCancelled() {
            events.add("voiceCancelled");
        }
    }
}
