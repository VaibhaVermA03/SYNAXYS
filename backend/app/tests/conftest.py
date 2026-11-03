"""API test fixtures. Require installed deps: pip install -r requirements-dev.txt"""
import os
import pytest

os.environ.update(APP_ENV="test", APP_SECRET_KEY="test-secret-key-at-least-32-characters!!",
                  GITHUB_CLIENT_ID="cid", GITHUB_CLIENT_SECRET="csec", GITHUB_WEBHOOK_SECRET="whsec", DEMO_LOGIN_ENABLED="true",
                  FRONTEND_URL="http://localhost:5173", CORS_ORIGINS="http://localhost:5173")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.sqlite3")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    from app.core.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def ctx(env):
    """Fresh app + schema per test. Returns an object with client, db factory, fake GitHub hooks."""
    import importlib, sys
    for m in [m for m in sys.modules if m.startswith("app.") and m != "app.tests.conftest" and not m.startswith("app.tests")]:
        del sys.modules[m]
    from fastapi.testclient import TestClient
    from app.api import deps
    from app.db.base import Base
    from app.db.session import SessionLocal, engine
    import app.models  # noqa: F401
    from app.main import create_app
    Base.metadata.create_all(engine)
    app = create_app()
    deps.reset_limiters()

    class FakeGH:
        user = {"id": 1, "login": "alice"}
        installations = [{"id": 10, "account": {"login": "alice", "type": "User"}}]
        repos = {10: [{"id": 100, "full_name": "alice/app", "default_branch": "main", "private": True, "permissions": {"admin": True}}]}
        raise_status = None
        def exchange_code(self, code, verifier):
            self.last_verifier = verifier
            return {"access_token": "gho_plain_token", "scope": "read:user"}
        def get_user(self, token): return self.user
        def list_user_installations(self, token):
            from app.services.github_http import GitHubAPIError
            if self.raise_status: raise GitHubAPIError(self.raise_status)
            return self.installations
        def list_user_installation_repos(self, token, iid): return self.repos[iid]

    gh = FakeGH()
    app.dependency_overrides[deps.get_github_client] = lambda: gh

    class C:
        pass
    c = C(); c.app, c.gh, c.db, c.deps = app, gh, SessionLocal, deps
    c.client = lambda: TestClient(app, follow_redirects=False)
    return c


def login(ctx, github_user=None):
    """Perform the real OAuth callback against the fake GitHub; returns (client, csrf)."""
    from app.core.auth_tokens import sign_payload
    from app.core.config import get_settings
    if github_user:
        ctx.gh.user = github_user
    c = ctx.client()
    c.cookies.set("synaxys_oauth", sign_payload(get_settings().app_secret_key, "oauth", {"state": "S", "v": "V"}, 600),
                  path="/api/v1/auth/github")
    r = c.get("/api/v1/auth/github/callback?code=abc&state=S")
    assert "status=success" in r.headers["location"], r.headers["location"]
    csrf = c.get("/api/v1/auth/me").json()["csrf_token"]
    return c, csrf
