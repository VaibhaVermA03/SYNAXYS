"""In-memory sliding-window limiter.

LIMITATION (documented in SECURITY.md): state is per-process. With several backend
replicas, use a shared store (e.g. Redis) or enforce limits at the proxy as well.
"""
import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float, clock=time.monotonic):
        self.limit, self.window, self._clock = limit, window_seconds, clock
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = self._clock()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False, max(1, int(q[0] + self.window - now) + 1)
            q.append(now)
            if not q:
                self._hits.pop(key, None)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
