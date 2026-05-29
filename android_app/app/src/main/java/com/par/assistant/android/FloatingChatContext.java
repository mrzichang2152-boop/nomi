package com.par.assistant.android;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

final class FloatingChatContext {
    private final List<Turn> turns = new ArrayList<>();

    void addUser(String content) {
        add("user", content);
    }

    void addAssistant(String content) {
        add("assistant", content);
    }

    List<Turn> snapshot(int limit) {
        int size = turns.size();
        int from = Math.max(0, size - Math.max(0, limit));
        return Collections.unmodifiableList(new ArrayList<>(turns.subList(from, size)));
    }

    private void add(String role, String content) {
        String clean = content == null ? "" : content.trim();
        if (clean.isEmpty()) return;
        turns.add(new Turn(role, clean));
        if (turns.size() > 24) {
            turns.remove(0);
        }
    }

    static final class Turn {
        final String role;
        final String content;

        Turn(String role, String content) {
            this.role = role;
            this.content = content;
        }
    }
}
