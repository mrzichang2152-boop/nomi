import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_tool_registry_routes_ride_request_to_capability_before_adapter():
    from app.tool_registry import default_tool_registry

    registry = default_tool_registry(connected_adapters={"composio": {"google_maps"}})
    decision = registry.route_request("帮我打车去人民广场")

    assert decision["capability_id"] == "ride.prepare_booking"
    assert decision["pipeline_id"] == "ride_pipeline"
    assert decision["selected_adapter"] == "composio"
    assert decision["confirmation_required"] is True
    assert decision["permission"] == "purchase_or_payment"
    assert "final confirmation" in decision["reason"]


def test_tool_registry_requires_connection_instead_of_silent_failure():
    from app.tool_registry import default_tool_registry

    registry = default_tool_registry(connected_adapters={"composio": set()})
    decision = registry.route_request("帮我发邮件给 Alice 说报价明天给")

    assert decision["capability_id"] == "email.send_draft"
    assert decision["route_type"] == "connect_required"
    assert decision["connect_action"]["adapter"] == "composio"
    assert decision["connect_action"]["toolkit"] == "gmail"


def test_tool_registry_routes_assistant_owned_email_to_confirmation_pipeline():
    from app.tool_registry import default_tool_registry

    registry = default_tool_registry(connected_adapters={"local": {"assistant_gmail"}})
    decision = registry.route_request("用 Nomi 自己的邮箱给 Alice 发邮件")

    assert decision["capability_id"] == "assistant.email.send"
    assert decision["pipeline_id"] == "reply_pipeline"
    assert decision["selected_adapter"] == "local"
    assert decision["confirmation_required"] is True
    assert decision["permission"] == "external_message"
    assert "send_without_confirmation" in decision["forbidden_actions"]


def test_tool_registry_routes_assistant_owned_whatsapp_to_confirmation_pipeline():
    from app.tool_registry import default_tool_registry

    registry = default_tool_registry(connected_adapters={"local": {"assistant_whatsapp"}})
    decision = registry.route_request("让 Nomi 用 WhatsApp 告诉 Maya 我晚点到")

    assert decision["capability_id"] == "assistant.whatsapp.send"
    assert decision["pipeline_id"] == "reply_pipeline"
    assert decision["selected_adapter"] == "local"
    assert decision["confirmation_required"] is True
    assert decision["permission"] == "external_message"


def test_tool_registry_routes_assistant_owned_sms_to_confirmation_pipeline():
    from app.tool_registry import default_tool_registry

    registry = default_tool_registry(connected_adapters={"local": {"assistant_phone"}})
    decision = registry.route_request("让 Nomi 用自己的手机号给 Maya 发短信说我晚点到")

    assert decision["capability_id"] == "assistant.sms.send"
    assert decision["pipeline_id"] == "reply_pipeline"
    assert decision["selected_adapter"] == "local"
    assert decision["required_toolkit"] == "assistant_phone"
    assert decision["confirmation_required"] is True
    assert decision["permission"] == "external_message"
    assert "send_without_confirmation" in decision["forbidden_actions"]


def test_tool_registry_routes_assistant_owned_call_to_one_way_confirmation_pipeline():
    from app.tool_registry import default_tool_registry

    registry = default_tool_registry(connected_adapters={"local": {"assistant_phone"}})
    decision = registry.route_request("让 Nomi 用自己的手机号给 Maya 打电话播放我晚点到")

    assert decision["capability_id"] == "assistant.phone.call_playback"
    assert decision["pipeline_id"] == "reply_pipeline"
    assert decision["selected_adapter"] == "local"
    assert decision["required_toolkit"] == "assistant_phone"
    assert decision["confirmation_required"] is True
    assert decision["permission"] == "external_message"
    assert "duplex_call" in decision["forbidden_actions"]


def test_tool_registry_routes_long_tail_to_openclaw_with_minimized_context():
    from app.tool_registry import default_tool_registry

    registry = default_tool_registry()
    decision = registry.route_request("帮我去一个小众报名网站把表格填好但不要提交")

    assert decision["route_type"] == "openclaw_tool"
    assert decision["selected_adapter"] == "openclaw"
    assert "submit" in decision["forbidden_actions"]
    assert decision["confirmation_required"] is True


def test_tool_registry_schema_sql_creates_capability_and_trace_tables():
    from app.tool_registry import tool_registry_schema_sql

    combined = "\n".join(" ".join(sql.split()) for sql in tool_registry_schema_sql())

    assert "CREATE TABLE IF NOT EXISTS capability_catalog" in combined
    assert "CREATE TABLE IF NOT EXISTS tool_registry_entries" in combined
    assert "CREATE TABLE IF NOT EXISTS tool_invocation_traces" in combined
