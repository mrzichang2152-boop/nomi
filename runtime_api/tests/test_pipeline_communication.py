import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


from app.pipelines.communication import run_communication_pipeline


def test_unknown_pipeline_returns_none():
    assert run_communication_pipeline("route_pipeline", "查路线去武康路", {}) is None


def test_personal_search_returns_scoped_citations_sorted_by_score():
    result = run_communication_pipeline(
        "personal_search_pipeline",
        "Find Kai's travel preference",
        {
            "query": "travel preference",
            "current_scope": "chat:kai",
            "memory_hits": [
                {"id": "low", "content": "Kai likes train travel.", "scope": "chat:kai", "score": 0.42},
                {"id": "global", "content": "User prefers aisle seats.", "scope": "global", "score": 0.95},
                {"id": "other", "content": "Mira prefers window seats.", "scope": "chat:mira", "score": 0.99},
                {"id": "user", "content": "Travel reminders should include passport checks.", "scope": "user", "score": 0.77},
            ],
        },
    )

    assert result["pipeline_id"] == "personal_search_pipeline"
    assert result["status"] == "completed_read_only"
    assert result["missing_slots"] == []
    assert result["risk"]["permission"] == "read_only"
    assert result["output"]["answer_summary"].startswith("Found 3 scoped memory")
    assert [citation["id"] for citation in result["output"]["citations"]] == ["global", "user", "low"]
    assert "other" not in {citation["id"] for citation in result["output"]["citations"]}
    assert result["provider_calls"] == []


def test_personal_search_requires_scope_when_hits_cross_private_scopes():
    result = run_communication_pipeline(
        "personal_search_pipeline",
        "Find the dinner preference",
        {
            "query": "dinner preference",
            "memory_hits": [
                {"id": "kai", "content": "Kai likes soba.", "scope": "chat:kai", "score": 0.88},
                {"id": "mira", "content": "Mira likes tacos.", "scope": "chat:mira", "score": 0.91},
                {"id": "global", "content": "The user avoids cilantro.", "scope": "global", "score": 0.7},
            ],
        },
    )

    assert result["status"] == "needs_user_input"
    assert "search_scope" in result["missing_slots"]
    assert "which scope" in result["output"]["question"].lower()
    assert result["output"]["scope_filter_report"]["allowed_count"] == 1
    assert result["output"]["scope_filter_report"]["excluded_count"] == 2
    assert {item["reason"] for item in result["output"]["scope_filter_report"]["excluded"]} == {
        "requires_explicit_search_scope"
    }
    assert result["output"]["evidence_ranking"] == []


def test_personal_search_without_evidence_says_no_reliable_evidence():
    result = run_communication_pipeline(
        "personal_search_pipeline",
        "Find Mira's seat preference",
        {
            "query": "seat preference",
            "current_scope": "chat:mira",
            "memory_hits": [{"id": "kai-only", "content": "Kai prefers trains.", "scope": "chat:kai", "score": 0.8}],
        },
    )

    assert result["status"] == "completed_read_only"
    assert result["output"]["citations"] == []
    assert "no reliable evidence" in result["output"]["answer_summary"].lower()
    assert result["output"]["no_evidence_reason"] == "no_hits_in_allowed_scope"
    assert result["output"]["scope_filter_report"]["excluded"][0]["id"] == "kai-only"


def test_personal_search_outputs_evidence_ranking_with_recency_and_final_rank():
    result = run_communication_pipeline(
        "personal_search_pipeline",
        "Find Kai's travel preference",
        {
            "query": "travel preference",
            "current_scope": "chat:kai",
            "memory_hits": [
                {"id": "old", "content": "Kai liked trains in 2023.", "scope": "chat:kai", "score": 0.95, "recency": 10},
                {"id": "new", "content": "Kai now prefers ferries.", "scope": "chat:kai", "score": 0.91, "recency": 1},
            ],
        },
    )

    assert result["status"] == "completed_read_only"
    assert result["output"]["evidence_ranking"] == [
        {"id": "new", "scope": "chat:kai", "score": 0.91, "recency_rank": 1, "final_rank": 1},
        {"id": "old", "scope": "chat:kai", "score": 0.95, "recency_rank": 2, "final_rank": 2},
    ]


