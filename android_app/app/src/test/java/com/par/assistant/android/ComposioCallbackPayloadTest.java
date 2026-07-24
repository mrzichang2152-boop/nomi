package com.par.assistant.android;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class ComposioCallbackPayloadTest {
    @Test
    public void recognizesNomiComposioCallbackPath() {
        assertTrue(ComposioCallbackPayload.isCallback("nomi", "composio", "/connected"));
        assertFalse(ComposioCallbackPayload.isCallback("https", "composio", "/connected"));
        assertFalse(ComposioCallbackPayload.isCallback("nomi", "other", "/connected"));
    }

    @Test
    public void buildsHumanStatusMessageForKnownToolkit() {
        String message = ComposioCallbackPayload.statusMessage("gmail", "success");

        assertEquals("Gmail 授权已完成，正在刷新账号状态。", message);
    }

    @Test
    public void fallsBackForUnknownOrFailedStatus() {
        assertEquals(
                "calendar 授权流程已返回，正在刷新账号状态。",
                ComposioCallbackPayload.statusMessage("calendar", "")
        );
        assertEquals(
                "Gmail 授权未完成，请重新尝试。",
                ComposioCallbackPayload.statusMessage("gmail", "error")
        );
    }

    @Test
    public void identifiesAssistantOwnedGmailCallbackWithoutReadingAnyToken() {
        assertEquals(
                "nomi_gmail_primary",
                ComposioCallbackPayload.assistantIdentityId("nomi_gmail_primary")
        );
        assertEquals("", ComposioCallbackPayload.assistantIdentityId("user_gmail_primary"));
        assertEquals("", ComposioCallbackPayload.assistantIdentityId(null));
    }
}
