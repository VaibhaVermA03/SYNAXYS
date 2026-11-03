"""Shared FastAPI dependencies: settings, DB, GitHub client, auth, CSRF, rate limits."""
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.auth_tokens import verify_csrf
from app.core.config import Settings, get_settings
from app.core.exceptions import Forbidden, RateLimited, Unauthorized
from app.core.rate_limit import SlidingWindowLimiter
from app.db.session import get_db
from app.models import User, UserSession
from app.services.auth_service import resolve_session
from app.services.github_service import GitHubClient

SESSION_COOKIE = "synaxys_session"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

_limiters: dict[str, SlidingWindowLimiter] = {}


def reset_limiters() -> None:
    for l in _limiters.values():
        l.reset()


def settings_dep() -> Settings:
    return get_settings()


def get_github_client(s: Settings = Depends(settings_dep)) -> GitHubClient:
    return GitHubClient(s)  # tests override this dependency with a fake-backed client


def client_ip(request: Request, s: Settings) -> str:
    if s.trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(name: str, limit_attr_or_value, window: float = 60.0):
    def dep(request: Request, s: Settings = Depends(settings_dep)):
        limit = limit_attr_or_value if isinstance(limit_attr_or_value, int) else getattr(s, limit_attr_or_value)
        lim = _limiters.setdefault(name, SlidingWindowLimiter(limit, window))
        ok, retry = lim.check(client_ip(request, s))
        if not ok:
            raise RateLimited(f"Too many requests. Retry in {retry}s.")
    return dep


def check_origin(request: Request, s: Settings) -> None:
    """Defense in depth: a present Origin header must be an allowed origin on unsafe methods."""
    origin = request.headers.get("origin")
    if origin and origin not in s.cors_origin_list and origin != s.frontend_url:
        raise Forbidden("Origin not allowed", code="bad_origin")


def current_session(request: Request, db: Session = Depends(get_db), s: Settings = Depends(settings_dep)) -> tuple[User, UserSession]:
    found = resolve_session(db, request.cookies.get(SESSION_COOKIE))
    if found is None:
        raise Unauthorized("Authentication required")
    if request.method in UNSAFE:
        check_origin(request, s)
        if not verify_csrf(s.app_secret_key, found[1].csrf_secret, request.headers.get("x-csrf-token")):
            raise Forbidden("Missing or invalid CSRF token", code="csrf_failed")
    return found


def current_user(auth: tuple[User, UserSession] = Depends(current_session)) -> User:
    return auth[0]
