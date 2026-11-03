"""Settings: integration status (booleans + non-secret values ONLY) and the caller's own audit trail."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, settings_dep
from app.core.config import Settings
from app.db.session import get_db
from app.models import AuditLog, OAuthIdentity, User
from app.schemas.settings import AuditOut, IntegrationItem, IntegrationsOut
from app.services.integration_status import integration_items

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/integrations", response_model=IntegrationsOut)
def integrations(db: Session = Depends(get_db), user: User = Depends(current_user), s: Settings = Depends(settings_dep)):
    stored = db.scalar(select(OAuthIdentity.id).where(OAuthIdentity.user_id == user.id, OAuthIdentity.provider == "github", OAuthIdentity.access_token_enc.is_not(None))) is not None
    return IntegrationsOut(items=[IntegrationItem(**i) for i in integration_items(s)], environment=s.app_env, webhook_url=f"{s.backend_url.rstrip('/')}/api/v1/webhooks/github",
                           oauth_callback_url=s.github_redirect_uri, install_url=f"https://github.com/apps/{s.github_app_slug}/installations/new" if s.github_app_slug else None,
                           demo_login=s.demo_login_available, mock_llm=s.review_use_mock_llm and not s.openai_configured, vector_backend=s.vector_backend, github_token_stored=stored)


@router.get("/audit", response_model=list[AuditOut])
def audit(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The caller's OWN sensitive-operation history (never other users')."""
    rows = db.scalars(select(AuditLog).where(AuditLog.user_id == user.id).order_by(AuditLog.id.desc()).limit(limit)).all()
    return [AuditOut(id=a.id, action=a.action, target_type=a.target_type, target_id=a.target_id, created_at=a.created_at.isoformat()) for a in rows]
