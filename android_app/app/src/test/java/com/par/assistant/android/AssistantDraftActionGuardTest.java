package com.par.assistant.android;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class AssistantDraftActionGuardTest {
    @Test
    public void repeatedTapCannotStartASecondSendUntilFirstFinishes() {
        AssistantDraftActionGuard guard = new AssistantDraftActionGuard();

        assertTrue(guard.begin("draft-shared-1"));
        assertFalse(guard.begin("draft-shared-1"));

        guard.finish("draft-shared-1");
        assertTrue(guard.begin("draft-shared-1"));
    }

    @Test
    public void emptyDraftIdNeverStartsAnAction() {
        AssistantDraftActionGuard guard = new AssistantDraftActionGuard();

        assertFalse(guard.begin(""));
        assertFalse(guard.begin(null));
    }
}
