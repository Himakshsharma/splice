"""Tiny in-memory sliding-window rate limiter for job creation.

Good enough for a single-instance public demo. It resets on restart and is not
shared across replicas — documented as a remaining abuse risk in the README.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Request


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 3600.0):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """Record a hit for ``key``. Returns (allowed, retry_after_seconds)."""
        if self.limit <= 0:
            return True, 0
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False, max(1, int(self.window - (now - hits[0])))
            hits.append(now)
            return True, 0


def client_ip(request: Request, trust_proxy_headers: bool) -> str:
    if trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
