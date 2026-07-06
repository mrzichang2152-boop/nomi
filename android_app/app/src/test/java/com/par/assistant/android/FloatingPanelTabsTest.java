package com.par.assistant.android;

import static org.junit.Assert.assertEquals;

import java.util.List;

import org.junit.Test;

public final class FloatingPanelTabsTest {
    @Test
    public void keepsCareerOutOfTopLevelFloatingPanelTabs() {
        List<FloatingPanelTab> tabs = FloatingPanelTabs.primaryTabs();

        assertEquals(0, tabs.size());
    }

    @Test
    public void keepsCareerAndAccountsOutOfFloatingPanelShortcuts() {
        List<FloatingPanelTab> shortcuts = FloatingPanelTabs.settingsShortcuts();

        assertEquals(0, shortcuts.size());
    }
}
