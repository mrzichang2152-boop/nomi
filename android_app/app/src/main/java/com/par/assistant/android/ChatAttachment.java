package com.par.assistant.android;

final class ChatAttachment {
    final String attachmentId;
    final String clientUploadId;
    final String filename;
    final String mimeType;
    final long byteSize;
    final String status;
    final String kind;
    final String previewUrl;
    final String contentUrl;
    final String errorMessage;

    ChatAttachment(
            String attachmentId,
            String clientUploadId,
            String filename,
            String mimeType,
            long byteSize,
            String status,
            String kind,
            String previewUrl,
            String contentUrl,
            String errorMessage
    ) {
        this.attachmentId = clean(attachmentId);
        this.clientUploadId = clean(clientUploadId);
        this.filename = clean(filename);
        this.mimeType = clean(mimeType);
        this.byteSize = Math.max(0L, byteSize);
        this.status = clean(status);
        this.kind = clean(kind);
        this.previewUrl = clean(previewUrl);
        this.contentUrl = clean(contentUrl);
        this.errorMessage = clean(errorMessage);
    }

    boolean isReady() {
        return "ready".equals(status);
    }

    boolean isFailed() {
        return "failed".equals(status) || "rejected".equals(status);
    }

    private static String clean(String value) {
        return value == null ? "" : value.trim();
    }
}
