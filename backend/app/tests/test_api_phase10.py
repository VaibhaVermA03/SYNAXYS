"""Settings, integrations, audit, dashboard metrics. NOT RUN in the build sandbox (needs deps)."""
from sqlalchemy import select

from app.tests.conftest import login


def test_integrations_status_requires_auth_and_never_leaks_secret_values(ctx, monkeypatch):
    for k, v in {"GITHUB_CLIENT_SECRET": "gcs-SECRET-1", "OPENAI_API_KEY": "sk-SECRET-3", "PINECONE_API_KEY": "pcsk-SECRET-4", "GITHUB_APP_ID": "123", "GITHUB_APP_PRIVATE_KEY": "PEM-SECRET-6"}.items():
        monkeypatch.setenv(k, v)
    from app.core.config import get_settings; get_settings.cache_clear()
    assert ctx.client().get("/api/v1/settings/integrations").status_code == 401
    c, _ = login(ctx)
    r = c.get("/api/v1/settings/integrations")
    assert r.status_code == 200
    for secret in ("gcs-SECRET-1", "sk-SECRET-3", "pcsk-SECRET-4", "PEM-SECRET-6", "whsec"):
        assert secret not in r.text
    d = r.json()
    assert {i["key"] for i in d["items"]} >= {"github_oauth", "github_app", "webhook", "openai", "pinecone", "encryption"}
    assert d["webhook_url"].endswith("/api/v1/webhooks/github") and d["github_token_stored"] is True


def test_revoking_credentials_flips_token_stored_and_is_audited_per_user(ctx):
    c, csrf = login(ctx); h = {"X-CSRF-Token": csrf}
    assert c.delete("/api/v1/github/credentials", headers=h).status_code == 204
    assert c.get("/api/v1/settings/integrations").json()["github_token_stored"] is False
    actions = [a["action"] for a in c.get("/api/v1/settings/audit").json()]
    assert "github.credentials_revoked" in actions and "auth.login" in actions
    eve, _ = login(ctx, {"id": 9, "login": "eve"})
    assert "github.credentials_revoked" not in [a["action"] for a in eve.get("/api/v1/settings/audit").json()]     # audit is scoped to the caller
    assert c.get("/api/v1/settings/audit?limit=0").status_code == 422


def test_dashboard_usage_metrics_are_scoped_and_complete(ctx):
    from app.db.seed import seed
    from app.models import ReviewComment
    seed()
    c = ctx.client(); c.post("/api/v1/auth/demo-login")
    d = c.get("/api/v1/dashboard").json()
    assert len(d["reviews_by_day"]) == 14 and sum(x["count"] for x in d["reviews_by_day"]) == 1 and d["published_comments"] == 0 and d["failed_reviews"] == 0
    with ctx.db() as db:
        db.scalars(select(ReviewComment)).first().state = "published"; db.commit()
    assert c.get("/api/v1/dashboard").json()["published_comments"] == 1
    other, _ = login(ctx, {"id": 5, "login": "eve"})
    o = other.get("/api/v1/dashboard").json()
    assert o["published_comments"] == 0 and sum(x["count"] for x in o["reviews_by_day"]) == 0
