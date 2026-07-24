package com.par.assistant.android;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;

import org.junit.Test;

public final class AssistantIdentityUiTest {
    @Test
    public void assistantIdentitySubtitleNamesChannelAddressAndStatus() {
        AssistantIdentity gmail = new AssistantIdentity(
                "nomi_gmail_primary",
                "assistant_gmail",
                "Nomi",
                "nomi@example.com",
                "connected"
        );

        assertEquals("Nomi Gmail · nomi@example.com · 已连接", gmail.subtitle());
    }

    @Test
    public void assistantPhoneIdentitySubtitleNamesPhoneChannel() {
        AssistantIdentity phone = new AssistantIdentity(
                "nomi_phone_primary",
                "assistant_phone",
                "Nomi",
                "+15557654321",
                "configured"
        );

        assertEquals("Nomi Phone · +15557654321 · 已配置", phone.subtitle());
    }

    @Test
    public void draftCardIncludesSendingIdentityRecipientAndActions() {
        AssistantDraft draft = new AssistantDraft(
                "draft-1",
                "Nomi Gmail",
                "alice@example.com",
                "报价",
                "我是 Nomi，张子长的个人助理。报价单今晚发。"
        );

        String card = draft.cardText();

        assertTrue(card.contains("将使用：Nomi Gmail"));
        assertTrue(card.contains("收件人：alice@example.com"));
        assertTrue(card.contains("主题：报价"));
        assertTrue(card.contains("我是 Nomi"));
        assertTrue(card.contains("发送 / 编辑 / 取消"));
    }

    @Test
    public void phoneCallDraftCardExplainsOneWayPlaybackAndCallAction() {
        AssistantDraft draft = new AssistantDraft(
                "draft-call-1",
                "Nomi Phone",
                "phone_call",
                "+15551234567",
                "",
                "我是 Nomi，张子长的个人助理。他十分钟后到。"
        );

        String card = draft.cardText();

        assertTrue(card.contains("将使用：Nomi Phone"));
        assertTrue(card.contains("收件人：+15551234567"));
        assertTrue(card.contains("电话只会播放这段语音，不会实时对话"));
        assertTrue(card.contains("拨打 / 编辑 / 取消"));
    }

    @Test
    public void gmailDraftCardShowsEvidenceCountAndBlockedRetryGuidance() {
        AssistantDraft draft = new AssistantDraft(
                "draft-blocked-1",
                "nomi_gmail_primary",
                "Nomi Gmail",
                "gmail",
                "alice@example.com",
                "会议确认",
                "周五下午三点见。",
                "blocked",
                false,
                "2026-07-22T10:00:00Z",
                Arrays.asList("evt-1", "evt-2")
        );

        String card = draft.cardText();

        assertTrue(card.contains("依据：2 条"));
        assertTrue(card.contains("邮件已被策略拦截，请修改后重新确认"));
        assertTrue(card.contains("编辑 / 取消"));
        assertTrue(!card.contains("发送 / 编辑 / 取消"));
    }

    @Test
    public void terminalDraftCardDoesNotOfferDraftActions() {
        AssistantDraft draft = new AssistantDraft(
                "draft-sent-1",
                "nomi_gmail_primary",
                "Nomi Gmail",
                "gmail",
                "alice@example.com",
                "会议确认",
                "周五下午三点见。",
                "sent",
                false,
                "2026-07-22T10:00:00Z"
        );

        String card = draft.cardText();

        assertTrue(card.contains("状态：已发送"));
        assertTrue(!card.contains("发送 / 编辑 / 取消"));
        assertTrue(!card.contains("编辑 / 取消"));
    }

    @Test
    public void sendResultMessageReflectsPersistedProviderState() {
        AssistantDraft unknown = new AssistantDraft(
                "draft-unknown-1",
                "nomi_gmail_primary",
                "Nomi Gmail",
                "gmail",
                "alice@example.com",
                "会议确认",
                "周五下午三点见。",
                "delivery_unknown",
                false,
                "2026-07-22T10:00:00Z"
        );
        AssistantDraft sent = new AssistantDraft(
                "draft-sent-2",
                "nomi_gmail_primary",
                "Nomi Gmail",
                "gmail",
                "alice@example.com",
                "会议确认",
                "周五下午三点见。",
                "sent",
                false,
                "2026-07-22T10:00:00Z"
        );

        assertEquals("邮件已发送。", sent.actionResultMessage());
        assertTrue(unknown.actionResultMessage().contains("送达状态未知"));
        assertTrue(unknown.actionResultMessage().contains("不会自动重发"));
    }
}
