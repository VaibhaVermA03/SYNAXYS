"""Admin view over the real background-job queue (table background_jobs). Read paths never expose payloads beyond the
allow-list in admin_policy.safe_payload and never raw stack traces (last_error is stored redacted and truncated)."""
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequest, Conflict, NotFound
from app.db.base import utcnow
from app.models import AuditLog, BackgroundJob, CodeReview, IndexingJob, PullRequest, Repository, User
from app.services.admin_policy import VALID_KINDS, VALID_STATUSES, can_retry, clamp_page, safe_payload

_iso = lambda d: d.isoformat() if d else None  # noqa: E731


def _context(db: Session, jobs: list[BackgroundJob]) -> dict[int, dict]:
    """job.id -> {repository_id, repository, pull_request_number, review_status}, resolved in bulk (no N+1)."""
    review_ids = {int(j.payload["review_id"]) for j in jobs if isinstance(j.payload, dict) and isinstance(j.payload.get("review_id"), int)}
    repo_ids = {int(j.payload["repository_id"]) for j in jobs if isinstance(j.payload, dict) and isinstance(j.payload.get("repository_id"), int)}
    reviews: dict[int, tuple] = {}
    if review_ids:
        for rid, status, pr_no, repo_id in db.execute(select(CodeReview.id, CodeReview.status, PullRequest.number, PullRequest.repository_id)
                                                      .join(PullRequest, PullRequest.id == CodeReview.pull_request_id).where(CodeReview.id.in_(review_ids))):
            reviews[rid] = (status, pr_no, repo_id)
            repo_ids.add(repo_id)
    names = dict(db.execute(select(Repository.id, Repository.full_name).where(Repository.id.in_(repo_ids))).all()) if repo_ids else {}
    out: dict[int, dict] = {}
    for j in jobs:
        p = j.payload if isinstance(j.payload, dict) else {}
        status = pr_no = None
        repo_id = p.get("repository_id") if isinstance(p.get("repository_id"), int) else None
        if isinstance(p.get("review_id"), int) and p["review_id"] in reviews:
            status, pr_no, repo_id = reviews[p["review_id"]]
        out[j.id] = {"repository_id": repo_id, "repository": names.get(repo_id), "pull_request_number": pr_no, "review_status": status}
    return out


def _row(j: BackgroundJob, ctx: dict) -> dict:
    return {"id": j.id, "kind": j.kind, "status": j.status, "attempts": j.attempts, "max_attempts": j.max_attempts, "created_at": _iso(j.created_at),
            "run_after": _iso(j.run_after), "finished_at": _iso(j.finished_at), "error": j.last_error, "repository_id": ctx.get("repository_id"),
            "repository": ctx.get("repository"), "pull_request_number": ctx.get("pull_request_number"), "workspace": None, "can_retry": can_retry(j.status)}


def list_jobs(db: Session, *, status: str | None, kind: str | None, page: int, page_size: int) -> dict:
    if status is not None and status not in VALID_STATUSES:
        raise BadRequest("Unknown status filter", code="invalid_filter")
    if kind is not None and kind not in VALID_KINDS:
        raise BadRequest("Unknown kind filter", code="invalid_filter")
    page, page_size = clamp_page(page, page_size)
    q = select(BackgroundJob)
    cq = select(func.count()).select_from(BackgroundJob)
    for col, val in ((BackgroundJob.status, status), (BackgroundJob.kind, kind)):
        if val:
            q, cq = q.where(col == val), cq.where(col == val)
    jobs = db.scalars(q.order_by(BackgroundJob.id.desc()).limit(page_size).offset((page - 1) * page_size)).all()
    ctx = _context(db, jobs)
    return {"items": [_row(j, ctx[j.id]) for j in jobs], "total": db.scalar(cq) or 0, "page": page, "page_size": page_size}


