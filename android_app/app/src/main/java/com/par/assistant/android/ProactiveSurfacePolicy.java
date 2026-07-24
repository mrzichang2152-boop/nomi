package com.par.assistant.android;

final class ProactiveSurfacePolicy {
    enum Surface {
        OVERLAY_BUBBLE,
        INLINE_PANEL_CARD,
        SUPPRESS_OVERLAY
    }

    private ProactiveSurfacePolicy() {
    }

    static Surface choose(boolean floatingPanelOpen, boolean nomiActivityVisible) {
        if (nomiActivityVisible) return Surface.SUPPRESS_OVERLAY;
        if (floatingPanelOpen) return Surface.INLINE_PANEL_CARD;
        return Surface.OVERLAY_BUBBLE;
    }
}
