package com.par.assistant.android;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;

import org.junit.Test;

public final class FloatingAttachmentControllerTest {
    @Test
    public void uploadsOncePollsUntilReadyAndPreservesOrderedIds() throws Exception {
        FakeGateway gateway = new FakeGateway();
        gateway.statuses.add(attachment("server-1", "processing"));
        gateway.statuses.add(attachment("server-1", "ready"));
        FloatingAttachmentController controller = new FloatingAttachmentController(gateway, millis -> { });
        controller.add(AttachmentDraft.create("content://1", "一.pdf", "application/pdf", 4, "local-1"));

        controller.prepareForSend();
        controller.prepareForSend();

        assertEquals(1, gateway.uploadCalls);
        assertEquals(List.of("server-1"), controller.readyAttachmentIds());
        assertTrue(controller.canSend(""));
    }

    @Test
    public void pickerCancellationAndRecreationKeepDraftAndKeyboardIntent() {
        FakeGateway gateway = new FakeGateway();
        FloatingAttachmentController first = new FloatingAttachmentController(gateway, millis -> { });
        first.add(AttachmentDraft.create("content://1", "brief.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 10, "local-1"));
        first.beginPicker(true);
        first.cancelPicker();

        FloatingAttachmentController restored = new FloatingAttachmentController(gateway, millis -> { }, first.snapshot());

        assertEquals(1, restored.drafts().size());
        assertEquals("local-1", restored.drafts().get(0).clientUploadId);
        assertTrue(restored.shouldRestoreKeyboard());
        assertFalse(restored.isPickerOpen());
    }

    @Test
    public void failedDraftBlocksSendUntilRetrySucceedsAndRemoveWorks() throws Exception {
        FakeGateway gateway = new FakeGateway();
        FloatingAttachmentController controller = new FloatingAttachmentController(gateway, millis -> { });
        AttachmentDraft draft = AttachmentDraft.create("content://1", "bad.pdf", "application/pdf", 4, "local-1");
        draft.markFailed("parse_failed");
        controller.add(draft);

        assertFalse(controller.canSend("hello"));
        gateway.retryResult = attachment("server-1", "ready");
        draft.markUploaded(attachment("server-1", "failed"));
        controller.retry("local-1");
        assertTrue(controller.canSend("hello"));
        controller.remove("local-1");
        assertEquals(0, controller.drafts().size());
    }

    @Test
    public void cancelledDraftDoesNotStartOrRepeatUpload() {
        FakeGateway gateway = new FakeGateway();
        FloatingAttachmentController controller = new FloatingAttachmentController(gateway, millis -> { });
        controller.add(AttachmentDraft.create("content://1", "cancel.pdf", "application/pdf", 4, "local-cancel"));
        controller.cancel("local-cancel");

        try {
            controller.prepareForSend();
        } catch (Exception expected) {
            assertTrue(expected.getMessage().contains("取消"));
        }

        assertEquals(0, gateway.uploadCalls);
    }

    private static ChatAttachment attachment(String id, String status) {
        return new ChatAttachment(id, "local-1", "a.pdf", "application/pdf", 4, status, "document", "", "/content", "");
    }

    private static final class FakeGateway implements FloatingAttachmentController.Gateway {
        int uploadCalls;
        ArrayDeque<ChatAttachment> statuses = new ArrayDeque<>();
        ChatAttachment retryResult;
        List<String> deleted = new ArrayList<>();

        @Override
        public ChatAttachment upload(AttachmentDraft draft, FloatingAttachmentController.Progress progress) {
            uploadCalls += 1;
            return attachment("server-1", "processing");
        }

        @Override
        public ChatAttachment status(String attachmentId) {
            return statuses.removeFirst();
        }

        @Override
        public ChatAttachment retry(String attachmentId) {
            return retryResult;
        }

        @Override
        public void delete(String attachmentId) {
            deleted.add(attachmentId);
        }
    }
}
