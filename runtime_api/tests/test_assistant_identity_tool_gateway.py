import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _connected_registry():
    from app.assistant_identity.models import AssistantIdentity
    from app.assistant_identity.registry import AssistantIdentityRegistry

    registry = AssistantIdentityRegistry()
    registry.add(
        AssistantIdentity(
            identity_id="nomi_gmail_primary",
            kind="assistant_gmail",
            provider="composio_gmail",
            display_name="Nomi",
            address="nomi@example.com",
            status="connected",
            capabilities=["receive", "draft", "send", "thread_reply"],
            metadata={"provider_connection": {"connected_account_id": "ca_nomi"}},
        )
    )
    return registry


def _gateway():
    from app.assistant_identity.outbound import OutboundMessagePipeline
    from app.assistant_identity.tool_gateway import AssistantToolGateway

    return AssistantToolGateway(
        registry=_connected_registry(),
        outbound=OutboundMessagePipeline(),
        contacts={
            "contact_alice": {
                "display_name": "Alice",
                "gmail": "alice@example.com",
            },
            "contact_bob": {
                "display_name": "Bob",
                "gmail": "bob@example.com",
            },
        },
    )


def _task_scope():
    return {
        "task_id": "lta_789",
        "permitted_tool_names": [
            "assistant.identity.get_status",
            "assistant.contacts.resolve",
            "assistant.email.create_draft",
            "assistant.outbound.get_status",
            "assistant.outbound.cancel_draft",
        ],
        "permitted_contact_ids": ["contact_alice"],
        "permitted_source_evidence_ids": ["evt_123", "job_456"],
    }


def test_opencode_manifest_exposes_only_bounded_gmail_v1_tools():
    from app.assistant_identity.tool_gateway import assistant_tool_manifest

    manifest = assistant_tool_manifest()
    names = {tool["name"] for tool in manifest}

    assert names == {
        "assistant.identity.get_status",
        "assistant.contacts.resolve",
        "assistant.email.create_draft",
        "assistant.outbound.get_status",
        "assistant.outbound.cancel_draft",
    }
    serialized = str(manifest).lower()
    assert "send_confirmed_draft" not in serialized
    assert "confirmation_token" not in serialized
    assert "composio" not in serialized
    assert "gmail_send_email" not in serialized
    assert "assistant.whatsapp" not in serialized


def test_opencode_can_create_idempotent_confirmation_required_email_draft():
    gateway = _gateway()
    arguments = {
        "identity_id": "nomi_gmail_primary",
        "recipient": {"contact_id": "contact_alice"},
        "subject": "明天会议资料",
        "body_text": "Alice 你好，我是 Nomi。会议资料已经整理好。",
        "source_evidence_ids": ["evt_123"],
        "task_id": "lta_789",
        "idempotency_key": "lta_789:contact_alice:draft:1",
    }

    first = gateway.execute(
        "assistant.email.create_draft",
        arguments,
        task_scope=_task_scope(),
    )
    second = gateway.execute(
        "assistant.email.create_draft",
        arguments,
        task_scope=_task_scope(),
    )

    assert first == second
    assert first["status"] == "confirmation_required"
    assert first["identity"] == "Nomi <nomi@example.com>"
    assert first["recipient"] == "Alice <alice@example.com>"
    assert first["policy_checks"] == [
        "identity_connected",
        "recipient_resolved",
        "evidence_scope_passed",
        "idempotency_passed",
    ]
    assert first["audit"] == {
        "tool_name": "assistant.email.create_draft",
        "task_id": "lta_789",
        "status": "confirmation_required",
        "draft_id": first["draft_id"],
        "sensitive_arguments_persisted": False,
    }
    assert "alice@example.com" not in str(first["audit"])
    assert "会议资料已经整理好" not in str(first["audit"])
    assert gateway.outbound.get_draft(first["draft_id"])["send_called"] is False


def test_opencode_draft_idempotency_and_ownership_survive_gateway_recreation():
    from app.assistant_identity.outbound import OutboundMessagePipeline
    from app.assistant_identity.outbound_repository import InMemoryAssistantOutboundRepository
    from app.assistant_identity.tool_gateway import AssistantToolGateway

    repository = InMemoryAssistantOutboundRepository()

    def new_gateway():
        return AssistantToolGateway(
            registry=_connected_registry(),
            outbound=OutboundMessagePipeline(repository=repository),
            contacts={
                "contact_alice": {
                    "display_name": "Alice",
                    "gmail": "alice@example.com",
                }
            },
        )

    arguments = {
        "identity_id": "nomi_gmail_primary",
        "recipient": {"contact_id": "contact_alice"},
        "subject": "跨重启幂等",
        "body_text": "重复执行同一步骤只能得到同一份草稿。",
        "source_evidence_ids": ["evt_123"],
        "task_id": "lta_789",
        "idempotency_key": "lta_789:contact_alice:persisted:1",
    }
    first = new_gateway().execute(
        "assistant.email.create_draft",
        arguments,
        task_scope=_task_scope(),
    )
    recreated = new_gateway()
    second = recreated.execute(
        "assistant.email.create_draft",
        arguments,
        task_scope=_task_scope(),
    )
    status = recreated.execute(
        "assistant.outbound.get_status",
        {"draft_id": first["draft_id"]},
        task_scope=_task_scope(),
    )

    assert second["draft_id"] == first["draft_id"]
    assert status == {
        "draft_id": first["draft_id"],
        "status": "draft",
        "confirmation_required": True,
        "send_called": False,
    }


