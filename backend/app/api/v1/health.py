from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import settings_dep
from app.core.config import Settings
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def liveness():
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(db: Session = Depends(get_db), s: Settings = Depends(settings_dep)):
    db.execute(text("SELECT 1"))
    return {"status": "ready", "integrations": {"github_oauth": s.github_oauth_configured, "github_app": s.github_app_configured,
                                                 "openai": s.openai_configured, "pinecone": s.pinecone_configured}}
