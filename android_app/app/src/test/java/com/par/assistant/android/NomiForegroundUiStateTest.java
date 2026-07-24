package com.par.assistant.android;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.After;
import org.junit.Test;

public final class NomiForegroundUiStateTest {
    @After
    public void resetState() {
        NomiForegroundUiState.resetForTests();
    }

    @Test
    public void nestedActivitiesRemainForegroundUntilBothStop() {
        NomiForegroundUiState.enter();
        NomiForegroundUiState.enter();
        NomiForegroundUiState.exit();
        assertTrue(NomiForegroundUiState.isVisible());

        NomiForegroundUiState.exit();
        assertFalse(NomiForegroundUiState.isVisible());
    }

    @Test
    public void extraExitClampsAtZero() {
        NomiForegroundUiState.exit();
        NomiForegroundUiState.exit();
        assertFalse(NomiForegroundUiState.isVisible());

        NomiForegroundUiState.enter();
        assertTrue(NomiForegroundUiState.isVisible());
    }
}
