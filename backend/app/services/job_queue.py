"""Durable DB-backed job queue.

* enqueue(): idempotent via unique dedup_key (savepoint, so callers' transactions survive).
* claim_next(): SELECT .. FOR UPDATE SKIP LOCKED on PostgreSQL, plus a fenced conditional
  UPDATE (status='queued') that is also safe on SQLite.
* complete()/fail(): fenced on (status='processing', locked_by=worker) so a worker whose job
  was already recovered cannot overwrite the new outcome.
* recover_stale(): jobs whose lock outlived their timeout are retried or failed.
"""
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import BackgroundJob
from app.services.job_policy import backoff_seconds, is_stale, sanitize_error


def enqueue(db: Session, kind: str, payload: dict, dedup_key: str | None = None, *, max_attempts: int = 4,
            timeout_seconds: int = 600, run_after: datetime | None = None) -> tuple[BackgroundJob, bool]:
    """Returns (job, created). Does not commit."""
    if dedup_key:
        existing = db.scalar(select(BackgroundJob).where(BackgroundJob.dedup_key == dedup_key))
        if existing:
            return existing, False
    job = BackgroundJob(kind=kind, payload=payload, dedup_key=dedup_key, max_attempts=max_attempts,
                        timeout_seconds=timeout_seconds, run_after=run_after or utcnow())
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError:  # concurrent insert of same dedup_key
        return db.scalar(select(BackgroundJob).where(BackgroundJob.dedup_key == dedup_key)), False
    return job, True


def enqueue_or_requeue(db: Session, kind: str, payload: dict, dedup_key: str, **kw) -> tuple[BackgroundJob, bool]:
    """For recurring one-per-subject jobs (e.g. disconnect cleanup): a finished job with the same key is reset
    and queued again instead of being silently treated as 'already done'."""
    job, created = enqueue(db, kind, payload, dedup_key, **kw)
    if created:
        return job, True
    if job.status in ("succeeded", "failed", "cancelled"):
        job.status, job.attempts, job.run_after, job.finished_at, job.last_error, job.payload = "queued", 0, utcnow(), None, None, payload
        return job, True
    return job, False


def claim_next(db: Session, worker_id: str, kinds: list[str] | None = None, now: datetime | None = None) -> BackgroundJob | None:
    now = now or utcnow()
    q = select(BackgroundJob).where(BackgroundJob.status == "queued", BackgroundJob.run_after <= now)
    if kinds:
        q = q.where(BackgroundJob.kind.in_(kinds))
    q = q.order_by(BackgroundJob.run_after, BackgroundJob.id).limit(1)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        q = q.with_for_update(skip_locked=True)
    job = db.scalar(q)
    if job is None:
        db.rollback()
        return None
    res = db.execute(update(BackgroundJob).where(BackgroundJob.id == job.id, BackgroundJob.status == "queued")
                     .values(status="processing", locked_at=now, locked_by=worker_id, attempts=BackgroundJob.attempts + 1))
    db.commit()
    if res.rowcount != 1:
        return None
    db.refresh(job)
    return job


def complete(db: Session, job_id: int, worker_id: str) -> bool:
    res = db.execute(update(BackgroundJob).where(BackgroundJob.id == job_id, BackgroundJob.status == "processing",
                                                 BackgroundJob.locked_by == worker_id)
                     .values(status="succeeded", finished_at=utcnow(), locked_at=None, locked_by=None, last_error=None))
    db.commit()
    return res.rowcount == 1


def fail(db: Session, job_id: int, worker_id: str | None, error, *, retriable: bool = True, now: datetime | None = None,
         rand=None) -> str | None:
    """Returns 'queued' (will retry), 'failed' (final), or None if the fence rejected the update."""
    now = now or utcnow()
    job = db.get(BackgroundJob, job_id)
    if job is None or job.status != "processing" or (worker_id is not None and job.locked_by != worker_id):
        return None
    msg = sanitize_error(error)
    if retriable and job.attempts < job.max_attempts:
        delay = backoff_seconds(job.attempts) if rand is None else backoff_seconds(job.attempts, rand=rand)
        job.status, job.run_after = "queued", now + timedelta(seconds=delay)
        outcome = "queued"
    else:
        job.status, job.finished_at = "failed", now
        outcome = "failed"
    job.locked_at = job.locked_by = None
    job.last_error = msg
    db.commit()
    return outcome


def recover_stale(db: Session, now: datetime | None = None) -> list[tuple[int, str]]:
    """Requeue/fail jobs abandoned by crashed or timed-out workers. Returns [(job_id, outcome)]."""
    now = now or utcnow()
    out = []
    for job in db.scalars(select(BackgroundJob).where(BackgroundJob.status == "processing")).all():
        if is_stale(job.locked_at, job.timeout_seconds, now):
            r = fail(db, job.id, None, "Job timed out or worker was lost", retriable=True, now=now)
            if r:
                out.append((job.id, r))
    return out


def cancel(db: Session, job_id: int) -> bool:
    res = db.execute(update(BackgroundJob).where(BackgroundJob.id == job_id, BackgroundJob.status == "queued")
                     .values(status="cancelled", finished_at=utcnow()))
    db.commit()
    return res.rowcount == 1


def requeue(db: Session, job_id: int) -> bool:
    """Manual retry of a failed/cancelled job (resets attempts)."""
    res = db.execute(update(BackgroundJob).where(BackgroundJob.id == job_id, BackgroundJob.status.in_(["failed", "cancelled"]))
                     .values(status="queued", attempts=0, run_after=utcnow(), finished_at=None, last_error=None))
    db.commit()
    return res.rowcount == 1
