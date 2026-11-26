"""Integration test against a REAL Redis (skipped unless TEST_REDIS_URL is set; CI provides a redis service).
Proves the shared-counter guarantee across two limiter instances and 40 concurrent threads."""
import os
import threading
import uuid

import pytest

URL = os.environ.get("TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_REDIS_URL not set")


def _client():
    import redis
    return redis.Redis.from_url(URL, socket_timeout=1, socket_connect_timeout=1)


def test_limit_is_exact_across_instances_and_threads():
    from app.core.rate_limit import DistributedLimiter
    name = f"it-{uuid.uuid4().hex[:8]}"
    a = DistributedLimiter(name, 10, 30, client_factory=_client)
    b = DistributedLimiter(name, 10, 30, client_factory=_client)  # a second API instance
    allowed, lock = [], threading.Lock()

    def hit(l):
        ok, _ = l.check("ip:1.2.3.4")
        with lock:
            allowed.append(ok)

    ts = [threading.Thread(target=hit, args=(a if i % 2 else b,)) for i in range(40)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert allowed.count(True) == 10 and allowed.count(False) == 30
    ttl = _client().ttl(f"synaxys:rl:{name}:ip:1.2.3.4")
    assert 0 < ttl <= 30  # the counter always carries an expiry


def test_unreachable_redis_falls_back_instead_of_raising():
    import redis
    from app.core.rate_limit import DistributedLimiter
    dead = lambda: redis.Redis(host="127.0.0.1", port=1, socket_timeout=0.2, socket_connect_timeout=0.2)  # noqa: E731
    l = DistributedLimiter("dead", 2, 30, client_factory=dead, failure_mode="memory")
    assert [l.check("x")[0] for _ in range(3)] == [True, True, False] and l.degraded
