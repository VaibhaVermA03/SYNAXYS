import logging
import re
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_handlers
from app.core.logging import configure_logging, request_id_var
from app.core.monitoring import init_monitoring
from app.core.security_headers import api_security_headers

_REQUEST_ID_OK = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.log_level)
    init_monitoring(s, "api")
    log = logging.getLogger("synaxys")
    if s.is_production and not s.redis_configured:
        log.warning("REDIS_URL is not set: rate limits are per process. Run a single API instance or configure Redis.")
    app = FastAPI(title="SYNAXYS API", version="0.1.0",
                  docs_url=None if s.is_production else "/docs", redoc_url=None,
                  openapi_url=None if s.is_production else "/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origin_list, allow_credentials=True,
                       allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type", "X-CSRF-Token", "X-Workspace-Id"])
    https = s.is_production and s.cookie_secure

    @app.middleware("http")
    async def guards(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _REQUEST_ID_OK.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        try:
            cl = request.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > s.max_request_bytes:
                resp = JSONResponse({"error": {"code": "payload_too_large", "message": "Request body too large"}}, status_code=413)
            else:
                resp = await call_next(request)
            for k, v in api_security_headers(request.url.path, is_production=s.is_production, https=https).items():
                resp.headers.setdefault(k, v)
            resp.headers["X-Request-ID"] = rid
            return resp
        finally:
            request_id_var.reset(token)

    register_handlers(app)
    app.include_router(api_router)
    log.info("SYNAXYS API started (env=%s, rate limiter=%s, sentry=%s)", s.app_env, "redis" if s.redis_configured else "memory", s.sentry_configured)
    return app


app = create_app()
