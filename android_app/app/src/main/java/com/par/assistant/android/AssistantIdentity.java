package com.par.assistant.android;

final class AssistantIdentity {
    final String identityId;
    final String kind;
    final String displayName;
    final String address;
    final String status;

    AssistantIdentity(String identityId, String kind, String displayName, String address, String status) {
        this.identityId = identityId == null ? "" : identityId;
        this.kind = kind == null ? "" : kind;
        this.displayName = displayName == null || displayName.trim().isEmpty() ? "Nomi" : displayName.trim();
        this.address = address == null ? "" : address;
        this.status = status == null ? "" : status;
    }

    String subtitle() {
        return channelLabel() + " · " + address + " · " + statusLabel();
    }

    String channelLabel() {
        if ("assistant_whatsapp".equals(kind)) {
            return "Nomi WhatsApp";
        }
        if ("assistant_phone".equals(kind)) {
            return "Nomi Phone";
        }
        return "Nomi Gmail";
    }

    private String statusLabel() {
        if ("connected".equals(status) || "healthy".equals(status)) {
            return "已连接";
        }
        if ("configured".equals(status)) {
            return "已配置";
        }
        if ("expired".equals(status)) {
            return "需重新授权";
        }
        return status.isEmpty() ? "未知" : status;
    }
}
