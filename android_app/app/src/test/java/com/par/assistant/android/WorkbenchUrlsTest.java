package com.par.assistant.android;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public final class WorkbenchUrlsTest {
    @Test
    public void chatUrlIncludesActiveConversationBeforeHash() {
        String url = WorkbenchUrls.chatUrl(
                "http://206.119.171.141",
                "11111111-1111-4111-8111-111111111111"
        );

        assertEquals(
                "http://206.119.171.141?conversation_id=11111111-1111-4111-8111-111111111111#chat",
                url
        );
    }

    @Test
    public void chatUrlKeepsBaseUrlWhenConversationIsMissing() {
        assertEquals("http://206.119.171.141#chat", WorkbenchUrls.chatUrl("http://206.119.171.141", ""));
    }

    @Test
    public void chatUrlAppendsConversationToExistingQuery() {
        String url = WorkbenchUrls.chatUrl("http://206.119.171.141/?mode=compact", "conv 1");

        assertEquals("http://206.119.171.141/?mode=compact&conversation_id=conv+1#chat", url);
    }
}
