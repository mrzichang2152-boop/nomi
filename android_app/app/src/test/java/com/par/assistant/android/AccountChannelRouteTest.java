package com.par.assistant.android;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class AccountChannelRouteTest {
    @Test
    public void routesGoogleToolkitsThroughComposioConnect() {
        AccountChannelRoute route = AccountChannelRoute.forSource("gmail");

        assertEquals(AccountChannelRoute.Kind.COMPOSIO_CONNECT, route.kind());
        assertEquals("gmail", route.composioToolkitSlug());
        assertTrue(route.requiresUnobstructedExternalAuth());
    }

    @Test
    public void routesBrowserOnlyChannelsThroughRemoteBrowser() {
        AccountChannelRoute route = AccountChannelRoute.forSource("whatsapp");

        assertEquals(AccountChannelRoute.Kind.REMOTE_BROWSER, route.kind());
        assertTrue(route.composioToolkitSlug().isEmpty());
        assertEquals("whatsapp", route.remoteBrowserSource());
        assertEquals(false, route.requiresUnobstructedExternalAuth());
    }

    @Test
    public void routesTelegramThroughRemoteBrowserWithConcreteSource() {
        AccountChannelRoute route = AccountChannelRoute.forSource("telegram");

        assertEquals(AccountChannelRoute.Kind.REMOTE_BROWSER, route.kind());
        assertEquals("telegram", route.remoteBrowserSource());
    }

    @Test
    public void routesLinkedInThroughRemoteBrowserWithConcreteSource() {
        AccountChannelRoute route = AccountChannelRoute.forSource("linkedin");

        assertEquals(AccountChannelRoute.Kind.REMOTE_BROWSER, route.kind());
        assertEquals("linkedin", route.remoteBrowserSource());
    }

    @Test
    public void healthyComposioChannelDoesNotOpenAuthorizationAgain() {
        AccountChannelRoute route = AccountChannelRoute.forSource("gmail");

        assertEquals(
                false,
                route.shouldOpenForStatus(new CollectorStatus("gmail", true, false, "healthy"))
        );
        assertEquals(
                true,
                route.shouldOpenForStatus(new CollectorStatus("gmail", true, false, "degraded"))
        );
    }

    @Test
    public void connectedComposioAuthorizationDoesNotDependOnBrowserCollectorHealth() {
        AccountChannelRoute route = AccountChannelRoute.forSource("gmail");
        CollectorStatus status = new CollectorStatus(
                "gmail",
                true,
                false,
                "degraded",
                "api_connected",
                "logged_out",
                "degraded",
                "API 已连接",
                "浏览器未登录，但 Gmail API 可用。"
        );

        assertEquals(false, route.shouldOpenForStatus(status));
    }

    @Test
    public void loggedInRemoteBrowserChannelDoesNotOpenLoginAgainWhenCollectionIsDegraded() {
        AccountChannelRoute route = AccountChannelRoute.forSource("telegram");
        CollectorStatus status = new CollectorStatus(
                "telegram",
                true,
                false,
                "degraded",
                "browser_required",
                "logged_in",
                "degraded",
                "已登录 / 采集异常",
                "Telegram Web 已登录，但当前可见页面解析异常。"
        );

        assertEquals(false, route.shouldOpenForStatus(status));
    }

    @Test
    public void remoteBrowserDisplayLabelUsesLoginStateBeforeCollectionHealth() {
        CollectorStatus status = new CollectorStatus(
                "telegram",
                true,
                false,
                "degraded",
                "browser_required",
                "logged_in",
                "degraded",
                "",
                ""
        );

        assertEquals("已登录 / 采集异常", status.displayLabel(true));
    }
}
