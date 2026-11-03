import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_handlers
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.log_level)
    app = FastAPI(title="SYNAXYS API", version="0.1.0",
                  docs_url=None if s.is_production else "/docs", redoc_url=None,
                  openapi_url=None if s.is_production else "/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origin_list, allow_credentials=True,
                       allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type", "X-CSRF-Token"])

    @app.middleware("http")
    async def guards(request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > s.max_request_bytes:
            return JSONResponse({"error": {"code": "payload_too_large", "message": "Request body too large"}}, status_code=413)
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    register_handlers(app)
    app.include_router(api_router)
    logging.getLogger("synaxys").info("SYNAXYS API started (env=%s)", s.app_env)
    return app


app = create_app()