def test_chat_response_returns_stream_plan_and_context_snapshot_writeback():
    result = run_communication_pipeline(
        "chat_response_pipeline",
        "Can you help me plan dinner?",
        {
            "conversation_id": "conv-42",
            "message": "Can you help me plan dinner?",
            "context_pack_id": "ctx-7",
            "memory_hits": [{"id": "m1", "content": "No cilantro.", "scope": "user", "score": 0.8}],
            "action_cards": [{"type": "reply", "title": "Text Sam"}],
        },
    )

    assert result["status"] == "completed_read_only"
    assert result["resolved_slots"]["conversation_id"] == "conv-42"
    assert result["output"]["stream_plan"]["mode"] == "assistant_response"
    assert result["output"]["stream_plan"]["conversation_id"] == "conv-42"
    assert result["output"]["action_cards"] == [{"type": "reply", "title": "Text Sam"}]
    assert result["writeback_plan"][0]["target"] == "context_snapshots"
    assert result["writeback_plan"][0]["payload"]["context_pack_id"] == "ctx-7"
    assert result["writeback_plan"][0]["payload"]["evidence_ids"] == ["m1"]


def test_chat_response_stream_plan_and_action_handoff_are_explicit():
    result = run_communication_pipeline(
        "chat_response_pipeline",
        "Reply to Sam after this answer",
        {
            "conversation_id": "conv-99",
            "message": "Reply to Sam after this answer",
            "trace_id": "trace-abc",
            "action_intent": {"type": "reply", "target_pipeline": "reply_pipeline"},
        },
    )

    assert result["status"] == "completed_read_only"
    assert result["output"]["stream_plan"]["chunk_mode"] == "token"
    assert result["output"]["stream_plan"]["trace_id"] == "trace-abc"
    assert result["output"]["stream_plan"]["writeback_after_stream"] is True
    assert result["output"]["action_handoff"] == {
        "target_pipeline": "reply_pipeline",
        "requires_user_click": True,
    }


def test_chat_response_action_handoff_uses_card_target_pipeline_before_fallback():
    result = run_communication_pipeline(
        "chat_response_pipeline",
        "帮我打车",
        {
            "conversation_id": "conv-ride",
            "message": "帮我打车",
            "action_cards": [{"label": "帮我打车", "target_pipeline": "ride_pipeline"}],
        },
    )

    assert result["status"] == "completed_read_only"
    assert result["output"]["action_handoff"] == {
        "target_pipeline": "ride_pipeline",
        "requires_user_click": True,
    }


def test_reply_pipeline_builds_draft_without_sending():
    result = run_communication_pipeline(
        "reply_pipeline",
        "Reply to Alice on WhatsApp that Friday at 8 works",
        {"active_source_scope": {"source": "whatsapp"}, "tone": "warm"},
    )

    assert result["status"] == "draft_ready"
    assert result["resolved_slots"]["recipient"] == "Alice"
    assert result["resolved_slots"]["channel"] == "whatsapp"
    assert "Friday at 8 works" in result["resolved_slots"]["message_intent"]
    assert result["risk"]["permission"] == "external_message"
    assert result["risk"]["confirmation_required"] is True
    assert result["external_effects"] == ["send_message"]
    assert result["output"]["target"] == {"recipient": "Alice", "channel": "whatsapp"}
    assert "Friday at 8 works" in result["output"]["draft"]
    assert result["output"]["confirmation_card"]["recipient"] == "Alice"
    assert result["output"]["confirmation_card"]["channel"] == "whatsapp"
    assert result["output"]["confirmation_card"]["actions"] == ["confirm_send", "edit_draft", "cancel"]
    assert result["provider_calls"] == []


