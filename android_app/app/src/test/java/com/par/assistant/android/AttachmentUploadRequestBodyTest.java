package com.par.assistant.android;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

import org.junit.Test;

import okhttp3.MediaType;
import okio.Buffer;

public final class AttachmentUploadRequestBodyTest {
    @Test
    public void streamsLargeInputInChunksReportsProgressClosesAndPreservesBytes() throws Exception {
        byte[] content = new byte[192 * 1024 + 17];
        for (int index = 0; index < content.length; index++) content[index] = (byte) (index % 251);
        TrackingInputStream input = new TrackingInputStream(content);
        List<Long> progress = new ArrayList<>();
        AttachmentUploadRequestBody body = new AttachmentUploadRequestBody(
                MediaType.get("application/pdf"),
                content.length,
                () -> input,
                16 * 1024,
                (written, total) -> progress.add(written),
                () -> false
        );
        Buffer sink = new Buffer();

        body.writeTo(sink);

        byte[] uploaded = sink.readByteArray();
        assertArrayEquals(content, uploaded);
        assertTrue("large input must be read more than once", input.readCalls > 1);
        assertTrue("progress must be incremental", progress.size() > 1);
        assertEquals(Long.valueOf(content.length), progress.get(progress.size() - 1));
        assertTrue(input.closed);
        assertArrayEquals(
                MessageDigest.getInstance("SHA-256").digest(content),
                MessageDigest.getInstance("SHA-256").digest(uploaded)
        );
    }

    @Test
    public void cancellationStopsStreamingAndStillClosesInput() throws Exception {
        byte[] content = new byte[96 * 1024];
        TrackingInputStream input = new TrackingInputStream(content);
        AtomicBoolean cancelled = new AtomicBoolean(false);
        AttachmentUploadRequestBody body = new AttachmentUploadRequestBody(
                MediaType.get("application/octet-stream"),
                content.length,
                () -> input,
                8 * 1024,
                (written, total) -> {
                    if (written >= 16 * 1024) cancelled.set(true);
                },
                cancelled::get
        );

        try {
            body.writeTo(new Buffer());
            fail("expected cancellation");
        } catch (IOException expected) {
            assertTrue(expected.getMessage().contains("cancel"));
        }
        assertTrue(input.closed);
    }

    private static final class TrackingInputStream extends ByteArrayInputStream {
        int readCalls;
        boolean closed;

        TrackingInputStream(byte[] content) {
            super(content);
        }

        @Override
        public synchronized int read(byte[] buffer, int offset, int length) {
            readCalls += 1;
            return super.read(buffer, offset, length);
        }

        @Override
        public void close() throws IOException {
            closed = true;
            super.close();
        }
    }
}
