package com.par.assistant.android;

final class FloatingPanelLayout {
    private FloatingPanelLayout() {
    }

    static Frame compute(
            int defaultY,
            int defaultHeight,
            int visibleBottom,
            int screenHeight,
            int topMargin,
            int bottomMargin,
            int minHeight,
            int keyboardThreshold
    ) {
        if (screenHeight - visibleBottom <= keyboardThreshold) {
            return new Frame(defaultY, defaultHeight);
        }

        int maxBottom = Math.max(topMargin, visibleBottom - bottomMargin);
        int availableHeight = Math.max(0, maxBottom - topMargin);
        int height = Math.min(defaultHeight, availableHeight);
        if (height < minHeight && availableHeight >= minHeight) {
            height = minHeight;
        }
        int y = Math.min(defaultY, maxBottom - height);
        y = Math.max(topMargin, y);
        return new Frame(y, height);
    }

    static int visibleBottomForInputFocus(
            int screenHeight,
            int detectedVisibleBottom,
            boolean inputFocused,
            int estimatedKeyboardHeight,
            int keyboardThreshold
    ) {
        if (!inputFocused || screenHeight - detectedVisibleBottom > keyboardThreshold) {
            return detectedVisibleBottom;
        }
        return Math.max(0, screenHeight - estimatedKeyboardHeight);
    }

    static final class Frame {
        final int y;
        final int height;

        Frame(int y, int height) {
            this.y = y;
            this.height = height;
        }
    }
}