def test_reply_pipeline_blocks_leakage_from_disallowed_context():
    result = run_communication_pipeline(
        "reply_pipeline",
        "Reply to Alice on Slack that Project Phoenix budget is approved",
        {
            "leakage_terms": ["Project Phoenix"],
            "disallowed_context": ["budget is approved"],
        },
    )

    assert result["status"] == "blocked"
    assert result["external_effects"] == []
    assert result["output"]["send_message"]["status"] == "blocked"
    assert result["output"]["leakage_review"]["status"] == "blocked"
    assert set(result["output"]["leakage_review"]["matched_terms"]) == {"Project Phoenix", "budget is approved"}
    assert result["output"]["confirmation_card"]["actions"] == ["blocked"]
    assert "blocked" in result["output"]["confirmation_card"]["risk_summary"].lower()


def test_reply_pipeline_missing_slots_are_targeted():
    result = run_communication_pipeline("reply_pipeline", "Reply to Alice", {})

    assert result["status"] == "needs_user_input"
    assert result["resolved_slots"]["recipient"] == "Alice"
    assert result["missing_slots"] == ["channel", "message_intent"]
    assert "channel" in result["output"]["question"].lower()
    assert "message_intent" in result["output"]["question"]


def test_email_summarize_is_read_only_with_tasks():
    result = run_communication_pipeline(
        "email_pipeline",
        "Summarize inbox",
        {
            "mailbox": "gmail:primary",
            "email_intent": "summarize",
            "emails": [
                {"id": "e1", "from": "boss@example.com", "subject": "Launch", "snippet": "Please review the launch plan."},
                {"id": "e2", "from": "school@example.com", "subject": "Permission slip", "snippet": "Please sign by Friday."},
            ],
        },
    )

    assert result["status"] == "completed_read_only"
    assert result["risk"]["permission"] == "read_only"
    assert "2 email" in result["output"]["summary"]
    assert result["output"]["task_candidates"][0]["source_email_id"] == "e1"
    assert "read_model" in result["output"]
    assert "confirmation_card" not in result["output"]
    assert result["external_effects"] == []


def test_email_generates_internal_candidates_without_external_calls():
    result = run_communication_pipeline(
        "email_pipeline",
        "Summarize this email",
        {
            "mailbox": "gmail:primary",
            "email_intent": "summarize",
            "email_body": "Agenda: roadmap review. TODO: send notes. Invoice payment due Friday. Please reply to Dana.",
            "candidates": [{"type": "todo", "title": "Bring printed agenda"}],
        },
    )

    candidate_types = {candidate["type"] for candidate in result["output"]["internal_candidates"]}
    assert {"agenda", "todo", "payment", "reply"}.issubset(candidate_types)
    assert result["provider_calls"] == []
    assert result["external_effects"] == []


def test_email_draft_send_archive_label_are_confirmation_required_plans():
    cases = [
        ("draft", "Draft a reply in Gmail", "draft"),
        ("send", "Send an email from Gmail", "draft"),
        ("archive", "Archive this Gmail thread", "action_plan"),
        ("label", "Label this Gmail thread as travel", "action_plan"),
    ]

    for intent, request, expected_output_key in cases:
        result = run_communication_pipeline(
            "email_pipeline",
            request,
            {"mailbox": "gmail:primary", "email_intent": intent, "label": "travel"},
        )

        assert result["status"] == "draft_ready"
        assert result["risk"]["permission"] == "external_message"
        assert result["risk"]["confirmation_required"] is True
        assert result["execution_guard"]["policy"] == "requires_final_user_confirmation"
        assert expected_output_key in result["output"]
        assert result["output"]["confirmation_card"]["actions"] == ["confirm", "edit", "cancel"]
        assert result["output"]["provider_call_plan"]["status"] == "proposed_only"
        assert result["output"]["provider_call_plan"]["intent"] == intent
        assert result["provider_calls"] == []
        assert set(result["external_effects"]).issubset({"send_email", "archive_email", "label_email"})
