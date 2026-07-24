package com.par.assistant.android;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class FileViewerUrlsTest {
    private static final String ATTACHMENT =
            "/api/chat/attachments/11111111-1111-4111-8111-111111111111/content";
    private static final String ARTIFACT = "/api/artifacts/task_2026-07-15_A1/download";

    @Test
    public void onlyNomiOriginalFileEndpointsCanBeViewed() {
        assertTrue(FileViewerUrls.isAllowedSource(ATTACHMENT));
        assertTrue(FileViewerUrls.isAllowedSource(ARTIFACT));
        assertFalse(FileViewerUrls.isAllowedSource("https://evil.test/file.pdf"));
        assertFalse(FileViewerUrls.isAllowedSource("/api/login"));
        assertFalse(FileViewerUrls.isAllowedSource(ATTACHMENT.replace("/content", "/preview")));
        assertFalse(FileViewerUrls.isAllowedSource("content://downloads/file.pdf"));
    }

    @Test
    public void viewerUrlUsesRelativeSourceAndNeverEmbedsPassword() {
        String url = FileViewerUrls.viewerUrl(
                "https://nomi.test/",
                "https://nomi.test" + ARTIFACT + "?password=secret",
                "季度 汇报.pptx",
                "application/test"
        );

        assertTrue(url.startsWith("https://nomi.test/viewer?"));
        assertTrue(url.contains("source=%2Fapi%2Fartifacts%2Ftask_2026-07-15_A1%2Fdownload"));
        assertTrue(url.contains("filename=%E5%AD%A3%E5%BA%A6%20%E6%B1%87%E6%8A%A5.pptx"));
        assertFalse(url.contains("secret"));
        assertFalse(url.contains("password"));
    }

    @Test
    public void externalOrCrossOriginSourceReturnsEmptyUrl() {
        assertEquals("", FileViewerUrls.viewerUrl(
                "https://nomi.test",
                "https://evil.test/private.pdf",
                "private.pdf",
                "application/pdf"
        ));
    }

    @Test
    public void trustedRelativeViewerUrlIsNormalizedBeforeWebViewLoadsIt() {
        String relative = "/viewer?source=%2Fapi%2Fartifacts%2Ftask_A1%2Fdownload"
                + "&filename=deck.pptx";

        assertEquals(
                "https://nomi.test/viewer?source=%2Fapi%2Fartifacts%2Ftask_A1%2Fdownload"
                        + "&filename=deck.pptx",
                FileViewerUrls.normalizeTrustedViewerUrl("https://nomi.test/workbench", relative)
        );
        assertEquals("", FileViewerUrls.normalizeTrustedViewerUrl(
                "https://nomi.test",
                "https://evil.test/viewer?source=%2Fapi%2Fartifacts%2Ftask_A1%2Fdownload"
        ));
    }
}
