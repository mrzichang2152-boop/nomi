package com.par.assistant.core;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public final class SuggestionDeduper {
    private final Set<String> displayedIds = new HashSet<>();

    public boolean shouldDisplay(String suggestionId) {
        return suggestionId != null && !suggestionId.trim().isEmpty() && !displayedIds.contains(suggestionId.trim());
    }

    public void markDisplayed(String suggestionId) {
        if (suggestionId != null && !suggestionId.trim().isEmpty()) {
            displayedIds.add(suggestionId.trim());
        }
    }

    public List<AssistantSuggestion> filterNew(List<AssistantSuggestion> suggestions) {
        List<AssistantSuggestion> visible = new ArrayList<>();
        if (suggestions == null) {
            return visible;
        }
        for (AssistantSuggestion suggestion : suggestions) {
            if (suggestion != null && suggestion.isDisplayable() && shouldDisplay(suggestion.id())) {
                visible.add(suggestion);
            }
        }
        return visible;
    }
}
