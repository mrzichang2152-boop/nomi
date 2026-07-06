package com.par.assistant.android;

import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.net.Proxy;

import org.junit.Test;

public final class NomiHttpClientsTest {
    @Test
    public void privateCloudBuilderBypassesSystemHttpProxy() {
        assertSame(Proxy.NO_PROXY, NomiHttpClients.privateCloudBuilder().build().proxy());
    }

    @Test
    public void privateCloudClientsUseNoProxyFactory() throws Exception {
        assertUsesNoProxyFactory("AssistantApiClient.java");
        assertUsesNoProxyFactory("RealtimeClient.java");
        assertUsesNoProxyFactory("StreamingAsrClient.java");
    }

    private void assertUsesNoProxyFactory(String fileName) throws Exception {
        String source = new String(
                Files.readAllBytes(Path.of("src/main/java/com/par/assistant/android/" + fileName)),
                StandardCharsets.UTF_8
        );

        assertTrue(fileName + " must use NomiHttpClients.privateCloudBuilder()", source.contains("NomiHttpClients.privateCloudBuilder()"));
    }
}
