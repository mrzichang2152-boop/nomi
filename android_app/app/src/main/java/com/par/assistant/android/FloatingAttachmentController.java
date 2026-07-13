package com.par.assistant.android;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

final class FloatingAttachmentController {
    static final int MAX_ATTACHMENTS = 8;
    static final long MAX_TOTAL_BYTES = 64L * 1024L * 1024L;
    private static final int MAX_STATUS_POLLS = 240;

    interface Progress {
        void onProgress(long written, long total);
    }

    interface Gateway {
        ChatAttachment upload(AttachmentDraft draft, Progress progress) throws Exception;
        ChatAttachment status(String attachmentId) throws Exception;
        ChatAttachment retry(String attachmentId) throws Exception;
        void delete(String attachmentId) throws Exception;
    }

    interface Sleeper {
        void sleep(long millis) throws InterruptedException;
    }

    static final class Snapshot {
        final List<AttachmentDraft> drafts;
        final boolean restoreKeyboard;

        Snapshot(List<AttachmentDraft> drafts, boolean restoreKeyboard) {
            this.drafts = drafts;
            this.restoreKeyboard = restoreKeyboard;
        }
    }

    private final Gateway gateway;
    private final Sleeper sleeper;
    private final List<AttachmentDraft> drafts = new ArrayList<>();
    private final Set<String> cancelledDrafts = ConcurrentHashMap.newKeySet();
    private boolean pickerOpen;
    private boolean restoreKeyboard;

    FloatingAttachmentController(Gateway gateway, Sleeper sleeper) {
        this(gateway, sleeper, null);
    }

    FloatingAttachmentController(Gateway gateway, Sleeper sleeper, Snapshot snapshot) {
        this.gateway = gateway;
        this.sleeper = sleeper;
        if (snapshot != null) {
            for (AttachmentDraft draft : snapshot.drafts) drafts.add(draft.copy());
            restoreKeyboard = snapshot.restoreKeyboard;
        }
    }

    synchronized void add(AttachmentDraft draft) {
        if (draft == null) return;
        if (drafts.size() >= MAX_ATTACHMENTS) throw new IllegalArgumentException("最多选择 8 个附件");
        long nextTotal = Math.max(0L, draft.byteSize);
        for (AttachmentDraft item : drafts) nextTotal += Math.max(0L, item.byteSize);
        if (nextTotal > MAX_TOTAL_BYTES) throw new IllegalArgumentException("附件总大小不能超过 64MB");
        for (AttachmentDraft item : drafts) {
            if (item.clientUploadId.equals(draft.clientUploadId)) return;
        }
        drafts.add(draft);
    }

    synchronized List<AttachmentDraft> drafts() {
        List<AttachmentDraft> copy = new ArrayList<>();
        for (AttachmentDraft draft : drafts) copy.add(draft.copy());
        return List.copyOf(copy);
    }

    void prepareForSend() throws Exception {
        List<AttachmentDraft> current;
        synchronized (this) {
            current = new ArrayList<>(drafts);
        }
        for (AttachmentDraft draft : current) {
            try {
                if (cancelledDrafts.contains(draft.clientUploadId)) throw new IllegalStateException("附件上传已取消");
                if (draft.isReady()) continue;
                if (draft.isFailed()) throw new IllegalStateException("附件处理失败，请重试或移除");
                if (draft.isPendingUpload()) {
                    ChatAttachment uploaded = gateway.upload(draft, draft::markProgress);
                    draft.markUploaded(uploaded);
                }
                ChatAttachment state = draft.remote();
                for (int attempt = 0; state != null && !state.isReady() && !state.isFailed() && attempt < MAX_STATUS_POLLS; attempt++) {
                    if (cancelledDrafts.contains(draft.clientUploadId)) throw new IllegalStateException("附件上传已取消");
                    sleeper.sleep(attempt == 0 ? 0L : 500L);
                    state = gateway.status(state.attachmentId);
                    draft.markUploaded(state);
                }
                if (!draft.isReady()) throw new IllegalStateException(draft.errorMessage().isEmpty() ? "附件仍在处理中" : draft.errorMessage());
            } catch (Exception error) {
                if (!draft.isFailed()) draft.markFailed(error.getMessage());
                throw error;
            }
        }
    }

    synchronized boolean canSend(String text) {
        if (drafts.isEmpty()) return text != null && !text.trim().isEmpty();
        for (AttachmentDraft draft : drafts) if (!draft.isReady()) return false;
        return true;
    }

    synchronized List<String> readyAttachmentIds() {
        List<String> ids = new ArrayList<>();
        for (AttachmentDraft draft : drafts) {
            if (draft.isReady()) ids.add(draft.remote().attachmentId);
        }
        return List.copyOf(ids);
    }

    synchronized void retry(String clientUploadId) throws Exception {
        AttachmentDraft draft = find(clientUploadId);
        if (draft == null) return;
        if (draft.remote() == null) {
            draft.resetForRetry();
            return;
        }
        draft.markUploaded(gateway.retry(draft.remote().attachmentId));
    }

    synchronized void remove(String clientUploadId) {
        AttachmentDraft draft = find(clientUploadId);
        if (draft == null) return;
        drafts.remove(draft);
        cancelledDrafts.remove(clientUploadId);
        if (draft.remote() != null && !draft.remote().attachmentId.isEmpty()) {
            try {
                gateway.delete(draft.remote().attachmentId);
            } catch (Exception ignored) {
                // Local removal must remain responsive; server lifecycle cleanup is idempotent.
            }
        }
    }

    synchronized void clearAfterSend() {
        drafts.clear();
        cancelledDrafts.clear();
    }

    void cancel(String clientUploadId) {
        if (clientUploadId != null && !clientUploadId.trim().isEmpty()) cancelledDrafts.add(clientUploadId.trim());
    }

    synchronized void beginPicker(boolean keyboardVisible) {
        pickerOpen = true;
        restoreKeyboard = keyboardVisible;
    }

    synchronized void cancelPicker() {
        pickerOpen = false;
    }

    synchronized void completePicker() {
        pickerOpen = false;
    }

    synchronized boolean isPickerOpen() {
        return pickerOpen;
    }

    synchronized boolean shouldRestoreKeyboard() {
        return restoreKeyboard;
    }

    synchronized Snapshot snapshot() {
        List<AttachmentDraft> copy = new ArrayList<>();
        for (AttachmentDraft draft : drafts) copy.add(draft.copy());
        return new Snapshot(copy, restoreKeyboard);
    }

    private AttachmentDraft find(String clientUploadId) {
        for (AttachmentDraft draft : drafts) {
            if (draft.clientUploadId.equals(clientUploadId)) return draft;
        }
        return null;
    }
}
