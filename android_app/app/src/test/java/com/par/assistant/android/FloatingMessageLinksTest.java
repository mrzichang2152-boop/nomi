package com.par.assistant.android;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class FloatingMessageLinksTest {
    @Test
    public void detectsLinkedinJobDetailUrlsInsideMarkdownLinks() {
        String message = "[Backend Engineer](https://www.linkedin.com/jobs/view/4378789245/) 是一个推荐岗位";

        assertTrue(FloatingMessageLinks.containsWebUrl(message));
    }

    @Test
    public void ignoresPlainRecommendationTextWithoutUrls() {
        assertFalse(FloatingMessageLinks.containsWebUrl("这个岗位匹配 AI Agent，但还没有可打开链接。"));
    }

    @Test
    public void extractsFirstMarkdownUrlWithoutClosingParenthesis() {
        String message = "[Backend Engineer](https://www.linkedin.com/jobs/view/4378789245/)";

        assertTrue(FloatingMessageLinks.firstWebUrl(message).endsWith("/4378789245/"));
    }

    @Test
    public void recognizesLinkedinJobDetailUrlsForManagedBrowserRouting() {
        assertTrue(FloatingMessageLinks.isLinkedInJobDetailUrl("https://www.linkedin.com/jobs/view/4378789245/"));
        assertTrue(FloatingMessageLinks.isLinkedInJobDetailUrl("https://www.linkedin.com/jobs/view/4378789245/?trackingId=abc"));
        assertFalse(FloatingMessageLinks.isLinkedInJobDetailUrl("https://www.linkedin.com/jobs/search/?currentJobId=4378789245"));
        assertFalse(FloatingMessageLinks.isLinkedInJobDetailUrl("https://evil.example/jobs/view/4378789245/"));
    }
}
