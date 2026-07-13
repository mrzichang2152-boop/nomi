package com.par.assistant.android;

import java.util.UUID;

final class AttachmentDraft {
    final String uri;
    final String filename;
    final String mimeType;
    final long byteSize;
    final String clientUploadId;
    private ChatAttachment remote;
    private int progressPercent;
    private String localError = "";

    private AttachmentDraft(String uri, String filename, String mimeType, long byteSize, String clientUploadId) {
        this.uri = value(uri);
        this.filename = value(filename).isEmpty() ? "attachment" : value(filename);
        this.mimeType = value(mimeType).isEmpty() ? "application/octet-stream" : value(mimeType);
        this.byteSize = byteSize < 0L ? -1L : byteSize;
        this.clientUploadId = value(clientUploadId).isEmpty() ? UUID.randomUUID().toString() : value(clientUploadId);
    }

    static AttachmentDraft create(String uri, String filename, String mimeType, long byteSize, String clientUploadId) {
        return new AttachmentDraft(uri, filename, mimeType, byteSize, clientUploadId);
    }

    AttachmentDraft copy() {
        AttachmentDraft copy = create(uri, filename, mimeType, byteSize, clientUploadId);
        copy.remote = remote;
        copy.progressPercent = progressPercent;
        copy.localError = localError;
        return copy;
    }

    void markProgress(long written, long total) {
        if (total <= 0) return;
        progressPercent = (int) Math.min(100L, Math.max(0L, written * 100L / total));
    }

    void markUploaded(ChatAttachment attachment) {
        remote = attachment;
        localError = attachment == null ? "upload_failed" : attachment.errorMessage;
        if (attachment != null && attachment.isReady()) progressPercent = 100;
    }

    void markFailed(String message) {
        localError = value(message).isEmpty() ? "upload_failed" : value(message);
    }

    void resetForRetry() {
        localError = "";
        if (remote != null && remote.isFailed()) remote = null;
        progressPercent = 0;
    }

    ChatAttachment remote() {
        return remote;
    }

    int progressPercent() {
        return progressPercent;
    }

    String errorMessage() {
        if (!localError.isEmpty()) return localError;
        return remote == null ? "" : remote.errorMessage;
    }

    boolean isPendingUpload() {
        return remote == null && localError.isEmpty();
    }

    boolean isReady() {
        return remote != null && remote.isReady();
    }

    boolean isFailed() {
        return !localError.isEmpty() || (remote != null && remote.isFailed());
    }

    private static String value(String input) {
        return input == null ? "" : input.trim();
    }
}
