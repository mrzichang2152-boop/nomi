package com.par.assistant.android;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.util.List;

import org.junit.Test;

public final class LocalChatAttachmentHistoryTest {
    @Test
    public void serverHistoryReplacesStableLocalWindowAndKeepsOnlyIdlessPendingText() {
        List<ChatHistoryMessage> local = List.of(
                message("2", "user", "2", attachment("2", "a-2", "相同.pdf", 0)),
                message("3", "assistant", "3"),
                message("4", "user", "4"),
                message("deleted", "user", "服务端已删除", attachment("deleted", "local-only", "相同.pdf", 0)),
                message("", "user", "尚未提交", attachment("", "draft-only", "草稿.pdf", 0))
        );
        List<ChatHistoryMessage> remote = List.of(
                message("1", "assistant", "1"),
                message("2", "user", "2", attachment("2", "a-2", "相同.pdf", 0)),
                message("3", "assistant", "3"),
                message("4", "user", "4"),
                message("5", "user", "5", attachment("5", "a-5", "相同.pdf", 0)),
                message("6", "assistant", "6")
        );

        List<ChatHistoryMessage> merged = LocalChatHistoryStore.reconcile(local, remote, 80);

        assertEquals(List.of("1", "2", "3", "4", "5", "6", ""), ids(merged));
        assertEquals("尚未提交", merged.get(6).content);
        assertTrue(merged.get(6).attachments.isEmpty());
        assertFalse(ids(merged).contains("deleted"));
    }

    @Test
    public void attachmentsNeverCrossMessageBoundaryOrMatchByFilename() {
        ChatHistoryMessage local = message(
                "m-1",
                "user",
                "local",
                attachment("m-1", "local-id", "同名.pdf", 0)
        );
        ChatHistoryMessage remote = message(
                "m-1",
                "user",
                "server",
                attachment("m-1", "server-id", "同名.pdf", 0)
        );

        ChatHistoryMessage merged = LocalChatHistoryStore.reconcile(List.of(local), List.of(remote), 80).get(0);

        assertEquals("server", merged.content);
        assertEquals(List.of("server-id"), attachmentIds(merged));
    }

    @Test
    public void safeSerializationKeepsOrderedMetadataAndNoPrivateBytes() {
        ChatHistoryMessage message = message(
                "m-1",
                "user",
                "分析附件",
                attachment("m-1", "a-2", "第二.pdf", 1),
                attachment("m-1", "a-1", "第一.png", 0)
        );

        String serialized = LocalChatHistoryStore.serializeMessages(List.of(message));
        List<ChatHistoryMessage> restored = LocalChatHistoryStore.deserializeMessages(serialized, 80);

        assertEquals(List.of("a-1", "a-2"), attachmentIds(restored.get(0)));
        assertTrue(serialized.contains("preview_url"));
        assertTrue(serialized.contains("content_url"));
        assertFalse(serialized.contains("base64"));
        assertFalse(serialized.contains("original_bytes"));
        assertFalse(serialized.contains("storage_relative_path"));
        assertFalse(serialized.contains("file://"));
    }

    @Test
    public void mismatchedOwnerMetadataIsDiscarded() {
        ChatHistoryMessage message = message(
                "m-1",
                "user",
                "附件",
                attachment("some-other-message", "a-1", "越界.pdf", 0)
        );

        String serialized = LocalChatHistoryStore.serializeMessages(List.of(message));
        List<ChatHistoryMessage> restored = LocalChatHistoryStore.deserializeMessages(serialized, 80);

        assertTrue(restored.get(0).attachments.isEmpty());
    }

    @Test
    public void idlessPendingTextIsConsumedOnlyWhenServerHasMatchingOccurrence() {
        List<ChatHistoryMessage> local = List.of(
                message("", "user", "重复问题"),
                message("", "user", "重复问题"),
                message("", "assistant", "待发送回复")
        );
        List<ChatHistoryMessage> remote = List.of(
                message("server-user-1", "user", "重复问题")
        );

        List<ChatHistoryMessage> merged = LocalChatHistoryStore.reconcile(local, remote, 80);

        assertEquals(List.of("server-user-1", "", ""), ids(merged));
        assertEquals(List.of("重复问题", "重复问题", "待发送回复"),
                merged.stream().map(message -> message.content).toList());
    }

    private static ChatHistoryMessage message(
            String id,
            String role,
            String content,
            ChatHistoryAttachment... attachments
    ) {
        return new ChatHistoryMessage(id, "2026-07-13T10:00:00+08:00", role, content, List.of(attachments));
    }

    private static ChatHistoryAttachment attachment(String messageId, String attachmentId, String filename, int ordinal) {
        return new ChatHistoryAttachment(
                messageId,
                attachmentId,
                filename,
                filename.endsWith(".png") ? "image/png" : "application/pdf",
                128L,
                "ready",
                filename.endsWith(".png") ? "image" : "pdf",
                "/api/chat/attachments/" + attachmentId + "/preview",
                "/api/chat/attachments/" + attachmentId + "/content",
                ordinal
        );
    }

    private static List<String> ids(List<ChatHistoryMessage> messages) {
        return messages.stream().map(message -> message.id).toList();
    }

    private static List<String> attachmentIds(ChatHistoryMessage message) {
        return message.attachments.stream().map(attachment -> attachment.attachmentId).toList();
    }
}
