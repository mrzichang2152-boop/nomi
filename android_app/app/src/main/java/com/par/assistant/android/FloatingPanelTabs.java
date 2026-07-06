package com.par.assistant.android;

import java.util.List;

final class FloatingPanelTabs {
    private FloatingPanelTabs() {
    }

    static List<FloatingPanelTab> primaryTabs() {
        return List.of();
    }

    static List<FloatingPanelTab> settingsShortcuts() {
        return List.of();
    }
}

final class FloatingPanelTab {
    final String id;
    final String label;

    FloatingPanelTab(String id, String label) {
        this.id = id == null ? "" : id;
        this.label = label == null ? "" : label;
    }
}
