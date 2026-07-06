package com.par.assistant.core;

public final class AssistantSuggestion {
    private final String id;
    private final String title;
    private final String body;
    private final double priority;

    public AssistantSuggestion(String id, String title, String body, double priority) {
        if (id == null || id.trim().isEmpty()) {
            throw new IllegalArgumentException("suggestion id is required");
        }
        this.id = id.trim();
        this.title = title == null ? "" : title;
        this.body = body == null ? "" : body;
        this.priority = priority;
    }

    public String id() {
        return id;
    }

    public String title() {
        return title;
    }

    public String body() {
        return body;
    }

    public double priority() {
        return priority;
    }

    public boolean isDisplayable() {
        return isDisplayableText(title, body);
    }

    public static boolean isDisplayableText(String title, String body) {
        String text = ((title == null ? "" : title) + "\n" + (body == null ? "" : body)).trim().toLowerCase();
        if (text.isEmpty()) {
            return false;
        }
        if (text.matches("(?s).*\\b\\d+\\s+notifications?\\s+total\\b.*")) {
            return false;
        }
        if (text.contains("user said to nomi:") || text.contains("assistant said to nomi:")) {
            return false;
        }
        if (text.matches("(?s).*可能需要跟进：\\(\\d+\\)\\s*(whatsapp|telegram)\\s*。?\\s*$")) {
            return false;
        }
        return true;
    }
}
