package com.par.assistant.android;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public final class ProactiveSurfacePolicyTest {
    @Test
    public void backgroundUsesCompactOverlayBubble() {
        assertEquals(
                ProactiveSurfacePolicy.Surface.OVERLAY_BUBBLE,
                ProactiveSurfacePolicy.choose(false, false)
        );
    }

    @Test
    public void openFloatingPanelUsesInlineCard() {
        assertEquals(
                ProactiveSurfacePolicy.Surface.INLINE_PANEL_CARD,
                ProactiveSurfacePolicy.choose(true, false)
        );
    }

    @Test
    public void foregroundNomiActivitySuppressesOverlay() {
        assertEquals(
                ProactiveSurfacePolicy.Surface.SUPPRESS_OVERLAY,
                ProactiveSurfacePolicy.choose(false, true)
        );
    }

    @Test
    public void foregroundActivityWinsOverStalePanelState() {
        assertEquals(
                ProactiveSurfacePolicy.Surface.SUPPRESS_OVERLAY,
                ProactiveSurfacePolicy.choose(true, true)
        );
    }
}
