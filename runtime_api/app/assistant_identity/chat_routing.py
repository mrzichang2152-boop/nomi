from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.assistant_identity.routing import AssistantCommunicationTriggerRouter


NOMI_GMAIL_IDENTITY_ID = "nomi_gmail_primary"
_EMAIL_RE = re.compile(
    r"(?<![A-Z0-9.!#$%&'*+/=?^_`{|}~-])([A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9-]+(?:\.[A-Z0-9-]+)+)(?![A-Z0-9.-])",
    re.IGNORECASE,
)
_OWNED_GMAIL_PATTERNS = (
    re.compile(r"用(?:你|nomi|助理)(?:自己)?的?(?:gmail)?邮箱", re.IGNORECASE),
    re.compile(r"用(?:你|nomi|助理)(?:自己)?的?gmail", re.IGNORECASE),
    re.compile(r"让nomi用(?:他|自己)的?(?:gmail)?邮箱", re.IGNORECASE),
)
_OUTBOUND_MAIL_RE = re.compile(r"(?:发|写)(?:一封|个)?(?:电子)?邮件", re.IGNORECASE)


@dataclass(frozen=True)
class NomiGmailCommand:
    recipient: str
    subject: str
    body_text: str


def parse_nomi_gmail_command(text: str) -> NomiGmailCommand | None:
    request = str(text or "").strip()
    compact = re.sub(r"\s+", "", request)
    if not request or not _OUTBOUND_MAIL_RE.search(compact):
        return None
    if not any(pattern.search(compact) for pattern in _OWNED_GMAIL_PATTERNS):
        return None

    email_match = _EMAIL_RE.search(request)
    recipient = email_match.group(1) if email_match else ""
    subject = _extract_subject(request)
    body_text = _extract_body_text(request, email_match=email_match)
    if not subject and body_text:
        subject = "提醒" if body_text.startswith("提醒") else "来自 Nomi 的消息"
    return NomiGmailCommand(
        recipient=recipient,
        subject=subject,
        body_text=body_text,
    )


def prepare_nomi_gmail_chat_action(
    text: str,
    *,
    event_id: str,
    client_request_id: str | None,
    identity_registry: Any,
    outbound_pipeline: Any,
) -> dict[str, Any] | None:
    command = parse_nomi_gmail_command(text)
    if command is None:
        return None

    route_decision = AssistantCommunicationTriggerRouter().route(
        {
            "trigger_source": "user_explicit_send_request",
            "text": text,
            "channel_hint": "gmail",
            "recipient_hint": command.recipient,
            "source_evidence_ids": [event_id] if event_id else [],
        }
    )
    missing_slots = []
    if not command.recipient:
        missing_slots.append("recipient_email")
    if not command.body_text:
        missing_slots.append("body_text")
    if missing_slots:
        if missing_slots == ["recipient_email"]:
            answer = "可以，请告诉我收件人邮箱地址。我会先用 Nomi 自己的 Gmail 生成草稿，发送前仍需你确认。"
        elif missing_slots == ["body_text"]:
            answer = "可以，请告诉我邮件正文要写什么。我会先用 Nomi 自己的 Gmail 生成草稿，发送前仍需你确认。"
        else:
            answer = "可以，请告诉我收件人邮箱地址和邮件正文。我会先生成草稿，发送前仍需你确认。"
        return {
            "status": "needs_user_input",
            "answer": answer,
            "missing_slots": missing_slots,
            "route_decision": route_decision,
        }

    identity = identity_registry.get(NOMI_GMAIL_IDENTITY_ID)
    capabilities = {
        str(item or "").strip().lower()
        for item in getattr(identity, "capabilities", []) or []
    }
    if (
        identity is None
        or str(getattr(identity, "status", "") or "").strip().lower() != "connected"
        or not str(getattr(identity, "address", "") or "").strip()
        or not {"draft", "send"}.issubset(capabilities)
    ):
        return {
            "status": "identity_unavailable",
            "answer": "Nomi 自己的 Gmail 目前未连接或缺少发信权限。请先在“账号 > Nomi 助理身份”中完成 Gmail 授权。",
            "route_decision": route_decision,
        }

    request_key = str(client_request_id or event_id or "").strip()
    draft = outbound_pipeline.prepare_draft(
        identity_id=NOMI_GMAIL_IDENTITY_ID,
        channel="gmail",
        recipient=command.recipient,
        subject=command.subject,
        body_text=command.body_text,
        source_evidence_ids=[event_id] if event_id else [],
        risk_notes=["third_party_send_requires_confirmation"],
        idempotency_key=f"chat:{request_key}:nomi-gmail",
        task_id=f"chat:{event_id}",
    )
    answer = (
        f"我已用 Nomi 自己的 Gmail 为 {command.recipient} 准备好邮件草稿。\n"
        f"主题：{command.subject}\n"
        f"正文：{command.body_text}\n"
        "邮件尚未发送，请在下方确认卡中检查、编辑或发送。"
    )
    return {
        "status": "draft_ready",
        "answer": answer,
        "draft": draft,
        "route_decision": route_decision,
    }


def _extract_subject(text: str) -> str:
    match = re.search(
        r"主题\s*(?:是|为|[:：])\s*(.+?)(?=(?:正文|内容)\s*(?:是|为|[:：])|$)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return ""
    return _clean_fragment(match.group(1), add_terminal_punctuation=False)[:120]


def _extract_body_text(text: str, *, email_match: re.Match[str] | None) -> str:
    explicit = re.search(
        r"(?:正文|内容)\s*(?:是|为|[:：])\s*(.+)$",
        text,
        re.IGNORECASE,
    )
    if explicit:
        return _normalize_recipient_message(explicit.group(1))

    tail_start = email_match.end() if email_match else 0
    tail = text[tail_start:]
    tail = re.sub(r"^\s*(?:这个)?邮箱\s*", "", tail, flags=re.IGNORECASE)
    mail_action = _OUTBOUND_MAIL_RE.search(tail)
    if mail_action:
        tail = tail[mail_action.end():]
    else:
        request_action = _OUTBOUND_MAIL_RE.search(text)
        tail = text[request_action.end():] if request_action else ""
    tail = re.sub(r"^\s*(?:给\s*)?", "", tail)
    tail = re.sub(r"^\s*(?:说|写(?:上|着)?|内容(?:是|为)?|正文(?:是|为)?)\s*", "", tail)
    return _normalize_recipient_message(tail)


def _normalize_recipient_message(value: str) -> str:
    text = _clean_fragment(value, add_terminal_punctuation=False)
    text = re.sub(r"^提醒\s*(?:他|她|对方|收件人)", "提醒您", text)
    if text and text[-1] not in "。！？!?；;":
        text += "。"
    return text


def _clean_fragment(value: str, *, add_terminal_punctuation: bool) -> str:
    text = str(value or "").strip(" \t\r\n,，:：;；")
    text = re.sub(r"\s+", " ", text)
    if add_terminal_punctuation and text and text[-1] not in "。！？!?；;":
        text += "。"
    return text
