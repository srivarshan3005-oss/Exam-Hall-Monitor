"""In-process sliding-window rate limiter.

LIMITATION (documented in docs/SECURITY.md): state lives in one Python process.
With several worker processes / servers each has its own counters, so put a shared
limiter (reverse proxy, WAF or Redis) in front for production. Account lockout is
additionally stored in the database so it holds across workers and restarts.
"""
import math, threading, time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self):
        self._events: dict[str, deque] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, window: float, now: float):
        q = self._events.get(key)
        if q is None:
            return None
        while q and q[0] <= now - window:
            q.popleft()
        if not q:
            del self._events[key]
            return None
        return q

    def check_and_record(self, key: str, limit: int, window: float) -> tuple[bool, int]:
        """Record one event unless the limit is reached. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, window, now)
            if q is not None and len(q) >= limit:
                return False, max(1, math.ceil(q[0] + window - now))
            self._events.setdefault(key, deque()).append(now)
            if len(self._events) > 100_000:  # memory guard
                for k in list(self._events)[:50_000]:
                    self._prune(k, window, now)
            return True, 0

    def is_blocked(self, key: str, limit: int, window: float) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, window, now)
            if q is not None and len(q) >= limit:
                return True, max(1, math.ceil(q[0] + window - now))
            return False, 0

    def record(self, key: str) -> None:
        with self._lock:
            self._events.setdefault(key, deque()).append(time.monotonic())

    def clear(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


limiter = SlidingWindowLimiter()
