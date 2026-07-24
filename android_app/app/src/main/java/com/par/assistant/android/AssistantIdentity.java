package com.par.assistant.android;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

final class AssistantIdentity {
    final String identityId;
    final String kind;
    final String displayName;
    final String address;
    final String provider;
    final List<String> capabilities;
    final String status;
    final long version;
    final String lastVerifiedAt;
    final String lastErrorCode;
    final boolean secretStored;

    AssistantIdentity(String identityId, String kind, String displayName, String address, String status) {
        this(identityId, kind, displayName, address, "", List.of(), status, 1L, "", "", false);
    }

    AssistantIdentity(
            String identityId,
            String kind,
            String displayName,
            String address,
            String provider,
            List<String> capabilities,
            String status,
            long version,
            String lastVerifiedAt,
            String lastErrorCode,
            boolean secretStored
    ) {
        this.identityId = identityId == null ? "" : identityId;
        this.kind = kind == null ? "" : kind;
        this.displayName = displayName == null || displayName.trim().isEmpty() ? "Nomi" : displayName.trim();
        this.address = address == null ? "" : address;
        this.provider = provider == null ? "" : provider;
        this.capabilities = Collections.unmodifiableList(new ArrayList<>(capabilities == null ? List.of() : capabilities));
        this.status = status == null ? "" : status;
        this.version = version;
        this.lastVerifiedAt = lastVerifiedAt == null ? "" : lastVerifiedAt;
        this.lastErrorCode = lastErrorCode == null ? "" : lastErrorCode;
        this.secretStored = secretStored;
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
        if ("degraded".equals(status)) {
            return "连接异常";
        }
        if ("authorization_pending".equals(status)) {
            return "等待授权";
        }
        if ("verifying".equals(status)) {
            return "验证中";
        }
        if ("disabled".equals(status)) {
            return "已停用";
        }
        if ("unconfigured".equals(status)) {
            return "未配置";
        }
        return status.isEmpty() ? "未知" : status;
    }
}
