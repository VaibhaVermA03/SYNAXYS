"""Webhook delivery handling: idempotent, validated, persisted, enqueue-only (never runs a review)."""
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import utcnow
from app.models import (BackgroundJob, CodeReview, GitHubInstallation, PullRequest, Repository, ReviewConfiguration,
                        WebhookDelivery)
from app.services import job_queue
from app.services.job_policy import sanitize_error
from app.services.webhook_events import (EventValidationError, decide_pr_action, parse_installation, parse_pull_request,
                                          parse_push, push_targets_default_branch)

log = logging.getLogger("synaxys.webhooks")




def _parse_dt(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
    except ValueError:
        return None


def handle_delivery(db: Session, s: Settings, delivery_id: str, event: str, payload: dict) -> tuple[str, str]:
    """Returns (outcome, detail). outcome in: queued | updated | ignored | duplicate.

    A redelivery (same GUID) of a delivery that previously FAILED is processed again;
    one that completed is reported as duplicate and creates nothing.
    """
    existing = db.scalar(select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id))
    if existing is not None and existing.status != "failed":
        return "duplicate", "delivery already processed"
    try:
        delivery = existing or WebhookDelivery(delivery_id=delivery_id, event=event[:60],
                                               action=str(payload.get("action"))[:60] if payload.get("action") else None,
                                               installation_id=(payload.get("installation") or {}).get("id")
                                               if isinstance((payload.get("installation") or {}).get("id"), int) else None)
        if existing is None:
            db.add(delivery)
            db.flush()  # unique(delivery_id) arbitrates concurrent duplicates
    except IntegrityError:
        db.rollback()
        return "duplicate", "delivery already processed"
    try:
        outcome, detail = _dispatch(db, s, event, payload)
        delivery.status, delivery.detail = ("queued" if outcome == "queued" else "ignored" if outcome == "ignored" else "processed"), sanitize_error(detail, 300)
        db.commit()
        return outcome, detail
    except EventValidationError as e:
        db.rollback()
        _record_failure(db, delivery_id, event, str(e))
        raise
    except Exception as e:  # noqa: BLE001
        db.rollback()
        _record_failure(db, delivery_id, event, e)
        log.exception("webhook processing failed")
        raise


def _record_failure(db: Session, delivery_id: str, event: str, err) -> None:
    row = db.scalar(select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id))
    if row is None:
        row = WebhookDelivery(delivery_id=delivery_id, event=event[:60])
        db.add(row)
    row.status, row.detail = "failed", sanitize_error(err, 300)
    db.commit()


def _dispatch(db: Session, s: Settings, event: str, payload: dict) -> tuple[str, str]:
    if event == "pull_request":
        return _on_pull_request(db, s, payload)
    if event == "push":
        return _on_push(db, payload)
    if event == "installation":
        return _on_installation(db, payload)
    if event == "installation_repositories":
        return _on_installation_repos(db, payload)
    return "ignored", f"unsupported event: {event[:40]}"


def _on_pull_request(db: Session, s: Settings, payload: dict):
    ev = parse_pull_request(payload)
    repo = db.scalar(select(Repository).where(Repository.github_repo_id == ev.github_repo_id))
    if repo is None:
        return "ignored", "repository not known"
    cfg = repo.config or ReviewConfiguration(repository_id=repo.id)
    decision = decide_pr_action(ev, repo.is_enabled, list(cfg.allowed_actions or []))
    if decision == "ignore":
        return "ignored", f"action not handled: {ev.action}"

    pr = db.scalar(select(PullRequest).where(PullRequest.repository_id == repo.id, PullRequest.number == ev.number))
    if pr is None:
        pr = PullRequest(repository_id=repo.id, number=ev.number, author_login=ev.author, base_branch=ev.base_branch,
                         head_branch=ev.head_branch, head_sha=ev.head_sha, title=ev.title)
        db.add(pr)
    pr.title, pr.author_login, pr.state, pr.merged = ev.title, ev.author, ev.state, ev.merged
    pr.base_branch, pr.head_branch, pr.head_sha, pr.html_url = ev.base_branch, ev.head_branch, ev.head_sha, ev.html_url
    pr.github_updated_at = _parse_dt(ev.updated_at)
    db.flush()

    if decision != "review":
        return "updated", f"pr #{ev.number} {ev.action}"

    # Supersede stale work for older commits of this PR.
    for old in db.scalars(select(CodeReview).where(CodeReview.pull_request_id == pr.id, CodeReview.status == "queued",
                                                    CodeReview.head_sha != ev.head_sha)).all():
        old.status = "cancelled"
        job = db.scalar(select(BackgroundJob).where(BackgroundJob.dedup_key == f"review:{old.dedup_key}"))
        if job and job.status == "queued":
            job.status, job.finished_at = "cancelled", utcnow()

    key = f"pr:{repo.id}:{ev.number}:sha:{ev.head_sha}:webhook"
    review = db.scalar(select(CodeReview).where(CodeReview.dedup_key == key))
    if review is not None:
        return "ignored", "review for this commit already exists"
    review = CodeReview(pull_request_id=pr.id, dedup_key=key, head_sha=ev.head_sha, status="queued", trigger="webhook")
    db.add(review)
    db.flush()
    job, created = job_queue.enqueue(db, "review", {"review_id": review.id}, f"review:{key}",
                                     max_attempts=s.job_max_attempts, timeout_seconds=s.job_default_timeout_seconds)
    return "queued", f"review queued for pr #{ev.number}" if created else "review job already queued"


