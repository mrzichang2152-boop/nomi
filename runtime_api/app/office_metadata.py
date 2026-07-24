from __future__ import annotations

import re


OFFICE_CORE_PROPERTY_LIMIT = 255


def office_core_property(value: object, *, limit: int = OFFICE_CORE_PROPERTY_LIMIT) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    return normalized[: max(0, int(limit))]
