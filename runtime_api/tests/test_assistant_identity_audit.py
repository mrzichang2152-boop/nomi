import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class RecordingGmailAdapter:
    def send_message(self, **values) -> dict[str, object]:
        return {
            "status": "sent",
            "provider": "recording_gmail",
            "provider_message_id": "gmail-audit-1",
            "provider_result": {
                "status_code": 200,
                "body": {"echo": values["body_text"]},
            },
        }


def test_outbound_audit_is_complete_append_only_and_redacted(monkeypatch):
    from app.assistant_identity.audit import AssistantIdentityAuditor, InMemoryAssistantAuditRepository
    from app.assistant_identity.outbound import OutboundMessagePipeline

    monkeypatch.setenv("ASSISTANT_GMAIL_ADDRESS", "nomi@example.com")
    repository = InMemoryAssistantAuditRepository()
    pipeline = OutboundMessagePipeline(
        gmail_adapter=RecordingGmailAdapter(),
        auditor=AssistantIdentityAuditor(repository),
    )
    draft = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice.private@example.com",
        subject="私密主题",
        body_text="绝不能进入审计的私密正文",
        source_evidence_ids=["evt_audit"],
        idempotency_key="audit-task:1",
        task_id="audit-task",
    )
    confirmation = pipeline.issue_confirmation(draft["draft_id"], actor="local_owner")
    sent = pipeline.confirm_and_send(
        draft["draft_id"],
        confirmation["confirmation_token"],
        actor="local_owner",
    )
    receipt = pipeline.record_delivery_receipt(
        identity_id="nomi_gmail_primary",
        provider_message_id="gmail-audit-1",
        status="delivered",
        receipt_payload={"body": "private receipt payload", "provider_status": "accepted"},
    )

    events = repository.list(identity_id="nomi_gmail_primary")
    assert [event["action"] for event in events] == [
        "outbound.draft_created",
        "outbound.confirmation_issued",
        "outbound.send_completed",
        "outbound.delivery_receipt",
    ]
    assert all(event["trace_id"] for event in events)
    assert all(event["identity_id"] == "nomi_gmail_primary" for event in events)
    assert sent["audit_trace_id"] == events[-2]["trace_id"]
    assert receipt["audit_trace_id"] == events[-1]["trace_id"]
    serialized = str(events)
    assert "alice.private@example.com" not in serialized
    assert "绝不能进入审计的私密正文" not in serialized
    assert confirmation["confirmation_token"] not in serialized
    assert "gmail-audit-1" in serialized
    assert "private receipt payload" not in serialized
    assert receipt["status"] == "delivered"


def test_block_edit_cancel_and_timeout_each_append_truthful_audit(monkeypatch):
    from app.assistant_identity.audit import AssistantIdentityAuditor, InMemoryAssistantAuditRepository
    from app.assistant_identity.outbound import OutboundMessagePipeline

    class TimeoutAdapter:
        def send_message(self, **values):
            raise TimeoutError("private provider timeout payload")

    monkeypatch.setenv("ASSISTANT_GMAIL_ADDRESS", "nomi@example.com")
    repository = InMemoryAssistantAuditRepository()
    pipeline = OutboundMessagePipeline(
        gmail_adapter=TimeoutAdapter(),
        auditor=AssistantIdentityAuditor(repository),
    )
    first = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="跟进",
        body_text="重复正文",
        source_evidence_ids=["evt_audit_2"],
        idempotency_key="audit-2:1",
        task_id="audit-2",
    )
    blocked = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="跟进二",
        body_text="重复正文！",
        source_evidence_ids=["evt_audit_2"],
        idempotency_key="audit-2:2",
        task_id="audit-2",
    )
    pipeline.edit_draft(blocked["draft_id"], body_text="修改后仍不发送")
    pipeline.cancel_draft(blocked["draft_id"])
    confirmation = pipeline.issue_confirmation(first["draft_id"], actor="local_owner")
    timeout = pipeline.confirm_and_send(
        first["draft_id"],
        confirmation["confirmation_token"],
        actor="local_owner",
    )

    actions = [event["action"] for event in repository.list()]
    assert actions == [
        "outbound.draft_created",
        "outbound.draft_blocked",
        "outbound.draft_edited",
        "outbound.draft_cancelled",
        "outbound.confirmation_issued",
        "outbound.send_timeout",
    ]
    assert timeout["status"] == "delivery_unknown"
    assert "private provider timeout payload" not in str(repository.list())


def test_identity_lifecycle_appends_redacted_transition_audit():
    from app.assistant_identity.audit import AssistantIdentityAuditor, InMemoryAssistantAuditRepository
    from app.assistant_identity.lifecycle import AssistantIdentityLifecycle
    from app.assistant_identity.registry import AssistantIdentityRegistry
    from app.assistant_identity.repository import InMemoryAssistantIdentityRepository

    identity_repository = InMemoryAssistantIdentityRepository()
    registry = AssistantIdentityRegistry(repository=identity_repository)
    identity = registry.bootstrap_defaults()[0]
    audit_repository = InMemoryAssistantAuditRepository()
    lifecycle = AssistantIdentityLifecycle(
        identity_repository,
        auditor=AssistantIdentityAuditor(audit_repository),
    )

    lifecycle.request_authorization(identity.identity_id)
    lifecycle.begin_verification(identity.identity_id)
    lifecycle.provider_verified(
        identity.identity_id,
        provider="composio_gmail",
        address="nomi.private@example.com",
        capabilities=["draft", "send"],
    )
    lifecycle.disable(identity.identity_id)

    events = audit_repository.list(identity_id=identity.identity_id)
    assert [event["action"] for event in events] == [
        "identity.authorization_requested",
        "identity.verification_started",
        "identity.provider_verified",
        "identity.disabled",
    ]
    assert [event["actor"] for event in events] == [
        "local_owner",
        "system",
        "provider",
        "local_owner",
    ]
    assert "nomi.private@example.com" not in str(events)


def test_profile_update_and_blocked_direct_tool_attempt_are_audited():
    from app.assistant_identity.audit import AssistantIdentityAuditor, InMemoryAssistantAuditRepository
    from app.assistant_identity.outbound import OutboundMessagePipeline
    from app.assistant_identity.registry import AssistantIdentityRegistry
    from app.assistant_identity.tool_gateway import AssistantToolGateway

    audit_repository = InMemoryAssistantAuditRepository()
    auditor = AssistantIdentityAuditor(audit_repository)
    registry = AssistantIdentityRegistry(auditor=auditor)
    identity = registry.bootstrap_defaults()[0]
    registry.update_profile(
        identity.identity_id,
        display_name="Nomi 工作助理",
        style={"tone": "concise"},
    )
    gateway = AssistantToolGateway(
        registry=registry,
        outbound=OutboundMessagePipeline(auditor=auditor),
        auditor=auditor,
    )

    try:
        gateway.execute(
            "GMAIL_SEND_EMAIL",
            {
                "identity_id": identity.identity_id,
                "recipient": "alice.private@example.com",
                "body_text": "不可审计的私密正文",
            },
            task_scope={"task_id": "task-blocked", "permitted_tool_names": []},
        )
    except PermissionError as exc:
        assert "not_allowed" in str(exc)
    else:
        raise AssertionError("provider tool bypass was not blocked")

    events = audit_repository.list(identity_id=identity.identity_id)
    assert [event["action"] for event in events] == [
        "identity.profile_updated",
        "assistant_tool.blocked",
    ]
    assert events[-1]["policy_result"] == "assistant_tool_not_allowed"
    assert "alice.private@example.com" not in str(events)
    assert "不可审计的私密正文" not in str(events)
