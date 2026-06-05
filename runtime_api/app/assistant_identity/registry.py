from __future__ import annotations

import os
from collections import OrderedDict

from app.assistant_identity.models import AssistantIdentity


ALLOWED_IDENTITY_KINDS = {"assistant_gmail", "assistant_whatsapp", "assistant_phone"}


class AssistantIdentityRegistry:
    def __init__(self) -> None:
        self._identities: OrderedDict[str, AssistantIdentity] = OrderedDict()

    def bootstrap_defaults(self) -> list[AssistantIdentity]:
        if not self._identities:
            self.add(
                AssistantIdentity(
                    identity_id="nomi_gmail_primary",
                    kind="assistant_gmail",
                    display_name="Nomi",
                    address=os.getenv("ASSISTANT_GMAIL_ADDRESS", "nomi@example.com"),
                    capabilities=["receive", "draft", "send", "thread_reply"],
                    status=os.getenv("ASSISTANT_GMAIL_STATUS", "configured"),
                )
            )
            self.add(
                AssistantIdentity(
                    identity_id="nomi_whatsapp_primary",
                    kind="assistant_whatsapp",
                    display_name="Nomi",
                    address=os.getenv("ASSISTANT_WHATSAPP_NUMBER", "+00000000000"),
                    capabilities=["receive", "send_text", "delivery_receipt"],
                    status=os.getenv("ASSISTANT_WHATSAPP_STATUS", "configured"),
                )
            )
            self.add(
                AssistantIdentity(
                    identity_id="nomi_phone_primary",
                    kind="assistant_phone",
                    display_name="Nomi",
                    address=os.getenv("ASSISTANT_PHONE_NUMBER", "+00000000000"),
                    capabilities=[
                        "receive_sms",
                        "send_sms",
                        "outbound_call_playback",
                        "inbound_call_greeting",
                        "delivery_receipt",
                        "call_status",
                    ],
                    status=os.getenv("ASSISTANT_PHONE_STATUS", "configured"),
                )
            )
        return self.list()

    def add(self, identity: AssistantIdentity) -> AssistantIdentity:
        if identity.kind not in ALLOWED_IDENTITY_KINDS:
            raise ValueError("Only Nomi-owned identity kinds are allowed.")
        display_name = identity.display_name.strip() or "Nomi"
        normalized = AssistantIdentity(
            identity_id=identity.identity_id.strip(),
            kind=identity.kind.strip(),
            display_name=display_name,
            address=identity.address.strip(),
            capabilities=list(identity.capabilities),
            status=identity.status.strip() or "configured",
            metadata=dict(identity.metadata),
        )
        self._identities[normalized.identity_id] = normalized
        return normalized

    def list(self) -> list[AssistantIdentity]:
        return list(self._identities.values())

    def get(self, identity_id: str) -> AssistantIdentity | None:
        if not self._identities:
            self.bootstrap_defaults()
        return self._identities.get(identity_id)

    def connect_kind(self, kind: str) -> AssistantIdentity:
        if kind not in ALLOWED_IDENTITY_KINDS:
            raise ValueError("Only Nomi-owned identity kinds are allowed.")
        self.bootstrap_defaults()
        for identity in self._identities.values():
            if identity.kind == kind:
                connected = AssistantIdentity(
                    identity_id=identity.identity_id,
                    kind=identity.kind,
                    display_name=identity.display_name,
                    address=identity.address,
                    capabilities=list(identity.capabilities),
                    status="connected",
                    metadata=dict(identity.metadata),
                )
                self._identities[connected.identity_id] = connected
                return connected
        raise KeyError(kind)

    def update(self, identity_id: str, *, display_name: str | None = None, status: str | None = None) -> AssistantIdentity:
        self.bootstrap_defaults()
        identity = self._identities[identity_id]
        updated = AssistantIdentity(
            identity_id=identity.identity_id,
            kind=identity.kind,
            display_name=display_name if display_name is not None else identity.display_name,
            address=identity.address,
            capabilities=list(identity.capabilities),
            status=status if status is not None else identity.status,
            metadata=dict(identity.metadata),
        )
        self._identities[updated.identity_id] = updated
        return updated