def _on_push(db: Session, payload: dict):
    ev = parse_push(payload)
    repo = db.scalar(select(Repository).where(Repository.github_repo_id == ev.github_repo_id))
    if repo is None or not repo.is_enabled or not (repo.config and repo.config.index_enabled):
        return "ignored", "repository not enabled for indexing"
    if not push_targets_default_branch(ev):
        return "ignored", "push is not a non-delete update of the default branch"
    _, created = job_queue.enqueue(db, "index", {"repository_id": repo.id, "branch": repo.default_branch, "commit": ev.after},
                                   f"index:{repo.id}:{ev.after}", timeout_seconds=1800)
    return ("queued", "index job queued") if created else ("ignored", "index job already queued")


def _on_installation(db: Session, payload: dict):
    ev = parse_installation(payload)
    inst = db.scalar(select(GitHubInstallation).where(GitHubInstallation.installation_id == ev.installation_id))
    if ev.action == "created":
        if inst is None:
            inst = GitHubInstallation(installation_id=ev.installation_id, account_login=ev.account_login, account_type=ev.account_type)
            db.add(inst)
            db.flush()
        inst.deleted_at = None
        _add_repos(db, inst, ev.added)
        return "updated", "installation created"
    if inst is None:
        return "ignored", "installation not known"
    if ev.action == "deleted":
        inst.deleted_at = utcnow()
        for repo in db.scalars(select(Repository).where(Repository.installation_id == inst.id)).all():
            _disable_repo(db, repo)
        return "updated", "installation deleted; repositories disabled"
    if ev.action in ("suspend", "unsuspend"):
        inst.suspended_at = utcnow() if ev.action == "suspend" else None
        return "updated", f"installation {ev.action}"
    return "ignored", f"installation action not handled: {ev.action}"


def _on_installation_repos(db: Session, payload: dict):
    ev = parse_installation(payload)
    inst = db.scalar(select(GitHubInstallation).where(GitHubInstallation.installation_id == ev.installation_id))
    if inst is None:
        return "ignored", "installation not known"
    _add_repos(db, inst, ev.added)
    for ref in ev.removed:
        repo = db.scalar(select(Repository).where(Repository.github_repo_id == ref.github_repo_id))
        if repo is not None:
            _disable_repo(db, repo)
    return "updated", f"repositories added={len(ev.added)} removed={len(ev.removed)}"


def _add_repos(db: Session, inst: GitHubInstallation, refs) -> None:
    for ref in refs:
        if db.scalar(select(Repository).where(Repository.github_repo_id == ref.github_repo_id)) is None:
            r = Repository(installation_id=inst.id, github_repo_id=ref.github_repo_id, full_name=ref.full_name, is_private=ref.private)
            r.config = ReviewConfiguration()
            db.add(r)  # reviewing stays disabled until an admin connects it


def _disable_repo(db: Session, repo: Repository) -> None:
    repo.is_enabled, repo.index_status = False, "not_indexed"
    job_queue.enqueue_or_requeue(db, "index_delete", {"repository_id": repo.id}, f"index_delete:{repo.id}")
