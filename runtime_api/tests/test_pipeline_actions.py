import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_route_pipeline_prepares_google_maps_route_without_confirmation():
    from app.pipelines.actions import run_action_pipeline

    result = run_action_pipeline(
        "route_pipeline",
        "查一下去武康路要多久",
        {"destination": "武康路", "origin": "当前位置"},
    )

    assert result["pipeline_id"] == "route_pipeline"
    assert result["status"] == "completed_read_only"
    assert result["required_slots"] == ["destination"]
    assert result["resolved_slots"]["destination"] == "武康路"
    assert result["missing_slots"] == []
    assert result["risk"] == {
        "permission": "read_only",
        "confirmation_required": False,
        "final_user_confirmation": False,
    }
    assert result["external_effects"] == []
    assert result["provider_calls"] == []
    assert result["output"]["route_request"] == {
        "origin": "当前位置",
        "destination": "武康路",
        "mode": "transit",
    }
    assert result["output"]["provider_needed"] == "google_maps"
    assert result["writeback_plan"][0]["target"] == "task_trace"


def test_route_pipeline_normalizes_provider_result_and_keeps_external_effects_blocked():
    from app.pipelines.actions import run_action_pipeline

    result = run_action_pipeline(
        "route_pipeline",
        "查一下去静安寺要多久",
        {
            "destination": "静安寺",
            "origin": "当前位置",
            "mode": "driving",
            "provider_result": {
                "routes": [
                    {
                        "duration": {"value": 1680, "text": "28 mins"},
                        "distance": {"text": "8.4 km"},
                        "provider": "google_maps",
                    }
                ]
            },
        },
    )

    assert result["provider_call_plan"]["mode"] == "estimate_only"
    assert result["provider_call_plan"]["provider"] == "google_maps"
    assert result["provider_call_plan"]["external_effect"] is False
    assert result["blocked_effects"] == []
    assert result["safety_checks"] == [
        {"name": "read_only_route_lookup", "status": "passed"},
        {"name": "no_external_effects", "status": "passed"},
    ]
    assert result["output"]["route_options"] == [
        {
            "eta_minutes": 28,
            "distance_text": "8.4 km",
            "provider": "google_maps",
            "mode": "driving",
        }
    ]
    assert "provider_result" not in result["output"]


def test_route_pipeline_without_provider_result_only_proposes_lookup():
    from app.pipelines.actions import run_action_pipeline

    result = run_action_pipeline(
        "route_pipeline",
        "查一下去静安寺要多久",
        {"destination": "静安寺", "origin": "当前位置"},
    )

    assert result["provider_call_plan"]["mode"] == "proposed_only"
    assert result["provider_call_plan"]["action"] == "route_lookup"
    assert result["provider_calls"] == []
    assert result["blocked_effects"] == []
    assert result["output"]["route_options"] == []


def test_ride_pipeline_missing_pickup_asks_targeted_question_and_does_not_book():
    from app.pipelines.actions import run_action_pipeline

    result = run_action_pipeline(
        "ride_pipeline",
        "帮我打车去武康路",
        {"destination": "武康路"},
    )

    assert result["status"] == "needs_user_input"
    assert result["resolved_slots"] == {"destination": "武康路"}
    assert result["missing_slots"] == ["pickup"]
    assert result["risk"]["confirmation_required"] is True
    assert result["external_effects"] == ["book_ride", "payment"]
    assert result["provider_calls"] == []
    assert "pickup" in result["output"]["question"].lower()


def test_ride_pipeline_blocks_booking_and_payment_until_confirmation():
    from app.pipelines.actions import run_action_pipeline

    result = run_action_pipeline(
        "ride_pipeline",
        "帮我叫车从家去武康路",
        {"pickup": "家", "destination": "武康路", "ride_type": "comfort"},
    )

    assert result["provider_call_plan"]["mode"] == "blocked_until_confirmation"
    assert result["provider_call_plan"]["allowed_actions"] == ["estimate_ride"]
    assert result["blocked_effects"] == ["book_ride", "payment"]
    assert result["confirmation_card"] == {
        "type": "ride_confirmation",
        "pickup": "家",
        "destination": "武康路",
        "options": [{"provider": "uber", "ride_type": "comfort"}],
        "confirm_action": "book_ride",
    }
    assert result["safety_checks"][0]["name"] == "requires_final_user_confirmation"


def test_ride_pipeline_with_slots_requires_confirmation_and_only_proposes_provider_calls():
    from app.pipelines.actions import run_action_pipeline

    result = run_action_pipeline(
        "ride_pipeline",
        "帮我叫车从家去武康路",
        {"pickup": "家", "destination": "武康路", "ride_type": "comfort"},
    )

    assert result["status"] == "confirmation_required"
    assert result["missing_slots"] == []
    assert result["output"]["ride_options"][0]["provider"] == "uber"
    assert result["output"]["proposed_provider_calls"][0]["action"] == "estimate_ride"
    assert result["provider_calls"] == []
    assert result["writeback_plan"][0]["action"] == "show_confirmation_card"
    assert all(call.get("action") != "book_ride" for call in result["output"]["proposed_provider_calls"])


