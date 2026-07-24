package com.par.assistant.android;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public final class OriginalFileDownloadTest {
    @Test
    public void resolvesAllowedArtifactAndAttachmentSourcesAgainstPrivateCloudOrigin() {
        assertEquals(
                "http://206.119.171.141/api/artifacts/artifact_123/download",
                OriginalFileDownload.resolveDownloadUrl(
                        "http://206.119.171.141",
                        "/api/artifacts/artifact_123/download"
                )
        );
        assertEquals(
                "https://nomi.example/api/chat/attachments/550e8400-e29b-41d4-a716-446655440000/content",
                OriginalFileDownload.resolveDownloadUrl(
                        "https://nomi.example/app",
                        "/api/chat/attachments/550e8400-e29b-41d4-a716-446655440000/content"
                )
        );
    }

    @Test
    public void rejectsCrossOriginTraversalAndUnsupportedSources() {
        assertEquals("", OriginalFileDownload.resolveDownloadUrl(
                "https://nomi.example",
                "https://evil.example/api/artifacts/a/download"
        ));
        assertEquals("", OriginalFileDownload.resolveDownloadUrl(
                "https://nomi.example",
                "/api/artifacts/../secret/download"
        ));
        assertEquals("", OriginalFileDownload.resolveDownloadUrl(
                "https://nomi.example",
                "/api/admin/export"
        ));
    }

    @Test
    public void sanitizesFilenameAndMimeTypeForStorage() {
        assertEquals("slides.pptx", OriginalFileDownload.safeFilename("../../slides.pptx"));
        assertEquals("Nomi-file", OriginalFileDownload.safeFilename("\r\n"));
        assertEquals(
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                OriginalFileDownload.safeMimeType(
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                )
        );
        assertEquals("text/plain", OriginalFileDownload.safeMimeType("text/plain; charset=utf-8"));
        assertEquals("application/octet-stream", OriginalFileDownload.safeMimeType("text/plain\r\nX-Bad: 1"));
    }
}
