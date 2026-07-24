package com.par.assistant.android;

import static org.junit.Assert.assertEquals;

import java.util.List;

import org.junit.Test;

public final class LocalChatHistoryStoreTest {
    @Test
    public void mergeWithRemoteAppendsOnlyRemoteSuffixAfterCachedWindow() {
        List<ChatHistoryMessage> local = List.of(
                new ChatHistoryMessage("user", "2"),
                new ChatHistoryMessage("assistant", "3"),
                new ChatHistoryMessage("user", "4")
        );
        List<ChatHistoryMessage> remote = List.of(
                new ChatHistoryMessage("assistant", "1"),
                new ChatHistoryMessage("user", "2"),
                new ChatHistoryMessage("assistant", "3"),
                new ChatHistoryMessage("user", "4"),
                new ChatHistoryMessage("assistant", "5"),
                new ChatHistoryMessage("user", "6")
        );

        List<ChatHistoryMessage> merged = LocalChatHistoryStore.mergeWithRemote(local, remote, 80);

        assertEquals(List.of("2", "3", "4", "5", "6"), contents(merged));
    }

    @Test
    public void mergeWithRemoteFallsBackToRemoteWhenNoReliableOverlapExists() {
        List<ChatHistoryMessage> local = List.of(
                new ChatHistoryMessage("user", "local-only")
        );
        List<ChatHistoryMessage> remote = List.of(
                new ChatHistoryMessage("user", "server-1"),
                new ChatHistoryMessage("assistant", "server-2")
        );

        List<ChatHistoryMessage> merged = LocalChatHistoryStore.mergeWithRemote(local, remote, 80);

        assertEquals(List.of("server-1", "server-2"), contents(merged));
    }

    @Test
    public void mergeWithRemoteKeepsMostRecentMessagesWithinLimit() {
        List<ChatHistoryMessage> local = List.of(
                new ChatHistoryMessage("user", "2"),
                new ChatHistoryMessage("assistant", "3")
        );
        List<ChatHistoryMessage> remote = List.of(
                new ChatHistoryMessage("assistant", "1"),
                new ChatHistoryMessage("user", "2"),
                new ChatHistoryMessage("assistant", "3"),
                new ChatHistoryMessage("user", "4"),
                new ChatHistoryMessage("assistant", "5")
        );

        List<ChatHistoryMessage> merged = LocalChatHistoryStore.mergeWithRemote(local, remote, 3);

        assertEquals(List.of("3", "4", "5"), contents(merged));
    }

    @Test
    public void mergeWithRemoteUsesStableIdsBeforeContentOverlap() {
        List<ChatHistoryMessage> local = List.of(
                new ChatHistoryMessage("local-1", "2026-05-29T08:00:00+00:00", "user", "重复内容"),
                new ChatHistoryMessage("local-2", "2026-05-29T08:00:01+00:00", "assistant", "旧回复")
        );
        List<ChatHistoryMessage> remote = List.of(
                new ChatHistoryMessage("remote-1", "2026-05-29T08:00:00+00:00", "user", "重复内容"),
                new ChatHistoryMessage("remote-2", "2026-05-29T08:00:02+00:00", "assistant", "新回复")
        );

        List<ChatHistoryMessage> merged = LocalChatHistoryStore.mergeWithRemote(local, remote, 80);

        assertEquals(List.of("remote-1", "remote-2"), ids(merged));
        assertEquals(List.of("重复内容", "新回复"), contents(merged));
    }

    @Test
    public void mergeWithRemoteHydratesLegacyLocalCacheWithRemoteIds() {
        List<ChatHistoryMessage> local = List.of(
                new ChatHistoryMessage("user", "2"),
                new ChatHistoryMessage("assistant", "3"),
                new ChatHistoryMessage("user", "4")
        );
        List<ChatHistoryMessage> remote = List.of(
                new ChatHistoryMessage("remote-1", "2026-05-29T07:59:59+00:00", "assistant", "1"),
                new ChatHistoryMessage("remote-2", "2026-05-29T08:00:00+00:00", "user", "2"),
                new ChatHistoryMessage("remote-3", "2026-05-29T08:00:01+00:00", "assistant", "3"),
                new ChatHistoryMessage("remote-4", "2026-05-29T08:00:02+00:00", "user", "4"),
                new ChatHistoryMessage("remote-5", "2026-05-29T08:00:03+00:00", "assistant", "5")
        );

        List<ChatHistoryMessage> merged = LocalChatHistoryStore.mergeWithRemote(local, remote, 80);

        assertEquals(List.of("remote-2", "remote-3", "remote-4", "remote-5"), ids(merged));
        assertEquals(List.of("2", "3", "4", "5"), contents(merged));
    }

    @Test
    public void mergeWithRemotePreservesLocalUnsyncedSuffixAfterStableIdOverlap() {
        List<ChatHistoryMessage> local = List.of(
                new ChatHistoryMessage("remote-1", "2026-05-29T08:00:00+00:00", "user", "1"),
                new ChatHistoryMessage("remote-2", "2026-05-29T08:00:01+00:00", "assistant", "2"),
                new ChatHistoryMessage("user", "刚刚又问了一句")
        );
        List<ChatHistoryMessage> remote = List.of(
                new ChatHistoryMessage("remote-1", "2026-05-29T08:00:00+00:00", "user", "1"),
                new ChatHistoryMessage("remote-2", "2026-05-29T08:00:01+00:00", "assistant", "2"),
                new ChatHistoryMessage("remote-3", "2026-05-29T08:00:02+00:00", "assistant", "3")
        );

        List<ChatHistoryMessage> merged = LocalChatHistoryStore.mergeWithRemote(local, remote, 80);

        assertEquals(List.of("remote-1", "remote-2", "remote-3", ""), ids(merged));
        assertEquals(List.of("1", "2", "3", "刚刚又问了一句"), contents(merged));
    }

    private static List<String> contents(List<ChatHistoryMessage> messages) {
        return messages.stream().map(message -> message.content).toList();
    }

    private static List<String> ids(List<ChatHistoryMessage> messages) {
        return messages.stream().map(message -> message.id).toList();
    }
}
