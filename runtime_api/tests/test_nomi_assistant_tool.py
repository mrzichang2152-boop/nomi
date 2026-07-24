import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_cli_exposes_only_bounded_assistant_commands():
    from scripts.nomi_assistant_tool import build_parser

    parser = build_parser()
    choices = parser._subparsers._group_actions[0].choices

    assert set(choices) == {
        "identity-status",
        "resolve-contact",
        "create-email-draft",
        "outbound-status",
        "cancel-draft",
    }
    assert "send" not in choices
    assert "confirm" not in choices


def test_cli_sends_task_and_arguments_without_client_task_scope(monkeypatch):
    from scripts import nomi_assistant_tool

    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "confirmation_required", "draft_id": "draft-1"}

    def fake_post(url, *, headers, json, timeout):
        captured.update(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        return Response()

    monkeypatch.setenv("RUNTIME_API_URL", "http://runtime-api:8080")
    monkeypatch.setenv("RUNTIME_API_PASSWORD", "runtime-secret")
    monkeypatch.setattr(nomi_assistant_tool.httpx, "post", fake_post)

    result = nomi_assistant_tool.execute_tool(
        task_id="lta_789",
        tool_name="assistant.email.create_draft",
        arguments={"task_id": "lta_789", "subject": "跟进"},
    )

    assert result == {"status": "confirmation_required", "draft_id": "draft-1"}
    assert captured["url"] == "http://runtime-api:8080/api/assistant-tools/execute"
    assert captured["headers"] == {"x-par-password": "runtime-secret"}
    assert captured["json"] == {
        "task_id": "lta_789",
        "tool_name": "assistant.email.create_draft",
        "arguments": {"task_id": "lta_789", "subject": "跟进"},
    }
    assert "task_scope" not in captured["json"]