def test_opencode_tool_scope_blocks_unlisted_contact_and_evidence():
    gateway = _gateway()
    base = {
        "identity_id": "nomi_gmail_primary",
        "recipient": {"contact_id": "contact_bob"},
        "subject": "越权测试",
        "body_text": "不应创建。",
        "source_evidence_ids": ["evt_123"],
        "task_id": "lta_789",
        "idempotency_key": "lta_789:contact_bob:draft:1",
    }

    with pytest.raises(PermissionError, match="contact_scope_denied"):
        gateway.execute("assistant.email.create_draft", base, task_scope=_task_scope())

    base["recipient"] = {"contact_id": "contact_alice"}
    base["source_evidence_ids"] = ["evt_not_permitted"]
    with pytest.raises(PermissionError, match="evidence_scope_denied"):
        gateway.execute("assistant.email.create_draft", base, task_scope=_task_scope())


@pytest.mark.parametrize(
    "invented_tool",
    [
        "gmail.send",
        "GMAIL_SEND_EMAIL",
        "composio.tools.execute",
        "assistant.email.send_confirmed_draft",
        "assistant.outbound.confirm",
    ],
)
def test_opencode_cannot_invent_direct_send_or_confirmation_tools(invented_tool):
    gateway = _gateway()

    with pytest.raises(PermissionError, match="assistant_tool_not_allowed"):
        gateway.execute(invented_tool, {}, task_scope=_task_scope())


def test_task_scope_must_explicitly_allow_the_high_level_tool():
    gateway = _gateway()

    with pytest.raises(PermissionError, match="assistant_tool_scope_denied"):
        gateway.execute(
            "assistant.email.create_draft",
            {
                "identity_id": "nomi_gmail_primary",
                "recipient": {"contact_id": "contact_alice"},
                "subject": "不应创建",
                "body_text": "当前步骤没有草稿权限。",
                "source_evidence_ids": ["evt_123"],
                "task_id": "lta_789",
                "idempotency_key": "lta_789:denied",
            },
            task_scope={
                **_task_scope(),
                "permitted_tool_names": ["assistant.identity.get_status"],
            },
        )


def test_server_builds_task_scope_from_route_and_current_step_only():
    from app.assistant_identity.tool_gateway import build_assistant_task_scope

    scope = build_assistant_task_scope(
        {
            "task_id": "lta_789",
            "current_step_id": "draft_follow_up",
            "route_decision": {
                "source_event_ids": ["evt_123", "evt_123", ""],
                "permitted_contact_ids": ["contact_alice", "contact_alice"],
                "task_scope": {
                    "permitted_contact_ids": ["contact_injected"],
                    "permitted_source_evidence_ids": ["evt_injected"],
                },
            },
        },
        {
            "steps": [
                {
                    "step_id": "draft_follow_up",
                    "allowed_actions": [
                        "assistant.identity.get_status",
                        "assistant.contacts.resolve",
                        "assistant.email.create_draft",
                        "GMAIL_SEND_EMAIL",
                    ],
                }
            ]
        },
    )

    assert scope == {
        "task_id": "lta_789",
        "step_id": "draft_follow_up",
        "permitted_tool_names": [
            "assistant.identity.get_status",
            "assistant.contacts.resolve",
            "assistant.email.create_draft",
        ],
        "permitted_contact_ids": ["contact_alice"],
        "permitted_source_evidence_ids": ["evt_123"],
    }


def test_server_task_scope_fails_closed_without_current_step():
    from app.assistant_identity.tool_gateway import build_assistant_task_scope

    scope = build_assistant_task_scope(
        {
            "task_id": "lta_789",
            "route_decision": {
                "source_event_ids": ["evt_123"],
                "permitted_contact_ids": ["contact_alice"],
            },
        },
        {"steps": []},
    )

    assert scope["permitted_tool_names"] == []
    assert scope["step_id"] == ""


