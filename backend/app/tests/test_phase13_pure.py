"""Phase 1 hardening, stdlib-only tests (batch 13): distributed rate limiter, client IP, security headers, Sentry scrubbing,
admin allow-list, admin job policy, retention policy."""
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from app.core.admin import is_admin_github_id, parse_admin_ids
from app.core.monitoring import fingerprint_for, scrub_breadcrumb, scrub_event
from app.core.rate_limit import DistributedLimiter, extract_client_ip
from app.core.security_headers import API_CSP, api_security_headers
from app.services.admin_policy import can_retry, clamp_page, safe_payload
from app.services.retention_policy import RetentionPolicy, is_security_action


FAKE_TOKEN = "ghp_" + "a1b2" * 9  # built at runtime so repository secret scanners do not flag the test file


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


class FakeRedis:
    """Implements exactly the commands DistributedLimiter uses, with real SET NX EX / INCR / TTL semantics and a shared clock."""
    def __init__(self, clock): self.clock, self.data, self.fail = clock, {}, False
    def _live(self, k):
        v = self.data.get(k)
        if v and v[1] is not None and v[1] <= self.clock():
            del self.data[k]; v = None
        return v
    def pipeline(self, transaction=True): return Pipe(self)
    def expire(self, k, s):
        if self._live(k): self.data[k] = (self.data[k][0], self.clock() + s)


class Pipe:
    def __init__(self, r): self.r, self.ops = r, []
    def set(self, k, v, ex=None, nx=False): self.ops.append(("set", k, v, ex, nx))
    def incr(self, k): self.ops.append(("incr", k))
    def ttl(self, k): self.ops.append(("ttl", k))
    def execute(self):
        if self.r.fail:
            raise ConnectionError("redis://user:hunter2@host:6379 refused")
        out = []
        for op in self.ops:
            if op[0] == "set":
                _, k, v, ex, nx = op
                if nx and self.r._live(k): out.append(None)
                else: self.r.data[k] = (v, self.r.clock() + ex if ex else None); out.append(True)
            elif op[0] == "incr":
                v = self.r._live(op[1]); n = (int(v[0]) if v else 0) + 1
                self.r.data[op[1]] = (n, v[1] if v else None); out.append(n)
            else:
                v = self.r._live(op[1]); out.append(-2 if not v else (-1 if v[1] is None else int(v[1] - self.r.clock())))
        return out


def limiter(redis, clock, mode="memory", limit=3, window=60):
    return DistributedLimiter("t", limit, window, client_factory=lambda: redis, failure_mode=mode, retry_seconds=15, clock=clock)


def test_two_instances_share_one_limit():
    c = Clock(); r = FakeRedis(c)
    a, b = limiter(r, c), limiter(r, c)  # two API processes, one Redis
    results = [a.check("ip:1")[0], b.check("ip:1")[0], a.check("ip:1")[0], b.check("ip:1")[0], a.check("ip:1")[0]]
    assert results == [True, True, True, False, False]  # per-process limiters would have allowed 6
    assert b.check("ip:2")[0] is True  # other subject unaffected


def test_window_expires_and_retry_after_is_reported():
    c = Clock(); r = FakeRedis(c); l = limiter(r, c)
    for _ in range(3): assert l.check("s")[0]
    ok, retry = l.check("s")
    assert ok is False and 1 <= retry <= 60
    c.t += 61
    assert l.check("s")[0] is True


def test_redis_failure_memory_mode_falls_back_to_local_limit_and_logs_no_secret(caplog=None):
    c = Clock(); r = FakeRedis(c); r.fail = True; l = limiter(r, c, "memory")
    records = []
    h = logging.Handler(); h.emit = records.append
    logging.getLogger("synaxys.ratelimit").addHandler(h)
    try:
        assert [l.check("x")[0] for _ in range(4)] == [True, True, True, False]  # still limited, per process
    finally:
        logging.getLogger("synaxys.ratelimit").removeHandler(h)
    assert l.degraded is True
    text = " ".join(r_.getMessage() for r_ in records)
    assert "ConnectionError" in text and "hunter2" not in text and "redis://" not in text


