import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_repeated_successful_tool_traces_create_pipeline_candidate_without_enabling_it():
    from app.workflow_distillation import WorkflowDistiller

    distiller = WorkflowDistiller(min_successes=2)
    first = distiller.observe_trace(
        {
            "source": "openclaw",
            "request": "帮我去供应商网站下载报价单并总结",
            "normalized_goal": "supplier_quote_download_summary",
            "status": "succeeded",
            "steps": ["open_supplier_portal", "download_quote", "summarize_quote"],
            "tools": ["browser"],
            "risk_permission": "read_only",
            "required_slots": ["supplier", "quote_query"],
        }
    )
    second = distiller.observe_trace(
        {
            "source": "openclaw",
            "request": "再去供应商网站下载报价单并总结",
            "normalized_goal": "supplier_quote_download_summary",
            "status": "succeeded",
            "steps": ["open_supplier_portal", "download_quote", "summarize_quote"],
            "tools": ["browser"],
            "risk_permission": "read_only",
            "required_slots": ["supplier", "quote_query"],
        }
    )

    assert first["candidate"] is None
    candidate = second["candidate"]
    assert candidate["normalized_goal"] == "supplier_quote_download_summary"
    assert candidate["approval_status"] == "pending_review"
    assert candidate["evaluation_status"] == "needs_offline_evaluation"
    assert candidate["enabled"] is False
    assert candidate["proposed_steps"] == ["open_supplier_portal", "download_quote", "summarize_quote"]
    assert "human approval" in candidate["promotion_blockers"]


def test_unsafe_external_effect_candidate_is_never_auto_promoted():
    from app.workflow_distillation import WorkflowDistiller

    distiller = WorkflowDistiller(min_successes=2)
    trace = {
        "source": "composio",
        "request": "帮我买同款墨盒并付款",
        "normalized_goal": "buy_and_pay_toner",
        "status": "succeeded",
        "steps": ["search_item", "add_to_cart", "pay"],
        "tools": ["amazon", "stripe"],
        "risk_permission": "purchase_or_payment",
        "required_slots": ["product", "merchant", "amount"],
        "external_effects": ["purchase", "payment"],
    }

    distiller.observe_trace(trace)
    candidate = distiller.observe_trace({**trace, "request": "再次帮我买同款墨盒并付款"})["candidate"]

    assert candidate["enabled"] is False
    assert candidate["confirmation_policy"]["final_user_confirmation"] is True
    assert candidate["approval_status"] == "pending_review"
    assert "unsafe external effect" in candidate["reasonableness_review"]
    assert {"purchase", "payment"}.issubset(set(candidate["forbidden_tools"]))


def test_failed_or_ambiguous_traces_do_not_create_candidates():
    from app.workflow_distillation import WorkflowDistiller

    distiller = WorkflowDistiller(min_successes=2)
    ambiguous = {
        "source": "openclaw",
        "request": "帮我处理一下那个东西",
        "normalized_goal": "ambiguous_process_item",
        "status": "ambiguous",
        "steps": ["ask_clarification"],
        "tools": ["browser"],
        "risk_permission": "external_execution",
    }

    distiller.observe_trace(ambiguous)
    result = distiller.observe_trace({**ambiguous, "request": "继续处理那个东西"})

    assert result["candidate"] is None
    pattern = result["pattern"]
    assert pattern["success_count"] == 0
    assert pattern["failure_count"] == 2


def test_candidate_enable_requires_passed_evaluation_and_human_approval():
    from app.workflow_distillation import WorkflowDistiller

    distiller = WorkflowDistiller(min_successes=2)
    trace = {
        "source": "openclaw",
        "request": "帮我整理供应商报价",
        "normalized_goal": "supplier_quote_summary",
        "status": "succeeded",
        "steps": ["fetch_quote", "summarize_quote"],
        "tools": ["browser"],
        "risk_permission": "read_only",
        "required_slots": ["supplier"],
    }
    distiller.observe_trace(trace)
    candidate = distiller.observe_trace({**trace, "request": "再次整理供应商报价"})["candidate"]

    blocked = distiller.enable_candidate(candidate["candidate_id"])
    assert blocked["enabled"] is False
    assert blocked["approval_status"] == "pending_review"
    assert "evaluation" in blocked["enable_blocked_reason"]

    evaluation = distiller.record_evaluation(
        candidate["candidate_id"],
        [
            {"test_case_id": "positive", "status": "passed", "reasonableness_review": "slots and output are reasonable"},
            {"test_case_id": "ambiguous", "status": "passed", "reasonableness_review": "asks before acting"},
            {"test_case_id": "unsafe", "status": "passed", "reasonableness_review": "blocks external effects"},
        ],
    )
    assert evaluation["evaluation_status"] == "passed_offline_evaluation"

    approved = distiller.approve_candidate(candidate["candidate_id"], reviewer_id="owner")
    assert approved["approval_status"] == "approved"
    assert approved["enabled"] is True
    assert approved["approved_by"] == "owner"


def test_workflow_distillation_schema_sql_creates_pattern_candidate_evaluation_tables():
    from app.workflow_distillation import workflow_distillation_schema_sql

    combined = "\n".join(" ".join(sql.split()) for sql in workflow_distillation_schema_sql())

    assert "CREATE TABLE IF NOT EXISTS workflow_patterns" in combined
    assert "CREATE TABLE IF NOT EXISTS pipeline_candidates" in combined
    assert "CREATE TABLE IF NOT EXISTS skill_evaluation_runs" in combined
