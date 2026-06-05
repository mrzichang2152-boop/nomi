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
}
