package com.par.assistant.core;

import java.util.Arrays;
import java.util.List;

public final class CoreLogicTest {
    public static void main(String[] args) {
        testNormalizesServerBaseUrl();
        testRejectsInvalidServerBaseUrl();
        testSuppressesInternalSuggestionText();
        testDedupesSuggestionIds();
        testFiltersAlreadySeenSuggestions();
        System.out.println("CoreLogicTest passed");
    }

    private static void testNormalizesServerBaseUrl() {
        ServerConfig config = ServerConfig.create("10.0.2.2:8080/", "secret");
        assertEquals("http://10.0.2.2:8080", config.baseUrl(), "adds http and strips trailing slash");

        ServerConfig https = ServerConfig.create("https://par.example.com///", "secret");
        assertEquals("https://par.example.com", https.baseUrl(), "preserves https and strips slashes");
    }

    private static void testRejectsInvalidServerBaseUrl() {
        assertThrows(() -> ServerConfig.create("", "secret"), "empty base url");
        assertThrows(() -> ServerConfig.create("ftp://par.example.com", "secret"), "unsupported scheme");
        assertThrows(() -> ServerConfig.create("http://par.example.com", ""), "empty password");
    }

    private static void testSuppressesInternalSuggestionText() {
        assertFalse(
                AssistantSuggestion.isDisplayableText(
                        "可能值得关注",
                        "user said to Nomi: 保利广场的安排缺什么信息？请只基于我的真实记录回答。"
                ),
                "internal Nomi user question should not display as proactive suggestion"
        );
        assertFalse(
                AssistantSuggestion.isDisplayableText("跟进近期安排", "这条信息可能需要跟进：(2) WhatsApp。"),
                "WhatsApp title badge should not display as appointment suggestion"
        );
        assertTrue(
                AssistantSuggestion.isDisplayableText("跟进近期安排", "这条信息可能需要跟进：明天下午3点半人民广场见，带合同。"),
                "real WhatsApp appointment should remain displayable"
        );
    }

    private static void testDedupesSuggestionIds() {
        SuggestionDeduper deduper = new SuggestionDeduper();
        assertTrue(deduper.shouldDisplay("sug-1"), "new suggestion should display");
        deduper.markDisplayed("sug-1");
        assertFalse(deduper.shouldDisplay("sug-1"), "displayed suggestion should not display again");
        assertTrue(deduper.shouldDisplay("sug-2"), "different suggestion should display");
    }

    private static void testFiltersAlreadySeenSuggestions() {
        SuggestionDeduper deduper = new SuggestionDeduper();
        deduper.markDisplayed("done");
        List<AssistantSuggestion> visible = deduper.filterNew(
                Arrays.asList(
                        new AssistantSuggestion("done", "旧建议", "已经展示", 0.9),
                        new AssistantSuggestion("fresh", "新建议", "需要展示", 0.7)
                )
        );
        assertEquals(1, visible.size(), "only fresh suggestion remains");
        assertEquals("fresh", visible.get(0).id(), "fresh suggestion id");
    }

    private static void assertEquals(Object expected, Object actual, String message) {
        if ((expected == null && actual != null) || (expected != null && !expected.equals(actual))) {
            throw new AssertionError(message + ": expected=" + expected + " actual=" + actual);
        }
    }

    private static void assertTrue(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static void assertFalse(boolean value, String message) {
        if (value) throw new AssertionError(message);
    }

    private static void assertThrows(Runnable runnable, String message) {
        try {
            runnable.run();
        } catch (IllegalArgumentException expected) {
            return;
        }
        throw new AssertionError(message + ": expected IllegalArgumentException");
    }
}
