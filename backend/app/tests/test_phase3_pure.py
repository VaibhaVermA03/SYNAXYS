import hashlib
from app.core.auth_tokens import (csrf_token, verify_csrf, pkce_challenge, new_pkce_pair, sign_payload,
                                  verify_payload, hash_token, new_session_token)
from app.core.rate_limit import SlidingWindowLimiter
from app.core.exceptions import RateLimited
from app.services.github_http import execute_with_retry, parse_next_link, GitHubAPIError


class Resp:
    def __init__(self, status, headers=None, body=None):
        self.status_code, self.headers, self._b = status, headers or {}, body
    def json(self): return self._b


def _seq(*responses):
    it = iter(responses)
    def send():
        r = next(it)
        if isinstance(r, Exception): raise r
        return r
    return send


NOSLEEP = dict(sleep=lambda s: None, rand=lambda: 0.0)


def test_pkce_rfc7636_vector():
    assert pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    v, c = new_pkce_pair()
    assert 43 <= len(v) <= 128 and c == pkce_challenge(v)


def test_signed_state_roundtrip_tamper_expiry_purpose():
    t = sign_payload("k", "oauth", {"state": "s1"}, 600, now=1000)
    assert verify_payload("k", "oauth", t, now=1100)["state"] == "s1"
    assert verify_payload("k", "oauth", t, now=2000) is None          # expired
    assert verify_payload("other", "oauth", t, now=1100) is None      # wrong key
    assert verify_payload("k", "session", t, now=1100) is None        # wrong purpose
    body, sig = t.split(".")
    assert verify_payload("k", "oauth", body + "." + sig[:-2] + "AA", now=1100) is None
    assert verify_payload("k", "oauth", None) is None and verify_payload("k", "oauth", "garbage") is None


def test_csrf_binding():
    t = csrf_token("app", "sess1")
    assert verify_csrf("app", "sess1", t)
    assert not verify_csrf("app", "sess2", t) and not verify_csrf("app", "sess1", None) and not verify_csrf("app", "sess1", "")


def test_session_token_hashed():
    tok = new_session_token()
    assert hash_token(tok) == hashlib.sha256(tok.encode()).hexdigest() and tok not in hash_token(tok)


def test_rate_limiter_window():
    now = [0.0]
    lim = SlidingWindowLimiter(2, 10, clock=lambda: now[0])
    assert lim.check("a")[0] and lim.check("a")[0]
    ok, retry = lim.check("a"); assert not ok and retry >= 1
    assert lim.check("b")[0]            # per-key
    now[0] = 11; assert lim.check("a")[0]


def test_parse_next_link():
    h = '<https://api.github.com/x?page=2>; rel="next", <https://api.github.com/x?page=9>; rel="last"'
    assert parse_next_link(h) == "https://api.github.com/x?page=2"
    assert parse_next_link(None) is None and parse_next_link('<u>; rel="last"') is None


def test_retry_5xx_then_success():
    r = execute_with_retry(_seq(Resp(502), Resp(503), Resp(200, {}, {"ok": 1})), **NOSLEEP)
    assert r.body == {"ok": 1}


def test_retry_gives_up_on_persistent_5xx_and_does_not_retry_4xx():
    try: execute_with_retry(_seq(*[Resp(500)] * 4), **NOSLEEP); assert False
    except GitHubAPIError as e: assert e.status == 500
    calls = []
    def send(): calls.append(1); return Resp(404)
    try: execute_with_retry(send, **NOSLEEP); assert False
    except GitHubAPIError as e: assert e.status == 404 and len(calls) == 1


