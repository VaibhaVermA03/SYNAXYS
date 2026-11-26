"""Central notifications (Phase 4). One row per (user, event): `dedup_key` is unique per user, so retries/duplicate webhooks never notify twice.
Delivery is in-app only (polling from the UI); no extra infrastructure. Calls never raise into the caller: a notification problem must not break a review."""
import logging

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import Notification, Repository, RepositoryAccess, WorkspaceMember

log = logging.getLogger("synaxys.notifications")


def notify(db: Session, user_ids, *, kind: str, title: str, body: str | None = None, link: str | None = None, workspace_id: int | None = None, dedup_key: str) -> int:
    """Create the notification for each user unless it exists. Returns how many were created. The caller commits."""
    created = 0
    for uid in sorted({int(u) for u in user_ids if u is not None}):
        try:
            with db.begin_nested():
                db.add(Notification(user_id=uid, workspace_id=workspace_id, kind=kind, title=title[:200], body=(body or None) and body[:500],
                                    link=link if (link or "").startswith("/app/") else None, dedup_key=dedup_key[:200]))
                db.flush()
            created += 1
        except IntegrityError:
            continue  # already notified for this event
        except Exception:  # noqa: BLE001
            log.warning("notification failed (%s)", kind)
    return created


def repo_admin_ids(db: Session, repo: Repository) -> set[int]:
    """Who cares about repository-level events: workspace owners/admins; for repositories outside a workspace, the GitHub-derived repository admins."""
    if repo.workspace_id is not None:
        return {u for (u,) in db.execute(select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == repo.workspace_id, WorkspaceMember.role.in_(["owner", "admin"])))}
    return {u for (u,) in db.execute(select(RepositoryAccess.user_id).where(RepositoryAccess.repository_id == repo.id, RepositoryAccess.role == "owner"))}


def safe(fn, *a, **kw):
    """Run a notification hook; swallow everything (the caller's transaction must stay healthy)."""
    try:
        return fn(*a, **kw)
    except Exception:  # noqa: BLE001
        log.warning("notification hook failed")
        return 0


# ---- read side ---------------------------------------------------------------------------------------------------
def unread_count(db: Session, user_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None))) or 0


def mark_read(db: Session, user_id: int, notification_id: int) -> bool:
    """Only the owner's own notification; idempotent. False = not found (never reveals other users' ids)."""
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user_id:
        return False
    if n.read_at is None:
        n.read_at = utcnow()
        db.commit()
    return True


def mark_all_read(db: Session, user_id: int) -> int:
    res = db.execute(update(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None)).values(read_at=utcnow()))
    db.commit()
    return res.rowcount or 0


# ---- event helpers (called from review/indexing/worker code through safe()) --------------------------------------
def _recipients(db: Session, repo: Repository, requester_id: int | None = None) -> set[int]:
    ids = repo_admin_ids(db, repo)
    if requester_id is not None:
        ids = ids | {requester_id}
    return ids


def on_review_completed(db: Session, review, pr, repo, findings: int, by_severity: dict[str, int]) -> int:
    """Review finished (and, separately, 'findings generated' when there are active findings). Dedup keys make worker retries harmless."""
    who = _recipients(db, repo, review.requested_by_id)
    link = f"/app/reviews/{review.id}"
    label = f"{repo.full_name} #{pr.number}"
    n = notify(db, who, kind="review_completed", title=f"Review completed: {label}", body=(pr.title or "")[:200], link=link, workspace_id=repo.workspace_id, dedup_key=f"review:{review.id}:completed")
    if findings > 0:
        top = ", ".join(f"{c} {s}" for s, c in by_severity.items() if c)
        n += notify(db, who, kind="findings_generated", title=f"{findings} finding(s) on {label}", body=top[:300] or None, link=link, workspace_id=repo.workspace_id, dedup_key=f"review:{review.id}:findings")
    return n


def on_review_failed(db: Session, review_id: int) -> int:
    from app.models import CodeReview, PullRequest
    r = db.get(CodeReview, review_id)
    if r is None:
        return 0
    pr = db.get(PullRequest, r.pull_request_id)
    repo = db.get(Repository, pr.repository_id)
    return notify(db, _recipients(db, repo, r.requested_by_id), kind="review_failed", title=f"Review failed: {repo.full_name} #{pr.number}", body=(r.error or "")[:300] or None,
                  link=f"/app/reviews/{r.id}", workspace_id=repo.workspace_id, dedup_key=f"review:{r.id}:failed")


def on_index_finished(db: Session, repo: Repository, branch: str, outcome: str, job) -> int:
    if outcome == "completed":
        title, kind = f"Indexing finished: {repo.full_name} ({branch})", "index_completed"
    else:
        title, kind = f"Indexing partly finished: {repo.full_name} ({branch})", "index_partial"
    return notify(db, repo_admin_ids(db, repo), kind=kind, title=title, body=f"{job.files_indexed} files processed." if outcome == "completed" else (job.error or "")[:300] or None,
                  link="/app/repositories", workspace_id=repo.workspace_id, dedup_key=f"index:{job.id}:{outcome}")


def on_index_failed(db: Session, repo_id: int, job_id: int, error: str) -> int:
    repo = db.get(Repository, repo_id)
    if repo is None:
        return 0
    return notify(db, repo_admin_ids(db, repo), kind="index_failed", title=f"Indexing failed: {repo.full_name}", body=error[:300] or None, link="/app/repositories", workspace_id=repo.workspace_id,
                  dedup_key=f"index_failed:{job_id}")
