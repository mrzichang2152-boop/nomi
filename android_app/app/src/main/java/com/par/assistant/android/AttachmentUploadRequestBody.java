package com.par.assistant.android;

import android.content.ContentResolver;
import android.net.Uri;

import java.io.IOException;
import java.io.InputStream;
import java.util.function.BooleanSupplier;

import okhttp3.MediaType;
import okhttp3.RequestBody;
import okio.BufferedSink;

final class AttachmentUploadRequestBody extends RequestBody {
    interface StreamFactory {
        InputStream open() throws IOException;
    }

    interface ProgressListener {
        void onProgress(long bytesWritten, long totalBytes);
    }

    private final MediaType mediaType;
    private final long byteSize;
    private final StreamFactory streamFactory;
    private final int bufferSize;
    private final ProgressListener progressListener;
    private final BooleanSupplier cancelled;

    AttachmentUploadRequestBody(
            MediaType mediaType,
            long byteSize,
            StreamFactory streamFactory,
            int bufferSize,
            ProgressListener progressListener,
            BooleanSupplier cancelled
    ) {
        if (streamFactory == null) throw new IllegalArgumentException("streamFactory is required");
        this.mediaType = mediaType;
        this.byteSize = byteSize;
        this.streamFactory = streamFactory;
        this.bufferSize = Math.max(4 * 1024, bufferSize);
        this.progressListener = progressListener == null ? (written, total) -> { } : progressListener;
        this.cancelled = cancelled == null ? () -> false : cancelled;
    }

    static AttachmentUploadRequestBody forUri(
            ContentResolver resolver,
            Uri uri,
            String mimeType,
            long byteSize,
            ProgressListener progressListener,
            BooleanSupplier cancelled
    ) {
        return new AttachmentUploadRequestBody(
                MediaType.parse(mimeType == null ? "application/octet-stream" : mimeType),
                byteSize,
                () -> {
                    InputStream stream = resolver.openInputStream(uri);
                    if (stream == null) throw new IOException("attachment stream unavailable");
                    return stream;
                },
                64 * 1024,
                progressListener,
                cancelled
        );
    }

    @Override
    public MediaType contentType() {
        return mediaType;
    }

    @Override
    public long contentLength() {
        return byteSize;
    }

    @Override
    public void writeTo(BufferedSink sink) throws IOException {
        byte[] buffer = new byte[bufferSize];
        long written = 0L;
        try (InputStream input = streamFactory.open()) {
            while (true) {
                if (cancelled.getAsBoolean()) throw new IOException("attachment upload cancelled");
                int count = input.read(buffer, 0, buffer.length);
                if (count < 0) break;
                if (count == 0) continue;
                sink.write(buffer, 0, count);
                written += count;
                progressListener.onProgress(written, byteSize);
            }
        }
        if (byteSize >= 0 && written != byteSize) {
            throw new IOException("attachment size changed during upload");
        }
    }
}
