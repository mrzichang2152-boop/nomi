package com.par.assistant.android;

import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

final class AssistantDraftActionGuard {
    private final Set<String> inFlightDraftIds = ConcurrentHashMap.newKeySet();

    boolean begin(String draftId) {
        String cleanDraftId = draftId == null ? "" : draftId.trim();
        return !cleanDraftId.isEmpty() && inFlightDraftIds.add(cleanDraftId);
    }

    void finish(String draftId) {
        String cleanDraftId = draftId == null ? "" : draftId.trim();
        if (!cleanDraftId.isEmpty()) inFlightDraftIds.remove(cleanDraftId);
    }
}
