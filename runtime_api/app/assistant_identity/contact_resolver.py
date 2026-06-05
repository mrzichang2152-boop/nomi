from __future__ import annotations

import hashlib
import re
from typing import Any


class ContactResolver:
    def __init__(
        self,
        *,
        user_keys: set[str] | None = None,
        known_contacts: dict[str, str] | None = None,
    ) -> None:
        self.user_keys = {self.normalize_key(key) for key in (user_keys or set()) if self.normalize_key(key)}
        self.known_contacts = {
            self.normalize_key(key): value
            for key, value in (known_contacts or {}).items()
            if self.normalize_key(key) and value
        }

    def classify_sender(self, value: str) -> dict[str, Any]:
        normalized = self.normalize_key(value)
        sender_key = self.hash_key(normalized)
        if normalized in self.user_keys:
            return {
                "sender_class": "user",
                "contact_id": "",
                "counterparty_ids": [],
                "sender_key": sender_key,
                "normalized": normalized,
            }
        contact_id = self.known_contacts.get(normalized)
        if contact_id:
            return {
                "sender_class": "known_contact",
                "contact_id": contact_id,
                "counterparty_ids": [contact_id],
                "sender_key": sender_key,
                "normalized": normalized,
            }
        return {
            "sender_class": "unknown",
            "contact_id": "",
            "counterparty_ids": [],
            "sender_key": sender_key,
            "normalized": normalized,
        }

    def normalize_key(self, value: str) -> str:
        clean = str(value or "").strip().lower()
        if "@" in clean:
            return clean
        digits = re.sub(r"[^\d+]", "", clean)
        return digits or clean

    def hash_key(self, value: str) -> str:
        return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
