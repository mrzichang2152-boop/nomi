from __future__ import annotations

import json
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Union
from uuid import UUID


@dataclass(frozen=True)
class QueueItem:
    attachment_id: UUID
    processing_version: str

    @property
    def key(self) -> str:
        return f"{self.attachment_id}:{self.processing_version}"

    def encode(self) -> str:
        return json.dumps(
            {
                "attachment_id": str(self.attachment_id),
                "processing_version": self.processing_version,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def decode(cls, value: str | bytes) -> "QueueItem":
        payload = json.loads(value.decode() if isinstance(value, bytes) else value)
        return cls(UUID(payload["attachment_id"]), str(payload["processing_version"]))


@dataclass(frozen=True)
class QueueLease:
    item: QueueItem
    worker_id: str
    expires_at: datetime


class InMemoryAttachmentQueue:
    def __init__(self) -> None:
        self._pending: deque[QueueItem] = deque()
        self._known_keys: set[str] = set()
        self._leases: dict[str, QueueLease] = {}
        self._completed_keys: set[str] = set()
        self._lock = threading.RLock()

    def enqueue(self, attachment_id: UUID, processing_version: str = "attachment-v1") -> bool:
        item = QueueItem(attachment_id, processing_version)
        with self._lock:
            if item.key in self._known_keys or item.key in self._completed_keys:
                return False
            self._known_keys.add(item.key)
            self._pending.append(item)
            return True

    def claim(
        self,
        worker_id: str,
        *,
        lease_seconds: int,
        now: Optional[datetime] = None,
    ) -> Optional[QueueItem]:
        active_now = now or datetime.now(timezone.utc)
        with self._lock:
            if not self._pending:
                return None
            item = self._pending.popleft()
            self._leases[item.key] = QueueLease(
                item=item,
                worker_id=worker_id,
                expires_at=active_now + timedelta(seconds=lease_seconds),
            )
            return item

    def ack(self, item: QueueItem, worker_id: str) -> bool:
        with self._lock:
            lease = self._leases.get(item.key)
            if lease is None or lease.worker_id != worker_id:
                return False
            del self._leases[item.key]
            self._known_keys.discard(item.key)
            self._completed_keys.add(item.key)
            return True

    def release(self, item: QueueItem, worker_id: str) -> bool:
        with self._lock:
            lease = self._leases.get(item.key)
            if lease is None or lease.worker_id != worker_id:
                return False
            del self._leases[item.key]
            self._pending.appendleft(item)
            return True

    def recover_expired(self, *, now: Optional[datetime] = None) -> int:
        active_now = now or datetime.now(timezone.utc)
        with self._lock:
            expired = sorted(
                (lease for lease in self._leases.values() if lease.expires_at <= active_now),
                key=lambda lease: (lease.expires_at, lease.item.key),
            )
            for lease in expired:
                self._leases.pop(lease.item.key, None)
                self._pending.append(lease.item)
            return len(expired)

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    @property
    def inflight_count(self) -> int:
        with self._lock:
            return len(self._leases)

    @property
    def completed_keys(self) -> set[str]:
        with self._lock:
            return set(self._completed_keys)


class RedisAttachmentQueue:
    def __init__(
        self,
        client: Union[object, Callable[[], object]],
        *,
        queue_name: str = "nomi:attachments:pending",
        inflight_name: str = "nomi:attachments:inflight",
        lease_name: str = "nomi:attachments:leases",
        dedupe_ttl_seconds: int = 7 * 24 * 3600,
    ) -> None:
        self._client_or_factory = client
        self.queue_name = queue_name
        self.inflight_name = inflight_name
        self.lease_name = lease_name
        self.dedupe_ttl_seconds = dedupe_ttl_seconds

    @property
    def client(self) -> object:
        if callable(self._client_or_factory):
            return self._client_or_factory()
        return self._client_or_factory

    def _known_key(self, item: QueueItem) -> str:
        return f"nomi:attachments:known:{item.key}"

    def _done_key(self, item: QueueItem) -> str:
        return f"nomi:attachments:done:{item.key}"

    def enqueue(self, attachment_id: UUID, processing_version: str = "attachment-v1") -> bool:
        item = QueueItem(attachment_id, processing_version)
        if self.client.exists(self._done_key(item)):
            return False
        acquired = self.client.set(
            self._known_key(item),
            "1",
            nx=True,
            ex=self.dedupe_ttl_seconds,
        )
        if not acquired:
            return False
        try:
            self.client.rpush(self.queue_name, item.encode())
        except Exception:
            self.client.delete(self._known_key(item))
            raise
        return True

    def claim(
        self,
        worker_id: str,
        *,
        lease_seconds: int,
        now: Optional[datetime] = None,
    ) -> Optional[QueueItem]:
        encoded = self.client.lmove(self.queue_name, self.inflight_name, "LEFT", "RIGHT")
        if encoded is None:
            return None
        item = QueueItem.decode(encoded)
        active_now = now or datetime.now(timezone.utc)
        lease_payload = json.dumps(
            {
                "worker_id": worker_id,
                "expires_at": (active_now + timedelta(seconds=lease_seconds)).isoformat(),
                "item": item.encode(),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        self.client.hset(self.lease_name, item.key, lease_payload)
        return item

    def _lease(self, item: QueueItem) -> Optional[dict[str, str]]:
        payload = self.client.hget(self.lease_name, item.key)
        if payload is None:
            return None
        return json.loads(payload.decode() if isinstance(payload, bytes) else payload)

    def ack(self, item: QueueItem, worker_id: str) -> bool:
        lease = self._lease(item)
        if lease is None or lease.get("worker_id") != worker_id:
            return False
        self.client.lrem(self.inflight_name, 1, item.encode())
        self.client.hdel(self.lease_name, item.key)
        self.client.delete(self._known_key(item))
        self.client.set(self._done_key(item), "1", ex=self.dedupe_ttl_seconds)
        return True

    def release(self, item: QueueItem, worker_id: str) -> bool:
        lease = self._lease(item)
        if lease is None or lease.get("worker_id") != worker_id:
            return False
        self.client.lrem(self.inflight_name, 1, item.encode())
        self.client.hdel(self.lease_name, item.key)
        self.client.lpush(self.queue_name, item.encode())
        return True

    def recover_expired(self, *, now: Optional[datetime] = None) -> int:
        active_now = now or datetime.now(timezone.utc)
        recovered = 0
        for encoded in self.client.lrange(self.inflight_name, 0, -1):
            item = QueueItem.decode(encoded)
            lease = self._lease(item)
            expires_at = None
            if lease and lease.get("expires_at"):
                expires_at = datetime.fromisoformat(lease["expires_at"])
            if expires_at is not None and expires_at > active_now:
                continue
            self.client.lrem(self.inflight_name, 1, item.encode())
            self.client.hdel(self.lease_name, item.key)
            self.client.rpush(self.queue_name, item.encode())
            recovered += 1
        return recovered


__all__ = [
    "InMemoryAttachmentQueue",
    "QueueItem",
    "QueueLease",
    "RedisAttachmentQueue",
]
