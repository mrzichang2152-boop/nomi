from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "source",
}


class UnsafeUrlError(ValueError):
    pass


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(str(url or "").strip())
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if not scheme or not hostname:
        return str(url or "").strip()
    port = parsed.port
    include_port = port is not None and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80))
    netloc = hostname if not include_port else f"{hostname}:{port}"
    path = parsed.path or ""
    if path != "/":
        path = path.rstrip("/")
    else:
        path = ""
    query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in TRACKING_QUERY_KEYS:
            continue
        query.append((key, value))
    query.sort()
    return urlunsplit((scheme, netloc, path, urlencode(query, doseq=True), ""))


def _default_resolver(hostname: str) -> list[str]:
    return list(
        dict.fromkeys(
            item[4][0]
            for item in socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        )
    )


def _is_forbidden_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return True
    return not address.is_global


def validate_public_url(
    url: str,
    *,
    resolver: Callable[[str], list[str]] | None = None,
) -> str:
    value = str(url or "").strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeUrlError("only_http_and_https_are_allowed")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("url_userinfo_is_not_allowed")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise UnsafeUrlError("hostname_is_required")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise UnsafeUrlError("local_hostname_is_not_allowed")
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if _is_forbidden_ip(hostname):
            raise UnsafeUrlError("private_or_reserved_ip_is_not_allowed")
        return value
    resolved = (resolver or _default_resolver)(hostname)
    if not resolved:
        raise UnsafeUrlError("hostname_did_not_resolve")
    if any(_is_forbidden_ip(item) for item in resolved):
        raise UnsafeUrlError("hostname_resolved_to_private_or_reserved_ip")
    return value
