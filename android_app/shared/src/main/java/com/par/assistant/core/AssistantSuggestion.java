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
}
