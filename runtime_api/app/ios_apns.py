from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def build_live_activity_apns_payload(
    content_state: dict[str, Any],
    event: str = "update",
    stale_after_seconds: int = 600,
) -> dict[str, Any]:
    now = int(time.time())
    return {
        "aps": {
            "timestamp": now,
            "event": event,
            "content-state": content_state,
            "stale-date": now + max(60, stale_after_seconds),
        }
    }


def build_alert_apns_payload(title: str, body: str, deep_link: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "aps": {
            "alert": {
                "title": title,
                "body": body,
            },
            "sound": "default",
        }
    }
    if deep_link:
        payload["deep_link"] = deep_link
    return payload


@dataclass(frozen=True)
class APNsConfig:
    team_id: str
    key_id: str
    bundle_id: str
    private_key_p8: str
    environment: str = "sandbox"

    @property
    def base_url(self) -> str:
        if self.environment == "production":
            return "https://api.push.apple.com"
        return "https://api.sandbox.push.apple.com"

    @property
    def live_activity_topic(self) -> str:
        return f"{self.bundle_id}.push-type.liveactivity"

    @property
    def alert_topic(self) -> str:
        return self.bundle_id


def apns_config_from_env() -> APNsConfig:
    return APNsConfig(
        team_id=os.getenv("APNS_TEAM_ID", "").strip(),
        key_id=os.getenv("APNS_KEY_ID", "").strip(),
        bundle_id=os.getenv("APNS_BUNDLE_ID", "").strip(),
        private_key_p8=os.getenv("APNS_PRIVATE_KEY_P8", "").replace("\\n", "\n").strip(),
        environment=os.getenv("APNS_ENVIRONMENT", "sandbox").strip() or "sandbox",
    )


def apns_jwt(config: APNsConfig, issued_at: int | None = None) -> str:
    issued_at = issued_at or int(time.time())
    header = {"alg": "ES256", "kid": config.key_id}
    claims = {"iss": config.team_id, "iat": issued_at}
    signing_input = (
        f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_b64url(json.dumps(claims, separators=(',', ':')).encode())}"
    )
    private_key = serialization.load_pem_private_key(config.private_key_p8.encode("utf-8"), password=None)
    if not isinstance(private_key, ec.EllipticCurvePrivateKey):
        raise ValueError("APNs private key must be an EC private key")
    der_signature = private_key.sign(signing_input.encode("ascii"), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_signature)
    raw_signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"{signing_input}.{_b64url(raw_signature)}"


class APNsLiveActivityClient:
    def __init__(self, config: APNsConfig | None = None):
        self.config = config or apns_config_from_env()

    def configured(self) -> bool:
        return all([self.config.team_id, self.config.key_id, self.config.bundle_id, self.config.private_key_p8])

    async def send_update(self, update_token: str, content_state: dict[str, Any]) -> dict[str, Any]:
        if not self.configured():
            return {"status": "misconfigured", "status_code": 0, "error": "APNs configuration missing"}
        payload = build_live_activity_apns_payload(content_state)
        headers = {
            "authorization": f"bearer {apns_jwt(self.config)}",
            "apns-topic": self.config.live_activity_topic,
            "apns-push-type": "liveactivity",
            "apns-priority": "10",
        }
        async with httpx.AsyncClient(http2=True, timeout=10.0) as client:
            response = await client.post(
                f"{self.config.base_url}/3/device/{update_token}",
                headers=headers,
                json=payload,
            )
        if 200 <= response.status_code < 300:
            return {"status": "sent", "status_code": response.status_code, "payload": payload}
        return {"status": "failed", "status_code": response.status_code, "error": response.text[:500], "payload": payload}

    async def send_alert(self, device_token: str, title: str, body: str, deep_link: str = "") -> dict[str, Any]:
        if not self.configured():
            return {"status": "misconfigured", "status_code": 0, "error": "APNs configuration missing"}
        payload = build_alert_apns_payload(title=title, body=body, deep_link=deep_link)
        headers = {
            "authorization": f"bearer {apns_jwt(self.config)}",
            "apns-topic": self.config.alert_topic,
            "apns-push-type": "alert",
            "apns-priority": "10",
        }
        async with httpx.AsyncClient(http2=True, timeout=10.0) as client:
            response = await client.post(
                f"{self.config.base_url}/3/device/{device_token}",
                headers=headers,
                json=payload,
            )
        if 200 <= response.status_code < 300:
            return {"status": "sent", "status_code": response.status_code, "payload": payload}
        return {"status": "failed", "status_code": response.status_code, "error": response.text[:500], "payload": payload}
