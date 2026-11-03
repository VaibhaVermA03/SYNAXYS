"""GitHub OAuth (authorization-code + PKCE S256 + signed state) and cookie sessions."""
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import SESSION_COOKIE, check_origin, current_session, get_github_client, rate_limit, settings_dep
from app.core.auth_tokens import csrf_token, new_pkce_pair, sign_payload, verify_csrf, verify_payload
from app.core.config import Settings
from app.core.exceptions import AppError, Forbidden, NotConfigured
from app.db.session import get_db
from app.models import AuditLog
from app.schemas.auth import IntegrationStatus, MeOut, UserOut
from app.services import auth_service
from app.services.github_service import OAUTH_AUTHORIZE_URL, GitHubClient

router = APIRouter(prefix="/auth", tags=["auth"])
STATE_COOKIE = "synaxys_oauth"
STATE_TTL = 600
limit_auth = rate_limit("auth", "auth_rate_limit_per_minute")


def _status(s: Settings) -> IntegrationStatus:
    return IntegrationStatus(github_oauth=s.github_oauth_configured, github_app=s.github_app_configured,
                             webhook_secret=bool(s.github_webhook_secret), openai=s.openai_configured,
                             pinecone=s.pinecone_configured, demo_mode=not s.github_oauth_configured,
                             demo_login=s.demo_login_available)


def _frontend(s: Settings, **q) -> RedirectResponse:
    r = RedirectResponse(f"{s.frontend_url}/auth/callback?{urlencode(q)}", status_code=302)
    r.delete_cookie(STATE_COOKIE, path="/api/v1/auth/github")
    return r


@router.get("/config", response_model=IntegrationStatus)
def public_config(s: Settings = Depends(settings_dep)):
    return _status(s)


@router.get("/github/login", dependencies=[Depends(limit_auth)])
def github_login(s: Settings = Depends(settings_dep)):
    if not s.github_oauth_configured:
        raise NotConfigured("GitHub OAuth is not configured. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET.",
                            code="github_oauth_not_configured")
    state = secrets.token_urlsafe(32)
    verifier, challenge = new_pkce_pair()
    url = OAUTH_AUTHORIZE_URL + "?" + urlencode({
        "client_id": s.github_client_id, "redirect_uri": s.github_redirect_uri, "state": state,
        "scope": s.github_oauth_scope, "code_challenge": challenge, "code_challenge_method": "S256"})
    resp = RedirectResponse(url, status_code=302)
    # SameSite=Lax so the cookie survives GitHub's top-level redirect back to us.
    resp.set_cookie(STATE_COOKIE, sign_payload(s.app_secret_key, "oauth", {"state": state, "v": verifier}, STATE_TTL),
                    max_age=STATE_TTL, httponly=True, secure=s.cookie_secure, samesite="lax", path="/api/v1/auth/github")
    return resp


@router.get("/github/callback", dependencies=[Depends(limit_auth)])
def github_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                    db: Session = Depends(get_db), s: Settings = Depends(settings_dep),
                    gh: GitHubClient = Depends(get_github_client)):
    if error:
        return _frontend(s, error="access_denied")
    data = verify_payload(s.app_secret_key, "oauth", request.cookies.get(STATE_COOKIE))
    if not data or not state or not code or not secrets.compare_digest(data["state"], state):
        return _frontend(s, error="invalid_state")
    try:
        token_resp = gh.exchange_code(code, data["v"])
        access_token = token_resp["access_token"]
        gh_user = gh.get_user(access_token)
        user = auth_service.upsert_user_from_github(db, s, gh_user, access_token, token_resp.get("scope", ""))
    except NotConfigured:
        return _frontend(s, error="not_configured")
    except AppError:
        return _frontend(s, error="oauth_failed")  # details are logged, never shown
    raw = auth_service.create_session(db, s, user, request.headers.get("user-agent"))
    db.add(AuditLog(user_id=user.id, action="auth.login", target_type="user", target_id=str(user.id)))
    db.commit()
    resp = _frontend(s, status="success")
    resp.set_cookie(SESSION_COOKIE, raw, max_age=s.session_ttl_hours * 3600, httponly=True, secure=s.cookie_secure,
                    samesite=s.cookie_samesite, path="/")
    return resp


@router.get("/me", response_model=MeOut)
def me(auth=Depends(current_session), s: Settings = Depends(settings_dep)):
    user, sess = auth
    return MeOut(user=UserOut(id=user.id, login=user.login, name=user.name, avatar_url=user.avatar_url),
                 csrf_token=csrf_token(s.app_secret_key, sess.csrf_secret), integrations=_status(s))


@router.post("/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_db), s: Settings = Depends(settings_dep)):
    check_origin(request, s)
    raw = request.cookies.get(SESSION_COOKIE)
    found = auth_service.resolve_session(db, raw)
    if found and not verify_csrf(s.app_secret_key, found[1].csrf_secret, request.headers.get("x-csrf-token")):
        raise Forbidden("Missing or invalid CSRF token", code="csrf_failed")
    auth_service.revoke_session(db, raw)
    if found:
        db.add(AuditLog(user_id=found[0].id, action="auth.logout"))
        db.commit()
    resp = Response(status_code=204)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.post("/demo-login", status_code=204, dependencies=[Depends(limit_auth)])
def demo_login(request: Request, db: Session = Depends(get_db), s: Settings = Depends(settings_dep)):
    """Local demo only: signs in the seeded sample user. Disabled in production."""
    from sqlalchemy import select
    from app.core.exceptions import NotFound
    from app.models import User
    check_origin(request, s)
    if not s.demo_login_available:
        raise NotFound("Not found")
    user = db.scalar(select(User).where(User.github_id == -1))
    if user is None:
        raise NotFound("Demo data not found. Run: python -m app.db.seed", code="demo_not_seeded")
    raw = auth_service.create_session(db, s, user, request.headers.get("user-agent"))
    db.add(AuditLog(user_id=user.id, action="auth.demo_login"))
    db.commit()
    resp = Response(status_code=204)
    resp.set_cookie(SESSION_COOKIE, raw, max_age=s.session_ttl_hours * 3600, httponly=True, secure=s.cookie_secure,
                    samesite=s.cookie_samesite, path="/")
    return resp
