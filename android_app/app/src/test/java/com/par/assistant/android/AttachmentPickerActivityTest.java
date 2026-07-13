package com.par.assistant.android;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;
import java.util.List;

import org.junit.Test;

public final class AttachmentPickerActivityTest {
    @Test
    public void pickerExposesOnlyApprovedProductMimeTypes() {
        List<String> types = Arrays.asList(AttachmentPickerActivity.APPROVED_MIME_TYPES);

        assertEquals(11, types.size());
        assertTrue(types.contains("image/png"));
        assertTrue(types.contains("image/jpeg"));
        assertTrue(types.contains("application/pdf"));
        assertTrue(types.contains("application/vnd.openxmlformats-officedocument.wordprocessingml.document"));
        assertTrue(types.contains("application/vnd.openxmlformats-officedocument.presentationml.presentation"));
        assertTrue(types.contains("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"));
        assertTrue(types.contains("text/csv"));
        assertTrue(types.contains("text/plain"));
        assertTrue(types.contains("text/markdown"));
    }

    @Test
    public void pickerRecoversApprovedMimeFromFilenameAndRejectsExecutables() {
        assertEquals("application/vnd.openxmlformats-officedocument.presentationml.presentation",
                AttachmentPickerActivity.approvedMimeType("培训方案.PPTX", "application/octet-stream"));
        assertEquals("image/jpeg", AttachmentPickerActivity.approvedMimeType("photo.jpeg", null));
        assertEquals("", AttachmentPickerActivity.approvedMimeType("installer.apk", "application/octet-stream"));
    }
}
