from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import active_workspace, current_user
from app.core.exceptions import NotFound
from app.db.session import get_db
from app.models import Notification, User
from app.schemas.workspaces import NotificationOut, NotificationPage
from app.services import notification_service as svc

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(id=n.id, kind=n.kind, title=n.title, body=n.body, link=n.link, workspace_id=n.workspace_id, read=n.read_at is not None, created_at=n.created_at.isoformat())


@router.get("", response_model=NotificationPage)
def list_notifications(unread: bool = False, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(current_user),
                       ws: int | None = Depends(active_workspace)):
    """The caller's own notifications only. With an active workspace: that workspace's plus workspace-independent ones (e.g. export ready)."""
    q = select(Notification).where(Notification.user_id == user.id)
    if ws is not None:
        q = q.where((Notification.workspace_id == ws) | Notification.workspace_id.is_(None))
    if unread:
        q = q.where(Notification.read_at.is_(None))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Notification.id.desc()).limit(page_size).offset((page - 1) * page_size)).all()
    return NotificationPage(items=[_out(n) for n in rows], total=total, unread=svc.unread_count(db, user.id), page=page, page_size=page_size)


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"unread": svc.unread_count(db, user.id)}


@router.post("/read-all")
def read_all(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"marked": svc.mark_all_read(db, user.id)}


@router.post("/{notification_id}/read", status_code=204)
def read_one(notification_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not svc.mark_read(db, user.id, notification_id):
        raise NotFound("Notification not found")
