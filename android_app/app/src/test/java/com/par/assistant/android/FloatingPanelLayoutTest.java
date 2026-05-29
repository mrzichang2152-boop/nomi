package com.par.assistant.android;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class FloatingPanelLayoutTest {
    @Test
    public void keepsDefaultFrameWhenKeyboardIsHidden() {
        FloatingPanelLayout.Frame frame = FloatingPanelLayout.compute(
                220,
                440,
                900,
                900,
                24,
                12,
                260,
                120
        );

        assertEquals(220, frame.y);
        assertEquals(440, frame.height);
    }

    @Test
    public void movesPanelAboveKeyboardWhenKeyboardIsVisible() {
        FloatingPanelLayout.Frame frame = FloatingPanelLayout.compute(
                220,
                440,
                620,
                900,
                24,
                12,
                260,
                120
        );

        assertEquals(168, frame.y);
        assertEquals(440, frame.height);
        assertTrue(frame.y + frame.height <= 608);
    }

    @Test
    public void shrinksPanelWhenKeyboardLeavesLittleSpace() {
        FloatingPanelLayout.Frame frame = FloatingPanelLayout.compute(
                220,
                440,
                420,
                900,
                24,
                12,
                260,
                120
        );

        assertEquals(24, frame.y);
        assertEquals(384, frame.height);
        assertTrue(frame.y + frame.height <= 408);
    }

    @Test
    public void estimatesKeyboardTopWhenInputIsFocusedButInsetsAreUnavailable() {
        int visibleBottom = FloatingPanelLayout.visibleBottomForInputFocus(
                900,
                900,
                true,
                320,
                120
        );

        assertEquals(580, visibleBottom);
    }

    @Test
    public void trustsDetectedKeyboardTopWhenInsetsAreAvailable() {
        int visibleBottom = FloatingPanelLayout.visibleBottomForInputFocus(
                900,
                620,
                true,
                320,
                120
        );

        assertEquals(620, visibleBottom);
    }
}
