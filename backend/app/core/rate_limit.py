"""Rate limiting.

* SlidingWindowLimiter - in-process sliding window (used in tests/dev, and as the Redis-failure fallback).
* DistributedLimiter   - shared fixed-window counters in Redis, so every API instance sees the same counts.

Redis algorithm (one atomic MULTI/EXEC transaction per check):
    SET key 0 EX <window> NX   -> creates the counter AND its expiry together (a counter can never outlive its window)
    INCR key                    -> the request count in the current window
    TTL key                     -> seconds until the window ends (used for Retry-After)
Fixed windows allow at most 2x the limit around a window boundary; that trade-off is accepted for a single round trip
and no Lua script. If Redis is slow or down the limiter follows `failure_mode`:
    memory (default) - fall back to a per-process sliding window (limits still apply, per instance, not globally)
    closed           - deny the request while Redis is unreachable
    open             - allow the request
After a failure Redis is not contacted again for `retry_seconds` (circuit breaker), so a dead Redis costs one timeout
per interval instead of one per request. Only the exception TYPE is logged (connection strings can contain passwords).
"""
import logging
import math
import threading
import time
from collections import defaultdict, deque

log = logging.getLogger("synaxys.ratelimit")


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


class DistributedLimiter:
    """client_factory() -> a redis-py compatible client (pipeline/set/incr/ttl/expire) or None when unavailable."""

    def __init__(self, name: str, limit: int, window_seconds: float, *, client_factory=None, failure_mode: str = "memory",
                 prefix: str = "synaxys:rl", retry_seconds: int = 15, clock=time.monotonic):
        if failure_mode not in ("memory", "closed", "open"):
            raise ValueError("failure_mode must be memory, closed or open")
        self.name, self.limit, self.window = name, limit, window_seconds
        self._window_int = max(1, math.ceil(window_seconds))
        self._factory, self._mode, self._prefix, self._retry = client_factory, failure_mode, prefix, retry_seconds
        self._clock = clock
        self._local = SlidingWindowLimiter(limit, window_seconds, clock)
        self._down_until = 0.0
        self._was_down = False
        self._lock = threading.Lock()

    @property
    def degraded(self) -> bool:
        return self._factory is not None and self._clock() < self._down_until

    def _key(self, subject: str) -> str:
        return f"{self._prefix}:{self.name}:{subject}"

    def _redis_check(self, subject: str) -> tuple[bool, int]:
        client = self._factory()
        if client is None:
            raise RuntimeError("redis client unavailable")
        key = self._key(subject)
        pipe = client.pipeline(transaction=True)
        pipe.set(key, 0, ex=self._window_int, nx=True)
        pipe.incr(key)
        pipe.ttl(key)
        _, count, ttl = pipe.execute()
        if ttl is None or ttl < 0:  # self-heal a counter that somehow has no expiry
            client.expire(key, self._window_int)
            ttl = self._window_int
        if int(count) <= self.limit:
            return True, 0
        return False, max(1, int(ttl))

    def _fallback(self, subject: str) -> tuple[bool, int]:
        if self._mode == "open":
            return True, 0
        if self._mode == "closed":
            return False, max(1, int(self._down_until - self._clock()) + 1)
        return self._local.check(subject)

    def check(self, subject: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        if self._factory is None:
            return self._local.check(subject)
        if self._clock() < self._down_until:
            return self._fallback(subject)
        try:
            result = self._redis_check(subject)
        except Exception as exc:  # noqa: BLE001 - any Redis/driver/timeout failure must degrade safely, never 500 the API
            with self._lock:
                self._down_until = self._clock() + self._retry
                first = not self._was_down
                self._was_down = True
            if first:
                log.error("rate limiter: Redis unavailable (%s); failure mode=%s, retrying in %ss", type(exc).__name__, self._mode, self._retry)
            return self._fallback(subject)
        if self._was_down:
            self._was_down = False
            log.warning("rate limiter: Redis is reachable again")
        return result

    def reset(self) -> None:
        """Clears LOCAL state only (tests). Redis counters expire by themselves."""
        self._local.reset()
        self._down_until = 0.0
        self._was_down = False


def extract_client_ip(forwarded_for: str | None, peer: str | None, *, trust_proxy: bool, hops: int = 0) -> str:
    """Client address used as the rate-limit subject.

    Without a trusted proxy only the TCP peer is used (X-Forwarded-For is attacker-controlled).
    With one: hops == 0 keeps the legacy behaviour (first entry); hops == N takes the N-th entry from the RIGHT,
    i.e. the address that the N-th proxy in front of the app recorded. Falls back to the peer when the header is
    shorter than expected.
    """
    peer = peer or "unknown"
    if not trust_proxy or not forwarded_for:
        return peer
    parts = [p.strip() for p in forwarded_for.split(",") if p.strip()]
    if not parts:
        return peer
    if hops <= 0:
        return parts[0]
    return parts[-hops] if len(parts) >= hops else peer
