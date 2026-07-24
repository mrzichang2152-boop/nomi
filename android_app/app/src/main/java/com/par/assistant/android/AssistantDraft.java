package com.par.assistant.android;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

final class AssistantDraft {
    final String draftId;
    final String identityId;
    final String identityLabel;
    final String channel;
    final String recipient;
    final String subject;
    final String bodyText;
    final String status;
    final boolean confirmationRequired;
    final String updatedAt;
    final List<String> sourceEvidenceIds;
    final String failureReason;
    final String recoveryGuidance;

    AssistantDraft(String draftId, String identityLabel, String recipient, String subject, String bodyText) {
        this(draftId, identityLabel, "", recipient, subject, bodyText);
    }

    AssistantDraft(String draftId, String identityLabel, String channel, String recipient, String subject, String bodyText) {
        this(draftId, "", identityLabel, channel, recipient, subject, bodyText, "draft", true, "");
    }

    AssistantDraft(
            String draftId,
            String identityId,
            String identityLabel,
            String channel,
            String recipient,
            String subject,
            String bodyText,
            String status,
            boolean confirmationRequired,
            String updatedAt
    ) {
        this(
                draftId,
                identityId,
                identityLabel,
                channel,
                recipient,
                subject,
                bodyText,
                status,
                confirmationRequired,
                updatedAt,
                Collections.emptyList(),
                "",
                ""
        );
    }

    AssistantDraft(
            String draftId,
            String identityId,
            String identityLabel,
            String channel,
            String recipient,
            String subject,
            String bodyText,
            String status,
            boolean confirmationRequired,
            String updatedAt,
            List<String> sourceEvidenceIds
    ) {
        this(
                draftId,
                identityId,
                identityLabel,
                channel,
                recipient,
                subject,
                bodyText,
                status,
                confirmationRequired,
                updatedAt,
                sourceEvidenceIds,
                "",
                ""
        );
    }

    AssistantDraft(
            String draftId,
            String identityId,
            String identityLabel,
            String channel,
            String recipient,
            String subject,
            String bodyText,
            String status,
            boolean confirmationRequired,
            String updatedAt,
            List<String> sourceEvidenceIds,
            String failureReason,
            String recoveryGuidance
    ) {
        this.draftId = draftId == null ? "" : draftId;
        this.identityId = identityId == null ? "" : identityId;
        this.identityLabel = identityLabel == null || identityLabel.trim().isEmpty() ? "Nomi" : identityLabel.trim();
        this.channel = channel == null ? "" : channel.trim();
        this.recipient = recipient == null ? "" : recipient;
        this.subject = subject == null ? "" : subject;
        this.bodyText = bodyText == null ? "" : bodyText;
        this.status = status == null ? "" : status.trim();
        this.confirmationRequired = confirmationRequired;
        this.updatedAt = updatedAt == null ? "" : updatedAt.trim();
        this.sourceEvidenceIds = Collections.unmodifiableList(
                new ArrayList<>(sourceEvidenceIds == null ? Collections.emptyList() : sourceEvidenceIds)
        );
        this.failureReason = failureReason == null ? "" : failureReason.trim();
        this.recoveryGuidance = recoveryGuidance == null ? "" : recoveryGuidance.trim();
    }

    boolean isPendingGmailConfirmation() {
        return "nomi_gmail_primary".equals(identityId)
                && "gmail".equals(channel)
                && ("draft".equals(status) || "blocked".equals(status));
    }

    boolean isVisibleGmailDraftCard() {
        if (!"nomi_gmail_primary".equals(identityId) || !"gmail".equals(channel)) return false;
        switch (status) {
            case "draft":
            case "blocked":
            case "sending":
            case "sent":
            case "delivered":
            case "read":
            case "failed":
            case "rejected":
            case "delivery_unknown":
                return true;
            default:
                return false;
        }
    }

    String statusLabel() {
        switch (status) {
            case "draft": return "待确认";
            case "blocked": return "已拦截";
            case "sending": return "发送中";
            case "sent": return "已发送";
            case "delivered": return "已送达";
            case "read": return "已读";
            case "failed": return "发送失败";
            case "rejected": return "已拒绝";
            case "delivery_unknown": return "送达状态待核实";
            default: return status.isEmpty() ? "未知" : status;
        }
    }

    boolean isEditable() {
        return "draft".equals(status) || "blocked".equals(status);
    }

    String actionResultMessage() {
        switch (status) {
            case "sent": return "邮件已发送。";
            case "delivered": return "邮件已送达。";
            case "read": return "邮件已被收件人阅读。";
            case "sending": return "邮件正在发送，请稍后刷新状态。";
            case "delivery_unknown":
                return "邮件送达状态未知，请先在 Gmail 中核实；系统不会自动重发。";
            case "blocked": return "邮件被策略拦截，请修改草稿后重新确认。";
            case "rejected": return "邮件被发送服务拒绝，请检查账号和收件人后再修改草稿。";
            case "failed": return "邮件发送失败，请查看失败原因后修改草稿。";
            default: return "邮件状态已更新：" + statusLabel() + "。";
        }
    }

    String cardText() {
        StringBuilder builder = new StringBuilder();
        builder.append("将使用：").append(identityLabel).append("\n");
        builder.append("状态：").append(statusLabel()).append("\n");
        builder.append("收件人：").append(recipient).append("\n");
        if (!subject.isEmpty()) {
            builder.append("主题：").append(subject).append("\n");
        }
        builder.append("\n").append(bodyText).append("\n\n");
        builder.append("依据：").append(sourceEvidenceIds.size()).append(" 条\n");
        if ("blocked".equals(status)) {
            builder.append("邮件已被策略拦截，请修改后重新确认");
            if (!recoveryGuidance.isEmpty()) builder.append("：").append(recoveryGuidance);
            if (!failureReason.isEmpty()) builder.append("（").append(failureReason).append("）");
            builder.append("\n");
        } else if ("failed".equals(status) || "rejected".equals(status)) {
            builder.append(actionResultMessage());
            if (!recoveryGuidance.isEmpty()) builder.append(" ").append(recoveryGuidance);
            if (!failureReason.isEmpty()) builder.append("（").append(failureReason).append("）");
            builder.append("\n");
        } else if ("delivery_unknown".equals(status)) {
            builder.append(actionResultMessage()).append("\n");
        }
        builder.append("\n");
        if (!isEditable()) {
            return builder.toString().trim();
        }
        if ("phone_call".equals(channel)) {
            builder.append("电话只会播放这段语音，不会实时对话。\n");
            builder.append("draft".equals(status) ? "拨打 / 编辑 / 取消" : "编辑 / 取消");
        } else {
            builder.append("draft".equals(status) ? "发送 / 编辑 / 取消" : "编辑 / 取消");
        }
        return builder.toString();
    }
}
