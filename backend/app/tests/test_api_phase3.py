"""OAuth security, sessions, CSRF, rate limits, repository authorization. NOT RUN in the build sandbox."""
from urllib.parse import parse_qs, urlparse

from app.tests.conftest import login


def test_login_redirect_has_state_and_pkce_and_httponly_cookie(ctx):
    r = ctx.client().get("/api/v1/auth/github/login")
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["state"] and q["code_challenge"]
    assert "httponly" in r.headers["set-cookie"].lower()


def test_login_unconfigured_returns_clear_error(ctx, monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "")
    from app.core.config import get_settings; get_settings.cache_clear()
    r = ctx.client().get("/api/v1/auth/github/login")
    assert r.status_code == 503 and r.json()["error"]["code"] == "github_oauth_not_configured"


def test_callback_rejects_state_mismatch_and_missing_cookie(ctx):
    from app.core.auth_tokens import sign_payload
    from app.core.config import get_settings
    c = ctx.client()
    r = c.get("/api/v1/auth/github/callback?code=x&state=S")                 # no cookie
    assert "error=invalid_state" in r.headers["location"] and "synaxys_session" not in r.headers.get("set-cookie", "")
    c.cookies.set("synaxys_oauth", sign_payload(get_settings().app_secret_key, "oauth", {"state": "S", "v": "V"}, 600), path="/api/v1/auth/github")
    r = c.get("/api/v1/auth/github/callback?code=x&state=OTHER")             # mismatch
    assert "error=invalid_state" in r.headers["location"]


def test_callback_success_encrypts_token_and_sends_pkce_verifier(ctx):
    c, _ = login(ctx)
    assert ctx.gh.last_verifier == "V"
    from sqlalchemy import select
    from app.models import OAuthIdentity
    with ctx.db() as db:
        ident = db.scalar(select(OAuthIdentity))
        assert ident.access_token_enc and "gho_plain_token" not in ident.access_token_enc


def test_me_requires_auth_and_logout_invalidates_session(ctx):
    assert ctx.client().get("/api/v1/auth/me").status_code == 401
    c, csrf = login(ctx)
    assert c.post("/api/v1/auth/logout").status_code == 403                  # CSRF required
    assert c.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert c.get("/api/v1/auth/me").status_code == 401


def test_csrf_and_origin_enforced_on_unsafe_methods(ctx):
    c, csrf = login(ctx)
    assert c.post("/api/v1/github/repositories/sync").status_code == 403
    assert c.post("/api/v1/github/repositories/sync", headers={"X-CSRF-Token": csrf, "Origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/v1/github/repositories/sync", headers={"X-CSRF-Token": csrf}).status_code == 200


def test_auth_rate_limit(ctx):
    c = ctx.client()
    codes = [c.get("/api/v1/auth/github/login").status_code for _ in range(12)]
    assert 429 in codes


def test_sync_lists_only_authorized_repos_and_isolates_users(ctx):
    a, csrf_a = login(ctx)
    assert a.post("/api/v1/github/repositories/sync", headers={"X-CSRF-Token": csrf_a}).json()["repositories"] == 1
    repo_id = a.get("/api/v1/github/repositories").json()["items"][0]["id"]
    ctx.gh.repos = {10: []}
    b, csrf_b = login(ctx, {"id": 2, "login": "bob"})                         # bob sees nothing of alice's
    assert b.get("/api/v1/github/repositories").json()["total"] == 0
    assert b.post(f"/api/v1/github/repositories/{repo_id}/connect", headers={"X-CSRF-Token": csrf_b}).status_code == 404


def test_member_cannot_connect_but_admin_can_and_disconnect_queues_cleanup(ctx):
    ctx.gh.repos[10][0]["permissions"] = {"admin": False}
    c, csrf = login(ctx)
    c.post("/api/v1/github/repositories/sync", headers={"X-CSRF-Token": csrf})
    rid = c.get("/api/v1/github/repositories").json()["items"][0]["id"]
    assert c.post(f"/api/v1/github/repositories/{rid}/connect", headers={"X-CSRF-Token": csrf}).status_code == 403
    ctx.gh.repos[10][0]["permissions"] = {"admin": True}
    c.post("/api/v1/github/repositories/sync", headers={"X-CSRF-Token": csrf})
    assert c.post(f"/api/v1/github/repositories/{rid}/connect", headers={"X-CSRF-Token": csrf}).json()["is_enabled"] is True
    assert c.delete(f"/api/v1/github/repositories/{rid}/disconnect", headers={"X-CSRF-Token": csrf}).json()["is_enabled"] is False
    from sqlalchemy import select
    from app.models import BackgroundJob
    with ctx.db() as db:
        assert db.scalar(select(BackgroundJob).where(BackgroundJob.kind == "index_delete"))


def test_sync_revokes_access_removed_on_github_and_handles_expired_token(ctx):
    c, csrf = login(ctx)
    c.post("/api/v1/github/repositories/sync", headers={"X-CSRF-Token": csrf})
    ctx.gh.repos = {10: []}
    assert c.post("/api/v1/github/repositories/sync", headers={"X-CSRF-Token": csrf}).json()["access_removed"] == 1
    assert c.get("/api/v1/github/repositories").json()["total"] == 0
    ctx.gh.raise_status = 401
    r = c.post("/api/v1/github/repositories/sync", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 409 and r.json()["error"]["code"] == "github_reauth_required"


def test_revoke_credentials_deletes_token(ctx):
    c, csrf = login(ctx)
    assert c.delete("/api/v1/github/credentials", headers={"X-CSRF-Token": csrf}).status_code == 204
    r = c.post("/api/v1/github/repositories/sync", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 409


# ---- Phase 5 backend additions ----
def test_demo_login_works_in_dev_and_is_blocked_when_disabled(ctx, monkeypatch):
    from app.db.seed import seed
    seed()
    c = ctx.client()
    assert c.post("/api/v1/auth/demo-login").status_code == 204
    assert c.get("/api/v1/auth/me").json()["user"]["login"] == "demo-user"
    monkeypatch.setenv("DEMO_LOGIN_ENABLED", "false")
    from app.core.config import get_settings; get_settings.cache_clear()
    assert ctx.client().post("/api/v1/auth/demo-login").status_code == 404


def test_dashboard_scoped_to_user_and_labels_demo(ctx):
    from app.db.seed import seed
    seed()
    c = ctx.client(); c.post("/api/v1/auth/demo-login")
    d = c.get("/api/v1/dashboard").json()
    assert d["has_demo_data"] and d["total_repositories"] == 1 and d["findings_by_severity"]["high"] == 1
    assert d["recent_reviews"][0]["is_demo"] is True
    other, _ = login(ctx, {"id": 5, "login": "eve"})
    assert other.get("/api/v1/dashboard").json()["total_repositories"] == 0     # no leakage
    assert ctx.client().get("/api/v1/dashboard").status_code == 401