def get_job(db: Session, job_id: int) -> dict:
    j = db.get(BackgroundJob, job_id)
    if j is None:
        raise NotFound("Job not found")
    ctx = _context(db, [j])[j.id]
    return {**_row(j, ctx), "timeout_seconds": j.timeout_seconds, "locked_at": _iso(j.locked_at), "locked_by": j.locked_by,
            "payload": safe_payload(j.payload), "review_status": ctx.get("review_status")}


def stats(db: Session, now: datetime | None = None) -> dict:
    now = now or utcnow()
    by_status = {s: 0 for s in VALID_STATUSES}
    by_status.update(dict(db.execute(select(BackgroundJob.status, func.count()).group_by(BackgroundJob.status)).all()))
    failed_by_kind = dict(db.execute(select(BackgroundJob.kind, func.count()).where(BackgroundJob.status == "failed").group_by(BackgroundJob.kind)).all())
    failed_24h = db.scalar(select(func.count()).select_from(BackgroundJob).where(BackgroundJob.status == "failed", BackgroundJob.finished_at >= now - timedelta(hours=24))) or 0
    oldest = db.scalar(select(func.min(BackgroundJob.run_after)).where(BackgroundJob.status == "queued"))
    # 'processing' whose lock is older than its own timeout: the worker's recover_stale() should have reclaimed it
    stale = sum(1 for j in db.scalars(select(BackgroundJob).where(BackgroundJob.status == "processing")).all()
                if j.locked_at is None or j.locked_at + timedelta(seconds=j.timeout_seconds) < now)
    return {"by_status": by_status, "failed_by_kind": failed_by_kind, "failed_last_24h": failed_24h,
            "queued_oldest_age_seconds": max(0, int((now - oldest).total_seconds())) if oldest else None, "stale_processing": stale, "total": sum(by_status.values())}


def retry_job(db: Session, admin: User, job_id: int) -> dict:
    """failed -> queued, atomically. The conditional UPDATE is the idempotency guard: a double click or two admins at once
    produce exactly one requeue; the loser gets 409. Linked review/indexing rows are reset in the SAME transaction, before
    the job becomes claimable (it is committed together), so a worker never sees a queued job with a stale 'failed' parent."""
    job = db.get(BackgroundJob, job_id)
    if job is None:
        raise NotFound("Job not found")
    if not can_retry(job.status):
        raise Conflict(f"Only failed jobs can be retried (this job is {job.status}).", code="not_retryable")
    payload = job.payload if isinstance(job.payload, dict) else {}
    previous_error, kind, prev_attempts = (job.last_error or "")[:300], job.kind, job.attempts

    if kind == "review" and isinstance(payload.get("review_id"), int):
        review = db.get(CodeReview, payload["review_id"])
        if review is not None and review.status not in ("failed", "queued", "cancelled"):
            raise Conflict(f"The linked review is already {review.status}; nothing to retry.", code="not_retryable")
    res = db.execute(update(BackgroundJob).where(BackgroundJob.id == job_id, BackgroundJob.status == "failed")
                     .values(status="queued", attempts=0, run_after=utcnow(), finished_at=None, last_error=None, locked_at=None, locked_by=None))
    if res.rowcount != 1:
        db.rollback()
        raise Conflict("This job was already retried or changed state.", code="not_retryable")
    if kind == "review" and isinstance(payload.get("review_id"), int):
        db.execute(update(CodeReview).where(CodeReview.id == payload["review_id"], CodeReview.status == "failed").values(status="queued", error=None, finished_at=None))
    if kind == "index" and isinstance(payload.get("indexing_job_id"), int):
        db.execute(update(IndexingJob).where(IndexingJob.id == payload["indexing_job_id"], IndexingJob.status == "failed").values(status="queued", error=None, finished_at=None))
    db.add(AuditLog(user_id=admin.id, action="admin.job_retry", target_type="background_job", target_id=str(job_id),
                    meta={"kind": kind, "previous_attempts": prev_attempts, "previous_error": previous_error}))
    db.commit()
    return get_job(db, job_id)
