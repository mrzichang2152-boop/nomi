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

    @Test
    public void snapshotsDeltaByCharacterBudgetInsteadOfFixedTurnCount() {
        FloatingChatContext context = new FloatingChatContext();
        for (int index = 0; index < 12; index++) {
            context.addAssistant("第 " + index + " 条：PHONE_1 报价成本与利润率上下文");
        }

        List<FloatingChatContext.Turn> snapshot = context.snapshotDelta(1200);

        assertEquals(12, snapshot.size());
        assertEquals("第 0 条：PHONE_1 报价成本与利润率上下文", snapshot.get(0).content);
        assertEquals("第 11 条：PHONE_1 报价成本与利润率上下文", snapshot.get(11).content);
    }

    @Test
    public void replacesLocalTurnsWithServerHistoryForRestartRecovery() {
        FloatingChatContext context = new FloatingChatContext();
        context.addUser("本地临时内容");

        context.replaceWithHistory(List.of(
                new ChatHistoryMessage("user", "需要"),
                new ChatHistoryMessage("assistant", "好的，我会继续核对成本与利润率。")
        ));

        List<FloatingChatContext.Turn> snapshot = context.snapshot(8);
        assertEquals(2, snapshot.size());
        assertEquals("user", snapshot.get(0).role);
        assertEquals("需要", snapshot.get(0).content);
        assertEquals("assistant", snapshot.get(1).role);
        assertEquals("好的，我会继续核对成本与利润率。", snapshot.get(1).content);
    }
}