def test_secondary_rate_limit_retry_after_and_primary_reset():
    waits = []
    r = execute_with_retry(_seq(Resp(403, {"Retry-After": "2"}), Resp(200, {}, [])), sleep=waits.append, rand=lambda: 0.0)
    assert waits == [2.0] and r.status == 200
    try:
        execute_with_retry(_seq(Resp(403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999999"})),
                           now=lambda: 0, **NOSLEEP)
        assert False
    except RateLimited as e: assert e.code == "github_rate_limited"   # wait > max_wait → fail fast


def test_network_errors_retry_then_raise():
    class Boom(Exception): pass
    r = execute_with_retry(_seq(Boom(), Resp(200, {}, 1)), retry_exceptions=(Boom,), **NOSLEEP)
    assert r.body == 1
    try: execute_with_retry(_seq(*[Boom()] * 4), retry_exceptions=(Boom,), **NOSLEEP); assert False
    except GitHubAPIError as e: assert e.status == 0


def test_plain_403_permission_error_not_retried():
    try: execute_with_retry(_seq(Resp(403, {"x-ratelimit-remaining": "42"})), **NOSLEEP); assert False
    except GitHubAPIError as e: assert e.status == 403


# ---- GitHubClient with a fake HTTP layer (no network, no httpx) -----------------
from types import SimpleNamespace
from app.services.github_service import GitHubClient


class FakeHttp:
    def __init__(self, routes): self.routes, self.calls = routes, []
    def request(self, method, url, headers=None, params=None, data=None, **kw):
        self.calls.append((method, url, dict(headers or {}), params, data, kw.get('json')))
        r = self.routes[(method, url)]
        return r.pop(0) if isinstance(r, list) else r


S = SimpleNamespace(github_oauth_configured=True, github_client_id="cid", github_client_secret="csec",
                    github_redirect_uri="http://x/cb", github_app_configured=False)


def test_client_paginates_with_link_header_and_sends_bearer():
    http = FakeHttp({
        ("GET", "https://api.github.com/user/installations"): Resp(200, {"Link": '<https://api.github.com/p2>; rel="next"'}, {"installations": [{"id": 1}]}),
        ("GET", "https://api.github.com/p2"): Resp(200, {}, {"installations": [{"id": 2}]}),
    })
    items = GitHubClient(S, http=http).list_user_installations("tok")
    assert [i["id"] for i in items] == [1, 2]
    assert http.calls[0][2]["Authorization"] == "Bearer tok" and http.calls[0][3]["per_page"] == 100
    assert http.calls[1][3] is None            # next link carries its own query


def test_oauth_exchange_sends_pkce_verifier_and_rejects_error_body():
    ok = FakeHttp({("POST", "https://github.com/login/oauth/access_token"): Resp(200, {}, {"access_token": "t", "scope": "read:user"})})
    assert GitHubClient(S, http=ok).exchange_code("c", "ver")["access_token"] == "t"
    assert ok.calls[0][4]["code_verifier"] == "ver" and ok.calls[0][2]["Accept"] == "application/json"
    bad = FakeHttp({("POST", "https://github.com/login/oauth/access_token"): Resp(200, {}, {"error": "bad_verification_code", "error_description": "secret detail"})})
    try: GitHubClient(S, http=bad).exchange_code("c", "ver"); assert False
    except GitHubAPIError as e: assert "secret detail" not in str(e)


def test_installation_token_is_cached():
    http = FakeHttp({("POST", "https://api.github.com/app/installations/7/access_tokens"): [Resp(201, {}, {"token": "i1"}), Resp(201, {}, {"token": "i2"})]})
    c = GitHubClient(S, http=http); c.app_jwt = lambda: "jwt"
    assert c.installation_token(7) == "i1" and c.installation_token(7) == "i1" and len(http.calls) == 1


def test_publishing_posts_are_never_auto_retried_and_event_is_comment():
    http = FakeHttp({("POST", "https://api.github.com/repos/o/r/pulls/3/reviews"): [Resp(502), Resp(200, {}, {"id": 1})]})
    c = GitHubClient(S, http=http)
    try: c.create_pull_request_review("t", "o/r", 3, "sha", "body", [{"path": "a", "line": 1, "side": "RIGHT", "body": "x"}]); assert False
    except GitHubAPIError as e: assert e.status == 502
    assert len(http.calls) == 1                                           # no blind retry: could duplicate the review
    sent = http.calls[0]
    assert sent[2]["Authorization"] == "Bearer t" and sent[5]["event"] == "COMMENT" and sent[5]["commit_id"] == "sha"
    http2 = FakeHttp({("POST", "https://api.github.com/repos/o/r/pulls/3/reviews"): Resp(200, {}, {"id": 9})})
    GitHubClient(S, http=http2).create_pull_request_review("t", "o/r", 3, "sha", "b", [])
    try: GitHubClient(S, http=http2).create_review_comment("t", "../etc", 3, "sha", {}); assert False
    except GitHubAPIError as e: assert e.status == 400                    # repo name validated before building the URL


def test_repo_name_validation_rejects_traversal():
    from app.services.github_service import valid_repo_name
    assert valid_repo_name("octo/hello.world-1") and valid_repo_name("a_b/c.d")
    for bad in ("../etc", "a/..", "./x", "a/b/c", "a b/c", "a/", "/a", "a/b?x=1", ""):
        assert not valid_repo_name(bad), bad
    try: GitHubClient(S, http=FakeHttp({})).list_pull_request_files("t", "../x", 1); assert False
    except GitHubAPIError as e: assert e.status == 400
