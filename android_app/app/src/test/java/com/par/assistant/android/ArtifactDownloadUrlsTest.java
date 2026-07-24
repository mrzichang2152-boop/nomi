package com.par.assistant.android;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public final class ArtifactDownloadUrlsTest {
    @Test
    public void resolvesRelativeDownloadUrlAndAddsPasswordForExternalBrowser() {
        String url = ArtifactDownloadUrls.resolveForExternalBrowser(
                "http://206.119.171.141",
                "/api/artifacts/artifact_1/download",
                "par-dev"
        );

        assertEquals("http://206.119.171.141/api/artifacts/artifact_1/download?password=par-dev", url);
    }

    @Test
    public void preservesExistingQueryAndUrlEncodesPassword() {
        String url = ArtifactDownloadUrls.resolveForExternalBrowser(
                "http://example.test/",
                "/api/artifacts/artifact_1/download?version=1",
                "p a/r"
        );

        assertEquals("http://example.test/api/artifacts/artifact_1/download?version=1&password=p%20a%2Fr", url);
    }

    @Test
    public void leavesNonArtifactUrlsWithoutPassword() {
        String url = ArtifactDownloadUrls.resolveForExternalBrowser(
                "http://example.test",
                "https://files.example/download/demo.pptx",
                "secret"
        );

        assertEquals("https://files.example/download/demo.pptx", url);
    }
}