def test_redis_failure_closed_and_open_modes():
    c = Clock(); r = FakeRedis(c); r.fail = True
    assert limiter(r, c, "closed").check("x")[0] is False
    assert limiter(r, c, "open").check("x")[0] is True


def test_circuit_breaker_skips_redis_then_recovers():
    c = Clock(); r = FakeRedis(c); l = limiter(r, c, "open")
    r.fail = True; l.check("x")
    calls = {"n": 0}; orig = r.pipeline
    def counting(*a, **k): calls["n"] += 1; return orig(*a, **k)
    r.pipeline = counting; r.fail = False
    l.check("x"); l.check("x")
    assert calls["n"] == 0  # breaker open: Redis not contacted
    c.t += 16
    assert l.check("x")[0] is True and calls["n"] == 1 and l.degraded is False


def test_no_redis_configured_uses_local_limiter():
    c = Clock(); l = DistributedLimiter("t", 2, 60, client_factory=None, clock=c)
    assert [l.check("a")[0] for _ in range(3)] == [True, True, False] and l.degraded is False


def test_unavailable_client_none_is_handled_like_a_failure():
    c = Clock(); l = DistributedLimiter("t", 1, 60, client_factory=lambda: None, failure_mode="closed", clock=c)
    assert l.check("a")[0] is False


def test_client_ip_extraction():
    f = extract_client_ip
    assert f("1.1.1.1, 2.2.2.2", "9.9.9.9", trust_proxy=False) == "9.9.9.9"      # header ignored without a trusted proxy
    assert f("1.1.1.1, 2.2.2.2", "9.9.9.9", trust_proxy=True) == "1.1.1.1"        # legacy: first entry
    assert f("spoof, real", "9.9.9.9", trust_proxy=True, hops=1) == "real"        # rightmost entry
    assert f("client, vercel", "9.9.9.9", trust_proxy=True, hops=2) == "client"
    assert f("only", "9.9.9.9", trust_proxy=True, hops=2) == "9.9.9.9"            # header shorter than expected
    assert f(None, None, trust_proxy=True) == "unknown"


def test_security_headers():
    h = api_security_headers("/api/v1/me", is_production=True, https=True)
    assert h["Content-Security-Policy"] == API_CSP and "frame-ancestors 'none'" in API_CSP
    assert h["Strict-Transport-Security"].startswith("max-age=") and "preload" not in h["Strict-Transport-Security"]
    assert h["X-Content-Type-Options"] == "nosniff" and h["Referrer-Policy"] == "no-referrer" and "camera=()" in h["Permissions-Policy"]
    assert "Strict-Transport-Security" not in api_security_headers("/x", is_production=False, https=False)
    assert "Content-Security-Policy" not in api_security_headers("/docs", is_production=False, https=False)   # swagger needs a CDN in dev
    assert "Content-Security-Policy" in api_security_headers("/docs", is_production=True, https=True)


