"""Review list/detail/retry. Approval and publishing are added in Phase 8."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import current_user, settings_dep
from app.api.v1.pull_requests import review_briefs
from app.core.config import Settings
from app.core.exceptions import BadRequest
from app.db.base import utcnow
from app.db.session import get_db
from app.models import AuditLog, BackgroundJob, CodeReview, PullRequest, Repository, User
from app.repositories.access import accessible_repo_ids, get_review_for_user, repo_role
from app.services.publish_logic import publish_blocker
from app.services.publish_service import review_comments
from app.schemas.reviews import CommentOut, FindingOut, ReviewDetail, ReviewListItem, ReviewPage
from app.services import job_queue

router = APIRouter(prefix="/reviews", tags=["reviews"])


def confidence_label(c: float) -> str:
    return "high" if c >= 0.8 else "medium" if c >= 0.5 else "low"


def _item(brief, pr: PullRequest, repo: Repository) -> dict:
    return dict(brief.model_dump(), repository=repo.full_name, pr_id=pr.id, pr_number=pr.number, pr_title=pr.title)


@router.get("", response_model=ReviewPage)
def list_reviews(status: str | None = Query(None, pattern="^(queued|processing|completed|failed|cancelled)$"), repository_id: int | None = None,
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(current_user)):
    base = (select(CodeReview, PullRequest, Repository).join(PullRequest, PullRequest.id == CodeReview.pull_request_id)
            .join(Repository, Repository.id == PullRequest.repository_id).where(PullRequest.repository_id.in_(accessible_repo_ids(db, user))))
    if status:
        base = base.where(CodeReview.status == status)
    if repository_id:
        base = base.where(PullRequest.repository_id == repository_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(base.order_by(CodeReview.id.desc()).limit(page_size).offset((page - 1) * page_size)).all()
    briefs = review_briefs(db, [r for r, _, _ in rows])
    return ReviewPage(items=[ReviewListItem(**_item(briefs[r.id], pr, repo)) for r, pr, repo in rows], total=total, page=page, page_size=page_size)


@router.get("/{review_id}", response_model=ReviewDetail)
def review_detail(review_id: int, db: Session = Depends(get_db), user: User = Depends(current_user), s: Settings = Depends(settings_dep)):
    review, pr, repo = get_review_for_user(db, user, review_id)
    review = db.scalar(select(CodeReview).where(CodeReview.id == review.id).options(selectinload(CodeReview.findings)))
    brief = review_briefs(db, [review])[review.id]
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    findings = sorted((f for f in review.findings if f.status != "dismissed"), key=lambda f: (order.get(f.severity, 9), f.path, f.start_line or 0))
    by_cat: dict[str, int] = {}
    for f in findings:
        by_cat[f.category] = by_cat.get(f.category, 0) + 1
    cfg = repo.config
    approved = sum(1 for c in review_comments(db, review) if c.state == "approved")
    owner = repo_role(db, user, repo.id) == "owner"
    blocker = publish_blocker(review_status=review.status, is_demo=review.is_demo or pr.is_demo, repo_enabled=repo.is_enabled, pr_state=pr.state,
                              pr_head=pr.head_sha, review_head=review.head_sha, app_configured=s.github_app_configured)
    out = [FindingOut(id=f.id, category=f.category, severity=f.severity, title=f.title, explanation=f.explanation, evidence=f.evidence, path=f.path,
                      start_line=f.start_line, end_line=f.end_line, remediation=f.remediation, patch=f.patch, confidence=f.confidence,
                      confidence_label=confidence_label(f.confidence), inline_possible=f.inline_possible, status=f.status,
                      comment=CommentOut(id=f.comment.id, state=f.comment.state, body=f.comment.body, edited=f.comment.edited) if f.comment else None)
           for f in findings]
    return ReviewDetail(**_item(brief, pr, repo), summary=review.summary, model=review.model, by_category=by_cat, findings_list=out,
                        require_approval=cfg.require_approval if cfg else True, auto_publish=cfg.auto_publish if cfg else False,
                        can_retry=review.status in ("failed", "cancelled") and not review.is_demo, can_manage=owner and not review.is_demo,
                        approved_comments=approved, publishable=owner and blocker is None and approved > 0, publish_blocker=blocker)


@router.post("/{review_id}/retry", response_model=ReviewListItem, status_code=202)
def retry_review(review_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    review, pr, repo = get_review_for_user(db, user, review_id)
    if review.is_demo:
        raise BadRequest("Demo reviews are sample data and cannot be retried.", code="demo_readonly")
    if review.status not in ("failed", "cancelled"):
        raise BadRequest("Only failed or cancelled reviews can be retried.", code="not_retryable")
    if not repo.is_enabled:
        raise BadRequest("Connect this repository before retrying.", code="repository_not_connected")
    review.status, review.error, review.finished_at = "queued", None, None
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.dedup_key == f"review:{review.dedup_key}"))
    requeued = False
    if job is not None:
        db.flush()
        requeued = job_queue.requeue(db, job.id)  # resets attempts; commits
    if not requeued:  # old job missing or already 'succeeded': never leave a queued review without a job
        job_queue.enqueue(db, "review", {"review_id": review.id}, f"review:{review.dedup_key}:retry:{uuid.uuid4().hex[:8]}")
    db.add(AuditLog(user_id=user.id, action="review.retry", target_type="review", target_id=str(review.id), meta={"at": utcnow().isoformat()}))
    db.commit()
    return ReviewListItem(**_item(review_briefs(db, [review])[review.id], pr, repo))
