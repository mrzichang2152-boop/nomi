package com.par.assistant.android;

import static org.junit.Assert.assertEquals;

import java.util.List;

import org.junit.Test;

public final class FloatingChatContextTest {
    @Test
    public void snapshotsRecentTurnsInOrderForShortReplyContext() {
        FloatingChatContext context = new FloatingChatContext();
        context.addAssistant("需要我帮你核对成本与利润率数据吗？");
        context.addUser("需要");

        List<FloatingChatContext.Turn> snapshot = context.snapshot(8);

        assertEquals(2, snapshot.size());
        assertEquals("assistant", snapshot.get(0).role);
        assertEquals("需要我帮你核对成本与利润率数据吗？", snapshot.get(0).content);
        assertEquals("user", snapshot.get(1).role);
        assertEquals("需要", snapshot.get(1).content);
    }
}