def test_sentry_event_is_scrubbed():
    ev = {"request": {"method": "GET", "url": "https://api.x/cb?code=OAUTHCODE&state=S", "query_string": "code=OAUTHCODE", "cookies": {"synaxys_session": "SESSIONVALUE"},
                      "headers": {"Authorization": "Bearer " + FAKE_TOKEN, "X-CSRF-Token": "csrf"}, "data": {"diff": "def secret_code(): pass"}},
          "user": {"id": 7, "email": "a@b.c", "ip_address": "1.2.3.4", "username": "bob"},
          "exception": {"values": [{"type": "X", "value": "failed with token " + FAKE_TOKEN + " and more",
                                    "stacktrace": {"frames": [{"filename": "a.py", "lineno": 3, "vars": {"api_key": "sk-123"}, "context_line": "x = SECRET", "pre_context": ["a"], "post_context": ["b"]}]}}]},
          "extra": {"github_token": "ghp_x", "repo_id": 5, "payload": {"a": 1}}, "tags": {"component": "api"},
          "breadcrumbs": {"values": [{"category": "console", "message": "dbg"}, {"category": "httplib", "message": "m", "data": {"url": "https://api.github.com/x?access_token=abc", "method": "GET", "status_code": 200, "body": "SECRETBODY"}}]}}
    out = scrub_event(ev)
    blob = str(out)
    for leak in ("OAUTHCODE", "SESSIONVALUE", FAKE_TOKEN, "sk-123", "SECRET", "a@b.c", "1.2.3.4", "bob", "access_token", "csrf", "secret_code", "SECRETBODY"):
        assert leak not in blob, leak
    assert out["request"] == {"method": "GET", "url": "https://api.x/cb"}
    assert out["user"] == {"id": "7"} and out["extra"]["repo_id"] == 5 and out["extra"]["github_token"] == "[Filtered]"
    frame = out["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert frame == {"filename": "a.py", "lineno": 3}
    assert [b["category"] for b in out["breadcrumbs"]["values"]] == ["httplib"]


def test_sentry_grouping_fingerprints():
    class GitHubAPIError(Exception): status = 502
    class UpstreamError(Exception): code = "openai_unavailable"
    ev = scrub_event({"message": "x"}, {"exc_info": (GitHubAPIError, GitHubAPIError(), None)})
    assert ev["fingerprint"] == ["github-api-error", "502"]
    assert fingerprint_for(UpstreamError()) == ["UpstreamError", "openai_unavailable"] and fingerprint_for(ValueError()) is None
    assert scrub_breadcrumb({"category": "console"}) is None and scrub_event(None) is None


def test_admin_allow_list():
    assert parse_admin_ids("") == frozenset() and parse_admin_ids(" 12, 34 ,") == frozenset({12, 34})
    for bad in ("octocat", "12,abc", "-1", "0", "1.5"):
        try: parse_admin_ids(bad)
        except ValueError: continue
        raise AssertionError(bad)
    ids = parse_admin_ids("5")
    assert is_admin_github_id(5, ids) and not is_admin_github_id(6, ids) and not is_admin_github_id(-1, ids) and not is_admin_github_id(None, ids)
    assert not is_admin_github_id(-1, frozenset({-1}))  # the demo user can never be admin, even if someone configures it


def test_admin_job_policy():
    p = safe_payload({"review_id": 3, "repository_id": 4, "branch": "main", "commit": "a" * 40, "token": "ghp_x", "diff": "code", "nested": {"a": 1}, "indexing_job_id": True})
    assert p == {"review_id": 3, "repository_id": 4, "branch": "main", "commit": "a" * 12}
    assert safe_payload(None) == {} and safe_payload("x") == {}
    assert can_retry("failed") and not any(can_retry(s) for s in ("queued", "processing", "succeeded", "cancelled"))
    assert clamp_page(0, 1000) == (1, 100) and clamp_page(3, 0) == (3, 1)


def _settings(**kw):
    base = dict(retention_sessions_days=7, retention_webhook_days=30, retention_jobs_done_days=14, retention_jobs_failed_days=60, retention_indexing_jobs_days=30,
                retention_audit_days=365, retention_security_audit_days=730, cleanup_batch_size=500, cleanup_max_batches=20)
    return NS(**{**base, **kw})


def test_retention_cutoffs_and_disabled_rules():
    now = datetime(2026, 11, 20, tzinfo=timezone.utc)
    c = RetentionPolicy.from_settings(_settings()).cutoffs(now)
    assert c["sessions"] == now - timedelta(days=7) and c["audit_security"] == now - timedelta(days=730) and c["audit_security"] < c["audit_general"]
    c2 = RetentionPolicy.from_settings(_settings(retention_audit_days=0, retention_security_audit_days=0)).cutoffs(now)
    assert c2["audit_general"] is None and c2["audit_security"] is None and c2["sessions"] is not None


def test_security_audit_actions_are_classified():
    for a in ("auth.login", "auth.logout", "admin.job_retry", "github.credentials_revoked", "account.delete", "workspace.member_removed"):
        assert is_security_action(a), a
    for a in ("review.publish", "repository.connect", "system.cleanup", "rule.update"):
        assert not is_security_action(a), a
