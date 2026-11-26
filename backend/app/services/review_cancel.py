"""Cancel a review that is still WAITING in the internal queue (Phase 2). Nothing is ever touched on GitHub.

How it is race-safe: worker claims are `UPDATE ... WHERE status='queued'` (job_queue.claim_next) and so is our cancel
(job_queue.cancel). The database lets exactly one of them win. If the worker won, our UPDATE matches 0 rows, we roll back and
answer 409; if we won, the job is 'cancelled' and can never be claimed. The review row is changed in the SAME transaction, and only
`WHERE status='queued'`, so a review can never be marked cancelled while a worker is already running it."""
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequest, Conflict
from app.db.base import utcnow
from app.models import AuditLog, BackgroundJob, CodeReview, PullRequest
from app.services import job_queue
from app.services.review_workflow_logic import CANCEL_MESSAGES, cancel_blocker


def _review_jobs(db: Session, review: CodeReview) -> list[BackgroundJob]:
    base = f"review:{review.dedup_key}"
    rows = db.scalars(select(BackgroundJob).where(BackgroundJob.kind == "review", BackgroundJob.dedup_key.like(f"{base}%")).order_by(BackgroundJob.id.desc())).all()
    return [j for j in rows if (j.dedup_key == base or j.dedup_key.startswith(base + ":retry:")) and (j.payload or {}).get("review_id") == review.id]


def cancel_queued_review(db: Session, user_id: int, review: CodeReview, pr: PullRequest) -> dict:
    code = cancel_blocker(review_status=review.status, is_demo=review.is_demo or pr.is_demo)
    if code == "demo_readonly":
        raise BadRequest(CANCEL_MESSAGES[code], code=code)
    if code:
        raise Conflict(CANCEL_MESSAGES[code], code=code)
    jobs = _review_jobs(db, review)
    queued = [j for j in jobs if j.status == "queued"]
    if not queued and any(j.status == "processing" for j in jobs):
        raise Conflict(CANCEL_MESSAGES["not_queued"], code="not_queued")
    cancelled_ids = [j.id for j in queued if job_queue.cancel(db, j.id, reason="Cancelled by user before execution", commit=False)]
    if queued and not cancelled_ids:  # a worker claimed every queued job first
        db.rollback()
        raise Conflict(CANCEL_MESSAGES["not_queued"], code="not_queued")
    now = utcnow()
    res = db.execute(update(CodeReview).where(CodeReview.id == review.id, CodeReview.status == "queued")
                     .values(status="cancelled", error="Cancelled by user", finished_at=now, cancelled_by_id=user_id, cancelled_at=now))
    if res.rowcount != 1:  # the review moved on (for example a worker set 'processing' after we looked)
        db.rollback()
        raise Conflict(CANCEL_MESSAGES["not_queued"], code="not_queued")
    db.add(AuditLog(user_id=user_id, action="review.cancel", target_type="review", target_id=str(review.id),
                    meta={"job_ids": cancelled_ids, "orphaned": not queued, "pull_request": pr.number}))
    db.commit()
    db.refresh(review)
    return {"cancelled_jobs": len(cancelled_ids)}
