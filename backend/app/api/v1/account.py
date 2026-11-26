"""Account data export and account deletion (see services/account_service.py for the guarantees)."""
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import SESSION_COOKIE, current_session, get_github_client, rate_limit, settings_dep
from app.core.config import Settings
from app.db.session import get_db
from app.models import DataExport, User, UserSession
from app.schemas.workspaces import DeleteAccountIn, ExportOut
from app.services import account_service as svc
from app.services.github_service import GitHubClient

router = APIRouter(prefix="/account", tags=["account"])


def _out(e: DataExport) -> ExportOut:
    return ExportOut(id=e.id, status=e.status, size_bytes=e.size_bytes, created_at=e.created_at.isoformat(), expires_at=e.expires_at.isoformat(),
                     downloaded_at=e.downloaded_at.isoformat() if e.downloaded_at else None, error=e.error)


@router.post("/exports", response_model=ExportOut, status_code=202, dependencies=[Depends(rate_limit("account_export", 3, 3600, by="user"))])
def request_export(db: Session = Depends(get_db), auth: tuple[User, UserSession] = Depends(current_session), s: Settings = Depends(settings_dep)):
    return _out(svc.request_export(db, auth[0], s.export_ttl_hours))


@router.get("/exports", response_model=list[ExportOut])
def list_exports(db: Session = Depends(get_db), auth: tuple[User, UserSession] = Depends(current_session)):
    rows = db.scalars(select(DataExport).where(DataExport.user_id == auth[0].id).order_by(DataExport.id.desc()).limit(10)).all()
    return [_out(e) for e in rows]


@router.get("/exports/{export_id}/download")
def download_export(export_id: int, db: Session = Depends(get_db), auth: tuple[User, UserSession] = Depends(current_session)):
    """Authenticated download (session cookie of the OWNER); there is no public or shareable link."""
    ex = svc.get_export_for_download(db, auth[0], export_id)
    return Response(content=ex.payload, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="synaxys-export-{ex.id}.zip"', "Cache-Control": "no-store"})


@router.post("/delete", status_code=204, dependencies=[Depends(rate_limit("account_delete", 5, 3600, by="user"))])
def delete_account(body: DeleteAccountIn, request: Request, db: Session = Depends(get_db), auth: tuple[User, UserSession] = Depends(current_session), s: Settings = Depends(settings_dep),
                   gh: GitHubClient = Depends(get_github_client)):
    """Irreversible. Requires: CSRF, the typed GitHub login, and a session younger than 15 minutes (sign in again if older)."""
    svc.delete_account(db, auth[0], auth[1], body.confirm_login, gh=gh, s=s)
    resp = Response(status_code=204)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp
