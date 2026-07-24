import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class RecordingGmailAdapter:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def send_message(
        self,
        *,
        sender: str,
        recipient: str,
        subject: str,
        body_text: str,
        thread_id: str = "",
    ) -> dict[str, object]:
        self.calls.append(
            {
                "sender": sender,
                "recipient": recipient,
                "subject": subject,
                "body_text": body_text,
                "thread_id": thread_id,
            }
        )
        return {
            "status": "sent",
            "provider": "recording_gmail",
            "provider_message_id": "gmail-persisted-1",
            "provider_result": {"accepted": True},
        }


class TimeoutGmailAdapter(RecordingGmailAdapter):
    def send_message(self, **values) -> dict[str, object]:
        self.calls.append(dict(values))
        raise TimeoutError("provider response timed out")


class BlockingGmailAdapter(RecordingGmailAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self._lock = threading.Lock()

    def send_message(self, **values) -> dict[str, object]:
        with self._lock:
            self.calls.append(dict(values))
        self.entered.set()
        if not self.release.wait(timeout=2):
            raise TimeoutError("test did not release provider")
        return {
            "status": "sent",
            "provider": "blocking_gmail",
            "provider_message_id": "gmail-concurrent-1",
            "provider_result": {"accepted": True},
        }


def test_outbound_state_and_confirmation_survive_pipeline_recreation(monkeypatch):
    from app.assistant_identity.outbound import OutboundMessagePipeline
    from app.assistant_identity.outbound_repository import InMemoryAssistantOutboundRepository

    monkeypatch.setenv("ASSISTANT_GMAIL_ADDRESS", "nomi@example.com")
    repository = InMemoryAssistantOutboundRepository()
    adapter = RecordingGmailAdapter()
    first_process = OutboundMessagePipeline(
        repository=repository,
        gmail_adapter=adapter,
    )
    draft = first_process.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="跨重启确认",
        body_text="这封邮件只能发送一次。",
        source_evidence_ids=["evt_persisted"],
        idempotency_key="task-1:alice:follow-up:1",
        task_id="task-1",
    )
    confirmation = first_process.issue_confirmation(
        draft["draft_id"],
        actor="local_owner",
    )

    second_process = OutboundMessagePipeline(
        repository=repository,
        gmail_adapter=adapter,
    )
    sent = second_process.confirm_and_send(
        draft["draft_id"],
        confirmation_token=confirmation["confirmation_token"],
        actor="local_owner",
    )
    duplicate_tap = second_process.confirm_and_send(
        draft["draft_id"],
        confirmation_token=confirmation["confirmation_token"],
        actor="local_owner",
    )

    assert sent["status"] == "sent"
    assert duplicate_tap["provider_message_id"] == "gmail-persisted-1"
    assert len(adapter.calls) == 1

    third_process = OutboundMessagePipeline(repository=repository)
    duplicate_draft = third_process.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="跨重启确认",
        body_text="这封邮件只能发送一次。",
        source_evidence_ids=["evt_persisted"],
        idempotency_key="task-1:alice:follow-up:1",
        task_id="task-1",
    )
    assert duplicate_draft["draft_id"] == draft["draft_id"]
    assert duplicate_draft["status"] == "sent"


def test_concurrent_cross_surface_confirmation_claim_calls_provider_only_once(monkeypatch):
    from app.assistant_identity.outbound import OutboundMessagePipeline
    from app.assistant_identity.outbound_repository import InMemoryAssistantOutboundRepository

    monkeypatch.setenv("ASSISTANT_GMAIL_ADDRESS", "nomi@example.com")
    repository = InMemoryAssistantOutboundRepository()
    adapter = BlockingGmailAdapter()
    first_surface = OutboundMessagePipeline(repository=repository, gmail_adapter=adapter)
    second_surface = OutboundMessagePipeline(repository=repository, gmail_adapter=adapter)
    draft = first_surface.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="并发确认",
        body_text="Web 和 Android 同时点击也只能发送一次。",
        source_evidence_ids=["evt-concurrent"],
        idempotency_key="concurrent-send-1",
        task_id="concurrent-send",
    )
    web_confirmation = first_surface.issue_confirmation(
        draft["draft_id"], actor="local_owner"
    )
    android_confirmation = second_surface.issue_confirmation(
        draft["draft_id"], actor="local_owner"
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            first_surface.confirm_and_send,
            draft["draft_id"],
            web_confirmation["confirmation_token"],
            actor="local_owner",
        )
        assert adapter.entered.wait(timeout=1)
        second = pool.submit(
            second_surface.confirm_and_send,
            draft["draft_id"],
            android_confirmation["confirmation_token"],
            actor="local_owner",
        )
        adapter.release.set()
        first.result(timeout=2)
        second.result(timeout=2)

    assert len(adapter.calls) == 1
    assert repository.get_draft(draft["draft_id"])["status"] == "sent"


def test_edit_persists_and_invalidates_confirmation_across_pipeline_recreation():
    from app.assistant_identity.outbound import OutboundMessagePipeline
    from app.assistant_identity.outbound_repository import InMemoryAssistantOutboundRepository

    repository = InMemoryAssistantOutboundRepository()
    first_process = OutboundMessagePipeline(repository=repository)
    draft = first_process.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="旧主题",
        body_text="旧正文",
        source_evidence_ids=["evt_edit"],
        idempotency_key="task-edit:alice:1",
        task_id="task-edit",
    )
    confirmation = first_process.issue_confirmation(
        draft["draft_id"],
        actor="local_owner",
    )
    first_process.edit_draft(
        draft["draft_id"],
        subject="新主题",
        body_text="新正文",
    )

    second_process = OutboundMessagePipeline(repository=repository)
    persisted = second_process.get_draft(draft["draft_id"])
    assert persisted["subject"] == "新主题"
    assert persisted["body_text"] == "新正文"

    try:
        second_process.confirm_and_send(
            draft["draft_id"],
            confirmation_token=confirmation["confirmation_token"],
            actor="local_owner",
        )
    except PermissionError as exc:
        assert "changed" in str(exc).lower() or "invalid" in str(exc).lower()
    else:
        raise AssertionError("edited draft accepted a stale persisted confirmation")


def test_confirmation_issued_during_edit_is_bound_to_original_revision(monkeypatch):
    from app.assistant_identity.outbound import OutboundMessagePipeline
    from app.assistant_identity.outbound_repository import InMemoryAssistantOutboundRepository

    class PausingConfirmationRepository(InMemoryAssistantOutboundRepository):
        def __init__(self):
            super().__init__()
            self.confirmation_ready = threading.Event()
            self.allow_confirmation_save = threading.Event()

        def save_confirmation(self, confirmation):
            self.confirmation_ready.set()
            if not self.allow_confirmation_save.wait(timeout=2):
                raise TimeoutError("test did not release confirmation save")
            return super().save_confirmation(confirmation)

    monkeypatch.setenv("ASSISTANT_GMAIL_ADDRESS", "nomi@example.com")
    repository = PausingConfirmationRepository()
    adapter = RecordingGmailAdapter()
    pipeline = OutboundMessagePipeline(repository=repository, gmail_adapter=adapter)
    draft = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="Revision binding",
        body_text="The content stays unchanged while risk notes change.",
        source_evidence_ids=["evt-revision-binding"],
    )

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending_confirmation = pool.submit(
            pipeline.issue_confirmation,
            draft["draft_id"],
            actor="local_owner",
        )
        assert repository.confirmation_ready.wait(timeout=1)
        pipeline.edit_draft(draft["draft_id"], risk_notes=["new risk review"])
        repository.allow_confirmation_save.set()
        confirmation = pending_confirmation.result(timeout=2)

    try:
        pipeline.confirm_and_send(
            draft["draft_id"],
            confirmation["confirmation_token"],
            actor="local_owner",
        )
    except PermissionError as exc:
        assert "changed" in str(exc).lower() or "invalid" in str(exc).lower()
    else:
        raise AssertionError("confirmation from an older revision was accepted")
    assert adapter.calls == []


def test_sent_draft_cannot_be_edited_cancelled_or_sent_again(monkeypatch):
    from app.assistant_identity.outbound import OutboundMessagePipeline
    from app.assistant_identity.outbound_repository import InMemoryAssistantOutboundRepository

    monkeypatch.setenv("ASSISTANT_GMAIL_ADDRESS", "nomi@example.com")
    repository = InMemoryAssistantOutboundRepository()
    adapter = RecordingGmailAdapter()
    pipeline = OutboundMessagePipeline(repository=repository, gmail_adapter=adapter)
    draft = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="终态保护",
        body_text="发送后不能被旧页面改回草稿。",
        source_evidence_ids=["evt-terminal"],
    )
    confirmation = pipeline.issue_confirmation(draft["draft_id"], actor="local_owner")
    sent = pipeline.confirm_and_send(
        draft["draft_id"],
        confirmation["confirmation_token"],
        actor="local_owner",
    )

    assert sent["status"] == "sent"
    for operation in (
        lambda: pipeline.edit_draft(draft["draft_id"], body_text="过期页面修改"),
        lambda: pipeline.cancel_draft(draft["draft_id"]),
    ):
        try:
            operation()
        except PermissionError as exc:
            assert "status" in str(exc).lower() or "state" in str(exc).lower()
        else:
            raise AssertionError("terminal draft accepted an invalid transition")

    assert pipeline.get_draft(draft["draft_id"])["status"] == "sent"
    assert len(adapter.calls) == 1


def test_editing_blocked_draft_rechecks_policy_and_restores_confirmation():
    from app.assistant_identity.outbound import OutboundMessagePipeline
    from app.assistant_identity.outbound_repository import InMemoryAssistantOutboundRepository

    pipeline = OutboundMessagePipeline(repository=InMemoryAssistantOutboundRepository())
    first = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="第一封",
        body_text="重复正文",
        source_evidence_ids=["evt-first"],
    )
    blocked = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="第二封",
        body_text="重复正文",
        source_evidence_ids=["evt-blocked"],
    )

    assert first["status"] == "draft"
    assert blocked["status"] == "blocked"
    edited = pipeline.edit_draft(
        blocked["draft_id"],
        body_text="这是一封内容完全不同的后续邮件。",
    )

    assert edited["status"] == "draft"
    assert edited["confirmation_required"] is True
    assert edited["confirmation_card"]["actions"] == ["send", "edit", "cancel"]
    assert "reason" not in edited
    assert "policy_result" not in edited


def test_stale_sending_attempt_is_reconciled_to_delivery_unknown_without_retry(monkeypatch):
    from app.assistant_identity.outbound import OutboundMessagePipeline
    from app.assistant_identity.outbound_repository import InMemoryAssistantOutboundRepository

    monkeypatch.setenv("ASSISTANT_GMAIL_ADDRESS", "nomi@example.com")
    now = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
    repository = InMemoryAssistantOutboundRepository()
    adapter = BlockingGmailAdapter()
    pipeline = OutboundMessagePipeline(
        repository=repository,
        gmail_adapter=adapter,
        clock=lambda: now,
    )
    draft = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="崩溃恢复",
        body_text="不能因为恢复而重复发送。",
        source_evidence_ids=["evt-recovery"],
    )
    persisted = repository.get_draft(draft["draft_id"])
    persisted.update(
        {
            "status": "sending",
            "send_called": True,
            "send_attempt_id": "attempt-before-crash",
            "send_lease_expires_at": (now - timedelta(minutes=1)).isoformat(),
            "updated_at": (now - timedelta(minutes=6)).isoformat(),
        }
    )
    repository.save_draft(persisted)

    recovered = pipeline.reconcile_stale_attempts()

    assert recovered == [draft["draft_id"]]
    current = repository.get_draft(draft["draft_id"])
    assert current["status"] == "delivery_unknown"
    assert current["reason"] == "stale_sending_requires_provider_verification"
    assert "verify" in current["recovery_guidance"].lower()
    assert adapter.calls == []


def test_near_duplicate_draft_is_blocked_with_actionable_policy_result():
    from app.assistant_identity.outbound import OutboundMessagePipeline
    from app.assistant_identity.outbound_repository import InMemoryAssistantOutboundRepository

    pipeline = OutboundMessagePipeline(repository=InMemoryAssistantOutboundRepository())
    first = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="跟进",
        body_text="Alice 你好，会议资料已经整理好了。",
        source_evidence_ids=["evt_duplicate_1"],
        idempotency_key="task-dup:1",
        task_id="task-dup",
    )
    duplicate = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="再次跟进",
        body_text="Alice，你好！会议资料已经整理好了",
        source_evidence_ids=["evt_duplicate_1"],
        idempotency_key="task-dup:2",
        task_id="task-dup",
    )

    assert first["status"] == "draft"
    assert duplicate["status"] == "blocked"
    assert duplicate["reason"] == "near_duplicate_outbound"
    assert duplicate["confirmation_required"] is False
    assert duplicate["policy_result"]["matched_draft_id"] == first["draft_id"]
    assert duplicate["confirmation_card"]["actions"] == ["edit", "cancel"]


def test_contact_channel_and_daily_quotas_are_independently_enforced(monkeypatch):
    from app.assistant_identity.outbound import OutboundMessagePipeline
    from app.assistant_identity.outbound_repository import InMemoryAssistantOutboundRepository

    monkeypatch.setenv("ASSISTANT_GMAIL_ADDRESS", "nomi@example.com")

    def send(pipeline, recipient, body, key):
        draft = pipeline.prepare_draft(
            identity_id="nomi_gmail_primary",
            channel="gmail",
            recipient=recipient,
            subject=key,
            body_text=body,
            source_evidence_ids=[key],
            idempotency_key=key,
            task_id=key,
        )
        if draft["status"] == "draft":
            confirmation = pipeline.issue_confirmation(draft["draft_id"], actor="local_owner")
            return pipeline.confirm_and_send(
                draft["draft_id"],
                confirmation["confirmation_token"],
                actor="local_owner",
            )
        return draft

    contact_pipeline = OutboundMessagePipeline(
        repository=InMemoryAssistantOutboundRepository(),
        gmail_adapter=RecordingGmailAdapter(),
        per_contact_daily_limit=1,
        per_channel_daily_limit=10,
        daily_limit=10,
    )
    assert send(contact_pipeline, "alice@example.com", "第一封", "contact-1")["status"] == "sent"
    contact_blocked = send(contact_pipeline, "alice@example.com", "完全不同的第二封", "contact-2")
    assert contact_blocked["reason"] == "per_contact_daily_quota_exceeded"

    channel_pipeline = OutboundMessagePipeline(
        repository=InMemoryAssistantOutboundRepository(),
        gmail_adapter=RecordingGmailAdapter(),
        per_contact_daily_limit=10,
        per_channel_daily_limit=1,
        daily_limit=10,
    )
    assert send(channel_pipeline, "alice@example.com", "渠道第一封", "channel-1")["status"] == "sent"
    channel_blocked = send(channel_pipeline, "bob@example.com", "渠道第二封", "channel-2")
    assert channel_blocked["reason"] == "per_channel_daily_quota_exceeded"

    daily_pipeline = OutboundMessagePipeline(
        repository=InMemoryAssistantOutboundRepository(),
        gmail_adapter=RecordingGmailAdapter(),
        per_contact_daily_limit=10,
        per_channel_daily_limit=10,
        daily_limit=1,
    )
    assert send(daily_pipeline, "alice@example.com", "全局第一封", "daily-1")["status"] == "sent"
    daily_blocked = send(daily_pipeline, "bob@example.com", "全局第二封", "daily-2")
    assert daily_blocked["reason"] == "assistant_daily_quota_exceeded"


def test_provider_timeout_is_persisted_as_unknown_and_duplicate_tap_does_not_resend(monkeypatch):
    from app.assistant_identity.outbound import OutboundMessagePipeline
    from app.assistant_identity.outbound_repository import InMemoryAssistantOutboundRepository

    monkeypatch.setenv("ASSISTANT_GMAIL_ADDRESS", "nomi@example.com")
    adapter = TimeoutGmailAdapter()
    repository = InMemoryAssistantOutboundRepository()
    pipeline = OutboundMessagePipeline(repository=repository, gmail_adapter=adapter)
    draft = pipeline.prepare_draft(
        identity_id="nomi_gmail_primary",
        channel="gmail",
        recipient="alice@example.com",
        subject="超时",
        body_text="提供方是否接收未知。",
        source_evidence_ids=["evt_timeout"],
        idempotency_key="timeout:1",
        task_id="timeout-task",
    )
    confirmation = pipeline.issue_confirmation(draft["draft_id"], actor="local_owner")

    first = pipeline.confirm_and_send(
        draft["draft_id"],
        confirmation["confirmation_token"],
        actor="local_owner",
    )
    second = OutboundMessagePipeline(
        repository=repository,
        gmail_adapter=adapter,
    ).confirm_and_send(
        draft["draft_id"],
        confirmation["confirmation_token"],
        actor="local_owner",
    )

    assert first["status"] == "delivery_unknown"
    assert first["reason"] == "provider_timeout_requires_verification"
    assert second == first
    assert len(adapter.calls) == 1