def test_scoped_executor_rebuilds_scope_and_records_only_safe_draft_checkpoint():
    from app.assistant_identity.tool_gateway import AssistantScopedToolExecutor
    from app.long_tail_agent import LongTailEventStore

    event_store = LongTailEventStore()
    task_state = {
        "task_id": "lta_789",
        "current_step_id": "draft_follow_up",
        "route_decision": {
            "source_event_ids": ["evt_123"],
            "permitted_contact_ids": ["contact_alice"],
        },
    }
    plan = {
        "steps": [
            {
                "step_id": "draft_follow_up",
                "allowed_actions": ["assistant.email.create_draft"],
            }
        ]
    }
    executor = AssistantScopedToolExecutor(
        gateway=_gateway(),
        task_loader=lambda task_id: (task_state, plan),
        event_store=event_store,
    )
    arguments = {
        "identity_id": "nomi_gmail_primary",
        "recipient": {"contact_id": "contact_alice"},
        "subject": "报价跟进",
        "body_text": "Alice 你好，这里是不能进入 checkpoint 的正文。",
        "source_evidence_ids": ["evt_123"],
        "task_id": "lta_789",
        "idempotency_key": "lta_789:contact_alice:draft:checkpoint",
    }

    first = executor.execute(
        task_id="lta_789",
        tool_name="assistant.email.create_draft",
        arguments=arguments,
    )
    second = executor.execute(
        task_id="lta_789",
        tool_name="assistant.email.create_draft",
        arguments=arguments,
    )

    assert first == second
    events = event_store.task_events("lta_789")
    assert len(events) == 1
    assert events[0]["event_type"] == "assistant.tool.executed"
    assert events[0]["step_id"] == "draft_follow_up"
    assert events[0]["payload"] == {
        "tool_name": "assistant.email.create_draft",
        "status": "confirmation_required",
        "draft_id": first["draft_id"],
    }
    serialized = str(events)
    assert "不能进入 checkpoint 的正文" not in serialized
    assert "alice@example.com" not in serialized
    assert "connected_account_id" not in serialized


def test_scoped_executor_rejects_client_attempt_to_expand_task_scope():
    from app.assistant_identity.tool_gateway import AssistantScopedToolExecutor
    from app.long_tail_agent import LongTailEventStore

    executor = AssistantScopedToolExecutor(
        gateway=_gateway(),
        task_loader=lambda task_id: (
            {
                "task_id": task_id,
                "current_step_id": "read_only",
                "route_decision": {
                    "source_event_ids": ["evt_123"],
                    "permitted_contact_ids": ["contact_alice"],
                },
            },
            {
                "steps": [
                    {
                        "step_id": "read_only",
                        "allowed_actions": ["assistant.identity.get_status"],
                    }
                ]
            },
        ),
        event_store=LongTailEventStore(),
    )

    with pytest.raises(PermissionError, match="assistant_tool_scope_denied"):
        executor.execute(
            task_id="lta_789",
            tool_name="assistant.email.create_draft",
            arguments={
                "task_scope": {
                    "permitted_tool_names": ["assistant.email.create_draft"],
                    "permitted_contact_ids": ["contact_bob"],
                },
                "task_id": "lta_789",
            },
        )


def test_outbound_status_and_cancel_are_task_scoped():
    gateway = _gateway()
    created = gateway.execute(
        "assistant.email.create_draft",
        {
            "identity_id": "nomi_gmail_primary",
            "recipient": {"contact_id": "contact_alice"},
            "subject": "跟进",
            "body_text": "Alice 你好，我是 Nomi。",
            "source_evidence_ids": ["evt_123"],
            "task_id": "lta_789",
            "idempotency_key": "lta_789:contact_alice:draft:status",
        },
        task_scope=_task_scope(),
    )

    status = gateway.execute(
        "assistant.outbound.get_status",
        {"draft_id": created["draft_id"]},
        task_scope=_task_scope(),
    )
    assert status == {
        "draft_id": created["draft_id"],
        "status": "draft",
        "confirmation_required": True,
        "send_called": False,
    }

    with pytest.raises(PermissionError, match="draft_scope_denied"):
        gateway.execute(
            "assistant.outbound.cancel_draft",
            {"draft_id": created["draft_id"]},
            task_scope={**_task_scope(), "task_id": "lta_other"},
        )

    cancelled = gateway.execute(
        "assistant.outbound.cancel_draft",
        {"draft_id": created["draft_id"]},
        task_scope=_task_scope(),
    )
    assert cancelled["status"] == "cancelled"
    assert cancelled["send_called"] is False


def test_identity_status_is_redacted_and_requires_task_scope():
    gateway = _gateway()

    status = gateway.execute(
        "assistant.identity.get_status",
        {"identity_id": "nomi_gmail_primary"},
        task_scope=_task_scope(),
    )

    assert status == {
        "identity_id": "nomi_gmail_primary",
        "display_name": "Nomi",
        "address": "nomi@example.com",
        "status": "connected",
        "capabilities": ["receive", "draft", "send", "thread_reply"],
        "available": True,
    }
    assert "metadata" not in status
    assert "connected_account_id" not in str(status)
