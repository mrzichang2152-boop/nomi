from __future__ import annotations

import os
import secrets


def configured_password() -> str:
    return os.getenv("APP_PASSWORD", "par-dev")


def is_authorized(password: str | None) -> bool:
    expected = configured_password()
    if not password or not expected:
        return False
    return secrets.compare_digest(password, expected)
