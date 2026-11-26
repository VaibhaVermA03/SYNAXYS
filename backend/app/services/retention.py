"""Scheduled cleanup of expired/old data. Idempotent, batched, and safe to run concurrently (deletes are by primary key).

Never touched: active (unexpired, unrevoked) sessions; queued/processing jobs; the newest indexing job of every repository;
repository/finding/review/comment data; indexed_files (live indexing state).
Runs inside the worker (see workers/runner.py) or from `python -m app.scripts.cleanup` (external cron)."""
import logging
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import and_, delete, func, not_, or_, select, text

from app.core import monitoring
from app.db.base import utcnow
from app.models import AuditLog, BackgroundJob, DataExport, IndexingJob, Notification, UserSession, WebhookDelivery, WorkspaceInvitation
from app.services.retention_policy import INDEXING_DONE_STATUSES, JOB_DONE_STATUSES, SECURITY_ACTION_PREFIXES, RetentionPolicy

log = logging.getLogger("synaxys.cleanup")
LOCK_KEY = 727_001  # arbitrary constant for the PostgreSQL advisory lock


def _purge(sf, model, where, policy: RetentionPolicy, dry_run: bool) -> tuple[int, bool]:
    """Delete rows matching `where` in id-ordered batches. Returns (rows, more_remaining)."""
    total = 0
    with sf() as db:
        if dry_run:
            return db.scalar(select(func.count()).select_from(model).where(where)) or 0, False
        for _ in range(policy.max_batches):
            ids = db.scalars(select(model.id).where(where).order_by(model.id).limit(policy.batch_size)).all()
            if not ids:
                return total, False
            db.execute(delete(model).where(model.id.in_(ids)))
            db.commit()
            total += len(ids)
            if len(ids) < policy.batch_size:
                return total, False
    return total, True


def _rules(policy: RetentionPolicy, now: datetime):
    c = policy.cutoffs(now)
    sec = [AuditLog.action.like(f"{p}%") for p in SECURITY_ACTION_PREFIXES]
    latest_per_repo = select(func.max(IndexingJob.id)).group_by(IndexingJob.repository_id)
    rules = []
    if c["sessions"]:
        rules.append(("sessions", UserSession, or_(UserSession.expires_at < c["sessions"], and_(UserSession.revoked_at.is_not(None), UserSession.revoked_at < c["sessions"]))))
    if c["webhook_deliveries"]:
        rules.append(("webhook_deliveries", WebhookDelivery, WebhookDelivery.received_at < c["webhook_deliveries"]))
    if c["jobs_done"]:
        rules.append(("jobs_done", BackgroundJob, and_(BackgroundJob.status.in_(JOB_DONE_STATUSES), BackgroundJob.finished_at < c["jobs_done"])))
    if c["jobs_failed"]:
        rules.append(("jobs_failed", BackgroundJob, and_(BackgroundJob.status == "failed", BackgroundJob.finished_at < c["jobs_failed"])))
    if c["indexing_jobs"]:
        rules.append(("indexing_jobs", IndexingJob, and_(IndexingJob.status.in_(INDEXING_DONE_STATUSES), IndexingJob.finished_at < c["indexing_jobs"], IndexingJob.id.not_in(latest_per_repo))))
    if c["audit_general"]:
        rules.append(("audit_general", AuditLog, and_(AuditLog.created_at < c["audit_general"], not_(or_(*sec)))))
    if c["audit_security"]:
        rules.append(("audit_security", AuditLog, AuditLog.created_at < c["audit_security"]))
    rules.append(("data_exports", DataExport, DataExport.expires_at < now))  # temporary export archives: gone as soon as they expire
    if c["invitations"]:
        rules.append(("invitations", WorkspaceInvitation, or_(and_(WorkspaceInvitation.status != "pending", func.coalesce(WorkspaceInvitation.responded_at, WorkspaceInvitation.expires_at) < c["invitations"]),
                                                              and_(WorkspaceInvitation.status == "pending", WorkspaceInvitation.expires_at < c["invitations"]))))
    if c["notifications_read"] and c["notifications_any"]:
        rules.append(("notifications", Notification, or_(and_(Notification.read_at.is_not(None), Notification.read_at < c["notifications_read"]), Notification.created_at < c["notifications_any"])))
    return rules


@contextmanager
def _exclusive(engine):
    """PostgreSQL advisory lock so two workers do not clean at once (harmless if they did; this only saves DB load)."""
    if engine is None or engine.dialect.name != "postgresql":
        yield True
        return
    with engine.connect() as conn:
        got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar())
        conn.commit()  # end the implicit transaction; the session-level lock stays
        try:
            yield got
        finally:
            if got:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
                conn.commit()


def run_cleanup(sf, settings, *, dry_run: bool = False, now: datetime | None = None, engine=None) -> dict:
    """sf: session factory. Returns {'deleted': {rule: n}, 'more': [rules], 'errors': [rules], 'skipped': bool}."""
    policy = RetentionPolicy.from_settings(settings)
    now = now or utcnow()
    result: dict = {"deleted": {}, "more": [], "errors": [], "skipped": False, "dry_run": dry_run}
    with _exclusive(engine) as got:
        if not got:
            result["skipped"] = True
            log.info("cleanup skipped: another worker holds the lock")
            return result
        for name, model, where in _rules(policy, now):
            try:
                n, more = _purge(sf, model, where, policy, dry_run)
            except Exception as exc:  # noqa: BLE001 - one failing rule must not block the others
                result["errors"].append(name)
                log.error("cleanup rule %s failed (%s)", name, type(exc).__name__)
                monitoring.capture_exception(exc, area="cleanup", rule=name)
                continue
            result["deleted"][name] = n
            if more:
                result["more"].append(name)
    total = sum(result["deleted"].values())
    log.info("cleanup %s: %s rows (%s)", "dry-run" if dry_run else "done", total, result["deleted"])
    if total and not dry_run:
        with sf() as db:
            db.add(AuditLog(user_id=None, action="system.cleanup", target_type="retention", meta={"deleted": result["deleted"], "more": result["more"]}))
            db.commit()
    return result
