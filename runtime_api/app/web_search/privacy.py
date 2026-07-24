from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s()-]{7,}\d)(?!\d)")
SECRET_RE = re.compile(
    r"(?i)(?:"
    r"\b(?:password|passwd|pwd|api[_\s-]?key|access[_\s-]?token|secret(?:[_\s-]?key)?|token)\b"
    r"|(?:密码|口令|API\s*密钥|访问令牌|密钥|令牌)"
    r")\s*(?::|：|=|是|为)\s*"
    r"(?!(?:什么|多少|哪里|哪个|哪一个)(?:[？?，,。；;\s]|$))"
    r"[^\s,，;；。]+"
)
BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}=*")
SECRET_SEARCH_BOILERPLATE_RE = re.compile(
    r"(?i)(?:请|麻烦|帮我|给我|我的|邮箱|账号|账户|"
    r"gmail|api|联网|上网|在网上|网络|搜索|查询|查一下|查查|一下)"
)


@dataclass(frozen=True)
class PreparedQuery:
    query: str
    query_hash: str
    sensitivity: str
    redacted_types: tuple[str, ...]
    blocked: bool
    reason: str = ""


def _replace(pattern: re.Pattern[str], text: str, label: str, redacted: list[str]) -> str:
    if pattern.search(text):
        redacted.append(label)
        return pattern.sub(" ", text)
    return text


def prepare_public_query(query: str) -> PreparedQuery:
    original = str(query or "").strip()
    redacted: list[str] = []
    sanitized = _replace(EMAIL_RE, original, "email", redacted)
    sanitized = _replace(PHONE_RE, sanitized, "phone", redacted)
    sanitized = _replace(SECRET_RE, sanitized, "secret", redacted)
    sanitized = _replace(BEARER_RE, sanitized, "secret", redacted)
    sanitized = re.sub(r"\s+", " ", sanitized).strip(" ,，;；。")
    meaningful = re.sub(
        r"(?i)\b(?:password|passwd|pwd|api[_-]?key|access[_-]?token|secret|token)\b|"
        r"(?:密码|口令|API\s*密钥|访问令牌|密钥|令牌)|[\s=:：,，;；。]",
        "",
        sanitized,
    )
    if "secret" in redacted:
        meaningful = SECRET_SEARCH_BOILERPLATE_RE.sub("", meaningful)
        meaningful = re.sub(r"[\s=:：,，;；。？?]", "", meaningful)
    blocked = bool(original) and len(meaningful) < 4
    if blocked:
        sanitized = ""
    unique_types = tuple(dict.fromkeys(redacted))
    sensitivity = "blocked" if blocked else ("derived_private" if unique_types else "public")
    return PreparedQuery(
        query=sanitized,
        query_hash=hashlib.sha256(original.encode("utf-8")).hexdigest(),
        sensitivity=sensitivity,
        redacted_types=unique_types,
        blocked=blocked,
        reason="query_contains_only_credentials_or_private_identifiers" if blocked else "",
    )