def test_shopping_pipeline_comparison_is_read_only():
    from app.pipelines.actions import run_action_pipeline

    result = run_action_pipeline(
        "shopping_pipeline",
        "比较一下降噪耳机",
        {"product_intent": "compare noise cancelling headphones", "shopping_intent": "compare"},
    )

    assert result["status"] == "completed_read_only"
    assert result["risk"]["permission"] == "read_only"
    assert result["external_effects"] == []
    assert result["output"]["comparison_plan"]["product_intent"] == "compare noise cancelling headphones"
    assert result["output"]["purchase_blocked"] is True


def test_shopping_pipeline_compare_outputs_ranked_products_and_criteria():
    from app.pipelines.actions import run_action_pipeline

    result = run_action_pipeline(
        "shopping_pipeline",
        "比较一下降噪耳机",
        {
            "product_intent": "noise cancelling headphones",
            "shopping_intent": "compare",
            "products": [
                {"name": "QuietMax 2", "price": 199, "rating": 4.6},
                {"name": "Silence Pro", "price": 149, "rating": 4.4},
            ],
        },
    )

    assert result["provider_call_plan"]["mode"] == "proposed_only"
    assert result["output"]["comparison_criteria"] == ["price", "reviews", "availability"]
    assert result["output"]["ranked_products"] == [
        {"rank": 1, "name": "QuietMax 2", "price": 199, "rating": 4.6},
        {"rank": 2, "name": "Silence Pro", "price": 149, "rating": 4.4},
    ]
    assert result["blocked_effects"] == ["add_to_cart", "purchase"]


def test_shopping_pipeline_buy_and_cart_are_blocked_until_confirmation():
    from app.pipelines.actions import run_action_pipeline

    buy_result = run_action_pipeline(
        "shopping_pipeline",
        "买咖啡滤纸",
        {"product_intent": "coffee filters", "shopping_intent": "buy"},
    )
    cart_result = run_action_pipeline(
        "shopping_pipeline",
        "把咖啡滤纸加到购物车",
        {"product_intent": "coffee filters", "shopping_intent": "add_to_cart"},
    )

    assert buy_result["provider_call_plan"]["mode"] == "blocked_until_confirmation"
    assert buy_result["provider_call_plan"]["action"] == "purchase"
    assert buy_result["blocked_effects"] == ["purchase"]
    assert buy_result["confirmation_card"]["confirm_action"] == "purchase"
    assert cart_result["provider_call_plan"]["mode"] == "blocked_until_confirmation"
    assert cart_result["provider_call_plan"]["action"] == "add_to_cart"
    assert cart_result["blocked_effects"] == ["add_to_cart"]
    assert cart_result["confirmation_card"]["confirm_action"] == "add_to_cart"


def test_shopping_pipeline_purchase_plan_requires_confirmation_and_never_purchases():
    from app.pipelines.actions import run_action_pipeline

    result = run_action_pipeline(
        "shopping_pipeline",
        "把咖啡滤纸加到购物车",
        {"product_intent": "coffee filters", "shopping_intent": "add_to_cart", "quantity": 2},
    )

    assert result["status"] == "confirmation_required"
    assert result["risk"]["permission"] == "payment_or_purchase"
    assert result["external_effects"] == ["add_to_cart", "purchase"]
    assert result["provider_calls"] == []
    assert result["output"]["proposed_action"]["action"] == "add_to_cart"
    assert result["output"]["purchase_blocked"] is True


def test_payment_pipeline_outputs_risk_summary_and_confirmation_card():
    from app.pipelines.actions import run_action_pipeline

    result = run_action_pipeline(
        "payment_bill_pipeline",
        "付给物业 320 元水电费",
        {"counterparty": "物业", "amount_or_bill": "320 元水电费", "payment_method": "alipay"},
    )

    assert result["provider_call_plan"]["mode"] == "blocked_until_confirmation"
    assert result["blocked_effects"] == ["payment", "transfer"]
    assert result["output"]["risk_summary"] == {
        "level": "high",
        "reasons": ["moves_money", "irreversible_or_sensitive_external_effect"],
    }
    assert result["output"]["payment_confirmation_card"] == {
        "type": "payment_confirmation",
        "counterparty": "物业",
        "amount_or_bill": "320 元水电费",
        "payment_method": "alipay",
        "confirm_action": "transfer_funds",
    }


def test_payment_pipeline_vague_payment_needs_counterparty_and_amount():
    from app.pipelines.actions import run_action_pipeline

    result = run_action_pipeline("payment_bill_pipeline", "帮我付款", {})

    assert result["status"] == "needs_user_input"
    assert result["missing_slots"] == ["counterparty", "amount_or_bill"]
    assert result["risk"]["permission"] == "payment_or_purchase"
    assert result["provider_calls"] == []
    assert result["output"]["question"] == "Who should be paid, and what amount or bill should I prepare?"


