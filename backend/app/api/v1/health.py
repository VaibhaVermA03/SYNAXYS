import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import rate_limiter_status, settings_dep
from app.core import monitoring
from app.core.config import Settings
from app.db.session import get_db

router = APIRouter(tags=["health"])
log = logging.getLogger("synaxys.health")


@router.get("/health")
def liveness():
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(db: Session = Depends(get_db), s: Settings = Depends(settings_dep)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - report DB connectivity problems as 503 + an error event, never a stack trace
        log.error("readiness: database unreachable (%s)", type(exc).__name__)
        monitoring.capture_exception(exc, area="database_connectivity")
        return JSONResponse({"status": "unavailable", "database": "down"}, status_code=503)
    return {"status": "ready", "rate_limiter": rate_limiter_status(s),
            "integrations": {"github_oauth": s.github_oauth_configured, "github_app": s.github_app_configured,
                             "openai": s.openai_configured, "pinecone": s.pinecone_configured, "sentry": s.sentry_configured}}
