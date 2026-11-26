from fastapi import APIRouter, Depends

from app.api.deps import rate_limit
from app.api.v1 import (account, admin, auth, notifications, code_search, dashboard, github, health, pull_requests, repositories, review_actions,
                        review_rules, reviews, settings, webhooks, workspaces)

api_router = APIRouter(prefix="/api/v1")

# Deliberately NOT rate limited per IP: liveness probes, and GitHub webhooks (GitHub delivers from a small shared set of
# addresses, so an IP limit would drop legitimate deliveries; webhooks are protected by HMAC verification and a size cap).
api_router.include_router(health.router)
api_router.include_router(webhooks.router)

# Everything else: per-IP flood limit (Redis-backed when REDIS_URL is set) ...
_ip_limited = APIRouter(dependencies=[Depends(rate_limit("global_ip", "global_rate_limit_per_minute"))])
_ip_limited.include_router(auth.router)  # login/callback additionally keep their own, stricter limits (see auth.py)

# ... and, for routes that need a session, a per-user limit that cannot be dodged by changing IP.
_authed = APIRouter(dependencies=[Depends(rate_limit("global_user", "user_rate_limit_per_minute", by="user"))])
for r in (github.router, dashboard.router, pull_requests.router, reviews.router, review_rules.router, review_actions.router,
          code_search.router, repositories.router, settings.router, admin.router, workspaces.router, notifications.router, account.router):
    _authed.include_router(r)
_ip_limited.include_router(_authed)
api_router.include_router(_ip_limited)
