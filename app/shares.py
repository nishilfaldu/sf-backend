"""Short-lived in-memory share tokens for handing a contact to someone nearby."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

SHARE_TTL = timedelta(minutes=30)
TOKEN_BYTES = 6  # ~8 url-safe characters

_lock = Lock()
_shares: dict[str, "Share"] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Share:
    token: str
    contact: dict[str, Any]
    expires_at: datetime

    @property
    def expired(self) -> bool:
        return self.expires_at <= _utcnow()


def reset_shares() -> None:
    """Drop every token. Tests call this so cases cannot leak into each other."""
    with _lock:
        _shares.clear()


def _purge_locked(now: datetime) -> None:
    expired = [token for token, share in _shares.items() if share.expires_at <= now]
    for token in expired:
        del _shares[token]


def create_share(contact: dict[str, Any], *, ttl: timedelta = SHARE_TTL) -> Share:
    """Store a snapshot of `contact` and return a token that expires after `ttl`."""
    now = _utcnow()
    expires_at = now + ttl
    with _lock:
        _purge_locked(now)
        for _ in range(8):
            token = secrets.token_urlsafe(TOKEN_BYTES)
            if token not in _shares:
                share = Share(token=token, contact=contact, expires_at=expires_at)
                _shares[token] = share
                return share
    raise RuntimeError("Could not allocate a unique share token")


def get_share(token: str) -> Share | None:
    now = _utcnow()
    with _lock:
        _purge_locked(now)
        share = _shares.get(token)
        if share is None or share.expires_at <= now:
            return None
        return share