def test_payment_pipeline_complete_info_requires_confirmation_and_never_transfers():
    from app.pipelines.actions import run_action_pipeline

    result = run_action_pipeline(
        "payment_bill_pipeline",
        "付给物业 320 元水电费",
        {"counterparty": "物业", "amount_or_bill": "320 元水电费", "payment_method": "alipay"},
    )

    assert result["status"] == "confirmation_required"
    assert result["missing_slots"] == []
    assert result["external_effects"] == ["payment", "transfer"]
    assert result["output"]["payment_plan"]["counterparty"] == "物业"
    assert result["output"]["payment_plan"]["amount_or_bill"] == "320 元水电费"
    assert result["output"]["transfer_blocked"] is True
    assert result["provider_calls"] == []


def test_document_pipeline_read_is_read_only_but_share_requires_confirmation():
    from app.pipelines.actions import run_action_pipeline

    read_result = run_action_pipeline(
        "document_file_pipeline",
        "总结一下项目计划",
        {"file_or_query": "项目计划.docx", "document_intent": "summarize"},
    )
    share_result = run_action_pipeline(
        "document_file_pipeline",
        "把项目计划分享给 Alice",
        {"file_or_query": "项目计划.docx", "document_intent": "share", "recipient": "Alice"},
    )

    assert read_result["status"] == "completed_read_only"
    assert read_result["risk"]["permission"] == "read_only"
    assert read_result["output"]["document_plan"]["action"] == "summarize"
    assert read_result["external_effects"] == []
    assert share_result["status"] == "confirmation_required"
    assert share_result["risk"]["permission"] == "external_write"
    assert share_result["external_effects"] == ["write_document", "share_file"]
    assert share_result["output"]["write_blocked"] is True
    assert share_result["provider_calls"] == []


def test_document_pipeline_read_outputs_document_result_while_write_and_share_are_blocked():
    from app.pipelines.actions import run_action_pipeline

    read_result = run_action_pipeline(
        "document_file_pipeline",
        "总结一下项目计划",
        {"file_or_query": "项目计划.docx", "document_intent": "summarize"},
    )
    write_result = run_action_pipeline(
        "document_file_pipeline",
        "修改项目计划",
        {"file_or_query": "项目计划.docx", "document_intent": "write"},
    )
    share_result = run_action_pipeline(
        "document_file_pipeline",
        "把项目计划分享给 Alice",
        {"file_or_query": "项目计划.docx", "document_intent": "share", "recipient": "Alice"},
    )

    assert read_result["provider_call_plan"]["mode"] == "proposed_only"
    assert read_result["output"]["document_result"] == {
        "action": "summarize",
        "file_or_query": "项目计划.docx",
        "read_only": True,
    }
    assert read_result["blocked_effects"] == []
    assert write_result["provider_call_plan"]["mode"] == "blocked_until_confirmation"
    assert write_result["blocked_effects"] == ["write_document"]
    assert write_result["output"]["edit_or_share_confirmation_card"]["confirm_action"] == "write_document"
    assert share_result["provider_call_plan"]["mode"] == "blocked_until_confirmation"
    assert share_result["blocked_effects"] == ["share_file"]
    assert share_result["output"]["edit_or_share_confirmation_card"]["recipient"] == "Alice"


def test_account_login_pipeline_prepares_browser_plan_without_credentials():
    from app.pipelines.actions import run_action_pipeline

    result = run_action_pipeline(
        "account_login_pipeline",
        "打开 Google 登录",
        {"account_provider": "Google", "login_url": "https://accounts.google.com/"},
    )

    assert result["status"] == "draft_ready"
    assert result["resolved_slots"] == {"account_provider": "Google"}
    assert result["external_effects"] == ["open_browser"]
    assert result["output"]["login_plan"]["login_url"] == "https://accounts.google.com/"
    assert result["output"]["credential_handling"] == "user_enters_credentials_directly"
    assert "password" not in result["resolved_slots"]
    assert result["provider_calls"] == []


def test_account_login_pipeline_outputs_controlled_browser_plan_and_never_handles_credentials():
    from app.pipelines.actions import run_action_pipeline

    result = run_action_pipeline(
        "account_login_pipeline",
        "打开 Google 登录",
        {
            "account_provider": "Google",
            "login_url": "https://accounts.google.com/",
            "username": "user@example.com",
            "password": "secret",
        },
    )

    assert result["provider_call_plan"]["mode"] == "proposed_only"
    assert result["blocked_effects"] == ["submit_credentials", "read_credentials"]
    assert result["output"]["controlled_browser_plan"] == {
        "action": "open_browser",
        "account_provider": "Google",
        "login_url": "https://accounts.google.com/",
        "credential_entry": "user_only",
    }
    assert result["output"]["connection_health"] == {
        "status": "not_connected",
        "reason": "no_external_login_attempted",
    }
    assert result["output"]["credential_handling"] == "user_enters_credentials_directly"
    assert "username" not in result["resolved_slots"]
    assert "password" not in result["resolved_slots"]


def test_unknown_pipeline_id_returns_none():
    from app.pipelines.actions import run_action_pipeline

    assert run_action_pipeline("agenda_pipeline", "remind me", {}) is None
