"""Shared FastAPI dependencies: settings, DB, GitHub client, auth, CSRF, rate limits."""
import threading

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.auth_tokens import verify_csrf
from app.core.config import Settings, get_settings
from app.core.admin import is_admin_github_id
from app.core.exceptions import Forbidden, NotFound, RateLimited, Unauthorized
from app.core.rate_limit import DistributedLimiter, extract_client_ip
from app.core.redis_client import get_redis
from app.db.session import get_db
from app.models import User, UserSession
from app.services.auth_service import resolve_session
from app.services.github_service import GitHubClient

SESSION_COOKIE = "synaxys_session"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def settings_dep() -> Settings:
    return get_settings()


def get_github_client(s: Settings = Depends(settings_dep)) -> GitHubClient:
    return GitHubClient(s)  # tests override this dependency with a fake-backed client


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


_limiters: dict[str, DistributedLimiter] = {}
_limiters_lock = threading.Lock()


def reset_limiters() -> None:
    with _limiters_lock:
        for l in _limiters.values():
            l.reset()


def client_ip(request: Request, s: Settings) -> str:
    return extract_client_ip(request.headers.get("x-forwarded-for"), request.client.host if request.client else None,
                             trust_proxy=s.trust_proxy_headers, hops=s.trusted_proxy_hops)


def _limiter(name: str, limit: int, window: float, s: Settings) -> DistributedLimiter:
    key = f"{name}:{limit}:{window}"
    lim = _limiters.get(key)
    if lim is None:
        with _limiters_lock:
            lim = _limiters.get(key)
            if lim is None:
                factory = (lambda: get_redis(s)) if s.redis_configured else None
                lim = _limiters[key] = DistributedLimiter(name, limit, window, client_factory=factory, failure_mode=s.rate_limit_redis_failure,
                                                          prefix=s.rate_limit_key_prefix, retry_seconds=s.rate_limit_redis_retry_seconds)
    return lim


def rate_limiter_status(s: Settings) -> str:
    """'memory' (no Redis configured), 'redis' (healthy) or 'memory-fallback' (Redis configured but currently failing)."""
    if not s.redis_configured:
        return "memory"
    return "memory-fallback" if any(l.degraded for l in list(_limiters.values())) else "redis"


def _enforce(name: str, limit_attr_or_value, window: float, subject: str, s: Settings) -> None:
    limit = limit_attr_or_value if isinstance(limit_attr_or_value, int) else getattr(s, limit_attr_or_value)
    ok, retry = _limiter(name, limit, window, s).check(subject)
    if not ok:
        raise RateLimited(f"Too many requests. Retry in {retry}s.")


def rate_limit(name: str, limit_attr_or_value, window: float = 60.0, *, by: str = "ip"):
    """FastAPI dependency. by='ip' keys on the client address; by='user' keys on the authenticated user id
    (reuses the request's cached session lookup, so no extra DB query) and therefore requires a valid session."""
    if by == "user":
        def dep_user(request: Request, s: Settings = Depends(settings_dep), auth: tuple[User, UserSession] = Depends(current_session)):
            _enforce(name, limit_attr_or_value, window, f"u:{auth[0].id}", s)
        return dep_user

    def dep(request: Request, s: Settings = Depends(settings_dep)):
        _enforce(name, limit_attr_or_value, window, f"ip:{client_ip(request, s)}", s)
    return dep


def active_workspace(request: Request, db: Session = Depends(get_db), auth: tuple[User, UserSession] = Depends(current_session)) -> int | None:
    """The workspace the UI is working in (header X-Workspace-Id), or None. Membership is verified on EVERY request: a foreign or unknown id is a plain 404,
    so the header can only narrow what a user sees, never widen it."""
    raw = request.headers.get("x-workspace-id")
    if not raw:
        return None
    from app.services.workspace_service import require_member
    if not raw.isdigit() or len(raw) > 12:
        raise NotFound("Workspace not found")
    require_member(db, auth[0], int(raw))
    return int(raw)


def is_platform_admin(user: User, s: Settings) -> bool:
    return is_admin_github_id(user.github_id, s.admin_github_id_set)


def require_admin(user: User = Depends(current_user), s: Settings = Depends(settings_dep)) -> User:
    """Platform administrators only (ADMIN_GITHUB_IDS). Everyone else gets a plain 404, so the admin API is not discoverable."""
    if not is_platform_admin(user, s):
        raise NotFound("Not found")
    return user
