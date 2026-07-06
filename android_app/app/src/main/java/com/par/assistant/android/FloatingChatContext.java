package com.par.assistant.android;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

final class FloatingChatContext {
    private static final int DEFAULT_DELTA_TURN_LIMIT = 30;
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

    List<Turn> snapshotDelta(int maxChars) {
        return snapshotDelta(maxChars, DEFAULT_DELTA_TURN_LIMIT);
    }

    List<Turn> snapshotDelta(int maxChars, int maxTurns) {
        int remaining = Math.max(0, maxChars);
        int turnLimit = Math.max(0, maxTurns);
        ArrayList<Turn> selected = new ArrayList<>();
        for (int index = turns.size() - 1; index >= 0; index--) {
            if (selected.size() >= turnLimit) {
                break;
            }
            Turn turn = turns.get(index);
            int cost = turn.role.length() + turn.content.length() + 8;
            if (!selected.isEmpty() && cost > remaining) {
                break;
            }
            selected.add(0, turn);
            remaining -= cost;
            if (remaining <= 0) {
                break;
            }
        }
        return Collections.unmodifiableList(selected);
    }

    void replaceWithHistory(List<ChatHistoryMessage> messages) {
        turns.clear();
        if (messages == null) return;
        for (ChatHistoryMessage message : messages) {
            if (message == null) continue;
            String role = message.role == null ? "" : message.role.trim();
            if (!"user".equals(role) && !"assistant".equals(role)) continue;
            add(role, message.content);
        }
    }

    int size() {
        return turns.size();
    }

    private void add(String role, String content) {
        String clean = content == null ? "" : content.trim();
        if (clean.isEmpty()) return;
        turns.add(new Turn(role, clean));
        if (turns.size() > 80) {
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
