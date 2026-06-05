package com.par.assistant.android;

final class AssistantDraft {
    final String draftId;
    final String identityLabel;
    final String channel;
    final String recipient;
    final String subject;
    final String bodyText;

    AssistantDraft(String draftId, String identityLabel, String recipient, String subject, String bodyText) {
        this(draftId, identityLabel, "", recipient, subject, bodyText);
    }

    AssistantDraft(String draftId, String identityLabel, String channel, String recipient, String subject, String bodyText) {
        this.draftId = draftId == null ? "" : draftId;
        this.identityLabel = identityLabel == null || identityLabel.trim().isEmpty() ? "Nomi" : identityLabel.trim();
        this.channel = channel == null ? "" : channel.trim();
        this.recipient = recipient == null ? "" : recipient;
        this.subject = subject == null ? "" : subject;
        this.bodyText = bodyText == null ? "" : bodyText;
    }

    String cardText() {
        StringBuilder builder = new StringBuilder();
        builder.append("将使用：").append(identityLabel).append("\n");
        builder.append("收件人：").append(recipient).append("\n");
        if (!subject.isEmpty()) {
            builder.append("主题：").append(subject).append("\n");
        }
        builder.append("\n").append(bodyText).append("\n\n");
        if ("phone_call".equals(channel)) {
            builder.append("电话只会播放这段语音，不会实时对话。\n");
            builder.append("拨打 / 编辑 / 取消");
        } else {
            builder.append("发送 / 编辑 / 取消");
        }
        return builder.toString();
    }
}
