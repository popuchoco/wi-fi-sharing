"""Small stdlib-only helpers for session cookies and request throttling."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import threading
import time
from collections import defaultdict, deque


def is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def issue_session_cookie(
    session_id: str,
    authenticated: bool,
    secret: bytes,
    expires_at: int,
) -> str:
    auth_flag = "1" if authenticated else "0"
    payload = f"{session_id}.{expires_at}.{auth_flag}"
    signature = hmac.new(secret, payload.encode(), hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{payload}.{encoded}"


def verify_session_cookie(
    value: str | None,
    secret: bytes,
    *,
    now: int | None = None,
) -> tuple[str, bool] | None:
    if not value:
        return None
    try:
        session_id, expires_raw, auth_flag, signature = value.split(".", 3)
        expires_at = int(expires_raw)
    except (ValueError, TypeError):
        return None
    current_time = int(time.time()) if now is None else now
    if not session_id or auth_flag not in {"0", "1"} or expires_at <= current_time:
        return None
    if expires_at > current_time + 24 * 60 * 60 + 60:
        return None
    payload = f"{session_id}.{expires_at}.{auth_flag}"
    expected = base64.urlsafe_b64encode(
        hmac.new(secret, payload.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    if not hmac.compare_digest(signature, expected):
        return None
    return session_id, auth_flag == "1"


class SlidingWindowRateLimiter:
    """Process-local fixed-key sliding window limiter for small deployments."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, *, limit: int, window_seconds: float) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            events = self._events.get(key)
            if events is None:
                if len(self._events) >= 4096:
                    for old_key, old_events in list(self._events.items()):
                        while old_events and old_events[0] <= cutoff:
                            old_events.popleft()
                        if not old_events:
                            self._events.pop(old_key, None)
                    if len(self._events) >= 4096:
                        return False
                events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True
